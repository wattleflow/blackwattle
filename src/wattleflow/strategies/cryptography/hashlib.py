# Module name: strategies/cryptography/hashlib.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
Description: This module provides concrete classes implementing key
management strategies within the Wattleflow framework. It offers tools
for secure generation, handling, and validation of cryptographic keys.
"""

# --------------------------------------------------------------------------- #
# region imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
from hashlib import md5, sha224, sha256, sha384, sha512
from wattleflow.concrete import Wattleflow
from wattleflow.core import IStrategy

# --------------------------------------------------------------------------- #
# endregion imports                                                           #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Strategies                                                           #
# --------------------------------------------------------------------------- #


class StrategyMD5(Wattleflow, IStrategy):
    def execute(self, value: str) -> str:
        return md5(value.encode("utf-8")).hexdigest()


class StrategySha224(Wattleflow, IStrategy):
    def execute(self, value: str) -> str:
        return sha224(value.encode("utf-8")).hexdigest()


class StrategySha256(Wattleflow, IStrategy):
    def execute(self, value: str) -> str:
        return sha256(value.encode("utf-8")).hexdigest()


class StrategySha384(Wattleflow, IStrategy):
    def execute(self, value: str) -> str:
        return sha384(value.encode("utf-8")).hexdigest()


class StrategySha512(Wattleflow, IStrategy):
    def execute(self, value: str) -> str:
        return sha512(value.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# endregion Strategies                                                        #
# --------------------------------------------------------------------------- #
