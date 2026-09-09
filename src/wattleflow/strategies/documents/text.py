# Module name: strategies/documents/text.py
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
    # StrategyRead,
    StrategyWrite,
)
from wattleflow.concrete.exception import StrategyException
from wattleflow.enums.event import Event
from wattleflow.enums.filetype import FileType
from wattleflow.documents.file import FileDocument
from wattleflow.concrete.helpers import Attribute
from wattleflow.helpers.normaliser import Normaliser
from wattleflow.helpers.streams import TextStream
from wattleflow.helpers.formatters.factory import FormatterFactory
from wattleflow.helpers.dtime import Now

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Strategy                                                             #
# --------------------------------------------------------------------------- #


class CreateTextDocument(StrategyCreate):
    def execute(self, caller: IWattleflow, *args, **kwargs) -> Optional[ITarget]:
        try:
            self.debug(msg=Event.Create.name, step=Event.Started.name, kwargs=kwargs)

            assert isinstance(caller, IBlackboard), "Expected IBlackboard. Found %s" % type(caller)

            Attribute.mandatory(self, "filename", str, **kwargs)
            Attribute.mandatory(self, "content", str, **kwargs)

            document = FileDocument(filename=self.filename)
            facade = DocumentFacade(document)
            content = TextStream(self.content)
            # metadata
            document.update_metadata("created_by", self.name)
            document.update_metadata("created_at", Now.utc())
            document.update_metadata("caller", caller.name)
            document.update_metadata("filename", self.filename)
            document.update_metadata("source_format", "text")

            for key, value in kwargs.items():
                if key in ("caller", "filename", "content", "schema", "processor", "blackboard"):
                    continue
                document.update_metadata(f"kwargs_{key}", value)

            document.update_content(str(content))

            self.debug(
                msg=Event.Create.name,
                step=Event.Completed.name,
                document=document,
                file_path=self.filename,
                size=document.size,
            )
            return facade
        except AssertionError as e:
            error = f"Assertion: {str(e)}"
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e


class WriteTextDocument(StrategyWrite):
    def execute(self, caller: IWattleflow, facade: ITarget, *args, **kwargs) -> bool:
        try:
            self.debug(msg=Event.Write.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IRepository), "Expected IRepository. Found %s" % type(caller)
            assert isinstance(facade, ITarget), "Expected ITarget. Found %s" % type(facade)

            driver = kwargs.get("driver")
            assert driver is not None, (
                "Driver not in kwargs — strategy requires RepositoryWithDriver"
            )

            document: FileDocument = facade.request()
            suffix = kwargs.get("suffix", ".txt")
            filename = document.metadata.get("filename", document.identifier)
            filepath = Path(str(filename)).with_suffix(suffix)

            if not document.size > 0:  # type: ignore
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="Text content is feeling a bit empty today!",
                    document=document,
                    filepath=filepath,
                    size=document.size,
                )
                return False
            document.update_metadata("stored_by", caller.name)
            document.update_metadata("stored_at", document.utc_time_stamp())
            formatter = FormatterFactory.create(FileType.TXT)
            payload = formatter.render(content=str(document.content))
            output = driver.write(
                payload,
                filename=filename,
                suffix=formatter.SUFFIX,
            )
            document.update_metadata("storage_filename", output)

            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                size=document.size,
                document=document,
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


class WriteTextContent(StrategyWrite):
    def _stem_for(self, caller: IWattleflow, document: FileDocument) -> str:
        try:
            stem = str(Path(document.filename).stem)
            stem = Normaliser(stem).date().name(max_len=120)
            caller_name = getattr(caller, "name", caller.__class__.__name__)
            stem = f"{stem}.{caller_name}"
            if document.metadata.get("verification_failed"):
                stem = f"{stem}.FAILED"
            return stem
        except Exception as e:
            error = "%s._stem_for caught exception at %s at %s" % (
                self.__class__.__name__,
                str(e),
                __file__,
            )
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(caller=self, error=error, exc=e) from e

    def execute(self, caller: IWattleflow, facade: ITarget, **kwargs: Any) -> bool:
        self.debug(
            msg=Event.Write.name,
            step=Event.Started.name,
            caller=caller,
            facade=facade,
            kwargs=kwargs,
        )
        output = None
        try:
            assert isinstance(caller, IRepository), "Expected IRepository. Found %s" % type(caller)
            assert isinstance(facade, ITarget), "Expected ITarget. Found %s" % type(facade)
            driver = kwargs.get("driver")
            assert driver is not None, (
                "Driver not in kwargs — strategy requires RepositoryWithDriver"
            )

            document: FileDocument = facade.request()
            content = document.content or ""
            if not content.strip():
                # A document that reaches the writer with nothing in it is a
                # finding about the SOURCE, not a failure of the write. The
                # record has to NAME the file: a pass over 242 PDFs produced 17
                # of these, and an identifier alone cannot say which 17.
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="no content to write",
                    filename=str(document.filename),
                    document=facade.identifier,
                    size=0,
                )
                # The audit stream is read while the run happens; the metadata is
                # what a later reader has, so the skip travels with the document.
                document.update_metadata("write_skipped_by", self.name)
                document.update_metadata("write_skipped_at", Now.utc())
                document.update_metadata("write_skipped_reason", "no content")
                return False

            filename = self._stem_for(caller, document)
            formatter = FormatterFactory.create(FileType.TXT)
            payload = formatter.render(content=content)
            output = driver.write(
                payload,
                filename=filename,
                suffix=formatter.SUFFIX,
            )
            document.update_metadata("storage_filename", output)
        except AssertionError as e:
            error = f"Assertion: {str(e)}"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        except Exception as e:
            error = "%s.execute: caught exception at %s at %s" % (
                self.__class__.__name__,
                str(e),
                __file__,
            )
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(
                caller=self,
                error=error,
                exc=e,
            ) from e

        self.debug(
            msg=Event.Write.name,
            step=Event.Completed.name,
            document=document,
            output=str(output),
            size=len(content),
        )
        return True


# --------------------------------------------------------------------------- #
# endregion Strategy                                                          #
# --------------------------------------------------------------------------- #
