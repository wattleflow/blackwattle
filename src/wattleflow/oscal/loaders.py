# Module name: oscal/loaders.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Mapping
from wattleflow.concrete import Wattleflow
from wattleflow.core import IStrategy, IWattleflow
from .models import Catalog, Profile

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #
__author__ = "WattleFlow"
__copyright__ = "© 2022–2026 WattleFlow. All rights reserved"
# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Loaders                                                              #
# --------------------------------------------------------------------------- #


class ASDOSCALLoader(Wattleflow, IStrategy, ABC):
    """Common behaviour of the ASD ISM OSCAL loaders: reading the JSON
    source and validating the keyword contract."""

    @classmethod
    def _require_path(cls, kwargs: Mapping[str, Any]) -> str | Path:
        path = kwargs.get("path")
        if path is None:
            raise ValueError(f"{cls.__name__} requires 'path' keyword argument")
        return path

    @staticmethod
    def _read_json(path: str | Path) -> Mapping[str, Any]:
        source = Path(path)
        if not source.is_file():
            raise FileNotFoundError(f"OSCAL JSON not found: {source}")
        with source.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    @abstractmethod
    def execute(self, caller: IWattleflow, **kwargs) -> Any: ...


class ASDOSCALCatalogLoader(ASDOSCALLoader):
    """Loads an ASD ISM OSCAL JSON *catalog* (full ISM or resolved-profile
    catalog) into a :class:`~wattleflow.oscal.models.Catalog`.

    Accepts both the OSCAL wrapper form (``{"catalog": {...}}``) and a bare
    catalog object.
    """

    def execute(self, caller: IWattleflow, **kwargs) -> Catalog:
        path = self._require_path(kwargs)
        payload = self._read_json(path)
        if "profile" in payload:
            raise ValueError(f"{path} is an OSCAL Profile document — use ASDOSCALProfileLoader")
        return Catalog.from_dict(payload)


class ASDOSCALProfileLoader(ASDOSCALLoader):
    """Loads an ASD ISM OSCAL JSON *profile* (selector document) into a
    :class:`~wattleflow.oscal.models.Profile`.

    A profile only carries imports/selectors; resolving it against a source
    catalog into a flat control list is a separate concern not performed
    here.
    """

    def execute(self, caller: IWattleflow, **kwargs) -> Profile:
        path = self._require_path(kwargs)
        payload = self._read_json(path)
        if "catalog" in payload:
            raise ValueError(f"{path} is an OSCAL Catalog document — use ASDOSCALCatalogLoader")
        return Profile.from_dict(payload)


# --------------------------------------------------------------------------- #
# endregion Loaders                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Public API                                                           #
# --------------------------------------------------------------------------- #
__all__ = [
    "ASDOSCALCatalogLoader",
    "ASDOSCALLoader",
    "ASDOSCALProfileLoader",
]
# --------------------------------------------------------------------------- #
# endregion Public API                                                        #
# --------------------------------------------------------------------------- #
