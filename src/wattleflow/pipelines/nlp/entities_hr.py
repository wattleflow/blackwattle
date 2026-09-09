# Module name: pipelines/nlp/entities_hr.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# Croatian NER pipelines: spaCy, Stanza/CLASSLA, Flair.                       #
# Install (per backend, only what you use):                                   #
#   pip install spacy && python -m spacy download hr_core_news_lg            #
#   pip install classla && python -c "import classla; classla.download('hr')"#
#   pip install flair                                                         #
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


Targets = List[Dict[str, str]]


# --------------------------------------------------------------------------- #
# region Helpers                                                              #
# --------------------------------------------------------------------------- #
def _redact(content: str, seen: Dict[str, str]) -> str:
    redacted = content
    for text in sorted(seen, key=len, reverse=True):
        redacted = re.sub(re.escape(text), seen[text], redacted)
    return redacted


def _filter_regexes(processor: IProcessor) -> List[re.Pattern]:
    ignore = getattr(processor, "ignore", None) or []
    return [re.compile(p, re.IGNORECASE) for p in ignore]


# --------------------------------------------------------------------------- #
# endregion Helpers                                                           #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Pipelines                                                            #
# --------------------------------------------------------------------------- #
class PipelineSpacyEntitiesHR(GenericPipeline):
    """
    Croatian NER via spaCy.

    Processor config (with defaults):
        spacy_model:    str   = "hr_core_news_lg"
        spacy_labels:   tuple = ("PER", "LOC", "ORG", "MISC")
        spacy_disable:  list  = []           # e.g. ["tagger", "parser"] for speed
        spacy_exclude:  list  = []
    """

    _DEFAULT_LABELS: Tuple[str, ...] = ("PER", "LOC", "ORG", "MISC")

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> None:

        document: FileDocument = facade.request()
        content: str = document.content
        Attribute.evaluate(caller=self, target=content, expected_type=str)

        if not content.strip():
            self.warning(msg=Event.Transform.name, step=Event.Check.name, error="Content is empty!")
            return

        try:
            import spacy
        except ImportError as e:
            raise RuntimeError("PipelineSpacyEntitiesHR requires spacy") from e

        model = getattr(processor, "spacy_model", "hr_core_news_lg")
        labels = tuple(getattr(processor, "spacy_labels", self._DEFAULT_LABELS))
        disable = list(getattr(processor, "spacy_disable", []) or [])
        exclude = list(getattr(processor, "spacy_exclude", []) or [])

        try:
            nlp = spacy.load(model, disable=disable, exclude=exclude)
        except OSError as e:
            self.debug(msg=Event.Transform.name, step=Event.Failed.name, error=str(e))
            raise RuntimeError(
                f"spaCy model '{model}' not installed. Run: python -m spacy download {model}"
            ) from e

        filter_res = _filter_regexes(processor)

        doc = nlp(content)

        targets: Targets = []
        seen: Dict[str, str] = {}
        counter = 0
        for ent in doc.ents:
            if ent.label_ not in labels:
                continue
            text = ent.text.strip()
            if not text or text in seen:
                continue
            if any(r.search(text) for r in filter_res):
                continue
            counter += 1
            label = f"ENTITET{counter}"
            seen[text] = label
            targets.append({"text": text, "replacement": label, "entity": ent.label_})

        document.update_content(_redact(content, seen))
        document.update_metadata("entity_targets", targets)

        uid = processor.blackboard.write(
            facade=facade,
            processor=processor,
            pipeline=self,
        )
        self.debug(
            msg=Event.Transform.name,
            step=Event.Completed.name,
            uid=uid,
            entities=len(targets),
            backend="spacy",
        )


class PipelineStanzaEntitiesHR(GenericPipeline):
    """
    Croatian NER via Stanza / CLASSLA (preferred for South-Slavic).

    Processor config (with defaults):
        stanza_lang:       str  = "hr"
        stanza_processors: str  = "tokenize,ner"
        stanza_use_gpu:    bool = False
        stanza_use_classla: bool = True      # True = CLASSLA fork (better for HR)
        stanza_labels:     tuple = ("PER", "LOC", "ORG", "MISC")
        stanza_dir:        str | None = None # custom model cache directory
    """

    _DEFAULT_LABELS: Tuple[str, ...] = ("PER", "LOC", "ORG", "MISC")

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> None:

        document: FileDocument = facade.request()
        content: str = document.content
        Attribute.evaluate(caller=self, target=content, expected_type=str)

        if not content.strip():
            self.warning(msg=Event.Transform.name, step=Event.Check.name, error="Content is empty!")
            return

        use_classla = bool(getattr(processor, "stanza_use_classla", True))
        lang = getattr(processor, "stanza_lang", "hr")
        procs = getattr(processor, "stanza_processors", "tokenize,ner")
        use_gpu = bool(getattr(processor, "stanza_use_gpu", False))
        model_dir = getattr(processor, "stanza_dir", None)
        labels = tuple(getattr(processor, "stanza_labels", self._DEFAULT_LABELS))

        try:
            backend = __import__("classla") if use_classla else __import__("stanza")
        except ImportError as e:
            pkg = "classla" if use_classla else "stanza"
            raise RuntimeError(f"PipelineStanzaEntitiesHR requires '{pkg}'") from e

        pipeline_kwargs: Dict[str, Any] = {"lang": lang, "processors": procs, "use_gpu": use_gpu}
        if model_dir:
            pipeline_kwargs["dir"] = model_dir

        try:
            nlp = backend.Pipeline(**pipeline_kwargs)
        except Exception as e:
            pkg = "classla" if use_classla else "stanza"
            self.debug(msg=Event.Transform.name, step=Event.Failed.name, error=str(e))
            raise RuntimeError(
                f"{pkg} model for '{lang}' not available. "
                f"Run: python -c \"import {pkg}; {pkg}.download('{lang}')\""
            ) from e

        filter_res = _filter_regexes(processor)
        doc = nlp(content)

        targets: Targets = []
        seen: Dict[str, str] = {}
        counter = 0
        for sent in getattr(doc, "sentences", []):
            for ent in getattr(sent, "ents", []) or []:
                ent_type = getattr(ent, "type", None) or getattr(ent, "label_", None)
                if ent_type not in labels:
                    continue
                text = (getattr(ent, "text", "") or "").strip()
                if not text or text in seen:
                    continue
                if any(r.search(text) for r in filter_res):
                    continue
                counter += 1
                label = f"ENTITET{counter}"
                seen[text] = label
                targets.append({"text": text, "replacement": label, "entity": ent_type})

        document.update_content(_redact(content, seen))
        document.update_metadata("entity_targets", targets)

        uid = processor.blackboard.write(
            facade=facade,
            processor=processor,
            pipeline=self,
        )
        self.debug(
            msg=Event.Transform.name,
            step=Event.Completed.name,
            uid=uid,
            entities=len(targets),
            backend="classla" if use_classla else "stanza",
        )


class PipelineFlairEntitiesHR(GenericPipeline):
    """
    Croatian NER via Flair (BERTić / XLM-R style transformer tagger).

    Processor config (with defaults):
        flair_model:        str  = "classla/bcms-bertic-ner"
        flair_use_gpu:      bool = False
        flair_mini_batch:   int  = 16
        flair_labels:       tuple | None = None   # None = accept any tag
        flair_score_min:    float = 0.0           # filter low-confidence ents
    """

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> None:

        document: FileDocument = facade.request()
        content: str = document.content
        Attribute.evaluate(caller=self, target=content, expected_type=str)

        if not content.strip():
            self.warning(msg=Event.Transform.name, step=Event.Check.name, error="Content is empty!")
            return

        try:
            from flair.data import Sentence
            from flair.models import SequenceTagger
        except ImportError as e:
            raise RuntimeError("PipelineFlairEntitiesHR requires flair") from e

        model_name = getattr(processor, "flair_model", "classla/bcms-bertic-ner")
        use_gpu = bool(getattr(processor, "flair_use_gpu", False))
        mini_batch = int(getattr(processor, "flair_mini_batch", 16))
        labels = getattr(processor, "flair_labels", None)
        labels = tuple(labels) if labels else None
        score_min = float(getattr(processor, "flair_score_min", 0.0))

        if not use_gpu:
            try:
                import flair
                import torch

                flair.device = torch.device("cpu")
            except Exception:
                pass

        try:
            tagger = SequenceTagger.load(model_name)
        except Exception as e:
            self.debug(msg=Event.Transform.name, step=Event.Failed.name, error=str(e))
            raise RuntimeError(f"Flair model '{model_name}' could not be loaded") from e

        filter_res = _filter_regexes(processor)

        sentence = Sentence(content)
        tagger.predict(sentence, mini_batch_size=mini_batch)

        targets: Targets = []
        seen: Dict[str, str] = {}
        counter = 0
        for span in sentence.get_spans("ner"):
            tag = span.tag
            if labels and tag not in labels:
                continue
            if span.score < score_min:
                continue
            text = (span.text or "").strip()
            if not text or text in seen:
                continue
            if any(r.search(text) for r in filter_res):
                continue
            counter += 1
            label = f"ENTITET{counter}"
            seen[text] = label
            targets.append({"text": text, "replacement": label, "entity": tag})

        document.update_content(_redact(content, seen))
        document.update_metadata("entity_targets", targets)

        uid = processor.blackboard.write(
            facade=facade,
            processor=processor,
            pipeline=self,
        )
        self.debug(
            msg=Event.Transform.name,
            step=Event.Completed.name,
            uid=uid,
            entities=len(targets),
            backend="flair",
        )


# --------------------------------------------------------------------------- #
# endregion Pipelines                                                         #
# --------------------------------------------------------------------------- #
