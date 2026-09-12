# Module name: drivers/sdr.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# Dependency (optional, extra `sdr`): numpy, loaded on the first block.       #
# --------------------------------------------------------------------------- #

"""DriverSDR — the only component that touches the sample stream (FRQ-DRV-16.2).

`read` is one implementation for every family: the profile supplies the format
and full scale, the parser turns bytes into samples, and the connection owns the
unit, its direction and its tuning plan (BR-13).
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from importlib import metadata
from io import BytesIO
from typing import Any, BinaryIO, ClassVar
from wattleflow.concrete.driver import DriverMetadata, GenericDriver
from wattleflow.concrete.exception import DriverException
from wattleflow.concrete.serialisation import GenericParser, ParserError
from wattleflow.connections.sdr.connection import SDRConnection
from wattleflow.connections.sdr.profile import Direction, SampleFormat, SDREffective
from wattleflow.enums.event import Event
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = [
    "DriverSDR",
    "DriverSDRError",
    "IQSampleParser",
    "SDRDeviceLost",
    "SDRSampleBlock",
    "SDRTransmitNotSupported",
]

# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class DriverSDRError(DriverException):
    """Base of every failure the SDR driver raises."""


class SDRTransmitNotSupported(DriverSDRError):
    """`write` on a unit or family that does not transmit (NFRQ-SEC-07 k.1)."""


class SDRDeviceLost(DriverSDRError):
    """The unit stopped delivering blocks during a stream (BR-09)."""


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Values                                                               #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SDRSampleBlock:
    """Samples with one description of how they were taken (FRQ-DRV-16.2 k.2)."""

    samples: Any
    sequence_no: int
    started_at: datetime
    sample_count: int
    effective_rate: float
    center_freq: float
    format: str
    full_scale: float
    # None when the access mechanism cannot see losses at all (BR-07).
    lost_before: int | None

    def description(self) -> dict[str, Any]:
        """Everything but the samples — safe for metadata and records (NFRQ-SEC-06)."""
        return {
            "sequence_no": self.sequence_no,
            "started_at": self.started_at.isoformat(),
            "sample_count": self.sample_count,
            "effective_rate": self.effective_rate,
            "center_freq": self.center_freq,
            "format": self.format,
            "full_scale": self.full_scale,
            "lost_before": self.lost_before,
        }


# --------------------------------------------------------------------------- #
# endregion Values                                                            #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Parser                                                               #
# --------------------------------------------------------------------------- #


class IQSampleParser(GenericParser):
    """Interleaved I/Q bytes → complex64 samples normalised by the profile full scale.

    Domain-local helper (NFRQ-ORG-01): only this driver reads sample formats.
    """

    ALLOWED = ["format", "full_scale"]
    DTYPE: ClassVar[dict[SampleFormat, str]] = {
        SampleFormat.U8_IQ: "u1",
        SampleFormat.S8_IQ: "i1",
        SampleFormat.S16_IQ: "<i2",
        SampleFormat.CF32_IQ: "<f4",
    }
    # Unsigned samples sit around mid-scale.
    OFFSET: ClassVar[dict[SampleFormat, float]] = {SampleFormat.U8_IQ: 127.5}

    def deserialise(self, reader: BinaryIO, **kwargs) -> Any:
        import numpy

        fmt = SampleFormat(kwargs.pop("format", None) or self.format)
        scale = float(kwargs.pop("full_scale", None) or self.full_scale or fmt.full_scale)
        raw = numpy.frombuffer(reader.read(), dtype=self.DTYPE[fmt])
        if raw.size % 2:
            raise ParserError(caller=self, error=f"{raw.size} values: I and Q must pair")
        values = raw.astype(numpy.float32)
        offset = self.OFFSET.get(fmt, 0.0)
        if offset:
            values -= offset
        values /= scale
        return values.view(numpy.complex64)


# --------------------------------------------------------------------------- #
# endregion Parser                                                            #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Driver                                                               #
# --------------------------------------------------------------------------- #


class DriverSDR(GenericDriver):
    ALLOWED = ["connection_name", "connection_manager", "block_size", "settle_blocks"]
    # rtl_sdr default: 16 × 16384 bytes of 8-bit I/Q.
    BLOCK_SIZE: ClassVar[int] = 131_072
    # Blocks dropped after a retune; the PLL lock is not observable through the
    # host library, so settling is counted, not measured (declared blind spot).
    SETTLE_BLOCKS: ClassVar[int] = 1

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._connection: SDRConnection | None = None
        self._parser: IQSampleParser | None = None
        self._format: SampleFormat | None = None
        self._full_scale: float = 0.0
        self._block_bytes: int = 0
        # Stays None while the mechanism cannot measure losses (BR-07).
        self._lost_total: int | None = None

    @property
    def effective(self) -> SDREffective | None:
        return self._connection.effective if self._connection else None

    @property
    def lost_total(self) -> int | None:
        return self._lost_total

    @classmethod
    def metadata(cls) -> DriverMetadata:
        # A class method states the superset; whether `write` works is decided
        # per instance, from the profile.
        try:
            version = metadata.version("blackwattle")
        except metadata.PackageNotFoundError:
            version = "unknown"
        return DriverMetadata(
            name=cls.__name__,
            version=version,
            protocol="sdr",
            capabilities=["read", "write", "stream"],
        )

    def load(self) -> None:
        self.debug(msg=Event.Load.name, step=Event.Started.name)
        manager, name = self.connection_manager, self.connection_name
        if manager is None or not name:
            raise DriverSDRError(
                caller=self, error="connection_name and connection_manager are required"
            )
        connection = manager.get_connection(name)
        if not isinstance(connection, SDRConnection):
            raise DriverSDRError(
                caller=self, error=f"{name!r} is {type(connection).__name__}, not SDRConnection"
            )
        # Claims the unit now if the connection was lazy (BR-06).
        connection.ensure_created()

        profile = connection.profile
        fmt = profile.primary_format
        block_size = int(self.block_size or self.BLOCK_SIZE)
        block_bytes = block_size * fmt.bytes_per_sample
        align = connection.backend.BLOCK_ALIGN
        if block_size <= 0 or block_bytes % align:
            raise DriverSDRError(
                caller=self,
                error=f"block_size {block_size} gives {block_bytes} bytes, "
                f"not a multiple of {align}",
            )

        self._connection = connection
        self._format = fmt
        self._full_scale = profile.formats[fmt]
        self._parser = IQSampleParser(format=fmt.value, full_scale=self._full_scale)
        self._block_bytes = block_bytes
        self._lost_total = 0 if connection.backend.MEASURES_LOSS else None
        self.debug(msg=Event.Load.name, step=Event.Completed.name, format=fmt.value)

    def close(self) -> None:
        # The unit belongs to the connection; the driver only lets go of it.
        self._parser = None
        self._connection = None
        self.debug(msg=Event.Close.name, step=Event.Completed.name)

    def read(self, uri: str = "", **kwargs) -> Generator[SDRSampleBlock, None, None]:
        """Blocks as a generator; nothing accumulates beyond one block (k.1)."""
        self.ensure_live()
        if self._connection.direction is not Direction.RECEIVE:
            raise DriverSDRError(caller=self, error="the connection is not in receive")
        return self._stream()

    def write(self, uri: str, **kwargs) -> Any:
        profile = self._connection.profile if self._connection else None
        reason = (
            "the profile declares no transmit"
            if profile is None or Direction.TRANSMIT not in profile.directions
            else "no family backend transmits yet"
        )
        raise SDRTransmitNotSupported(caller=self, error=f"write refused: {reason}")

    def _pull(self, session: Any) -> bytes:
        try:
            return self._connection.backend.read(session, self._block_bytes)
        except Exception as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=f"{type(e).__name__}: {e}")
            raise SDRDeviceLost(
                caller=self, error=f"read failed: {type(e).__name__}: {e}"
            ) from e

    def _stream(self) -> Generator[SDRSampleBlock, None, None]:
        connection = self._connection
        settle = self.SETTLE_BLOCKS if self.settle_blocks is None else int(self.settle_blocks)
        sequence = 0
        with connection.connect() as session:
            for hz, dwell in connection.schedule():
                if hz is not None:
                    connection.tune(hz)
                    for _ in range(settle):
                        self._pull(session)
                kept = 0
                while dwell is None or kept < dwell:
                    raw = self._pull(session)
                    effective = connection.effective
                    samples = self._parser.deserialise(BytesIO(raw))
                    count = int(samples.shape[0])
                    # Host clock at read completion minus the block's duration.
                    started = datetime.now(timezone.utc) - timedelta(
                        seconds=count / effective.sample_rate
                    )
                    yield SDRSampleBlock(
                        samples=samples,
                        sequence_no=sequence,
                        started_at=started,
                        sample_count=count,
                        effective_rate=effective.sample_rate,
                        center_freq=effective.center_freq,
                        format=self._format.value,
                        full_scale=self._full_scale,
                        lost_before=self._lost_total,
                    )
                    sequence += 1
                    kept += 1


# --------------------------------------------------------------------------- #
# endregion Driver                                                            #
# --------------------------------------------------------------------------- #
