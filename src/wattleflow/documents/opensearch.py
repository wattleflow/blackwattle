# Module name: documents/opensearch.py
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

OpenSearchContent = List[Dict[str, Any]]
OpenSearchSchema = Optional[Dict[str, Any]]

# --------------------------------------------------------------------------- #
# endregion Type aliases                                                      #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Documents                                                            #
# --------------------------------------------------------------------------- #


class OpenSearchDocument(Document[OpenSearchContent], ABC):
    """Document carrying OpenSearch records (one dict per hit / document).

    Mirrors SolrDocument shape: ``content`` is a list of dicts, ``metadata``
    records the index, query and optional schema for downstream inspection.
    """

    def __init__(
        self,
        content: OpenSearchContent,
        schema: OpenSearchSchema = None,
        filename: Optional[str] = None,
        index: Optional[str] = None,
        query: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(content=content, **kwargs)
        if schema is not None:
            self.update_metadata("schema", schema)
        if filename is not None:
            self.update_metadata("filename", filename)
        if index is not None:
            self.update_metadata("index", index)
        if query is not None:
            self.update_metadata("query", query)

    # region Properties

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
    def schema(self) -> OpenSearchSchema:
        return self.metadata.get("schema")  # type: ignore[return-value]

    @schema.setter
    def schema(self, value: OpenSearchSchema) -> None:
        self.update_metadata("schema", value)

    @property
    def index(self) -> Optional[str]:
        value = self.metadata.get("index")
        return str(value) if value else None

    @property
    def size(self) -> int:
        if isinstance(self.content, list):
            return len(self.content)
        return 0

    # endregion Properties


# --------------------------------------------------------------------------- #
# endregion Documents                                                         #
# --------------------------------------------------------------------------- #
