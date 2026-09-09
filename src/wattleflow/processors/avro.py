# Module name: processors/avro.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# IMPORTANT:
# This module requires the fastavro library.
# Ensure you have it installed using:
#   pip install fastavro
#
# AvroReadProcessor  — iterates a list of .avro files (or glob pattern) on the
#                      local storage driver, parses each into records and
#                      yields one DocumentFacade(AvroDocument) per file.
# AvroWriteProcessor — iterates a list of in-memory record batches and yields
#                      one DocumentFacade(AvroDocument) per batch. The matching
#                      WriteAvroDocument strategy persists each via the driver.
#
# Both processors delegate persistence to DriverLocalStorage; strategies
# remain unaware of fastavro internals.
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from pathlib import Path
from traceback import format_exc
from typing import Any, Generator, List
from wattleflow.concrete import DocumentFacade, GenericProcessor
from wattleflow.concrete.exception import DriverNotFound, ProcessorException
from wattleflow.enums.event import Event
from wattleflow.core import ITarget
from wattleflow.documents.avro import AvroContent, AvroRecord, AvroSchema
from wattleflow.drivers.local_storage import DriverLocalStorage
from wattleflow.concrete.helpers import Attribute
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Processors                                                           #
# --------------------------------------------------------------------------- #


class AvroReadProcessor(GenericProcessor):
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
            pattern=getattr(self, "pattern", "*.avro"),
            recursive=getattr(self, "recursive", False),
            explicit=len(getattr(self, "files", []) or []),
        )

    def _ensure_driver(self) -> DriverLocalStorage:
        driver = getattr(self, "driver", None)
        if driver is not None:
            return driver
        repository_path = getattr(self, "repository_path", None)
        if not repository_path:
            raise DriverNotFound(
                self,
                "AvroReadProcessor requires 'driver' or 'repository_path'.",
            )
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
            pattern=getattr(self, "pattern", "*.avro"),
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
                uri = str(filename.absolute())
                self.debug(msg=Event.Generate.name, scope="item", uri=uri)
                try:
                    if filename.name in exclude:
                        self.warning(
                            msg=Event.Generate.name,
                            step=Event.Check.name,
                            reason="excluded file; skipped",
                            uri=uri,
                        )
                        continue

                    records: AvroContent = driver.read(uri=uri)
                    if not isinstance(records, list):
                        records = list(records)

                    self.debug(
                        msg=Event.Generate.name,
                        scope="item",
                        no=self.cycle + 1,
                        uri=uri,
                        records=len(records),
                    )

                    facade: DocumentFacade = self.blackboard.create(  # type: ignore
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


class AvroWriteProcessor(GenericProcessor):
    """Emit one document facade per pre-built Avro record batch.

    Persistence is performed by :class:`WriteAvroDocument` through the
    repository driver — this processor only assembles facades.

    Args:
        batches : List of dicts, each containing:
                    filename (str)      — target file name (``.avro`` suffix optional).
                    schema   (dict)     — parsed Avro schema.
                    records  (list[dict]) — Avro records to encode.
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
            batches: List[dict] = getattr(self, "batches", None) or []
            Attribute.mandatory(self, "batches", list, batches=batches)

            self.debug(msg=Event.Generate.name, batches=len(batches))

            for batch in batches:
                filename: str = batch.get("filename", "")
                uri = str(Path(filename).with_suffix(".avro")) if filename else ""
                self.debug(msg=Event.Generate.name, scope="item", uri=uri)
                try:
                    schema: AvroSchema = batch.get("schema", {})
                    records: AvroRecord = batch.get("records", [])

                    if (
                        not filename
                        or not isinstance(schema, dict)
                        or not isinstance(records, list)
                    ):
                        self.warning(
                            msg=Event.Generate.name,
                            step=Event.Check.name,
                            reason="invalid Avro batch (missing filename/schema/records); skipped",
                            filename=filename,
                        )
                        continue

                    self.debug(
                        msg=Event.Generate.name,
                        scope="item",
                        no=self.cycle + 1,
                        uri=uri,
                        records=len(records),
                        schema=schema.get("name", "?"),
                    )

                    facade: DocumentFacade = self.blackboard.create(  # type: ignore
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
