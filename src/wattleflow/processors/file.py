# Module name: processors/file.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import re
from pathlib import Path
from traceback import format_exc
from typing import Any, Callable, Generator
from wattleflow.core import ITarget
from wattleflow.concrete import GenericProcessor
from wattleflow.concrete.exception import ProcessorException
from wattleflow.enums.event import Event
from wattleflow.helpers.dtime import CreatedWithin
from wattleflow.helpers.files import FileScanner
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #


class FileDocumentProcessor(GenericProcessor):
    ALLOWED = [
        "converter",
        "created_from",
        "created_to",
        "driver",
        "entities",
        "filter",
        "ignore",
        "pattern",
        "recursive",
        "sort_by",
        "sort_desc",
        "source_path",
        "zone",
    ]

    SORT_KEYS: dict[str, Callable[[Path], Any]] = {
        "name": lambda path: path.name.lower(),
        "created": lambda path: path.stat().st_ctime,
        "modified": lambda path: path.stat().st_mtime,
        "size": lambda path: path.stat().st_size,
    }

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

        if self.entities:
            self._initialise_entities(self.entities)

        self._sort: str = str(self.sort_by or "").strip().lower()
        if self._sort and self._sort not in self.SORT_KEYS:
            reason = "sort_by must be one of %s, got %r" % (
                ", ".join(sorted(self.SORT_KEYS)),
                self.sort_by,
            )
            self.debug(msg=Event.Constructor.name, step=Event.Failed.name, error=reason)
            raise ProcessorException(caller=self, error=reason)

        self.debug(msg=Event.Constructor.name, step=Event.Completed.name)

    def _ordered(self, paths: list[Path]) -> list[Path]:
        """`paths` in the configured order, or as scanned when none is set."""
        if not self._sort:
            return paths
        try:
            return sorted(paths, key=self.SORT_KEYS[self._sort], reverse=bool(self.sort_desc))
        except OSError as e:
            self.warning(
                msg=Event.Generate.name,
                step=Event.Check.name,
                reason="sort failed; scan order kept",
                sort_by=self._sort,
                error=str(e),
            )
            return paths

    def create_generator(self) -> Generator[ITarget, None, None]:
        self.debug(msg=Event.Generate.name, step=Event.Started.name)

        try:
            if not Path(self.source_path).exists():
                raise FileNotFoundError(f"Source path not found: {self.source_path}")

            search_path = Path(self.source_path)

            if not search_path.exists():
                raise FileNotFoundError(
                    "%s: source_path '%s' doesn't exist!" % self.name,
                    str(search_path),
                )

            filtered = re.compile(self.filter) if self.filter else None
            files = self._ordered(list(FileScanner.scan(search_path, self.pattern, self.recursive)))
            count = len(files)

            self.info(
                msg=Event.Generate.name,
                files=count,
                path=str(search_path),
                pattern=self.pattern,
                recursive=bool(self.recursive),
                order=self._sort or "scan",
            )

            for filepath in files:
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

                    self.debug(
                        msg=Event.Generate.name,
                        scope="item",
                        no=self.cycle + 1,
                        filename=str(filepath),
                        size=filepath.stat().st_size,
                    )

                    # The processor discovers and hands over the path; it never
                    # opens the file. Making the document — and reading bytes if
                    # the subject needs them — is the create strategy's duty.
                    context = {"zone": self.zone} if self.zone else {}
                    yield self.blackboard.create(
                        self,
                        filename=str(filepath.absolute()),
                        **context,
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
            self.debug(
                msg=Event.Generate.name,
                step=Event.Failed.name,
                error=str(e),
            )
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
