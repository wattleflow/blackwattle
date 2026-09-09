# Module name: drivers/local_storage.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import fnmatch
import os
import shutil
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from functools import singledispatchmethod
from pathlib import Path
from typing import Any, BinaryIO, Callable, Generator, Iterator, Optional, Union
from wattleflow.concrete import GenericDriver
from wattleflow.concrete.driver import DriverAction, DriverMetadata
from wattleflow.concrete.exception import AuditException, DriverException
from wattleflow.enums.event import Event
from wattleflow.enums.filetype import FileType
from wattleflow.drivers import FileStorage
from wattleflow.helpers.parsers.factory import ParserFactory
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class DriverLocalStorageException(DriverException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Classes                                                              #
# --------------------------------------------------------------------------- #


class DriverLocalStorage(GenericDriver):
    ALLOWED = [
        "atomic",
        "create",
        "current_path",
        "level",
        "normalised",
        "read_path",
        "write_path",
    ]

    DEFAULT_CHUNK_SIZE = 1024 * 1024  # 1 MiB — streaming copy granularity
    # Suffix of the file a write lands on before it becomes the target.
    PART_SUFFIX: str = ".part"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # The driver keeps the tally and says nothing: it runs inside another
        # component's unit of work, so an INFO of its own would scale with the
        # input rather than with the job (NFRQ-OBS-03).
        self._activity: dict[str, int] = {
            "read": 0,
            "written": 0,
            "copied": 0,
            "bytes": 0,
            "empty": 0,
        }
        self.ensure_live()

    @property
    def activity(self) -> dict[str, int]:
        """Operations this driver performed, and the bytes they moved."""
        return dict(self._activity)

    def _record(self, operation: str, size: int = 0) -> None:
        self._activity[operation] = self._activity.get(operation, 0) + 1
        if size:
            self._activity["bytes"] += int(size)
            return

        # A write of nothing still lands on disk, and a zero-byte file looks
        # exactly like a successful one. Counting it here means the end-of-run
        # tally says so even when the caller reported nothing.
        if operation in ("written", "copied"):
            self._activity["empty"] += 1
            self.warning(
                msg=Event.Write.name,
                step=Event.Check.name,
                reason="wrote an empty file",
                operation=operation,
            )

    def close(self) -> None:
        self.debug(msg=Event.Close.name, step=Event.Started.name)
        if not self.can(DriverAction.UNLOAD):
            return
        self.debug(msg=Event.Close.name, step=Event.Completed.name)

    def report(self) -> None:
        """State what this driver did, at INFO"""
        # Named, never splatted: a caller's key landing in the audit namespace
        # can silently become a control argument (NFRQ-OBS-02 §5).
        activity = self.activity
        self.info(
            msg=Event.Completed.name,
            write_path=str(self.write_path),
            read=activity.get("read", 0),
            written=activity.get("written", 0),
            copied=activity.get("copied", 0),
            empty=activity.get("empty", 0),
            bytes=activity.get("bytes", 0),
        )

    def metadata(self) -> DriverMetadata:
        return DriverMetadata(
            name=self.__class__.__name__,
            version="1.0",
            protocol="file",
            capabilities=["read", "write", "search"],
        )

    def load(self) -> None:
        self.debug(
            msg=Event.Load.name,
            step=Event.Started.name,
            read_path=self.read_path,
            write_path=self.write_path,
            normalised=self.normalised,
            create=self.create,
        )

        try:
            self.create = self.create or False
            self.normalised = self.normalised or False
            self.read_path = Path(self.read_path)
            self.write_path = Path(self.write_path)
            self.current_path: Path = self.write_path
        except Exception as e:
            reason = f"Invalid configuration: {str(e)}"
            self.debug(
                msg=Event.Load.name,
                step=Event.Failed.name,
                reason=reason,
                read_path=str(self.read_path),
                write_path=str(self.write_path),
                normalised=self.normalised,
                create=self.create,
            )
            raise DriverLocalStorageException(caller=self, error=reason) from e

        if not self.write_path.is_dir():
            if not self.create:
                reason = (
                    f"not a directory: {str(self.write_path)!r} "
                    "(pass create=True to have the driver make it)"
                )
                self.error(
                    msg=Event.Load.name,
                    reason=reason,
                    local_path=str(self.write_path),
                )
                raise DriverLocalStorageException(caller=self, error=reason)
            self.write_path.mkdir(parents=True, exist_ok=True)

        self.info(
            msg=Event.Load.name,
            step=Event.Completed.name,
            read_path=str(self.read_path),
            write_path=str(self.write_path),
            create=self.create,
            atomic=bool(self.atomic),
            normalised=self.normalised,
        )

    def _confined(self, uri: str) -> Path:
        """``uri`` resolved inside ``read_path``, or a refusal.

        The confinement is the driver's, not the parser's: a parser receives an
        open reader and never resolves a path (DR-COR-015). Subclasses that read
        by other means go through here for the same guard.
        """
        _uri = Path(uri).resolve()
        _base = Path(self.read_path).resolve()

        if not _uri.is_relative_to(_base):
            reason = f"Access denied: path outside base directory: {str(uri)!r}"
            self.error(msg=Event.Read.name, uri=uri, reason=reason)
            raise PermissionError(reason)
        return _uri

    def read(self, uri: str, **kwargs) -> Any:
        self.debug(msg=Event.Read.name, step=Event.Started.name, uri=uri, kwargs=kwargs)
        _uri = self._confined(uri)

        try:
            filetype = FileType.detect(str(_uri))
            self.debug(
                msg=Event.Read.name,
                step=Event.Completed.name,
                filetype=filetype.name,
                uri=_uri.as_uri(),
                kwargs=kwargs,
            )
            with open(_uri, "rb") as stream:
                parsed = ParserFactory.create(filetype).parse(stream=stream, **kwargs)
            self._record("read", _uri.stat().st_size)
            return parsed
        except AuditException as e:
            self.debug(
                msg=Event.Read.name,
                step=Event.Failed.name,
                uri=uri,
                error=e.reason,
            )
            raise DriverLocalStorageException(
                caller=self,
                error=e.reason,
                uri=uri,
            ) from e
        except Exception as e:
            self.debug(
                msg=Event.Read.name,
                step=Event.Failed.name,
                uri=uri,
                error=str(e),
            )
            raise DriverLocalStorageException(caller=self, error=str(e), uri=uri) from e

    def search(
        self, pattern: str, case_sensitive: bool = False, recursive: bool = False
    ) -> Generator[Path, None, None]:
        self.debug(
            msg=Event.Search.name,
            step=Event.Started.name,
            pattern=pattern,
            case_sensitive=case_sensitive,
            recursive=recursive,
        )
        if self.read_path is None:
            raise RuntimeError("search: read_path is not configured")

        search_path = Path(self.read_path).resolve()

        self.debug(
            msg=Event.Search.name,
            step=Event.Started.name,
            pattern=pattern,
            case_sensitive=case_sensitive,
            recursive=recursive,
            search_path=str(search_path),
        )

        iterator = search_path.rglob("*") if recursive else search_path.glob("*")

        for path in iterator:
            name = path.name
            if "*" in pattern or "?" in pattern or "[" in pattern:
                if case_sensitive:
                    if fnmatch.fnmatchcase(name, pattern):
                        yield path
                else:
                    if fnmatch.fnmatchcase(name.lower(), pattern.lower()):
                        yield path
            else:
                if case_sensitive:
                    if pattern in name:
                        yield path
                else:
                    if pattern.lower() in name.lower():
                        yield path

        self.debug(
            msg=Event.Search.name,
            step=Event.Completed.name,
        )

    # region private methods

    # ------------------------------------------------------------------ #
    # region Persistence primitives                                      #
    #                                                                    #
    # Format-agnostic save layer: a Formatter (in a write strategy)      #
    # produces the final str / bytes / stream and the driver only writes #
    # it to disk. Keeps formatting out of the driver so strategies stay  #
    # swappable. ``write`` is the format-agnostic, type-dispatched save. #
    # ------------------------------------------------------------------ #

    def _staged(self, target: Path) -> Path:
        """Same dir, so the rename that follows is a rename"""
        return target.with_name(f"{target.name}{self.PART_SUFFIX}-{os.getpid()}")

    def _commit(self, staged: Path, target: Path) -> None:
        """os.replace"""
        os.replace(staged, target)

    def _write_via(self, target: Path, write: Callable[[Path], None]) -> None:
        """
        Apply `write` to `target`, through a part-file when `atomic` is set.
        Direct writing truncates the target before the first byte is written, so
        an interrupted write leaves a file that looks written and is not.
        """
        if not self.atomic:
            write(target)
            return

        staged = self._staged(target)
        try:
            write(staged)
            self._commit(staged, target)
        except BaseException as e:
            # The target is untouched; the part-file is a debris.(NFRQ-OBS-01 §2).
            staged.unlink(missing_ok=True)
            self.debug(
                msg=Event.Write.name,
                step=Event.Failed.name,
                output=str(target),
                staged=str(staged),
                mode="atomic",
                error=str(e),
            )
            raise

    def _resolve_target(
        self,
        filename: str,
        suffix: Optional[str] = None,
        subdir: Optional[str] = None,
        mkdir: bool = False,
    ) -> Path:
        """Resolve the on-disk path for ``filename`` via FileStorage, honouring
        the driver's create/normalised policy and an optional subdir. ``subdir``
        is a PURE per-call parameter: it does NOT mutate driver state, so
        successive writes with different subdirs never interfere (no leak)."""
        local_dir = (
            self._subdir_path(subdir, mkdir) if subdir else Path(self.write_path)
        )
        storage = FileStorage(
            local_path=str(local_dir.resolve()),
            uri=filename,
            create=self.create,
            normalised=self.normalised,
        )
        return storage.with_suffix(suffix) if suffix else storage.filename

    # def target_path(
    #     self,
    #     filename: str,
    #     suffix: Optional[str] = None,
    #     subdir: Optional[str] = None,
    #     mkdir: bool = False,
    # ) -> str:
    #     return str(self._resolve_target(filename, suffix, subdir, mkdir).absolute())

    def save_text(
        self,
        filename: str,
        text: str,
        *,
        suffix: Optional[str] = None,
        encoding: str = "utf-8",
        subdir: Optional[str] = None,
        mkdir: bool = False,
    ) -> str:
        self.debug(
            msg=Event.Write.name,
            step=Event.Started.name,
            filename=filename,
            subdir=subdir,
            mkdir=mkdir,
            mode="text",
        )
        target = self._resolve_target(filename, suffix, subdir, mkdir)
        self._write_via(target, lambda path: path.write_text(text, encoding=encoding))
        self._record("written", len(text.encode(encoding)))
        self.debug(
            msg=Event.Write.name,
            step=Event.Completed.name,
            output=str(target),
            size=len(text),
            mode="text",
        )
        return str(target.absolute())

    def save_bytes(
        self,
        filename: str,
        data: Union[bytes, bytearray, memoryview],
        *,
        suffix: Optional[str] = None,
        subdir: Optional[str] = None,
        mkdir: bool = False,
    ) -> str:
        self.debug(
            msg=Event.Write.name,
            step=Event.Started.name,
            filename=filename,
            mkdir=mkdir,
            subdir=subdir,
            mode="bytes",
        )
        target = self._resolve_target(filename, suffix, subdir, mkdir)
        payload = bytes(data)
        self._write_via(target, lambda path: path.write_bytes(payload))
        self._record("written", len(payload))
        self.debug(
            msg=Event.Write.name,
            step=Event.Completed.name,
            output=str(target),
            size=len(payload),
            mode="bytes",
        )
        return str(target.absolute())

    def save_stream(
        self,
        filename: str,
        source: Any,
        *,
        suffix: Optional[str] = None,
        encoding: str = "utf-8",
        chunk: int = DEFAULT_CHUNK_SIZE,
        subdir: Optional[str] = None,
        mkdir: bool = False,
    ) -> str:
        self.debug(
            msg=Event.Write.name,
            step=Event.Started.name,
            filename=filename,
            mode="stream",
        )
        target = self._resolve_target(filename, suffix, subdir, mkdir)
        written = 0

        def stream_into(path: Path) -> None:
            nonlocal written
            with open(path, "wb") as fh:
                if hasattr(source, "read"):
                    while True:
                        buf = source.read(chunk)
                        if not buf:
                            break
                        if isinstance(buf, str):
                            buf = buf.encode(encoding)
                        fh.write(buf)
                        written += len(buf)
                else:
                    for piece in source:
                        if isinstance(piece, str):
                            piece = piece.encode(encoding)
                        fh.write(piece)
                        written += len(piece)

        try:
            self._write_via(target, stream_into)
        except Exception as e:
            self.debug(
                msg=Event.Write.name,
                step=Event.Failed.name,
                output=str(target),
                error=str(e),
            )
            raise DriverLocalStorageException(caller=self, error=str(e)) from e
        self._record("written", written)
        self.debug(
            msg=Event.Write.name,
            step=Event.Completed.name,
            output=str(target),
            size=written,
            mode="stream",
        )
        return str(target.absolute())

    def copy(
        self,
        source: str | Path,
        *,
        filename: Optional[str] = None,
        suffix: Optional[str] = None,
        subdir: Optional[str] = None,
        mkdir: bool = False,
    ) -> str:
        """Fast OS-level copy of an EXISTING file into the driver's storage.

        Uses ``shutil.copy2`` (sendfile / copy_file_range where the OS supports it,
        far faster than streaming through Python) and preserves every OS-settable
        source metadatum: permission bits, modification time (mtime), access time
        (atime) and file flags. NOTE: a file's CREATION/birth time cannot be set
        from userspace on Linux/macOS (and needs a platform API on Windows), so the
        copy inevitably carries a fresh creation time — the authoritative original
        timestamps and content digest must therefore travel as DATA (document
        metadata), not be relied upon from the copy's filesystem stat.
        ``filename``/``suffix`` default to the source's own stem/suffix.
        """
        self.debug(
            msg=Event.Copy.name,
            step=Event.Started.name,
            filename=filename,
            mode="copy",
        )
        src = Path(source)
        if not src.is_file():
            raise DriverLocalStorageException(
                caller=self, error=f"copy: source is not a file: {src}"
            )
        name = filename if filename is not None else src.stem
        suf = suffix if suffix is not None else src.suffix
        target = self._resolve_target(name, suf, subdir, mkdir)

        if target.exists() and src.samefile(target):
            self.debug(
                msg=Event.Copy.name,
                step=Event.Started.name,
                output=str(src),
                mode="copy",
                reason="target resolves to source",
            )
            return str(src.absolute())

        try:
            self._write_via(target, lambda path: shutil.copy2(src, path))
        except OSError as e:
            self.debug(
                msg=Event.Copy.name,
                step=Event.Failed.name,
                output=str(target),
                error=str(e),
            )
            raise DriverLocalStorageException(caller=self, error=str(e)) from e
        self._record("copied", target.stat().st_size)
        self.debug(
            msg=Event.Copy.name,
            step=Event.Completed.name,
            output=str(target),
            size=target.stat().st_size,
            mode="copy",
        )
        return str(target.absolute())

    @contextmanager
    def open_target(
        self,
        filename: str,
        *,
        suffix: Optional[str] = None,
        mode: str = "wb",
        subdir: Optional[str] = None,
        mkdir: bool = False,
    ) -> Iterator[BinaryIO]:
        self.debug(
            msg=Event.Write.name,
            step=Event.Started.name,
            filename=filename,
            mode=f"open:{mode}",
        )
        target = self._resolve_target(filename, suffix, subdir, mkdir)
        fh = open(target, mode)
        try:
            yield fh
        finally:
            fh.close()
            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                output=str(target),
            )

    @singledispatchmethod
    def write(
        self,
        content: Any,
        *,
        filename: str,
        suffix: Optional[str] = None,
        encoding: str = "utf-8",
        chunk: int = DEFAULT_CHUNK_SIZE,
        subdir: Optional[str] = None,
        mkdir: bool = False,
    ) -> str:
        """Type-dispatched save: ``str``→text, ``bytes``-like→bytes,
        file-like/iterable→stream.
        Single entry point a write strategy calls
        once a Formatter has produced the final payload. Mappings and other
        objects are rejected — they must be serialised by a Formatter first.
        """
        if not isinstance(content, Mapping) and (
            hasattr(content, "read") or isinstance(content, Iterable)
        ):
            return self.save_stream(
                filename,
                content,
                suffix=suffix,
                encoding=encoding,
                chunk=chunk,
                subdir=subdir,
                mkdir=mkdir,
            )
        raise DriverLocalStorageException(
            caller=self,
            error=(
                f"write: unsupported content type {type(content).__name__}; "
                "format it via a Formatter into str/bytes/stream first."
            ),
        )

    @write.register
    def _(
        self,
        content: str,
        *,
        filename: str,
        suffix: Optional[str] = None,
        encoding: str = "utf-8",
        subdir: Optional[str] = None,
        mkdir: bool = False,
        **_: Any,
    ) -> str:
        return self.save_text(
            filename,
            content,
            suffix=suffix,
            encoding=encoding,
            subdir=subdir,
            mkdir=mkdir,
        )

    @write.register(bytes)
    @write.register(bytearray)
    @write.register(memoryview)
    def _(
        self,
        content: Any,
        *,
        filename: str,
        suffix: Optional[str] = None,
        subdir: Optional[str] = None,
        mkdir: bool = False,
        **_: Any,
    ) -> str:
        return self.save_bytes(
            filename, content, suffix=suffix, subdir=subdir, mkdir=mkdir
        )

    # endregion Persistence primitives

    def _subdir_path(self, name: str, mkdir: bool = True) -> Path:
        """Resolve ``write_path/name`` with a traversal guard, optionally creating
        it. PURE: returns the resolved directory, never mutates ``current_path``."""
        _base = Path(self.write_path).resolve()
        _resolved = _base.joinpath(name).resolve()
        if not _resolved.is_relative_to(_base):
            reason = f"Path traversal detected: {name!r}"
            self.error(
                msg=Event.Configure.name,
                step=Event.Started.name,
                name=name,
                reason=reason,
            )
            raise PermissionError(reason)

        if mkdir and not _resolved.exists():
            _resolved.mkdir(parents=True)

        self.debug(
            msg=Event.Configure.name,
            step=Event.Completed.name,
            name=name,
            mkdir=mkdir,
            resolved=str(_resolved),
        )
        return _resolved

    # endregion private methods


# --------------------------------------------------------------------------- #
# endregion Clasess                                                            #
# --------------------------------------------------------------------------- #
