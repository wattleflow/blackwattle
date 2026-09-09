# Module name: enums/metric.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
Measurement nomenclature — the counterpart of `Event` for audit records that
state HOW MUCH work was done.

`Event` names the operation, `step` its phase; neither says what was moved. A
closing record that carries `size=`, `chars=` or `pages=` is already measuring,
but each component chose its own word, so a collector had to guess among them.
`Measure` fixes that vocabulary and, with it, the unit and the series a value
belongs to — so a number cannot arrive without saying what it counts.

Adding a member extends a controlled vocabulary and goes through a DR (D-12).
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from enum import Enum
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["Measure", "MetricKind"]

# --------------------------------------------------------------------------- #
# region Enumerations                                                         #
# --------------------------------------------------------------------------- #


class MetricKind(str, Enum):
    """How a series behaves, in Prometheus' own terms."""

    COUNTER = "counter"  # monotonic; `rate()` is meaningful
    GAUGE = "gauge"  # a level that rises and falls
    HISTOGRAM = "histogram"  # a distribution: buckets + sum + count


class Measure(str, Enum):
    """A quantity an audit record may state, with its unit and its series.

    The member value is the FIELD NAME as it appears in the record, so a
    collector reads `Measure.Bytes.value` rather than a literal. `unit` and
    `series` travel with it because a count without a unit is not a measurement
    (`NFRQ-OBS-04` c.2), and a value with no series has nowhere to go.
    """

    Bytes = ("bytes", "bytes", "wf_bytes_total")
    Size = ("size", "bytes", "wf_bytes_total")  # what the file drivers already write
    Documents = ("documents", "documents", "wf_documents_total")
    Cycles = ("cycles", "documents", "wf_documents_total")  # the processor's own word
    Characters = ("chars", "characters", "wf_characters_total")
    Pages = ("pages", "pages", "wf_pages_total")
    Records = ("records", "records", "wf_records_total")
    Rows = ("rows", "rows", "wf_records_total")
    Files = ("files", "files", "wf_files_total")

    def __new__(cls, field: str, unit: str, series: str):
        member = str.__new__(cls, field)
        member._value_ = field
        member.unit = unit
        member.series = series
        return member

    @classmethod
    def fields(cls) -> tuple[str, ...]:
        """Every field name a closing record may use to state a quantity."""
        return tuple(member.value for member in cls)

    @classmethod
    def resolve(cls, field: str) -> "Measure | None":
        """The member for a record's field name, or None when it states none."""
        return _LOOKUP.get(str(field or "").strip().lower())


_LOOKUP: dict[str, Measure] = {member.value.lower(): member for member in Measure}


# --------------------------------------------------------------------------- #
# endregion Enumerations                                                      #
# --------------------------------------------------------------------------- #
