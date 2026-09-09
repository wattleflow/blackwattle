# Module name: helpers/formatters/tabular.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
Tabular/columnar Formatter implementations (CSV, Excel, ORC, Avro).

Serialisation logic ported out of ``DriverLocalStorage._write_*``: these
classes only turn ``content`` into a payload (str/bytes) or write it into a
handle — no file paths, FileStorage or driver concerns.
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import io
from typing import Any, BinaryIO
from wattleflow.concrete.serialisation import GenericFormatter
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["CsvFormatter", "ExcelFormatter", "OrcFormatter", "AvroFormatter"]

# --------------------------------------------------------------------------- #
# region Formatters                                                           #
# --------------------------------------------------------------------------- #


class CsvFormatter(GenericFormatter):
    SUFFIX = ".csv"

    def serialise(self, content: Any, **opts: Any) -> str:
        import pandas as pd

        if not isinstance(content, pd.DataFrame):
            raise TypeError(f"CsvFormatter: unsupported content type {type(content).__name__}")
        return content.to_csv(**opts)


class ExcelFormatter(GenericFormatter):
    SUFFIX = ".xlsx"

    def serialise(self, content: Any, **opts: Any) -> bytes:
        import pandas as pd

        if not isinstance(content, pd.DataFrame):
            raise TypeError(f"ExcelFormatter: unsupported content type {type(content).__name__}")
        buf = io.BytesIO()
        content.to_excel(
            buf,
            sheet_name=opts.pop("sheet_name", "Sheet1"),
            index=opts.pop("index", False),
            **opts,
        )
        return buf.getvalue()


class OrcFormatter(GenericFormatter):
    SUFFIX = ".orc"

    def _build_table(self, content: Any, **opts: Any):
        import pyarrow as pa

        schema = opts.get("schema", None)
        if isinstance(content, pa.Table):
            return content
        if isinstance(content, list):
            if schema is not None and not isinstance(schema, pa.Schema):
                schema = pa.schema(list(schema.items()))
            return pa.Table.from_pylist(content, schema=schema)
        raise TypeError(f"OrcFormatter: unsupported content type {type(content).__name__}")

    def stream(self, fh: BinaryIO, content: Any, **opts: Any) -> None:
        import pyarrow.orc as _orc

        table = self._build_table(content, **opts)
        _orc.write_table(table, fh, compression=opts.get("compression", "ZSTD"))

    def serialise(self, content: Any, **opts: Any) -> bytes:
        buf = io.BytesIO()
        self.stream(buf, content, **opts)
        return buf.getvalue()


class AvroFormatter(GenericFormatter):
    SUFFIX = ".avro"

    def stream(self, fh: BinaryIO, content: Any, **opts: Any) -> None:
        try:
            from fastavro import parse_schema, writer as _avro_writer
        except ImportError as e:
            raise ModuleNotFoundError(
                "fastavro library is missing. Add it manually: pip install fastavro"
            ) from e

        schema = opts.get("schema", None)
        if schema is None:
            raise ValueError("Avro write requires a 'schema' kwarg (parsed dict).")
        _avro_writer(fh, parse_schema(schema), content, codec=opts.get("codec", "deflate"))

    def serialise(self, content: Any, **opts: Any) -> bytes:
        buf = io.BytesIO()
        self.stream(buf, content, **opts)
        return buf.getvalue()


# --------------------------------------------------------------------------- #
# endregion Formatters                                                        #
# --------------------------------------------------------------------------- #
