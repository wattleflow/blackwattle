# Module name: strategies/documents/file.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
from pathlib import Path
from typing import Any, Optional

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
from wattleflow.concrete.exception import StrategyException
from wattleflow.enums.event import Event
from wattleflow.enums.filetype import FileType
from wattleflow.documents.file import FileDocument
from wattleflow.concrete.helpers import Attribute
from wattleflow.helpers.dtime import Now
from wattleflow.helpers.formatters.factory import FormatterFactory

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Strategies                                                           #
# --------------------------------------------------------------------------- #
class CreateFileDocument(StrategyCreate):
    def execute(self, caller: IWattleflow, *args, **kwargs) -> Optional[ITarget]:
        try:
            self.debug(msg=Event.Create.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IBlackboard), "Expected IBlackboard. Found %s" % type(caller)

            Attribute.mandatory(self, "filename", str, **kwargs)
            document = FileDocument(filename=self.filename)

            # metadata
            document.update_metadata("created_by", self.name)
            document.update_metadata("created_at", Now.utc())
            document.update_metadata("caller", caller.name)
            document.update_metadata("filename", self.filename)
            document.update_metadata("source_format", "file")

            for key, value in kwargs.items():
                if key in ("caller", "filename", "content", "schema", "processor", "blackboard"):
                    continue
                document.update_metadata(f"kwargs_{key}", value)

            if not document.size > 0:
                self.warning(
                    msg=Event.Create.name,
                    step=Event.Check.name,
                    reason="Document file's feeling a bit empty today!",
                    document=document,
                )

            self.debug(
                msg=Event.Create.name,
                step=Event.Completed.name,
                document=document,
                filename=self.filename,
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


class ReadDocumentFile(StrategyRead):
    def execute(self, caller: IWattleflow, **kwargs: Any) -> Optional[ITarget]:
        Attribute.mandatory(self, "identifier", str, **kwargs)
        return None


class WriteDocumentToFile(StrategyWrite):
    def execute(self, caller: IWattleflow, facade: ITarget, *args, **kwargs) -> bool:
        try:
            self.debug(msg=Event.Write.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IRepository), "Expected IRepository. Found %s" % type(caller)
            assert isinstance(facade, ITarget), "Expected ITarget. Found %s" % type(facade)

            driver = kwargs.get("driver")
            suffix = kwargs.get("suffix")

            assert driver is not None, (
                "Driver not in kwargs — strategy requires RepositoryWithDriver"
            )
            assert suffix is not None, "Suffix not in kwargs — strategy requires a file suffix"

            document: FileDocument = facade.request()
            filename = document.metadata.get("filename", document.identifier)
            filepath = Path(str(filename)).with_suffix(suffix)

            if not document.size > 0:  # type: ignore
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="Text content is feeling a bit empty today!",
                    document=document,
                    origin=filename,
                    filepath=filepath,
                    size=document.size,
                )
                return False

            filetype = FileType.detect(suffix)
            formatter = FormatterFactory.create(filetype)
            payload = formatter.render(content=document.content)
            output = driver.write(
                payload,
                filename=filepath.name,
                suffix=formatter.SUFFIX,
            )

            size = len(payload) if payload else 0
            document.update_metadata("size", size)
            document.update_metadata("output", output)
            document.update_metadata("stored_by", caller.name)
            document.update_metadata("stored_at", Now.utc())
            document.update_metadata("document_utc", document.utc_time_stamp())
            document.update_metadata("source_format", formatter.SUFFIX)

            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                document=document,
                output=output,
                size=size,
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


__all__ = ["CreateFileDocument", "ReadDocumentFile", "WriteDocumentToFile"]
