# Module name: pipelines/ocr/ocr_tika_extractor.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from pathlib import Path
from typing import Any, Optional
from wattleflow.core import IProcessor, ITarget
from wattleflow.concrete import GenericPipeline
from wattleflow.concrete.exception import PipelineException
from wattleflow.enums.event import Event
from wattleflow.documents.file import FileDocument
from wattleflow.concrete.helpers import Attribute
from wattleflow.processors.ocr import OCRPreflightMixin
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Pipelines                                                            #
# --------------------------------------------------------------------------- #


class PipelineOCRExtractTika(OCRPreflightMixin, GenericPipeline):
    """Extract text via OCR, populating ``document.content``.
    Uses the server-side mechanism as ``PipelinePDFExtractText`` (Apache
    Tika → tesseract), so scanned PDFs and images yield text. Format-agnostic
    (Tika detects the type).`.
    """

    ALLOWED = ["backend", "tika_timeout"]
    SUPPORTED_BACKENDS = ("tika",)

    def __init__(self, **kwargs: Any) -> None:
        backend = kwargs.pop("backend", "tika")
        if backend not in self.SUPPORTED_BACKENDS:
            raise PipelineException(
                caller=self,
                error=f"Unsupported backend {backend!r}. Expected one of {self.SUPPORTED_BACKENDS}",
            )
        super().__init__(backend=backend, **kwargs)

    def _extract_using_tika(self, path: Path) -> str:
        # Stage the LOCAL JAR and validate Java BEFORE importing tika, which
        # freezes TIKA_SERVER_JAR / TIKA_PATH at import time. Tika runs tesseract
        # server-side, so scanned images with no text still yield text.
        if not getattr(self, "_tika_ready", False):
            self._ensure_tika_ready()
            self._tika_ready = True
        from tika import parser as tika_parser

        parsed = tika_parser.from_file(
            str(path.absolute()),
            requestOptions={"timeout": self._request_timeout()},
        )
        return (parsed.get("content") or "").strip()

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

        existing: Optional[str] = document.content or ""
        if existing.strip():
            self.debug(
                msg=Event.Transform.name,
                reason="document already has content",
                filename=filename,
                chars=len(existing),
            )
            return

        self.debug(
            msg=Event.Transform.name,
            step=Event.Started.name,
            backend=self.backend,
            filename=filename,
        )

        try:
            text = self._extract_using_tika(path)
        except PipelineException:
            raise
        except Exception as e:
            self.debug(msg=Event.Transform.name, step=Event.Failed.name, error=str(e))
            raise PipelineException(
                caller=self,
                error=f"OCR extraction failed for {filename}: {e}",
            ) from e

        document.update_content(text)
        document.update_metadata("ocr_backend", self.backend)
        document.update_metadata("extracted_chars", len(text))

        uid = processor.blackboard.write(
            facade=facade,
            processor=processor,
            pipeline=self,
        )

        self.debug(
            msg=Event.Transform.name,
            step=Event.Completed.name,
            backend=self.backend,
            uid=uid,
            chars=len(text),
        )


# --------------------------------------------------------------------------- #
# endregion Pipelines                                                         #
# --------------------------------------------------------------------------- #


__all__ = ["PipelineOCRExtractTika"]
