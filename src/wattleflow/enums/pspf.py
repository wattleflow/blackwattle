# Module name: enums/pspf.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from enum import Enum
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #


# Classification
class Classification(Enum):
    CLASSIFIED = "Classified"
    OFFICIAL = "OFFICIAL"
    PROTECTED = "PROTECTED"
    SECRET = "SECRET"
    TOP_SECRET = "TOP SECRET"
    UNCLASSIFIED = "UNCLASSIFIED"


# Classification DLM
class ClassificationDLM(Enum):
    PERSONAL = "Personal"
    SENSITIVE = "Sensitive"
    LEGAL_PREVILEGE = "Legal Privilege"
    CABINET = "CABINET"
    UNCLASSIFIED = "UNCLASSIFIED"
    UNDEFINED = "Undefined"


# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #
