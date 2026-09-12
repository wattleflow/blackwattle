# Module name: processors/sdr.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""SDRReadProcessor — a capture pass over a stream that never ends (FRQ-PRC-16.3).

Capture, not processing: demodulation and decoding are pipelines. Transmit does
not need a processor of its own — a document reaches the unit through a
repository whose strategy calls the driver's `write` (author, 2026-09-11).
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import time
from collections.abc import Generator
from dataclasses import asdict, dataclass
from typing import Any, ClassVar
from wattleflow.concrete.exception import ProcessorException
from wattleflow.concrete.processor import GenericProcessor
from wattleflow.core import ITarget
from wattleflow.enums.event import Event
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["SDRPassSummary", "SDRReadProcessor"]


@dataclass
class SDRPassSummary:
    """One record per pass (NFRQ-OBS-03): what was captured and whether it is whole."""

    blocks: int = 0
    samples: int = 0
    documents: int = 0
    duration: float = 0.0
    lost: int | None = None
    effective: dict[str, Any] | None = None
    partial: bool = False
    reason: str | None = None

    def as_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["lost"] = "unmeasured" if self.lost is None else self.lost
        return record


class SDRReadProcessor(GenericProcessor):
    ALLOWED = ["driver", "stop_blocks", "stop_seconds", "segment_blocks"]
    SEGMENT_BLOCKS: ClassVar[int] = 1

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._summary = SDRPassSummary()
        self._stop_blocks = self._positive("stop_blocks", int)
        self._stop_seconds = self._positive("stop_seconds", float)
        self._segment_blocks = self._positive("segment_blocks", int) or self.SEGMENT_BLOCKS
        if self._stop_blocks is None and self._stop_seconds is None:
            raise ProcessorException(
                caller=self,
                error="a capture boundary is required: stop_blocks or stop_seconds (BR-08)",
            )
        if self.driver is None:
            raise ProcessorException(caller=self, error="driver is required")

    @property
    def summary(self) -> SDRPassSummary:
        return self._summary

    def _positive(self, key: str, kind: type) -> Any:
        value = getattr(self, key)
        if value is None:
            return None
        value = kind(value)
        if value <= 0:
            raise ProcessorException(caller=self, error=f"{key} must be positive")
        return value

    def _reached(self, summary: SDRPassSummary, started: float) -> bool:
        if self._stop_blocks is not None and summary.blocks >= self._stop_blocks:
            return True
        return self._stop_seconds is not None and time.monotonic() - started >= self._stop_seconds

    def _emit(self, segment: list) -> ITarget:
        """The segment as it came off the unit; what it MEANS is the strategy's business."""
        first = segment[0]
        content = first.payload if len(segment) == 1 else self._joined(segment)
        metadata = first.description()
        metadata.update(
            sample_count=sum(block.sample_count for block in segment),
            bytes=sum(block.raw_bytes for block in segment),
            blocks=len(segment),
            loss_measured=first.lost_before is not None,
        )
        self._summary.documents += 1
        return self.blackboard.create(caller=self, content=content, metadata=metadata)

    @staticmethod
    def _joined(segment: list) -> Any:
        """One segment out of several blocks, in whatever form the driver delivered."""
        if isinstance(segment[0].payload, (bytes, bytearray, memoryview)):
            return b"".join(bytes(block.payload) for block in segment)
        import pandas

        return pandas.concat([block.payload for block in segment], ignore_index=True)

    def _close(self, blocks: Any, started: float, reason: str | None = None) -> None:
        summary = self._summary
        if blocks is not None:
            # Ends the stream session; the claim itself stays with the connection.
            blocks.close()
        summary.duration = round(time.monotonic() - started, 3)
        effective = getattr(self.driver, "effective", None)
        summary.effective = effective.as_record() if effective else None
        if reason is not None:
            summary.partial = True
            summary.reason = reason
        if summary.partial:
            self.warning(msg=Event.Finished.name, summary=summary.as_record())
        else:
            self.info(msg=Event.Finished.name, summary=summary.as_record())

    def create_generator(self) -> Generator[ITarget, None, None]:
        summary = self._summary = SDRPassSummary()
        started = time.monotonic()
        segment: list = []
        blocks = None
        try:
            # The unit is claimed before the first document (BR-06).
            self.driver.ensure_live()
            blocks = self.driver.read(uri="")
            for block in blocks:
                summary.blocks += 1
                summary.samples += block.sample_count
                summary.lost = block.lost_before
                # One document never spans two frequencies.
                if segment and block.center_freq != segment[-1].center_freq:
                    yield self._emit(segment)
                    segment = []
                segment.append(block)
                if len(segment) >= self._segment_blocks:
                    yield self._emit(segment)
                    segment = []
                if self._reached(summary, started):
                    break
            if segment:
                yield self._emit(segment)
        except GeneratorExit:
            self.debug(msg=Event.Generate.name, step=Event.Failed.name, error="closed early")
            self._close(blocks, started, reason="pass ended before its boundary")
            raise
        except Exception as e:
            self.debug(msg=Event.Generate.name, step=Event.Failed.name, error=type(e).__name__)
            self._close(blocks, started, reason=f"{type(e).__name__}: {e}")
            raise ProcessorException(
                caller=self, error=f"capture failed: {type(e).__name__}: {e}"
            ) from e
        self._close(blocks, started)
