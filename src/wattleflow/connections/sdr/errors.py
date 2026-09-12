# Module name: connections/sdr/errors.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""Failure classes of the SDR connection — they differ by type, not only by message
(FRQ-CON-16.1 k.6)."""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from wattleflow.concrete.exception import ConnectionException
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = [
    "SDRBackendUnavailable",
    "SDRConfigurationError",
    "SDRConnectionError",
    "SDRDeviceAmbiguous",
    "SDRDeviceBusy",
    "SDRDeviceNotFound",
    "SDRFrequencyOutOfRange",
    "SDRModelUnsupported",
    "SDRPermissionDenied",
    "SDRProfileMismatch",
]


class SDRConnectionError(ConnectionException):
    """Base of every failure the SDR connection raises."""


class SDRBackendUnavailable(SDRConnectionError):
    """The access mechanism is missing, or installed but cannot be loaded (BR-14)."""


class SDRConfigurationError(SDRConnectionError):
    """An instance value is malformed or lies outside its profile."""


class SDRDeviceNotFound(SDRConnectionError):
    """No attached unit matches the selector — reachability (BR-02)."""


class SDRDeviceAmbiguous(SDRConnectionError):
    """More than one attached unit matches the selector (BR-02)."""


class SDRDeviceBusy(SDRConnectionError):
    """The unit stays claimed elsewhere past `device_timeout` (BR-03)."""


class SDRPermissionDenied(SDRConnectionError):
    """The host denies access to the unit — rights."""


class SDRProfileMismatch(SDRConnectionError):
    """The declared profile and the reported unit disagree (BR-11)."""


class SDRModelUnsupported(SDRConnectionError):
    """The access mechanism does not support the declared model (BR-14)."""


class SDRFrequencyOutOfRange(SDRConnectionError):
    """A frequency outside every profile range, at load time or at read time (BR-15)."""
