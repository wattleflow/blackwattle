# Module name: helpers/converters/word.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
WordConverter — minimal Markdown ↔ DOCX bridge built on top of python-docx.

Public surface:
    - markdown_to_docx(text)  -> Document          (in-memory build)
    - docx_to_markdown(doc)   -> str               (extract back to Markdown)
    - read_docx(path)         -> str               (file → Markdown text)
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, BinaryIO, List, Optional, Union
from wattleflow.enums.pspf import Classification, ClassificationDLM

try:
    from docx import Document
    from docx.document import Document as WordDocument
    from docx.enum.style import WD_STYLE_TYPE
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    from docx.shared import Inches, Pt, RGBColor
except ImportError as e:
    raise ModuleNotFoundError(
        f"Missing required package to run this code: {__file__}.\n"
        "Please install it using:\n\tpip install python-docx"
    ) from e
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Classes                                                              #
# --------------------------------------------------------------------------- #


DEFAULT_CLASSIFICATION = "%s: %s, %s, %s" % (
    Classification.OFFICIAL.value,
    ClassificationDLM.SENSITIVE.value,
    ClassificationDLM.PERSONAL.value,
    ClassificationDLM.LEGAL_PREVILEGE.value,
)


@dataclass(frozen=True)
class DefaultConfig:
    font: str = "Segoe UI"
    size: int = 11
    h1: int = 18
    h2: int = 14
    h3: int = 13
    author: str = ""
    page_number_size: int = 9
    # Footer template; ``{page}`` and ``{total}`` become Word PAGE / NUMPAGES
    # fields. Empty string opts out of the footer entirely.
    page_number_format: str = "Page {page} of {total}"
    # Markdown blockquote (``> …``) marker. U+25B8 is the widest-supported
    # triangular bullet; pass "•" for an ordinary one.
    quote_glyph: str = "▸"
    quote_indent: float = 0.25
    header_grey: str = "D9D9D9"
    lang: str = "en-AU"
    lang_bidi: str = "hr-HR"
    classification: str = DEFAULT_CLASSIFICATION
    classification_size: int = 9

    @classmethod
    def from_mapping(cls, data: Optional[Union["DefaultConfig", dict]]) -> "DefaultConfig":
        if data is None:
            return cls()
        if isinstance(data, cls):
            return data
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in dict(data).items() if k in known})


class WordConverter:
    # Internal, non-configurable constants.
    BLACK = RGBColor(0x00, 0x00, 0x00)
    RED = RGBColor(0xFF, 0x00, 0x00)
    INLINE_RE = re.compile(r"(\*\*.+?\*\*|\*.+?\*|`.+?`)")
    # Control characters that OOXML/lxml reject (all C0/C1 except tab, LF, CR).
    XML_ILLEGAL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
    HR_RE = re.compile(r"^\s*([-=_])\1{2,}\s*$")
    HEADING_RE = re.compile(r"^(#{1,3})\s+(.*)$")
    BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)$")
    NUMBER_RE = re.compile(r"^\s*\d+\.\s+(.*)$")
    QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
    TABLE_DIVIDER_RE = re.compile(r"^[\s|:\-]+$")
    PAGE_TOKEN_RE = re.compile(r"(\{page\}|\{total\})")
    # Markers the reverse pass maps back to "> "; the configured glyph is only
    # one of them, since a document may have been produced with another.
    QUOTE_GLYPHS = ("▸", "‣", "▶", "▷", "➤", "»")

    def __init__(
        self,
        config: Optional[Union[DefaultConfig, dict]] = None,
        **kwargs: Any,
    ) -> None:
        # Precedence: explicit kwargs > ``config`` mapping > DefaultConfig.
        base: dict = {}
        if isinstance(config, DefaultConfig):
            base = asdict(config)
        elif isinstance(config, dict):
            base = dict(config)
        cfg = DefaultConfig.from_mapping({**base, **kwargs})

        self.config: DefaultConfig = cfg
        self.font: str = cfg.font
        self.size: int = int(cfg.size)
        self.h1: int = int(cfg.h1)
        self.h2: int = int(cfg.h2)
        self.h3: int = int(cfg.h3)
        self.author: str = cfg.author
        self.header_grey: str = cfg.header_grey
        self.page_number_size: int = int(cfg.page_number_size)
        self.page_number_format: str = cfg.page_number_format
        self.quote_glyph: str = cfg.quote_glyph
        self.quote_indent: float = float(cfg.quote_indent)
        self.lang: str = cfg.lang
        self.lang_bidi: str = cfg.lang_bidi
        # Classification stamped into every section header; ``""``/``None``
        # opts out (header skipped).
        self.classification: str = cfg.classification
        self.classification_size: int = int(cfg.classification_size)
        self.doc: WordDocument = Document()
        self._configure_styles()
        self._configure_page_numbers()
        self._configure_classification_header()

    # ----------------------------------------------------------------- #
    # region Private methods                                            #
    # ----------------------------------------------------------------- #

    # ----------------------------------------------------------------- #
    # Style and metadata setup                                          #
    # ----------------------------------------------------------------- #
    def _configure_styles(self) -> None:
        normal = self.doc.styles["Normal"]
        normal.font.name = self.font
        normal.font.size = Pt(self.size)
        normal.font.color.rgb = self.BLACK
        rpr = normal.element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.append(rfonts)
        for attr in ("w:ascii", "w:hAnsi", "w:cs"):
            rfonts.set(qn(attr), self.font)
        self._apply_language(rpr)

        heading_sizes = {1: self.h1, 2: self.h2, 3: self.h3}
        for level, size in heading_sizes.items():
            style = self.doc.styles[f"Heading {level}"]
            style.font.name = self.font
            style.font.size = Pt(size)
            style.font.bold = True
            style.font.color.rgb = self.BLACK
            self._apply_language(style.element.get_or_add_rPr())

        # Page number style — used by footer paragraphs
        try:
            page_style = self.doc.styles["Page Number"]
        except KeyError:
            page_style = self.doc.styles.add_style("Page Number", WD_STYLE_TYPE.CHARACTER)
        page_style.font.name = self.font
        page_style.font.size = Pt(self.page_number_size)
        page_style.font.color.rgb = self.BLACK

    def _apply_language(self, rpr) -> None:
        """Set Western + complex-script languages on a runProperties element."""
        lang = rpr.find(qn("w:lang"))
        if lang is None:
            lang = OxmlElement("w:lang")
            rpr.append(lang)
        lang.set(qn("w:val"), self.lang)
        lang.set(qn("w:eastAsia"), self.lang)
        lang.set(qn("w:bidi"), self.lang_bidi)

    def _configure_page_numbers(self) -> None:
        """Right-aligned "Page X of Y" in every section footer.

        Both numbers are Word FIELDS (``PAGE``, ``NUMPAGES``), never literal
        text: the renderer resolves them at paint time, so the total stays
        correct after the document is edited or content reflows.
        """
        template = (self.page_number_format or "").strip()
        if not template:
            return

        for section in self.doc.sections:
            footer = section.footer
            footer.is_linked_to_previous = False
            para = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
            para.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            for run in list(para.runs):
                run.text = ""

            for token in self.PAGE_TOKEN_RE.split(template):
                if not token:
                    continue
                run = self._footer_run(para)
                if token == "{page}":
                    self._add_field(run, "PAGE")
                elif token == "{total}":
                    self._add_field(run, "NUMPAGES")
                else:
                    run.text = token

    def _footer_run(self, para):
        run = para.add_run()
        run.font.name = self.font
        run.font.size = Pt(self.page_number_size)
        run.font.color.rgb = self.BLACK
        return run

    @staticmethod
    def _add_field(run, instruction: str) -> None:
        """Turn ``run`` into a Word field: begin / instruction / separate /
        cached result / end. The cached result is what a reader that does not
        recalculate fields displays, so it must not be left out."""
        begin = OxmlElement("w:fldChar")
        begin.set(qn("w:fldCharType"), "begin")
        instr = OxmlElement("w:instrText")
        instr.set(qn("xml:space"), "preserve")
        instr.text = instruction
        separate = OxmlElement("w:fldChar")
        separate.set(qn("w:fldCharType"), "separate")
        cached = OxmlElement("w:t")
        cached.text = "1"
        end = OxmlElement("w:fldChar")
        end.set(qn("w:fldCharType"), "end")
        for element in (begin, instr, separate, cached, end):
            run._r.append(element)

    def _configure_classification_header(self) -> None:
        """Stamp the security classification into every section header.

        Centred, 9pt and red. Skipped when ``classification`` is empty so
        callers can opt out by passing ``classification=""``.
        """
        label = (self.classification or "").strip()
        if not label:
            return
        for section in self.doc.sections:
            header = section.header
            header.is_linked_to_previous = False
            para = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in list(para.runs):
                run.text = ""
            run = para.add_run(label)
            run.font.name = self.font
            run.font.size = Pt(self.classification_size)
            run.font.color.rgb = self.RED

    def _strip_metadata(self) -> None:
        cp = self.doc.core_properties
        cp.author = self.author
        cp.last_modified_by = self.author
        for field in ("title", "subject", "keywords", "comments", "category"):
            try:
                setattr(cp, field, "")
            except (ValueError, AttributeError):
                pass

    # ----------------------------------------------------------------- #
    # Line-continuity helpers                                           #
    # ----------------------------------------------------------------- #
    def _is_block_start(self, line: str) -> bool:
        if line.strip() == "":
            return True
        if self.HEADING_RE.match(line) or self.HR_RE.match(line):
            return True
        if self.BULLET_RE.match(line) or self.NUMBER_RE.match(line):
            return True
        if self.QUOTE_RE.match(line):
            return True
        if line.lstrip().startswith("|"):
            return True
        return False

    @staticmethod
    def _collapse(parts: List[str]) -> str:
        return re.sub(r"\s+", " ", " ".join(p.strip() for p in parts if p)).strip()

    # ----------------------------------------------------------------- #
    # Inline formatting                                                 #
    # ----------------------------------------------------------------- #
    def _add_inline(self, paragraph, text: str) -> None:
        text = self.XML_ILLEGAL_RE.sub("", text)
        for token in self.INLINE_RE.split(text):
            if not token:
                continue
            if token.startswith("**") and token.endswith("**"):
                run = paragraph.add_run(token[2:-2])
                run.bold = True
            elif token.startswith("*") and token.endswith("*"):
                run = paragraph.add_run(token[1:-1])
                run.italic = True
            elif token.startswith("`") and token.endswith("`"):
                run = paragraph.add_run(token[1:-1])
                run.font.name = "Consolas"
            else:
                run = paragraph.add_run(token)
            run.font.color.rgb = self.BLACK

    # ----------------------------------------------------------------- #
    # region Block builders                                             #
    # ----------------------------------------------------------------- #

    def add_heading(self, level: int, text: str) -> None:
        para = self.doc.add_paragraph(style=f"Heading {level}")
        self._add_inline(para, text)

    def add_paragraph(self, text: str) -> None:
        para = self.doc.add_paragraph()
        self._add_inline(para, text)

    def add_bullet(self, text: str) -> None:
        para = self.doc.add_paragraph(style="List Bullet")
        self._add_inline(para, text)

    def add_numbered(self, text: str) -> None:
        para = self.doc.add_paragraph(style="List Number")
        self._add_inline(para, text)

    def add_quote(self, text: str) -> None:
        """Markdown blockquote as a triangle-glyph bullet.

        The glyph is a literal run behind a hanging indent rather than a list
        style: the bullet character of ``List Bullet`` lives in the numbering
        part, which cannot be redefined per-paragraph — so a quote styled that
        way would silently render as an ordinary dot.
        """
        para = self.doc.add_paragraph()
        para.paragraph_format.left_indent = Inches(self.quote_indent)
        para.paragraph_format.first_line_indent = Inches(-self.quote_indent)
        marker = para.add_run(f"{self.quote_glyph}\t")
        marker.font.name = self.font
        marker.font.color.rgb = self.BLACK
        self._add_inline(para, text)

    def add_horizontal_rule(self) -> None:
        para = self.doc.add_paragraph()
        p_pr = para._p.get_or_add_pPr()
        borders = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        bottom.set(qn("w:val"), "single")
        bottom.set(qn("w:sz"), "6")
        bottom.set(qn("w:space"), "1")
        bottom.set(qn("w:color"), "000000")
        borders.append(bottom)
        p_pr.append(borders)

    def add_table(self, rows: List[List[str]]) -> None:
        if not rows:
            return
        table = self.doc.add_table(rows=0, cols=len(rows[0]))
        table.style = "Table Grid"
        for r_idx, row in enumerate(rows):
            cells = table.add_row().cells
            for c_idx, cell_text in enumerate(row):
                if c_idx >= len(cells):
                    break
                cell = cells[c_idx]
                cell.text = ""
                self._add_inline(cell.paragraphs[0], cell_text.strip())
                if r_idx == 0:
                    self._shade_cell(cell, self.header_grey)
                    for run in cell.paragraphs[0].runs:
                        run.bold = True

    def _shade_cell(self, cell, fill: str) -> None:
        tc_pr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), fill)
        tc_pr.append(shd)

    # ----------------------------------------------------------------- #
    # endregion Block builders                                          #
    # ----------------------------------------------------------------- #

    # ----------------------------------------------------------------- #
    # Consumers                                                         #
    # ----------------------------------------------------------------- #
    def _consume_list_item(self, lines: List[str], i: int, match: re.Match):
        first_text = match.group(1)
        i += 1
        continuation: List[str] = []
        n = len(lines)
        while i < n and not self._is_block_start(lines[i]):
            continuation.append(lines[i])
            i += 1
        return self._collapse([first_text] + continuation), i

    def _consume_quote(self, lines: List[str], i: int):
        """Consume a whole blockquote — consecutive ``>`` lines plus their lazy
        continuations — into ONE bullet.

        Markdown treats a wrapped quote as a single block, and the repository's
        own notes are written that way, so emitting a bullet per physical line
        would split one note into three.
        """
        parts: List[str] = []
        n = len(lines)
        while i < n:
            quote = self.QUOTE_RE.match(lines[i])
            if quote:
                parts.append(quote.group(1))
                i += 1
                continue
            if self._is_block_start(lines[i]):
                break
            parts.append(lines[i])
            i += 1
        return self._collapse(parts), i

    def _consume_table(self, lines: List[str], i: int) -> int:
        rows: List[List[str]] = []
        n = len(lines)
        while i < n and lines[i].lstrip().startswith("|"):
            stripped = lines[i].strip()
            if self.TABLE_DIVIDER_RE.fullmatch(stripped):
                i += 1
                continue
            raw = stripped.strip("|")
            rows.append([c.strip() for c in raw.split("|")])
            i += 1
        if rows:
            self.add_table(rows)
        return i

    # ----------------------------------------------------------------- #
    # endregion Private methods                                         #
    # ----------------------------------------------------------------- #

    # ----------------------------------------------------------------- #
    # region Public API                                                 #
    # ----------------------------------------------------------------- #

    def markdown_to_docx(self, content: str) -> WordDocument:
        """Build a python-docx Document from Markdown text. Caller saves it."""
        lines = content.splitlines()
        i, n = 0, len(lines)
        while i < n:
            line = lines[i]
            if line.strip() == "":
                i += 1
                continue
            if self.HR_RE.match(line):
                self.add_horizontal_rule()
                i += 1
                continue
            heading = self.HEADING_RE.match(line)
            if heading:
                level = len(heading.group(1))
                self.add_heading(level, heading.group(2).strip())
                i += 1
                continue
            if line.lstrip().startswith("|"):
                i = self._consume_table(lines, i)
                continue
            if self.QUOTE_RE.match(line):
                text, i = self._consume_quote(lines, i)
                if text:
                    self.add_quote(text)
                continue
            bullet = self.BULLET_RE.match(line)
            number = self.NUMBER_RE.match(line)
            if bullet or number:
                text, i = self._consume_list_item(lines, i, bullet or number)
                if bullet:
                    self.add_bullet(text)
                else:
                    self.add_numbered(text)
                continue
            buf = [line]
            i += 1
            while i < n and not self._is_block_start(lines[i]):
                buf.append(lines[i])
                i += 1
            self.add_paragraph(self._collapse(buf))

        self._strip_metadata()
        return self.doc

    def convert_markdown_file(self, input_path: str, output_path: str) -> str:
        """Convenience: read a Markdown file and write a DOCX file."""
        text = Path(input_path).read_text(encoding="utf-8")
        doc = self.markdown_to_docx(text)
        doc.save(output_path)
        return output_path

    # ----------------------------------------------------------------- #
    # endregion Public API                                              #
    # ----------------------------------------------------------------- #

    # ----------------------------------------------------------------- #
    # region Static methods                                             #
    # ----------------------------------------------------------------- #
    # Reverse direction — DOCX → Markdown                               #
    # ----------------------------------------------------------------- #
    @classmethod
    def docx_to_markdown(cls, doc: Union[WordDocument, str, Path]) -> str:
        """Extract DOCX content as best-effort Markdown.

        Handles headings (H1–H3), bullet/numbered lists, plain paragraphs and
        simple tables. Inline formatting (bold/italic) is preserved via
        Markdown emphasis markers.
        """
        if isinstance(doc, (str, Path)):
            doc = Document(str(doc))

        out: List[str] = []
        body = doc.element.body
        for child in body.iterchildren():
            tag = child.tag.split("}", 1)[-1]
            if tag == "p":
                para = next((p for p in doc.paragraphs if p._p is child), None)
                if para is None:
                    continue
                text = cls._paragraph_to_md(para)
                out.append(text)
            elif tag == "tbl":
                table = next((t for t in doc.tables if t._tbl is child), None)
                if table is None:
                    continue
                out.append(cls._table_to_md(table))
                out.append("")
        return "\n".join(out).rstrip() + "\n"

    @classmethod
    def _paragraph_to_md(cls, para) -> str:
        style = (para.style.name or "").lower() if para.style else ""
        text_parts: List[str] = []
        for run in para.runs:
            t = run.text
            if not t:
                continue
            if run.bold and run.italic:
                t = f"***{t}***"
            elif run.bold:
                t = f"**{t}**"
            elif run.italic:
                t = f"*{t}*"
            text_parts.append(t)
        text = "".join(text_parts).strip()
        if not text:
            return ""
        if style.startswith("heading 1"):
            return f"# {text}"
        if style.startswith("heading 2"):
            return f"## {text}"
        if style.startswith("heading 3"):
            return f"### {text}"
        if "bullet" in style:
            return f"- {text}"
        if "number" in style:
            return f"1. {text}"
        # A quote carries no style of its own (see add_quote), so the glyph is
        # the only thing that identifies it on the way back.
        for glyph in cls.QUOTE_GLYPHS:
            if text.startswith(glyph):
                return f"> {text[len(glyph):].strip()}"
        return text

    @classmethod
    def _table_to_md(cls, table) -> str:
        rows: List[List[str]] = []
        for row in table.rows:
            cells: List[str] = []
            for cell in row.cells:
                p_text = cls._paragraph_to_md(cell.paragraphs[0]) if cell.paragraphs else ""
                cells.append(p_text or cell.text.strip())
            rows.append(cells)
        if not rows:
            return ""
        widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]

        def _row(r: List[str]) -> str:
            return "| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(r)) + " |"

        lines = [_row(rows[0]), "| " + " | ".join("-" * w for w in widths) + " |"]
        for r in rows[1:]:
            lines.append(_row(r))
        return "\n".join(lines)

    @classmethod
    def read_docx(cls, source: Union[str, Path, BinaryIO]) -> str:
        """Open a DOCX file or stream and return Markdown text."""
        opened = source if hasattr(source, "read") else str(source)
        return cls.docx_to_markdown(Document(opened))

    # ----------------------------------------------------------------- #
    # DOCX → PDF                                                        #
    # ----------------------------------------------------------------- #
    @staticmethod
    def docx_to_pdf(
        input_path: Union[str, Path],
        output_path: Optional[Union[str, Path]] = None,
        timeout: int = 120,
    ) -> str:
        """Convert a DOCX file to PDF using headless LibreOffice.

        Requires `libreoffice` (or `soffice`) on PATH. Returns the output path.
        """
        src = Path(input_path).expanduser().resolve()
        if not src.is_file():
            raise FileNotFoundError(f"DOCX not found: {src}")

        binary = shutil.which("libreoffice") or shutil.which("soffice")
        if binary is None:
            raise RuntimeError("LibreOffice not found. Install: sudo apt install libreoffice")

        out_path = (
            Path(output_path).expanduser().resolve() if output_path else src.with_suffix(".pdf")
        )
        out_dir = out_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            binary,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(src),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                f"LibreOffice conversion failed: {result.stderr.strip() or result.stdout.strip()}"
            )

        produced = out_dir / f"{src.stem}.pdf"
        if produced != out_path:
            produced.replace(out_path)
        return str(out_path)

    # ----------------------------------------------------------------- #
    # endregion Static methods                                          #
    # ----------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# endregion Classes                                                           #
# --------------------------------------------------------------------------- #

__all__ = [
    "DEFAULT_CLASSIFICATION",
    "WordConverter",
    "DefaultConfig",
]
