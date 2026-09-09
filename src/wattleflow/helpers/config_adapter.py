# Module name: helpers/config_adapter.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from wattleflow.core import IConfig, IHandler
from wattleflow.concrete.base import Wattleflow
from wattleflow.helpers.config_yaml import YAMLConfig

from wattleflow.helpers.yaml import yaml  # noqa: F401

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #


_REF_PATTERN = re.compile(r"^\$\{\s*(\w+)\s*:\s*([^}]+)\s*\}$")


# --------------------------------------------------------------------------- #
# region Global methods                                                       #
# --------------------------------------------------------------------------- #
# def config_section(*path: str):

#     def decorator(cls):
#         cls._CONFIG_SECTION_PATH = path
#         original_init = cls.__init__

#         def patched_init(self, *args, **kwargs):
#             config: Config | None = kwargs.pop("config", None)
#             chain: SecretResolverChain | None = kwargs.pop("resolver_chain", None)

#             name = kwargs.get("name")

#             if config is not None:
#                 adapter = ConfigAdapter(config, *path, resolver_chain=chain)

#                 if name:
#                     for section in adapter.as_dict().values():
#                         if isinstance(section, list):
#                             for item in section:
#                                 if item.get("name") == name:
#                                     for k, v in item.items():
#                                         kwargs.setdefault(k, v)
#                                     break
#                 else:
#                     for k, v in adapter.as_dict().items():
#                         kwargs.setdefault(k, v)

#             original_init(self, *args, **kwargs)

#         cls.__init__ = patched_init
#         return cls

#     return decorator


# --------------------------------------------------------------------------- #
# endregion Global methods                                                    #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Interfaces                                                           #
# --------------------------------------------------------------------------- #


class ISecretResolver(ABC):
    """Strategy interface for resolving secret references embedded in config values.
    A secret reference has the form: ${prefix:reference}
    e.g. ${env:MY_VAR}, ${aws:my-secret/key}, ${vault:secret/data/app/db_pass}
    """

    PREFIX: str = ""

    def can_resolve(self, value: Any) -> bool:
        if not isinstance(value, str):
            return False
        m = _REF_PATTERN.match(value)
        return m is not None and m.group(1) == self.PREFIX

    def resolve(self, value: Any, strict: bool = False) -> str | None:
        m = _REF_PATTERN.match(value)
        if m is None or m.group(1) != self.PREFIX:
            return None
        return self._fetch(m.group(2))

    @abstractmethod
    def _fetch(self, ref: str) -> str | None: ...


class IConfigValidator(IHandler, ABC):
    """
    Chain of Responsibility za validaciju razrijesene konfiguracije.
    Nasljedivanje: implementiraj validate() u konkretnoj klasi.
    Ulancavanje:   validator_a.set_next(validator_b).set_next(validator_c)
    """

    def __init__(self) -> None:
        self._next: "IConfigValidator" | None = None

    def set_next(self, handler: "IConfigValidator") -> "IConfigValidator":
        self._next = handler
        return handler

    def handle(self, data: Any) -> Any:
        self.validate(data)
        return self._next.handle(data) if self._next else data

    @abstractmethod
    def validate(self, data: Any) -> None: ...


# --------------------------------------------------------------------------- #
# endregion Interfaces                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Resolvers                                                            #
# --------------------------------------------------------------------------- #


class EnvVarResolver(ISecretResolver):
    """Resolves ${env:VAR_NAME} references from environment variables."""

    PREFIX = "env"

    def _fetch(self, ref: str) -> str | None:
        return os.environ.get(ref)


class SecretResolverChain:
    __slots__ = ("_resolvers",)

    def __init__(self) -> None:
        self._resolvers: list[ISecretResolver] = []

    def add(self, resolver: ISecretResolver) -> "SecretResolverChain":
        self._resolvers.append(resolver)
        return self

    def resolve(self, value: Any) -> str | None:
        for resolver in self._resolvers:
            if resolver.can_resolve(value):
                try:
                    result = resolver.resolve(value)
                    if result is not None:
                        return result
                except Exception:
                    continue
        return None

    def resolve_all(self, value: Any, strict: bool = False) -> Any:
        """Resolve every `${prefix:ref}` inside a parsed document."""
        if isinstance(value, str):
            resolved = self.resolve(value)
            if resolved is not None:
                return resolved
            # A value shaped like ${prefix:ref} that no resolver could satisfy is
            # a configuration error under strict resolution — fail loudly rather
            # than leak the literal token into a driver path/credential.
            if strict and _REF_PATTERN.match(value):
                raise ValueError(f"Unresolved configuration reference: {value!r}")
            return value

        if isinstance(value, dict):
            return {k: self.resolve_all(v, strict) for k, v in value.items()}

        if isinstance(value, list):
            return [self.resolve_all(v, strict) for v in value]

        return value


# --------------------------------------------------------------------------- #
# endregion Resolvers                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Validators                                                           #
# --------------------------------------------------------------------------- #


class TypeValidator(IConfigValidator):
    """Validates that the resolved config root is a mapping (dict)."""

    def validate(self, data: Any) -> None:
        if not isinstance(data, dict):
            raise TypeError(f"Config: expected mapping at root, got {type(data).__name__}")


class RequiredKeysValidator(IConfigValidator):
    """Validates that all specified top-level keys are present."""

    def __init__(self, *keys: str) -> None:
        super().__init__()
        self._keys = keys

    def validate(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        missing = [k for k in self._keys if k not in data]
        if missing:
            raise ValueError(f"Config: missing required keys {missing}")


class AllowedKeysValidator(IConfigValidator):
    """Validates that no keys outside the allowed set are present."""

    def __init__(self, *keys: str) -> None:
        super().__init__()
        self._allowed = set(keys)

    def validate(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        unknown = [k for k in data if k not in self._allowed]
        if unknown:
            raise ValueError(f"Config: unexpected keys {unknown}")


class AllowedValuesValidator(IConfigValidator):
    """Validates that a specific key holds one of the allowed values."""

    def __init__(self, key: str, *allowed: Any) -> None:
        super().__init__()
        self._key = key
        self._allowed = set(allowed)

    def validate(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        value = data.get(self._key)
        if value is not None and value not in self._allowed:
            raise ValueError(f"Config: {self._key!r} must be one of {self._allowed}, got {value!r}")


class NonEmptyValidator(IConfigValidator):
    """Validates that specified keys are present and non-empty."""

    def __init__(self, *keys: str) -> None:
        super().__init__()
        self._keys = keys

    def validate(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        for key in self._keys:
            value = data.get(key)
            if value is None or value == "" or value == [] or value == {}:
                raise ValueError(f"Config: {key!r} must be non-empty")


# --------------------------------------------------------------------------- #
# endregion Validators                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region ConfigAdapter                                                        #
# --------------------------------------------------------------------------- #


# Bases composed, not inherited from the framework root (DR-WFL-009).
class ConfigAdapter(Wattleflow, IConfig):
    def __init__(
        self,
        config_file: Path,
        *section_path: str,
        **kwargs,
    ) -> None:

        # handler: Handler | None = kwargs.get("handler", None)
        validator: IConfigValidator | None = kwargs.get("validator", None)
        resolver_chain: SecretResolverChain | None = kwargs.get("resolver_chain", None)

        super().__init__(**kwargs)

        self._config_file: Path = config_file
        self._section_path = section_path
        self._chain = resolver_chain
        self._strict: bool = kwargs.get("strict", False)
        self._root: Any = None
        self._resolved: Any = None

        config = YAMLConfig(config_file=config_file, strict=self._strict)
        self._resolve_all(config)

        if validator:
            validator.handle(self._resolved)

    @classmethod
    def from_path(
        cls,
        config_file: Path | str,
        *section_path: str,
        env_file: Path | str | None = None,
        strict: bool = True,
        **kwargs,
    ) -> ConfigAdapter:
        """Adapter over a YAML file with the standard secret chain.

        Per-file `${dotenv:...}` overrides plus `${env:VAR}` from os.environ.
        The `.env` section is keyed by the config file name; discovery walks up
        from the config directory, so one `.env` may serve a whole project.
        """
        from wattleflow.helpers.dotenv import DotEnvResolver, find_env_file

        config_file = Path(config_file)
        if env_file is None:
            env_file = find_env_file(config_file)

        chain = (
            SecretResolverChain()
            .add(DotEnvResolver(env_file, section=config_file.name))
            .add(EnvVarResolver())
        )
        return cls(config_file, *section_path, resolver_chain=chain, strict=strict, **kwargs)

    def _resolve_all(self, config: YAMLConfig) -> None:
        self._root = config.find(*self._section_path)
        self._resolved = self._deep_resolve(self._root)

    def _deep_resolve(self, value: Any) -> Any:
        if self._chain is None:
            return value
        return self._chain.resolve_all(value, self._strict)

    def find(
        self,
        *keys: str,
        name: str = None,
        default: Any = None,
    ) -> Any:
        node = self._resolved

        for key in keys:
            if isinstance(node, dict):
                node = node.get(key)
            elif isinstance(node, list):
                # lists are traversed flattened
                found = None
                for item in node:
                    if isinstance(item, dict) and key in item:
                        found = item[key]
                        break
                node = found
            else:
                return default

            if node is None:
                return default

        # list → filter
        if isinstance(node, list):
            if name is not None:
                for item in node:
                    if isinstance(item, dict) and item.get("name") == name:
                        return item
                return default

            return node  # eksplicitno trazena lista

        if name:
            node = node.get(name, default)

        return node

    def get(
        self,
        key: str = None,
        name: str = None,
        default: Any = None,
    ) -> Any:
        """Deterministic lookup for resolved node and specific name value"""

        # Layout B (root je lista)
        if key is None:
            if isinstance(self._resolved, list) and name:
                for item in self._resolved:
                    if isinstance(item, dict) and item.get("name") == name:
                        return item
            return default

        # Layout A
        if not isinstance(self._resolved, dict):
            return default

        val = self._resolved.get(key)

        if val is None:
            return default

        if isinstance(val, list) and name:
            for item in val:
                if isinstance(item, dict) and item.get("name") == name:
                    return item
            return default

        return val

    def as_dict(self) -> dict:
        return dict(self._resolved) if isinstance(self._resolved, dict) else {}

    def config(self) -> Path:
        return self._config_file


# --------------------------------------------------------------------------- #
# endregion ConfigAdapter                                                     #
# --------------------------------------------------------------------------- #
