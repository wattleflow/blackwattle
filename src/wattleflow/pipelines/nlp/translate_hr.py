# Module name: pipelines/nlp/translate_hr.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region docstr                                                               #
# --------------------------------------------------------------------------- #

"""
PipelineTranslateEnHr — translates a FileDocument's content from English to
Croatian using a local HuggingFace transformers model (no external API).

Supported backends (lazy-imported; the module imports cleanly without them):
    * opus-mt   — Helsinki-NLP/opus-mt-en-hr (default).
                  ~300 MB MarianMT model dedicated to EN→HR. Fast, decent.
    * nllb      — facebook/nllb-200-distilled-600M.
                  Multilingual; uses src_lang=eng_Latn, tgt_lang=hrv_Latn.
                  Best quality, heavier (~1.3 GB).
    * m2m100    — facebook/m2m100_418M.
                  Multilingual fallback; src_lang=en, tgt_lang=hr.

Install once (choose what you need):

    pip install transformers torch sentencepiece sacremoses
    # For NLLB/M2M100 also: protobuf

The first call downloads the model into the HuggingFace cache (HF_HOME or
~/.cache/huggingface). Set `cache_dir` in YAML to pin a project-local cache.
"""
# --------------------------------------------------------------------------- #
# endregion docstr                                                            #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
import re
from typing import Any, List, Optional, Tuple

from wattleflow.core import IProcessor, ITarget
from wattleflow.concrete import GenericPipeline
from wattleflow.concrete.exception import PipelineException
from wattleflow.enums.event import Event
from wattleflow.documents.file import FileDocument
from wattleflow.concrete.helpers import Attribute

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #

DEFAULT_BACKEND = "opus-mt"
SUPPORTED_BACKENDS = ("opus-mt", "nllb", "m2m100")

DEFAULT_MODELS = {
    "opus-mt": "Helsinki-NLP/opus-mt-en-hr",
    "nllb": "facebook/nllb-200-distilled-600M",
    "m2m100": "facebook/m2m100_418M",
}

DEFAULT_DEVICE = "auto"
DEFAULT_BATCH_SIZE = 8
DEFAULT_MAX_LENGTH = 512
DEFAULT_CHUNK_CHARS = 1800

# Match sentence-ish boundaries: ., !, ? followed by whitespace, or a
# blank line. Used by the chunker so we don't split mid-sentence.
_SENT_SPLIT_RE = re.compile(r"(?<=[\.\!\?])\s+|\n{2,}")

# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Pipelines                                                            #
# --------------------------------------------------------------------------- #


class PipelineTranslateEnHr(GenericPipeline):
    """Translate `document.content` from English to Croatian in place.

    The translated text overwrites `document.content`. When
    `preserve_original=True` (default) the source English text is stored in
    `document.metadata["original_content_en"]` so downstream pipelines can
    still reach it.

    Config keys (YAML `pipelines[].configuration`):
        backend            — "opus-mt" | "nllb" | "m2m100"  (default: opus-mt)
        model_name         — explicit HF model id (overrides backend default)
        device             — "cpu" | "cuda" | "auto" (default: auto)
        batch_size         — int, number of chunks per generate() call
        max_length         — int, generation cap per chunk
        chunk_chars        — approximate max chars per chunk; long content is
                             split on sentence/blank-line boundaries.
        cache_dir          — optional HF cache directory
        preserve_original  — bool; copy English source to metadata before
                             overwriting content (default: True)
    """

    ALLOWED = [
        "backend",
        "model_name",
        "device",
        "batch_size",
        "max_length",
        "chunk_chars",
        "cache_dir",
        "preserve_original",
    ]

    # ----------------------------------------------------------------- #
    # region Construction
    # ----------------------------------------------------------------- #

    def __init__(self, **kwargs: Any) -> None:

        backend = kwargs.pop("backend", DEFAULT_BACKEND)
        if backend not in SUPPORTED_BACKENDS:
            raise PipelineException(
                caller=self,
                error=f"Unsupported backend {backend!r}. Expected one of {SUPPORTED_BACKENDS}",
            )

        model_name = kwargs.pop("model_name", None) or DEFAULT_MODELS[backend]

        super().__init__(
            backend=backend,
            model_name=model_name,
            device=kwargs.pop("device", DEFAULT_DEVICE),
            batch_size=int(kwargs.pop("batch_size", DEFAULT_BATCH_SIZE)),
            max_length=int(kwargs.pop("max_length", DEFAULT_MAX_LENGTH)),
            chunk_chars=int(kwargs.pop("chunk_chars", DEFAULT_CHUNK_CHARS)),
            cache_dir=kwargs.pop("cache_dir", None),
            preserve_original=bool(kwargs.pop("preserve_original", True)),
            **kwargs,
        )

        self._tokenizer = None
        self._model = None
        self._resolved_device: Optional[str] = None

    # endregion Construction

    # ----------------------------------------------------------------- #
    # region Model loading
    # ----------------------------------------------------------------- #

    def _resolve_device(self) -> str:
        if self._resolved_device:
            return self._resolved_device
        requested = (self.device or DEFAULT_DEVICE).lower()
        if requested == "auto":
            try:
                import torch  # noqa: WPS433 — lazy

                requested = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                requested = "cpu"
        self._resolved_device = requested
        return requested

    def _load(self) -> None:
        if self._model is not None and self._tokenizer is not None:
            return

        try:
            from transformers import (  # noqa: WPS433 — lazy
                AutoModelForSeq2SeqLM,
                AutoTokenizer,
            )
        except ImportError as e:
            raise PipelineException(
                caller=self,
                error=(
                    f"transformers is required for {self.name}. "
                    "Install with: pip install transformers torch sentencepiece sacremoses"
                ),
            ) from e

        device = self._resolve_device()
        cache_dir = self.cache_dir or None

        self.debug(
            msg=Event.Load.name,
            step=Event.Started.name,
            backend=self.backend,
            model=self.model_name,
            device=device,
        )

        try:
            tokenizer = AutoTokenizer.from_pretrained(self.model_name, cache_dir=cache_dir)
            model = AutoModelForSeq2SeqLM.from_pretrained(self.model_name, cache_dir=cache_dir)
            model.eval()
            if device == "cuda":
                model = model.to("cuda")
        except Exception as e:
            self.debug(msg=Event.Load.name, step=Event.Failed.name, error=str(e))
            raise PipelineException(
                caller=self,
                error=f"Failed to load model {self.model_name!r}: {e}",
            ) from e

        # Backend-specific language tagging — set once at load time so we
        # don't pay the cost per call.
        if self.backend == "nllb":
            tokenizer.src_lang = "eng_Latn"
        elif self.backend == "m2m100":
            tokenizer.src_lang = "en"

        self._tokenizer = tokenizer
        self._model = model

        self.debug(
            msg=Event.Load.name,
            backend=self.backend,
            device=device,
        )

    # endregion Model loading

    # ----------------------------------------------------------------- #
    # region Chunking
    # ----------------------------------------------------------------- #

    def _chunk(self, text: str) -> List[str]:
        """Split text on sentence/paragraph boundaries so each chunk fits
        roughly within `chunk_chars`. Avoids slicing mid-sentence which
        would degrade translation quality."""
        cap = max(int(self.chunk_chars), 200)
        if len(text) <= cap:
            return [text]

        sentences = [s for s in _SENT_SPLIT_RE.split(text) if s and s.strip()]
        chunks: List[str] = []
        buffer: List[str] = []
        buffer_len = 0
        for sentence in sentences:
            sentence_len = len(sentence)
            if buffer and buffer_len + sentence_len + 1 > cap:
                chunks.append(" ".join(buffer))
                buffer = [sentence]
                buffer_len = sentence_len
            else:
                buffer.append(sentence)
                buffer_len += sentence_len + 1

        if buffer:
            chunks.append(" ".join(buffer))
        return chunks

    # endregion Chunking

    # ----------------------------------------------------------------- #
    # region Translation
    # ----------------------------------------------------------------- #

    def _generate_kwargs(self) -> dict:
        kwargs: dict = {"max_length": self.max_length}
        if self.backend == "nllb":
            forced = self._tokenizer.convert_tokens_to_ids("hrv_Latn")
            kwargs["forced_bos_token_id"] = forced
        elif self.backend == "m2m100":
            kwargs["forced_bos_token_id"] = self._tokenizer.get_lang_id("hr")
        return kwargs

    def _translate_batch(self, chunks: List[str]) -> List[str]:
        import torch  # noqa: WPS433 — lazy

        device = self._resolve_device()
        tokenizer = self._tokenizer
        model = self._model
        gen_kwargs = self._generate_kwargs()

        outputs: List[str] = []
        with torch.inference_mode():
            for i in range(0, len(chunks), self.batch_size):
                batch = chunks[i : i + self.batch_size]
                encoded = tokenizer(
                    batch,
                    return_tensors="pt",
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                )
                if device == "cuda":
                    encoded = {k: v.to("cuda") for k, v in encoded.items()}

                generated = model.generate(**encoded, **gen_kwargs)
                decoded = tokenizer.batch_decode(generated, skip_special_tokens=True)
                outputs.extend(decoded)
        return outputs

    def _translate(self, text: str) -> Tuple[str, int]:
        chunks = self._chunk(text)
        translated = self._translate_batch(chunks)
        return " ".join(t.strip() for t in translated if t.strip()), len(chunks)

    # endregion Translation

    # ----------------------------------------------------------------- #
    # region Public
    # ----------------------------------------------------------------- #

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> None:

        document: FileDocument = facade.request()
        Attribute.evaluate(caller=self, target=document, expected_type=FileDocument)

        content: str = document.content or ""
        if not content.strip():
            self.warning(msg=Event.Transform.name, step=Event.Check.name, error="Content is empty!")
            return

        self._load()

        self.debug(
            msg=Event.Transform.name,
            step=Event.Started.name,
            backend=self.backend,
            model=self.model_name,
            chars=len(content),
        )

        try:
            translated, n_chunks = self._translate(content)
        except PipelineException:
            raise
        except Exception as e:
            self.debug(msg=Event.Transform.name, step=Event.Failed.name, error=str(e))
            raise PipelineException(
                caller=self,
                error=f"Translation failed: {e}",
            ) from e

        if self.preserve_original:
            document.update_metadata("original_content_en", content)

        document.update_content(translated)
        document.update_metadata("translation_backend", self.backend)
        document.update_metadata("translation_model", self.model_name)
        document.update_metadata("translation_chars", len(translated))
        document.update_metadata("translation_chunks", n_chunks)
        document.update_metadata("source_language", "en")
        document.update_metadata("target_language", "hr")

        uid = processor.blackboard.write(
            facade=facade,
            processor=processor,
            pipeline=self,
        )

        self.debug(
            msg=Event.Transform.name,
            backend=self.backend,
            uid=uid,
            chunks=n_chunks,
            chars=len(translated),
        )

    # endregion Public


# --------------------------------------------------------------------------- #
# endregion Pipelines                                                         #
# --------------------------------------------------------------------------- #
