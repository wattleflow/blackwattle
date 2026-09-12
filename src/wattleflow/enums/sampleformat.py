# Module name: enums/sampleformat.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""Sample formats of an I/Q stream.

Foundation material, not a domain value: the connection declares it from a
profile, the driver and the create strategy read it, and a parser in the shared
shelf may not reach into a domain to learn it (NFRQ-ORG-01).
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from enum import Enum
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["SampleFormat"]


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
