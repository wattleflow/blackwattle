# Module name: helpers/parsers/lexical.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
Lexical-resource parsers — read-side deserialisers for the data the text-repair
pipelines run on: the repair dictionary (JSON -> `RepairDictionary`) and an
external word list (one word per line -> `list[str]`).

Same contract as every other parser: open stream -> domain object, so no
pipeline and no helper decodes these files itself. Like `OcrParser`, they are
not registered in `ParserFactory`: a repair dictionary is configuration, not a
document travelling the driver read path, so consumers open the file and
instantiate them directly.
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import json
from typing import Any, BinaryIO, List
from wattleflow.concrete.serialisation import GenericParser
from wattleflow.helpers.lexicon import RepairDictionary
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["RepairDictionaryParser", "WordListParser"]

# --------------------------------------------------------------------------- #
# region Parsers                                                              #
# --------------------------------------------------------------------------- #


class RepairDictionaryParser(GenericParser):
    """Deserialise a repair dictionary into a `RepairDictionary`.

    The class declares the schema (`RepairDictionary.KEYS`); this parser
    enforces it against the payload.
    """

    def deserialise(self, reader: BinaryIO, **opts: Any) -> RepairDictionary:
        data = json.loads(self.decode(reader, **opts))
        if not isinstance(data, dict):
            raise ValueError("Repair dictionary must be a JSON object")

        # `_about` is the repo-wide convention for a comment block in JSON data.
        unknown = set(data) - set(RepairDictionary.KEYS) - {"_about"}
        if unknown:
            raise ValueError(f"Unknown keys {sorted(unknown)!r} in repair dictionary")

        return RepairDictionary(**{key: data[key] for key in RepairDictionary.KEYS if key in data})


class WordListParser(GenericParser):
    """Deserialise a word list: one word per line, `#` starts a comment."""

    def deserialise(self, reader: BinaryIO, **opts: Any) -> List[str]:
        lines = self.decode(reader, **opts).splitlines()
        return [word.strip() for word in lines if word.strip() and not word.strip().startswith("#")]


# --------------------------------------------------------------------------- #
# endregion Parsers                                                           #
# --------------------------------------------------------------------------- #
