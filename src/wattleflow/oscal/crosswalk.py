# Module name: oscal/crosswalk.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import json
from pathlib import Path
from typing import Iterable, Mapping, Union
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #
__author__ = "WattleFlow"
__copyright__ = "© 2022–2026 WattleFlow. All rights reserved"

_PathLike = Union[str, Path]
# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Crosswalk                                                            #
# --------------------------------------------------------------------------- #


class Crosswalk:
    """Rewrites control ids from a source taxonomy into a target taxonomy.

    A component may declare controls in one taxonomy (e.g. NIST SP 800-53)
    while the active OSCAL baseline uses another (e.g. ASD ISM). The crosswalk
    maps declared ids onto the baseline's taxonomy before the policy check.

    Ids with no mapping pass through unchanged, so a component that already
    declares the baseline's native ids needs no crosswalk, and an id that is
    untranslatable surfaces as a policy violation rather than silently
    vanishing. The mapping table is a curated compliance artifact; this class
    is only the mechanism that applies it.
    """

    __slots__ = ("_name", "_map")

    def __init__(
        self,
        name: str = "",
        mappings: Mapping[str, Iterable[str]] | None = None,
    ) -> None:
        self._name = name
        self._map: dict[str, frozenset[str]] = {}
        for source, targets in (mappings or {}).items():
            self._map[source.lower()] = frozenset(t for t in targets)

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_empty(self) -> bool:
        return not self._map

    def __len__(self) -> int:
        return len(self._map)

    def __contains__(self, source_id: str) -> bool:
        return source_id.lower() in self._map

    def translate(self, ids: Iterable[str]) -> set[str]:
        """Map each id onto the target taxonomy; unmapped ids pass through."""
        out: set[str] = set()
        for cid in ids:
            mapped = self._map.get(cid.lower())
            if mapped is None:
                out.add(cid)
            else:
                out.update(mapped)
        return out

    @classmethod
    def from_dict(cls, payload: Mapping) -> "Crosswalk":
        return cls(name=payload.get("name", ""), mappings=payload.get("mappings", {}))

    @classmethod
    def from_file(cls, path: _PathLike) -> "Crosswalk":
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Crosswalk JSON not found: {p}")
        with p.open("r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


# --------------------------------------------------------------------------- #
# endregion Crosswalk                                                         #
# --------------------------------------------------------------------------- #
