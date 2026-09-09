# Module name: strategies/documents/protobuf.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
from pathlib import Path
from typing import Optional
from wattleflow.core import (
    IBlackboard,
    IRepository,
    ITarget,
    IWattleflow,
)
from wattleflow.concrete import (
    DocumentFacade,
    StrategyCreate,
    StrategyRead,
    StrategyWrite,
)
from wattleflow.enums.event import Event
from wattleflow.enums.filetype import FileType
from wattleflow.concrete.exception import StrategyException
from wattleflow.documents.protobuf import (
    ProtobufContent,
    ProtobufDocument,
    ProtobufRecord,
    ProtobufSchema,
)
from wattleflow.concrete.helpers import Attribute
from wattleflow.helpers.dtime import Now
from wattleflow.helpers.formatters.factory import FormatterFactory

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Strategies                                                           #
# --------------------------------------------------------------------------- #


class CreateProtobufDocument(StrategyCreate):
    """Wrap Protobuf records (and schema/message class) into a :class:`ProtobufDocument`."""

    def execute(self, caller: IWattleflow, **kwargs) -> Optional[ITarget]:
        try:
            self.debug(msg=Event.Create.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IBlackboard), "Expected IBlackboard. Found %s" % type(caller)
            Attribute.mandatory(self, "content", list, **kwargs)
            schema: ProtobufSchema = kwargs.get("schema")
            records: ProtobufRecord = self.content  # type: ignore[attr-defined]
            document = ProtobufDocument(
                content=records,
                schema=schema,
                filename=kwargs.get("filename"),
                level=self._level,
                handler=self._handler,
            )

            # metadata — provenance layer only; `filename` and `schema` are the
            # document's own identity keys and are not rewritten here.
            document.update_metadata("created_by", self.name)
            document.update_metadata("created_at", Now.utc())
            document.update_metadata("caller", caller.name)
            document.update_metadata("source_format", "records")

            # Keys already consumed above, plus the live objects the blackboard
            # forwards — neither belongs in document metadata.
            for key, value in kwargs.items():
                if key in ("caller", "filename", "content", "schema", "processor", "blackboard"):
                    continue
                document.update_metadata(f"kwargs_{key}", value)

            if document.size <= 0:
                self.warning(
                    msg=Event.Create.name,
                    step=Event.Check.name,
                    reason="Protobuf record set is empty.",
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


class ReadProtobufDocument(StrategyRead):
    """Read a length-delimited Protobuf file via the repository driver and
    wrap the parsed messages in a :class:`ProtobufDocument`.

    Expected ``kwargs``:
        repository : IRepository whose driver supports ``read(uri=...)`` for
                     :data:`FileType.PROTOBUF` (e.g. ``DriverLocalStorage``).
        identifier : Path to the ``.pb`` file.
        schema     : Descriptor dict or pre-compiled message class.
    """

    def execute(self, caller: IWattleflow, **kwargs) -> Optional[ITarget]:
        try:
            self.debug(msg=Event.Read.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IRepository), "Expected IRepository. Found %s" % type(caller)
            Attribute.mandatory(self, "identifier", str, **kwargs)
            uri: str = self.identifier  # type: ignore[attr-defined]
            driver = kwargs.get("driver")
            assert driver is not None, (
                "Driver not in kwargs — strategy requires RepositoryWithDriver"
            )
            schema: ProtobufSchema = kwargs.get("schema")
            driver_kwargs: dict = {}
            if schema is not None:
                driver_kwargs["schema"] = schema
            message_class = kwargs.get("message_class")
            if message_class is not None:
                driver_kwargs["message_class"] = message_class

            records: ProtobufContent = driver.read(  # type: ignore[attr-defined]
                uri=uri,
                **driver_kwargs,
            )
            if not isinstance(records, list):
                records = list(records)

            document = ProtobufDocument(
                content=records,
                schema=schema,
                filename=uri,
                level=self._level,
                handler=self._handler,
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


class WriteProtobufDocument(StrategyWrite):
    """Persist a :class:`ProtobufDocument` to disk via the repository driver."""

    def execute(self, caller: IWattleflow, facade: ITarget, **kwargs) -> bool:
        try:
            self.debug(msg=Event.Write.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IRepository), "Expected IRepository. Found %s" % type(caller)
            assert isinstance(facade, ITarget), "Expected ITarget. Found %s" % type(facade)
            driver = kwargs.get("driver")
            assert driver is not None, (
                "Driver not in kwargs — strategy requires RepositoryWithDriver"
            )

            document: ProtobufDocument = facade.request()  # type: ignore[assignment]
            if not isinstance(document.content, list) or document.size <= 0:
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="Protobuf record set is empty.",
                    document=document,
                )
                return False
            schema: ProtobufSchema = document.schema
            if schema is None:
                self.error(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="Missing protobuf schema on document metadata.",
                    document=document,
                )
                return False
            name = document.metadata.get("filename", document.identifier)
            filename: Path = Path(str(name)).with_suffix(".pb")
            formatter = FormatterFactory.create(FileType.PROTOBUF)
            payload = formatter.render(content=document.content, schema=schema)
            output = driver.write(  # type: ignore[attr-defined]
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
