# Module name: strategies/documents/records.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from pathlib import Path
from typing import Any, ClassVar
from wattleflow.core import IRepository, ITarget, IWattleflow
from wattleflow.concrete import DocumentFacade, StrategyRead, StrategyWrite
from wattleflow.concrete.exception import StrategyException
from wattleflow.concrete.helpers import Attribute
from wattleflow.enums.event import Event
from wattleflow.enums.filetype import FileType
from wattleflow.documents.file import FileDocument
from wattleflow.helpers.dtime import Now
from wattleflow.helpers.formatters.factory import FormatterFactory
from wattleflow.helpers.records import DocumentRecords
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["ReadDocumentRecords", "WriteDocumentRecords", "WriteQualityReport"]

# --------------------------------------------------------------------------- #
# region Strategies                                                           #
# --------------------------------------------------------------------------- #


class ReadDocumentRecords(StrategyRead):
    """Read a stored document through the repository driver and carry its content as records.

    A specialisation declares CONTENT, the shape the driver's parser returns, and FILE_TYPE.
    """

    CONTENT: ClassVar[type]
    FILE_TYPE: ClassVar[FileType]

    def execute(self, caller: IWattleflow, **kwargs: Any) -> ITarget | None:
        try:
            self.debug(msg=Event.Read.name, step=Event.Started.name, kwargs=kwargs)
            Attribute.evaluate(caller=self, target=caller, expected_type=IRepository)
            identifier = kwargs.get("identifier")
            Attribute.evaluate(caller=self, target=identifier, expected_type=str)

            driver = kwargs.get("driver") or getattr(caller, "driver", None)
            content = driver.read(uri=identifier)
            Attribute.evaluate(caller=self, target=content, expected_type=self.CONTENT)

            document = FileDocument(filename=identifier)
            DocumentRecords.stamp(document, content, self.FILE_TYPE)

            self.debug(msg=Event.Read.name, step=Event.Completed.name, records=len(content))
            return DocumentFacade(document)
        except Exception as e:
            error = f"{self.name} caught exception: {e}"
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e


class WriteDocumentRecords(StrategyWrite):
    """Render the records stamped on the document in their target format and store them."""

    SLOT: ClassVar[str] = ""

    def execute(self, caller: IWattleflow, facade: ITarget, **kwargs: Any) -> bool:
        try:
            self.debug(msg=Event.Write.name, step=Event.Started.name, caller=caller)
            Attribute.evaluate(caller=self, target=caller, expected_type=IRepository)
            Attribute.evaluate(caller=self, target=facade, expected_type=ITarget)

            driver = kwargs.get("driver") or getattr(caller, "driver", None)
            document = facade.request()
            content, file_type = DocumentRecords.content(document, self.SLOT)
            if not content:
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="no records to write",
                    document=facade.identifier,
                )
                return False

            formatter = FormatterFactory.create(file_type)
            name = document.metadata.get("filename", document.identifier)
            stem = ".".join(filter(None, (Path(str(name)).stem, self.SLOT)))
            # The driver replaces the last suffix: the name carries it, so dots in the stem survive.
            output = driver.write(
                formatter.render(content=content),
                filename=f"{stem}{formatter.SUFFIX}",
                suffix=formatter.SUFFIX,
            )
            document.update_metadata("output", output)
            document.update_metadata("stored_by", self.name)
            document.update_metadata("stored_at", Now.utc())

            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                output=str(output),
                format=file_type.name,
            )
            return True
        except Exception as e:
            error = f"{self.name} caught exception: {e}"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e


class WriteQualityReport(WriteDocumentRecords):
    """Store the quality report a measuring pipeline stamped beside the data."""

    SLOT = DocumentRecords.QUALITY


# --------------------------------------------------------------------------- #
# endregion Strategies                                                        #
# --------------------------------------------------------------------------- #
