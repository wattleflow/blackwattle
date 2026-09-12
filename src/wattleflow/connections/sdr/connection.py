# Module name: connections/sdr/connection.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""SDRConnection — exclusive claim of one radio unit (FRQ-CON-16.1).

The connection holds the unit and its parameters, never its samples. One class
serves every family: model differences live in the profile, family differences
in the backend helper (HLRQ-16 §4a). Direction and the tuning plan are state of
this layer (author, 2026-09-11).
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import itertools
import time
from collections.abc import Generator, Iterator, Mapping
from contextlib import contextmanager
from typing import Any, ClassVar
from wattleflow.concrete.connection import ConnectionAction, GenericConnection
from wattleflow.enums.event import Event
from .backend import SDRBackend
from .errors import (
    SDRConfigurationError,
    SDRConnectionError,
    SDRDeviceAmbiguous,
    SDRDeviceBusy,
    SDRDeviceNotFound,
    SDRFrequencyOutOfRange,
    SDRModelUnsupported,
    SDRProfileMismatch,
)
from .profile import (
    Direction,
    SDREffective,
    SDRInstance,
    SDRProfile,
    SDRReported,
    SDRSelector,
    SDRTuningPlan,
)
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["SDRConnection"]


class SDRConnection(GenericConnection):
    ALLOWED = [
        "connection_name",
        "lazy_loading",
        "device",
        "profile",
        "sample_rate",
        "center_freq",
        "gain_mode",
        "gain",
        "ppm",
        "antenna",
        "bias_tee",
        "direction",
        "authorisation",
        "device_timeout",
        "tuning_plan",
    ]
    GAIN_MODES: ClassVar[frozenset[str]] = frozenset({"auto", "manual"})
    # Seconds between claim attempts while the unit is busy (BR-03).
    CLAIM_RETRY: ClassVar[float] = 0.25

    def __init__(self, **kwargs) -> None:
        # Raw options are kept apart from the preset: `profile`, `direction` and
        # `tuning_plan` are also the names of the validated values exposed below.
        # Assigned first because the base constructor may claim the unit.
        self._options: dict[str, Any] = dict(kwargs)
        self._backend: SDRBackend | None = None
        self._profile: SDRProfile | None = None
        self._instance: SDRInstance | None = None
        self._effective: SDREffective | None = None
        super().__init__(**kwargs)

    # region Properties

    @property
    def backend(self) -> SDRBackend | None:
        return self._backend

    @property
    def profile(self) -> SDRProfile | None:
        return self._profile

    @property
    def effective(self) -> SDREffective | None:
        return self._effective

    @property
    def direction(self) -> Direction | None:
        return self._instance.direction if self._instance else None

    @property
    def tuning_plan(self) -> SDRTuningPlan | None:
        return self._instance.tuning_plan if self._instance else None

    # endregion Properties

    # region Configuration

    def _required(self, key: str) -> Any:
        value = self._options.get(key)
        if value is None:
            raise ValueError(f"{key} is required")
        return value

    def _gain(self) -> dict[str, float]:
        gain = self._options.get("gain") or {}
        if not isinstance(gain, Mapping):
            raise ValueError("gain must map each stage named in the profile to a value (BR-04)")
        return {str(stage): float(value) for stage, value in gain.items()}

    def _configure(self) -> tuple[SDRProfile, SDRInstance]:
        options = self._options
        try:
            profile = SDRProfile.from_mapping(options.get("profile"))
            plan = options.get("tuning_plan")
            instance = SDRInstance(
                selector=SDRSelector.from_mapping(options.get("device")),
                sample_rate=float(self._required("sample_rate")),
                center_freq=float(self._required("center_freq")),
                gain_mode=str(options.get("gain_mode") or "auto").lower(),
                gain=self._gain(),
                ppm=int(options.get("ppm") or 0),
                antenna=options.get("antenna"),
                bias_tee=options.get("bias_tee"),
                direction=Direction(options.get("direction") or Direction.RECEIVE.value),
                device_timeout=float(options.get("device_timeout") or 0.0),
                tuning_plan=SDRTuningPlan.from_mapping(plan) if plan else None,
            )
        except (TypeError, ValueError, KeyError) as e:
            self.debug(msg=Event.Configure.name, step=Event.Failed.name, error=str(e))
            raise SDRConfigurationError(
                caller=self, error=f"invalid SDR configuration: {e}"
            ) from e
        self._check(profile, instance)
        return profile, instance

    def _check(self, profile: SDRProfile, instance: SDRInstance) -> None:
        """An instance never overrides its profile (FRQ-CON-16.1 §1, rule 1)."""

        def outside(reason: str) -> SDRConfigurationError:
            return SDRConfigurationError(caller=self, error=reason)

        if instance.selector.family not in (None, profile.family):
            raise outside(f"device family {instance.selector.family!r} is not {profile.family!r}")
        if instance.direction not in profile.directions:
            raise outside(f"direction {instance.direction.value!r} is not declared by the profile")
        if instance.direction is Direction.TRANSMIT:
            # NFRQ-SEC-07: no family backend transmits yet (HackRF is phase 2).
            raise outside("transmit is not available: no family backend implements it")
        if not profile.allows_rate(instance.sample_rate):
            raise outside(f"sample_rate {instance.sample_rate:.0f} is not allowed by the profile")
        if instance.gain_mode not in self.GAIN_MODES:
            raise outside(f"gain_mode must be one of {sorted(self.GAIN_MODES)}")
        if instance.gain_mode == "manual":
            if not instance.gain:
                raise outside("manual gain needs a value for each stage (BR-04)")
            for stage, value in instance.gain.items():
                if not profile.allows_gain(stage, value):
                    raise outside(f"gain {stage}={value} is not in the profile table")
        if instance.antenna is not None and instance.antenna not in profile.ports:
            raise outside(f"antenna {instance.antenna!r} is not a profile port")
        if instance.bias_tee and "bias_tee" not in profile.features:
            raise outside("bias_tee is not a profile feature")
        if instance.device_timeout < 0:
            raise outside("device_timeout must not be negative")

        plan = instance.tuning_plan.points if instance.tuning_plan else ()
        for hz in (instance.center_freq, *plan):
            if not profile.contains_frequency(hz):
                raise SDRFrequencyOutOfRange(
                    caller=self,
                    error=f"{hz:.0f} Hz is outside {list(profile.freq_ranges)} (BR-15)",
                )

    # endregion Configuration

    # region Claim

    @staticmethod
    def _version(text: str) -> tuple[int, ...]:
        parts = []
        for piece in text.split("."):
            digits = "".join(itertools.takewhile(str.isdigit, piece))
            if not digits:
                break
            parts.append(int(digits))
        return tuple(parts)

    def _require(self, backend: SDRBackend, profile: SDRProfile) -> None:
        if not profile.requires:
            return
        found = backend.version()
        if found is None or self._version(found) < self._version(profile.requires):
            raise SDRModelUnsupported(
                caller=self,
                error=f"profile requires {backend.DISTRIBUTION} >= {profile.requires}, "
                f"found {found} (BR-14)",
            )

    def _resolve(self, backend: SDRBackend, selector: SDRSelector) -> dict[str, str]:
        devices = backend.enumerate()
        matches = [device for device in devices if selector.matches(device)]
        if not matches:
            raise SDRDeviceNotFound(
                caller=self,
                error=f"no unit matches {dict(selector.keys)}; attached: {len(devices)} (BR-02)",
            )
        if len(matches) > 1:
            raise SDRDeviceAmbiguous(
                caller=self,
                error=f"{len(matches)} units match {dict(selector.keys)}; "
                "add a key that tells them apart (BR-02)",
            )
        return matches[0]

    def _claim(self, backend: SDRBackend, device: dict[str, str], timeout: float) -> Any:
        deadline = time.monotonic() + timeout
        while True:
            try:
                return backend.claim(device)
            except SDRDeviceBusy as e:
                if time.monotonic() >= deadline:
                    self.debug(
                        msg=Event.Connect.name, step=Event.Failed.name, error=str(e), timeout=timeout
                    )
                    raise
                time.sleep(self.CLAIM_RETRY)

    def _verify(self, profile: SDRProfile, reported: SDRReported) -> None:
        for key, declared in profile.model.items():
            if reported.model.get(key) != declared:
                raise SDRProfileMismatch(
                    caller=self,
                    error=f"profile declares {key}={declared!r}, "
                    f"unit reports {reported.model.get(key)!r} (BR-11)",
                )
        for stage, table in reported.gain_table.items():
            declared = sorted(profile.gain_stages.get(stage, ()))
            if len(declared) != len(table) or any(
                abs(a - b) >= profile.GAIN_TOLERANCE for a, b in zip(declared, sorted(table), strict=True)
            ):
                raise SDRProfileMismatch(
                    caller=self,
                    error=f"gain stage {stage!r}: profile and unit tables differ (BR-11)",
                )

    @staticmethod
    def _release_quietly(backend: SDRBackend, session: Any) -> None:
        try:
            backend.release(session)
        except Exception:  # noqa: S110 — the original failure is the one to report
            pass

    # endregion Claim

    # region GenericConnection API

    def create_connection(self) -> None:
        self.debug(
            msg=Event.Create.name, step=Event.Started.name, connection_name=self.connection_name
        )
        profile, instance = self._configure()
        backend = SDRBackend.for_family(profile.family, owner=self)
        self._require(backend, profile)
        device = self._resolve(backend, instance.selector)
        session = self._claim(backend, device, instance.device_timeout)
        try:
            reported = backend.report(session)
            self._verify(profile, reported)
            if not backend.supports(reported.model):
                raise SDRModelUnsupported(
                    caller=self,
                    error=f"{backend.FAMILY} backend does not support {dict(reported.model)} "
                    "(BR-14)",
                )
            backend.apply(session, instance)
            effective = backend.read_back(session)
        except BaseException as e:
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=f"{type(e).__name__}: {e}")
            self._release_quietly(backend, session)
            raise

        self._backend = backend
        self._profile = profile
        self._instance = instance
        self._effective = effective
        self._engine = session
        self.debug(
            msg=Event.Create.name,
            step=Event.Completed.name,
            connection_name=self.connection_name,
            family=backend.FAMILY,
            effective=effective.as_record(),
        )

    @contextmanager
    def connect(self) -> Generator[Any, None, None]:
        self._ensure_created()
        if self._engine is None:
            raise SDRConnectionError(
                caller=self, error=f"{self.connection_name}: no unit is claimed"
            )
        self._fsm.apply(ConnectionAction.CONNECT)
        self._fsm.apply(ConnectionAction.CONNECT_OK)
        try:
            yield self._engine
        finally:
            if self._fsm.can(ConnectionAction.DISCONNECT):
                self._fsm.apply(ConnectionAction.DISCONNECT)

    def disconnect(self) -> None:
        session, backend = self._engine, self._backend
        self._engine = None
        if session is not None and backend is not None:
            backend.release(session)
        self.debug(msg=Event.Disconnect.name, connection_name=self.connection_name)

    # endregion GenericConnection API

    # region Tuning

    def tune(self, hz: float) -> SDREffective:
        """Retune within the profile range and read the result back (BR-05, BR-15)."""
        if self._profile is None or self._backend is None or self._engine is None:
            raise SDRConnectionError(
                caller=self, error=f"{self.connection_name}: no unit is claimed"
            )
        if not self._profile.contains_frequency(hz):
            raise SDRFrequencyOutOfRange(
                caller=self,
                error=f"{hz:.0f} Hz is outside {list(self._profile.freq_ranges)} (BR-15)",
            )
        self._backend.tune(self._engine, hz)
        self._effective = self._backend.read_back(self._engine)
        return self._effective

    def schedule(self) -> Iterator[tuple[float | None, int | None]]:
        """Frequencies a stream visits: the plan in turn, or `None` to stay where tuned."""
        plan = self.tuning_plan
        if plan is None:
            return iter(((None, None),))
        return itertools.cycle([(hz, plan.dwell_blocks) for hz in plan.points])

    # endregion Tuning

    def __repr__(self) -> str:
        family = self._profile.family if self._profile else "?"
        return f"{self.name}:{self.state.value}[family={family}]"
