# Module name: documents/solr.py
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

SolrContent = List[Dict[str, Any]]
SolrSchema = Optional[Dict[str, Any]]

# --------------------------------------------------------------------------- #
# endregion Type aliases                                                      #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Documents                                                            #
# --------------------------------------------------------------------------- #


class SolrDocument(Document[SolrContent], ABC):
    """Document carrying Solr records (one dict per Solr document).

    Schema metadata is a free-form dict that typically maps field name to
    Solr field type (``string``, ``text_general``, ``pdate``, ``tlong`` …).
    It is purely informational from the framework's perspective — the live
    schema is enforced by the Solr managed-schema. The optional ``core``
    metadata records which Solr core a result set came from.
    """

    def __init__(
        self,
        content: SolrContent,
        schema: SolrSchema = None,
        filename: Optional[str] = None,
        core: Optional[str] = None,
        query: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(content=content, **kwargs)
        if schema is not None:
            self.update_metadata("schema", schema)
        if filename is not None:
            self.update_metadata("filename", filename)
        if core is not None:
            self.update_metadata("core", core)
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
    def schema(self) -> SolrSchema:
        return self.metadata.get("schema")  # type: ignore[return-value]

    @schema.setter
    def schema(self, value: SolrSchema) -> None:
        self.update_metadata("schema", value)

    @property
    def core(self) -> Optional[str]:
        value = self.metadata.get("core")
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
