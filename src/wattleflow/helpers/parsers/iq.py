# Module name: helpers/parsers/iq.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""IQSampleParser — interleaved I/Q bytes into samples, and into the working table.

Conversion, not transformation: it changes the FORM and not the content, so it is
the driver's or the create strategy's to do, never a pipeline's (author,
2026-09-12). Both call this one definition.
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from typing import Any, BinaryIO, ClassVar
from wattleflow.concrete.serialisation import GenericParser, ParserError
from wattleflow.enums.sampleformat import SampleFormat
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["IQSampleParser"]


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

    @classmethod
    def frame(cls, payload: bytes, fmt: SampleFormat, full_scale: float | None = None) -> Any:
        """The working form: one row per sample, `i` and `q` in full scale."""
        import numpy
        import pandas

        scale = float(full_scale or fmt.full_scale)
        values = numpy.frombuffer(payload, dtype=cls.DTYPE[fmt]).astype(numpy.float32)
        if values.size % 2:
            raise ParserError(caller=cls, error=f"{values.size} values: I and Q must pair")
        offset = cls.OFFSET.get(fmt, 0.0)
        if offset:
            values -= offset
        values /= scale
        return pandas.DataFrame({"i": values[0::2], "q": values[1::2]})

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
