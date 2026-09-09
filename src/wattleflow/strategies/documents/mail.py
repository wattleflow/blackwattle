# Module name: strategies/documents/mail.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# ----------------------------------------------------------------------------#
# region Import                                                               #
# ----------------------------------------------------------------------------#
from __future__ import annotations
import re
import unicodedata
from pathlib import Path
from typing import Any, Optional
from wattleflow.core import IBlackboard, IRepository, ITarget, IWattleflow
from wattleflow.concrete import DocumentFacade, StrategyCreate, StrategyWrite
from wattleflow.concrete.exception import DriverException, StrategyException
from wattleflow.enums.event import Event
from wattleflow.enums.filetype import FileType
from wattleflow.documents.file import FileDocument
from wattleflow.concrete.helpers import Attribute
from wattleflow.helpers.dtime import Now
from wattleflow.helpers.formatters.factory import FormatterFactory
from wattleflow.helpers.parsers.mail import (
    AttachmentPolicy,
    MailHeader,
    MailKeys,
    MailMessage,
    MailMoment,
    MailParser,
)
# ----------------------------------------------------------------------------#
# endregion Import                                                            #
# ----------------------------------------------------------------------------#

# ----------------------------------------------------------------------------#
# region Module constants                                                     #
# ----------------------------------------------------------------------------#
# Keys the create strategy owns itself — a kwarg of the same name is wiring,
# not provenance, and must not shadow what is stamped below.
RESERVED_KWARGS = (
    "caller",
    "filename",
    "content",
    "schema",
    "processor",
    "blackboard",
    "zone",
)
# ----------------------------------------------------------------------------#
# endregion Module constants                                                  #
# ----------------------------------------------------------------------------#


# ----------------------------------------------------------------------------#
# region Classes                                                              #
# ----------------------------------------------------------------------------#
class CreateEmailDocument(StrategyCreate):
    __slot__ = ["_reader"]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._reader = MailParser()

    def execute(self, caller: IWattleflow, *args, **kwargs) -> Optional[ITarget]:
        try:
            self.debug(msg=Event.Create.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IBlackboard), "Expected IBlackboard. Found %s" % type(caller)

            Attribute.mandatory(self, "filename", str, **kwargs)

            document = FileDocument(filename=self.filename)
            document.update_metadata("created_by", self.name)
            document.update_metadata("created_at", Now.utc())
            document.update_metadata("caller", caller.name)
            document.update_metadata("filename", self.filename)
            document.update_metadata("source_format", "mail")

            for key, value in kwargs.items():
                if key not in RESERVED_KWARGS:
                    document.update_metadata(f"kwargs_{key}", value)

            message: MailMessage = self._reader.parse(path=Path(self.filename))

            for key, value in message.as_metadata(with_payload=False).items():
                document.update_metadata(key, value)

            if not document.size > 0:
                self.warning(
                    msg=Event.Create.name,
                    step=Event.Check.name,
                    reason="Document file's feeling a bit empty today!",
                    document=document,
                )

            self.debug(
                msg=Event.Create.name,
                step=Event.Completed.name,
                document=document,
                filename=self.filename,
                digest=message.digest,
                attachments=len(message.attachments),
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


class WriteEmailCopyOLD(StrategyWrite):
    """Archive email under a name composed here.
    `<sent date in the local zone>-<normalised subject><suffix>`."""

    MAX_SUBJECT = 120
    STAMP_FORMAT: str = "%Y-%m-%d-%H%M%S"
    FALLBACK: str = "without-subject"
    MARKING_RE = re.compile(r"\[\s*(?:SEC|DLM|ACCESS|CAVEAT)\s*=[^\]]*\]", re.IGNORECASE)
    REPLY_RE = re.compile(r"^(?:\s*(?:re|fw|fwd|aw|sv|vs|antw)\s*(?:\[\d+\])?\s*:)+", re.IGNORECASE)
    SEPARATOR_RE = re.compile(r"[^0-9A-Za-z]+")

    def _sent(self, document: FileDocument) -> str:
        zone = str(document.metadata.get("archive_zone") or "") or None
        for key in (MailKeys.DATE_SENT_RAW, MailKeys.DATE_SENT, MailKeys.DATE_RECEIVED):
            moment = MailMoment.parse(document.metadata.get(key))
            if moment:
                return moment.in_zone(zone).strftime(self.STAMP_FORMAT)
        return ""

    def _clean(self, text: Any) -> str:
        value = self.MARKING_RE.sub(" ", str(text or ""))
        value = self.REPLY_RE.sub(" ", value)
        value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        return self.SEPARATOR_RE.sub("-", value).strip("-")[: self.MAX_SUBJECT].strip("-")

    def _subject(self, document: FileDocument, source: Path) -> str:
        subject = document.metadata.get(MailKeys.raw(MailHeader.SUBJECT.value))
        return self._clean(subject) or self._clean(source.stem) or self.FALLBACK

    def output_name(self, document: FileDocument, source: Path) -> str:
        stamp = self._sent(document)
        subject = self._subject(document, source)
        return f"{stamp}-{subject}" if stamp else subject

    def execute(self, caller: IWattleflow, facade: ITarget, **kwargs: Any) -> bool:
        self.debug(msg=Event.Write.name, step=Event.Started.name, caller=caller)
        try:
            assert isinstance(caller, IRepository), "Expected IRepository. Found %s" % type(caller)
            assert isinstance(facade, ITarget), "Expected ITarget. Found %s" % type(facade)

            driver = kwargs.get("driver") or getattr(caller, "driver", None)
            assert driver is not None, (
                "Driver not available — strategy requires RepositoryWithDriver"
            )

            document: FileDocument = facade.request()
            source = Path(document.filename)
            document.update_metadata("strategy", self.name)

            if not source.is_file():
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="source message missing",
                    filename=str(source),
                )
                return False

            stem = self.output_name(document, source)
            output = driver.copy(source, filename=stem, suffix=source.suffix, mkdir=True)

            if Path(output).resolve() == source.resolve():
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="write_path resolves onto the source — nothing copied",
                    filename=str(source),
                    output=output,
                )
                return False

            document.update_metadata("storage_filename", output)
            self.info(
                msg=Event.Write.name,
                step=Event.Completed.name,
                stem=stem,
                strategija=self.name,
                output=str(output),
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


class WriteEmailWithAttachmentOLD(WriteEmailCopyOLD):
    __slots__ = ("_reader",)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._reader = MailParser()

    @staticmethod
    def _unique(name: str, taken: set[str]) -> str:
        # Two attachments may arrive under one name; the second must not
        # overwrite the first, and renaming both would lose the sender's naming.
        safe = Path(Path(name).name)
        stem, suffix = safe.stem or "attachment", safe.suffix or ".bin"
        candidate = f"{stem}{suffix}"
        counter = 1
        while candidate.lower() in taken:
            counter += 1
            candidate = f"{stem}-{counter}{suffix}"
        taken.add(candidate.lower())
        return candidate

    def _write_attachments(
        self, driver: Any, document: FileDocument, source: Path, stem: str
    ) -> list[str]:
        records = list(document.metadata.get(MailKeys.ATTACHMENTS) or [])
        written: list[str] = []
        taken: set[str] = set()

        for index, record in enumerate(records):
            name = self._unique(str(record.get("name") or f"attachment-{index + 1}"), taken)
            try:
                attachment = self._reader.extract(
                    index,
                    expected=str(record.get("digest") or ""),
                    path=source,
                )
            except (IndexError, ValueError) as e:
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="attachment not written",
                    attachment=name,
                    error=str(e),
                )
                continue

            output = driver.write(
                attachment.payload,
                filename=Path(name).stem,
                suffix=Path(name).suffix,
                subdir=stem,
                mkdir=True,
            )
            written.append(str(output))
            self.info(
                msg=Event.Write.name,
                step=Event.Completed.name,
                # scope="item",
                attachment=name,
                digest=attachment.digest,
                size=attachment.size,
                output=str(output),
            )

        return written

    def execute(self, caller: IWattleflow, facade: ITarget, **kwargs: Any) -> bool:
        ### TRICK with parent class
        if not super().execute(caller, facade, **kwargs):
            self.warning(
                msg=Event.Execute.name,
                step=Event.Completed.name,
                reason="parent strategy did not complete",
            )
            return False
        try:
            document: FileDocument = facade.request()
            if not document.metadata.get(MailKeys.HAS_ATTACHMENTS):
                return True

            driver = kwargs.get("driver") or getattr(caller, "driver", None)
            source = Path(document.filename)
            stem = self.output_name(document, source)

            written = self._write_attachments(driver, document, source, stem)
            document.update_metadata("storage_attachments", written)

            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                stem=stem,
                attachments=document.metadata.get(MailKeys.ATTACHMENT_COUNT),
                written=len(written),
            )
            return True
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        finally:
            # The bundle is complete, so the memo has no next reader — holding it
            # would keep one whole message alive until the next message arrives.
            self._reader.release()


class WriteEmailCopy(StrategyWrite):
    """Archive the message itself under a name composed here:
    `<sent date in the local zone>-<normalised subject><suffix>`.

    First of a pair. It copies and nothing else, and stamps `output_filename` —
    the path the driver returned — so the attachment strategy in the second
    repository names its directory after THIS copy rather than recomputing a
    name that could disagree with it.
    """

    MAX_SUBJECT = 120
    STAMP_FORMAT: str = "%Y-%m-%d-%H%M%S"
    FALLBACK: str = "without-subject"
    MARKING_RE = re.compile(r"\[\s*(?:SEC|DLM|ACCESS|CAVEAT)\s*=[^\]]*\]", re.IGNORECASE)
    REPLY_RE = re.compile(r"^(?:\s*(?:re|fw|fwd|aw|sv|vs|antw)\s*(?:\[\d+\])?\s*:)+", re.IGNORECASE)
    SEPARATOR_RE = re.compile(r"[^0-9A-Za-z]+")
    # A source directory routinely holds this workflow's own earlier output. A
    # message with no subject falls back to the file stem, so without this the
    # stamp is prepended again on every run: `2023-01-25-120511-2023-01-25-…`.
    STAMPED_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{6}-")

    def _sent(self, document: FileDocument) -> str:
        zone = str(document.metadata.get("archive_zone") or "") or None
        for key in (MailKeys.DATE_SENT_RAW, MailKeys.DATE_SENT, MailKeys.DATE_RECEIVED):
            moment = MailMoment.parse(document.metadata.get(key))
            if moment:
                return moment.in_zone(zone).strftime(self.STAMP_FORMAT)
        return ""

    def _clean(self, text: Any) -> str:
        value = self.MARKING_RE.sub(" ", str(text or ""))
        value = self.REPLY_RE.sub(" ", value)
        value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        return self.SEPARATOR_RE.sub("-", value).strip("-")[: self.MAX_SUBJECT].strip("-")

    def _subject(self, document: FileDocument, source: Path) -> str:
        subject = document.metadata.get(MailKeys.raw(MailHeader.SUBJECT.value))
        return (
            self._clean(subject)
            or self._clean(self.STAMPED_RE.sub("", source.stem))
            or self.FALLBACK
        )

    def output_name(self, document: FileDocument, source: Path) -> str:
        stamp = self._sent(document)
        subject = self._subject(document, source)
        return f"{stamp}-{subject}" if stamp else subject

    def execute(self, caller: IWattleflow, facade: ITarget, **kwargs: Any) -> bool:
        try:
            self.debug(msg=Event.Write.name, step=Event.Started.name, caller=caller)
            Attribute.evaluate(caller=self, target=caller, expected_type=IRepository)
            Attribute.evaluate(caller=self, target=facade, expected_type=ITarget)

            driver = kwargs.get("driver") or getattr(caller, "driver", None)
            if driver is None:
                raise StrategyException(
                    self, error="Driver not available — strategy requires RepositoryWithDriver"
                )

            document: FileDocument = facade.request()
            source = Path(str(document.filename))

            if not source.is_file():
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="source message missing",
                    filename=str(source),
                )
                return False

            stem = self.output_name(document, source)
            try:
                output = driver.copy(source, filename=stem, suffix=source.suffix, mkdir=True)
            except (DriverException, OSError) as e:
                # This layer stops the propagation, so this layer owns the ERROR
                # (NFRQ-OBS-01). A destination that cannot be written — a file
                # held open by another process, a directory without the right —
                # costs its own message and no other. No `output_filename` is
                # stamped, so the processor will not settle the source either:
                # nothing is deleted for an archive that was never written.
                self.error(
                    msg=Event.Write.name,
                    step=Event.Failed.name,
                    reason="destination not written",
                    filename=str(source),
                    stem=stem,
                    error=str(e),
                )
                return False

            if Path(output).resolve() == source.resolve():
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="write_path resolves onto the source — nothing copied",
                    filename=str(source),
                    output=str(output),
                )
                return False

            # Storage layer (M2): the name the second repository builds on, and
            # who put it there, when. `output_filename` is the driver's own
            # answer, never a name recomposed from metadata.
            document.update_metadata("output_filename", str(output))
            document.update_metadata("stored_by", self.name)
            document.update_metadata("stored_at", Now.utc())

            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                stem=stem,
                output=str(output),
            )
            return True
        except StrategyException:
            raise
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e


class WriteEmailAttachments(StrategyWrite):
    """Write a message's attachments into a directory named after the copy the
    first repository made.

    Second of a pair; it never touches the message itself. Rules, in order:
    BR01 the message declares attachments; BR02/BR03 `AttachmentPolicy` — the
    same rule the extraction pipeline applies — rejects the record. Every
    skipped part is named in the audit and in `attachments_skipped`: a bundle
    that quietly lost a part is worse than one that never had it.
    """

    __slots__ = ("_reader",)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._reader = MailParser()

    @staticmethod
    def _unique(name: str, taken: set[str]) -> str:
        # Two attachments may arrive under one name; the second must not
        # overwrite the first, and renaming both would lose the sender's naming.
        safe = Path(Path(name).name)
        stem, suffix = safe.stem or "attachment", safe.suffix or ".bin"
        candidate = f"{stem}{suffix}"
        counter = 1
        while candidate.lower() in taken:
            counter += 1
            candidate = f"{stem}-{counter}{suffix}"
        taken.add(candidate.lower())
        return candidate

    def _write_attachments(
        self,
        driver: Any,
        document: FileDocument,
        source: Path,
        subdir: str,
        policy: AttachmentPolicy,
    ) -> tuple[list[str], list[str], list[str]]:
        records = list(document.metadata.get(MailKeys.ATTACHMENTS) or [])
        written: list[str] = []
        skipped: list[str] = []
        failed: list[str] = []
        taken: set[str] = set()

        for index, record in enumerate(records):
            name = self._unique(str(record.get("name") or f"attachment-{index + 1}"), taken)

            reason = policy.rejects(record)
            if reason:
                skipped.append(name)
                self.debug(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    scope="item",
                    reason=reason,
                    attachment=name,
                )
                continue

            try:
                attachment = self._reader.extract(
                    index,
                    expected=str(record.get("digest") or ""),
                    path=source,
                )
            except (IndexError, ValueError) as e:
                failed.append(name)
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="attachment not written",
                    attachment=name,
                    error=str(e),
                )
                continue

            digest, size = attachment.digest, attachment.size
            try:
                output = driver.write(
                    attachment.payload,
                    filename=Path(name).stem,
                    suffix=Path(name).suffix,
                    subdir=subdir,
                    mkdir=True,
                )
            except (DriverException, OSError) as e:
                failed.append(name)
                self.error(
                    msg=Event.Write.name,
                    step=Event.Failed.name,
                    reason="attachment not written",
                    attachment=name,
                    error=str(e),
                )
                continue
            finally:
                # One payload resident at a time: without this the previous
                # attachment stays referenced while the next one is decoded.
                attachment = None

            written.append(str(output))
            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                scope="item",
                attachment=name,
                digest=digest,
                size=size,
                output=str(output),
            )

        return written, skipped, failed

    def execute(self, caller: IWattleflow, facade: ITarget, **kwargs: Any) -> bool:
        try:
            self.debug(msg=Event.Write.name, step=Event.Started.name, caller=caller)
            Attribute.evaluate(caller=self, target=caller, expected_type=IRepository)
            Attribute.evaluate(caller=self, target=facade, expected_type=ITarget)

            driver = kwargs.get("driver") or getattr(caller, "driver", None)
            if driver is None:
                raise StrategyException(
                    self, error="Driver not available — strategy requires RepositoryWithDriver"
                )

            document: FileDocument = facade.request()

            # BR01 — nothing to bundle is a complete outcome, not a failure.
            if not document.metadata.get(MailKeys.HAS_ATTACHMENTS):
                self.debug(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="message declares no attachments",
                )
                return True

            output = str(document.metadata.get("output_filename") or "")
            if not output:
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="no output_filename — the copy repository must be registered first",
                    document=document.identifier,
                )
                return False

            source = Path(str(document.filename))
            if not source.is_file():
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="source message missing",
                    filename=str(source),
                )
                return False

            subdir = Path(output).stem
            # The policy the extraction pipeline already uses — same records,
            # same question, so the same rule and the same configuration keys.
            policy = AttachmentPolicy(
                skip_inline=bool(kwargs.get("skip_inline")),
                skip_types=kwargs.get("skip_types") or (),
                skip_below=int(kwargs.get("skip_below") or 0),
            )
            written, skipped, failed = self._write_attachments(
                driver, document, source, subdir, policy
            )

            # Change layer (M2): who bundled, when, and with what effect. The
            # copy strategy's own stamps are left untouched — one document
            # carries the record of BOTH writes, not the last one only.
            document.update_metadata("attachments_by", self.name)
            document.update_metadata("attachments_at", Now.utc())
            document.update_metadata("attachments_subdir", subdir)
            document.update_metadata("attachments_written", written)
            document.update_metadata("attachments_skipped", skipped)
            document.update_metadata("attachments_failed", failed)

            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                subdir=subdir,
                attachments=document.metadata.get(MailKeys.ATTACHMENT_COUNT),
                written=len(written),
                skipped=len(skipped),
                failed=len(failed),
            )
            # A bundle missing a part is not a completed write, whatever the
            # repository can currently tell from the answer.
            return not failed
        except StrategyException:
            raise
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        finally:
            # The bundle is complete, so the memo has no next reader — holding it
            # would keep one whole message alive until the next message arrives.
            self._reader.release()


class WriteEmailText(StrategyWrite):
    """Write the message as plain text beside the copy the first repository made.

    Third of the set; like the second it names itself from `output_filename`, so
    all three artefacts of one message share a stem. The text is
    `MailMessage.render()` — the rendered header block, the attachment names and
    the body — which deliberately leaves out `Bcc` and the delivery trace: those
    are headers of the transport, not content of the message.

    The body is not in the metadata (a manifest describes, it does not carry),
    so the message is read again here. That read is memoised per source, and the
    memo is dropped when the write is done.
    """

    __slots__ = ("_reader",)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._reader = MailParser()

    def execute(self, caller: IWattleflow, facade: ITarget, **kwargs: Any) -> bool:
        try:
            self.debug(msg=Event.Write.name, step=Event.Started.name, caller=caller)
            Attribute.evaluate(caller=self, target=caller, expected_type=IRepository)
            Attribute.evaluate(caller=self, target=facade, expected_type=ITarget)

            driver = kwargs.get("driver") or getattr(caller, "driver", None)
            if driver is None:
                raise StrategyException(
                    self, error="Driver not available — strategy requires RepositoryWithDriver"
                )

            document: FileDocument = facade.request()

            output = str(document.metadata.get("output_filename") or "")
            if not output:
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="no output_filename — the copy repository must be registered first",
                    document=document.identifier,
                )
                return False

            source = Path(str(document.filename))
            if not source.is_file():
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="source message missing",
                    filename=str(source),
                )
                return False

            message = self._reader.read(path=source)
            formatter = FormatterFactory.create(FileType.TXT)
            payload = formatter.serialise(message.render())

            if not payload.strip():
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="message rendered empty, nothing written",
                    filename=str(source),
                )
                return False

            stem = Path(output).stem
            try:
                written = driver.write(
                    payload,
                    filename=stem,
                    suffix=formatter.SUFFIX,
                    encoding="utf-8",
                    mkdir=True,
                )
            except (DriverException, OSError) as e:
                # As in the copy strategy: this layer stops the propagation, so
                # it owns the ERROR, and one unwritable destination costs its own
                # message and no other.
                self.error(
                    msg=Event.Write.name,
                    step=Event.Failed.name,
                    reason="text not written",
                    filename=str(source),
                    stem=stem,
                    error=str(e),
                )
                return False

            # Change layer (M2): who rendered, when, and how much text it came
            # to. The copy and attachment stamps are left as they are.
            document.update_metadata("text_by", self.name)
            document.update_metadata("text_at", Now.utc())
            document.update_metadata("text_filename", str(written))
            document.update_metadata("text_chars", len(payload))

            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                stem=stem,
                chars=len(payload),
                output=str(written),
            )
            return True
        except StrategyException:
            raise
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        finally:
            # Nothing else reads this message, so the memo has no next reader.
            self._reader.release()


# ----------------------------------------------------------------------------#
# endregion Classes                                                           #
# ----------------------------------------------------------------------------#

__all__ = [
    "CreateEmailDocument",
    "WriteEmailAttachments",
    "WriteEmailCopy",
    "WriteEmailCopyOLD",
    "WriteEmailText",
    "WriteEmailWithAttachmentOLD",
]
