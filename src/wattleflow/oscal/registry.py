# Module name: oscal/registry.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from typing import Dict, Iterator, Optional
from wattleflow.concrete import Wattleflow
from wattleflow.enums.event import Event
from .models import Catalog, Control
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
# region Classes                                                              #
# --------------------------------------------------------------------------- #


class OSCALCatalogRegistry(Wattleflow):
    """In-memory registry of OSCAL Catalogs indexed by UUID, with a flat
    control-id lookup across all registered catalogs.
    """

    def __init__(self) -> None:
        super().__init__()
        self._catalogs: Dict[str, Catalog] = {}
        self._controls: Dict[str, Control] = {}

    def __len__(self) -> int:
        return len(self._catalogs)

    def __contains__(self, control_id: str) -> bool:
        return control_id in self._controls

    @property
    def control_count(self) -> int:
        return len(self._controls)

    def register(self, catalog: Catalog) -> None:
        if catalog.uuid in self._catalogs:
            raise ValueError(f"Catalog already registered: {catalog.uuid}")
        self._catalogs[catalog.uuid] = catalog
        for control in catalog.create_iterator():
            # Later catalogs win on conflict — caller is responsible for
            # ordering registrations (full ISM before E8 baselines).
            self._controls[control.id] = control

    def clear(self) -> None:
        self._catalogs.clear()
        self._controls.clear()

    def find(self, control_id: str) -> Optional[Control]:
        return self._controls.get(control_id)

    def get(self, control_id: str) -> Control:
        try:
            return self._controls[control_id]
        except KeyError as e:
            self.debug(msg=Event.Get.name, step=Event.Failed.name, error=str(e))
            raise KeyError(f"Unknown OSCAL control: {control_id}") from e

    def iter_catalogs(self) -> Iterator[Catalog]:
        return iter(self._catalogs.values())

    def iter_controls(self) -> Iterator[Control]:
        return iter(self._controls.values())


# --------------------------------------------------------------------------- #
# endregion Classes                                                           #
# --------------------------------------------------------------------------- #
