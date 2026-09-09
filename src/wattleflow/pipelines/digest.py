# Module name: pipelines/digest.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
Stamp the CONTENT digest of a document's source file onto its metadata.

The digest is taken over the file's BYTES (`helpers.digest.FileDigest`), so it
is stable across copies and renames and can serve as a content-addressed key:
`BundleBlackboard` reads `digest` when no `content_digest` is stamped and keys
its canvas by it, which is what makes identical content deduplicate instead of
storing a second copy.

Belongs at the FRONT of a chain. Every later step that needs a stable key for
the source document — attachment fan-out, bundle manifest, write strategies —
then finds one already there instead of re-reading the file to derive its own.
Deriving it here also keeps the read to one pass and gives the digest its own
audit record, rather than leaving it a side effect of whichever step first
happened to need it.
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import hashlib
from pathlib import Path
from typing import Any
from wattleflow.core import IProcessor, ITarget
from wattleflow.concrete import GenericPipeline
from wattleflow.concrete.exception import PipelineException
from wattleflow.enums.event import Event
from wattleflow.documents.file import FileDocument
from wattleflow.helpers.digest import FileDigest
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Pipelines                                                            #
# --------------------------------------------------------------------------- #
class PipelineFileExtractDigest(GenericPipeline):
    """Stamp the labelled content digest of the source file onto the document."""

    ALLOWED = ["algorithm", "metadata_key", "overwrite"]

    DEFAULT_KEY = "digest"

    def __init__(self, **kwargs: Any) -> None:
        algorithm = str(kwargs.pop("algorithm", FileDigest.DEFAULT_ALGORITHM))
        super().__init__(
            algorithm=algorithm,
            metadata_key=str(kwargs.pop("metadata_key", self.DEFAULT_KEY)),
            overwrite=bool(kwargs.pop("overwrite", False)),
            **kwargs,
        )
        # A misconfigured algorithm must fail when the workflow is built, not on
        # the first file: hashlib would otherwise raise mid-run, per document.
        # Checked AFTER the base constructor so a rejected value still leaves a
        # fully built object — GenericPipeline.__del__ reads `_preset` without
        # guarding partial construction, unlike GenericParser.__getattr__.
        if algorithm not in hashlib.algorithms_available:
            raise PipelineException(
                caller=self,
                error=(
                    f"Unsupported digest algorithm {algorithm!r}. "
                    f"Expected one of {sorted(hashlib.algorithms_available)}"
                ),
            )

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> str | None:
        document: FileDocument = facade.request()
        key: str = self.metadata_key

        # Re-running the chain must not re-read every source; an existing digest
        # is authoritative unless the caller asked for a recompute.
        if document.metadata.get(key) and not self.overwrite:
            self.debug(
                msg=Event.Transform.name,
                step=Event.Check.name,
                reason="digest already stamped, skipped",
                key=key,
                filename=str(document.filename),
            )
            return None

        source_path = Path(document.filename or document.identifier)
        if not source_path.is_file():
            raise PipelineException(
                caller=self,
                error=f"source_path: {source_path} is not a readable file!",
            )

        try:
            digest = FileDigest.labelled(source_path, algorithm=self.algorithm)
        except OSError as e:
            error = f"digest failed for {source_path}: {e}"
            self.debug(
                msg=Event.Transform.name,
                step=Event.Failed.name,
                error=error,
                algorithm=self.algorithm,
                filename=str(source_path),
            )
            raise PipelineException(caller=self, error=error) from e

        document.update_metadata(key, digest)

        uid = processor.blackboard.write(
            facade=facade,
            processor=processor,
            pipeline=self,
        )

        self.debug(
            msg=Event.Transform.name,
            step=Event.Completed.name,
            uid=uid,
            key=key,
            algorithm=self.algorithm,
            digest=digest,
            size=source_path.stat().st_size,
        )
        return uid


# --------------------------------------------------------------------------- #
# endregion Pipelines                                                         #
# --------------------------------------------------------------------------- #

__all__ = ["PipelineFileExtractDigest"]
