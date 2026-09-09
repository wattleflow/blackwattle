# Module name: drivers/entity.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
from pathlib import Path
from typing import Any, Optional

from wattleflow.concrete import GenericDriver
from wattleflow.concrete.driver import DriverAction, DriverMetadata
from wattleflow.concrete.exception import DriverException
from wattleflow.enums.event import Event
from wattleflow.enums.filetype import FileType

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #


_DEFAULT_ENCODING = "utf-8"
_DEFAULT_DELIMITER = ","


# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class DriverEntityError(DriverException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Driver                                                               #
# --------------------------------------------------------------------------- #


class DriverEntity(GenericDriver):
    """Pandas-backed driver for tabular file formats.

    Supported types: CSV, XLS/XLSX, JSON, Parquet, Pickle.
    Format is resolved per call via ``FileType.detect`` or the
    ``filetype`` configuration override.
    """

    ALLOWED = [
        "read_path",
        "write_path",
        "current_path",
        "path",
        "schema",
        "delete",
        "records",
        "filetype",
        "encoding",
        "delimiter",
        "sheet",
        "create",
        "options",
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.ensure_live()

    # region lifecycle

    def load(self) -> None:
        self.debug(
            msg=Event.Load.name,
            step=Event.Started.name,
            read_path=getattr(self, "read_path", None),
            write_path=getattr(self, "write_path", None),
        )

        self.create = bool(getattr(self, "create", False))
        self.encoding = getattr(self, "encoding", None) or _DEFAULT_ENCODING
        self.delimiter = getattr(self, "delimiter", None) or _DEFAULT_DELIMITER
        self.sheet = getattr(self, "sheet", None)
        self.options = getattr(self, "options", None) or {}
        self.schema = getattr(self, "schema", None) or {}

        # Single-file entity storage (table-mode): `path:` from YAML config.
        path = getattr(self, "path", None)
        self.path = Path(path) if path else None

        read_path = getattr(self, "read_path", None)
        write_path = getattr(self, "write_path", None)
        self.read_path = Path(read_path) if read_path else None
        self.write_path = Path(write_path) if write_path else None
        self.current_path: Optional[Path] = self.write_path

        if self.write_path is not None and not self.write_path.is_dir():
            if not self.create:
                reason = f"write_path is not a directory: {str(self.write_path)!r}"
                self.error(msg=Event.Load.name, reason=reason)
                raise DriverEntityError(caller=self, error=reason)
            self.write_path.mkdir(parents=True, exist_ok=True)

        self.debug(msg=Event.Load.name, step=Event.Completed.name)

    def close(self) -> None:
        self.debug(msg=Event.Close.name, step=Event.Started.name)
        if not self.can(DriverAction.UNLOAD):
            return
        self.debug(msg=Event.Close.name, step=Event.Completed.name)

    # endregion lifecycle

    # region public API

    def metadata(self) -> DriverMetadata:
        return DriverMetadata(
            name=self.__class__.__name__,
            version="1.0",
            protocol="pandas",
            capabilities=["read", "write"],
        )

    def read(self, uri: Optional[str] = None, **kwargs) -> Any:
        table = kwargs.pop("table", None)
        self.debug(msg=Event.Read.name, step=Event.Started.name, uri=uri, table=table)

        # Table-mode: read configured single-file storage and return list[dict].
        # Used by entity-pipeline configs where the driver has `path:` + `schema:`.
        if table is not None:
            return self._read_table(table, **kwargs)

        if not uri:
            raise DriverEntityError(caller=self, error="read: 'uri' or 'table' is required.")

        pd = self._pandas()
        resolved = self._resolve_read_path(uri)
        ftype = self._resolve_filetype(resolved, kwargs.pop("filetype", None))
        options = {**self.options, **kwargs}

        try:
            if ftype is FileType.CSV:
                df = pd.read_csv(
                    resolved,
                    encoding=options.pop("encoding", self.encoding),
                    sep=options.pop("sep", self.delimiter),
                    **options,
                )
            elif ftype is FileType.XLS:
                df = pd.read_excel(
                    resolved,
                    sheet_name=options.pop("sheet_name", self.sheet) or 0,
                    **options,
                )
            elif ftype is FileType.JSON:
                df = pd.read_json(resolved, **options)
            elif ftype is FileType.PICKLE:
                df = pd.read_pickle(resolved, **options)
            elif resolved.suffix.lower() == ".parquet":
                df = pd.read_parquet(resolved, **options)
            else:
                raise DriverEntityError(
                    caller=self,
                    error=f"read: unsupported file type {ftype.name} for {uri!r}",
                )
        except FileNotFoundError as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=str(e))
            raise DriverEntityError(caller=self, error=f"read: file not found: {resolved}") from e
        except DriverEntityError:
            raise
        except Exception as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=str(e))
            raise DriverEntityError(caller=self, error=f"read error: {e}") from e

        self.debug(
            msg=Event.Read.name,
            step=Event.Completed.name,
            uri=str(resolved),
            ftype=ftype.name,
            rows=int(getattr(df, "shape", (0,))[0]),
        )
        return df

    def write(self, uri: str, data: Any, **kwargs) -> str:
        self.debug(msg=Event.Write.name, step=Event.Started.name, uri=uri)

        if not uri:
            raise DriverEntityError(caller=self, error="write: uri is required.")

        pd = self._pandas()
        if not isinstance(data, pd.DataFrame):
            try:
                data = pd.DataFrame(data)
            except Exception as e:
                self.debug(msg=Event.Write.name, step=Event.Failed.name, error=str(e))
                raise DriverEntityError(
                    caller=self,
                    error=f"write: data must be a DataFrame or convertible: {e}",
                ) from e

        target = self._resolve_write_path(uri)
        ftype = self._resolve_filetype(target, kwargs.pop("filetype", None))
        options = {**self.options, **kwargs}

        try:
            if ftype is FileType.CSV:
                data.to_csv(
                    target,
                    index=options.pop("index", False),
                    encoding=options.pop("encoding", self.encoding),
                    sep=options.pop("sep", self.delimiter),
                    **options,
                )
            elif ftype is FileType.XLS:
                data.to_excel(
                    target,
                    sheet_name=options.pop("sheet_name", self.sheet) or "Sheet1",
                    index=options.pop("index", False),
                    **options,
                )
            elif ftype is FileType.JSON:
                data.to_json(target, **options)
            elif ftype is FileType.PICKLE:
                data.to_pickle(target, **options)
            elif target.suffix.lower() == ".parquet":
                data.to_parquet(target, index=options.pop("index", False), **options)
            else:
                raise DriverEntityError(
                    caller=self,
                    error=f"write: unsupported file type {ftype.name} for {uri!r}",
                )
        except DriverEntityError:
            raise
        except Exception as e:
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=str(e))
            raise DriverEntityError(caller=self, error=f"write error: {e}") from e

        self.debug(
            msg=Event.Write.name,
            step=Event.Completed.name,
            uri=str(target),
            ftype=ftype.name,
            rows=int(data.shape[0]),
        )
        return str(target)

    # endregion public API

    # region internal

    def _read_table(self, table: str, **kwargs) -> list:
        if not self.path:
            raise DriverEntityError(
                caller=self,
                error=f"read(table={table!r}): driver has no configured 'path'.",
            )

        target = Path(self.path)
        if not target.is_absolute():
            target = target.resolve()
        if not target.exists():
            raise DriverEntityError(
                caller=self, error=f"read(table={table!r}): file not found: {target}"
            )

        pd = self._pandas()
        ftype = self._resolve_filetype(target, kwargs.pop("filetype", None))
        where = kwargs.pop("where", None) or {}
        options = {**self.options, **kwargs}

        try:
            if ftype is FileType.CSV:
                df = pd.read_csv(
                    target,
                    encoding=options.pop("encoding", self.encoding),
                    sep=options.pop("sep", self.delimiter),
                    **options,
                )
            elif ftype is FileType.XLS:
                df = pd.read_excel(
                    target,
                    sheet_name=options.pop("sheet_name", self.sheet) or table,
                    **options,
                )
            elif ftype is FileType.JSON:
                df = pd.read_json(target, **options)
            elif ftype is FileType.PICKLE:
                df = pd.read_pickle(target, **options)
            elif target.suffix.lower() == ".parquet":
                df = pd.read_parquet(target, **options)
            else:
                raise DriverEntityError(
                    caller=self,
                    error=f"read(table={table!r}): unsupported file type {ftype.name}",
                )
        except DriverEntityError:
            raise
        except Exception as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=str(e))
            raise DriverEntityError(caller=self, error=f"read(table={table!r}) error: {e}") from e

        # Restrict to columns declared in schema[table].columns when available.
        spec = self.schema.get(table) if isinstance(self.schema, dict) else None
        if isinstance(spec, dict):
            declared = list((spec.get("columns") or {}).keys())
            if declared:
                keep = [c for c in declared if c in df.columns]
                if keep:
                    df = df[keep]

        # pandas converts empty quoted CSV fields to NaN — coerce back to ""
        # so downstream `r.get(col) or ""` works and TextMacros receives str.
        df = df.where(df.notna(), "")

        rows: list = df.to_dict(orient="records")

        if where:
            rows = [r for r in rows if all(r.get(k) == v for k, v in where.items())]

        self.debug(
            msg=Event.Read.name,
            step=Event.Started.name,
            table=table,
            path=str(target),
            ftype=ftype.name,
            rows=len(rows),
        )
        return rows

    def _pandas(self):
        try:
            import pandas as pd  # noqa: WPS433

            return pd
        except ImportError as e:
            raise ModuleNotFoundError(
                "pandas library is missing. Add it manually: pip install pandas"
            ) from e

    def _resolve_filetype(self, path: Path, override: Optional[str]) -> FileType:
        if override:
            try:
                return FileType[str(override).upper()]
            except KeyError as e:
                self.debug(msg=Event.Detect.name, step=Event.Failed.name, error=str(e))
                raise DriverEntityError(
                    caller=self, error=f"unknown filetype override: {override!r}"
                ) from e
        configured = getattr(self, "filetype", None)
        if configured:
            try:
                return FileType[str(configured).upper()]
            except KeyError as e:
                self.debug(msg=Event.Detect.name, step=Event.Failed.name, error=str(e))
                raise DriverEntityError(
                    caller=self, error=f"unknown filetype config: {configured!r}"
                ) from e
        return FileType.detect(str(path))

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

    # endregion internal

    def __repr__(self) -> str:
        rp = getattr(self, "read_path", None)
        wp = getattr(self, "write_path", None)
        return f"DriverEntity(read={rp}, write={wp}, state={self._fsm.state.value})"


# --------------------------------------------------------------------------- #
# endregion Driver                                                            #
# --------------------------------------------------------------------------- #
