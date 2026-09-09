# Module name: pipelines/ocr/ocr_span_reductor.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple
from wattleflow.core import IProcessor, ITarget
from wattleflow.concrete import GenericPipeline
from wattleflow.documents.file import FileDocument
from wattleflow.enums.event import Event
from wattleflow.enums.imageformat import ImageFormat
from wattleflow.helpers.parsers.ocr import OcrParser
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Types                                                                #
# --------------------------------------------------------------------------- #
# Accepted raster formats come from ImageFormat (enums/imageformat.py); the
# guard behind OcrParser validates a source against the same vocabulary.

Patterns = List[Dict[str, str]]
RedactBoxes = List[Tuple[int, int, int, int]]
Tokens = List[Dict[str, Any]]
# Standard redaction-span schema shared by every reduct pipeline and consumed by
# the redaction write strategies: {"page": int|None, "bbox": (x0,y0,x1,y1),
# "replacement": str, "text": str}. For images page is None and bbox is pixels.
SpanList = List[Dict[str, Any]]
# --------------------------------------------------------------------------- #
# endregion Types                                                             #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Pipelines                                                            #
# --------------------------------------------------------------------------- #


class PipelineOCRRedactSpans(GenericPipeline):
    """Locate redaction spans for a raster image via OCR: match each PII/entity
    target against the OCR token stream and emit union bounding boxes. Reduction
    only — text extraction is a separate (native) pipeline."""

    def __locate_phrase(self, tokens: Tokens, phrase: str) -> RedactBoxes:
        """Greedy contiguous-token match for phrase in OCR stream.
        Union bbox per hit. Case-insensitive."""
        if not phrase:
            return []

        words = [w for w in re.split(r"\s+", phrase.strip()) if w]

        if not words:
            return []

        N = len(tokens)
        W = len(words)

        hits: RedactBoxes = []
        lower = [w.lower() for w in words]

        i = 0
        while i <= N - W:
            ok = True
            for j in range(W):
                if lower[j] not in tokens[i + j]["text"].lower():
                    ok = False
                    break
            if ok:
                boxes = [tokens[i + j]["bbox"] for j in range(W)]
                x0 = min(b[0] for b in boxes)
                y0 = min(b[1] for b in boxes)
                x1 = max(b[2] for b in boxes)
                y1 = max(b[3] for b in boxes)
                hits.append((x0, y0, x1, y1))
                i += W
            else:
                i += 1
        return hits

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> None:
        document: FileDocument = facade.request()
        source_path = Path(document.filename)
        suffix = source_path.suffix.lower()

        if not ImageFormat.accepts(suffix):
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
            tokens = OcrParser().parse(path=source_path, expected=tuple(ImageFormat))
        except Exception as e:
            self.error(msg=Event.Transform.name, step=Event.Failed.name, error=f"OCR failed: {e}")
            return

        # Emit the STANDARD redaction-span schema (shared with PDF reduct + all
        # redaction write strategies); page is None for raster images.
        spans: SpanList = []
        for item in targets:
            text = item["text"]
            repl = item.get("replacement", "") or ""
            for box in self.__locate_phrase(tokens, text):
                spans.append({"page": None, "bbox": box, "replacement": repl, "text": text})

        document.update_metadata("redact_spans", spans)

        uid = processor.blackboard.write(
            facade=facade,
            processor=processor,
            pipeline=self,
        )

        self.debug(
            msg=Event.Transform.name,
            step=Event.Completed.name,
            uid=uid,
            targets=len(targets),
            spans=len(spans),
        )


# --------------------------------------------------------------------------- #
# endregion Pipelines                                                         #
# --------------------------------------------------------------------------- #

__all__ = ["PipelineOCRRedactSpans"]
