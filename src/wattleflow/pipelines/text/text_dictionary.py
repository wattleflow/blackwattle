# Module name: pipelines/text/text_dictionary.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region docstr                                                               #
# --------------------------------------------------------------------------- #

"""
Repair pipelines for text mangled by an upstream OCR/mail transformation.

    PipelineTextRepair      — undoes a token-level corruption: the scan read a
                              letter sequence as another token ("cer" -> "Cc:",
                              "tor" -> "To:"), so words are both broken in two
                              AND missing the swallowed character.
    PipelineFixStickyWords  — splits run-together tokens ("certificateof").

Neither pipeline carries repair data. WHAT was corrupted comes from an external
JSON dictionary (`configuration.dictionary`, see helpers/lexicon.py), WHICH
candidate is the right word is decided by the lexicon (wordfreq Zipf
frequencies) — no word lists, header names or artifact strings in the code.

    pipelines:
      - name: repair
        type: PipelineTextRepair
        configuration:
          dictionary: "dictionaries/ocr-repair.en.json"
          language: en
          threshold: 2.0
      - name: sticky
        type: PipelineFixStickyWords
        configuration:
          language: en
          min_length: 8

Install the NLP backend once:  pip install wordfreq
"""

# --------------------------------------------------------------------------- #
# endregion docstr                                                            #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
import re
from pathlib import Path
from typing import Any, Iterable, List, Optional, Tuple, Union
from wattleflow.core import IProcessor, ITarget
from wattleflow.concrete import GenericPipeline
from wattleflow.concrete.exception import PipelineException
from wattleflow.concrete.serialisation import ParserError
from wattleflow.enums.event import Event
from wattleflow.documents.file import FileDocument
from wattleflow.concrete.helpers import Attribute
from wattleflow.helpers.lexicon import (
    DEFAULT_LANGUAGE,
    DEFAULT_MAX_WORD,
    DEFAULT_THRESHOLD,
    Lexicon,
    RepairDictionary,
)
from wattleflow.helpers.parsers.lexical import RepairDictionaryParser, WordListParser

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #

# Control characters cannot occur in extracted text, so they are safe markers.
# JUNCTION marks where a substitution happened (rule index in between), GUARD
# parks a protected match while the substitutions run.
JUNCTION = "\x00"
GUARD = "\x01"

_JUNCTION_RE = re.compile(r"(\w*)\x00(\d+)\x00([ \t]*)(\w*)")
_GUARD_RE = re.compile(r"\x01(\d+)\x01")
# Letters only: digits and punctuation are never part of a sticky word.
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

DEFAULT_MIN_LENGTH = 8

# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Globals                                                              #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# endregion Globals                                                           #
# --------------------------------------------------------------------------- #


class DictionaryHelper:
    @classmethod
    def word_list(cls, source: Union[str, Path, Iterable[str], None]) -> List[str]:
        """Resolve the `words` configuration: a path is deserialised by the parser
        family, an inline list is taken as it stands."""
        if not source:
            return []
        if isinstance(source, (str, Path)):
            return WordListParser().parse(path=source)
        return [str(word) for word in source]


# --------------------------------------------------------------------------- #
# region Pipelines                                                            #
# --------------------------------------------------------------------------- #


class PipelineTextRepairDictionary(GenericPipeline):
    """Undo a token-level OCR corruption described by an external dictionary.

    Per line: the label of a legitimate header survives untouched, protected
    patterns are parked, every corrupted token is substituted and the junction
    it leaves behind is closed by the lexicon — the plain join or one restored
    character, whichever spells a real word. Fragments that stay unknown are
    left exactly as they were.

    Config keys (YAML `pipelines[].configuration`):
        dictionary — path to the repair dictionary (JSON, mandatory)
        language   — lexicon language (default: from the dictionary, else "en")
        threshold  — Zipf score at which a candidate counts as a real word
        max_word   — longest fragment the lexicon will consider
        words      — optional external word list (file or list) for domain terms
    """

    ALLOWED = ["dictionary", "language", "threshold", "max_word", "words"]

    # region Construction
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        source = kwargs.get("dictionary")
        if not source:
            raise PipelineException(
                caller=self,
                error="Mandatory 'dictionary' (repair dictionary path) is missing.",
            )

        try:
            self._dictionary: RepairDictionary = RepairDictionaryParser().parse(path=source)
            words = DictionaryHelper.word_list(kwargs.get("words") or self._dictionary.words)
        except (FileNotFoundError, ParserError, ValueError) as e:
            # GenericParser wraps a missing file or a malformed payload into
            # ParserError, so that is now the expected shape here.
            self.debug(msg=Event.Constructor.name, step=Event.Failed.name, error=str(e))
            raise PipelineException(caller=self, error=f"{source}: {e}") from e

        if not self._dictionary.confusions:
            raise PipelineException(
                caller=self,
                error=f"Repair dictionary {source!r} declares no 'confusions'.",
            )

        self._lexicon: Lexicon = Lexicon(
            language=kwargs.get("language") or self._dictionary.language,
            threshold=float(kwargs.get("threshold", DEFAULT_THRESHOLD)),
            max_word=int(kwargs.get("max_word", DEFAULT_MAX_WORD)),
            words=words,
        )

    # endregion Construction

    # region Private
    def _substitute(self, text: str) -> Tuple[str, int]:
        """Replace every corrupted token with what it should read, marking the
        junction so the rejoin step knows where a word was broken."""
        guarded: List[str] = []

        def _park(match: re.Match) -> str:
            guarded.append(match.group(0))
            return f"{GUARD}{len(guarded) - 1}{GUARD}"

        for rule in self._dictionary.confusions:
            for pattern in rule.protect:
                text = pattern.sub(_park, text)

        substitutions = 0
        for index, rule in enumerate(self._dictionary.confusions):
            parts = text.split(rule.pattern)
            if len(parts) == 1:
                continue
            substitutions += len(parts) - 1
            text = f"{rule.replacement}{JUNCTION}{index}{JUNCTION}".join(parts)

        if guarded:
            text = _GUARD_RE.sub(lambda m: guarded[int(m.group(1))], text)

        return text, substitutions

    def _rejoin(self, text: str) -> Tuple[str, int]:
        """Close every junction the substitution left behind. The lexicon
        decides whether the fragments are one broken word, one word plus a
        swallowed character, or two words that were always two words — in the
        last case the line keeps exactly the spacing it had."""
        joined = 0

        def _repair(match: re.Match) -> str:
            nonlocal joined

            left, index, spacing, right = (
                match.group(1),
                int(match.group(2)),
                match.group(3),
                match.group(4),
            )
            rule = self._dictionary.confusions[index]

            candidate = self._lexicon.repair(left, right, rule.restore, spacing)
            if candidate is None:
                return f"{left}{spacing}{right}"

            joined += 1
            return candidate

        return _JUNCTION_RE.sub(_repair, text), joined

    def _repair(self, content: str) -> Tuple[str, int, int]:
        substitutions = 0
        joins = 0
        repaired: List[str] = []

        for line in content.split("\n"):
            prefix = self._dictionary.prefix(line)
            head, rest = line[:prefix], line[prefix:]

            rest, substituted = self._substitute(rest)
            rest, rejoined = self._rejoin(rest)

            substitutions += substituted
            joins += rejoined
            repaired.append(f"{head}{rest}")

        text = "\n".join(repaired)

        macros = self._dictionary.macros
        if macros.count:
            text = macros.run(text)

        return text, substitutions, joins

    # endregion Private

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> None:
        document: FileDocument = facade.request()
        content: str = document.content
        Attribute.evaluate(caller=self, target=content, expected_type=str)

        if not content.strip():
            self.warning(msg=Event.Transform.name, step=Event.Check.name, error="Content is empty!")
            return

        text, substitutions, joins = self._repair(content)
        changed = text != content

        if changed:
            document.update_content(text)
            document.update_metadata("repair_substitutions", substitutions)
            document.update_metadata("repair_joins", joins)

        uid = processor.blackboard.write(
            facade=facade,
            processor=processor,
            pipeline=self,
        )

        self.debug(
            msg=Event.Transform.name,
            uid=uid,
            changed=changed,
            substitutions=substitutions,
            joins=joins,
        )


class PipelineTextRepairStickyWords(GenericPipeline):
    """Split run-together tokens ("certificateof" -> "certificate of").

    Only tokens the lexicon does not recognise are segmented, and only when
    every piece of the segmentation is a real word — so legitimate long words
    and unknown proper names are left alone. Whitespace, punctuation and line
    structure are preserved: the document keeps its layout.

    Config keys (YAML `pipelines[].configuration`):
        language   — lexicon language (default: "en")
        threshold  — Zipf score at which a piece counts as a real word
        max_word   — longest piece the segmentation will consider
        min_length — shortest token worth segmenting (default: 8)
        words      — optional external word list (file or list) for domain terms
    """

    ALLOWED = ["language", "threshold", "max_word", "min_length", "words"]

    # region Construction
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self._min_length: int = max(2, int(kwargs.get("min_length", DEFAULT_MIN_LENGTH)))

        try:
            words = DictionaryHelper.word_list(kwargs.get("words"))
        except (FileNotFoundError, ValueError) as e:
            self.debug(msg=Event.Constructor.name, step=Event.Failed.name, error=str(e))
            raise PipelineException(caller=self, error=str(e)) from e

        self._lexicon: Lexicon = Lexicon(
            language=kwargs.get("language") or DEFAULT_LANGUAGE,
            threshold=float(kwargs.get("threshold", DEFAULT_THRESHOLD)),
            max_word=int(kwargs.get("max_word", DEFAULT_MAX_WORD)),
            words=words,
        )

    # endregion Construction

    # region Private
    def _split(self, token: str) -> Optional[str]:
        if len(token) < self._min_length or self._lexicon.known(token):
            return None

        pieces = self._lexicon.segment(token)
        if len(pieces) < 2 or not all(self._lexicon.known(piece) for piece in pieces):
            return None

        return " ".join(pieces)

    # endregion Private

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> None:
        document: FileDocument = facade.request()
        content: str = document.content
        Attribute.evaluate(caller=self, target=content, expected_type=str)

        if not content.strip():
            self.warning(msg=Event.Transform.name, step=Event.Check.name, error="Content is empty!")
            return

        splits = 0

        def _unstick(match: re.Match) -> str:
            nonlocal splits

            token = match.group(0)
            segmented = self._split(token)
            if segmented is None:
                return token

            splits += 1
            return segmented

        text = _WORD_RE.sub(_unstick, content)

        if splits:
            document.update_content(text)
            document.update_metadata("sticky_splits", splits)

        uid = processor.blackboard.write(
            facade=facade,
            processor=processor,
            pipeline=self,
        )

        self.debug(msg=Event.Transform.name, uid=uid, splits=splits)


# --------------------------------------------------------------------------- #
# endregion Pipelines                                                         #
# --------------------------------------------------------------------------- #

__all__ = ["PipelineTextRepairDictionary", "PipelineTextRepairStickyWords"]
