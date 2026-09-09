# Module name: strategies/documents/word.py
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
    StrategyWrite,
)
from wattleflow.concrete.exception import StrategyException
from wattleflow.enums.event import Event
from wattleflow.enums.filetype import FileType
from wattleflow.documents.file import FileDocument
from wattleflow.concrete.helpers import Attribute
from wattleflow.helpers.normaliser import Normaliser
from wattleflow.helpers.streams import TextStream
from wattleflow.helpers.dtime import Now
from wattleflow.helpers.formatters.factory import FormatterFactory

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #
DEFAULT_MD_SUFFIX = ".md"
DEFAULT_DOCX_SUFFIX = ".docx"
# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Strategies                                                           #
# --------------------------------------------------------------------------- #


class CreateMarkdownFileDocument(StrategyCreate):
    def execute(self, caller: IWattleflow, *args, **kwargs) -> Optional[ITarget]:
        try:
            self.debug(msg=Event.Create.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IBlackboard), "Expected IBlackboard. Found %s" % type(caller)

            Attribute.mandatory(self, "filename", str, **kwargs)
            Attribute.mandatory(self, "content", str, **kwargs)

            filename: str = self.filename  # type: ignore[attr-defined]
            if not filename.lower().endswith(DEFAULT_MD_SUFFIX):
                filename = str(Path(filename).with_suffix(DEFAULT_MD_SUFFIX))

            if self._driver_normalise(caller):
                filename = str(Normaliser(filename).date().name())

            document = FileDocument(filename=filename)
            facade = DocumentFacade(document)

            content = TextStream(self.content)  # type: ignore[attr-defined]
            document.update_metadata("created_by", self.name)
            document.update_metadata("created_at", Now.utc())
            document.update_metadata("caller", caller.name)
            document.update_metadata("filename", filename)
            document.update_metadata("source_format", "markdown")

            for key, value in kwargs.items():
                if key in ("caller", "filename", "content", "schema", "processor", "blackboard"):
                    continue
                document.update_metadata(f"kwargs_{key}", value)

            document.update_content(str(content))

            self.debug(
                msg=Event.Create.name,
                step=Event.Completed.name,
                document=document,
                filename=filename,
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

    @staticmethod
    def _driver_normalise(caller: IBlackboard) -> bool:
        for repo in getattr(caller, "repositories", ()) or ():
            driver = getattr(repo, "driver", None)
            if driver is not None and bool(getattr(driver, "normalised", False)):
                return True
        return False


class WriteMarkdownToWordDocument(StrategyWrite):
    def execute(self, caller: IWattleflow, facade: ITarget, *args, **kwargs) -> bool:
        try:
            self.debug(msg=Event.Write.name, step=Event.Started.name)

            assert isinstance(caller, IRepository), "Expected IRepository. Found %s" % type(caller)
            assert isinstance(facade, ITarget), "Expected ITarget. Found %s" % type(facade)

            repository = kwargs.get("repository") or caller
            driver = getattr(repository, "driver", None)

            assert driver is not None, (
                "Driver not available — strategy requires RepositoryWithDriver"
            )

            document: FileDocument = facade.request()

            if document.size <= 0:
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="Markdown content is empty — nothing to write.",
                    document=document,
                    size=document.size,
                )
                return False

            filepath: Path = Path(document.metadata.get("filename")) or Path(document.identifier)

            if not filepath.exists():
                raise StrategyException(caller=self, error=f"File not found: {filepath.absolute()}")

            filename: str = Path(str(filepath)).with_suffix(DEFAULT_DOCX_SUFFIX).name
            document.update_metadata("stored_by", caller.name)
            document.update_metadata("stored_at", Now.utc())
            self.debug(
                msg=Event.Write.name,
                step=Event.Started.name,
                source=filepath.name,
                target=filename,
                size=document.size,
            )

            content = filepath.read_text(encoding=kwargs.pop("encoding", "utf-8"))
            processor = kwargs.get("processor")
            converter = (
                kwargs.get("converter")
                or getattr(processor, "converter", None)
                or getattr(repository, "converter", None)
                or {}
            )
            formatter = FormatterFactory.create(FileType.DOCX)
            payload = formatter.render(content=content, converter=converter)
            output = driver.write(
                payload,
                filename=filename,
                suffix=formatter.SUFFIX,
            )
            document.update_metadata("output", output)
            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                source=filepath.name,
                output=output,
                size=document.size,
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


__all__ = ["CreateMarkdownFileDocument", "WriteMarkdownToWordDocument"]
