# Module name: pipelines/quality/measure.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from typing import Any
from wattleflow.core import IProcessor, ITarget
from wattleflow.concrete import GenericPipeline
from wattleflow.enums.event import Event
from wattleflow.enums.filetype import FileType
from wattleflow.helpers.records import DocumentRecords
from wattleflow.pipelines.quality.dqi import QualityRules, RunningAggregate
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["PipelineQualityMeasure"]

# --------------------------------------------------------------------------- #
# region Pipelines                                                            #
# --------------------------------------------------------------------------- #


class PipelineQualityMeasure(GenericPipeline):
    """Measure the records a document carries at one checkpoint; the records are not changed.

    The report travels beside the data in the quality slot, and the last document of a pass carries
    the checkpoint's aggregate. Method: documentation/05-METHODS/dqi.md.
    """

    ALLOWED = ["checkpoint", "rules", "format"]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            checkpoint=kwargs.pop("checkpoint", None) or "T1",
            rules=kwargs.pop("rules", None) or {},
            format=kwargs.pop("format", None) or DocumentRecords.DEFAULT.name,
            **kwargs,
        )
        self.quality: QualityRules = QualityRules.from_mapping(self.rules)
        self.file_type: FileType = DocumentRecords.file_type(self.format)
        self.aggregate = RunningAggregate()
        self.seen: set[tuple[str, ...]] = set()

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> str | None:
        document = facade.request()
        records = DocumentRecords.records(document)
        if not records:
            self.warning(
                msg=Event.Transform.name,
                step=Event.Check.name,
                reason="no records to measure",
                document=facade.identifier,
            )
            return None

        measured = [self.quality.measure(record, self.checkpoint, self.seen) for record in records]
        for index in measured:
            self.aggregate.update(index.dqi, index.dimensions)

        report = DocumentRecords.records(document, DocumentRecords.QUALITY)
        rows = report + [index.row() for index in measured]
        DocumentRecords.stamp(document, rows, self.file_type, DocumentRecords.QUALITY)
        document.update_metadata(f"quality_{self.checkpoint}", self.aggregate.snapshot())
        uid = processor.blackboard.write(facade=facade, processor=processor, pipeline=self)

        self.debug(
            msg=Event.Transform.name,
            step=Event.Completed.name,
            uid=uid,
            checkpoint=self.checkpoint,
            records=len(measured),
            failed=sum(len(index.failed_rules) for index in measured),
        )
        return uid


# --------------------------------------------------------------------------- #
# endregion Pipelines                                                         #
# --------------------------------------------------------------------------- #
