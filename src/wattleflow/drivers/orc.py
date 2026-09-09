# Module name: drivers/orc.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# IMPORTANT: This driver requires the pyarrow library.                        #
# Ensure you have it installed using:                                         #
#   pip install pyarrow                                                       #
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
from wattleflow.documents.orc import OrcContent, OrcRecord, OrcSchema

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #


_DEFAULT_COMPRESSION = "ZSTD"


# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class DriverOrcError(DriverException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Driver                                                               #
# --------------------------------------------------------------------------- #


class DriverOrc(GenericDriver):
    """File-system driver dedicated to the Apache ORC columnar format.

    Read:  parses an ``.orc`` file via ``pyarrow.orc.read_table`` and returns
           a list of rows (one dict per row).
    Write: serialises a list of dicts (or a ``pyarrow.Table``) using an
           optional Arrow schema mapping; compression is configurable
           (``ZSTD`` by default).
    """

    ALLOWED = [
        "read_path",
        "write_path",
        "current_path",
        "compression",
        "create",
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.ensure_live()

    def metadata(self) -> DriverMetadata:
        return DriverMetadata(
            name=self.__class__.__name__,
            version="1.0",
            protocol="orc",
            capabilities=["read", "write", "search"],
        )

    def load(self) -> None:
        self.debug(
            msg=Event.Load.name,
            step=Event.Started.name,
            read_path=getattr(self, "read_path", None),
            write_path=getattr(self, "write_path", None),
            compression=getattr(self, "compression", None),
        )

        self.create = bool(getattr(self, "create", False))
        self.compression = getattr(self, "compression", None) or _DEFAULT_COMPRESSION

        read_path = getattr(self, "read_path", None)
        write_path = getattr(self, "write_path", None)
        self.read_path = Path(read_path) if read_path else None
        self.write_path = Path(write_path) if write_path else None
        self.current_path: Optional[Path] = self.write_path

        if self.write_path is not None and not self.write_path.is_dir():
            if not self.create:
                reason = f"write_path is not a directory: {str(self.write_path)!r}"
                self.error(msg=Event.Load.name, reason=reason)
                raise DriverOrcError(caller=self, error=reason)
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

    def read(self, uri: str, **kwargs) -> OrcContent:
        self.debug(msg=Event.Read.name, step=Event.Started.name, uri=uri)

        if not uri:
            raise DriverOrcError(caller=self, error="read: uri is required.")

        try:
            import pyarrow.orc as _orc
        except ImportError as e:
            raise ModuleNotFoundError(
                "pyarrow library is missing. Add it manually: pip install pyarrow"
            ) from e

        resolved = self._resolve_read_path(uri)
        columns = kwargs.pop("columns", None)

        try:
            table = _orc.read_table(str(resolved), columns=columns)
            records: OrcContent = table.to_pylist()
        except FileNotFoundError as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=str(e))
            raise DriverOrcError(caller=self, error=f"read: file not found: {resolved}") from e
        except Exception as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=str(e))
            raise DriverOrcError(caller=self, error=f"read error: {e}") from e

        self.debug(
            msg=Event.Read.name,
            step=Event.Completed.name,
            uri=str(resolved),
            rows=len(records),
        )
        return records

    def write(self, uri: str, data: OrcRecord, **kwargs) -> str:
        self.debug(msg=Event.Write.name, step=Event.Started.name, uri=uri)

        if not uri:
            raise DriverOrcError(caller=self, error="write: uri is required.")

        try:
            import pyarrow as pa
            import pyarrow.orc as _orc
        except ImportError as e:
            raise ModuleNotFoundError(
                "pyarrow library is missing. Add it manually: pip install pyarrow"
            ) from e

        schema: OrcSchema = kwargs.pop("schema", None)
        compression: str = (
            kwargs.pop("compression", None) or self.compression or _DEFAULT_COMPRESSION
        )
        output: Path = self._resolve_write_path(uri)

        try:
            if isinstance(data, pa.Table):
                table = data
            elif isinstance(data, list):
                pa_schema: Optional[pa.Schema] = None
                if isinstance(schema, pa.Schema):
                    pa_schema = schema
                elif isinstance(schema, dict):
                    pa_schema = pa.schema(list(schema.items()))
                table = pa.Table.from_pylist(data, schema=pa_schema)
            else:
                raise DriverOrcError(
                    caller=self,
                    error=f"write: unsupported data type {type(data).__name__}",
                )

            _orc.write_table(table, str(output), compression=compression)
        except DriverOrcError:
            raise
        except Exception as e:
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=str(e))
            raise DriverOrcError(caller=self, error=f"write error: {e}") from e

        self.debug(
            msg=Event.Write.name,
            step=Event.Completed.name,
            uri=str(output),
            rows=table.num_rows,
            compression=compression,
        )
        return str(output)

    def search(
        self,
        pattern: str = "*.orc",
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
            raise DriverOrcError(caller=self, error="search: read_path not configured.")

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
        if candidate.suffix.lower() != ".orc":
            candidate = candidate.with_suffix(".orc")

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
        return f"DriverOrc(read={rp}, write={wp})"


# --------------------------------------------------------------------------- #
# endregion Driver                                                            #
# --------------------------------------------------------------------------- #
