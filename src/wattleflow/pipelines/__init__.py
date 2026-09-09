# Module name: pipelines/__init__.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# Lazy public API (PEP 562) — DR-WFL-007.
#
# Eager `from .<module> import ...` re-exports defeat the lazy-loading policy of
# §7.4: a single third-party-bound leaf makes the WHOLE package unimportable, so
# a name that needs nothing still requires the full dependency set. Masking any
# one library proved this package unimportable before this change.
#
# Resolving a name imports ONLY the submodule that defines it. The public surface
# is unchanged and still explicit (NFRQ-SEC-02 t.2): `__all__` is complete and
# `_EXPORTS` states where each name lives.
#
# NOTE — `import *` resolves EVERY name in `__all__` and therefore still requires
# the full dependency set. That is the honest contract: asking for everything
# asks for everything. Named imports are the entry point on a partial install.
# --------------------------------------------------------------------------- #

from __future__ import annotations

from importlib import import_module
from typing import Any

# Public name -> defining submodule. Extend this when a member is added; it is
# the single declaration of what this package exposes and from where.
_EXPORTS: dict[str, str] = {
    "PipelineDummyWrite": "dummy",
    "PipelineMarkdownToWord": "convertors",
    "PipelineDataFrameClean": "dataframe",
    "PipelineFileExtractDigest": "digest",
    "EML_SUFFIX": "mail",
    "MSG_SUFFIX": "mail",
    "PipelineMailExtract": "mail",
    "PipelineMailExtractEML": "mail",
    "PipelineMailExtractAttachment": "mail",
    "AttachmentDocument": "mail",
    "PipelineMailExtractMSG": "mail",
    "PipelineOCRExtractTika": "ocr",
    "PipelineOCRRedactSpans": "ocr",
    "PipelinePDFExtractText": "pdf",
    "PipelinePDFRedact": "pdf",
    "DataQualityIndex": "quality",
    "RunningAggregate": "quality",
    "compute_completeness": "quality",
    "PipelineTextRedactMacroEntity": "text",
    "PipelineTextRepairDictionary": "text",
    "PipelineTextRepairStickyWords": "text",
}

__all__ = [
    "PipelineDummyWrite",
    "PipelineMarkdownToWord",
    "PipelineDataFrameClean",
    "PipelineFileExtractDigest",
    "EML_SUFFIX",
    "MSG_SUFFIX",
    "PipelineMailExtract",
    "PipelineMailExtractEML",
    "PipelineMailExtractAttachment",
    "AttachmentDocument",
    "PipelineMailExtractMSG",
    "PipelineOCRExtractTika",
    "PipelineOCRRedactSpans",
    "PipelinePDFExtractText",
    "PipelinePDFRedact",
    "DataQualityIndex",
    "RunningAggregate",
    "compute_completeness",
    "PipelineTextRedactMacroEntity",
    "PipelineTextRepairDictionary",
    "PipelineTextRepairStickyWords",
]


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(f".{module}", __name__), name)
    globals()[name] = value  # resolve once; subsequent lookups skip __getattr__
    return value


def __dir__() -> list[str]:
    return sorted(__all__)
