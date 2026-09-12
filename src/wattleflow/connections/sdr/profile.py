# Module name: connections/sdr/profile.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""Values of the SDR capability: model profile, instance, selector, read-back.

A profile declares what a model can do; an instance names the unit and the
task. Neither carries code — a new model is a new profile (HLRQ-16 §4a, BR-11).
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = [
    "Direction",
    "Duplex",
    "SampleFormat",
    "SDREffective",
    "SDRInstance",
    "SDRProfile",
    "SDRReported",
    "SDRSelector",
    "SDRTuningPlan",
]

# --------------------------------------------------------------------------- #
# region Enumerations                                                         #
# --------------------------------------------------------------------------- #


class Direction(str, Enum):
    IDLE = "idle"
    RECEIVE = "rx"
    TRANSMIT = "tx"


class Duplex(str, Enum):
    NONE = "none"
    HALF = "half"
    FULL = "full"


class SampleFormat(str, Enum):
    U8_IQ = "u8_iq"
    S8_IQ = "s8_iq"
    S16_IQ = "s16_iq"
    CF32_IQ = "cf32_iq"

    @property
    def bytes_per_sample(self) -> int:
        return {"u8_iq": 2, "s8_iq": 2, "s16_iq": 4, "cf32_iq": 8}[self.value]

    @property
    def full_scale(self) -> float:
        """Raw amplitude that maps to 1.0 unless the profile states otherwise."""
        return {"u8_iq": 127.5, "s8_iq": 128.0, "s16_iq": 32768.0, "cf32_iq": 1.0}[self.value]


# --------------------------------------------------------------------------- #
# endregion Enumerations                                                      #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Values                                                               #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SDRProfile:
    """Declared capabilities of one model, verified against the claimed unit (BR-11)."""

    REQUIRED: ClassVar[tuple[str, ...]] = (
        "model",
        "family",
        "freq_ranges",
        "sample_rates",
        "gain_stages",
        "formats",
        "directions",
    )
    # Gain tables are kept in tenths of a dB by the host libraries.
    GAIN_TOLERANCE: ClassVar[float] = 0.05

    model: Mapping[str, str]
    family: str
    freq_ranges: tuple[tuple[float, float], ...]
    sample_rates: tuple[tuple[float, float], ...]
    gain_stages: Mapping[str, tuple[float, ...]]
    formats: Mapping[SampleFormat, float]
    directions: frozenset[Direction]
    duplex: Duplex = Duplex.NONE
    requires: str | None = None
    ports: tuple[str, ...] = ()
    features: frozenset[str] = frozenset()

    @classmethod
    def from_mapping(cls, data: Any) -> SDRProfile:
        if not isinstance(data, Mapping):
            raise ValueError("profile must be a mapping")
        missing = [key for key in cls.REQUIRED if key not in data]
        if missing:
            raise ValueError(f"profile is missing {missing}")

        model = data["model"]
        if not isinstance(model, Mapping) or not model:
            raise ValueError("profile.model must be a non-empty mapping")
        stages = data["gain_stages"]
        if not isinstance(stages, Mapping):
            raise ValueError("profile.gain_stages must map a stage name to its values")

        formats: dict[SampleFormat, float] = {}
        for entry in data["formats"] or ():
            if isinstance(entry, Mapping):
                fmt = SampleFormat(entry["format"])
                formats[fmt] = float(entry.get("full_scale", fmt.full_scale))
            else:
                fmt = SampleFormat(entry)
                formats[fmt] = fmt.full_scale
        if not formats:
            raise ValueError("profile.formats must name at least one sample format")

        directions = frozenset(Direction(d) for d in data["directions"] or ())
        if not directions:
            raise ValueError("profile.directions must name at least one direction")

        return cls(
            model={str(k): str(v) for k, v in model.items()},
            family=str(data["family"]),
            freq_ranges=cls._ranges(data["freq_ranges"], "freq_ranges"),
            sample_rates=cls._ranges(data["sample_rates"], "sample_rates"),
            gain_stages={
                str(stage): tuple(float(v) for v in values) for stage, values in stages.items()
            },
            formats=formats,
            directions=directions,
            duplex=Duplex(data.get("duplex", Duplex.NONE.value)),
            requires=str(data["requires"]) if data.get("requires") else None,
            ports=tuple(str(p) for p in data.get("ports") or ()),
            features=frozenset(str(f) for f in data.get("features") or ()),
        )

    @staticmethod
    def _ranges(value: Any, key: str) -> tuple[tuple[float, float], ...]:
        ranges = []
        for pair in value or ():
            low, high = (float(v) for v in pair)
            if not low < high:
                raise ValueError(f"profile.{key}: {low} is not below {high}")
            ranges.append((low, high))
        if not ranges:
            raise ValueError(f"profile.{key} must hold at least one range")
        return tuple(ranges)

    @property
    def primary_format(self) -> SampleFormat:
        return next(iter(self.formats))

    def contains_frequency(self, hz: float) -> bool:
        """The single range check, used at load time and at read time (BR-15)."""
        return any(low <= hz <= high for low, high in self.freq_ranges)

    def allows_rate(self, sps: float) -> bool:
        return any(low <= sps <= high for low, high in self.sample_rates)

    def allows_gain(self, stage: str, value: float) -> bool:
        table = self.gain_stages.get(stage, ())
        return any(abs(value - known) < self.GAIN_TOLERANCE for known in table)


@dataclass(frozen=True)
class SDRSelector:
    """Key-value set that must resolve exactly one attached unit (BR-02)."""

    keys: Mapping[str, str]

    @classmethod
    def from_mapping(cls, data: Any) -> SDRSelector:
        if not isinstance(data, Mapping) or not data:
            raise ValueError("device must be a non-empty mapping, e.g. {serial: '00000001'}")
        return cls(keys={str(k): str(v) for k, v in data.items()})

    @property
    def family(self) -> str | None:
        return self.keys.get("family")

    def matches(self, device: Mapping[str, str]) -> bool:
        return all(
            device.get(key) == value for key, value in self.keys.items() if key != "family"
        )


@dataclass(frozen=True)
class SDRTuningPlan:
    """Frequencies a pass visits and the blocks kept at each (HLRQ-16 function 14)."""

    MAX_POINTS: ClassVar[int] = 10_000

    points: tuple[float, ...]
    dwell_blocks: int

    @classmethod
    def from_mapping(cls, data: Any) -> SDRTuningPlan:
        if not isinstance(data, Mapping):
            raise ValueError("tuning_plan must be a mapping")
        dwell = int(data.get("dwell_blocks", 0))
        if dwell < 1:
            raise ValueError("tuning_plan.dwell_blocks must be at least 1")
        if ("points" in data) == ("band" in data):
            raise ValueError("tuning_plan takes either points or band")

        if "points" in data:
            points = tuple(float(p) for p in data["points"] or ())
        else:
            start, stop, step = (float(v) for v in data["band"])
            if step <= 0 or stop < start:
                raise ValueError("tuning_plan.band must be [start, stop, step] with step > 0")
            count = int((stop - start) // step) + 1
            if count > cls.MAX_POINTS:
                raise ValueError(f"tuning_plan.band yields {count} points, over {cls.MAX_POINTS}")
            points = tuple(start + i * step for i in range(count))

        if not points or len(points) > cls.MAX_POINTS:
            raise ValueError(f"tuning_plan needs between 1 and {cls.MAX_POINTS} points")
        return cls(points=points, dwell_blocks=dwell)


@dataclass(frozen=True)
class SDRInstance:
    """The unit and the task; checked against the profile, never overriding it."""

    selector: SDRSelector
    sample_rate: float
    center_freq: float
    gain_mode: str
    gain: Mapping[str, float]
    ppm: int
    antenna: str | None
    bias_tee: bool | None
    direction: Direction
    device_timeout: float
    tuning_plan: SDRTuningPlan | None


@dataclass(frozen=True)
class SDRReported:
    """What the access mechanism says about the claimed unit (BR-11)."""

    model: Mapping[str, str]
    gain_table: Mapping[str, tuple[float, ...]]


@dataclass(frozen=True)
class SDREffective:
    """Values read back from the unit, never the requested ones (BR-05)."""

    center_freq: float
    sample_rate: float
    gain_mode: str
    gain: Mapping[str, float] | None
    ppm: int

    def as_record(self) -> dict[str, Any]:
        return {
            "center_freq": self.center_freq,
            "sample_rate": self.sample_rate,
            "gain_mode": self.gain_mode,
            "gain": dict(self.gain) if self.gain else None,
            "ppm": self.ppm,
        }


# --------------------------------------------------------------------------- #
# endregion Values                                                            #
# --------------------------------------------------------------------------- #
