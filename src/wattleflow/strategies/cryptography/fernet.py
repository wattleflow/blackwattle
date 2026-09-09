# Module name: strategies/cryptography/fernet.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
This module follows the “build once, use often” principle, supporting bespoke
implementations of Fernet-based cryptographic strategy classes within the
Wattleflow Workflow an ETL framework. It provides secure, symmetric encryption
and decryption mechanisms, ensuring data confidentiality and integrity through
key-managed operations, maintaining consistency and reusability across the framework.
"""

# --------------------------------------------------------------------------- #
# region imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations

try:
    from cryptography.fernet import Fernet
except ImportError as e:
    raise ModuleNotFoundError(
        "Cryptography `fernet` library is missing.\n\tInstall: pip install cryptography"
    ) from e

from wattleflow.concrete import Wattleflow
from wattleflow.core import IStrategy

# --------------------------------------------------------------------------- #
# endregion imports                                                           #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Strategies                                                           #
# --------------------------------------------------------------------------- #


# Abstract base: supplies the key; execute() stays abstract via IStrategy.
class StrategyFernetGeneric(Wattleflow, IStrategy):
    def __init__(self, key_filename: str, **kwargs):
        super().__init__(**kwargs)
        self.key_filename = key_filename
        self.key = self._load_key()

    def _generate_key(self):
        key = Fernet.generate_key()
        with open(self.key_filename, "wb") as key_file:
            key_file.write(key)
        return key

    def _load_key(self):
        try:
            with open(self.key_filename, "rb") as key_file:
                return key_file.read()
        except FileNotFoundError:
            return self._generate_key()


class StrategyFernetEncrypt(StrategyFernetGeneric):
    def execute(self, value: str):
        fernet = Fernet(self.key)
        return fernet.encrypt(value.encode())


class StrategyFernetDecrypt(StrategyFernetGeneric):
    def execute(self, value: str):
        fernet = Fernet(self.key)
        return fernet.decrypt(value).decode()


# --------------------------------------------------------------------------- #
# endregion Strategies                                                        #
# --------------------------------------------------------------------------- #
