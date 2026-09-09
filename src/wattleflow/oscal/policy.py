# Module name: oscal/policy.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from typing import FrozenSet, Iterable, Optional
from .models import Profile
from .crosswalk import Crosswalk
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
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class OSCALPolicyError(PermissionError):
    """Raised when a component fails the active OSCAL baseline."""


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Policy                                                               #
# --------------------------------------------------------------------------- #


class OSCALPolicy:
    """Gate that validates components against an active OSCAL Profile.

    A component declares the control ids it satisfies; the policy checks that
    every declared control belongs to the active baseline (``declared`` is a
    subset of the baseline). An optional :class:`Crosswalk` first rewrites the
    declared ids into the baseline's taxonomy, so a component may declare in a
    foreign taxonomy (e.g. NIST SP 800-53) against an ASD ISM baseline.
    """

    __slots__ = ("_profile", "_crosswalk", "_required")

    def __init__(
        self,
        profile: Profile,
        crosswalk: Optional[Crosswalk] = None,
    ) -> None:
        self._profile = profile
        self._crosswalk = crosswalk
        self._required: FrozenSet[str] = frozenset(profile.control_ids())

    @property
    def profile_uuid(self) -> str:
        return self._profile.uuid

    @property
    def required(self) -> FrozenSet[str]:
        return self._required

    def verify(self, component_name: str, declared: Iterable[str]) -> None:
        translated = (
            self._crosswalk.translate(declared) if self._crosswalk is not None else set(declared)
        )
        outside = translated - self._required
        if outside:
            raise OSCALPolicyError(
                f"{component_name} declares controls outside baseline "
                f"{self._profile.uuid}: {sorted(outside)}"
            )


# --------------------------------------------------------------------------- #
# endregion Policy                                                            #
# --------------------------------------------------------------------------- #
