# Module name: pipelines/xml/extract.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from pathlib import Path
from typing import Any
from wattleflow.core import IProcessor, ITarget
from wattleflow.concrete import GenericPipeline
from wattleflow.enums.event import Event
from wattleflow.enums.filetype import FileType
from wattleflow.documents.file import FileDocument
from wattleflow.helpers.parsers.text import XmlParser
from wattleflow.helpers.records import DocumentRecords
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["PipelineXMLExtract"]

# --------------------------------------------------------------------------- #
# region Pipelines                                                            #
# --------------------------------------------------------------------------- #


class PipelineXMLExtract(GenericPipeline):
    """Read one XML document and hand its records to the write side in the configured format.

    `record` names the repeating element; without it every child of the root is a record.
    """

    ALLOWED = ["format", "record"]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            format=kwargs.pop("format", None) or DocumentRecords.DEFAULT.name,
            **kwargs,
        )
        self.file_type: FileType = DocumentRecords.file_type(self.format)

    def read(self, source: Path) -> Any:
        """Content to hand over, read from one source document."""
        return XmlParser().parse(path=source, record=self.record)

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> str | None:
        document: FileDocument = facade.request()
        try:
            content = self.read(Path(document.filename))
        except Exception as e:
            self.error(
                msg=Event.Transform.name,
                step=Event.Failed.name,
                error=f"read failed: {e}",
                filename=document.filename,
            )
            return None

        if not content:
            self.warning(
                msg=Event.Transform.name,
                step=Event.Check.name,
                reason="no records",
                filename=document.filename,
            )
            return None

        DocumentRecords.stamp(document, content, self.file_type)
        uid = processor.blackboard.write(facade=facade, processor=processor, pipeline=self)

        self.debug(
            msg=Event.Transform.name,
            step=Event.Completed.name,
            uid=uid,
            records=len(content),
            format=self.file_type.name,
        )
        return uid


# --------------------------------------------------------------------------- #
# endregion Pipelines                                                         #
# --------------------------------------------------------------------------- #
