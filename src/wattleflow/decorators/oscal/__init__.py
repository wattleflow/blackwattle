# Module name: decorators/oscal/__init__.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

from .policy import oscal_policy
from .wrappers import oscal_connection, oscal_driver, oscal_processor

__all__ = [
    "oscal_policy",
    "oscal_connection",
    "oscal_driver",
    "oscal_processor",
]
