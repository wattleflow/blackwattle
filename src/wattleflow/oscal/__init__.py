# Module name: oscal/__init__.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

from ._version import __version__, OSCAL_VERSION, ASD_ISM_RELEASE
from .models import (
    BackMatter,
    Catalog,
    Control,
    Group,
    Import,
    IncludeControls,
    Link,
    Merge,
    Metadata,
    Param,
    Part,
    Profile,
    Prop,
)
from .loaders import ASDOSCALCatalogLoader, ASDOSCALProfileLoader
from .registry import OSCALCatalogRegistry
from .resolver import resolve
from .crosswalk import Crosswalk
from .policy import OSCALPolicy, OSCALPolicyError

__all__ = [
    "__version__",
    "OSCAL_VERSION",
    "ASD_ISM_RELEASE",
    "ASDOSCALCatalogLoader",
    "ASDOSCALProfileLoader",
    "BackMatter",
    "Catalog",
    "Control",
    "Crosswalk",
    "Group",
    "Import",
    "IncludeControls",
    "Link",
    "Merge",
    "Metadata",
    "OSCALCatalogRegistry",
    "OSCALPolicy",
    "OSCALPolicyError",
    "Param",
    "Part",
    "Profile",
    "Prop",
    "resolve",
]

__author__ = "WattleFlow"
__copyright__ = "© 2022–2026 WattleFlow. All rights reserved"
