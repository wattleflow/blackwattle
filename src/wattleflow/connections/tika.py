# Module name: connections/tika.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# Dependency:
#   pip install tika
#   a Java 11+ runtime (local mode only)
#
# Two modes, one handle:
#
#   mode: local   the connection validates Java, validates the configured JAR
#                 and stages it where tika-python launches it, then lets
#                 tika-python bring the server up on localhost. Nothing is
#                 downloaded from Maven.
#
#   mode: server  the connection talks to an endpoint that is ALREADY running
#                 (a container, a shared host). tika-python is put in
#                 client-only mode so it never tries to start one of its own,
#                 and an unreachable endpoint is a construction failure — a
#                 declared server that is down must not silently become a
#                 local server.
#
# WHY tika is NOT imported at module level (unlike the sibling connections):
# tika-python reads its whole configuration from the environment AT IMPORT TIME
# and freezes it into module globals and default arguments. Importing it here
# would fix the mode before any configuration is known. It is imported inside
# ``create_connection`` once the environment is set, and the globals that decide
# behaviour are then asserted directly — an earlier import by another component
# must not decide this connection's mode.
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import hashlib
import os
import re
import shutil
import socket
import subprocess
import tempfile
from abc import ABC, abstractmethod
from contextlib import contextmanager
from pathlib import Path
from typing import Any, ClassVar, Generator, Optional, Tuple
from urllib.parse import urlparse, urlunparse
from urllib.request import urlopen
from wattleflow.concrete.connection import (
    Connection,
    ConnectionAction,
    ConnectionState,
    GenericConnection,
)
from wattleflow.concrete.exception import ConnectionException
from wattleflow.enums.event import Event
from wattleflow.decorators.oscal import oscal_connection
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #
# Three distinct failures, so a JAR/path problem, a Java problem and an
# endpoint problem are told apart at a glance instead of arriving as one opaque
# server-startup error.


class TikaConnectionError(ConnectionException):
    """The Tika endpoint is unusable, or the requested mode is not valid."""


class TikaServerJarError(TikaConnectionError):
    """The configured Tika server JAR is missing, unreadable or not a JAR."""


class TikaJavaError(TikaConnectionError):
    """No suitable Java runtime is available to launch the Tika server."""


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Local runtime                                                        #
# --------------------------------------------------------------------------- #


class TikaRuntime:
    """Validation and staging of a LOCAL Apache Tika runtime.

    tika-python always launches ``$TIKA_PATH/tika-server.jar`` and checks it
    against an ``.md5`` sidecar; on a mismatch it deletes the file and fetches a
    replacement from Maven. Staging the configured JAR under that exact name
    with a matching checksum is what keeps the whole flow offline.

    Every entry point takes ``caller`` so a failure carries the identity of the
    component that asked for it, not of this helper.
    """

    JAR_NAME: ClassVar[str] = "tika-server.jar"
    STAGING_DIR: ClassVar[str] = "wattleflow-tika"
    MIN_JAVA_MAJOR: ClassVar[int] = 11
    JAVA_TIMEOUT: ClassVar[int] = 15
    READ_CHUNK: ClassVar[int] = 1 << 20
    # Handles both the legacy 1.x scheme (`1.8.0_381` -> 8) and the modern one.
    VERSION_PATTERN: ClassVar[str] = r'version "(\d+)(?:\.(\d+))?'

    @classmethod
    def server_jar(cls, caller: Any, configured: Optional[str]) -> Path:
        """The configured JAR as a validated local path."""
        raw = str(configured or os.environ.get("TIKA_SERVER_JAR", "")).strip()
        if not raw:
            raise TikaServerJarError(
                caller,
                "server_jar is not configured. Set the connection's 'server_jar' key "
                "(or TIKA_SERVER_JAR) to an absolute path to the Tika server JAR, so "
                "the library never downloads one from Maven.",
            )
        # A URL would make tika fetch the JAR over the network at runtime.
        if "://" in raw:
            raise TikaServerJarError(
                caller,
                f"server_jar is a remote URL ({raw!r}); a local JAR path is required.",
            )
        jar = Path(raw).expanduser()
        if not jar.exists():
            raise TikaServerJarError(caller, f"Tika server JAR not found: {jar}")
        if not jar.is_file():
            raise TikaServerJarError(caller, f"Tika server JAR is not a file: {jar}")
        if jar.suffix.lower() != ".jar":
            raise TikaServerJarError(caller, f"Tika server JAR is not a .jar file: {jar}")
        if not os.access(jar, os.R_OK):
            raise TikaServerJarError(caller, f"Tika server JAR is not readable: {jar}")
        return jar

    @classmethod
    def java(cls, caller: Any, java_home: Optional[str]) -> str:
        """Path to the Java executable that will run the server."""
        home = str(java_home or os.environ.get("JAVA_HOME", "")).strip()
        if home:
            candidate = Path(home).expanduser() / "bin" / "java"
            if not candidate.exists():
                raise TikaJavaError(
                    caller,
                    f"java_home is {home!r} but {candidate} does not exist.",
                )
            return str(candidate)

        found = shutil.which("java")
        if found is None:
            raise TikaJavaError(
                caller,
                "No Java runtime found: java_home is unset and 'java' is not on PATH. "
                f"The Tika server requires Java {cls.MIN_JAVA_MAJOR} or newer.",
            )
        return found

    @classmethod
    def java_major(cls, caller: Any, java_bin: str) -> int:
        """Major version of ``java_bin``, refusing anything below the minimum."""
        try:
            proc = subprocess.run(
                [java_bin, "-version"],
                capture_output=True,
                text=True,
                timeout=cls.JAVA_TIMEOUT,
            )
        except (OSError, subprocess.SubprocessError) as e:
            raise TikaJavaError(caller, f"Failed to run {java_bin!r}: {e}", exc=e) from e

        # `java -version` writes to stderr on virtually every JDK.
        output = f"{proc.stderr or ''}{proc.stdout or ''}".strip()
        if proc.returncode != 0:
            raise TikaJavaError(
                caller,
                f"{java_bin!r} -version exited with {proc.returncode}: {output!r}",
            )

        major = cls._major_from(output)
        if major is None:
            raise TikaJavaError(
                caller,
                f"Could not parse Java version from {java_bin!r}: {output!r}",
            )
        if major < cls.MIN_JAVA_MAJOR:
            raise TikaJavaError(
                caller,
                f"Tika server requires Java {cls.MIN_JAVA_MAJOR}+, but {java_bin!r} "
                f"reports Java {major}.",
            )
        return major

    @classmethod
    def staging_dir(cls, caller: Any, configured: Optional[str]) -> Path:
        """Directory tika-python launches the server from."""
        raw = str(configured or os.environ.get("TIKA_PATH", "")).strip()
        target = Path(raw).expanduser() if raw else Path(tempfile.gettempdir()) / cls.STAGING_DIR
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise TikaServerJarError(
                caller,
                f"Cannot create Tika runtime directory {target}: {e}",
                exc=e,
            ) from e
        return target

    @classmethod
    def stage(cls, caller: Any, jar: Path, runtime_dir: Path) -> Path:
        """Place ``jar`` under the launch name with a matching checksum sidecar."""
        target = runtime_dir / cls.JAR_NAME
        sidecar = Path(f"{target}.md5")

        staged = False
        if not cls._same_jar(target, jar):
            try:
                if target.exists() or target.is_symlink():
                    target.unlink()
                try:
                    target.symlink_to(jar)
                except OSError:
                    # Symlinks may be unavailable (some Windows/WSL mounts).
                    shutil.copy2(jar, target)
            except OSError as e:
                raise TikaServerJarError(
                    caller,
                    f"Cannot stage Tika JAR into {target}: {e}",
                    exc=e,
                ) from e
            staged = True

        if staged or not sidecar.exists():
            try:
                sidecar.write_text(cls.md5(jar))
            except OSError as e:
                raise TikaServerJarError(
                    caller,
                    f"Cannot write checksum {sidecar}: {e}",
                    exc=e,
                ) from e
        return target

    @classmethod
    def md5(cls, path: Path) -> str:
        digest = hashlib.md5()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(cls.READ_CHUNK), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def _major_from(cls, version_output: str) -> Optional[int]:
        match = re.search(cls.VERSION_PATTERN, version_output)
        if not match:
            return None
        major = int(match.group(1))
        if major == 1 and match.group(2):
            major = int(match.group(2))
        return major

    @staticmethod
    def _same_jar(target: Path, jar: Path) -> bool:
        try:
            if target.is_symlink():
                return target.resolve() == jar.resolve()
            return target.exists() and target.stat().st_size == jar.stat().st_size
        except OSError:
            return False


# --------------------------------------------------------------------------- #
# endregion Local runtime                                                     #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Client                                                               #
# --------------------------------------------------------------------------- #


class TikaClient:
    """Handle bound to one resolved Tika endpoint, yielded by ``connect()``.

    Wraps ``tika.parser`` and exposes ITS model unchanged: both calls return
    Tika's own ``{'status', 'content', 'metadata'}`` mapping. Deciding what to
    ask for, and what to do with the answer, belongs to the caller.
    """

    __slots__ = ("_parser", "_endpoint", "_request_options")

    def __init__(self, parser: Any, endpoint: str, request_options: dict) -> None:
        self._parser = parser
        self._endpoint = endpoint
        self._request_options = dict(request_options)

    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def request_options(self) -> dict:
        return dict(self._request_options)

    def from_file(
        self,
        path: str | Path,
        *,
        service: str = "all",
        headers: Optional[dict] = None,
    ) -> dict:
        """Parse a file on disk. ``service``: 'all' | 'text' | 'meta'."""
        return self._parser.from_file(
            str(Path(path).absolute()),
            serverEndpoint=self._endpoint,
            service=service,
            headers=headers,
            requestOptions=self.request_options,
        )

    def from_buffer(self, data: Any, *, headers: Optional[dict] = None) -> dict:
        """Parse an in-memory buffer."""
        return self._parser.from_buffer(
            data,
            serverEndpoint=self._endpoint,
            headers=headers,
            requestOptions=self.request_options,
        )

    def __repr__(self) -> str:
        return f"TikaClient[{self._endpoint}]"


# --------------------------------------------------------------------------- #
# endregion Client                                                            #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Connections                                                          #
# --------------------------------------------------------------------------- #
# Two classes rather than one with a `mode:` switch, for three reasons:
#   1. each configuration contract is then exact — a local-only key on a server
#      connection is refused by the preset gate instead of silently dropped;
#   2. it is the house idiom for one protocol in two roles (KafkaProducer /
#      KafkaConsumer);
#   3. only the local class can own a server process, so the server class
#      physically cannot stop somebody else's Tika.
# The modes are not interchangeable at run time — a declared server that is
# down must fail, never fall back — so the choice is a type, not a flag.


class TikaConnection(GenericConnection, ABC):
    """What both Tika connections share: the client handle, the endpoint probe
    and the lifecycle. A subclass says only how the endpoint comes to exist."""

    ALLOWED = [
        "connection_name",
        "lazy_loading",
        "timeout",
        "probe_timeout",
    ]
    # OSCAL: local path / endpoint validation (ac-3) and an HTTP endpoint the
    # payload travels over (sc-8). No credentials are held here, hence no ia-5.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ("ac-3", "sc-8")

    #: Human-readable label for audit records; not a configuration key.
    MODE: ClassVar[str] = "?"
    SCHEMES: ClassVar[Tuple[str, ...]] = ("http", "https")
    # tika-python defaults the read timeout to 60s; a scanned PDF the server has
    # to OCR routinely exceeds that.
    DEFAULT_TIMEOUT: ClassVar[int] = 300
    DEFAULT_PROBE_TIMEOUT: ClassVar[int] = 5
    # Tika server reports its own version here; the cheapest liveness question.
    PROBE_PATH: ClassVar[str] = "/version"

    # ---------------------------------------------------------------------- #
    # region Configuration
    # ---------------------------------------------------------------------- #

    def _request_options(self) -> dict:
        timeout = self.timeout
        return {"timeout": int(timeout) if timeout else self.DEFAULT_TIMEOUT}

    def _probe_timeout(self) -> int:
        return int(self.probe_timeout or self.DEFAULT_PROBE_TIMEOUT)

    @staticmethod
    def _redacted(endpoint: str) -> str:
        """``endpoint`` without any userinfo, safe to put in an audit record."""
        parsed = urlparse(endpoint)
        if not parsed.username and not parsed.password:
            return endpoint
        host = parsed.hostname or ""
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return urlunparse(parsed._replace(netloc=host))

    # endregion Configuration

    # ---------------------------------------------------------------------- #
    # region Runtime
    # ---------------------------------------------------------------------- #

    def _apply_environment(self, **settings: Optional[str]) -> None:
        """Set the variables tika-python reads at import time; drop the empty."""
        for key, value in settings.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = str(value)

    def _load_tika(self, client_only: bool) -> Any:
        """Import tika and assert the global that decides how it behaves.

        The environment is only honoured on tika's FIRST import anywhere in the
        process. Another component may already have imported it under different
        settings, so the global this connection depends on is written directly —
        otherwise the mode would be decided by import order.
        """
        try:
            from tika import parser as tika_parser
            from tika import tika as tika_runtime
        except ImportError as e:
            raise TikaConnectionError(
                caller=self,
                error=(
                    f"Missing required package to run this code: [{__file__}].\n"
                    "Please install it using:\n\tpip install tika"
                ),
                exc=e,
            ) from e

        tika_runtime.TikaClientOnly = client_only
        self._runtime = tika_runtime
        return tika_parser

    def _reachable(self, endpoint: str, timeout: int) -> bool:
        """Whether the endpoint answers. Never raises: the caller decides."""
        try:
            with urlopen(f"{endpoint}{self.PROBE_PATH}", timeout=timeout) as response:
                return 200 <= int(response.status) < 300
        except Exception as e:
            self.debug(
                msg=Event.Probe.name,
                step=Event.Failed.name,
                endpoint=self._redacted(endpoint),
                error=str(e),
            )
            return False

    def _listening(self, endpoint: str, timeout: int) -> bool:
        """Whether something already holds the endpoint's port."""
        parsed = urlparse(endpoint)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            with socket.create_connection((parsed.hostname, port), timeout=timeout):
                return True
        except OSError:
            return False

    # endregion Runtime

    # ---------------------------------------------------------------------- #
    # region Lifecycle
    # ---------------------------------------------------------------------- #

    @abstractmethod
    def _establish(self) -> None:
        """Resolve the endpoint and load tika, setting `_engine` and `_endpoint`.

        Called by `create_connection`; do not manage FSM state here.
        """
        ...

    def create_connection(self) -> None:
        self.debug(
            msg=Event.Create.name,
            step=Event.Started.name,
            name=self.connection_name,
            mode=self.MODE,
            state=self.state.value,
        )

        if self.state in (
            ConnectionState.CREATED,
            ConnectionState.CONNECTED,
            ConnectionState.CONNECTING,
        ):
            self.debug(
                msg=Event.Create.name,
                step=Event.Check.name,
                reason="connection already created",
                state=self.state.value,
            )
            return

        if self.state is ConnectionState.FAILED:
            raise TikaConnectionError(
                caller=self,
                error=f"Cannot create connection in state '{self.state.value}'",
            )

        self._runtime: Any = None
        self._endpoint: Optional[str] = None

        try:
            self._establish()
        except TikaConnectionError:
            raise
        except Exception as e:
            self.notify(
                self,
                error=f"Tika connection cannot be created: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=str(e))
            raise TikaConnectionError(
                caller=self,
                error=f"Tika connection cannot be created: {e}",
                exc=e,
            ) from e

        # DEBUG, not INFO: a connection runs inside another component's unit of
        # work, so a record of its own would scale with the input rather than
        # with the job (NFRQ-OBS-03 §1).
        self.debug(
            msg=Event.Create.name,
            step=Event.Completed.name,
            name=self.connection_name,
            mode=self.MODE,
            endpoint=self._redacted(self._endpoint),
            timeout=self._request_options()["timeout"],
        )

    @contextmanager
    def connect(self) -> Generator[Connection, None, None]:
        self._ensure_created()

        if self.state is not ConnectionState.CREATED:
            raise TikaConnectionError(
                caller=self,
                error=f"Cannot connect in state '{self.state.value}'",
            )

        if self._engine is None:
            raise TikaConnectionError(caller=self, error=f"{self.name}.connect: engine is None")

        self._fsm.apply(ConnectionAction.CONNECT)
        try:
            self._connection = TikaClient(
                self._engine,
                self._endpoint,
                self._request_options(),
            )
            self._fsm.apply(ConnectionAction.CONNECT_OK)
        except Exception as e:
            self._fsm.apply(ConnectionAction.CONNECT_FAIL)
            self.debug(msg=Event.Connect.name, step=Event.Failed.name, error=str(e))
            raise TikaConnectionError(caller=self, error=str(e), exc=e) from e

        try:
            yield self._connection
        finally:
            self._connection = None
            self._fsm.apply(ConnectionAction.DISCONNECT)

    def disconnect(self) -> None:
        self._connection = None
        self._engine = None
        self._runtime = None
        self.debug(
            msg=Event.Disconnected.name,
            connection_name=self.connection_name,
            mode=self.MODE,
            state=self.state.value,
        )

    # endregion Lifecycle

    # ---------------------------------------------------------------------- #
    # region Public
    # ---------------------------------------------------------------------- #

    @property
    def endpoint_url(self) -> Optional[str]:
        """Where this connection reaches Tika, once created."""
        return getattr(self, "_endpoint", None)

    def ping(self) -> bool:
        """Whether the server answers now."""
        self._ensure_created()
        endpoint = self.endpoint_url
        if not endpoint:
            return False
        return self._reachable(endpoint, self._probe_timeout())

    # endregion Public

    def __repr__(self) -> str:
        endpoint = self.endpoint_url
        return (
            f"{self.name}:{self.state.value}"
            f"[mode={self.MODE}, "
            f"endpoint={self._redacted(endpoint) if endpoint else '?'}]"
        )


@oscal_connection(strict=False)
class TikaServerConnection(TikaConnection):
    """Client of a Tika server that is ALREADY running — a container, a shared
    host. tika-python is put in client-only mode so it never starts one of its
    own, and an unreachable endpoint is a construction failure: a declared
    server that is down must not silently become a local server."""

    ALLOWED = ["endpoint", "probe"]
    MODE: ClassVar[str] = "server"

    def _resolve_endpoint(self) -> str:
        """The configured endpoint, normalised and refused if it is not usable."""
        raw = str(self.endpoint or "").strip().rstrip("/")
        if not raw:
            raise TikaConnectionError(
                caller=self,
                error=f"{type(self).__name__} requires 'endpoint' (e.g. http://tika:9998).",
            )
        parsed = urlparse(raw)
        if parsed.scheme not in self.SCHEMES:
            raise TikaConnectionError(
                caller=self,
                error=(
                    f"endpoint scheme must be one of {self.SCHEMES}, got "
                    f"{parsed.scheme or '<none>'!r} in {raw!r}"
                ),
            )
        if not parsed.hostname:
            raise TikaConnectionError(caller=self, error=f"endpoint has no host: {raw!r}")
        return raw

    def _establish(self) -> None:
        endpoint = self._resolve_endpoint()

        # Written before the import so a first import in this process already
        # sees them; asserted again on the module in _load_tika.
        self._apply_environment(
            TIKA_CLIENT_ONLY="True",
            TIKA_SERVER_ENDPOINT=endpoint,
        )
        self._engine = self._load_tika(client_only=True)
        self._endpoint = endpoint

        if self.probe is False:
            self.warning(
                msg=Event.Probe.name,
                step=Event.Check.name,
                reason="endpoint not probed; probe is disabled",
                endpoint=self._redacted(endpoint),
            )
            return

        timeout = self._probe_timeout()
        if not self._reachable(endpoint, timeout):
            raise TikaConnectionError(
                caller=self,
                error=(
                    f"Tika server at {self._redacted(endpoint)} did not answer "
                    f"{self.PROBE_PATH} within {timeout}s. This connection never starts "
                    "a server; use TikaLocalConnection for that."
                ),
            )


@oscal_connection(strict=False)
class TikaLocalConnection(TikaConnection):
    """Provisions a Tika server on localhost and is then its client: validates
    Java, validates the configured JAR and stages it where tika-python launches
    it, so nothing is downloaded from Maven.

    A server this connection started is stopped on teardown; one that was
    already listening belongs to whoever started it and is left alone."""

    ALLOWED = [
        "server_jar",
        "java_home",
        "tika_path",
        "log_path",
        "startup_sleep",
        "startup_max_retry",
    ]
    MODE: ClassVar[str] = "local"

    def _establish(self) -> None:
        self._java_bin: Optional[str] = None
        self._owns_server: bool = False

        jar = TikaRuntime.server_jar(self, self.server_jar)
        self._java_bin = TikaRuntime.java(self, self.java_home)
        java_major = TikaRuntime.java_major(self, self._java_bin)

        runtime_dir = TikaRuntime.staging_dir(self, self.tika_path)
        staged = TikaRuntime.stage(self, jar, runtime_dir)

        self._apply_environment(
            TIKA_CLIENT_ONLY=None,
            TIKA_PATH=str(runtime_dir),
            TIKA_SERVER_JAR=str(jar),
            TIKA_JAVA=self._java_bin,
            TIKA_LOG_PATH=str(self.log_path) if self.log_path else None,
        )
        self._engine = self._load_tika(client_only=False)

        # The launch path and the JVM are decided by module globals, not only by
        # the environment, so they are written after the import as well.
        self._runtime.TikaJarPath = str(staged.parent)
        self._runtime.TikaJava = self._java_bin
        if self.startup_sleep is not None:
            self._runtime.TikaStartupSleep = float(self.startup_sleep)
        if self.startup_max_retry is not None:
            self._runtime.TikaStartupMaxRetry = int(self.startup_max_retry)

        # tika builds the local endpoint from its own host/port globals; taking
        # it from there keeps one source of truth for where the server lands.
        self._endpoint = f"http://{self._runtime.ServerHost}:{self._runtime.Port}"

        # Read before anything is started: a server already on the port is not
        # ours to stop later.
        already = self._listening(self._endpoint, self._probe_timeout())
        self._owns_server = not already

        self.debug(
            msg=Event.Load.name,
            step=Event.Completed.name,
            component="tika",
            scope="preflight",
            java=self._java_bin,
            java_major=java_major,
            server_jar=str(jar),
            staged_jar=str(staged),
            tika_path=str(runtime_dir),
            already_running=already,
            owns_server=self._owns_server,
        )

    def disconnect(self) -> None:
        # Close only what this connection opened: a Tika server that was already
        # listening when the connection was created belongs to whoever started
        # it, and killing it would take out every other client on the host.
        runtime = getattr(self, "_runtime", None)
        owns = getattr(self, "_owns_server", False)
        try:
            if runtime is not None and owns and getattr(runtime, "TikaServerProcess", False):
                try:
                    runtime.killServer()
                    self.debug(
                        msg=Event.Close.name,
                        step=Event.Completed.name,
                        component="tika",
                        scope="server",
                    )
                except Exception as e:
                    self.warning(
                        msg=Event.Close.name,
                        step=Event.Failed.name,
                        reason="local Tika server not stopped",
                        error=str(e),
                    )
        finally:
            self._owns_server = False
            super().disconnect()

    @property
    def owns_server(self) -> bool:
        """Whether this connection started the server it talks to."""
        return getattr(self, "_owns_server", False)


# --------------------------------------------------------------------------- #
# endregion Connections                                                       #
# --------------------------------------------------------------------------- #


__all__ = [
    "TikaClient",
    "TikaConnection",
    "TikaConnectionError",
    "TikaJavaError",
    "TikaLocalConnection",
    "TikaRuntime",
    "TikaServerConnection",
    "TikaServerJarError",
]
