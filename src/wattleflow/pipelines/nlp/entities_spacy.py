# Module name: pipelines/nlp/entities_spacy.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# pipeline name into the output filename, yielding a forensic trail of
#   pip install spacy
#   python -m spacy download en_core_web_sm
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import re
from typing import Any, Dict, List, Tuple
from wattleflow.core import IProcessor, ITarget
from wattleflow.concrete import GenericPipeline
from wattleflow.enums.event import Event
from wattleflow.documents.file import FileDocument
from wattleflow.concrete.helpers import Attribute
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Pipelines                                                            #
# --------------------------------------------------------------------------- #


class PipelineSpacyEntities(GenericPipeline):
    _LABELS: Tuple[str, ...] = ("PERSON", "ORG", "EMAIL", "TELEPHONE")

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> None:

        document: FileDocument = facade.request()
        content: str = document.content
        Attribute.evaluate(caller=self, target=content, expected_type=str)

        if not content.strip():
            self.warning(msg=Event.Transform.name, step=Event.Check.name, error="Content is empty!")
            return

        try:
            import spacy  # lazy import — only required when this pipeline runs
        except ImportError as e:
            raise RuntimeError(
                "PipelinessSpacyEntityRecognition requires spacy + en_core_web_sm"
            ) from e

        try:
            nlp = spacy.load("en_core_web_sm")
        except OSError as e:
            self.debug(msg=Event.Transform.name, step=Event.Failed.name, error=str(e))
            raise RuntimeError(
                "spaCy model 'en_core_web_sm' not installed. "
                "Run: python -m spacy download en_core_web_sm"
            ) from e

        ignore = processor.ignore or []
        filter_res = [re.compile(p, re.IGNORECASE) for p in ignore]

        doc = nlp(content)

        targets: List[Dict[str, str]] = []
        seen: Dict[str, str] = {}
        counter = 0
        for ent in doc.ents:
            if ent.label_ not in self._LABELS:
                continue
            text = ent.text.strip()
            if not text:
                continue
            if any(r.search(text) for r in filter_res):
                continue
            if text in seen:
                continue
            counter += 1
            label = f"ENTITET{counter}"
            seen[text] = label
            targets.append({"text": text, "replacement": label, "entity": ent.label_})

        redacted = content
        # Sort by length descending so longer surface forms are replaced first
        # (avoids partial overlap when one entity is a substring of another).
        for text in sorted(seen, key=len, reverse=True):
            redacted = re.sub(re.escape(text), seen[text], redacted)

        document.update_content(redacted)
        document.update_metadata("entity_targets", targets)

        uid = processor.blackboard.write(
            facade=facade,
            processor=processor,
            pipeline=self,
        )
        self.debug(
            msg=Event.Transform.name, step=Event.Completed.name, uid=uid, entities=len(targets)
        )


class PipelineSpacyEntityRecognition(GenericPipeline):
    _LABELS: Tuple[str, ...] = ("PERSON", "ORG", "EMAIL", "TELEPHONE")

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> None:

        document: FileDocument = facade.request()
        content: str = document.content
        Attribute.evaluate(caller=self, target=content, expected_type=str)

        if not content.strip():
            self.warning(msg=Event.Transform.name, step=Event.Check.name, error="Content is empty!")
            return

        try:
            import spacy  # lazy import — only required when this pipeline runs
        except ImportError as e:
            raise RuntimeError("PipelineEntityRecognition requires spacy + en_core_web_sm") from e

        try:
            nlp = spacy.load("en_core_web_sm")
        except OSError as e:
            self.debug(msg=Event.Transform.name, step=Event.Failed.name, error=str(e))
            raise RuntimeError(
                "spaCy model 'en_core_web_sm' not installed. "
                "Run: python -m spacy download en_core_web_sm"
            ) from e

        ignore = processor.ignore or []
        filter_res = [re.compile(p, re.IGNORECASE) for p in ignore]

        doc = nlp(content)

        targets: List[Dict[str, str]] = []
        seen: Dict[str, str] = {}
        counter = 0
        for ent in doc.ents:
            if ent.label_ not in self._LABELS:
                continue
            text = ent.text.strip()
            if not text:
                continue
            if any(r.search(text) for r in filter_res):
                continue
            if text in seen:
                continue
            counter += 1
            label = f"ENTITET{counter}"
            seen[text] = label
            targets.append({"text": text, "replacement": label, "entity": ent.label_})

        redacted = content
        # Sort by length descending so longer surface forms are replaced first
        # (avoids partial overlap when one entity is a substring of another).
        for text in sorted(seen, key=len, reverse=True):
            redacted = re.sub(re.escape(text), seen[text], redacted)

        document.update_content(redacted)
        document.update_metadata("entity_targets", targets)

        uid = processor.blackboard.write(
            facade=facade,
            processor=processor,
            pipeline=self,
        )

        self.debug(
            msg=Event.Transform.name, step=Event.Completed.name, uid=uid, entities=len(targets)
        )


# --------------------------------------------------------------------------- #
# endregion Pipeline                                                          #
# --------------------------------------------------------------------------- #
