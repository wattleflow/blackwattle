# Module name: decorators/oscal/wrappers.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from functools import partial
from .policy import oscal_policy
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
# region Thin wrappers                                                        #
# --------------------------------------------------------------------------- #

# Convenience wrappers around oscal_policy with the component-type label fixed.
# Use the generic oscal_policy when the strict / controls_strategy defaults
# need overriding.

oscal_connection = partial(oscal_policy, kind="connection")
oscal_driver = partial(oscal_policy, kind="driver")
oscal_processor = partial(oscal_policy, kind="processor")

# --------------------------------------------------------------------------- #
# endregion Thin wrappers                                                     #
# --------------------------------------------------------------------------- #
