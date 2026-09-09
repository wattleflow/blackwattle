# Module name: processors/file_entity.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from itertools import tee
from traceback import format_exc
from typing import Any, Generator, Optional
from wattleflow.core import ITarget
from wattleflow.concrete import GenericProcessor
from wattleflow.concrete.exception import ProcessorException
from wattleflow.enums.event import Event
from wattleflow.helpers.dtime import CreatedWithin
from wattleflow.helpers.files import FileSourceScanner
from wattleflow.helpers.image_security import SAFE_MAX_BYTES
from wattleflow.helpers.routing import ROUTE_KEY, RoutingLabel
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Processors                                                           #
# --------------------------------------------------------------------------- #


class EntityFileDocumentProcessor(GenericProcessor):
    ALLOWED = [
        "converter",
        "created_from",
        "created_to",
        "driver",
        "filter",
        "ignore",
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
            # File discovery (glob + name exclusion + pattern/labels config) is
            # delegated to FileSourceScanner; the processor keeps only routing and
            # persistence. The scanner owns the PatternSpec parsed from `pattern`.
            scanner = FileSourceScanner(
                self.source_path,
                self.pattern,
                recursive=self.recursive,
                exclude=self.filter,
            )

            file_iter, file_iter_copy = tee(iter(scanner))
            count = sum(1 for _ in file_iter_copy)

            self.debug(msg=Event.Generate.name, files=count, path=str(scanner.source_path))

            for filepath in file_iter:
                self.debug(msg=Event.Generate.name, scope="item", filename=str(filepath))
                try:
                    # Classify the file into a route label by its NAME only (the
                    # processor searches by filename, not path). Files matching no
                    # label are skipped and surfaced as WARNING — an unroutable file
                    # is an operational signal, not debug noise.
                    label: Optional[RoutingLabel] = None
                    if scanner.rule is not None:
                        label = scanner.rule.classify(filepath.name)
                        if label is None:
                            self.warning(
                                msg=Event.Generate.name,
                                step=Event.Check.name,
                                reason="no route match; skipped",
                                filename=filepath.name,
                                format=scanner.rule.fmt,
                            )
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

                    # Refuse oversized inputs before they reach Tika, OCR or PIL —
                    # the cap protects external services from DoS via large blobs.
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

                    self.debug(
                        msg=Event.Generate.name,
                        scope="item",
                        no=self.cycle + 1,
                        filename=str(filepath),
                        size=size,
                    )

                    # Forward the classified label to the create strategy as a
                    # {name: target} pair plus a stable ROUTE_KEY -> name pointer;
                    # the create strategy stamps them onto the document metadata so
                    # write strategies can resolve the destination downstream.
                    create_kwargs: dict[str, Any] = {}
                    if label is not None:
                        create_kwargs[ROUTE_KEY] = label.name
                        create_kwargs[label.name] = label.target

                    # The processor hands over the path and the route it
                    # classified. It never opens the file: reading is the
                    # driver's, and making the document the create strategy's
                    # (`FRQ-PRC-15.22`, NFRQ-ORG-04).
                    yield self.blackboard.create(
                        caller=self,
                        filename=str(filepath.absolute()),
                        **create_kwargs,
                    )

                except Exception as e:
                    error = f"Error: {str(e)} with {filepath!r}"
                    self.error(
                        msg=Event.Generate.name,
                        step=Event.Failed.name,
                        filename=str(filepath),
                        reason=error,
                    )
                    continue
        except Exception as e:
            error = f"Error: {str(e)}"
            self.debug(
                msg=Event.Generate.name,
                step=Event.Failed.name,
                error=error,
                trace=format_exc(),
            )
            raise ProcessorException(
                caller=self,
                error=error,
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
