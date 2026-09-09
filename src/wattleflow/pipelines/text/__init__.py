# Module name: pipelines/text/__init__.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region imports                                                              #
# --------------------------------------------------------------------------- #
from . import entity_macros, text_dictionary  # noqa: F401
# --------------------------------------------------------------------------- #
# endregion imports                                                           #
# --------------------------------------------------------------------------- #

from .entity_macros import *  # noqa: F403
from .text_dictionary import *  # noqa: F403

__all__ = [*entity_macros.__all__, *text_dictionary.__all__]
