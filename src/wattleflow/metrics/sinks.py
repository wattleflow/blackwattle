# Module name: metrics/sinks.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
Metric destinations — `FRQ-MET-01`.

A sink FORMATS for one destination; the driver ships it. That split is the same
one documents already follow: a write strategy renders, a driver writes
(`FRQ-PRC-15.22`). Nothing here accumulates or derives — by the time samples
arrive they are final.
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from typing import Any, ClassVar, Sequence
from wattleflow.enums.metric import MetricKind
from wattleflow.helpers.metrics import MetricSample, MetricSink
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["GrafanaSink", "PrometheusSink", "SinkError"]


class SinkError(RuntimeError):
    """A destination refused the samples it was given."""


# --------------------------------------------------------------------------- #
# region Sinks                                                                #
# --------------------------------------------------------------------------- #


class PrometheusSink(MetricSink):
    """Push exposition 0.0.4 to a Pushgateway, through `DriverPrometheus`.

    Built as TEXT rather than through the driver's structured path: that path
    emits only `name{labels} value` and drops `# TYPE` / `# HELP`, and a
    histogram is not a histogram to Prometheus without its type.
    """

    #: Pushgateway holds the LAST value per grouping and is meant for jobs that
    #: end. One push per run, never per document.
    DEFAULT_JOB: ClassVar[str] = "wattleflow"

    def __init__(self, driver: Any, job: str | None = None, instance: str | None = None) -> None:
        self._driver = driver
        self.job = job or self.DEFAULT_JOB
        self.instance = instance

    # region Private

    @staticmethod
    def _labels(labels: dict[str, str], extra: dict[str, str] | None = None) -> str:
        merged = {**labels, **(extra or {})}
        if not merged:
            return ""
        inner = ",".join(f'{k}="{str(v)}"' for k, v in sorted(merged.items()))
        return "{" + inner + "}"

    def _series(self, sample: MetricSample) -> list[str]:
        """The sample's own lines, WITHOUT `# HELP` / `# TYPE`."""
        out: list[str] = []
        if sample.kind is MetricKind.HISTOGRAM and sample.buckets:
            for edge, count in sample.buckets.items():
                out.append(
                    f"{sample.name}_bucket{self._labels(dict(sample.labels), {'le': edge})} {count}"
                )
            out.append(f"{sample.name}_sum{self._labels(dict(sample.labels))} {sample.value}")
            out.append(
                f"{sample.name}_count{self._labels(dict(sample.labels))} "
                f"{sample.buckets.get('+Inf', 0)}"
            )
            return out
        out.append(f"{sample.name}{self._labels(dict(sample.labels))} {sample.value}")
        return out

    def exposition(self, samples: Sequence[MetricSample]) -> str:
        """The payload, exposed so it can be inspected without a Pushgateway.

        `# HELP` and `# TYPE` are emitted once per METRIC NAME, not once per
        sample: a second HELP line for the same name is a parse error, and the
        gateway rejects the whole push with 400 — measured, not assumed.
        """
        grouped: dict[str, list[MetricSample]] = {}
        for sample in samples:
            grouped.setdefault(sample.name, []).append(sample)

        lines: list[str] = []
        for name, group in grouped.items():
            head = group[0]
            lines.append(f"# HELP {name} wattleflow {head.unit or 'value'}")
            lines.append(f"# TYPE {name} {head.kind.value}")
            for sample in group:
                lines.extend(self._series(sample))
        return "\n".join(lines) + "\n"

    # endregion Private

    def publish(self, samples: Sequence[MetricSample]) -> bool:
        if not samples:
            return False
        uri = f"{self.job}:{self.instance}" if self.instance else self.job
        self._driver.write(uri, self.exposition(samples), mode="replace")
        return True

    def __repr__(self) -> str:
        return f"PrometheusSink[job={self.job}]"


class GrafanaSink(MetricSink):
    """Annotate a run on Grafana's timeline, through `DriverGrafana`.

    Annotations, not storage: they answer "what happened here" beside a graph
    whose numbers come from Prometheus.
    """

    def __init__(self, driver: Any, tags: Sequence[str] | None = None) -> None:
        self._driver = driver
        self.tags = list(tags or ["wattleflow"])

    def publish(self, samples: Sequence[MetricSample]) -> bool:
        if not samples:
            return False
        failures = sum(
            s.value
            for s in samples
            if s.name == "wf_operations_total" and s.labels.get("outcome") == "failed"
        )
        operations = sum(s.value for s in samples if s.name == "wf_operations_total")
        self._driver.write(
            "annotation",
            {
                "text": f"wattleflow run — {int(operations)} operations, {int(failures)} failed",
                "tags": self.tags + (["failed"] if failures else ["ok"]),
            },
        )
        return True

    def __repr__(self) -> str:
        return f"GrafanaSink[tags={self.tags}]"


# --------------------------------------------------------------------------- #
# endregion Sinks                                                             #
# --------------------------------------------------------------------------- #
