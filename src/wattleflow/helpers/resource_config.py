# Module name: helpers/resource_config.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

"""ResourceConfig — IConfig over a JSON template shipped with the distribution (v0.0.4, DR-PRC-008)."""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations

from collections.abc import Mapping
from functools import cache
from importlib.resources import as_file, files
from types import MappingProxyType
from typing import Any, ClassVar

from wattleflow.concrete.base import Wattleflow
from wattleflow.core import IConfig
from wattleflow.helpers.config import JSONConfig

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["ResourceConfig"]


class ResourceConfig(Wattleflow, IConfig):
    """Template settings overridden by the caller's settings."""

    ROOT: ClassVar[str] = "wattleflow.resources"
    FILENAME: ClassVar[str] = "default.json"
    FORMATTERS: ClassVar[str] = "helpers.formatters"
    CONVERTERS: ClassVar[str] = "helpers.converters"

    def __init__(self, template: str, overrides: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.template = template
        self.defaults: Mapping[str, Any] = self._load(template)
        self.settings: dict[str, Any] = {**self.defaults, **dict(overrides or {})}

    @classmethod
    def formatter(cls, name: str, overrides: Mapping[str, Any] | None = None) -> ResourceConfig:
        return cls(f"{cls.FORMATTERS}.{name}", overrides)

    @classmethod
    def converter(cls, name: str, overrides: Mapping[str, Any] | None = None) -> ResourceConfig:
        return cls(f"{cls.CONVERTERS}.{name}", overrides)

    @classmethod
    @cache
    def _load(cls, template: str) -> Mapping[str, Any]:
        with as_file(files(f"{cls.ROOT}.{template}") / cls.FILENAME) as path:
            return MappingProxyType(dict(JSONConfig(path).find()))

    def find(self, *keys: str, default: Any = None) -> Any:
        node: Any = self.settings
        for key in keys:
            if not isinstance(node, Mapping) or key not in node:
                return default
            node = node[key]
        return node

    def __getitem__(self, key: str) -> Any:
        if key not in self.settings:
            raise ValueError(f"template {self.template} lacks the setting '{key}'")
        return self.settings[key]

    def unknown(self, keys: Mapping[str, Any] | None) -> list[str]:
        """Keys the template does not define."""
        return sorted(k for k in (keys or {}) if k not in self.defaults)
