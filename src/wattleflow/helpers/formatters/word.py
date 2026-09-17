# Module name: helpers/formatters/word.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
Word formatters — serialise document content into DOCX/legacy DOC payloads.

Reuses ``WordConverter`` for the Markdown → DOCX build; ``DocFormatter``
additionally shells out to headless LibreOffice for the legacy .doc format.
Formatters return ``bytes`` only — no file paths or driver concerns.
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from abc import abstractmethod
import io
import tempfile
from pathlib import Path
from typing import Any

from wattleflow.concrete.serialisation import GenericFormatter
from wattleflow.enums.event import Event
from wattleflow.helpers.resource_config import ResourceConfig
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["WordFormatter", "DocFormatter"]


# --------------------------------------------------------------------------- #
# region Formatters                                                           #
# --------------------------------------------------------------------------- #


class _BaseFormatter(GenericFormatter):
    def _build_docx(self, content: Any, converter_kwargs: dict):
        """Return a python-docx Document built from ``content``."""
        try:
            from docx.document import Document as DocumentT
        except ImportError as e:
            raise ModuleNotFoundError(
                "python-docx library is missing. Add it manually: pip install python-docx"
            ) from e

        from wattleflow.helpers.converters import WordConverter

        if isinstance(content, DocumentT):
            return content
        # v0.0.4 (DR-PRC-005): report unknown settings instead of dropping them.
        discarded = WordConverter.unknown(converter_kwargs)
        if discarded:
            self.warning(
                msg=Event.Render,
                step=Event.Check,
                reason="converter keys are not Word converter settings and were discarded",
                discarded=discarded,
            )
        if isinstance(content, (bytes, bytearray)):
            return WordConverter(**converter_kwargs).markdown_to_docx(
                bytes(content).decode("utf-8")
            )
        if isinstance(content, str):
            return WordConverter(**converter_kwargs).markdown_to_docx(content)
        raise TypeError(f"Unsupported content type: {type(content).__name__}")

    @abstractmethod
    def serialise(self, content: Any, **opts: Any) -> bytes: ...


class WordFormatter(_BaseFormatter):
    SUFFIX: str = ".docx"
    TEMPLATE = "word"

    def serialise(self, content: Any, **opts: Any) -> bytes:
        converter_kwargs = opts.get("converter", {}) or {}
        doc = self._build_docx(content, converter_kwargs)
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()


class DocFormatter(_BaseFormatter):
    """Serialise content into a legacy .doc payload via headless LibreOffice."""

    SUFFIX: str = ".doc"
    TEMPLATE = "doc"

    def serialise(self, content: Any, **opts: Any) -> bytes:
        from wattleflow.helpers.converters.office import OfficeConverter

        OfficeConverter.binary()  # fail before the build when LibreOffice is absent
        doc = self._build_docx(content, opts.get("converter", {}) or {})
        with tempfile.TemporaryDirectory() as tmpdir:
            docx_path = Path(tmpdir) / "document.docx"
            doc.save(str(docx_path))
            timeout = ResourceConfig.formatter(self.TEMPLATE, opts).find("timeout")
            produced = OfficeConverter.convert(docx_path, "doc", Path(tmpdir), timeout)
            return produced.read_bytes()


# --------------------------------------------------------------------------- #
# endregion Formatters                                                        #
# --------------------------------------------------------------------------- #
