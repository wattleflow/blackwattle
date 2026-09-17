# Module name: helpers/parsers/word.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
Word-document parsers — read-side deserialisation for DOCX and legacy DOC.

Both reuse ``WordConverter`` and return Markdown text. ``DocParser`` is the one
parser that cannot consume a stream directly: headless LibreOffice converts
files on disk, so it materialises the payload into its own temporary directory
rather than reaching back for the driver's path (DR-COR-015).
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from pathlib import Path
from typing import Any, BinaryIO
from wattleflow.concrete.serialisation import GenericParser
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["DocxParser", "DocParser"]

# --------------------------------------------------------------------------- #
# region Parsers                                                              #
# --------------------------------------------------------------------------- #


class DocxParser(GenericParser):
    """Read a DOCX stream and return Markdown-formatted text."""

    def deserialise(self, reader: BinaryIO, **opts: Any) -> str:
        from wattleflow.helpers.converters import WordConverter

        return WordConverter.read_docx(reader)


class DocParser(GenericParser):
    """Read a legacy .doc stream by converting it to .docx via LibreOffice,
    then extracting Markdown text via WordConverter.
    """

    def deserialise(self, reader: BinaryIO, **opts: Any) -> str:
        import tempfile

        from wattleflow.helpers.converters import WordConverter
        from wattleflow.helpers.converters.office import OfficeConverter

        OfficeConverter.binary()  # fail before touching the payload when LibreOffice is absent
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "input.doc"
            source.write_bytes(reader.read())
            produced = OfficeConverter.convert(source, "docx", Path(tmpdir), opts.get("timeout"))
            return WordConverter.read_docx(produced)


# --------------------------------------------------------------------------- #
# endregion Parsers                                                           #
# --------------------------------------------------------------------------- #
