# Module name: drivers/pdf.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# One place that reads and writes PDF.
#
# READ  — `PdfParser` runs a local library (pymupdf / pypdf / pdfminer). When the
#         file yields (almost) nothing, it is a scan: the pages carry images, not
#         a text layer, and no local library can help. The driver then asks Apache
#         Tika through a connection, which OCRs server-side. That decision lives
#         here, not in a pipeline — choosing HOW to read is the driver's job.
#
# WRITE — inherited from DriverLocalStorage: a Formatter (in a write strategy)
#         renders the final bytes and the driver only puts them on disk, through
#         the same atomic part-file and path confinement as any other file.
#
# The Tika connection is OPTIONAL. Without `connection_name` the driver reads
# with local libraries only and says so when a scan arrives, instead of failing.
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from pathlib import Path
from typing import Any, ClassVar, Optional, Tuple
from wattleflow.concrete.driver import DriverMetadata
from wattleflow.concrete.exception import DriverException
from wattleflow.enums.event import Event
from wattleflow.enums.filetype import FileType
from wattleflow.drivers.local_storage import DriverLocalStorage
from wattleflow.helpers.parsers.binary import PdfParser, PdfText
from wattleflow.helpers.parsers.tika import TikaParser
from wattleflow.decorators.oscal import oscal_driver
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class DriverPdfError(DriverException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Types                                                                #
# --------------------------------------------------------------------------- #


class PdfRead:
    """What one read produced, and how.

    `backend` names the library that actually did it — `pymupdf`, `pypdf`,
    `pdfminer` or `tika` — so a caller can record provenance instead of guessing
    it. `scanned` says the local backend found no usable text layer. `pages` is
    None when nothing counted them, which is not the same as a document of zero
    pages.
    """

    __slots__ = ("text", "backend", "pages", "scanned")

    def __init__(self, text: str, backend: str, pages: Optional[int], scanned: bool) -> None:
        self.text = text
        self.backend = backend
        self.pages = pages
        self.scanned = scanned

    def __repr__(self) -> str:
        return (
            f"PdfRead[backend={self.backend}, pages={self.pages}, "
            f"chars={len(self.text)}, scanned={self.scanned}]"
        )


# --------------------------------------------------------------------------- #
# endregion Types                                                             #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Drivers                                                              #
# --------------------------------------------------------------------------- #


@oscal_driver(strict=False)
class DriverPdf(DriverLocalStorage):
    """Reads and writes PDF: local libraries first, Apache Tika for scans."""

    ALLOWED = [
        "backend",
        "connection_manager",
        "connection_name",
        "min_chars",
        "page_separator",
        "password",
        "preserve_layout",
        "scan_threshold",
    ]
    # OSCAL: path confinement on read and write (ac-3); the scan path sends the
    # document to a Tika endpoint over HTTP (sc-8).
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ("ac-3", "sc-8")

    DEFAULT_SEPARATOR: ClassVar[str] = "\n\n"
    #: A page shorter than this carries no usable text and is dropped.
    DEFAULT_MIN_CHARS: ClassVar[int] = 1
    #: Whole-document character count below which the file is treated as a scan.
    #: Deliberately small: a page of running text yields hundreds of characters,
    #: while a scan yields a handful of stray glyphs, if any.
    DEFAULT_SCAN_THRESHOLD: ClassVar[int] = 32
    #: Not a PdfParser backend — it names the connection path, not a library.
    TIKA_BACKEND: ClassVar[str] = "tika"

    # ---------------------------------------------------------------------- #
    # region Lifecycle
    # ---------------------------------------------------------------------- #

    def load(self) -> None:
        super().load()

        self._tika: Any = None
        name = self.connection_name
        if name:
            manager = self.connection_manager
            if manager is None:
                raise DriverPdfError(
                    caller=self,
                    error=(
                        f"connection_name is {name!r} but no ConnectionManager was injected; "
                        "declare the connection under managers.connections."
                    ),
                )
            self._tika = manager.get_connection(name)

        self.debug(
            msg=Event.Load.name,
            step=Event.Completed.name,
            component="pdf",
            backend=self.backend or PdfParser.DEFAULT_BACKEND,
            scan_backend=name or None,
            scan_threshold=self._scan_threshold(),
        )

    def metadata(self) -> DriverMetadata:
        return DriverMetadata(
            name=self.__class__.__name__,
            version="1.0",
            protocol="pdf",
            capabilities=["read", "write", "search"],
        )

    # endregion Lifecycle

    # ---------------------------------------------------------------------- #
    # region Settings
    # ---------------------------------------------------------------------- #

    def _separator(self) -> str:
        separator = self.page_separator
        return self.DEFAULT_SEPARATOR if separator is None else str(separator)

    def _min_chars(self) -> int:
        value = self.min_chars
        return self.DEFAULT_MIN_CHARS if value is None else int(value)

    def _scan_threshold(self) -> int:
        value = self.scan_threshold
        return self.DEFAULT_SCAN_THRESHOLD if value is None else int(value)

    def _parser(self, **overrides: Any) -> PdfParser:
        return PdfParser(
            backend=overrides.get("backend", self.backend),
            password=overrides.get("password", self.password),
            preserve_layout=overrides.get("preserve_layout", self.preserve_layout),
            level=self._level,
            handler=self._handler,
        )

    # endregion Settings

    # ---------------------------------------------------------------------- #
    # region Read
    # ---------------------------------------------------------------------- #

    def read(self, uri: str, **kwargs: Any) -> str:
        """The document's text. See :meth:`extract` for the provenance as well."""
        return self.extract(uri, **kwargs).text

    def extract(self, uri: str, **kwargs: Any) -> PdfRead:
        """Text plus which backend produced it and whether the file was a scan."""
        self.debug(msg=Event.Read.name, step=Event.Started.name, uri=uri, kwargs=kwargs)

        path = self._confined(uri)
        if not FileType.accepts(path.suffix, FileType.PDF):
            raise DriverPdfError(caller=self, error=f"not a PDF: {path.name}")
        if not path.is_file():
            raise DriverPdfError(caller=self, error=f"not a readable file: {path}")

        # `backend="tika"` skips the local libraries entirely: the caller already
        # knows this source has no text layer worth trying.
        forced = str(kwargs.get("backend") or "").strip().lower() == self.TIKA_BACKEND
        if forced:
            kwargs.pop("backend", None)
            result = self._scanned(path, PdfRead("", self.TIKA_BACKEND, None, scanned=True))
        else:
            result = self._local(path, **kwargs)
            if len(result.text) < self._scan_threshold():
                result = self._scanned(path, result)

        self._record("read", path.stat().st_size)
        self.debug(
            msg=Event.Read.name,
            step=Event.Completed.name,
            uri=str(path),
            backend=result.backend,
            pages=result.pages,
            chars=len(result.text),
            scanned=result.scanned,
        )
        return result

    def _local(self, path: Path, **kwargs: Any) -> PdfRead:
        """Read with a local library. Never reaches the network."""
        try:
            with open(path, "rb") as stream:
                parsed: PdfText = self._parser(**kwargs).parse(stream=stream, extract_text=True)
        except Exception as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, uri=str(path), error=str(e))
            raise DriverPdfError(caller=self, error=str(e), uri=str(path)) from e

        kept = [page for page in parsed.pages if len(page.strip()) >= self._min_chars()]
        text = self._separator().join(kept).strip()
        return PdfRead(text=text, backend=parsed.backend, pages=len(parsed.pages), scanned=False)

    def _scanned(self, path: Path, local: PdfRead) -> PdfRead:
        """A file with no text layer: ask Tika, which OCRs it server-side.

        Without a configured connection this reports and returns what the local
        backend found. An empty result is a fact about the document, not a
        failure of the driver, and the caller decides what it means.
        """
        if self._tika is None:
            self.warning(
                msg=Event.Read.name,
                step=Event.Check.name,
                reason="no text layer and no Tika connection configured",
                uri=str(path),
                chars=len(local.text),
            )
            return PdfRead(local.text, local.backend, local.pages, scanned=True)

        try:
            with self._tika.connect() as client:
                with open(path, "rb") as stream:
                    text = TikaParser(
                        client=client,
                        level=self._level,
                        handler=self._handler,
                    ).parse(stream=stream)
        except Exception as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, uri=str(path), error=str(e))
            raise DriverPdfError(caller=self, error=str(e), uri=str(path)) from e

        self.debug(
            msg=Event.Read.name,
            step=Event.Check.name,
            reason="no text layer; read through Tika",
            uri=str(path),
            local_backend=local.backend,
            local_chars=len(local.text),
            chars=len(text),
        )
        return PdfRead(text=text, backend="tika", pages=local.pages, scanned=True)

    # endregion Read

    # ---------------------------------------------------------------------- #
    # region Write
    # ---------------------------------------------------------------------- #
    # `write` / `save_bytes` / `copy` / `open_target` / `search` are inherited
    # unchanged: a PDF payload is bytes like any other, and the atomic part-file,
    # the path confinement and the activity tally already apply to it. What is
    # added here is only the refusal to write something that is not a PDF.
    # ---------------------------------------------------------------------- #

    def write(self, content: Any, **kwargs: Any) -> str:
        suffix = kwargs.get("suffix") or FileType.PDF.value
        # A PDF payload is bytes a Formatter produced; text or a stream here means
        # the caller skipped the formatter, which is a mistake worth naming.
        if not isinstance(content, (bytes, bytearray, memoryview)):
            raise DriverPdfError(
                caller=self,
                error=(
                    f"{type(self).__name__} writes PDF bytes; got "
                    f"{type(content).__name__}. Render it with PdfFormatter first."
                ),
            )
        if not FileType.accepts(str(suffix), FileType.PDF):
            raise DriverPdfError(
                caller=self,
                error=f"{type(self).__name__} writes PDF only; got suffix {suffix!r}",
            )
        kwargs["suffix"] = suffix
        return super().write(content, **kwargs)

    # endregion Write

    def __repr__(self) -> str:
        connection: Optional[str] = self.connection_name
        return f"{self.name}[backend={self.backend or 'auto'}, tika={connection or 'none'}]"


# --------------------------------------------------------------------------- #
# endregion Drivers                                                           #
# --------------------------------------------------------------------------- #


__all__ = ["DriverPdf", "DriverPdfError", "PdfRead"]
