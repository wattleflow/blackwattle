# Module name: helpers/parsers/binary.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
Binary GenericParser subclasses — read-side deserialisers for PDF, pickle,
protobuf and PNG sources. GenericParser resolves the source and owns the reader
(DR-COR-015); third-party dependencies are lazy-imported in ``deserialise``.
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from dataclasses import dataclass
from io import BytesIO
from typing import Any, BinaryIO, Callable, ClassVar
from wattleflow.concrete.serialisation import GenericParser, ParserError
from wattleflow.helpers.image_security import ImageSecurityGuard
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["PdfParser", "PdfText", "PickleParser", "ProtobufParser", "PngParser"]


@dataclass(frozen=True)
class PdfText:
    """Text a PDF yielded, and which backend produced it."""

    pages: tuple[str, ...]
    backend: str


# --------------------------------------------------------------------------- #
# region Parsers                                                              #
# --------------------------------------------------------------------------- #


class PdfParser(GenericParser):
    """Read a PDF stream.

    Returns raw bytes by default; ``extract_text=True`` returns a
    :class:`PdfText` — the pages and the backend that produced them, so the
    caller can record which library actually read the file.

    ``backend`` is ``auto`` (first installed of pymupdf, pypdf, pdfminer) or a
    named one, in which case a missing library is an error rather than a silent
    fallback. Tika is deliberately NOT among them: it needs a server, which is a
    connection's business, not a parser's.
    """

    # PresetGate unions ALLOWED across the MRO; `encoding` comes from the base.
    ALLOWED = ["backend", "password", "preserve_layout"]

    BACKENDS: ClassVar[tuple[str, ...]] = ("auto", "pymupdf", "pypdf", "pdfminer")
    DEFAULT_BACKEND: ClassVar[str] = "auto"
    #: backend -> the module whose presence decides whether it can run
    MODULES: ClassVar[dict[str, str]] = {
        "pymupdf": "fitz",
        "pypdf": "pypdf",
        "pdfminer": "pdfminer.high_level",
    }
    #: pdfminer returns one string with a form feed between pages
    PAGE_BREAK: ClassVar[str] = "\x0c"

    def deserialise(self, reader: BinaryIO, **opts: Any) -> object:
        if not opts.pop("extract_text", False):
            return reader.read()

        requested = str(opts.pop("backend", None) or self.backend or self.DEFAULT_BACKEND)
        if requested not in self.BACKENDS:
            raise ParserError(
                caller=self,
                error=f"backend must be one of {self.BACKENDS}, got {requested!r}",
            )

        password = opts.pop("password", None) or self.password or ""
        layout = opts.pop("preserve_layout", None)
        layout = self.preserve_layout if layout is None else layout

        payload = reader.read()
        name, extract = self._resolve(requested)
        return PdfText(pages=tuple(extract(payload, password, bool(layout))), backend=name)

    # region Backends

    def _resolve(self, requested: str) -> tuple[str, Callable[[bytes, str, bool], list[str]]]:
        """The backend to use, and the callable that runs it."""
        extractors = {
            "pymupdf": self._pymupdf,
            "pypdf": self._pypdf,
            "pdfminer": self._pdfminer,
        }

        if requested != "auto":
            module = self.MODULES[requested]
            try:
                __import__(module)
            except ImportError as e:
                raise ParserError(
                    caller=self,
                    error=f"backend {requested!r} was asked for but {module!r} is not installed",
                ) from e
            return requested, extractors[requested]

        for name in ("pymupdf", "pypdf", "pdfminer"):
            try:
                __import__(self.MODULES[name])
            except ImportError:
                continue
            return name, extractors[name]

        raise ParserError(
            caller=self,
            error="no PDF backend installed; add one of: PyMuPDF, pypdf, pdfminer.six",
        )

    def _pymupdf(self, payload: bytes, password: str, layout: bool) -> list[str]:
        import fitz  # PyMuPDF

        doc = fitz.open(stream=payload, filetype="pdf")
        try:
            if doc.is_encrypted and not doc.authenticate(password):
                raise ParserError(caller=self, error="PDF is password-protected")
            return [page.get_text("text") or "" for page in doc]
        finally:
            doc.close()

    def _pypdf(self, payload: bytes, password: str, layout: bool) -> list[str]:
        import pypdf

        reader = pypdf.PdfReader(BytesIO(payload))
        if reader.is_encrypted and not reader.decrypt(password):
            raise ParserError(caller=self, error="PDF is password-protected")
        return [page.extract_text() or "" for page in reader.pages]

    def _pdfminer(self, payload: bytes, password: str, layout: bool) -> list[str]:
        from pdfminer.high_level import extract_text
        from pdfminer.layout import LAParams

        text = (
            extract_text(
                BytesIO(payload),
                password=password,
                laparams=LAParams() if layout else None,
            )
            or ""
        )
        return text.split(self.PAGE_BREAK) if self.PAGE_BREAK in text else [text]

    # endregion Backends


class PickleParser(GenericParser):
    """Load a pickled object. Pickle execution is unsafe by design; the caller
    must opt in explicitly via ``allow_pickle_load=True``."""

    def deserialise(self, reader: BinaryIO, **opts: Any) -> Any:
        if not opts.pop("allow_pickle_load", False):
            raise PermissionError(
                "PickleParser: pass allow_pickle_load=True to load untrusted pickles"
            )
        import pickle

        return pickle.load(reader)


class ProtobufParser(GenericParser):
    """Decode a length-delimited protobuf stream into a list of dicts."""

    def deserialise(self, reader: BinaryIO, **opts: Any) -> list[dict]:
        from wattleflow.helpers.protobuf import (
            decode_delimited_stream,
            resolve_message_class,
        )

        schema = opts.pop("schema", None)
        message_class = opts.pop("message_class", None)
        message_cls = message_class or resolve_message_class(schema)

        return decode_delimited_stream(reader.read(), message_cls)


class PngParser(GenericParser):
    """Read a PNG stream. Returns a PIL Image by default; pass ``raw_bytes=True``
    to return the original bytes instead, or ``ocr=True`` for an OCR token
    stream."""

    def deserialise(self, reader: BinaryIO, **opts: Any) -> object:
        if opts.pop("raw_bytes", False):
            return reader.read()
        if opts.pop("ocr", False):
            from wattleflow.helpers.parsers.ocr import OcrParser

            return OcrParser().parse(stream=reader, **opts)

        return ImageSecurityGuard.safe_open_bytes(reader.read(), expected=("PNG",))


# --------------------------------------------------------------------------- #
# endregion Parsers                                                           #
# --------------------------------------------------------------------------- #
