# Module name: decorators/pspf.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
Description: This module implements information classification and
dissemination limiting mechanisms consistent with the Australian Government’s
Protective Security Policy Framework (PSPF). It defines structures for managing
information classification levels and Dissemination Limiting Markers (DLMs)
within the Wattleflow Workflow framework. The module ensures consistent
application of security controls for sensitive or classified data, supporting
proper data handling, storage, and sharing practices in accordance with PSPF guidelines.

See more:
- https://www.protectivesecurity.gov.au/
- https://www.protectivesecurity.gov.au/system/files/2025-07/pspf-release-2025-summary-changes.pdf
"""

from __future__ import annotations
from enum import Enum
from wattleflow.core import IWattleflow
import wattleflow.enums.pspf as wattleconst


class PSPFDecorator:
    __slots__ = ("_classification", "_dlm")

    def __init__(self, parent: IWattleflow, **kwargs):
        super().__init__()

        classification = kwargs.pop(
            "classification",
            wattleconst.Classification.UNCLASSIFIED,
        )

        dlm = kwargs.pop(
            "dlm",
            wattleconst.ClassificationDLM.UNCLASSIFIED,
        )

        self._classification: Enum = getattr(
            wattleconst,
            classification.upper(),
            wattleconst.Classification.UNCLASSIFIED,
        )

        self._dlm: Enum = getattr(
            wattleconst,
            dlm.upper(),
            wattleconst.ClassificationDLM.UNDEFINED,
        )

    @property
    def classification(self) -> Enum:
        return self._classification

    @property
    def dlm(self) -> Enum:
        return self._dlm
