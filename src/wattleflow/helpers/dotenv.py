# Module name: helpers/dotenv.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""Per-file `.env` overrides for workflow YAML configuration.

The `.env` is an INI document sectioned by YAML file name; dotted keys are
opaque lookup keys resolving `${dotenv:<key>}` values. Discovery walks upward
from the YAML directory, so one `.env` may serve a whole project.

    [03_pii_reduction.yaml]
    managers.drivers.configuration.read_path = /data/in
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
import configparser
from pathlib import Path

from wattleflow.helpers.config_adapter import ISecretResolver

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["DEFAULT_ENV_FILENAME", "DotEnvResolver", "find_env_file"]

DEFAULT_ENV_FILENAME = ".env"

# --------------------------------------------------------------------------- #
# region Discovery                                                            #
# --------------------------------------------------------------------------- #


def find_env_file(
    start: str | Path,
    filename: str = DEFAULT_ENV_FILENAME,
) -> Path | None:
    """Walk upward from ``start`` (file or directory) returning the first
    ``filename`` found, or ``None``. Lets one ``.env`` sit next to the YAML
    configs or higher up at the project root."""
    p = Path(start).resolve()
    base = p if p.is_dir() else p.parent
    for directory in [base, *base.parents]:
        candidate = directory / filename
        if candidate.is_file():
            return candidate
    return None


# --------------------------------------------------------------------------- #
# endregion Discovery                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region DotEnvResolver                                                       #
# --------------------------------------------------------------------------- #


class DotEnvResolver(ISecretResolver):
    """Resolves ``${dotenv:dotted.key}`` from a single section of a ``.env`` file.

    The section is the YAML file name (e.g. ``03_pii_reduction.yaml``); the
    reference is an opaque key within that section. An absent section yields an
    empty map, so unknown keys return ``None`` — the chain reports it and, under
    strict resolution (``ConfigAdapter._deep_resolve``), the build fails.
    """

    PREFIX = "dotenv"

    __slots__ = ("_section", "_values")

    def __init__(self, env_file: str | Path | None, section: str) -> None:
        self._section = section
        self._values: dict[str, str] = {}
        if env_file is not None:
            self._values = self._parse(env_file).get(section, {})

    @staticmethod
    def _parse(env_file: str | Path) -> dict[str, dict[str, str]]:
        """Read an INI-style ``.env`` into ``{section: {key: value}}``.

        Keys stay case-sensitive and verbatim (dots preserved) via
        ``optionxform``; interpolation is off so values may contain ``%`` and
        ``$`` freely.
        """
        path = Path(env_file)
        if not path.is_file():
            raise FileNotFoundError(f"DotEnvResolver: env file not found: {path}")

        parser = configparser.ConfigParser(interpolation=None)
        parser.optionxform = str  # preserve key case and dots verbatim
        try:
            parser.read(path, encoding="utf-8")
        except configparser.Error as e:
            raise ValueError(f"DotEnvResolver: invalid .env file {path}: {e}") from e

        return {section: dict(parser.items(section)) for section in parser.sections()}

    def _fetch(self, ref: str) -> str | None:
        return self._values.get(ref)


# --------------------------------------------------------------------------- #
# endregion DotEnvResolver                                                    #
# --------------------------------------------------------------------------- #
