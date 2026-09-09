# Module name: helpers/lexicon.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region docstr                                                               #
# --------------------------------------------------------------------------- #

"""
Lexical resources for OCR/text repair — the two collaborators that keep repair
DATA out of the pipeline code.

    * `RepairDictionary` — the external data: which corrupted token maps to
      which replacement, which character(s) the corruption swallowed, which
      line prefixes are legitimate and must survive untouched, plus optional
      corpus-specific regex replacements. It comes from the JSON file named in
      the pipeline's `configuration.dictionary`, deserialised by
      `helpers.parsers.lexical.RepairDictionaryParser` — no word, header or
      artifact is ever hardcoded in a pipeline.

    * `Lexicon` — the NLP side: word likelihood taken from `wordfreq` (Zipf
      frequency, 0–8) plus an optional external word list for domain terms
      (read by `helpers.parsers.lexical.WordListParser`).
      It answers the only three questions the repair actually needs:
          known(word)              — is this a real word?
          repair(left, right, ...) — how does a corrupted junction read?
          segment(token)           — how does a run-together token split back?

Install the NLP backend once (lazy-imported, so this module imports without it):

    pip install wordfreq

Dictionary schema (all keys optional except `confusions`):

    {
      "language": "en",
      "headers": ["From:", "Sent:"],
      "confusions": [
        {
          "pattern": "To:",           # what the corruption produced
          "replacement": "to",        # what it should read
          "restore": "ro",            # character(s) the corruption swallowed
          "keep_when": "^\\s*To:\\s+[A-Z@\"]",   # line-level: keep the label
          "protect": ["mail[Tt]o:"]   # never substituted
        }
      ],
      "replacements": [{"pattern": "Sendt\\b", "replacement": "Send to"}],
      "words": ["wattleflow"]
    }
"""

# --------------------------------------------------------------------------- #
# endregion docstr                                                            #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
import re
from typing import Any, Dict, Iterable, List, Optional, Pattern, Sequence, Tuple
from wattleflow.helpers.macros import TextMacros

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #

DEFAULT_LANGUAGE = "en"
# Zipf scale: 8 ≈ "the", 4 ≈ common word, 2 ≈ rare but real, 0 ≈ unseen.
DEFAULT_THRESHOLD = 2.0
DEFAULT_MAX_WORD = 20
KNOWN_SCORE = 8.0
UNKNOWN_SCORE = -10.0
# Zipf is log10(occurrences per billion words), so log10 P(word) = zipf - 9.
# Comparing hypotheses in log-probability is what makes one word beat two:
# every extra word costs ~9, which is why a plausible join wins over a split
# and why segmentation does not shatter a token into common fragments.
ZIPF_BASE = 9.0
# The only one-letter English words; every other single character is a
# segmentation artifact, not a word.
SINGLE_LETTER_WORDS = ("a", "i")

WORDFREQ_MISSING = (
    "wordfreq is required for lexicon-driven text repair. Add it manually: pip install wordfreq"
)

Words = Optional[Iterable[str]]

# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Lexicon                                                              #
# --------------------------------------------------------------------------- #


class Lexicon:
    """Word-likelihood oracle over `wordfreq` and an optional external word
    list. Scores are memoised per instance — repair calls the same fragments
    thousands of times per document."""

    __slots__ = ("_language", "_threshold", "_max_word", "_words", "_scores", "_zipf")

    def __init__(
        self,
        language: str = DEFAULT_LANGUAGE,
        threshold: float = DEFAULT_THRESHOLD,
        max_word: int = DEFAULT_MAX_WORD,
        words: Words = None,
    ) -> None:
        self._language: str = language or DEFAULT_LANGUAGE
        self._threshold: float = float(threshold)
        self._max_word: int = max(2, int(max_word))
        self._words: set = self._load(words)
        self._scores: Dict[str, float] = {}
        self._zipf = None

    # region Private
    @classmethod
    def _load(cls, words: Words) -> set:
        """Normalise the external word list — domain vocabulary wordfreq cannot
        know. Reading it from a file is `WordListParser`'s job, never this
        class's: the lexicon scores words, it does not touch the disk."""
        if not words:
            return set()

        return {str(word).strip().lower() for word in words if str(word).strip()}

    @property
    def _frequency(self):
        if self._zipf is None:
            try:
                from wordfreq import zipf_frequency
            except ImportError as e:
                raise ModuleNotFoundError(WORDFREQ_MISSING) from e
            self._zipf = zipf_frequency
        return self._zipf

    # endregion

    @property
    def language(self) -> str:
        return self._language

    @property
    def threshold(self) -> float:
        return self._threshold

    def score(self, word: str) -> float:
        """Zipf frequency of `word`, `UNKNOWN_SCORE` when the corpus has never
        seen it. Case-insensitive."""
        if not word:
            return UNKNOWN_SCORE

        key = word.lower()
        cached = self._scores.get(key)
        if cached is not None:
            return cached

        if key in self._words:
            value = KNOWN_SCORE
        else:
            value = self._frequency(key, self._language)
            if value <= 0:
                value = UNKNOWN_SCORE

        self._scores[key] = value
        return value

    def known(self, word: str) -> bool:
        return self.score(word) >= self._threshold

    def logp(self, word: str) -> float:
        """log10 P(word). An empty fragment is free, so hypotheses with a
        different number of words stay comparable."""
        return 0.0 if not word else self.score(word) - ZIPF_BASE

    def repair(self, left: str, right: str, restore: str = "", spacing: str = " ") -> Optional[str]:
        """Best hypothesis for a corrupted junction, `None` when the fragments
        as they stand already are the most likely reading.

        Competing hypotheses, scored in log-probability:
            keep    — `left` and `right` are two words (the null hypothesis)
            join    — one word: the fragments glued, optionally with one
                      swallowed `restore` character put back at the junction
            complete— two words, but the swallowed character belonged to the
                      end of `left` (the space was a real word boundary; only
                      considered when the junction actually has one)
        """
        if not left and not right:
            return None

        best = self.logp(left) + self.logp(right)
        winner: Optional[str] = None

        if left and right:
            for candidate in self._candidates(left, right, restore):
                value = self.logp(candidate)
                if value > best and self.known(candidate):
                    best, winner = value, candidate

        if left and (spacing or not right):
            for candidate in self._candidates(left, "", restore):
                value = self.logp(candidate) + self.logp(right)
                if value > best and self.known(candidate):
                    best, winner = value, f"{candidate}{spacing}{right}"

        return winner

    def _candidates(self, left: str, right: str, restore: str) -> List[str]:
        """The glued fragments plus one restored character at the junction.
        An all-caps fragment restores an upper-case character."""
        upper = left.isupper()
        candidates = [f"{left}{right}"] if right else []
        candidates += [
            f"{left}{character.upper() if upper else character}{right}" for character in restore
        ]
        return candidates

    def segment(self, token: str) -> List[str]:
        """Split a run-together token into the most likely word sequence
        (dynamic programming over word log-probabilities, so a fragment only
        survives if it pays for the extra word). Returns `[token]` when no
        segmentation scores at all."""
        size = len(token)
        if size == 0:
            return []

        # best[i] = (score, pieces) for token[:i]
        best: List[Tuple[float, List[str]]] = [(float("-inf"), []) for _ in range(size + 1)]
        best[0] = (0.0, [])

        for i in range(1, size + 1):
            for j in range(max(0, i - self._max_word), i):
                score, pieces = best[j]
                if score == float("-inf"):
                    continue

                piece = token[j:i]
                if len(piece) == 1 and piece.lower() not in SINGLE_LETTER_WORDS:
                    continue

                value = score + self.logp(piece)
                if value > best[i][0]:
                    best[i] = (value, pieces + [piece])

        return best[size][1] or [token]


# --------------------------------------------------------------------------- #
# endregion Lexicon                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Dictionary                                                           #
# --------------------------------------------------------------------------- #


class ConfusionRule:
    """One corruption the upstream transformation introduced: `pattern` reads
    where `replacement` belongs, and `restore` lists the character(s) the
    substitution swallowed at the junction."""

    __slots__ = ("pattern", "replacement", "restore", "keep_when", "protect")

    def __init__(
        self,
        pattern: str,
        replacement: str,
        restore: str = "",
        keep_when: Optional[str] = None,
        protect: Sequence[str] = (),
    ) -> None:
        if not pattern:
            raise ValueError("Confusion rule requires a non-empty 'pattern'.")

        self.pattern: str = pattern
        self.replacement: str = replacement
        self.restore: str = restore or ""
        self.keep_when: Optional[Pattern] = re.compile(keep_when) if keep_when else None
        self.protect: List[Pattern] = [re.compile(item) for item in protect]

    def __repr__(self) -> str:
        return f"ConfusionRule({self.pattern!r} -> {self.replacement!r})"


class RepairDictionary:
    """External repair data for the text pipelines. Everything the repair knows
    about a specific corpus lives in the JSON file, never in the code.

    `KEYS` declares the schema; reading and validating a file against it is
    `helpers.parsers.lexical.RepairDictionaryParser`'s job.
    """

    KEYS = ("language", "headers", "confusions", "replacements", "words")
    __slots__ = ("_language", "_headers", "_confusions", "_replacements", "_words", "_macros")

    def __init__(
        self,
        language: str = DEFAULT_LANGUAGE,
        headers: Sequence[str] = (),
        confusions: Sequence[Dict[str, Any]] = (),
        replacements: Sequence[Dict[str, Any]] = (),
        words: Sequence[str] = (),
    ) -> None:
        self._language: str = language or DEFAULT_LANGUAGE
        self._headers: List[str] = [str(header) for header in headers]
        self._confusions: List[ConfusionRule] = [ConfusionRule(**rule) for rule in confusions]
        self._replacements: List[Dict[str, Any]] = [dict(item) for item in replacements]
        self._words: List[str] = [str(word) for word in words]
        self._macros: Optional[TextMacros] = None

    @property
    def language(self) -> str:
        return self._language

    @property
    def confusions(self) -> List[ConfusionRule]:
        return self._confusions

    @property
    def words(self) -> List[str]:
        return self._words

    @property
    def macros(self) -> TextMacros:
        """Corpus-specific regex replacements — the escape hatch for artifacts
        no lexicon can infer (e.g. a lost word boundary in a proper name)."""
        if self._macros is None:
            self._macros = TextMacros(self._replacements or [])
        return self._macros

    def prefix(self, line: str) -> int:
        """Number of leading characters that must survive untouched: the label
        of a legitimate header line. Everything after it is still repaired."""
        stripped = line.lstrip()
        offset = len(line) - len(stripped)

        for header in self._headers:
            if stripped.startswith(header):
                return offset + len(header)

        for rule in self._confusions:
            if rule.keep_when and rule.keep_when.match(line):
                index = line.find(rule.pattern)
                if index >= 0:
                    return index + len(rule.pattern)

        return 0


# --------------------------------------------------------------------------- #
# endregion Dictionary                                                        #
# --------------------------------------------------------------------------- #

__all__ = ["ConfusionRule", "Lexicon", "RepairDictionary"]
