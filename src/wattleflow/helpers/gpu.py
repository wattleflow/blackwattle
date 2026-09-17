# Module name: helpers/gpu.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

"""GPU memory for `Monitor` through NVML (`HLRQ-18` BR-08, `FRQ-PTN-18.1`) — v0.0.4.

`nvidia-ml-py` is imported lazily: without it, or without a device, the GPU is
reported unmeasured rather than free.
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from typing import Any, ClassVar
from wattleflow.helpers.monitor import ResourceExtension
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["NvmlGpuExtension"]


class NvmlGpuExtension(ResourceExtension):
    """Device memory summed over every NVIDIA device the process can see."""

    RESOURCE: ClassVar[str] = "gpu"
    SOURCE: ClassVar[str] = "nvml"

    def __init__(self) -> None:
        self._nvml: Any = None
        self._handles: list[Any] = []
        try:
            import pynvml

            pynvml.nvmlInit()
            count = pynvml.nvmlDeviceGetCount()
            self._handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(count)]
            self._nvml = pynvml if self._handles else None
        except Exception:
            self._nvml = None

    def _memory(self) -> list[Any]:
        return [self._nvml.nvmlDeviceGetMemoryInfo(handle) for handle in self._handles]

    def available(self) -> bool:
        return self._nvml is not None

    def limit(self) -> tuple[int | None, str]:
        if not self.available():
            return None, "unmeasured"
        try:
            return sum(int(m.total) for m in self._memory()), self.SOURCE
        except Exception:
            return None, "unknown"

    def used(self) -> int | None:
        if not self.available():
            return None
        try:
            return sum(int(m.used) for m in self._memory())
        except Exception:
            return None
