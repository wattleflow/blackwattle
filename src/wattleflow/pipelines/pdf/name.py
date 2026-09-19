# Module name: pipelines/pdf/name.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

"""
Descriptive name for a PDF — `FRQ-PDF-01`, `DR-PRC-009` (v0.0.4).

    <PREFIX>-<date>-<slug>-<N>pp        a document with readable text
    SCAN-<stem>-<N>pp                   a scan with no readable text at all

The pipeline composes the stem deterministically from the document's text and
Info dictionary and puts it on the document as `archive_name`; the write strategy
that copies the PDF uses it (`WritePdfArchive`). Nothing here touches the disk.
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import re
import unicodedata
from pathlib import Path
from typing import Any, ClassVar
from wattleflow.core import IProcessor, ITarget
from wattleflow.concrete import GenericPipeline
from wattleflow.concrete.exception import PipelineException
from wattleflow.concrete.helpers import Attribute
from wattleflow.documents.file import FileDocument
from wattleflow.drivers.pdf import DriverPdf, PdfRead
from wattleflow.enums.event import Event
from wattleflow.helpers.parsers.binary import PdfInfo, PdfParser
from wattleflow.pipelines.pdf.pdf import PdfTextReader
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["PdfDescriptiveName", "PipelinePDFName"]

# --------------------------------------------------------------------------- #
# region Rules                                                                #
# --------------------------------------------------------------------------- #


class PdfDescriptiveName:
    """The naming rules of `FRQ-PDF-01` §7, as one deterministic function of the inputs."""

    DEFAULT_PREFIX: ClassVar[str] = "RESOURCE"
    SCAN_PREFIX: ClassVar[str] = "SCAN"
    FALLBACK_SLUG: ClassVar[str] = "without-title"
    DEFAULT_SLUG_LEN: ClassVar[int] = 70
    MIN_SLUG_LEN: ClassVar[int] = 8
    MIN_TITLE: ClassVar[int] = 8  # a shorter `Title` is a code, not a title
    MIN_LINE: ClassVar[int] = 12
    DATE_WINDOW: ClassVar[int] = 600  # characters of page one searched for a year
    #: The archive's own hash name: `YYYY-MM-DD-HHMMSS-<16 hex>`.
    HASHED: ClassVar[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{6}-[0-9a-f]{16}$", re.I)
    STOP_LINE: ClassVar[re.Pattern[str]] = re.compile(
        r"^(page \d+ of \d+|contents|table of contents|official[: ].*)$", re.I
    )
    NUMERIC_LINE: ClassVar[re.Pattern[str]] = re.compile(r"[\d\s.\-–]+")
    YEAR: ClassVar[re.Pattern[str]] = re.compile(r"\b(199\d|20\d\d)\b")

    # region Parts

    @classmethod
    def is_hashed(cls, stem: str) -> bool:
        return bool(cls.HASHED.match(stem))

    @classmethod
    def slug(cls, text: str, max_len: int) -> str:
        """ASCII `[a-z0-9-]`, cut at a word boundary — BR-06."""
        value = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
        value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
        if len(value) <= max_len:
            return value
        cut = value[:max_len]
        if value[max_len] == "-" or "-" not in cut:
            return cut
        return cut[: cut.rfind("-")]

    @classmethod
    def date(cls, created: str | None, first_page: str, full: bool) -> str:
        """`CreationDate` first, else the first year on page one, else "" — BR-04."""
        if created:
            return created[:10] if full else created[:4]
        match = cls.YEAR.search(first_page[: cls.DATE_WINDOW])
        return match.group(1) if match else ""

    @classmethod
    def first_line(cls, text: str) -> str:
        """The first line that reads like a title — BR-05."""
        for line in (raw.strip() for raw in text.splitlines()):
            if len(line) < cls.MIN_LINE or cls.STOP_LINE.match(line):
                continue
            if cls.NUMERIC_LINE.fullmatch(line):
                continue
            return line
        return " ".join(text.split())[:120]

    @classmethod
    def subject(cls, title: str | None, first_page: str) -> tuple[str, str]:
        """(text, source) — `title` when it is one, else the first title-like line."""
        if title and len(title) > cls.MIN_TITLE:
            return title, "title"
        return cls.first_line(first_page), "first-line"

    # endregion Parts

    @classmethod
    def compose(
        cls,
        stem: str,
        text: str,
        info: PdfInfo | None,
        pages: int | None,
        prefix: str = DEFAULT_PREFIX,
        slug_len: int = DEFAULT_SLUG_LEN,
        full_date: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        """The new stem and the evidence for it (`name_*` fields) — BR-04…BR-08."""
        count = pages if pages is not None else (info.pages if info else None)
        suffix = f"{count}pp" if count is not None else None
        evidence: dict[str, Any] = {
            "name_prefix": prefix,
            "name_pages": count,
            "pdf_title": info.title if info else None,
            "pdf_created": info.created if info else None,
        }
        if not text.strip():
            parts = [cls.SCAN_PREFIX, stem] + ([suffix] if suffix else [])
            return "-".join(parts), {**evidence, "name_source": "scan", "name_date": ""}

        first_page = text.split("\f", 1)[0]
        date = cls.date(info.created if info else None, first_page, full_date)
        subject, source = cls.subject(info.title if info else None, first_page)
        parts = [prefix]
        if date:
            parts.append(date)
        parts.append(cls.slug(subject, slug_len) or cls.FALLBACK_SLUG)
        if suffix:
            parts.append(suffix)
        return "-".join(parts), {**evidence, "name_source": source, "name_date": date}


# --------------------------------------------------------------------------- #
# endregion Rules                                                             #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Pipeline                                                             #
# --------------------------------------------------------------------------- #


class PipelinePDFName(GenericPipeline):
    """Put a descriptive `archive_name` on a PDF document.

    Reads the text the way `PipelinePDFExtractText` does (driver with Tika for a
    scan, else the local parser) and the Info dictionary through the parser,
    then applies `PdfDescriptiveName`. Content already on the document is reused,
    never re-extracted.
    """

    ALLOWED = ["prefix", "slug_len", "full_date", "only_hashed", "backend", "password",
               "preserve_layout", "min_chars", "page_separator"]

    #: Metadata this pipeline reads from and writes to.
    NAME_KEY: ClassVar[str] = "archive_name"
    KIND_KEY: ClassVar[str] = "document_kind"
    CORRESPONDENCE: ClassVar[str] = "correspondence"

    def __init__(self, **kwargs: Any) -> None:
        prefix = str(kwargs.pop("prefix", None) or PdfDescriptiveName.DEFAULT_PREFIX).strip()
        slug_len = int(kwargs.pop("slug_len", None) or PdfDescriptiveName.DEFAULT_SLUG_LEN)
        super().__init__(
            prefix=prefix,
            slug_len=slug_len,
            full_date=bool(kwargs.pop("full_date", False)),
            only_hashed=bool(kwargs.pop("only_hashed", True)),
            backend=kwargs.pop("backend", PdfParser.DEFAULT_BACKEND),
            password=kwargs.pop("password", None),
            preserve_layout=bool(kwargs.pop("preserve_layout", False)),
            min_chars=int(kwargs.pop("min_chars", 1)),
            page_separator=kwargs.pop("page_separator", "\n\n"),
            **kwargs,
        )
        # After the base constructor, so a refused preset does not break `__del__`.
        if not prefix or slug_len < PdfDescriptiveName.MIN_SLUG_LEN:
            raise PipelineException(
                caller=self,
                error=f"prefix must be non-empty and slug_len >= {PdfDescriptiveName.MIN_SLUG_LEN}",
            )
        supported = PdfParser.BACKENDS + (DriverPdf.TIKA_BACKEND,)
        if self.backend not in supported:
            raise PipelineException(
                caller=self, error=f"Unsupported backend {self.backend!r}. Expected one of {supported}"
            )

    # region Private

    def _info(self, path: Path) -> PdfInfo | None:
        """Info dictionary and page count; None when no local backend can read the file."""
        try:
            with open(path, "rb") as stream:
                return PdfParser(
                    backend=self.backend if self.backend != DriverPdf.TIKA_BACKEND else None,
                    password=self.password,
                    level=self._level,
                    handler=self._handler,
                ).parse(stream=stream, info=True)
        except Exception as e:
            self.debug(msg=Event.Read, step=Event.Check, reason="no Info dictionary", error=str(e))
            return None

    def _skip(self, processor: IProcessor, facade: ITarget, document: FileDocument, why: str) -> None:
        document.update_metadata("name_source", why)
        self.debug(msg=Event.Transform, step=Event.Completed, reason=why, named=False)
        processor.blackboard.write(facade=facade, processor=processor, pipeline=self)

    # endregion Private

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> None:
        document: FileDocument = facade.request()
        Attribute.evaluate(caller=self, target=document, expected_type=FileDocument)

        path = Path(str(document.filename or ""))
        if not document.filename or not path.is_file():
            self.warning(msg=Event.Transform, step=Event.Check, error="File does not exist",
                         filename=str(path))
            return

        self.debug(msg=Event.Transform, step=Event.Started, filename=path.name)

        if self.only_hashed and not PdfDescriptiveName.is_hashed(path.stem):
            return self._skip(processor, facade, document, "kept")
        if document.metadata.get(self.KIND_KEY) == self.CORRESPONDENCE:
            return self._skip(processor, facade, document, self.CORRESPONDENCE)

        try:
            existing = document.content or ""
            if existing.strip():
                read = PdfRead(existing, "document", None, scanned=False)
            else:
                read = PdfTextReader.read(self, processor, path)
        except PipelineException:
            raise
        except Exception as e:
            # A file that cannot be read is a finding about the SOURCE (FRQ-PDF-01 §6):
            # the document keeps its name and the pass goes on.
            self.warning(msg=Event.Transform, step=Event.Check, reason="unreadable PDF; not named",
                         filename=path.name, error=str(e))
            return self._skip(processor, facade, document, "unreadable")
        info = self._info(path)

        stem, evidence = PdfDescriptiveName.compose(
            path.stem, read.text, info, read.pages,
            prefix=self.prefix, slug_len=self.slug_len, full_date=self.full_date,
        )
        document.update_metadata(self.NAME_KEY, stem)
        document.update_metadata("name_ocr", read.backend == DriverPdf.TIKA_BACKEND)
        for key, value in evidence.items():
            document.update_metadata(key, value)

        uid = processor.blackboard.write(facade=facade, processor=processor, pipeline=self)
        self.debug(
            msg=Event.Transform,
            step=Event.Completed,
            uid=uid,
            archive_name=stem,
            source=evidence["name_source"],
            pages=evidence["name_pages"],
        )


# --------------------------------------------------------------------------- #
# endregion Pipeline                                                          #
# --------------------------------------------------------------------------- #
