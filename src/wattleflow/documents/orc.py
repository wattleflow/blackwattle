# Module name: documents/orc.py
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

OrcRecord = List[Dict[str, Any]]
OrcContent = List[Dict[str, Any]]
OrcSchema = Optional[Dict[str, Any]]

# --------------------------------------------------------------------------- #
# endregion Type aliases                                                      #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Documents                                                            #
# --------------------------------------------------------------------------- #


class OrcDocument(Document[OrcContent], ABC):
    """Document carrying ORC records and their (optional) Arrow-style schema.

    Content is a list of dicts (one per ORC row). Schema is stored in metadata
    under the ``schema`` key as a mapping of column name → pyarrow type string
    (e.g. ``{"flight_no": "string", "passengers": "int32"}``) so it can be
    expressed declaratively in YAML. A raw ``pyarrow.Schema`` is also accepted
    and passed through to the driver.
    """

    def __init__(
        self,
        content: OrcContent,
        schema: OrcSchema = None,
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
    def schema(self) -> OrcSchema:
        return self.metadata.get("schema")  # type: ignore[return-value]

    @schema.setter
    def schema(self, value: OrcSchema) -> None:
        self.update_metadata("schema", value)

    @property
    def size(self) -> int:
        if isinstance(self.content, list):
            return len(self.content)
        return 0


# --------------------------------------------------------------------------- #
# endregion Documents                                                         #
# --------------------------------------------------------------------------- #
