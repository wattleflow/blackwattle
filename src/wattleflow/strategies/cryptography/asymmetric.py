# Module name: strategies/cryptography/asymmetric.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
from abc import abstractmethod
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from wattleflow.concrete import Wattleflow
from wattleflow.core import IStrategy

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Strategies                                                           #
# --------------------------------------------------------------------------- #


class StrategyBaseRSA(Wattleflow, IStrategy):
    def __init__(self, private_key: RSAPrivateKey, **kwargs):
        super().__init__(**kwargs)
        self.private_key = private_key

    @abstractmethod
    def execute(self, value: str):
        pass


class StrategyRSAEncrypt256(StrategyBaseRSA):
    def execute(self, value: str):
        public_key = self.private_key.public_key()
        return public_key.encrypt(
            value.encode("utf-8"),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )


class StrategyRSADecrypt256(StrategyBaseRSA):
    def execute(self, value: bytes):
        return self.private_key.decrypt(
            value,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        ).decode("utf-8")


class StrategyRSAEncrypt512(StrategyBaseRSA):
    def execute(self, value: str):
        public_key = self.private_key.public_key()
        return public_key.encrypt(
            plaintext=value.encode("utf-8"),
            padding=padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA512()),
                algorithm=hashes.SHA512(),
                label=None,
            ),
        )


class StrategyRSADecrypt512(StrategyBaseRSA):
    def execute(self, value: bytes):
        return self.private_key.decrypt(
            ciphertext=value,
            padding=padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA512()),
                algorithm=hashes.SHA512(),
                label=None,
            ),
        ).decode("utf-8")


# --------------------------------------------------------------------------- #
# endregion Strategies                                                        #
# --------------------------------------------------------------------------- #
