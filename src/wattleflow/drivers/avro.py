# Module name: drivers/avro.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# IMPORTANT: This driver requires the fastavro library.                       #
# Ensure you have it installed using:                                         #
#   pip install fastavro                                                      #
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
from wattleflow.documents.avro import AvroContent, AvroRecord, AvroSchema

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #


_DEFAULT_CODEC = "deflate"


# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class DriverAvroError(DriverException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Driver                                                               #
# --------------------------------------------------------------------------- #


class DriverAvro(GenericDriver):
    """File-system driver dedicated to the Apache Avro container format.

    Read:  parses an ``.avro`` file via ``fastavro.reader`` and returns
           a list of records (one dict per record).
    Write: serialises a list of records using a parsed Avro schema via
           ``fastavro.writer``; codec is configurable (``deflate`` by default).
    """

    ALLOWED = [
        "read_path",
        "write_path",
        "current_path",
        "codec",
        "create",
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.ensure_live()

    def metadata(self) -> DriverMetadata:
        return DriverMetadata(
            name=self.__class__.__name__,
            version="1.0",
            protocol="avro",
            capabilities=["read", "write", "search"],
        )

    def load(self) -> None:
        self.debug(
            msg=Event.Load.name,
            step=Event.Started.name,
            read_path=getattr(self, "read_path", None),
            write_path=getattr(self, "write_path", None),
            codec=getattr(self, "codec", None),
        )

        self.create = bool(getattr(self, "create", False))
        self.codec = getattr(self, "codec", None) or _DEFAULT_CODEC

        read_path = getattr(self, "read_path", None)
        write_path = getattr(self, "write_path", None)
        self.read_path = Path(read_path) if read_path else None
        self.write_path = Path(write_path) if write_path else None
        self.current_path: Optional[Path] = self.write_path

        if self.write_path is not None and not self.write_path.is_dir():
            if not self.create:
                reason = f"write_path is not a directory: {str(self.write_path)!r}"
                self.error(msg=Event.Load.name, reason=reason)
                raise DriverAvroError(caller=self, error=reason)
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

    def read(self, uri: str, **kwargs) -> AvroContent:
        self.debug(msg=Event.Read.name, step=Event.Started.name, uri=uri)

        if not uri:
            raise DriverAvroError(caller=self, error="read: uri is required.")

        try:
            from fastavro import reader as _avro_reader
        except ImportError as e:
            raise ModuleNotFoundError(
                "fastavro library is missing. Add it manually: pip install fastavro"
            ) from e

        resolved = self._resolve_read_path(uri)

        try:
            with open(resolved, "rb") as fh:
                records: AvroContent = list(_avro_reader(fh))
        except FileNotFoundError as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=str(e))
            raise DriverAvroError(caller=self, error=f"read: file not found: {resolved}") from e
        except Exception as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=str(e))
            raise DriverAvroError(caller=self, error=f"read error: {e}") from e

        self.debug(
            msg=Event.Read.name,
            step=Event.Completed.name,
            uri=str(resolved),
            records=len(records),
        )
        return records

    def write(self, uri: str, data: AvroRecord, **kwargs) -> str:
        self.debug(msg=Event.Write.name, step=Event.Started.name, uri=uri)

        if not uri:
            raise DriverAvroError(caller=self, error="write: uri is required.")
        if not isinstance(data, list):
            raise DriverAvroError(caller=self, error="write: data must be list[dict] (AvroRecord).")

        schema: AvroSchema = kwargs.pop("schema", None)
        if not isinstance(schema, dict):
            raise DriverAvroError(caller=self, error="write: 'schema' kwarg (dict) is required.")

        try:
            from fastavro import parse_schema, writer as _avro_writer
        except ImportError as e:
            raise ModuleNotFoundError(
                "fastavro library is missing. Add it manually: pip install fastavro"
            ) from e

        codec: str = kwargs.pop("codec", None) or self.codec or _DEFAULT_CODEC
        output: Path = self._resolve_write_path(uri)

        try:
            parsed = parse_schema(schema)
            with open(output, "wb") as fh:
                _avro_writer(fh, parsed, data, codec=codec)
        except Exception as e:
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=str(e))
            raise DriverAvroError(caller=self, error=f"write error: {e}") from e

        self.debug(
            msg=Event.Write.name,
            step=Event.Completed.name,
            uri=str(output),
            records=len(data),
            codec=codec,
        )
        return str(output)

    def search(
        self,
        pattern: str = "*.avro",
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
            raise DriverAvroError(caller=self, error="search: read_path not configured.")

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
        if candidate.suffix.lower() != ".avro":
            candidate = candidate.with_suffix(".avro")

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
        return f"DriverAvro(read={rp}, write={wp})"


# --------------------------------------------------------------------------- #
# endregion Driver                                                            #
# --------------------------------------------------------------------------- #
