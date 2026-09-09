# Module name: decorators/encrypted_preset.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


from __future__ import annotations

import pickle
from typing import Any, Optional
from cryptography.fernet import Fernet
from wattleflow.core import IWattleflow
from wattleflow.concrete.exception import AttributeException
from wattleflow.decorators.preset import PresetDecorator


class EncryptedPreset(PresetDecorator):
    """
    Session-encrypted variant of PresetDecorator.

    All preset values are symmetrically encrypted with a per-instance
    Fernet key generated at construction time.  Keys and plain-text values
    are never stored persistently.
    """

    __slots__ = ("_cipher",)

    def __init__(self, parent: IWattleflow, **kwargs) -> None:
        session_key: bytes = Fernet.generate_key()
        object.__setattr__(self, "_cipher", Fernet(session_key))

        super().__init__(parent, **kwargs)

        plain: dict = object.__getattribute__(self, "_values")
        encrypted: dict = {k: self._encrypt(v) for k, v in plain.items()}
        object.__setattr__(self, "_values", encrypted)

    # ---------------------------------------------------------------------- #
    # Encryption helpers
    # ---------------------------------------------------------------------- #

    def _encrypt(self, value: Any) -> Optional[bytes]:
        """Serialise *value* with pickle and encrypt with the session cipher."""
        if value is None:
            return None
        cipher: Fernet = object.__getattribute__(self, "_cipher")
        return cipher.encrypt(pickle.dumps(value))

    def _decrypt(self, token: Optional[bytes]) -> Any:
        """Decrypt *token* and deserialise back to the original Python object."""
        if token is None:
            return None
        cipher: Fernet = object.__getattribute__(self, "_cipher")
        return pickle.loads(cipher.decrypt(token))

    # ---------------------------------------------------------------------- #
    # PresetDecorator interface — transparent encrypt / decrypt
    # ---------------------------------------------------------------------- #

    def __getattr__(self, name: str) -> Any:
        parent: IWattleflow = object.__getattribute__(self, "_parent")
        try:
            value = object.__getattribute__(parent, name)
            if value:
                return value
        except Exception:
            pass

        allowed: set = object.__getattribute__(self, "_allowed")
        if name in allowed:
            values: dict = object.__getattribute__(self, "_values")
            return self._decrypt(values.get(name))

        raise AttributeException(
            caller=parent,
            error=f"{parent.name}.{name} is not permitted.",
            name=name,
            exc_info=True,
        )

    def __setattr__(self, name: str, value: Any) -> None:
        if name in EncryptedPreset.__slots__:
            object.__setattr__(self, name, value)
            return

        if name in PresetDecorator.__slots__:
            object.__setattr__(self, name, value)
            return

        allowed: set = object.__getattribute__(self, "_allowed")
        if name in allowed:
            values: dict = object.__getattribute__(self, "_values")
            values[name] = self._encrypt(value)
            return

        parent: IWattleflow = object.__getattribute__(self, "_parent")
        raise AttributeError(f"{parent.name}.{name} is not permitted.")

    def __repr__(self) -> str:
        parent: IWattleflow = object.__getattribute__(self, "_parent")
        return f"{parent.name}._encrypted_preset"
