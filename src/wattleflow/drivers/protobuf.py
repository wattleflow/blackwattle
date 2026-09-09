# Module name: drivers/protobuf.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# IMPORTANT: This driver requires the protobuf library.                       #
#       pip install protobuf                                                  #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
import fnmatch
from pathlib import Path
from typing import Generator, Optional
from wattleflow.concrete import GenericDriver
from wattleflow.concrete.driver import DriverAction, DriverMetadata
from wattleflow.concrete.exception import DriverException
from wattleflow.enums.event import Event
from wattleflow.documents.protobuf import ProtobufContent, ProtobufRecord, ProtobufSchema
from wattleflow.helpers.protobuf import (
    decode_delimited_stream,
    encode_delimited_stream,
    resolve_message_class,
)

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class DriverProtobufError(DriverException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Driver                                                               #
# --------------------------------------------------------------------------- #


class DriverProtobuf(GenericDriver):
    """File-system driver dedicated to length-delimited Protocol Buffer streams.

    Read:  parses a ``.pb`` file produced by :meth:`write` (varint-length
           prefixed concatenation of serialised messages) and returns a
           ``list[dict]``.
    Write: serialises a list of dicts (via the bound message class) into the
           same length-delimited format.

    A schema is required at write time — either set on the driver via
    ``schema=`` / ``message_class=`` configuration or supplied per-call as
    ``write(..., schema=...)``.
    """

    ALLOWED = [
        "read_path",
        "write_path",
        "current_path",
        "schema",
        "message_class",
        "create",
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.ensure_live()

    def metadata(self) -> DriverMetadata:
        return DriverMetadata(
            name=self.__class__.__name__,
            version="1.0",
            protocol="protobuf",
            capabilities=["read", "write", "search"],
        )

    def load(self) -> None:
        self.debug(
            msg=Event.Load.name,
            step=Event.Started.name,
            read_path=getattr(self, "read_path", None),
            write_path=getattr(self, "write_path", None),
        )

        self.create = bool(getattr(self, "create", False))
        self.schema = getattr(self, "schema", None)
        self.message_class = getattr(self, "message_class", None)

        read_path = getattr(self, "read_path", None)
        write_path = getattr(self, "write_path", None)
        self.read_path = Path(read_path) if read_path else None
        self.write_path = Path(write_path) if write_path else None
        self.current_path: Optional[Path] = self.write_path

        if self.write_path is not None and not self.write_path.is_dir():
            if not self.create:
                reason = f"write_path is not a directory: {str(self.write_path)!r}"
                self.error(msg=Event.Load.name, reason=reason)
                raise DriverProtobufError(caller=self, error=reason)
            self.write_path.mkdir(parents=True, exist_ok=True)

        self.debug(msg=Event.Load.name, step=Event.Completed.name)

    def close(self) -> None:
        self.debug(msg=Event.Close.name, step=Event.Started.name)
        if not self.can(DriverAction.UNLOAD):
            return
        self.debug(msg=Event.Close.name, step=Event.Completed.name)

    # ---------------------------------------------------------------------- #
    # region Read / Write                                                    #
    # ---------------------------------------------------------------------- #

    def read(self, uri: str, **kwargs) -> ProtobufContent:
        self.debug(msg=Event.Read.name, step=Event.Started.name, uri=uri)

        if not uri:
            raise DriverProtobufError(caller=self, error="read: uri is required.")

        schema = kwargs.pop("schema", None) or self.schema
        message_class = kwargs.pop("message_class", None) or self.message_class
        try:
            cls = message_class or resolve_message_class(schema)
        except Exception as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=str(e))
            raise DriverProtobufError(
                caller=self, error=f"read: invalid schema/message_class: {e}"
            ) from e

        resolved = self._resolve_read_path(uri)

        try:
            with open(resolved, "rb") as fh:
                raw = fh.read()
            records = decode_delimited_stream(raw, cls)
        except FileNotFoundError as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=str(e))
            raise DriverProtobufError(caller=self, error=f"read: file not found: {resolved}") from e
        except Exception as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=str(e))
            raise DriverProtobufError(caller=self, error=f"read error: {e}") from e

        self.debug(
            msg=Event.Read.name,
            step=Event.Completed.name,
            uri=str(resolved),
            records=len(records),
        )
        return records

    def write(self, uri: str, data: ProtobufRecord, **kwargs) -> str:
        self.debug(msg=Event.Write.name, step=Event.Started.name, uri=uri)

        if not uri:
            raise DriverProtobufError(caller=self, error="write: uri is required.")
        if not isinstance(data, list):
            raise DriverProtobufError(
                caller=self,
                error="write: data must be list[dict] (ProtobufRecord).",
            )

        schema: ProtobufSchema = kwargs.pop("schema", None) or self.schema
        message_class = kwargs.pop("message_class", None) or self.message_class
        try:
            cls = message_class or resolve_message_class(schema)
        except Exception as e:
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=str(e))
            raise DriverProtobufError(
                caller=self, error=f"write: invalid schema/message_class: {e}"
            ) from e

        output: Path = self._resolve_write_path(uri)

        try:
            payload = encode_delimited_stream(data, cls)
            with open(output, "wb") as fh:
                fh.write(payload)
        except Exception as e:
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=str(e))
            raise DriverProtobufError(caller=self, error=f"write error: {e}") from e

        self.debug(
            msg=Event.Write.name,
            step=Event.Completed.name,
            uri=str(output),
            records=len(data),
        )
        return str(output)

    def search(
        self,
        pattern: str = "*.pb",
        case_sensitive: bool = False,
        recursive: bool = False,
    ) -> Generator[Path, None, None]:
        self.debug(
            msg=Event.Search.name,
            step=Event.Started.name,
            pattern=pattern,
            recursive=recursive,
        )

        if self.read_path is None:
            raise DriverProtobufError(caller=self, error="search: read_path not configured.")

        base = Path(self.read_path).resolve()
        iterator = base.rglob("*") if recursive else base.glob("*")

        for path in iterator:
            name = path.name
            target = name if case_sensitive else name.lower()
            needle = pattern if case_sensitive else pattern.lower()
            if any(c in pattern for c in ("*", "?", "[")):
                if fnmatch.fnmatchcase(target, needle):
                    yield path
            else:
                if needle in target:
                    yield path

        self.debug(msg=Event.Search.name, step=Event.Completed.name)

    # ---------------------------------------------------------------------- #
    # endregion Read / Write                                                 #
    # ---------------------------------------------------------------------- #

    # ---------------------------------------------------------------------- #
    # region Internal helpers                                                #
    # ---------------------------------------------------------------------- #

    def _resolve_read_path(self, uri: str) -> Path:
        candidate = Path(uri)
        if candidate.is_absolute():
            target = candidate.resolve()
        elif self.read_path is not None:
            target = (Path(self.read_path) / candidate).resolve()
        else:
            target = candidate.resolve()

        if self.read_path is not None:
            base = Path(self.read_path).resolve()
            if not target.is_relative_to(base):
                reason = f"Access denied: path outside read_path: {uri!r}"
                self.error(msg=Event.Configure.name, step=Event.Started.name, reason=reason)
                raise PermissionError(reason)

        return target

    def _resolve_write_path(self, uri: str) -> Path:
        candidate = Path(uri)
        if candidate.suffix.lower() not in (".pb", ".protobuf"):
            candidate = candidate.with_suffix(".pb")

        if candidate.is_absolute():
            target = candidate.resolve()
        elif self.write_path is not None:
            target = (Path(self.write_path) / candidate).resolve()
        else:
            target = candidate.resolve()

        if self.write_path is not None:
            base = Path(self.write_path).resolve()
            if not target.is_relative_to(base):
                reason = f"Access denied: path outside write_path: {uri!r}"
                self.error(msg=Event.Configure.name, step=Event.Started.name, reason=reason)
                raise PermissionError(reason)

        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    # ---------------------------------------------------------------------- #
    # endregion Internal helpers                                             #
    # ---------------------------------------------------------------------- #

    def __repr__(self) -> str:
        rp = getattr(self, "read_path", None)
        wp = getattr(self, "write_path", None)
        return f"DriverProtobuf(read={rp}, write={wp})"


# --------------------------------------------------------------------------- #
# endregion Driver                                                            #
# --------------------------------------------------------------------------- #
