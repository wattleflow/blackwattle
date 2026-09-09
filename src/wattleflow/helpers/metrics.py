# Module name: helpers/metrics.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
Metric collection — `FRQ-MET-01`, decomposition per its class diagram.

Nothing here is measured by a component. A method that writes `step=Started`
and `step=Completed`|`Failed` has already bracketed its own duration, because
every record carries `record.created`; the closing record usually carries the
quantity as well. This module pairs those records, corrects what the code got
wrong, and derives the series — so a component never learns that a monitor
exists.

Transport is NOT here: a sink formats, a driver ships (`FRQ-PRC-15.22`). This
module therefore imports stdlib and `wattleflow.enums` only, and holds no edge
to a domain package (`NFRQ-ORG-01`).
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import logging
import re
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from typing import ClassVar, Iterable, Mapping, Sequence
from wattleflow.enums.metric import Measure, MetricKind
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = [
    "MetricCollector",
    "MetricReporter",
    "MetricSample",
    "MetricSet",
    "MetricSink",
    "MetricSpan",
]

# --------------------------------------------------------------------------- #
# region Values                                                               #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class MetricSpan:
    """One measured operation, read off a `Started`/`Completed`|`Failed` pair.

    `depth` is what makes exclusive time computable: layers nest, and the same
    work is otherwise reported once per layer (`NFRQ-OBS-04` c.6).
    """

    component: str
    method: str
    event: str
    outcome: str  # "completed" | "failed" | "expired"
    started: float
    seconds: float
    quantity: int | None = None
    measure: Measure | None = None
    depth: int = 0

    @property
    def ok(self) -> bool:
        return self.outcome == "completed"


@dataclass(frozen=True, slots=True)
class MetricSample:
    """One published series point.

    `buckets` is what separates a distribution from a number: a mean is derived
    at query time (`rate(_sum)/rate(_count)`), never stored (`NFRQ-OBS-04` c.1).
    """

    name: str
    kind: MetricKind
    labels: Mapping[str, str] = field(default_factory=dict)
    value: float = 0.0
    buckets: Mapping[str, int] | None = None
    unit: str = ""


# --------------------------------------------------------------------------- #
# endregion Values                                                            #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Accumulation                                                         #
# --------------------------------------------------------------------------- #


class MetricSet:
    """Owns the derivation: counters, buckets, throughput.

    Nothing arrives here already aggregated, so a published figure can never
    disagree with the figures it came from.
    """

    #: Seconds. Coarse and provisional — Shewhart wants limits computed from the
    #: process, and no history exists yet (`NFRQ-OBS-04` §6 t.2).
    BUCKETS: ClassVar[tuple[float, ...]] = (0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0)

    def __init__(self) -> None:
        self._spans: list[MetricSpan] = []
        self._open = 0
        self._dropped = 0

    def record(self, span: MetricSpan) -> None:
        self._spans.append(span)

    def note_open(self, count: int) -> None:
        self._open = count

    def note_dropped(self, count: int = 1) -> None:
        self._dropped += count

    def clear(self) -> None:
        self._spans.clear()

    # region Derivation

    def _histogram(self, seconds: Sequence[float]) -> tuple[dict[str, int], float, int]:
        buckets: dict[str, int] = {}
        running = 0
        for edge in self.BUCKETS:
            running = sum(1 for s in seconds if s <= edge)
            buckets[str(edge)] = running
        buckets["+Inf"] = len(seconds)
        return buckets, sum(seconds), len(seconds)

    def samples(self) -> list[MetricSample]:
        """Every series this run produced."""
        out: list[MetricSample] = []

        operations: dict[tuple[str, str, str], int] = defaultdict(int)
        durations: dict[tuple[str, str], list[float]] = defaultdict(list)
        quantities: dict[tuple[str, str, str], int] = defaultdict(int)

        for span in self._spans:
            operations[(span.component, span.method, span.outcome)] += 1
            durations[(span.component, span.method)].append(span.seconds)
            if span.quantity is not None and span.measure is not None:
                quantities[(span.measure.series, span.component, span.measure.unit)] += (
                    span.quantity
                )

        for (component, method, outcome), count in sorted(operations.items()):
            out.append(
                MetricSample(
                    name="wf_operations_total",
                    kind=MetricKind.COUNTER,
                    labels={"component": component, "method": method, "outcome": outcome},
                    value=float(count),
                    unit="operations",
                )
            )

        for (component, method), seconds in sorted(durations.items()):
            buckets, total, count = self._histogram(seconds)
            out.append(
                MetricSample(
                    name="wf_operation_seconds",
                    kind=MetricKind.HISTOGRAM,
                    # `scope` is inclusive: a layer's span contains the layers
                    # below it. Only exclusive time may be summed, and that
                    # decision is still open (`FRQ-MET-01` §12 t.2).
                    labels={"component": component, "method": method, "scope": "inclusive"},
                    value=total,
                    buckets=buckets,
                    unit="seconds",
                )
            )

        for (series, component, unit), total in sorted(quantities.items()):
            out.append(
                MetricSample(
                    name=series,
                    kind=MetricKind.COUNTER,
                    labels={"component": component},
                    value=float(total),
                    unit=unit,
                )
            )

        return out + self.health()

    def health(self) -> list[MetricSample]:
        """What the measurement could not measure — never left to look like zero."""
        return [
            MetricSample("wf_open_spans", MetricKind.GAUGE, {}, float(self._open), unit="spans"),
            MetricSample(
                "wf_dropped_spans_total",
                MetricKind.COUNTER,
                {},
                float(self._dropped),
                unit="spans",
            ),
        ]

    # endregion Derivation


# --------------------------------------------------------------------------- #
# endregion Accumulation                                                      #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Collector                                                            #
# --------------------------------------------------------------------------- #


class MetricCollector(logging.Handler):
    """Purpose-built handler: pairs spans, corrects them, feeds a `MetricSet`.

    `format()` is deliberately never called — this wants the record, not a line
    of text. Only `emit` is overridden; the base contributes the level gate,
    filters and its own lock.
    """

    EVENT: ClassVar[re.Pattern[str]] = re.compile(r"^(\w+)")
    FIELD: ClassVar[re.Pattern[str]] = re.compile(r"'(\w+)=([^']*)'")
    OPENING: ClassVar[frozenset[str]] = frozenset({"Started", "Starting"})
    CLOSING: ClassVar[frozenset[str]] = frozenset({"Completed", "Failed"})
    DEFAULT_TTL: ClassVar[float] = 30.0

    def __init__(self, metrics: MetricSet | None = None, ttl: float | None = None) -> None:
        super().__init__(logging.DEBUG)
        self.metrics = metrics if metrics is not None else MetricSet()
        self.ttl = self.DEFAULT_TTL if ttl is None else float(ttl)
        self._open: dict[tuple[str, str, str], list[float]] = {}

    # region Private

    def _fields(self, record: logging.LogRecord) -> dict[str, str]:
        """Named fields of the record.

        `extra` first: when the audit layer passes the fields through, they are
        attributes and nothing needs parsing. The message is the fallback,
        because today `_log_msg` flattens them into the text before any handler
        sees them (`FRQ-MET-01` §12).
        """
        carried = getattr(record, "wf_fields", None)
        if isinstance(carried, Mapping):
            return {str(k): str(v) for k, v in carried.items()}
        return dict(self.FIELD.findall(record.getMessage()))

    def _quantity(self, fields: Mapping[str, str]) -> tuple[int | None, Measure | None]:
        for name, raw in fields.items():
            measure = Measure.resolve(name)
            if measure is None:
                continue
            text = str(raw).strip()
            if text.lstrip("-").isdigit():
                return int(text), measure
        return None, None

    def _expire(self, now: float) -> None:
        for key, stack in list(self._open.items()):
            kept = [t for t in stack if now - t <= self.ttl]
            self.metrics.note_dropped(len(stack) - len(kept))
            if kept:
                self._open[key] = kept
            else:
                self._open.pop(key)

    # endregion Private

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102 - overrides Handler
        try:
            match = self.EVENT.match(record.getMessage())
            if match is None:
                return
            fields = self._fields(record)
            step = fields.get("step")
            if step not in self.OPENING and step not in self.CLOSING:
                return

            key = (record.name, record.funcName, match.group(1))
            if step in self.OPENING:
                # A second opening in one method is the code's defect, not the
                # measurement's: keep the first and count the surplus.
                stack = self._open.setdefault(key, [])
                if stack:
                    self.metrics.note_dropped()
                else:
                    stack.append(record.created)
            else:
                stack = self._open.get(key)
                if not stack:
                    return
                started = stack.pop()
                if not stack:
                    self._open.pop(key, None)
                quantity, measure = self._quantity(fields)
                self.metrics.record(
                    MetricSpan(
                        component=record.name,
                        method=record.funcName,
                        event=match.group(1),
                        outcome="failed" if step == "Failed" else "completed",
                        started=started,
                        seconds=record.created - started,
                        quantity=quantity,
                        measure=measure,
                        depth=len(self._open),
                    )
                )

            self._expire(record.created)
            self.metrics.note_open(sum(len(v) for v in self._open.values()))
        except Exception:
            self.handleError(record)


# --------------------------------------------------------------------------- #
# endregion Collector                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Destinations                                                         #
# --------------------------------------------------------------------------- #


class MetricSink(ABC):
    """One destination. It formats; a driver ships."""

    @abstractmethod
    def publish(self, samples: Sequence[MetricSample]) -> bool: ...


class MetricReporter:
    """Holds N destinations over ONE sample set.

    The fan-out `FRQ-PRC-15.22` already uses for documents: a failing
    destination is reported and the others are still visited — monitoring must
    not be able to stop the run it is watching.
    """

    def __init__(self, ttl: float | None = None) -> None:
        self.metrics = MetricSet()
        self.collector = MetricCollector(self.metrics, ttl=ttl)
        self._sinks: list[MetricSink] = []

    def register(self, sink: MetricSink) -> "MetricReporter":
        self._sinks.append(sink)
        return self

    def attach(self, *loggers: logging.Logger) -> None:
        for logger in loggers:
            if self.collector not in logger.handlers:
                logger.addHandler(self.collector)

    def report(self) -> list[tuple[MetricSink, bool | Exception]]:
        samples = self.metrics.samples()
        outcome: list[tuple[MetricSink, bool | Exception]] = []
        for sink in self._sinks:
            try:
                outcome.append((sink, sink.publish(samples)))
            except Exception as e:
                outcome.append((sink, e))
        return outcome

    def spans(self) -> Iterable[MetricSpan]:
        return tuple(self.metrics._spans)

    def __repr__(self) -> str:
        return f"MetricReporter[sinks={len(self._sinks)}, spans={len(self.metrics._spans)}]"


# --------------------------------------------------------------------------- #
# endregion Destinations                                                      #
# --------------------------------------------------------------------------- #
