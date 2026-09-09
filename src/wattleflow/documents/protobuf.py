# Module name: documents/protobuf.py
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

ProtobufRecord = List[Dict[str, Any]]
ProtobufContent = List[Dict[str, Any]]
ProtobufSchema = Optional[Any]
# ProtobufSchema is intentionally permissive — it accepts either a
# descriptor-dict (declarative, YAML-friendly), a pre-compiled message
# class, or an instance of such a class. See helpers.protobuf.resolve_message_class
# for the resolution policy.

# --------------------------------------------------------------------------- #
# endregion Type aliases                                                      #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Documents                                                            #
# --------------------------------------------------------------------------- #


class ProtobufDocument(Document[ProtobufContent], ABC):
    """Document carrying Protocol Buffer records.

    Content is a list of dicts (one per message). The schema metadata holds
    the descriptor dict (or a reference to a pre-compiled message class) and
    is required for both serialisation and deserialisation.
    """

    def __init__(
        self,
        content: ProtobufContent,
        schema: ProtobufSchema = None,
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
    def schema(self) -> ProtobufSchema:
        return self.metadata.get("schema")

    @schema.setter
    def schema(self, value: ProtobufSchema) -> None:
        self.update_metadata("schema", value)

    @property
    def size(self) -> int:
        if isinstance(self.content, list):
            return len(self.content)
        return 0


# --------------------------------------------------------------------------- #
# endregion Documents                                                         #
# --------------------------------------------------------------------------- #
