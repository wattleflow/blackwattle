# Module name: processors/ocr.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# IMPORTANT: This processor requires the `tika` library and a Java 11+ runtime. #
#       pip install tika                                                       #
# --------------------------------------------------------------------------- #
# The Apache Tika server JAR is configured at the WORKFLOW level via the
# `runtime` block, which WorkflowFactory exports as environment variables BEFORE
# any processor runs:
#
#   runtime:
#     tika_server_jar: /opt/tika/tika-server-standard-3.1.0.jar  # -> TIKA_SERVER_JAR
#     java_home: /usr/lib/jvm/java-17-openjdk                     # -> JAVA_HOME
#
# OCRTextProcessor validates that JAR path and the Java runtime up front and
# stages the JAR where tika expects it, so the library never silently downloads
# the server JAR from Maven at runtime.
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from traceback import format_exc
from typing import Any, Generator
from wattleflow.core import ITarget
from wattleflow.concrete import GenericProcessor
from wattleflow.concrete.exception import ProcessorException
from wattleflow.enums.event import Event
from wattleflow.helpers.files import FileScanner
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #
# tika-python defaults the client read timeout to 60s; large or scanned PDFs
# (server-side OCR) routinely exceed that. Callers may override per-processor via
# the `tika_timeout` configuration key.
TIKA_DEFAULT_TIMEOUT = 300
# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #
# Two distinct failures so a developer can tell a JAR/path problem from a Java
# runtime problem (e.g. missing or too-old JDK) at a glance.


class TikaServerJarError(ProcessorException):
    """The configured Tika server JAR is missing, unreadable or not a JAR."""


class TikaJavaError(ProcessorException):
    """No suitable Java runtime is available to launch the Tika server."""


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #


class OCRPreflightMixin:
    """Validate + stage a LOCAL Tika server JAR and the Java runtime so tika-python
    uses the configured JAR instead of downloading one from Maven. Shared by every
    processor that drives Apache Tika; callers import tika ONLY after
    ``_ensure_tika_ready()`` so the local JAR and paths are already staged."""

    # Apache Tika 3.x server requires Java 11 or newer.
    _MIN_JAVA_MAJOR = 11

    def _request_timeout(self) -> int:
        # Optional `tika_timeout` config key; falls back to the package default.
        configured = getattr(self, "tika_timeout", None)
        return int(configured) if configured else TIKA_DEFAULT_TIMEOUT

    def _ensure_tika_ready(self) -> Path:
        """Validate the Tika server JAR path and Java runtime, then stage the JAR.

        Returns the staged JAR path. Raises `TikaServerJarError` for path problems
        and `TikaJavaError` for Java problems, so failures carry a precise reason
        instead of an opaque Maven download or server-startup error.
        """
        jar = self._resolve_server_jar()
        self.debug(
            msg=Event.Check.name,
            component="tika",
            scope="preflight",
            step=Event.Started.name,
            tika_server_jar=str(jar),
        )

        java_bin = self._resolve_java()
        java_major = self._check_java_version(java_bin)
        self.debug(
            msg=Event.Check.name,
            component="tika",
            scope="preflight",
            java=java_bin,
            java_major=java_major,
        )

        staged = self._stage_server_jar(jar)
        self.debug(
            msg=Event.Check.name,
            component="tika",
            scope="preflight",
            step=Event.Completed.name,
            loaded=True,
            tika_server_jar=str(jar),
            staged_jar=str(staged),
            tika_path=os.environ.get("TIKA_PATH"),
        )
        return staged

    def _resolve_server_jar(self) -> Path:
        raw = os.environ.get("TIKA_SERVER_JAR", "").strip()
        if not raw:
            raise TikaServerJarError(
                self,
                "TIKA_SERVER_JAR is not set. Configure the workflow 'runtime.tika_server_jar' "
                "key with an absolute path to the Tika server JAR to avoid a Maven download.",
            )
        # A URL would make tika fetch the JAR over the network; require a local file.
        if "://" in raw:
            raise TikaServerJarError(
                self,
                f"TIKA_SERVER_JAR is a remote URL ({raw!r}); a local JAR path is required "
                "to avoid runtime downloads.",
            )
        jar = Path(raw).expanduser()
        if not jar.exists():
            raise TikaServerJarError(self, f"Tika server JAR not found: {jar}")
        if not jar.is_file():
            raise TikaServerJarError(self, f"Tika server JAR is not a file: {jar}")
        if jar.suffix.lower() != ".jar":
            raise TikaServerJarError(self, f"Tika server JAR is not a .jar file: {jar}")
        if not os.access(jar, os.R_OK):
            raise TikaServerJarError(self, f"Tika server JAR is not readable: {jar}")
        return jar

    def _resolve_java(self) -> str:
        java_home = os.environ.get("JAVA_HOME", "").strip()
        if java_home:
            candidate = Path(java_home) / "bin" / "java"
            if not candidate.exists():
                raise TikaJavaError(
                    self,
                    f"JAVA_HOME is set to {java_home!r} but {candidate} does not exist.",
                )
            return str(candidate)
        java_bin = shutil.which("java")
        if java_bin is None:
            raise TikaJavaError(
                self,
                "No Java runtime found: JAVA_HOME is unset and 'java' is not on PATH. "
                f"The Tika server requires Java {self._MIN_JAVA_MAJOR} or newer.",
            )
        return java_bin

    def _check_java_version(self, java_bin: str) -> int:
        try:
            proc = subprocess.run(
                [java_bin, "-version"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError) as e:
            self.debug(msg=Event.Check.name, step=Event.Failed.name, error=str(e))
            raise TikaJavaError(self, f"Failed to run {java_bin!r}: {e}") from e

        # `java -version` writes to stderr on virtually every JDK.
        output = f"{proc.stderr or ''}{proc.stdout or ''}".strip()
        if proc.returncode != 0:
            raise TikaJavaError(
                self, f"{java_bin!r} -version exited with {proc.returncode}: {output!r}"
            )
        major = self._parse_java_major(output)
        if major is None:
            raise TikaJavaError(self, f"Could not parse Java version from {java_bin!r}: {output!r}")
        if major < self._MIN_JAVA_MAJOR:
            raise TikaJavaError(
                self,
                f"Tika server requires Java {self._MIN_JAVA_MAJOR}+, but {java_bin!r} "
                f"reports Java {major}.",
            )
        return major

    def _stage_server_jar(self, jar: Path) -> Path:
        """Place the configured JAR where tika launches it and add a matching .md5.

        tika-python always runs `$TIKA_PATH/tika-server.jar` and validates it against
        a `.md5` sidecar; on mismatch it deletes the file and re-downloads from Maven.
        Staging the configured JAR under that exact name with a correct checksum keeps
        the whole flow offline.
        """
        base = os.environ.get("TIKA_PATH", "").strip()
        if base:
            runtime_dir = Path(base).expanduser()
        else:
            runtime_dir = Path(tempfile.gettempdir()) / "wattleflow-tika"
        try:
            runtime_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.debug(msg=Event.Check.name, step=Event.Failed.name, error=str(e))
            raise TikaServerJarError(
                self, f"Cannot create Tika runtime directory {runtime_dir}: {e}"
            ) from e

        target = runtime_dir / "tika-server.jar"
        md5_path = Path(f"{target}.md5")

        staged = False
        if not self._same_jar(target, jar):
            try:
                if target.exists() or target.is_symlink():
                    target.unlink()
                try:
                    target.symlink_to(jar)
                except OSError:
                    # Symlinks may be unavailable (some Windows/WSL mounts); fall back.
                    shutil.copy2(jar, target)
            except OSError as e:
                self.debug(msg=Event.Check.name, step=Event.Failed.name, error=str(e))
                raise TikaServerJarError(self, f"Cannot stage Tika JAR into {target}: {e}") from e
            staged = True

        if staged or not md5_path.exists():
            try:
                md5_path.write_text(self._md5_hex(jar))
            except OSError as e:
                self.debug(msg=Event.Check.name, step=Event.Failed.name, error=str(e))
                raise TikaServerJarError(self, f"Cannot write checksum {md5_path}: {e}") from e

        os.environ["TIKA_PATH"] = str(runtime_dir)
        return target

    @staticmethod
    def _parse_java_major(version_output: str) -> int | None:
        # Handles both the legacy 1.x scheme (`1.8.0_381` -> 8) and the modern
        # scheme (`17.0.9` -> 17).
        match = re.search(r'version "(\d+)(?:\.(\d+))?', version_output)
        if not match:
            return None
        major = int(match.group(1))
        if major == 1 and match.group(2):
            major = int(match.group(2))
        return major

    @staticmethod
    def _md5_hex(path: Path) -> str:
        digest = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _same_jar(target: Path, jar: Path) -> bool:
        try:
            if target.is_symlink():
                return target.resolve() == jar.resolve()
            return target.exists() and target.stat().st_size == jar.stat().st_size
        except OSError:
            return False


# --------------------------------------------------------------------------- #
# region Processors                                                           #
# --------------------------------------------------------------------------- #
# OCRTextProcessor extends GenericProcessor and implements create_generator
# using the Apache Tika parser to extract text content from each matched file.
# --------------------------------------------------------------------------- #


class OCRTextProcessor(OCRPreflightMixin, GenericProcessor):
    ALLOWED = [
        "driver",
        "filter",
        "ignore",
        "macros",
        "pattern",
        "repository_path",
        "recursive",
        "source_path",
        "tika_timeout",
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.debug(msg=Event.Constructor.name, step=Event.Started.name)

    def create_generator(self) -> Generator[ITarget, None, None]:
        self.debug(msg=Event.Generate.name, step=Event.Started.name)

        try:
            # Validate the configured JAR + Java and stage the JAR BEFORE importing
            # tika. A bad path now raises a clear error instead of triggering a
            # Maven download.
            self._ensure_tika_ready()

            # Lazy import: tika reads TIKA_SERVER_JAR / TIKA_PATH at import time and
            # freezes them as default arguments. Importing here - after the runtime
            # env is applied and the JAR is staged - makes tika use the local JAR.
            from tika import parser as tika_parser

            if not Path(self.source_path).exists():
                raise FileNotFoundError(f"Source path not found: {self.source_path}")

            search_path = Path(self.source_path)
            filtered = re.compile(self.filter) if self.filter else None
            file_iter = FileScanner.scan(search_path, self.pattern, self.recursive)
            timeout = self._request_timeout()

            for filepath in file_iter:
                self.debug(msg=Event.Generate.name, scope="item", filename=str(filepath))
                try:
                    if filtered and filtered.findall(filepath.stem):
                        continue

                    parsed = tika_parser.from_file(
                        str(filepath.absolute()),
                        requestOptions={"timeout": timeout},
                    )
                    content: str = (parsed.get("content") or "").strip()

                    self.debug(
                        msg=Event.Generate.name,
                        scope="item",
                        filename=str(filepath),
                        size=len(content),
                    )

                    yield self.blackboard.create(
                        self,
                        filename=str(filepath.absolute()),
                        content=content,
                    )

                except Exception as e:
                    filename = str(filepath)
                    error = f"Error: {str(e)} with {filename!r}"
                    self.exception(
                        msg=Event.Generate.name,
                        step=Event.Failed.name,
                        error=error,
                        filename=str(filename),
                    )
                    continue
        except (TikaServerJarError, TikaJavaError):
            # Already precise (path vs Java) - surface as-is, do not re-wrap.
            raise
        except Exception as e:
            error = f"Error: {str(e)}"
            self.debug(
                msg=Event.Generate.name,
                step=Event.Failed.name,
                error=error,
            )
            raise ProcessorException(
                caller=self,
                error=error,
                exc=format_exc(),
            ) from e

        self.debug(msg=Event.Generate.name, step=Event.Completed.name)


# --------------------------------------------------------------------------- #
# endregion Processors                                                        #
# --------------------------------------------------------------------------- #
