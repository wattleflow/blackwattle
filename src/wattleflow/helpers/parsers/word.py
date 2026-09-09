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
        import shutil
        import subprocess
        import tempfile

        from wattleflow.helpers.converters import WordConverter

        binary = shutil.which("libreoffice") or shutil.which("soffice")
        if binary is None:
            raise RuntimeError(
                "LibreOffice not found. Install: sudo apt install libreoffice"
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "input.doc"
            source.write_bytes(reader.read())
            result = subprocess.run(
                [
                    binary,
                    "--headless",
                    "--convert-to",
                    "docx",
                    "--outdir",
                    tmpdir,
                    str(source),
                ],
                capture_output=True,
                text=True,
                timeout=opts.pop("timeout", 120),
                check=False,
            )
            if result.returncode != 0:
                detail = result.stderr.strip() or result.stdout.strip()
                raise RuntimeError(f"LibreOffice .doc conversion failed: {detail}")
            docx_path = next(Path(tmpdir).glob("*.docx"), None)
            if docx_path is None:
                raise RuntimeError(
                    "LibreOffice produced no .docx output for .doc input"
                )
            return WordConverter.read_docx(docx_path)


# --------------------------------------------------------------------------- #
# endregion Parsers                                                           #
# --------------------------------------------------------------------------- #
