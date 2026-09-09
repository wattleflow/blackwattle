# Module name: pipelines/mail/extract.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
The mail reader family: the shared step and the two containers it accepts.

Everything after reading is identical — render the content, stamp the raw
headers and the normalised envelope, publish to the blackboard — so the tail
exists once, on the shared step (NFRQ-ORG-08).

Reading is shared too, and deliberately: the container is decided by the
message CONTENT, not by its name, so `MailParser.deserialise` dispatches on the
OLE2 signature and a .msg export written as plain RFC 822 — which mail clients
do routinely — reads correctly without a decision here. A subclass therefore
narrows only `SUFFIXES`: what it accepts, not how it parses.

The split follows the layer boundary: what a message IS belongs to the mail
model (`NFRQ-ORG-09`, `FRQ-MAIL-01`); stamping a document and publishing it is
pipeline wiring and belongs here. The parser never sees a `Document`, and this
module never re-derives what the model already answers.
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from pathlib import Path
from typing import Any
from wattleflow.core import IProcessor, ITarget
from wattleflow.concrete import GenericPipeline
from wattleflow.enums.event import Event
from wattleflow.documents.file import FileDocument
from wattleflow.helpers.parsers.mail import MailHeader, MailKeys, MailMessage, MailParser
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Types                                                                #
# --------------------------------------------------------------------------- #

# Suffixes carry the leading dot because `Path.suffix` does.
EML_SUFFIX: tuple[str, ...] = (".eml",)
MSG_SUFFIX: tuple[str, ...] = (".msg",)

# --------------------------------------------------------------------------- #
# endregion Types                                                             #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Pipelines                                                            #
# --------------------------------------------------------------------------- #
class PipelineMailExtract(GenericPipeline):
    """Read one message, stamp it onto its document, publish it."""

    SUFFIXES: tuple[str, ...] = EML_SUFFIX + MSG_SUFFIX

    def owns(self, source_path: Path) -> bool:
        return source_path.suffix.lower() in self.SUFFIXES

    def read(self, source_path: Path) -> MailMessage | None:
        try:
            # The parser owns the source policy: it opens, audits and closes the
            # file, and turns any failure into ParserError (FRQ-PTN-15.19).
            return MailParser().parse(path=source_path)
        except Exception as e:
            self.error(
                msg=Event.Transform.name,
                step=Event.Failed.name,
                error=f"mail parse failed: {e}",
                filename=str(source_path),
            )
            return None

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> None:
        document: FileDocument = facade.request()
        source_path: Path = Path(document.filename or document.identifier)

        if source_path.exists() is False:
            raise FileNotFoundError(f"source_path: {str(source_path)} is missing!")

        if not self.owns(source_path):
            self.debug(
                msg=Event.Transform.name,
                step=Event.Check.name,
                reason="source not owned by this reader, skipped",
                suffixes=", ".join(self.SUFFIXES),
                filename=str(source_path),
            )
            return

        # Already read at genesis by a mail-aware create strategy: reading it a
        # second time would double the cost of the largest step in the chain to
        # arrive at the same metadata. What is left to do is publish it.
        if document.metadata.get(MailKeys.CONTENT_DIGEST):
            uid = processor.blackboard.write(facade=facade, processor=processor, pipeline=self)
            self.debug(
                msg=Event.Transform.name,
                step=Event.Completed.name,
                reason="message already read at genesis, published unchanged",
                uid=uid,
                filename=str(source_path),
            )
            return

        message: MailMessage | None = self.read(source_path)
        if message is None:
            self.warning(
                msg=Event.Transform.name,
                step=Event.Check.name,
                reason="empty message",
                filename=str(source_path),
            )
            return

        content = message.render()
        if not content.strip():
            self.warning(
                msg=Event.Transform.name,
                step=Event.Check.name,
                reason="empty mail payload",
                filename=str(source_path),
            )
            return

        self.stamp(document, message, content)

        uid = processor.blackboard.write(
            facade=facade,
            processor=processor,
            pipeline=self,
        )

        self.debug(
            msg=Event.Transform.name,
            step=Event.Completed.name,
            uid=uid,
            subject=message.text(MailHeader.SUBJECT),
            attachments=len(message.attachments),
            size=len(content),
        )

    def stamp(self, document: FileDocument, message: MailMessage, content: str) -> None:
        """Everything the message answers, onto its document.

        Redundant when `CreateEmailDocument` already read the file — the values
        are identical, so re-stamping is idempotent — and load-bearing when the
        chain creates plain file documents instead: without `content_digest` the
        blackboard would key the message on its rendered text. No name is
        stamped here — an output name is the write side's decision.
        """
        document.update_content(content)
        for key, value in message.as_metadata(with_payload=False).items():
            document.update_metadata(key, value)

        document.update_metadata(MailKeys.CONTENT_DIGEST, message.digest)


class PipelineMailExtractEML(PipelineMailExtract):
    """Read an RFC 822 .eml message into its document."""

    SUFFIXES: tuple[str, ...] = EML_SUFFIX


class PipelineMailExtractMSG(PipelineMailExtract):
    """Read an Outlook .msg message into its document."""

    SUFFIXES: tuple[str, ...] = MSG_SUFFIX


# --------------------------------------------------------------------------- #
# endregion Pipelines                                                         #
# --------------------------------------------------------------------------- #

__all__ = [
    "EML_SUFFIX",
    "MSG_SUFFIX",
    "PipelineMailExtract",
    "PipelineMailExtractEML",
    "PipelineMailExtractMSG",
]
