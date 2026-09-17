# Module Name: pipelines/convertors/md2word.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""Convert a Markdown file to a Word document beside the source.

v0.0.4 (DR-PRC-005): rendered by the Word formatter; the module's own parser copy is removed.
"""

# --------------------------------------------------------------------------- #
# region imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from pathlib import Path
from typing import Any
from wattleflow.core import IProcessor, ITarget
from wattleflow.concrete import GenericPipeline
from wattleflow.documents import FileDocument
from wattleflow.enums.event import Event
from wattleflow.enums.filetype import FileType
from wattleflow.helpers.formatters.factory import FormatterFactory

# --------------------------------------------------------------------------- #
# endregion imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Pipelines
# --------------------------------------------------------------------------- #


class PipelineMarkdownToWord(GenericPipeline):
    # `converter` holds any Word converter setting; named keys override it.
    ALLOWED = ["author", "converter", "font", "h1", "h2", "h3", "size"]
    SETTINGS = ("author", "font", "h1", "h2", "h3", "size")

    def settings(self, processor: IProcessor) -> dict[str, Any]:
        """Converter settings: pipeline `converter`, else the processor's; named keys win."""
        base = self.converter or getattr(processor, "converter", None) or {}
        named = {key: getattr(self, key) for key in self.SETTINGS if getattr(self, key) is not None}
        return {**dict(base), **named}

    def transform(
        self,
        processor: IProcessor,
        facade: ITarget,
        *args,
        **kwargs,
    ) -> str | None:
        document: FileDocument = facade.request()
        assert isinstance(document, FileDocument), "Expected FileDocument type: Found %s" % type(
            document
        )

        filename_raw = getattr(document, "filename", None)
        filename: Path | None = Path(filename_raw) if filename_raw else None
        if filename is None or not filename.exists():
            self.error(
                msg=Event.Transform,
                step=Event.Started,
                reason="No valid file to process!",
                document=document,
                filename=filename,
            )
            return None

        if not document.size > 0:
            self.warning(
                msg=Event.Transform,
                step=Event.Check,
                reason="Nothing to process here!",
                document=document,
                size=document.size,
            )
            return None

        formatter = FormatterFactory.create(FileType.DOCX)
        payload = formatter.render(
            content=filename.read_text(encoding="utf-8"),
            converter=self.settings(processor),
        )
        output = filename.with_suffix(formatter.SUFFIX)
        output.write_bytes(payload)
        document.update_metadata("output", str(output))

        uid = processor.blackboard.write(
            pipeline=self,
            facade=facade,
            processor=processor,
        )

        self.debug(
            msg=Event.Transform,
            step=Event.Completed,
            uid=uid,
            size=document.size,
            output=str(output),
        )
        # Returned so GenericPipeline.process records it as `result`.
        return uid


# --------------------------------------------------------------------------- #
# endregion Pipelines                                                         #
# --------------------------------------------------------------------------- #

__all__ = ["PipelineMarkdownToWord"]
