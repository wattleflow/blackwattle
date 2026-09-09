# Module name: drivers/file_storage.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import hashlib
import os

from pathlib import Path, PurePosixPath
from typing import ClassVar, Optional
from urllib.parse import unquote, urlparse
from wattleflow.concrete import Wattleflow
from wattleflow.enums.event import Event
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Clasess                                                              #
# --------------------------------------------------------------------------- #


# Concrete value object: instantiated directly by the storage drivers, so it
# inherits the Wattleflow root (which carries AuditLogger and the `name`
# contract) rather than naming AuditLogger itself.
class FileStorage(Wattleflow):
    # region Sanitisation

    # A name reaching the filesystem has to survive POSIX and Windows alike:
    # separators, the control range, and the characters Windows refuses. The
    # policy lives here as class attributes so a driver can tighten it by
    # subclassing rather than by re-deriving names before the call.
    ILLEGAL: ClassVar[str] = '<>:"/\\|?*'
    FALLBACK: ClassVar[str] = "unnamed"
    MAX_LENGTH: ClassVar[int] = 120
    REPLACEMENT: ClassVar[str] = "_"
    RESERVED: ClassVar[frozenset] = frozenset({"", ".", ".."})
    URI_SCHEMES: ClassVar[tuple] = ("http", "https", "ftp", "ftps", "file", "s3")

    @classmethod
    def _scrub(cls, text: str) -> str:
        """Character policy shared by every name part.

        A reserved character is one the sender wrote, so it leaves a mark; a
        control character is a container artefact (OLE2 terminates its strings
        with NUL) and is dropped, because replacing it would rename the file.
        """
        return "".join(
            cls.REPLACEMENT if character in cls.ILLEGAL else character
            for character in str(text or "")
            if ord(character) >= 32 and character != "\x7f"
        )

    @classmethod
    def sanitise(cls, name: str) -> str:
        """Reduce `name` to one filesystem-safe path component.

        Percent-escapes are decoded first — a URI-derived name is otherwise
        stored verbatim as `Report%20Q1%2C%202021.xlsx`. Separators never
        survive: whatever comes back is a leaf, so it cannot climb out of the
        directory it was resolved against.
        """
        candidate = unquote(str(name)).strip()

        # One component only: take the leaf of either separator style.
        candidate = candidate.replace("\\", "/").rsplit("/", 1)[-1]

        candidate = cls._scrub(candidate)

        # Windows silently drops trailing dots and spaces; drop them here so the
        # name on disk is the name that was validated.
        candidate = candidate.strip(". ")

        if len(candidate) > cls.MAX_LENGTH:
            suffix = Path(candidate).suffix[: cls.MAX_LENGTH]
            candidate = candidate[: cls.MAX_LENGTH - len(suffix)].rstrip(". ") + suffix

        return cls.FALLBACK if candidate in cls.RESERVED else candidate

    @classmethod
    def sanitise_suffix(cls, suffix: str) -> str:
        """Filesystem-safe extension, leading dot included.

        A suffix reaches the disk as part of the name, so it answers to the
        same policy — `Path.with_suffix` validates only the leading dot, and a
        caller that split a hostile name keeps the hostile half here.
        """
        candidate = cls._scrub(str(suffix or "").strip()).rstrip(". ")

        if not candidate:
            return ""

        return candidate if candidate.startswith(".") else f".{candidate}"

    @classmethod
    def sanitise_uri(cls, uri: str) -> str:
        """Filesystem-safe leaf name the URI addresses.

        Only the path carries the name: `…/report.xlsx?token=abc` must not store
        its query string, and a credential in the URI must not reach the disk.
        A value with no recognised scheme is treated as a plain path — a Windows
        drive letter parses as a one-character scheme, so it never qualifies.
        """
        parsed = urlparse(str(uri))

        if parsed.scheme.lower() not in cls.URI_SCHEMES:
            return cls.sanitise(uri)

        return cls.sanitise(PurePosixPath(parsed.path).name)

    # endregion

    def __init__(
        self,
        local_path: str,
        uri: str,
        create: bool,
        normalised: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.debug(
            msg=Event.Constructor.name,
            step=Event.Started.name,
            local_path=local_path,
            uri=uri,
            create=create,
            normalised=normalised,
            kwargs=kwargs,
        )

        self._filename: Optional[Path] = None
        self._local_path: Path = Path(local_path).resolve()
        self._origin: Path = Path(uri)
        self._create: bool = create
        self._normalised: bool = normalised

        if not self._local_path.is_dir() and not create:
            raise FileNotFoundError(
                f"Path doesn't exist or is not a directory: {str(self._local_path)}"
            )

        if create and self._local_path.exists() is False:
            self._local_path.mkdir(parents=True, exist_ok=True)

        # `Path(uri).name` kept the percent-escaping and any query string; the
        # escape check below stays as defence in depth, not as the only gate.
        name = self.digest if normalised else self.sanitise_uri(uri)

        _candidate = self._local_path / name
        if not _candidate.resolve().is_relative_to(self._local_path):
            reason = f"Filename escapes local_path: {uri!r}"
            self.error(
                msg=Event.Constructor.name, step=Event.Completed.name, reason=reason, uri=uri
            )
            raise PermissionError(reason)

        self._filename = _candidate

    @property
    def digest(self) -> str:
        digest = hashlib.sha256(str(self.origin).encode()).hexdigest()[:16]
        suffix = Path(urlparse(str(self.origin)).path).suffix or ".bin"
        return f"{digest}{suffix}"

    @property
    def filename(self) -> Path:
        return self._filename

    @property
    def origin(self) -> Path:
        return self._origin

    @property
    def size(self) -> int:
        if self._filename.exists():
            return os.stat(self._filename.absolute()).st_size
        return 0

    @property
    def uri(self) -> str:
        return self.filename.as_uri()

    def with_suffix(self, suffix: str) -> Path:
        return self._filename.with_suffix(self.sanitise_suffix(suffix))

    def with_dir(self, directory=None, mkdir=True) -> Path:
        subdir = directory if directory else self._filename.stem
        out_dir = self._local_path.joinpath(subdir)
        if mkdir:
            out_dir.mkdir(parents=True, exist_ok=True)

        return out_dir.joinpath(self._filename.name)


# --------------------------------------------------------------------------- #
# endregion Clasess                                                           #
# --------------------------------------------------------------------------- #
