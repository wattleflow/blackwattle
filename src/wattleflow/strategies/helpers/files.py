# Module name: strategies/helpers/files.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import re
from fnmatch import fnmatch
from wattleflow.concrete import Wattleflow
from wattleflow.core import IStrategy
# --------------------------------------------------------------------------- #
# endregion imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Strategies                                                           #
# --------------------------------------------------------------------------- #


class StrategyFilename(Wattleflow, IStrategy):
    def execute(self, value) -> str:
        filtered = re.sub(r"(^[a-zA-Z0-9]+)", "", value)
        filename = filtered.lower()
        return filename


class StrategyFilterFiles(Wattleflow, IStrategy):
    def __init__(self, pattern, **kwargs):
        super().__init__(**kwargs)
        self.pattern = pattern

    def execute(self, filename):
        return fnmatch(filename, self.pattern)


# --------------------------------------------------------------------------- #
# endregion Strategies                                                        #
# --------------------------------------------------------------------------- #


__all__ = ["StrategyFilename", "StrategyFilterFiles"]
