# Module name: strategies/documents/avro.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
from pathlib import Path
from typing import Optional
from wattleflow.core import IBlackboard, IRepository, ITarget, IWattleflow
from wattleflow.concrete import DocumentFacade, StrategyCreate, StrategyRead, StrategyWrite
from wattleflow.concrete.exception import StrategyException
from wattleflow.enums.event import Event
from wattleflow.enums.filetype import FileType
from wattleflow.documents.avro import AvroContent, AvroDocument, AvroRecord, AvroSchema
from wattleflow.concrete.helpers import Attribute
from wattleflow.helpers.dtime import Now
from wattleflow.helpers.formatters.factory import FormatterFactory

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Strategies                                                           #
# --------------------------------------------------------------------------- #


class CreateAvroDocument(StrategyCreate):
    def execute(self, caller: IWattleflow, **kwargs) -> Optional[ITarget]:
        try:
            self.debug(msg=Event.Create.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IBlackboard), "Expected IBlackboard. Found %s" % type(caller)

            Attribute.mandatory(self, "content", list, **kwargs)
            raw_schema = kwargs.get("schema")
            schema: AvroSchema = raw_schema if isinstance(raw_schema, dict) else None
            records: AvroRecord = self.content  # type: ignore[attr-defined]
            filename: Optional[str] = kwargs.get("filename")

            ### AvroDocument
            document: AvroDocument = AvroDocument(
                content=records,
                schema=schema,
                filename=filename,
                level=self._level,
                handler=self._handler,
            )

            # metadata
            document.update_metadata("created_by", self.name)
            document.update_metadata("created_at", Now.utc())
            document.update_metadata("caller", caller.name)
            document.update_metadata("filename", filename)
            document.update_metadata("source_format", "records")

            for key, value in kwargs.items():
                if key in ("caller", "filename", "content", "schema", "processor", "blackboard"):
                    continue
                document.update_metadata(f"kwargs_{key}", value)

            if not document.size > 0:
                self.warning(
                    msg=Event.Create.name,
                    step=Event.Check.name,
                    reason="Avro record set is empty.",
                    document=document,
                )

            self.debug(
                msg=Event.Create.name,
                step=Event.Completed.name,
                document=document.identifier,
                size=document.size,
            )

            return DocumentFacade(document)
        except AssertionError as e:
            error = f"Assertion: {str(e)}"
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e


class ReadAvroDocument(StrategyRead):
    """Read an Avro file via the repository driver and wrap it in :class:`AvroDocument`.
    Expected ``kwargs``:
        repository : IRepository whose driver exposes ``read(uri=...)`` for AVRO.
        identifier : Absolute or repository-relative path to the ``.avro`` file.
    """

    def execute(self, caller: IWattleflow, **kwargs) -> Optional[ITarget]:
        try:
            self.debug(msg=Event.Read.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IRepository), "Expected IRepository. Found %s" % type(caller)
            Attribute.mandatory(self, "identifier", str, **kwargs)
            uri: str = self.identifier
            # Driver stize kroz kwargs samo ako je caller RepositoryWithDriver.
            driver = kwargs.get("driver")
            assert driver is not None, (
                "Driver not in kwargs — strategy requires RepositoryWithDriver"
            )
            records: AvroContent = driver.read(uri=uri)
            if not isinstance(records, list):
                records = list(records)
            self.debug(
                msg=Event.Read.name,
                step=Event.Validating.name,
                uri=uri,
                count=len(records),
            )

            raw_schema = kwargs.get("schema")
            schema: AvroSchema = raw_schema if isinstance(raw_schema, dict) else None
            document = AvroDocument(
                content=records,
                schema=schema,
                filename=uri,
            )
            document.update_metadata("source_uri", uri)
            self.debug(
                msg=Event.Read.name,
                step=Event.Completed.name,
                document=document.identifier,
                size=document.size,
            )
            return DocumentFacade(document)
        except AssertionError as e:
            error = f"Assertion: {str(e)}"
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e


class WriteAvroDocument(StrategyWrite):
    """Persist an :class:`AvroDocument` to disk via the repository driver."""

    def execute(self, caller: IWattleflow, facade: ITarget, **kwargs) -> bool:
        try:
            self.debug(msg=Event.Write.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IRepository), "Expected IRepository. Found %s" % type(caller)
            assert isinstance(facade, ITarget), "Expected ITarget. Found %s" % type(facade)

            driver = kwargs.get("driver")
            assert driver is not None, (
                "Driver not in kwargs — strategy requires RepositoryWithDriver"
            )

            document: AvroDocument = facade.request()
            if not isinstance(document.content, list) or document.size <= 0:
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="Avro record set is empty.",
                    document=document,
                )
                return False
            schema: AvroSchema = document.schema
            if not isinstance(schema, dict):
                self.error(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="Missing Avro schema on document metadata.",
                    document=document,
                )
                return False
            name = document.metadata.get("filename", document.identifier)
            filename: Path = Path(str(name)).with_suffix(".avro")
            write_kwargs: dict = {}
            # Configuration je na procesoru (pipeline ga proslijedi kao kwarg).
            processor = kwargs.get("processor")
            configuration = getattr(processor, "configuration", None) if processor else None
            if configuration is not None:
                write_kwargs = dict(configuration.get("write", {}).get(filename.name, {}))

            codec = kwargs.pop("codec", write_kwargs.pop("codec", "deflate"))
            formatter = FormatterFactory.create(FileType.AVRO)
            payload = formatter.render(
                content=document.content,
                schema=schema,
                codec=codec,
                **write_kwargs,
            )
            output = driver.write(
                payload,
                filename=filename.name,
                suffix=formatter.SUFFIX,
                subdir=caller.name.lower(),
                mkdir=True,
            )

            document.update_metadata("storage_filename", output)
            document.update_metadata("stored_by", caller.name)
            document.update_metadata("stored_at", document.utc_time_stamp())

            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                document=document,
                size=document.size,
                output=output,
            )
            return True
        except AssertionError as e:
            error = f"Assertion: {str(e)}"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e


# --------------------------------------------------------------------------- #
# endregion Strategies                                                        #
# --------------------------------------------------------------------------- #
