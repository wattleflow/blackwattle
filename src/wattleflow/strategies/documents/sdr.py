# Module name: strategies/documents/sdr.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""Genesis of a captured segment (FRQ-DOC-16.4).

The processor hands over what it received; this gives it shape. Neither the
connection, the driver nor the processor decides what the bytes mean — the
strategy does, and only it stamps provenance (author, 2026-09-12). The same
strategy serves any source of the same bytes: a tuner, a broker, a file.

Two of them, and the configuration chooses: one keeps the bytes as they came,
one converts them into the working form a pipeline reads (author, 2026-09-12).
Conversion costs bytes, not time — see the analysis of the recording format.
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from collections.abc import Mapping
from typing import Any, Optional
from wattleflow.core import IBlackboard, ITarget, IWattleflow
from wattleflow.concrete import DocumentFacade, StrategyCreate
from wattleflow.concrete.exception import StrategyException
from wattleflow.connections.sdr.profile import SampleFormat
from wattleflow.documents.dataframe import DataFrameDocument
from wattleflow.documents.sdr import SDRSampleDocument
from wattleflow.helpers.parsers.iq import IQSampleParser
from wattleflow.enums.event import Event
from wattleflow.helpers.dtime import Now
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["CreateSDRDataframeDocument", "CreateSDRSampleDocument"]
# Written by the document itself on every change; a caller may not set them.
AUDIT_KEYS = ("last_change_key", "last_change_time")
# Wiring, not provenance: these never become metadata of their own.
RESERVED_KWARGS = ("caller", "content", "metadata", "processor", "blackboard")

# --------------------------------------------------------------------------- #
# region Strategies                                                           #
# --------------------------------------------------------------------------- #


class CreateSDRSampleDocument(StrategyCreate):
    def execute(self, caller: IWattleflow, **kwargs: Any) -> Optional[ITarget]:
        try:
            self.debug(msg=Event.Create.name, step=Event.Started.name)
            if not isinstance(caller, IBlackboard):
                raise TypeError(f"Expected IBlackboard. Found {type(caller).__name__}")

            content = kwargs.get("content")
            if not isinstance(content, (bytes, bytearray, memoryview)):
                raise TypeError(
                    f"content must be the captured bytes; found {type(content).__name__}"
                )
            description = kwargs.get("metadata") or {}
            if not isinstance(description, Mapping):
                raise TypeError("metadata must be the sampling description, as a mapping")

            document = SDRSampleDocument(
                content=bytes(content),
                level=self._level,
                handler=self._handler,
            )
            for key, value in description.items():
                document.update_metadata(str(key), value)
            document.update_metadata("created_by", self.name)
            document.update_metadata("created_at", Now.utc())
            document.update_metadata("caller", caller.name)
            document.update_metadata("source_format", "iq_samples")
            for key, value in kwargs.items():
                if key not in RESERVED_KWARGS:
                    document.update_metadata(f"kwargs_{key}", value)

            if not document.size:
                # An empty segment describes nothing; the pass says so once.
                self.warning(
                    msg=Event.Create.name,
                    step=Event.Check.name,
                    reason="no sample_count in the description",
                    document=document.identifier,
                )

            self.debug(
                msg=Event.Create.name,
                step=Event.Completed.name,
                document=document.identifier,
                samples=document.size,
                format=document.format,
            )
            return DocumentFacade(document)
        except (TypeError, ValueError) as e:
            error = f"{self.name} refused the segment: {e}"
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e


class CreateSDRDataframeDocument(CreateSDRSampleDocument):
    """The same segment as a table: one row per sample, `i` and `q` in full scale.

    The working form pipelines read (author, 2026-09-11: a DataFrame wherever it
    fits). The description stays in metadata, so the table carries data only.
    """

    ALLOWED = ["column", "full_scale"]

    @staticmethod
    def _is_frame(content: Any) -> bool:
        """A table already, whoever converted it — asked without importing pandas."""
        return type(content).__name__ == "DataFrame"

    def execute(self, caller: IWattleflow, **kwargs: Any) -> Optional[ITarget]:
        content = kwargs.get("content")
        if self._is_frame(content):
            # The driver was configured to convert; nothing left to do but stamp it.
            frame, description = content, dict(kwargs.get("metadata") or {})
        else:
            facade = super().execute(caller, **kwargs)
            document = facade.request()
            description = dict(document.metadata)
            try:
                frame = self._frame(document.content, description)
            except (ImportError, KeyError, TypeError, ValueError) as e:
                error = f"{self.name} cannot build the table: {e}"
                self.debug(msg=Event.Create.name, step=Event.Failed.name, error=error)
                raise StrategyException(self, error=error, exc=e) from e

        table = DataFrameDocument(content=frame, level=self._level, handler=self._handler)
        for key, value in description.items():
            if key not in AUDIT_KEYS:
                table.update_metadata(str(key), value)
        table.update_metadata("created_by", self.name)
        table.update_metadata("source_format", "iq_table")
        self.debug(
            msg=Event.Create.name,
            step=Event.Completed.name,
            document=table.identifier,
            rows=len(frame),
        )
        return DocumentFacade(table)

    @staticmethod
    def _frame(payload: bytes, description: Mapping[str, Any]) -> Any:
        fmt = SampleFormat(str(description.get("format") or SampleFormat.U8_IQ.value))
        return IQSampleParser.frame(payload, fmt, description.get("full_scale"))


# --------------------------------------------------------------------------- #
# endregion Strategies                                                        #
# --------------------------------------------------------------------------- #
