# Module name: documents/avro.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
from abc import ABC
from typing import Any, Dict, List, Optional
from wattleflow.concrete import Document

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Type aliases                                                         #
# --------------------------------------------------------------------------- #

AvroRecord = List[Dict[str, Any]]
AvroContent = List[Dict[str, Any]]
AvroSchema = Optional[Dict[str, Any]]

# --------------------------------------------------------------------------- #
# endregion Type aliases                                                      #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Documents                                                            #
# --------------------------------------------------------------------------- #


class AvroDocument(Document[AvroContent], ABC):
    """Document carrying Avro records and their schema."""

    def __init__(
        self,
        content: AvroContent,
        schema: AvroSchema = None,
        filename: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(content=content, **kwargs)
        if schema is not None:
            self.update_metadata("schema", schema)
        if filename is not None:
            self.update_metadata("filename", filename)

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
    def schema(self) -> AvroSchema:
        return self.metadata.get("schema")  # type: ignore[return-value]

    @schema.setter
    def schema(self, value: AvroSchema) -> None:
        if not isinstance(value, dict):
            raise TypeError("schema must be a dict (parsed Avro schema)")
        self.update_metadata("schema", value)

    @property
    def size(self) -> int:
        if isinstance(self.content, list):
            return len(self.content)
        return 0


# --------------------------------------------------------------------------- #
# endregion Documents                                                         #
# --------------------------------------------------------------------------- #
