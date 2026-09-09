# Module name: strategies/documents/dataframe.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from pathlib import Path
from typing import Optional
import pandas as pd
from wattleflow.core import IBlackboard, IRepository, ITarget, IWattleflow
from wattleflow.concrete import DocumentFacade, StrategyCreate, StrategyRead, StrategyWrite
from wattleflow.enums.event import Event
from wattleflow.concrete.exception import StrategyException
from wattleflow.documents.dataframe import DataFrameDocument
from wattleflow.enums.filetype import FileType
from wattleflow.concrete.helpers import Attribute
from wattleflow.helpers.dtime import Now
from wattleflow.helpers.formatters.factory import FormatterFactory
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Strategies                                                           #
# --------------------------------------------------------------------------- #


class CreateDataframeDocument(StrategyCreate):
    def execute(self, caller: IWattleflow, **kwargs) -> Optional[ITarget]:
        try:
            self.debug(msg=Event.Create.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IBlackboard), "Expected IBlackboard. Found %s" % type(caller)

            Attribute.mandatory(self, "content", pd.DataFrame, **kwargs)
            Attribute.mandatory(self, "filename", str, **kwargs)

            ### DataFrameDocument ---------------------------------------------
            document: DataFrameDocument = DataFrameDocument(
                content=self.content,
                level=self._level,
                handler=self._handler,
            )

            # metadata
            document.update_metadata("created_by", self.name)
            document.update_metadata("created_at", Now.utc())
            document.update_metadata("caller", caller.name)
            document.update_metadata("filename", self.filename)
            document.update_metadata("source_format", "records")

            for key, value in kwargs.items():
                if key in ("caller", "filename", "content", "schema", "processor", "blackboard"):
                    continue
                document.update_metadata(f"kwargs_{key}", value)

            if not document.size > 0:
                self.warning(
                    msg=Event.Create.name,
                    step=Event.Check.name,
                    reason="Dataframe's feeling a bit empty today!",
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


class ReadDataframeDocument(StrategyRead):
    def execute(self, caller: IWattleflow, **kwargs) -> Optional[ITarget]:
        try:
            raise NotImplementedError(f"{self}")
        except AssertionError as e:
            error = f"Assertion: {str(e)}"
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e


class WriteDataframeDocument(StrategyWrite):
    def execute(self, caller: IWattleflow, facade: ITarget, **kwargs) -> bool:
        try:
            self.debug(msg=Event.Write.name, step=Event.Started.name, facade=facade, kwargs=kwargs)
            assert isinstance(caller, IRepository), "Expected IRepository. Found %s" % type(caller)
            assert isinstance(facade, ITarget), "Expected ITarget. Found %s" % type(facade)
            driver = kwargs.get("driver")
            assert driver is not None, (
                "Driver not in kwargs — strategy requires RepositoryWithDriver"
            )

            document: DataFrameDocument = facade.request()
            if document.content.empty:
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="Dataframe's feeling a bit empty today!",
                    document=document,
                    size=document.size,
                )
                return False
            filename: Path = document.metadata.get("filename", document.identifier)
            write_kwargs = {}
            processor = kwargs.get("processor")
            configuration = getattr(processor, "configuration", None) if processor else None
            if configuration is not None:
                cfg_write = configuration.get("write", {})
                if filename in cfg_write:
                    write_kwargs = cfg_write.get(filename, {})
            self.debug(
                msg=Event.Write.name,
                step=Event.Configuring.name,
                filename=filename,
                write_kwargs=write_kwargs,
            )
            filename: Path = Path(filename).with_suffix(".csv")
            formatter = FormatterFactory.create(FileType.DATAFRAME)
            payload = formatter.render(content=document.content, **write_kwargs)
            output = driver.write(
                payload,
                filename=filename.name,
                suffix=formatter.SUFFIX,
                subdir=caller.name.lower(),
                mkdir=True,
            )
            document.update_metadata("storage_filename", output)
            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                document=document,
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
# endregion Strategies                                                         #
# --------------------------------------------------------------------------- #


__all__ = ["CreateDataframeDocument", "WriteDataframeDocument"]
