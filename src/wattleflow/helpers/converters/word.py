# Module name: helpers/converters/word.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""WordConverter — Markdown ↔ DOCX over python-docx.

Markdown subset: CommonMark §2.4 escapes, §6.1 code spans, §6.2 flanking emphasis, §6.3 links, and
GFM tables. Hand-written, as no Markdown implementation is in the distribution tier (NFRQ-ORG-09).
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, BinaryIO, List, Optional, Union
from urllib.parse import urlsplit
from wattleflow.helpers.resource_config import ResourceConfig
from wattleflow.helpers.converters.office import OfficeConverter

try:
    from docx import Document
    from docx.document import Document as WordDocument
    from docx.enum.style import WD_STYLE_TYPE
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    from docx.shared import Inches, Pt, RGBColor
    from docx.table import Table
    from docx.text.hyperlink import Hyperlink
except ImportError as e:
    raise ModuleNotFoundError(
        f"Missing required package to run this code: {__file__}.\nPlease install it using:\n\tpip install python-docx"
    ) from e
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Classes                                                              #
# --------------------------------------------------------------------------- #


class WordConverter:
    # v0.0.4 (DR-PRC-007): settings live in the distribution template; configuration overrides them.
    TEMPLATE = "word"
    LINK_SCHEMES = frozenset({"http", "https", "mailto"})
    # Order matters: escapes and code spans are opaque to emphasis.
    INLINE_RE = re.compile(
        r"(?P<escape>\\[!-/:-@\[-`{-~])"
        r"|(?P<code>`[^`]+`)"
        r"|(?P<link>\[(?P<link_text>[^\]]+)\]\((?P<link_url>[^)\s]+)\))"
        r"|(?P<strong_em>\*\*\*(?=\S)(?P<strong_em_text>.+?)(?<=\S)\*\*\*)"
        r"|(?P<strong>\*\*(?=\S)(?P<strong_text>.+?)(?<=\S)\*\*)"
        r"|(?P<em>\*(?=[^\s*])(?P<em_text>.+?)(?<=[^\s*])\*)"
    )
    # Escaped on reading, so Word text never reads back as markup.
    ESCAPE_RE = re.compile(r"([\\`*\[\]|])")
    UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")
    # Replaces the template's app.xml, which names its authoring application.
    EMPTY_APP_PROPERTIES = (
        b"<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n"
        b'<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
        b'extended-properties"/>'
    )
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

    def __init__(self, config: Optional[Mapping[str, Any]] = None, **kwargs: Any) -> None:
        defaults = self.defaults()
        overrides = {**dict(config or {}), **kwargs}
        self.config: dict[str, Any] = {**defaults, **{k: v for k, v in overrides.items() if k in defaults}}
        settings = self.config
        self.font: str = self._setting(settings, "font")
        self.size: int = int(self._setting(settings, "size"))
        self.h1: int = int(self._setting(settings, "h1"))
        self.h2: int = int(self._setting(settings, "h2"))
        self.h3: int = int(self._setting(settings, "h3"))
        self.author: str = self._setting(settings, "author")
        self.code_font: str = self._setting(settings, "code_font")
        self.text_colour = RGBColor.from_string(self._setting(settings, "text_colour"))
        self.header_grey: str = self._setting(settings, "header_grey")
        self.page_number_size: int = int(self._setting(settings, "page_number_size"))
        self.page_number_format: str = self._setting(settings, "page_number_format")
        self.quote_glyph: str = self._setting(settings, "quote_glyph")
        self.quote_indent: float = float(self._setting(settings, "quote_indent"))
        self.lang: str = self._setting(settings, "lang")
        self.lang_bidi: str = self._setting(settings, "lang_bidi")
        self.classification: str = self._setting(settings, "classification")
        self.classification_size: int = int(self._setting(settings, "classification_size"))
        self.classification_colour = RGBColor.from_string(self._setting(settings, "classification_colour"))
        self.doc: WordDocument = self._start_document()

    @classmethod
    def defaults(cls) -> dict[str, Any]:
        """The distribution template, read through IConfig."""
        return dict(ResourceConfig.formatter(cls.TEMPLATE).defaults)

    @classmethod
    def unknown(cls, settings: Optional[Mapping[str, Any]]) -> list[str]:
        """Setting keys the template does not define, so a caller can report them."""
        return ResourceConfig.formatter(cls.TEMPLATE).unknown(settings)

    @staticmethod
    def _setting(settings: Mapping[str, Any], key: str) -> Any:
        if key not in settings:
            raise ValueError(f"Word converter template lacks the setting '{key}'")
        return settings[key]

    # ----------------------------------------------------------------- #
    # region Private methods                                            #
    # ----------------------------------------------------------------- #

    # ----------------------------------------------------------------- #
    # Style and metadata setup                                          #
    # ----------------------------------------------------------------- #
    def _start_document(self) -> WordDocument:
        # v0.0.4 (DR-PRC-005): one document per conversion.
        self.doc = Document()
        self._configure_styles()
        self._configure_page_numbers()
        self._configure_classification_header()
        self._strip_metadata()
        return self.doc

    def _configure_styles(self) -> None:
        normal = self.doc.styles["Normal"]
        normal.font.name = self.font
        normal.font.size = Pt(self.size)
        normal.font.color.rgb = self.text_colour
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
            style.font.color.rgb = self.text_colour
            self._apply_language(style.element.get_or_add_rPr())

        # Page number style — used by footer paragraphs
        try:
            page_style = self.doc.styles["Page Number"]
        except KeyError:
            page_style = self.doc.styles.add_style("Page Number", WD_STYLE_TYPE.CHARACTER)
        page_style.font.name = self.font
        page_style.font.size = Pt(self.page_number_size)
        page_style.font.color.rgb = self.text_colour

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

            for part in self.PAGE_TOKEN_RE.split(template):
                if not part:
                    continue
                run = self._footer_run(para)
                if part == "{page}":
                    self._add_field(run, "PAGE")
                elif part == "{total}":
                    self._add_field(run, "NUMPAGES")
                else:
                    run.text = part

    def _footer_run(self, para):
        run = para.add_run()
        run.font.name = self.font
        run.font.size = Pt(self.page_number_size)
        run.font.color.rgb = self.text_colour
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
            run.font.color.rgb = self.classification_colour

    def _strip_metadata(self) -> None:
        cp = self.doc.core_properties
        cp.author = self.author
        cp.last_modified_by = self.author
        cp.revision = 1
        for field in (
            "title",
            "subject",
            "keywords",
            "comments",
            "category",
            "content_status",
            "identifier",
            "language",
            "version",
        ):
            setattr(cp, field, "")
        # v0.0.4 (DR-PRC-005): the template's dates would date the document 2013.
        for tag in ("dcterms:created", "dcterms:modified", "cp:lastPrinted"):
            for node in cp._element.findall(qn(tag)):
                cp._element.remove(node)

        package = self.doc.part.package
        for r_id, rel in list(package.rels.items()):
            if rel.reltype == RT.THUMBNAIL:
                package.rels.pop(r_id)
            elif rel.reltype == RT.EXTENDED_PROPERTIES:
                # No python-docx API for app.xml.
                rel.target_part._blob = self.EMPTY_APP_PROPERTIES

        settings = self.doc.settings.element
        for node in settings.findall(qn("w:rsids")):
            settings.remove(node)
        for node in self.doc.element.iter():
            for name in [a for a in node.attrib if a.rsplit("}", 1)[-1].startswith("rsid")]:
                del node.attrib[name]

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
        plain: List[str] = []
        position = 0
        for match in self.INLINE_RE.finditer(text):
            plain.append(text[position : match.start()])
            position = match.end()
            kind = match.lastgroup
            if kind == "escape":
                plain.append(match.group()[1])
                continue
            if kind == "link" and urlsplit(match["link_url"]).scheme not in self.LINK_SCHEMES:
                plain.append(match.group())
                continue
            self._add_plain(paragraph, plain)
            if kind == "code":
                self._add_run(paragraph, match.group()[1:-1]).font.name = self.code_font
            elif kind == "link":
                self._add_link(paragraph, match["link_text"], match["link_url"])
            else:
                run = self._add_run(paragraph, match[f"{kind}_text"])
                run.bold = kind in ("strong", "strong_em")
                run.italic = kind in ("em", "strong_em")
        plain.append(text[position:])
        self._add_plain(paragraph, plain)

    def _add_plain(self, paragraph, parts: List[str]) -> None:
        text = "".join(parts)
        parts.clear()
        if text:
            self._add_run(paragraph, text)

    def _add_run(self, paragraph, text: str):
        run = paragraph.add_run(text)
        run.font.color.rgb = self.text_colour
        return run

    def _add_link(self, paragraph, text: str, url: str) -> None:
        r_id = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
        link = OxmlElement("w:hyperlink")
        link.set(qn("r:id"), r_id)
        run = OxmlElement("w:r")
        properties = OxmlElement("w:rPr")
        underline = OxmlElement("w:u")
        underline.set(qn("w:val"), "single")
        properties.append(underline)
        run.append(properties)
        label = OxmlElement("w:t")
        label.set(qn("xml:space"), "preserve")
        label.text = text
        run.append(label)
        link.append(run)
        paragraph._p.append(link)

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
        marker.font.color.rgb = self.text_colour
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
        # v0.0.4 (DR-PRC-005): widen rather than drop cells beyond the header, as GFM does.
        table = self.doc.add_table(rows=0, cols=max(len(row) for row in rows))
        table.style = "Table Grid"
        for r_idx, row in enumerate(rows):
            cells = table.add_row().cells
            for c_idx, cell_text in enumerate(row):
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
            raw = stripped.removeprefix("|").removesuffix("|")
            rows.append([c.strip() for c in self.UNESCAPED_PIPE_RE.split(raw)])
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
        """Build a new python-docx Document from Markdown text. Caller saves it."""
        self._start_document()
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
        """Extract DOCX content as Markdown that ``markdown_to_docx`` reads back unchanged."""
        if isinstance(doc, (str, Path)):
            doc = Document(str(doc))

        code_font = cls.defaults()["code_font"]
        out: List[str] = []
        previous = ""
        # v0.0.4 (DR-PRC-005): one pass; a lookup per block was quadratic.
        for block in doc.iter_inner_content():
            if isinstance(block, Table):
                kind, text = "table", cls._table_to_md(block, code_font)
            else:
                kind, text = cls._paragraph_to_md(block, code_font)
            if not text:
                continue
            if out:
                out.append("\n" if kind == previous and kind in ("bullet", "number") else "\n\n")
            out.append(text)
            previous = kind
        return "".join(out) + "\n"

    @classmethod
    def _paragraph_to_md(cls, para, code_font: str) -> tuple[str, str]:
        style = (para.style.name or "").lower() if para.style else ""
        text = cls._inline_to_md(para, code_font).strip()
        if not text:
            borders = para._p.pPr.find(qn("w:pBdr")) if para._p.pPr is not None else None
            if borders is not None and borders.find(qn("w:bottom")) is not None:
                return "rule", "---"
            return "", ""
        for level in (1, 2, 3):
            if style.startswith(f"heading {level}"):
                return "heading", f"{'#' * level} {text}"
        if "bullet" in style:
            return "bullet", f"- {text}"
        if "number" in style:
            return "number", f"1. {text}"
        # A quote carries no style of its own (see add_quote), so the glyph is
        # the only thing that identifies it on the way back.
        for glyph in cls.QUOTE_GLYPHS:
            if text.startswith(glyph):
                return "quote", f"> {text[len(glyph) :].strip()}"
        return "paragraph", cls._escape_block_start(text)

    @classmethod
    def _inline_to_md(cls, para, code_font: str, bold_is_style: bool = False) -> str:
        """Runs and hyperlinks as inline Markdown; ``bold_is_style`` drops bold a style implies."""
        parts: List[str] = []
        for item in para.iter_inner_content():
            if isinstance(item, Hyperlink):
                label = cls._escape("".join(run.text for run in item.runs).replace("\n", " "))
                url = item.url.replace(" ", "%20").replace(")", "%29")
                parts.append(f"[{label}]({url})" if url and label else label)
                continue
            text = item.text.replace("\n", " ")
            if not text:
                continue
            code = item.font.name == code_font and "`" not in text
            bold = bool(item.bold) and not bold_is_style
            italic = bool(item.italic)
            if code:
                parts.append(f"`{text}`")
                continue
            core = text.strip()
            if not core or not (bold or italic):
                parts.append(cls._escape(text))
                continue
            marker = "***" if bold and italic else "**" if bold else "*"
            lead = text[: len(text) - len(text.lstrip())]
            trail = text[len(text.rstrip()) :]
            parts.append(f"{lead}{marker}{cls._escape(core)}{marker}{trail}")
        return "".join(parts)

    @classmethod
    def _escape(cls, text: str) -> str:
        return cls.ESCAPE_RE.sub(r"\\\1", text)

    @classmethod
    def _escape_block_start(cls, text: str) -> str:
        """Keep a plain paragraph from reading back as a heading, list, quote or rule."""
        number = re.match(r"^(\s*\d+)\.(\s)", text)
        if number:
            return f"{number.group(1)}\\.{text[number.end(1) + 1 :]}"
        if cls.HEADING_RE.match(text) or cls.HR_RE.match(text) or cls.BULLET_RE.match(text):
            return "\\" + text
        if cls.QUOTE_RE.match(text):
            return "\\" + text
        return text

    @classmethod
    def _table_to_md(cls, table, code_font: str) -> str:
        rows: List[List[str]] = []
        for r_idx, row in enumerate(table.rows):
            rows.append(
                [
                    # All cell paragraphs; the header row is bold by house style.
                    " ".join(
                        filter(None, (cls._inline_to_md(p, code_font, r_idx == 0).strip() for p in cell.paragraphs))
                    )
                    for cell in row.cells
                ]
            )
        if not rows:
            return ""
        columns = max(len(r) for r in rows)
        rows = [r + [""] * (columns - len(r)) for r in rows]
        widths = [max(3, max(len(r[i]) for r in rows)) for i in range(columns)]

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
        timeout: Optional[int] = None,
    ) -> str:
        """Convert a DOCX file to PDF using headless LibreOffice. Returns the output path."""
        src = Path(input_path).expanduser().resolve()
        if not src.is_file():
            raise FileNotFoundError(f"DOCX not found: {src}")

        out_path = Path(output_path).expanduser().resolve() if output_path else src.with_suffix(".pdf")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        produced = OfficeConverter.convert(src, "pdf", out_path.parent, timeout)
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
    "WordConverter",
]
