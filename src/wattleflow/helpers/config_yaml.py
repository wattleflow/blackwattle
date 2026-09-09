# Module name: helpers/config_yaml.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
from pathlib import Path
from typing import final, Any
from wattleflow.helpers.config import Config
from wattleflow.helpers.yaml import yaml  # type: ignore[assignment]

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["YAMLConfig"]

# --------------------------------------------------------------------------- #
# region Classes                                                              #
# --------------------------------------------------------------------------- #


# v0.0.20 (DR-WFL-012 t.1/t.6): YAML is a third-party-backed format, so its home
# is this distribution; the search contract is inherited from the clean core.
@final
class YAMLConfig(Config):
    FORMAT = "YAML"
    # YAML 1.2 fixes the encoding; the platform default must not decide it.
    ENCODING = "utf-8"
    ERRORS = (yaml.YAMLError, UnicodeDecodeError)

    __slots__ = ("_strict",)

    def __init__(self, config_file: str | Path, **kwargs) -> None:
        # Set before the base constructor: it loads the document, and loading is
        # what resolves the references.
        self._strict: bool = kwargs.pop("strict", True)
        super().__init__(config_file, **kwargs)

    def _parse(self, text: str) -> Any:
        """Parse the document and resolve its secret references.

        Per-file `${dotenv:...}` overrides plus `${env:VAR}` from os.environ; the
        `.env` section is keyed by this file's name and discovery walks up from
        its directory. Left unresolved, the tokens travel on as literal text and
        reach drivers as paths and credentials.
        """
        # Local import: `config_adapter` imports this module for its own parsing.
        from wattleflow.helpers.config_adapter import EnvVarResolver, SecretResolverChain
        from wattleflow.helpers.dotenv import DotEnvResolver, find_env_file

        path = Path(self.config_file)
        chain = (
            SecretResolverChain()
            .add(DotEnvResolver(find_env_file(path), section=path.name))
            .add(EnvVarResolver())
        )
        return chain.resolve_all(yaml.safe_load(text), self._strict)


# --------------------------------------------------------------------------- #
# endregion Classes                                                           #
# --------------------------------------------------------------------------- #
