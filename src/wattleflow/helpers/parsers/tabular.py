# Module name: helpers/parsers/tabular.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
Tabular parsers — CSV, Excel, ORC and Avro deserialisation.

Each parser turns the reader handed over by GenericParser into a domain
object (pandas DataFrame or list[dict]). Third-party dependencies are
lazy-imported inside ``deserialise`` so the module stays light.
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from typing import Any, BinaryIO
from wattleflow.concrete.serialisation import GenericParser
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["CsvParser", "ExcelParser", "OrcParser", "AvroParser"]

# --------------------------------------------------------------------------- #
# region Parsers                                                              #
# --------------------------------------------------------------------------- #


class CsvParser(GenericParser):
    """Read a CSV stream into a pandas DataFrame."""

    def deserialise(self, reader: BinaryIO, **opts: Any) -> Any:
        import pandas as pd

        return pd.read_csv(reader, **opts)


class ExcelParser(GenericParser):
    """Read an Excel stream into a pandas DataFrame."""

    def deserialise(self, reader: BinaryIO, **opts: Any) -> Any:
        import pandas as pd

        return pd.read_excel(reader, **opts)


class OrcParser(GenericParser):
    """Read an ORC stream into a list of row dicts."""

    def deserialise(self, reader: BinaryIO, **opts: Any) -> list[dict]:
        try:
            import pyarrow.orc as _orc
        except ImportError as e:
            raise ModuleNotFoundError(
                "pyarrow library is missing. Add it manually: pip install pyarrow"
            ) from e

        columns = opts.pop("columns", None)
        table = _orc.read_table(reader, columns=columns)
        return table.to_pylist()


class AvroParser(GenericParser):
    """Read an Avro stream into a list of record dicts."""

    def deserialise(self, reader: BinaryIO, **opts: Any) -> list[dict]:
        try:
            from fastavro import reader as _avro_reader
        except ImportError as e:
            raise ModuleNotFoundError(
                "fastavro library is missing. Add it manually: pip install fastavro"
            ) from e

        return list(_avro_reader(reader))


# --------------------------------------------------------------------------- #
# endregion Parsers                                                           #
# --------------------------------------------------------------------------- #
