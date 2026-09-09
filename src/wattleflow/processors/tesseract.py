# Module name: processors/tesseract.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# IMPORTANT: This test case requires the pytesseract library.                 #
# Ensure you have it installed using:                                         #
#       pip install pytesseract                                               #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import os
import re
import pytesseract
from itertools import tee
from pathlib import Path
from traceback import format_exc
from typing import Any, Generator
from PIL import Image
from wattleflow.core import ITarget
from wattleflow.concrete import GenericProcessor
from wattleflow.concrete.exception import ProcessorException
from wattleflow.enums.event import Event
from wattleflow.helpers.dtime import CreatedWithin
from wattleflow.helpers.files import FileScanner
from wattleflow.helpers.streams import TextStream
from wattleflow.helpers.image_security import SAFE_MAX_BYTES
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Processors                                                           #
# --------------------------------------------------------------------------- #


class TesseractProcessor(GenericProcessor):
    ALLOWED = [
        "case_sensitive",
        "created_from",
        "created_to",
        "filter",
        "macros",
        "pattern",
        "recursive",
        "source_path",
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        try:
            self._dates: CreatedWithin = CreatedWithin(self.created_from, self.created_to)
        except ValueError as e:
            self.debug(msg=Event.Constructor.name, step=Event.Failed.name, error=str(e))
            raise ProcessorException(caller=self, error=str(e)) from e

        if self._dates.active:
            self.debug(
                msg=Event.Constructor.name,
                step=Event.Started.name,
                created_from=self._dates.start.isoformat() if self._dates.start else None,
                created_to=self._dates.end.isoformat() if self._dates.end else None,
            )

        self.debug(msg=Event.Constructor.name, step=Event.Completed.name)

    def create_generator(self) -> Generator[ITarget, None, None]:
        self.debug(msg=Event.Generate.name, step=Event.Started.name)

        try:
            if not Path(self.source_path).exists():
                raise FileNotFoundError(f"Source path not found: {self.source_path}")

            search_path = Path(self.source_path)
            case_sensitive: bool = bool(getattr(self, "case_sensitive", False))
            recursive: bool = bool(getattr(self, "recursive", False))
            macros = getattr(self, "macros", None)

            flags = 0 if case_sensitive else re.IGNORECASE
            filtered = re.compile(self.filter, flags) if self.filter else None
            file_iter = FileScanner.scan(search_path, getattr(self, "pattern", None), recursive)

            file_iter, file_iter_copy = tee(file_iter)
            count = sum(1 for _ in file_iter_copy)
            self.info(msg=Event.Generate.name, files=count, path=search_path)

            for filepath in file_iter:
                self.debug(msg=Event.Generate.name, scope="item", filename=str(filepath))
                try:
                    if filtered and filtered.findall(filepath.stem):
                        continue

                    if self._dates.active:
                        verdict = self._dates.check(filepath)
                        if not verdict.ok:
                            if verdict.reason == "stat-failed":
                                self.warning(
                                    msg=Event.Generate.name,
                                    step=Event.Check.name,
                                    reason="stat failed; skipping",
                                    filename=str(filepath),
                                    error=verdict.error,
                                )
                            else:
                                self.debug(
                                    msg=Event.Generate.name,
                                    scope="item",
                                    reason=(
                                        "created before window; skipped"
                                        if verdict.reason == "before-window"
                                        else "created after window; skipped"
                                    ),
                                    filename=str(filepath),
                                    created_at=verdict.created_at.isoformat(),
                                )
                            continue

                    if not (os.access(filepath, os.R_OK) and filepath.stat().st_size > 0):
                        self.warning(
                            msg=Event.Generate.name,
                            step=Event.Check.name,
                            reason="File not accessible",
                            filename=str(filepath.absolute()),
                        )
                        continue

                    # Refuse oversized inputs before they reach OCR or PIL — the
                    # cap protects the decoder from DoS via large blobs.
                    size = filepath.stat().st_size
                    if size > SAFE_MAX_BYTES:
                        self.warning(
                            msg=Event.Generate.name,
                            step=Event.Check.name,
                            reason="file exceeds safe size cap",
                            filename=str(filepath),
                            size=size,
                            cap=SAFE_MAX_BYTES,
                        )
                        continue

                    image = Image.open(str(filepath.absolute()))
                    content = TextStream(
                        pytesseract.image_to_string(image),
                        macros=macros,
                    )

                    self.debug(
                        msg=Event.Generate.name,
                        scope="item",
                        no=self.cycle + 1,
                        filename=str(filepath),
                        size=len(str(content)),
                    )

                    yield self.blackboard.create(
                        caller=self,
                        filename=str(filepath.absolute()),
                        content=content,
                    )

                except Exception as e:
                    filename = str(filepath)
                    error = f"Error: {str(e)} with {filename!r}"
                    self.exception(
                        msg=Event.Generate.name,
                        step=Event.Failed.name,
                        error=error,
                        filename=filename,
                    )
                    continue
        except Exception as e:
            self.debug(msg=Event.Generate.name, step=Event.Failed.name, error=str(e))
            raise ProcessorException(
                caller=self,
                error=e,
                exc=format_exc(),
            ) from e

        self.debug(
            msg=Event.Generate.name,
            step=Event.Completed.name,
            count=self.cycle,
        )


# --------------------------------------------------------------------------- #
# endregion Processors                                                        #
# --------------------------------------------------------------------------- #
