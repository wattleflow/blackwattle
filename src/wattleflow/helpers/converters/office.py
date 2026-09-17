# Module name: helpers/converters/office.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""OfficeConverter — the single headless LibreOffice call (v0.0.4, DR-PRC-005)."""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path
from typing import ClassVar

from wattleflow.helpers.resource_config import ResourceConfig

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["OfficeConverter"]


class OfficeConverter:
    # v0.0.4 (DR-PRC-008): program names and timeout live in the converter template.
    TEMPLATE: ClassVar[str] = "office"

    @classmethod
    def binary(cls) -> str:
        """Path of the LibreOffice executable, or a failure that names it."""
        for name in ResourceConfig.converter(cls.TEMPLATE)["binaries"]:
            found = shutil.which(name)
            if found:
                return found
        raise RuntimeError("LibreOffice not found. Install: sudo apt install libreoffice")

    @classmethod
    def convert(cls, source: Path, target: str, outdir: Path, timeout: int | None = None) -> Path:
        """Convert ``source`` into format ``target`` inside ``outdir``; returns the produced file."""
        overrides = {} if timeout is None else {"timeout": timeout}
        result = subprocess.run(  # noqa: S603 — fixed argument list, no shell
            [cls.binary(), "--headless", "--convert-to", target, "--outdir", str(outdir), str(source)],
            capture_output=True,
            text=True,
            timeout=ResourceConfig.converter(cls.TEMPLATE, overrides)["timeout"],
            check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"LibreOffice conversion to {target} failed: {detail}")
        produced = Path(outdir) / f"{Path(source).stem}.{target}"
        if not produced.is_file():
            raise RuntimeError(f"LibreOffice produced no .{target} output for {Path(source).name}")
        return produced
