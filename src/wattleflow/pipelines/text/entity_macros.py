# Module name: pipelines/text/entity_macros.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from typing import Any, Dict, List, Optional
from wattleflow.core import IProcessor, ITarget
from wattleflow.concrete import GenericPipeline
from wattleflow.enums.event import Event
from wattleflow.documents.file import FileDocument
from wattleflow.helpers.macros import CompiledMacros, TextMacros
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Pipelines                                                            #
# --------------------------------------------------------------------------- #


# * **Gramatika:** `Pipeline + <Subject> + <Operation | ToTarget> + [Qualifier]`
class PipelineTextRedactMacroEntity(GenericPipeline):
    __slots__ = ("_compiled",)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._compiled: Optional[CompiledMacros] = None

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> Any:
        if self._compiled is None:
            self._compiled = TextMacros(processor.macros, flag=2).compiled

        document: FileDocument = facade.request()
        content: str = document.content

        assert isinstance(content, str), "PipelineMacroRedaction: `content` must be a string!"

        if not content.strip():
            self.warning(msg=Event.Transform.name, step=Event.Check.name, error="Content is empty!")
            return

        hits: List[Dict[str, str]] = []
        redacted = content
        for pattern, replacement in self._compiled:
            for match in pattern.finditer(content):
                matched = match.group(0)
                if matched:
                    hits.append({"text": matched, "replacement": replacement})
            redacted = pattern.sub(replacement, redacted)

        document.update_content(redacted)
        document.update_metadata("pii_hits", hits)

        return processor.blackboard.write(
            facade=facade,
            processor=processor,
            pipeline=self,
        )


# --------------------------------------------------------------------------- #
# endregion Pipelines                                                         #
# --------------------------------------------------------------------------- #

__all__ = ["PipelineTextRedactMacroEntity"]
