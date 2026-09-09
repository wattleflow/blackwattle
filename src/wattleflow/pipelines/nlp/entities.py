# Module name: pipelines/nlp/entities.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from wattleflow.core import IProcessor, ITarget
from wattleflow.concrete import GenericPipeline
from wattleflow.concrete.exception import PipelineException
from wattleflow.enums.event import Event
from wattleflow.drivers import DriverEntity
from wattleflow.documents.file import FileDocument
from wattleflow.concrete.helpers import Attribute
from wattleflow.helpers.macros import TextMacros
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Types                                                                #
# --------------------------------------------------------------------------- #
Targets = List[Dict[str, str]]
Entities = List[Dict[str, Any]]
# Sentinel used by DDL: `enddate DATETIME NOT NULL DEFAULT '9999-12-31 23:59:59'`
_SUNSET_MAX = datetime(9999, 12, 31, 23, 59, 59)
# --------------------------------------------------------------------------- #
# endregion Types                                                             #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Globals                                                              #
# --------------------------------------------------------------------------- #


def _parse_dt(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if not value:
        return fallback
    text = str(value).strip()
    if not text:
        return fallback
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return fallback


# --------------------------------------------------------------------------- #
# endregion Globals                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Pipelines                                                            #
# --------------------------------------------------------------------------- #


class PipelineProcessorDriverEntities(GenericPipeline):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._entities: TextMacros = TextMacros()

    def _load_patterns(
        self,
        processor: IProcessor,
        order_by_length: bool = False,
        as_of: Optional[datetime] = None,
    ) -> Targets:
        Attribute.evaluate(caller=self, target=processor.driver, expected_type=DriverEntity)

        rows = processor.driver.read(table="entitet")
        now = as_of or datetime.now()

        # Sunset filter: keep only rows where startdate <= now <= enddate.
        active: List[Dict[str, Any]] = []
        for r in rows:
            if not r.get("pattern"):
                continue
            start = _parse_dt(r.get("startdate"), datetime.min)
            end = _parse_dt(r.get("enddate"), _SUNSET_MAX)
            if start <= now <= end:
                active.append(r)

        patterns: Targets = [
            {"pattern": r["pattern"], "replacement": r.get("replacement") or ""} for r in active
        ]

        if order_by_length:
            # Longer patterns first so substrings don't pre-empt full matches.
            patterns.sort(key=lambda m: len(m["pattern"]), reverse=True)

        return patterns

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> None:
        try:
            document: FileDocument = facade.request()
            filepath = Path(facade.filename) if facade.filename else facade.identifier

            self.debug(msg=Event.Transform.name, step=Event.Started.name, document=document)

            if not filepath.exists():
                raise FileNotFoundError(str(filepath))

            content: str = (
                document.content
                if document.size > 0
                else filepath.read_text(encoding=kwargs.get("encoding", "utf-8"))
            )

            if not content.strip():
                self.warning(
                    msg=Event.Transform.name, step=Event.Check.name, error="Content is empty!"
                )
                return

            if self._entities.count < 1:
                macros = self._load_patterns(processor)
                if macros:
                    self._entities.add(macros)

            if self._entities.count < 1:
                self.warning(
                    msg=Event.Transform.name, step=Event.Check.name, error="No entities configured!"
                )
                document.update_content(content)
                return

            ignore = processor.ignore or []
            ignore_res = [re.compile(p, re.IGNORECASE) for p in ignore]

            targets: Targets = []
            seen: set = set()

            for compiled, replacement in self._entities.compiled:
                for match in compiled.finditer(content):
                    surface = (match.group(0) or "").strip()
                    if not surface or surface in seen:
                        continue
                    if any(r.search(surface) for r in ignore_res):
                        continue
                    seen.add(surface)
                    targets.append(
                        {
                            "text": surface,
                            "replacement": str(replacement),
                            "entity": compiled.pattern,
                        }
                    )

            content = self._entities.run(content)
            document.update_content(content)
            document.update_metadata("entity_targets", targets)

            uid = processor.blackboard.write(
                facade=facade,
                processor=processor,
                pipeline=self,
            )

            self.debug(
                msg=Event.Transform.name,
                step=Event.Completed.name,
                entities=len(targets),
                uid=uid,
            )
        except Exception as e:
            error = "%s caught exception: %s at %s" % (
                self.__class__.__name__,
                str(e),
                __file__,
            )
            self.debug(msg=Event.Transform.name, step=Event.Failed.name, error=error)
            raise PipelineException(caller=self, error=error, exc=e) from e


class PipelineProcessorDefinedEntities(GenericPipeline):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._entities: TextMacros = TextMacros()

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> None:
        try:
            document: FileDocument = facade.request()
            filepath = Path(FileDocument.filename)

            self.debug(msg=Event.Transform.name, step=Event.Started.name, filepath=filepath)

            if not filepath.exists():
                raise FileNotFoundError(str(filepath))

            content: str = (
                document.content
                if document.content > 0
                else filepath.read_text(encoding=kwargs.get("encoding", "utf-8"))
            )

            if self._entities.count < 1:
                self._entities.add(processor.entities)

            if not content.strip():
                self.warning(
                    msg=Event.Transform.name, step=Event.Check.name, error="Content is empty!"
                )
                return

            if self._entities.count > 0:
                content = self._entities.run(content)
            else:
                self.warning(
                    msg=Event.Transform.name, step=Event.Check.name, error="No entities configured!"
                )
                return

            document.update_content(content)

            uid = processor.blackboard.write(
                facade=facade,
                processor=processor,
                pipeline=self,
            )

            self.debug(
                msg=Event.Transform.name,
                step=Event.Completed.name,
                uid=uid,
            )
        except Exception as e:
            error = "%s caught exception: %s at %s" % (
                self.__class__.__name__,
                str(e),
                __file__,
            )
            self.debug(msg=Event.Transform.name, step=Event.Failed.name, error=error)
            raise PipelineException(caller=self, error=error, exc=e) from e


# --------------------------------------------------------------------------- #
# endregion Pipelines                                                           #
# --------------------------------------------------------------------------- #
