# Module name: documents/sdr.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""SDRSampleDocument — a captured segment: the bytes as the unit delivered them,
with the sampling description in metadata (FRQ-DOC-16.4)."""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from abc import ABC
from typing import Any
from wattleflow.concrete import Document
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["SDRSampleDocument"]

# --------------------------------------------------------------------------- #
# region Documents                                                            #
# --------------------------------------------------------------------------- #


class SDRSampleDocument(Document[bytes], ABC):
    def __init__(self, content: bytes, **kwargs: Any):
        super().__init__(content=content, **kwargs)

    @property
    def size(self) -> int:
        """Samples, not bytes: a sample is what the capture counts (FRQ-DOC-16.4 k.3)."""
        return int(self.metadata.get("sample_count") or 0)

    @property
    def format(self) -> str:
        return str(self.metadata.get("format", ""))

    @property
    def center_freq(self) -> float:
        return float(self.metadata.get("center_freq") or 0.0)


# --------------------------------------------------------------------------- #
# endregion Documents                                                         #
# --------------------------------------------------------------------------- #
