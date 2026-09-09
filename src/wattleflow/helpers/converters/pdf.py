# Module name: helpers/converters/pdf.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
PdfConverter — formatting/redaction bridge built on top of PyMuPDF.

Strategies build the final PDF bytes here and hand them to the driver, so
drivers never need to know about redactions, font handling or metadata
stripping. Mirrors the helpers.converters.word layout.

Public surface:
    - apply_redactions(source, spans) -> bytes
    - split_to_pages(source)          -> iterator of (idx, bytes)
    - strip_metadata(pdf)             -> None    (in-place)
    - to_bytes(source)                -> bytes   (load whatever, return bytes)
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple, Union

try:
    import fitz  # PyMuPDF
except ImportError as e:
    raise ModuleNotFoundError(
        f"Missing required package to run this code: {__file__}.\n"
        "Please install it using:\n\tpip install PyMuPDF"
    ) from e
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #
# PyMuPDF Base-14 families: regular, bold, italic, bold-italic.
PDF_FONT_FAMILY: Dict[str, Tuple[str, str, str, str]] = {
    "helv": ("helv", "hebo", "heit", "hebi"),
    "tiro": ("tiro", "tibo", "tiit", "tibi"),
    "cour": ("cour", "cobo", "coit", "cobi"),
}
SpanList = List[Dict[str, Any]]
Source = Union[str, Path, bytes, bytearray]
# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Classes                                                              #
# --------------------------------------------------------------------------- #


class PdfConverter:
    """Formatting helper for PDF documents. Strategies own the lifecycle.

    Defaults are tuned for redaction output (blackout on, 0.7 font scale,
    metadata stripped). Override via kwargs at call time when needed."""

    DEFAULT_FONT_NAME = "helv"
    DEFAULT_FONT_SCALE = 0.7
    DEFAULT_BLACKOUT = True
    DEFAULT_STRIP_METADATA = True
    GARBAGE_LEVEL = 4

    def __init__(self, **kwargs: Any) -> None:
        self.font_name: str = kwargs.get("font_name", self.DEFAULT_FONT_NAME)
        self.font_size: Optional[float] = kwargs.get("font_size", None)
        self.font_scale: float = float(kwargs.get("font_scale", self.DEFAULT_FONT_SCALE))
        self.bold: bool = bool(kwargs.get("bold", False))
        self.italic: bool = bool(kwargs.get("italic", False))
        self.underline: bool = bool(kwargs.get("underline", False))
        self.blackout: bool = bool(kwargs.get("blackout", self.DEFAULT_BLACKOUT))
        self.strip_metadata_on_save: bool = bool(
            kwargs.get("strip_metadata", self.DEFAULT_STRIP_METADATA)
        )

    # ----------------------------------------------------------------- #
    # region Public API                                                 #
    # ----------------------------------------------------------------- #
    def apply_redactions(self, source: Source, spans: SpanList) -> bytes:
        """Apply redaction spans to source PDF and return final bytes."""
        pdf = self._open(source)
        try:
            self._apply(pdf, spans)
            if self.strip_metadata_on_save:
                self.strip_metadata(pdf)
            return pdf.tobytes(garbage=self.GARBAGE_LEVEL, deflate=True, clean=True)
        finally:
            pdf.close()

    def split_to_pages(
        self,
        source: Source,
        spans: Optional[SpanList] = None,
    ) -> Iterator[Tuple[int, bytes]]:
        """Yield (page_index, single_page_pdf_bytes) for every page.

        When ``spans`` are supplied, per-page redactions are applied to each
        resulting single-page document (page index is remapped to 0)."""
        spans_by_page = self._group_by_page(spans or [])

        src = self._open(source)
        try:
            for idx in range(src.page_count):
                single = fitz.open()
                try:
                    single.insert_pdf(src, from_page=idx, to_page=idx)
                    page_spans = [{**s, "page": 0} for s in spans_by_page.get(idx, [])]
                    if page_spans:
                        self._apply(single, page_spans)
                    if self.strip_metadata_on_save:
                        self.strip_metadata(single)
                    yield idx, single.tobytes(garbage=self.GARBAGE_LEVEL, deflate=True, clean=True)
                finally:
                    single.close()
        finally:
            src.close()

    @classmethod
    def to_bytes(cls, source: Source) -> bytes:
        """Normalise source to bytes. Re-serialises through PyMuPDF so callers
        get a clean payload regardless of the input form."""
        pdf = cls._open(source)
        try:
            return pdf.tobytes(garbage=cls.GARBAGE_LEVEL, deflate=True, clean=True)
        finally:
            pdf.close()

    @staticmethod
    def strip_metadata(pdf: "fitz.Document") -> None:
        """Wipe document info + XMP metadata in place."""
        pdf.set_metadata({k: None for k in (pdf.metadata or {})})
        try:
            pdf.del_xml_metadata()
        except Exception:
            # XMP stream may be absent — not an error.
            pass

    # ----------------------------------------------------------------- #
    # endregion Public API                                              #
    # ----------------------------------------------------------------- #

    # ----------------------------------------------------------------- #
    # region Private                                                    #
    # ----------------------------------------------------------------- #
    @staticmethod
    def _open(source: Source) -> "fitz.Document":
        if isinstance(source, (bytes, bytearray)):
            return fitz.open(stream=bytes(source), filetype="pdf")
        return fitz.open(str(source))

    @staticmethod
    def _group_by_page(spans: SpanList) -> Dict[int, SpanList]:
        grouped: Dict[int, SpanList] = {}
        for span in spans:
            grouped.setdefault(int(span.get("page", 0)), []).append(span)
        return grouped

    @classmethod
    def _resolve_font(cls, family: str, bold: bool, italic: bool) -> str:
        variants = PDF_FONT_FAMILY.get(family, PDF_FONT_FAMILY[cls.DEFAULT_FONT_NAME])
        return variants[(1 if bold else 0) + (2 if italic else 0)]

    def _apply(self, pdf: "fitz.Document", spans: SpanList) -> None:
        if not spans:
            return
        resolved_font = self._resolve_font(self.font_name, self.bold, self.italic)
        grouped = self._group_by_page(spans)

        for page_idx, page_spans in grouped.items():
            if page_idx < 0 or page_idx >= pdf.page_count:
                continue
            page = pdf[page_idx]
            underline_rects: List["fitz.Rect"] = []
            for span in page_spans:
                bbox = span.get("bbox")
                if not bbox or len(bbox) != 4:
                    continue
                rect = fitz.Rect(*bbox)
                repl = span.get("replacement") or ""
                # Derive font size from bbox height so replacement visually
                # matches the redacted text (PyMuPDF default 11pt is too coarse).
                fs = (
                    float(self.font_size)
                    if self.font_size
                    else max(4.0, rect.height * self.font_scale)
                )
                if self.blackout:
                    page.add_redact_annot(rect, text="", fill=(0, 0, 0), fontsize=fs)
                else:
                    page.add_redact_annot(
                        rect,
                        text=repl,
                        fill=None,
                        fontsize=fs,
                        fontname=resolved_font,
                    )
                    if self.underline and repl:
                        underline_rects.append(rect)
            page.apply_redactions()

            # Underline must be drawn after apply_redactions — the sweep
            # wipes strokes inside the bbox along with original glyphs.
            for rect in underline_rects:
                y = rect.y1 - max(0.5, rect.height * 0.05)
                page.draw_line(
                    fitz.Point(rect.x0, y),
                    fitz.Point(rect.x1, y),
                    color=(0, 0, 0),
                    width=max(0.4, rect.height * 0.04),
                )

    # ----------------------------------------------------------------- #
    # endregion Private                                                 #
    # ----------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# endregion Classes                                                           #
# --------------------------------------------------------------------------- #


__all__ = ["PdfConverter", "PDF_FONT_FAMILY", "SpanList", "Source"]
