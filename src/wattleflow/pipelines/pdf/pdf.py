# Module name: pipelines/pdf/pdf.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional
from wattleflow.core import IProcessor, ITarget
from wattleflow.concrete import GenericPipeline
from wattleflow.concrete.exception import PipelineException
from wattleflow.enums.event import Event
from wattleflow.enums.filetype import FileType
from wattleflow.documents.file import FileDocument
from wattleflow.concrete.helpers import Attribute
from wattleflow.drivers.pdf import DriverPdf, PdfRead
from wattleflow.helpers.parsers.binary import PdfParser, PdfText
from wattleflow.helpers.parsers.mail import MailHeaderBlock

try:
    import fitz  # PyMuPDF # noqa: F401
except ImportError as e:
    raise ModuleNotFoundError(
        f"Missing required package to run this code: {__file__}.\n"
        "Please install it using:\n\tpip install PyMuPDF"
    ) from e

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Types                                                              #
# --------------------------------------------------------------------------- #
# `.pdf` is FileType's to name; this module does not keep a second copy.
Patterns = List[Dict[str, str]]
# --------------------------------------------------------------------------- #
# endregion Types                                                             #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Pipelines                                                            #
# --------------------------------------------------------------------------- #


class PipelinePDFExtractText(GenericPipeline):
    """Put a PDF's text on the document.

    The pipeline owns the transformation, not the reading: HOW a PDF is read —
    which local library, and whether a page-image needs Tika — is `DriverPdf`'s
    decision, and `PdfParser` is the fallback when no such driver is configured.
    The four extractor methods and the backend selection that used to live here
    were a second copy of both.
    """

    ALLOWED = [
        "backend",
        "templates",
        "min_chars",
        "overwrite",
        "page_separator",
        "password",
        "preserve_layout",
    ]

    DEFAULT_PAGE_SEPARATOR = "\n\n"
    DEFAULT_MIN_CHARS = 1
    #: `tika` is not a PdfParser backend; it names the driver's connection path.
    SUPPORTED_BACKENDS = PdfParser.BACKENDS + (DriverPdf.TIKA_BACKEND,)

    #: Metadata key naming what the text is, and its two values.
    KIND_KEY = "document_kind"
    MAIL = "correspondence"
    DOCUMENT = "document"

    def __init__(self, **kwargs: Any) -> None:
        backend = kwargs.pop("backend", PdfParser.DEFAULT_BACKEND)
        super().__init__(
            backend=backend,
            page_separator=kwargs.pop("page_separator", self.DEFAULT_PAGE_SEPARATOR),
            preserve_layout=bool(kwargs.pop("preserve_layout", False)),
            password=kwargs.pop("password", None),
            min_chars=int(kwargs.pop("min_chars", self.DEFAULT_MIN_CHARS)),
            **kwargs,
        )

        # Validated AFTER the base constructor: raising before it leaves an
        # object whose `__del__` then fails on the preset it never got.
        if backend not in self.SUPPORTED_BACKENDS:
            raise PipelineException(
                caller=self,
                error=f"Unsupported backend {backend!r}. Expected one of {self.SUPPORTED_BACKENDS}",
            )

    # region Extraction

    def _extract(self, processor: IProcessor, path: Path) -> PdfRead:
        """Text for ``path``, through the driver when the processor carries one.

        With a `DriverPdf` the scan path is available: a PDF whose pages carry
        images instead of a text layer goes to Tika. Without one, only the local
        libraries are reachable, and asking for `tika` is a configuration error
        rather than something to fail on silently.
        """
        driver = getattr(processor, "driver", None)
        if isinstance(driver, DriverPdf):
            return driver.extract(str(path), backend=self.backend)

        if self.backend == DriverPdf.TIKA_BACKEND:
            raise PipelineException(
                caller=self,
                error=(
                    "backend 'tika' needs a DriverPdf on the processor "
                    "(configuration.driver); it reaches Tika through a connection."
                ),
            )

        parsed: PdfText = PdfParser(
            backend=self.backend,
            password=self.password,
            preserve_layout=self.preserve_layout,
            level=self._level,
            handler=self._handler,
        ).parse(path=path, extract_text=True)

        kept = [page for page in parsed.pages if len(page.strip()) >= self.min_chars]
        text = self.page_separator.join(kept).strip()
        return PdfRead(
            text=text,
            backend=parsed.backend,
            pages=len(parsed.pages),
            scanned=not text,
        )

    # endregion Extraction

    # region Classification

    def _classify(self, document: FileDocument, text: str) -> None:
        """Record what the extracted text IS, not only that it was extracted.

        A printed email and a document are both `application/pdf`; the format
        does not separate them, the header block at the top does. The finding
        rides with the extraction because it costs ~1.7% of one (measured) and
        needs exactly the text the extraction just produced — a second pipeline
        would re-derive nothing and could be ordered wrongly.

        Detection itself is not implemented here: it belongs to the mail
        vocabulary that owns header blocks (`MailHeaderBlock`), which knows
        nothing about PDF and works on text from any source.
        """
        block = MailHeaderBlock.detect(text, self.templates or None)
        document.update_metadata(self.KIND_KEY, self.MAIL if block else self.DOCUMENT)
        if block is None:
            return
        for key, value in block.as_metadata().items():
            document.update_metadata(key, value)

    # endregion Classification

    # region Public

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> None:
        document: FileDocument = facade.request()
        Attribute.evaluate(caller=self, target=document, expected_type=FileDocument)

        filename: str = document.filename
        if not filename:
            self.warning(
                msg=Event.Transform.name,
                step=Event.Check.name,
                error="FileDocument has no filename!",
            )
            return

        path = Path(filename)
        if not path.exists():
            self.warning(
                msg=Event.Transform.name,
                step=Event.Check.name,
                error="File does not exist",
                filename=filename,
            )
            return

        # Another pipeline may already have put the text there; extracting a
        # second time would cost a full read and overwrite its work. The
        # CLASSIFICATION still runs on that text — it costs ~1.7% of an
        # extraction and the source of the text does not change what it is.
        existing: Optional[str] = document.content or ""
        if existing.strip() and not self.overwrite:
            self.debug(
                msg=Event.Transform.name,
                step=Event.Check.name,
                reason="document already carries content",
                filename=filename,
                chars=len(existing),
            )
            self._classify(document, existing)
            processor.blackboard.write(facade=facade, processor=processor, pipeline=self)
            return

        self.debug(
            msg=Event.Transform.name,
            step=Event.Started.name,
            backend=self.backend,
            filename=filename,
        )

        try:
            result = self._extract(processor, path)
        except PipelineException:
            raise
        except Exception as e:
            self.debug(msg=Event.Transform.name, step=Event.Failed.name, error=str(e))
            raise PipelineException(
                caller=self,
                error=f"Extraction failed for {filename}: {e}",
            ) from e

        if result.scanned and not result.text:
            self.warning(
                msg=Event.Transform.name,
                step=Event.Check.name,
                reason="no text layer and nothing recovered",
                filename=filename,
                backend=result.backend,
            )

        document.update_content(result.text)
        document.update_metadata("pdf_backend", result.backend)
        document.update_metadata("pdf_pages", result.pages)
        document.update_metadata("pdf_scanned", result.scanned)
        document.update_metadata("extracted_chars", len(result.text))
        self._classify(document, result.text)

        uid = processor.blackboard.write(
            facade=facade,
            processor=processor,
            pipeline=self,
        )

        self.debug(
            msg=Event.Transform.name,
            step=Event.Completed.name,
            backend=result.backend,
            uid=uid,
            pages=result.pages,
            chars=len(result.text),
            scanned=result.scanned,
        )

    # endregion Public


class PipelinePDFRedact(GenericPipeline):
    def locate_spans(
        self,
        source_path: Path,
        targets: Patterns,
    ) -> Patterns:
        spans: Patterns = []
        seen: set = set()
        pdf = fitz.open(source_path)
        try:
            for page_idx in range(pdf.page_count):
                page = pdf[page_idx]
                for item in targets:
                    text = (item.get("text") or "").strip()
                    if not text:
                        continue
                    repl = item.get("replacement", "") or ""
                    variants = {text, text.lower(), text.upper(), text.title()}
                    for variant in variants:
                        rects = page.search_for(variant) or []
                        for rect in rects:
                            key = (
                                page_idx,
                                round(rect.x0, 2),
                                round(rect.y0, 2),
                                round(rect.x1, 2),
                                round(rect.y1, 2),
                            )
                            if key in seen:
                                continue
                            seen.add(key)
                            spans.append(
                                {
                                    "page": page_idx,
                                    "bbox": (rect.x0, rect.y0, rect.x1, rect.y1),
                                    "replacement": repl,
                                    "text": text,
                                }
                            )
        finally:
            pdf.close()

        return spans

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> Any:
        document: FileDocument = facade.request()
        source_path = Path(document.filename)
        suffix = source_path.suffix.lower()

        if not FileType.accepts(suffix, FileType.PDF):
            self.warning(
                msg=Event.Transform.name,
                step=Event.Check.name,
                reason="unsupported source suffix",
                suffix=suffix,
            )
            return

        pii_hits = list(document.metadata.get("pii_hits") or [])
        entity_targets = list(document.metadata.get("entity_targets") or [])

        targets: Patterns = []
        seen_texts: set = set()
        for item in pii_hits + entity_targets:
            text = (item.get("text") or "").strip()
            if not text or text in seen_texts:
                continue
            seen_texts.add(text)
            targets.append(item)

        if not targets:
            self.warning(
                msg=Event.Transform.name, step=Event.Check.name, reason="no PII targets collected"
            )
            return

        try:
            spans = self.locate_spans(source_path, targets)
        except Exception as e:
            self.error(
                msg=Event.Transform.name, step=Event.Failed.name, error=f"PDF search failed: {e}"
            )
            return

        document.update_metadata("redact_spans", spans)

        return processor.blackboard.write(
            facade=facade,
            processor=processor,
            pipeline=self,
        )


# --------------------------------------------------------------------------- #
# endregion Pipelines                                                         #
# --------------------------------------------------------------------------- #
