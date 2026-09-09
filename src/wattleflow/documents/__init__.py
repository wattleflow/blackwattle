# Module name: documents/__init__.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region imports                                                              #
# --------------------------------------------------------------------------- #
from .dictionary import DictDocument
from .file import FileDocument
from .item import ItemDocument

# NOTE: third-party-backed document types are intentionally NOT re-exported here.
# `documents/` is shared with the core `wattleflow` / `wattleflow-workflow`
# distribution, which bundles only the light dictionary/file/item documents.
# Eager re-export would force pandas/rdflib/fastavro/pyarrow/opensearch-py/pysolr
# at `import wattleflow.documents`. Import them explicitly from their sub-module
# --------------------------------------------------------------------------- #
# endregion imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = [
    "DictDocument",
    "FileDocument",
    "ItemDocument",
]
