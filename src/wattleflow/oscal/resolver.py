# Module name: oscal/resolver.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import uuid as _uuid
from typing import Optional, Set
from .models import Catalog, Control, Group, Profile
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
# region Resolver                                                             #
# --------------------------------------------------------------------------- #


def resolve(
    profile: Profile,
    source: Catalog,
    *,
    catalog_uuid: Optional[str] = None,
    strict: bool = True,
) -> Catalog:
    """Resolve an OSCAL Profile against a source Catalog.

    Pruning is delegated to the nodes that hold the children
    (``Control.pruned`` / ``Group.pruned``); what this function owns is the
    profile's side of resolution: which ids are selected, how strictly a
    missing id is treated, and what the resulting Catalog is made of.

    Walks ``source`` and keeps only controls whose ids are selected by
    ``profile.imports[*].include_controls[*].with_ids``, minus any in
    ``exclude_controls``. Group hierarchy is preserved (``as-is`` merge);
    empty groups are pruned.

    Resolution is intentionally minimal — ``modify`` (alters/sets), pattern
    matching, parameter overrides, and ``include-all`` selectors are not
    implemented because ASD ISM profiles do not use them.

    Parameters
    ----------
    profile
        The Profile selecting controls.
    source
        The Catalog the profile imports from. The caller is responsible
        for ensuring this matches ``profile.imports[*].href``.
    catalog_uuid
        UUID for the resolved Catalog. Defaults to a fresh UUID4.
    strict
        If True (default), raise when the profile references control ids
        absent from the source catalog.
    """
    selected: Set[str] = set(profile.control_ids())
    if not selected:
        raise ValueError(f"Profile {profile.uuid} selects no controls")

    target_ids = selected - set(profile.excluded_control_ids())

    kept_controls, control_found = Control.prune_all(source.controls, target_ids)
    kept_groups, group_found = Group.prune_all(source.groups, target_ids)

    found = control_found | group_found
    if strict:
        missing = target_ids - found
        if missing:
            raise KeyError(
                f"Profile {profile.uuid} references {len(missing)} control(s) "
                f"absent from source catalog {source.uuid}: "
                f"{sorted(missing)[:10]}{'...' if len(missing) > 10 else ''}"
            )

    return Catalog(
        uuid=catalog_uuid or str(_uuid.uuid4()),
        metadata=profile.metadata,
        params=list(source.params),
        controls=kept_controls,
        groups=kept_groups,
        back_matter=profile.back_matter or source.back_matter,
    )


# --------------------------------------------------------------------------- #
# endregion Resolver                                                          #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Public API                                                           #
# --------------------------------------------------------------------------- #
__all__ = ["resolve"]
# --------------------------------------------------------------------------- #
# endregion Public API                                                        #
# --------------------------------------------------------------------------- #
