# Module name: strategies/documents/pdf.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# ----------------------------------------------------------------------------#
# region Import                                                               #
# ----------------------------------------------------------------------------#
from __future__ import annotations
import os
import re
import unicodedata
from abc import abstractmethod
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any, ClassVar, Dict, List, Mapping, Optional
from wattleflow.core import IBlackboard, IRepository, ITarget, IWattleflow
from wattleflow.concrete import DocumentFacade, StrategyCreate, StrategyWrite
from wattleflow.concrete.exception import StrategyException
from wattleflow.enums.event import Event
from wattleflow.enums.filetype import FileType
from wattleflow.documents.file import FileDocument
from wattleflow.concrete.helpers import Attribute
from wattleflow.helpers.converters import PdfConverter
from wattleflow.helpers.digest import FileDigest
from wattleflow.helpers.dtime import CreatedWithin, Now
from wattleflow.helpers.parsers.mail import MailHeader, MailKeys, MailMoment
from wattleflow.helpers.formatters.factory import FormatterFactory
# ----------------------------------------------------------------------------#
# endregion Import                                                            #
# ----------------------------------------------------------------------------#

# ----------------------------------------------------------------------------#
# region Types                                                                #
# ----------------------------------------------------------------------------#
SpanList = List[Dict[str, Any]]
# ----------------------------------------------------------------------------#
# endregion Types                                                             #
# ----------------------------------------------------------------------------#

# ----------------------------------------------------------------------------#
# region Classes                                                              #
# ----------------------------------------------------------------------------#


class PdfArchiveName:
    """Compose the name an archived PDF is written under.
    correspondence  `<sent stamp>-<normalised subject><suffix>`
    anything else   `<creation stamp>-<digest><suffix>`
    """

    STAMP_FORMAT: ClassVar[str] = "%Y-%m-%d-%H%M%S"
    MAX_SUBJECT: ClassVar[int] = 120
    DIGEST_CHARS: ClassVar[int] = 16
    FALLBACK: ClassVar[str] = "without-subject"
    MARKING_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"\[\s*(?:SEC|DLM|ACCESS|CAVEAT)\s*=[^\]]*\]", re.IGNORECASE
    )
    REPLY_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"^(?:\s*(?:re|fw|fwd|aw|sv|vs|antw)\s*(?:\[\d+\])?\s*:)+", re.IGNORECASE
    )
    SEPARATOR_RE: ClassVar[re.Pattern[str]] = re.compile(r"[^0-9A-Za-z]+")
    #: `2026-09-16-101500-2026-09-16-101500-...`.
    STAMPED_RE: ClassVar[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{6}-")

    @classmethod
    def clean(cls, text: Any) -> str:
        """`text` reduced to what a file name may carry."""
        value = cls.MARKING_RE.sub(" ", str(text or ""))
        value = cls.REPLY_RE.sub(" ", value)
        value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        return cls.SEPARATOR_RE.sub("-", value).strip("-")[: cls.MAX_SUBJECT].strip("-")

    @classmethod
    def local_zone(cls) -> str:
        """The machine's own zone as an IANA key, or "" when it cannot be named.

        Not `tzname()`: that yields an abbreviation (`AEST`), and `ZoneInfo`
        rejects it — storing one would put a value in the record that cannot
        convert anything. An empty string is the honest answer, and the
        conversion reads it as local anyway.
        """
        named = os.environ.get("TZ", "").strip()
        if not named:
            try:
                parts = Path("/etc/localtime").resolve().parts
            except OSError:
                return ""
            if "zoneinfo" not in parts:
                return ""
            named = "/".join(parts[parts.index("zoneinfo") + 1 :])
        try:
            ZoneInfo(named)
        except Exception:
            return ""
        return named

    @classmethod
    def stamp(cls, moment: Any, zone: Optional[str]) -> str:
        """`moment` as a file-name stamp, on one declared clock.

        A value without an offset was still written by a clock somewhere, and
        the LOCAL zone is that assumption — never UTC. Left alone the conversion
        reads a naive value as UTC, which turned a page printed `10:15` into
        `20:15`. Anchoring it locally first keeps the default a no-op and makes
        any other zone a declared choice; `mail_date_zone_known` on the document
        records that the page never stated one.
        """
        parsed = MailMoment.parse(moment)
        if not parsed:
            return ""
        value = parsed.value
        if value.tzinfo is None:
            value = value.astimezone()
        return MailMoment.parse(value).in_zone(zone).strftime(cls.STAMP_FORMAT)

    @classmethod
    def sent(cls, metadata: Mapping[str, Any], zone: Optional[str]) -> str:
        """When the message was sent, as the page states it."""
        for key in (MailKeys.DATE_SENT, MailKeys.DATE_SENT_RAW, MailKeys.DATE_RECEIVED):
            stamp = cls.stamp(metadata.get(key), zone)
            if stamp:
                return stamp
        return ""

    @classmethod
    def created(cls, source: Path, zone: Optional[str]) -> str:
        """When the file came into being, by the project's own reading of it."""
        try:
            return cls.stamp(CreatedWithin.created_at(source), zone)
        except OSError:
            return ""

    @classmethod
    def digest(cls, metadata: Mapping[str, Any], source: Path) -> str:
        """The content digest, shortened for a name."""
        stored = str(metadata.get("digest") or "")
        value = stored.split(":", 1)[-1] if stored else FileDigest.of(source)
        return value[: cls.DIGEST_CHARS]

    @classmethod
    def subject(cls, metadata: Mapping[str, Any], source: Path) -> str:
        subject = metadata.get(MailKeys.raw(MailHeader.SUBJECT.value))
        return cls.clean(subject) or cls.clean(cls.STAMPED_RE.sub("", source.stem)) or cls.FALLBACK

    @classmethod
    def compose(
        cls,
        metadata: Mapping[str, Any],
        source: Path,
        zone: Optional[str] = None,
        correspondence: bool = False,
    ) -> str:
        """The stem, without a suffix — the driver adds that."""
        if correspondence:
            stamp = cls.sent(metadata, zone) or cls.created(source, zone)
            return (
                f"{stamp}-{cls.subject(metadata, source)}"
                if stamp
                else cls.subject(metadata, source)
            )
        stamp = cls.created(source, zone)
        label = cls.digest(metadata, source)
        return f"{stamp}-{label}" if stamp else label


class BaseWriteStrategy(StrategyWrite):
    @staticmethod
    def _resolve_driver(caller: IWattleflow, kwargs: Dict[str, Any]):
        repository = kwargs.get("repository") or caller
        driver = kwargs.get("driver") or getattr(repository, "driver", None)
        assert driver is not None, "Driver not available — strategy requires RepositoryWithDriver"
        return driver

    @staticmethod
    def _converter(kwargs: Dict[str, Any]) -> PdfConverter:
        converter_kwargs = kwargs.pop("converter", {}) or {}
        return PdfConverter(**converter_kwargs)

    @abstractmethod
    def execute(self, caller: IWattleflow, facade: ITarget, **kwargs: Any) -> bool: ...


class CreatePdfDocument(StrategyCreate):
    """Describe a PDF; do not read it(`FRQ-PRC-15.22` §8 t.2)."""

    ZONE_KEY: ClassVar[str] = "archive_zone"

    def execute(self, caller: IWattleflow, **kwargs) -> Optional[ITarget]:
        try:
            self.debug(msg=Event.Create.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IBlackboard), "Expected IBlackboard. Found %s" % (
                type(caller).__name__
            )
            Attribute.mandatory(self, "filename", str, **kwargs)

            document = FileDocument(filename=self.filename)

            # metadata
            document.update_metadata("created_by", self.name)
            document.update_metadata("created_at", Now.utc())
            document.update_metadata("caller", caller.name)
            document.update_metadata("filename", self.filename)
            document.update_metadata("source_format", "pdf")
            # The zone is decided once, here, and travels as data. A name built
            # later must not re-decide it: two runs on machines in different
            # zones would otherwise file the same document under two names.
            document.update_metadata(
                self.ZONE_KEY,
                str(kwargs.get("zone") or "").strip() or PdfArchiveName.local_zone(),
            )

            for key, value in kwargs.items():
                if key in (
                    "caller",
                    "filename",
                    "content",
                    "schema",
                    "processor",
                    "blackboard",
                    "zone",
                ):
                    continue
                document.update_metadata(f"kwargs_{key}", value)

            if document.size <= 0:
                self.warning(
                    msg=Event.Create.name,
                    step=Event.Check.name,
                    reason="PDF source is empty or unreadable.",
                    document=document,
                )

            self.debug(
                msg=Event.Create.name,
                step=Event.Completed.name,
                document=document.identifier,
                size=document.size,
            )
            return DocumentFacade(document)
        except AssertionError as e:
            error = f"Assertion: {str(e)}"
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e


class WritePdfArchive(BaseWriteStrategy):
    """Archive the source PDF under a name composed at write time."""

    KIND_KEY: ClassVar[str] = "document_kind"
    CORRESPONDENCE: ClassVar[str] = "correspondence"

    #  (`FRQ-PRC-15.22` §5.2).
    def __init__(self, **kwargs: Any) -> None:
        self._zone: Optional[str] = kwargs.pop("zone", None)
        self._subdir: Optional[str] = kwargs.pop("subdir", None)
        super().__init__(**kwargs)

    def _archive_zone(self, document: FileDocument, kwargs: Dict[str, Any]) -> Optional[str]:
        """The zone this name is built on: per call, per instance, else the one
        the create strategy decided and left on the document."""
        for candidate in (
            kwargs.get("zone"),
            self._zone,
            document.metadata.get(CreatePdfDocument.ZONE_KEY),
        ):
            if candidate:
                return str(candidate)
        return None

    def execute(self, caller: IWattleflow, facade: ITarget, **kwargs: Any) -> bool:
        self.debug(msg=Event.Write.name, step=Event.Started.name, caller=caller)
        try:
            Attribute.evaluate(caller=self, target=caller, expected_type=IRepository)
            Attribute.evaluate(caller=self, target=facade, expected_type=ITarget)
            driver = self._resolve_driver(caller, kwargs)

            document: FileDocument = facade.request()
            source = Path(document.filename)

            if not FileType.accepts(source.suffix, FileType.PDF):
                self.debug(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="non-pdf source, skipped",
                    filename=str(source),
                )
                return False

            if not source.is_file():
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="source missing",
                    filename=str(source),
                )
                return False

            metadata = document.metadata
            correspondence = metadata.get(self.KIND_KEY) == self.CORRESPONDENCE
            stem = PdfArchiveName.compose(
                metadata,
                source,
                zone=self._archive_zone(document, kwargs),
                correspondence=correspondence,
            )

            output = driver.copy(
                source,
                filename=stem,
                suffix=source.suffix,
                subdir=kwargs.get("subdir") or self._subdir,
                mkdir=True,
            )

            document.update_metadata("stored_by", caller.name)
            document.update_metadata("stored_at", document.utc_time_stamp())
            document.update_metadata("output", output)

            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                kind=self.CORRESPONDENCE if correspondence else "document",
                source=str(source),
                output=output,
            )
            return True
        except AssertionError as e:
            error = f"Assertion: {str(e)}"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e


class WritePdfPerPageToFile(BaseWriteStrategy):
    """Split source PDF into one file per page (file01.pdf -> file01-pg-001.pdf).
    If ``redact_spans`` are present on the document metadata, redactions for
    each page are applied to the corresponding single-page output."""

    def execute(self, caller: IWattleflow, facade: ITarget, **kwargs: Any) -> bool:
        self.debug(msg=Event.Write.name, step=Event.Started.name, caller=caller, facade=facade)
        try:
            Attribute.evaluate(caller=self, target=caller, expected_type=IRepository)
            Attribute.evaluate(caller=self, target=facade, expected_type=ITarget)
            driver = self._resolve_driver(caller, kwargs)

            document: FileDocument = facade.request()
            source_path = Path(document.filename)

            if not FileType.accepts(source_path.suffix, FileType.PDF):
                self.debug(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="non-pdf source, skipped",
                )
                return False

            if not source_path.exists():
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="source missing",
                    filename=str(source_path),
                )
                return False

            spans: SpanList = list(document.metadata.get("redact_spans") or [])
            converter = self._converter(kwargs)

            stem = source_path.stem
            written = 0
            written_size = 0
            last_output: Optional[str] = None

            formatter = FormatterFactory.create(FileType.PDF)
            for idx, page_bytes in converter.split_to_pages(source_path, spans):
                filename = f"{stem}-pg-{idx + 1:03d}"
                last_output = driver.write(
                    formatter.render(content=page_bytes),
                    filename=filename,
                    suffix=formatter.SUFFIX,
                )
                written += 1
                written_size = len(page_bytes) if page_bytes else 0

            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                source=str(source_path),
                pages=written,
                output=last_output,
                size=written_size,
            )
            return written > 0
        except AssertionError as e:
            error = f"Assertion: {str(e)}"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e


class WritePdfRedactedToFile(BaseWriteStrategy):
    """Apply PDF redaction spans on the source and write a single redacted PDF."""

    def execute(self, caller: IWattleflow, facade: ITarget, **kwargs: Any) -> bool:
        self.debug(msg=Event.Write.name, step=Event.Started.name, caller=caller, facade=facade)
        try:
            self.debug(msg=Event.Write.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IRepository), "Expected IRepository. Found %s" % type(caller)
            assert isinstance(facade, ITarget), "Expected ITarget. Found %s" % type(facade)

            driver = self._resolve_driver(caller, kwargs)
            document: FileDocument = facade.request()
            filename = document.metadata.get("filename", document.identifier)
            spans: SpanList = list(document.metadata.get("redact_spans") or [])

            if not spans:
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="no redact_spans yet, skipped",
                )
                return False

            converter = self._converter(kwargs)
            payload = converter.apply_redactions(Path(filename), spans)

            formatter = FormatterFactory.create(FileType.PDF)
            output = driver.write(
                formatter.render(content=payload),
                filename=filename.name,
                suffix=formatter.SUFFIX,
            )

            size = len(payload) if payload else 0
            spans = len(spans) if spans else 0

            document.update_metadata("size", size)
            document.update_metadata("spans", spans)
            document.update_metadata("stored_by", caller.name)
            document.update_metadata("stored_at", document.utc_time_stamp())
            document.update_metadata("output", output)

            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                document=document,
                output=output,
                spans=spans,
                size=size,
            )

            return True
        except AssertionError as e:
            error = f"Assertion: {str(e)}"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e


# ----------------------------------------------------------------------------#
# endregion Classes                                                           #
# ----------------------------------------------------------------------------#


__all__ = [
    "CreatePdfDocument",
    "PdfArchiveName",
    "WritePdfArchive",
    "WritePdfPerPageToFile",
    "WritePdfRedactedToFile",
]
