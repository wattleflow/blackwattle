# Module name: strategies/documents/digest.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from typing import Any
from wattleflow.core import IWattleflow
from wattleflow.concrete import StrategyGenerate
from wattleflow.concrete.exception import StrategyException
from wattleflow.enums.event import Event
from wattleflow.helpers.digest import FileDigest
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["GenerateFileDigest"]

# --------------------------------------------------------------------------- #
# region Strategy                                                             #
# --------------------------------------------------------------------------- #


class GenerateFileDigest(StrategyGenerate):
    """Generate a content DIGEST (protective hash) for a file.

    The `source` (path, bytes or a binary stream) is hashed by CONTENT — never by
    path — so the digest is stable across copies and renames. Returns a labelled
    digest (`"sha256:<hex>"`) for a caller to stamp onto the document so integrity
    travels with the evidence. `algorithm` overrides the default (sha256).
    """

    def execute(self, caller: IWattleflow, **kwargs: Any) -> str | None:
        self.debug(msg=Event.Generate.name, step=Event.Started.name, caller=caller)
        source = kwargs.get("source") or kwargs.get("filename")
        if not source:
            self.warning(
                msg=Event.Generate.name, step=Event.Check.name, reason="no source for digest"
            )
            return None
        algorithm = kwargs.get("algorithm") or FileDigest.DEFAULT_ALGORITHM
        try:
            digest = FileDigest.labelled(source, algorithm=algorithm)
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Generate.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e

        self.debug(msg=Event.Generate.name, step=Event.Completed.name, digest=digest)
        return digest


# --------------------------------------------------------------------------- #
# endregion Strategy                                                          #
# --------------------------------------------------------------------------- #
