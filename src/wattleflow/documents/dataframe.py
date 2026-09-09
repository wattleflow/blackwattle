# Module name: documents/dataframe.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2025 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
from abc import ABC
from pandas import DataFrame
from wattleflow.concrete import Document

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Documents                                                            #
# --------------------------------------------------------------------------- #


class DataFrameDocument(Document[DataFrame], ABC):
    def __init__(self, content: DataFrame, **kwargs):
        super().__init__(content=content, **kwargs)

    @property
    def filename(self) -> str:
        return str(self.metadata.get("filename", ""))

    @filename.setter
    def filename(self, value: str) -> None:
        filename = value.strip()
        if not filename:
            raise ValueError("filename must be a non-empty string")
        self.update_metadata("filename", filename)

    @property
    def size(self) -> int:
        if isinstance(self.content, DataFrame):
            return len(self.content)
        return 0


# --------------------------------------------------------------------------- #
# endregion Documents                                                         #
# --------------------------------------------------------------------------- #
