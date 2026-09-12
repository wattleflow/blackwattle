# Module name: helpers/parsers/__init__.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# Lazy public API (PEP 562) — DR-WFL-007.
#
# The package carries an __init__.py so that it is a package of THIS
# distribution and not an implicit PEP 420 namespace. A namespace merges with any
# same-named directory another distribution ships, and `import *` over one yields
# nothing without raising (CLAUDE.md 2.6, 2.7 t.1, DR-WFL-017).
# Resolution stays deferred: some submodules need an optional library at import
# time — `binary` reaches `helpers.image_security`, which requires Pillow — so an
# eager aggregate would pull that tier on a bare install (DR-WFL-007).
# --------------------------------------------------------------------------- #

from __future__ import annotations

from importlib import import_module
from typing import Any

# Public name -> defining submodule. Extend this when a member is added; it is
# the single declaration of what this package exposes and from where.
_EXPORTS: dict[str, str] = {
    "PdfParser": "binary",
    "PdfText": "binary",
    "PickleParser": "binary",
    "ProtobufParser": "binary",
    "PngParser": "binary",
    "ParserFactory": "factory",
    "RepairDictionaryParser": "lexical",
    "WordListParser": "lexical",
    "AttachmentPolicy": "mail",
    "MailHeaderBlock": "mail",
    "MailTemplate": "mail",
    "MailTemplateParser": "mail",
    "PRINT_LABELS": "mail",
    "MailHop": "mail",
    "MailParser": "mail",
    "MailMessage": "mail",
    "MailEnvelope": "mail",
    "MailAttachment": "mail",
    "MailAddress": "mail",
    "MailMoment": "mail",
    "MailHeader": "mail",
    "MailKeys": "mail",
    "OcrParser": "ocr",
    "Tokens": "ocr",
    "CsvParser": "tabular",
    "ExcelParser": "tabular",
    "OrcParser": "tabular",
    "AvroParser": "tabular",
    "TxtParser": "text",
    "LogParser": "text",
    "MarkdownParser": "text",
    "JsonParser": "text",
    "GraphParser": "text",
    "RssParser": "text",
    "XmlParser": "text",
    "TikaParser": "tika",
    "DocxParser": "word",
    "DocParser": "word",
}

__all__ = [
    "PdfParser",
    "PdfText",
    "PickleParser",
    "ProtobufParser",
    "PngParser",
    "ParserFactory",
    "RepairDictionaryParser",
    "WordListParser",
    "AttachmentPolicy",
    "MailHeaderBlock",
    "MailTemplate",
    "MailTemplateParser",
    "PRINT_LABELS",
    "MailHop",
    "MailParser",
    "MailMessage",
    "MailEnvelope",
    "MailAttachment",
    "MailAddress",
    "MailMoment",
    "MailHeader",
    "MailKeys",
    "OcrParser",
    "Tokens",
    "CsvParser",
    "ExcelParser",
    "OrcParser",
    "AvroParser",
    "TxtParser",
    "LogParser",
    "MarkdownParser",
    "JsonParser",
    "GraphParser",
    "RssParser",
    "XmlParser",
    "TikaParser",
    "DocxParser",
    "DocParser",
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
