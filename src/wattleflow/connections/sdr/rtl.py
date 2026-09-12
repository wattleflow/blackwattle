# Module name: connections/sdr/rtl.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# Dependency (optional, extra `sdr`):                                         #
#   pip install "blackwattle[sdr]"   ->  pyrtlsdr[lib] (GPL-3.0-or-later)      #
# --------------------------------------------------------------------------- #
# pyrtlsdr 0.5.0 fails at IMPORT against the distribution package librtlsdr
# 2.0.1 with AttributeError (missing rtlsdr_set_dithering), not ImportError —
# so the guard below catches every exception, not only a missing package.
# --------------------------------------------------------------------------- #

"""RTLSDRBackend — the RTL2832U family through pyrtlsdr."""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from collections.abc import Mapping
from typing import Any, ClassVar
from wattleflow.enums.event import Event
from .backend import SDRBackend
from .errors import (
    SDRBackendUnavailable,
    SDRConnectionError,
    SDRDeviceBusy,
    SDRDeviceNotFound,
    SDRPermissionDenied,
)
from .profile import SDREffective, SDRInstance, SDRReported
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["RTLSDRBackend"]


class RTLSDRBackend(SDRBackend):
    FAMILY = "rtlsdr"
    DISTRIBUTION = "pyrtlsdr"
    BLOCK_ALIGN = 512
    # Synchronous reads report neither overruns nor dropped transfers; a short
    # read is raised by the library and closes the unit (declared blind spot).
    MEASURES_LOSS = False
    # The tuner is the only gain stage the family exposes.
    STAGE: ClassVar[str] = "TUNER"
    # enum rtlsdr_tuner in rtl-sdr.h
    TUNERS: ClassVar[dict[int, str]] = {
        0: "UNKNOWN",
        1: "E4000",
        2: "FC0012",
        3: "FC0013",
        4: "FC2580",
        5: "R820T",
        6: "R828D",
    }
    # libusb codes returned by rtlsdr_open
    BUSY: ClassVar[int] = -6
    ACCESS: ClassVar[int] = -3
    ABSENT: ClassVar[frozenset[int]] = frozenset({-1, -4, -5})

    def __init__(self, owner: Any) -> None:
        super().__init__(owner)
        # librtlsdr keeps no getter for the gain mode, so the backend remembers it.
        self._gain_mode = "auto"

    def _library(self) -> Any:
        try:
            import rtlsdr
        except Exception as e:
            self.debug(msg=Event.Load.name, step=Event.Failed.name, error=type(e).__name__)
            raise SDRBackendUnavailable(
                caller=self._owner,
                error=f"pyrtlsdr cannot be loaded ({type(e).__name__}: {e}); "
                'install "blackwattle[sdr]"',
            ) from e
        return rtlsdr

    def enumerate(self) -> list[dict[str, str]]:
        serials = self._library().RtlSdr.get_device_serial_addresses()
        return [{"index": str(i), "serial": serial} for i, serial in enumerate(serials)]

    def claim(self, device: Mapping[str, str]) -> Any:
        library = self._library()
        index = int(device["index"])
        try:
            return library.RtlSdr(device_index=index)
        except OSError as e:
            code = getattr(e, "errno", None)
            self.debug(msg=Event.Connect.name, step=Event.Failed.name, error=str(e), code=code)
            if code == self.BUSY:
                failure = SDRDeviceBusy
            elif code == self.ACCESS:
                failure = SDRPermissionDenied
            elif code in self.ABSENT:
                failure = SDRDeviceNotFound
            else:
                failure = SDRConnectionError
            raise failure(caller=self._owner, error=f"unit {index}: {e}") from e

    def report(self, session: Any) -> SDRReported:
        tuner = self.TUNERS.get(session.get_tuner_type(), "UNKNOWN")
        gains = tuple(tenths / 10 for tenths in session.get_gains())
        return SDRReported(model={"tuner": tuner}, gain_table={self.STAGE: gains})

    def supports(self, model: Mapping[str, str]) -> bool:
        # Whether the loaded librtlsdr drives this tuner is not asked here: the
        # library exposes no capability query (declared blind spot).
        return model.get("tuner") in set(self.TUNERS.values()) - {"UNKNOWN"}

    def apply(self, session: Any, instance: SDRInstance) -> None:
        session.set_sample_rate(instance.sample_rate)
        # librtlsdr rejects a correction equal to the current one with -2.
        if instance.ppm and instance.ppm != session.get_freq_correction():
            session.set_freq_correction(instance.ppm)
        session.set_center_freq(int(round(instance.center_freq)))
        if instance.gain_mode == "manual":
            session.set_manual_gain_enabled(True)
            session.set_gain(instance.gain[self.STAGE])
        else:
            session.set_gain("auto")
        self._gain_mode = instance.gain_mode
        if instance.bias_tee is not None:
            session.set_bias_tee(bool(instance.bias_tee))

    def read_back(self, session: Any) -> SDREffective:
        manual = self._gain_mode == "manual"
        return SDREffective(
            center_freq=float(session.get_center_freq()),
            sample_rate=float(session.get_sample_rate()),
            gain_mode=self._gain_mode,
            gain={self.STAGE: float(session.get_gain())} if manual else None,
            ppm=int(session.get_freq_correction()),
        )

    def tune(self, session: Any, hz: float) -> None:
        session.set_center_freq(int(round(hz)))

    def read(self, session: Any, nbytes: int) -> bytes:
        # The library reuses its buffer between reads; copy before returning.
        return bytes(session.read_bytes(nbytes))

    def release(self, session: Any) -> None:
        session.close()


SDRBackend.register(RTLSDRBackend)
