# Module name: pipelines/mail/attachments.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from pathlib import Path
from typing import Any
from wattleflow.core import IProcessor, ITarget
from wattleflow.concrete import GenericPipeline
from wattleflow.concrete.document import DocumentFacade
from wattleflow.enums.event import Event
from wattleflow.documents.file import FileDocument
from wattleflow.helpers.digest import FileDigest
from wattleflow.helpers.parsers.mail import AttachmentPolicy, MailKeys
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Types                                                                #
# --------------------------------------------------------------------------- #

# What a container reports when it knows nothing about the part's type.
GENERIC_TYPE: str = "application/octet-stream"

# --------------------------------------------------------------------------- #
# endregion Types                                                             #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Documents                                                            #
# --------------------------------------------------------------------------- #


class AttachmentDocument(FileDocument):
    """FileDocument for an in-memory attachment: there is no on-disk source to
    stat, so the file-metadata probe is skipped (payload/provenance live in
    metadata instead). Keeps the FileDocument surface write strategies expect."""

    def update_file_metadata(self) -> None:
        return


# --------------------------------------------------------------------------- #
# endregion Documents                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Pipeline                                                             #
# --------------------------------------------------------------------------- #


class PipelineMailExtractAttachment(GenericPipeline):
    """Promote each mail attachment to its OWN document on the blackboard.

    Reads the ``mail_attachments`` metadata produced by PipelineMailExtractEML /
    PipelineMailExtractMSG and, for each attachment, builds a child FileDocument
    carrying its COORDINATES plus provenance (``is_attachment``, ``content_digest`` =
    the attachment's own content hash, ``parent_digest`` = the message digest of
    the mail it came out of). Each child is written to the blackboard; a
    BundleBlackboard keys by ``content_digest`` so identical attachments across
    messages are deduplicated and an email→attachments manifest is recorded. The
    attachment write strategy (WriteEmailWithAttachment) then repackages each
    child into a file."""

    ALLOWED = ["skip_inline", "skip_types", "skip_below"]

    __slots__ = ("_policy",)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            skip_inline=bool(kwargs.pop("skip_inline", True)),
            skip_types=tuple(kwargs.pop("skip_types", ()) or ()),
            skip_below=int(kwargs.pop("skip_below", 0) or 0),
            **kwargs,
        )
        self._policy = AttachmentPolicy(
            skip_inline=self.skip_inline,
            skip_types=self.skip_types,
            skip_below=self.skip_below,
        )

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> None:

        # Attribute.evaluate(caller=self, target=content, expected_type=str)
        document: FileDocument = facade.request()
        source_path = Path(document.filename)

        parent_digest = document.metadata.get(
            MailKeys.CONTENT_DIGEST
        ) or document.metadata.get(MailKeys.FILE_DIGEST)
        if not parent_digest:
            parent_digest = document.metadata.get("digest")
        if not parent_digest and source_path.is_file():
            parent_digest = FileDigest.labelled(source_path)

        if parent_digest:
            document.update_metadata(MailKeys.CONTENT_DIGEST, str(parent_digest))

        attachments: list[dict[str, Any]] = list(
            document.metadata.get(MailKeys.ATTACHMENTS) or []
        )
        document.update_metadata(MailKeys.HAS_ATTACHMENTS, bool(attachments))

        # Re-write the parent so the blackboard keys it stably before children link.
        processor.blackboard.write(facade=facade, processor=processor, pipeline=self)

        if not attachments:
            self.debug(
                msg=Event.Transform.name,
                step=Event.Started.name,
                reason="no attachments",
            )
            return

        emitted = 0
        skipped = 0
        for idx, att in enumerate(attachments):
            reason = self._policy.rejects(att)
            if reason:
                # Never a silent cap: what the policy drops is named, one record
                # each, or "3 of 5 exported" becomes unreadable (NFRQ-OBS-01).
                skipped += 1
                self.debug(
                    msg=Event.Transform.name,
                    step=Event.Check.name,
                    reason=reason,
                    attachment=str(att.get("name") or ""),
                    content_type=AttachmentPolicy.content_type(att),
                    size=att.get("size"),
                )
                continue
            child = self._build_child(
                att, idx, str(parent_digest or ""), document, source_path
            )
            processor.blackboard.write(facade=child, processor=processor, pipeline=self)
            emitted += 1

        self.debug(
            msg=Event.Transform.name,
            step=Event.Completed.name,
            parent_digest=parent_digest,
            attachments=len(attachments),
            children=emitted,
            skipped=skipped,
        )

    @staticmethod
    def _build_child(
        att: dict[str, Any],
        idx: int,
        parent_digest: str,
        parent: FileDocument,
        source_path: Path,
    ) -> ITarget:
        name = str(att.get("name") or f"attachment-{idx + 1}.bin")
        # COORDINATES, not content. The child says which message it came out of
        # and which part it is; the write strategy reads those bytes back at the
        # moment it hands them to the driver. A payload stamped here would sit on
        # the canvas until the flush — once per attachment, for the whole cycle —
        # to say nothing the digest does not already say.
        document = AttachmentDocument(filename=name)
        document.update_metadata(MailKeys.IS_ATTACHMENT, True)
        # Digested over the payload at parse time — the attachment's identity is
        # its content, so the same file attached to two messages deduplicates.
        document.update_metadata(MailKeys.CONTENT_DIGEST, str(att.get("digest") or ""))
        document.update_metadata(MailKeys.PARENT_DIGEST, parent_digest)
        # The run's zone travels with the child so the write side can name in
        # it; that is provenance, not a name.
        zone = parent.metadata.get("archive_zone")
        if zone:
            document.update_metadata("archive_zone", zone)
        document.update_metadata(MailKeys.PARENT_SOURCE, str(source_path))
        document.update_metadata(MailKeys.ATTACHMENT_INDEX, idx)
        document.update_metadata(MailKeys.ATTACHMENT_NAME, name)
        document.update_metadata(MailKeys.CONTENT_TYPE, att.get("content_type"))
        document.update_metadata("size", int(att.get("size") or 0))
        return DocumentFacade(document)


# --------------------------------------------------------------------------- #
# endregion Pipeline                                                          #
# --------------------------------------------------------------------------- #

__all__ = ["AttachmentPolicy", "AttachmentDocument", "PipelineMailExtractAttachment"]
