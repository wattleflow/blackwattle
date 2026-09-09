# Module name: pipelines/nlp/entities_en.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# English NER pipelines: spaCy, Stanza, Flair, DeBERTa-v3 large, GLiNER.      #
# Install (per backend, only what you use):                                   #
#   pip install spacy && python -m spacy download en_core_web_trf            #
#   pip install stanza && python -c "import stanza; stanza.download('en')"   #
#   pip install flair                                                         #
#   pip install transformers torch                                            #
#   pip install gliner                                                        #
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
class PipelineSpacyEntitiesEN(GenericPipeline):
    """
    English NER via spaCy.

    Processor config (with defaults):
        spacy_model:    str   = "en_core_web_trf"   # or en_core_web_lg / _md / _sm
        spacy_labels:   tuple = ("PERSON","ORG","GPE","LOC","DATE","MONEY","NORP")
        spacy_disable:  list  = []
        spacy_exclude:  list  = []
    """

    _DEFAULT_LABELS: Tuple[str, ...] = (
        "PERSON",
        "ORG",
        "GPE",
        "LOC",
        "DATE",
        "MONEY",
        "NORP",
        "EMAIL",
        "TELEPHONE",
    )

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
            raise RuntimeError("PipelineSpacyEntitiesEN requires spacy") from e

        model = getattr(processor, "spacy_model", "en_core_web_trf")
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
            label = f"ENTITY{counter}"
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


class PipelineStanzaEntitiesEN(GenericPipeline):
    """
    English NER via Stanza.

    Processor config (with defaults):
        stanza_lang:       str  = "en"
        stanza_processors: str  = "tokenize,ner"
        stanza_use_gpu:    bool = False
        stanza_package:    str  = "default"          # or "ontonotes" for 18 types
        stanza_dir:        str | None = None
        stanza_labels:     tuple | None = None       # None = accept all
    """

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> None:

        document: FileDocument = facade.request()
        content: str = document.content
        Attribute.evaluate(caller=self, target=content, expected_type=str)

        if not content.strip():
            self.warning(msg=Event.Transform.name, step=Event.Check.name, error="Content is empty!")
            return

        try:
            import stanza
        except ImportError as e:
            raise RuntimeError("PipelineStanzaEntitiesEN requires stanza") from e

        lang = getattr(processor, "stanza_lang", "en")
        procs = getattr(processor, "stanza_processors", "tokenize,ner")
        use_gpu = bool(getattr(processor, "stanza_use_gpu", False))
        package = getattr(processor, "stanza_package", "default")
        model_dir = getattr(processor, "stanza_dir", None)
        labels = getattr(processor, "stanza_labels", None)
        labels = tuple(labels) if labels else None

        kw: Dict[str, Any] = {
            "lang": lang,
            "processors": procs,
            "use_gpu": use_gpu,
            "package": package,
        }
        if model_dir:
            kw["dir"] = model_dir

        try:
            nlp = stanza.Pipeline(**kw)
        except Exception as e:
            self.debug(msg=Event.Transform.name, step=Event.Failed.name, error=str(e))
            raise RuntimeError(
                f"stanza model for '{lang}' not available. "
                f"Run: python -c \"import stanza; stanza.download('{lang}')\""
            ) from e

        filter_res = _filter_regexes(processor)
        doc = nlp(content)

        targets: Targets = []
        seen: Dict[str, str] = {}
        counter = 0
        for ent in getattr(doc, "ents", []) or []:
            ent_type = getattr(ent, "type", None) or getattr(ent, "label_", None)
            if labels and ent_type not in labels:
                continue
            text = (getattr(ent, "text", "") or "").strip()
            if not text or text in seen:
                continue
            if any(r.search(text) for r in filter_res):
                continue
            counter += 1
            label = f"ENTITY{counter}"
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
            backend="stanza",
        )


class PipelineFlairEntitiesEN(GenericPipeline):
    """
    English NER via Flair.

    Processor config (with defaults):
        flair_model:      str  = "flair/ner-english-large"   # or "ner-english-fast"
        flair_use_gpu:    bool = False
        flair_mini_batch: int  = 32
        flair_labels:     tuple | None = None
        flair_score_min:  float = 0.0
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
            raise RuntimeError("PipelineFlairEntitiesEN requires flair") from e

        model_name = getattr(processor, "flair_model", "flair/ner-english-large")
        use_gpu = bool(getattr(processor, "flair_use_gpu", False))
        mini_batch = int(getattr(processor, "flair_mini_batch", 32))
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
            label = f"ENTITY{counter}"
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


class PipelineDebertaEntitiesEN(GenericPipeline):
    """
    English NER via DeBERTa-v3 large (HuggingFace transformers).

    Processor config (with defaults):
        deberta_model:        str  = "tner/deberta-v3-large-ontonotes5"
        deberta_use_gpu:      bool = False
        deberta_aggregation:  str  = "simple"        # simple|first|average|max|none
        deberta_max_length:   int  = 512
        deberta_stride:       int  = 64              # for long-text chunking
        deberta_labels:       tuple | None = None
        deberta_score_min:    float = 0.0
    """

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> None:

        document: FileDocument = facade.request()
        content: str = document.content
        Attribute.evaluate(caller=self, target=content, expected_type=str)

        if not content.strip():
            self.warning(msg=Event.Transform.name, step=Event.Check.name, error="Content is empty!")
            return

        try:
            from transformers import AutoTokenizer, AutoModelForTokenClassification, pipeline
        except ImportError as e:
            raise RuntimeError("PipelineDebertaEntitiesEN requires transformers + torch") from e

        model_name = getattr(processor, "deberta_model", "tner/deberta-v3-large-ontonotes5")
        use_gpu = bool(getattr(processor, "deberta_use_gpu", False))
        aggregation = getattr(processor, "deberta_aggregation", "simple")
        max_length = int(getattr(processor, "deberta_max_length", 512))
        stride = int(getattr(processor, "deberta_stride", 64))
        labels = getattr(processor, "deberta_labels", None)
        labels = tuple(labels) if labels else None
        score_min = float(getattr(processor, "deberta_score_min", 0.0))
        device = 0 if use_gpu else -1

        try:
            tokenizer = AutoTokenizer.from_pretrained(model_name)
            model = AutoModelForTokenClassification.from_pretrained(model_name)
            ner = pipeline(
                "token-classification",
                model=model,
                tokenizer=tokenizer,
                aggregation_strategy=aggregation,
                device=device,
            )
        except Exception as e:
            self.debug(msg=Event.Transform.name, step=Event.Failed.name, error=str(e))
            raise RuntimeError(f"DeBERTa model '{model_name}' could not be loaded") from e

        filter_res = _filter_regexes(processor)

        chunks: List[Tuple[int, str]] = []
        if len(content) > max_length * 4:
            step = (max_length - stride) * 4
            for offset in range(0, len(content), step):
                chunks.append((offset, content[offset : offset + max_length * 4]))
        else:
            chunks.append((0, content))

        targets: Targets = []
        seen: Dict[str, str] = {}
        counter = 0
        for _offset, chunk in chunks:
            try:
                results = ner(chunk)
            except Exception as e:
                self.warning(
                    msg=Event.Transform.name,
                    step=Event.Check.name,
                    error=f"deberta chunk failed: {e}",
                )
                continue
            for r in results:
                tag = r.get("entity_group") or r.get("entity")
                if labels and tag not in labels:
                    continue
                if float(r.get("score", 0.0)) < score_min:
                    continue
                text = (r.get("word") or "").strip()
                if not text or text in seen:
                    continue
                if any(rx.search(text) for rx in filter_res):
                    continue
                counter += 1
                label = f"ENTITY{counter}"
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
            backend="deberta-v3",
        )


class PipelineGlinerEntitiesEN(GenericPipeline):
    """
    English NER via GLiNER (zero-shot, custom label sets, multilingual model).

    Processor config (with defaults):
        gliner_model:      str  = "urchade/gliner_multi-v2.1"
        gliner_labels:     list = ["person","organization","location","date",
                                   "money","email","phone number"]
        gliner_use_gpu:    bool = False
        gliner_threshold:  float = 0.5
        gliner_flat_ner:   bool = True               # disallow nested entities
        gliner_multi_label: bool = False
    """

    _DEFAULT_LABELS: Tuple[str, ...] = (
        "person",
        "organization",
        "location",
        "date",
        "money",
        "email",
        "phone number",
    )

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> None:

        document: FileDocument = facade.request()
        content: str = document.content
        Attribute.evaluate(caller=self, target=content, expected_type=str)

        if not content.strip():
            self.warning(msg=Event.Transform.name, step=Event.Check.name, error="Content is empty!")
            return

        try:
            from gliner import GLiNER
        except ImportError as e:
            raise RuntimeError("PipelineGlinerEntitiesEN requires gliner") from e

        model_name = getattr(processor, "gliner_model", "urchade/gliner_multi-v2.1")
        labels = list(getattr(processor, "gliner_labels", self._DEFAULT_LABELS))
        use_gpu = bool(getattr(processor, "gliner_use_gpu", False))
        threshold = float(getattr(processor, "gliner_threshold", 0.5))
        flat_ner = bool(getattr(processor, "gliner_flat_ner", True))
        multi_label = bool(getattr(processor, "gliner_multi_label", False))

        try:
            model = GLiNER.from_pretrained(model_name)
            if use_gpu:
                try:
                    import torch

                    if torch.cuda.is_available():
                        model = model.to("cuda")
                except Exception:
                    pass
        except Exception as e:
            self.debug(msg=Event.Transform.name, step=Event.Failed.name, error=str(e))
            raise RuntimeError(f"GLiNER model '{model_name}' could not be loaded") from e

        filter_res = _filter_regexes(processor)

        try:
            entities = model.predict_entities(
                content,
                labels,
                threshold=threshold,
                flat_ner=flat_ner,
                multi_label=multi_label,
            )
        except TypeError:
            entities = model.predict_entities(content, labels, threshold=threshold)

        targets: Targets = []
        seen: Dict[str, str] = {}
        counter = 0
        for ent in entities:
            text = (ent.get("text") or "").strip()
            tag = ent.get("label")
            if not text or text in seen:
                continue
            if any(rx.search(text) for rx in filter_res):
                continue
            counter += 1
            label = f"ENTITY{counter}"
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
            backend="gliner",
        )


# --------------------------------------------------------------------------- #
# endregion Pipelines                                                         #
# --------------------------------------------------------------------------- #
