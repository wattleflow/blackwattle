# Module name: processors/orc.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# IMPORTANT:
# This module requires the pyarrow library.
# Ensure you have it installed using:
#   pip install pyarrow
#
# OrcReadProcessor  — iterates a list of .orc files (or glob pattern) on the
#                     local storage driver, parses each into rows and yields
#                     one DocumentFacade(OrcDocument) per file.
# OrcWriteProcessor — iterates a list of in-memory record batches and yields
#                     one DocumentFacade(OrcDocument) per batch. The matching
#                     WriteOrcDocument strategy persists each via the driver.
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from pathlib import Path
from traceback import format_exc
from typing import Any, Dict, Generator, List
from wattleflow.concrete import DocumentFacade, GenericProcessor
from wattleflow.concrete.exception import DriverNotFound, ProcessorException
from wattleflow.enums.event import Event
from wattleflow.core import ITarget
from wattleflow.documents.orc import OrcContent, OrcRecord, OrcSchema
from wattleflow.drivers.local_storage import DriverLocalStorage
from wattleflow.concrete.helpers import Attribute

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Processors                                                           #
# --------------------------------------------------------------------------- #


class OrcReadProcessor(GenericProcessor):
    """Read ORC files via :class:`DriverLocalStorage` and emit document facades."""

    ALLOWED = [
        "case_sensitive",
        "driver",
        "exclude",
        "files",
        "pattern",
        "recursive",
        "repository_path",
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.debug(
            msg=Event.Constructor.name,
            step=Event.Started.name,
            driver=repr(getattr(self, "driver", None)),
            pattern=getattr(self, "pattern", "*.orc"),
            recursive=getattr(self, "recursive", False),
            explicit=len(getattr(self, "files", []) or []),
        )

    def _ensure_driver(self) -> DriverLocalStorage:
        driver = getattr(self, "driver", None)
        if driver is not None:
            return driver
        repository_path = getattr(self, "repository_path", None)
        if not repository_path:
            raise DriverNotFound(self, "OrcReadProcessor requires 'driver' or 'repository_path'.")
        return DriverLocalStorage(
            repository_path=repository_path,
            level=self._level,
            handler=self._handler,
            create=False,
            normalised=False,
        )

    def _iter_paths(self, driver: DriverLocalStorage) -> Generator[Path, None, None]:
        files = getattr(self, "files", None) or []
        if files:
            for p in files:
                yield Path(p)
            return
        yield from driver.search(
            pattern=getattr(self, "pattern", "*.orc"),
            case_sensitive=getattr(self, "case_sensitive", False),
            recursive=getattr(self, "recursive", False),
        )

    def create_generator(self) -> Generator[ITarget, None, None]:
        self.debug(msg=Event.Generate.name, step=Event.Started.name)

        try:
            driver = self._ensure_driver()
            exclude = getattr(self, "exclude", []) or []
            paths = list(self._iter_paths(driver))

            self.debug(msg=Event.Generate.name, files=len(paths))

            for filename in paths:
                if filename.name in exclude:
                    self.warning(
                        msg=Event.Generate.name,
                        step=Event.Check.name,
                        error=f"Excluded file: {filename}.",
                    )
                    continue

                uri = str(filename.absolute())
                self.debug(msg=Event.Generate.name, scope="item", uri=uri)
                try:
                    records: OrcContent = driver.read(uri=uri)
                    if not isinstance(records, list):
                        records = list(records)

                    self.debug(
                        msg=Event.Generate.name,
                        scope="item",
                        no=self.cycle + 1,
                        uri=uri,
                        rows=len(records),
                    )

                    facade: DocumentFacade = self.blackboard.create(
                        caller=self,
                        uri=uri,
                        content=records,
                        filename=uri,
                    )
                    yield facade

                except Exception as e:
                    error = f"Error: {str(e)} with {uri!r}"
                    self.exception(
                        msg=Event.Generate.name,
                        step=Event.Failed.name,
                        error=error,
                        uri=str(uri),
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


class OrcWriteProcessor(GenericProcessor):
    """Emit one document facade per pre-built ORC record batch.

    Persistence is performed by :class:`WriteOrcDocument` through the
    repository driver — this processor only assembles facades.

    Args:
        batches : List of dicts, each containing:
                    filename (str)        — target file name (``.orc`` optional).
                    schema   (dict)       — column-name → Arrow type string.
                    records  (list[dict]) — ORC rows to encode.
    """

    ALLOWED = [
        "batches",
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.debug(
            msg=Event.Constructor.name,
            step=Event.Started.name,
            batches=len(getattr(self, "batches", []) or []),
        )

    def create_generator(self) -> Generator[ITarget, None, None]:
        self.debug(msg=Event.Generate.name, step=Event.Started.name)

        try:
            batches: List[Dict[str, Any]] = list(getattr(self, "batches", []) or [])
            Attribute.mandatory(self, "batches", list, batches=batches)

            self.debug(msg=Event.Generate.name, batches=len(batches))

            for batch in batches:
                filename: str = batch.get("filename", "")
                schema: OrcSchema = batch.get("schema")
                records: OrcRecord = batch.get("records", [])

                if not filename or not isinstance(records, list):
                    self.warning(
                        msg=Event.Generate.name,
                        step=Event.Check.name,
                        error="Skipping invalid ORC batch (missing filename/records).",
                        filename=filename,
                    )
                    continue

                uri = str(Path(filename).with_suffix(".orc"))
                self.debug(msg=Event.Generate.name, scope="item", uri=uri)
                try:
                    self.debug(
                        msg=Event.Generate.name,
                        scope="item",
                        no=self.cycle + 1,
                        uri=uri,
                        rows=len(records),
                        schema_cols=list((schema or {}).keys()),
                    )

                    facade: DocumentFacade = self.blackboard.create(
                        caller=self,
                        uri=uri,
                        content=records,
                        schema=schema,
                        filename=uri,
                    )
                    yield facade

                except Exception as e:
                    error = f"Error: {str(e)} with {uri!r}"
                    self.exception(
                        msg=Event.Generate.name,
                        step=Event.Failed.name,
                        error=error,
                        uri=str(uri),
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
