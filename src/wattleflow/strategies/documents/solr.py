# Module name: strategies/documents/solr.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
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
from wattleflow.concrete.exception import StrategyException
from wattleflow.documents.solr import SolrContent, SolrDocument, SolrSchema
from wattleflow.concrete.helpers import Attribute
from wattleflow.helpers.dtime import Now

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Strategies                                                           #
# --------------------------------------------------------------------------- #


class CreateSolrDocument(StrategyCreate):
    """Wrap Solr records (and optional schema) into a :class:`SolrDocument`."""

    def execute(self, caller: IWattleflow, **kwargs) -> Optional[ITarget]:
        try:
            self.debug(msg=Event.Create.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IBlackboard), "Expected IBlackboard. Found %s" % type(caller)
            Attribute.mandatory(self, "content", list, **kwargs)
            Attribute.mandatory(self, "filename", str, **kwargs)
            raw_schema = kwargs.get("schema")
            schema: SolrSchema = raw_schema if isinstance(raw_schema, dict) else None
            records: SolrContent = self.content  # type: ignore[attr-defined]
            document: SolrDocument = SolrDocument(
                content=records,
                schema=schema,
                filename=kwargs.get("filename"),
                core=kwargs.get("core"),
                query=kwargs.get("query"),
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

            if document.size <= 0:
                self.warning(
                    msg=Event.Create.name,
                    step=Event.Check.name,
                    reason="Solr record set is empty.",
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


class ReadSolrDocument(StrategyRead):
    """Run a Solr query through the repository driver and wrap the hits in a
    :class:`SolrDocument`.

    ``identifier`` is interpreted as a Solr query string (``*:*`` if empty).
    """

    def execute(self, caller: IWattleflow, **kwargs) -> Optional[ITarget]:
        try:
            self.debug(msg=Event.Read.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IRepository), "Expected IRepository. Found %s" % type(caller)
            Attribute.mandatory(self, "content", list, **kwargs)
            Attribute.mandatory(self, "filename", str, **kwargs)
            Attribute.mandatory(self, "identifier", str, **kwargs)
            query: str = self.identifier
            driver = kwargs.get("driver")
            assert driver is not None, (
                "Driver not in kwargs — strategy requires RepositoryWithDriver"
            )
            self.debug(
                msg=Event.Read.name,
                step=Event.Configuring.name,
                query=query[:120],
            )
            read_options = kwargs.get("read_options") or {}
            records: SolrContent = driver.read(  # type: ignore[attr-defined]
                uri=query,
                **read_options,
            )
            if not isinstance(records, list):
                records = list(records)
            raw_schema = kwargs.get("schema")
            schema: SolrSchema = raw_schema if isinstance(raw_schema, dict) else None
            document = SolrDocument(
                content=records,
                schema=schema,
                filename=query,
                core=kwargs.get("core"),
                query=query,
                level=self._level,
                handler=self._handler,
            )
            document.update_metadata("hits", len(records))
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


class WriteSolrDocument(StrategyWrite):
    def execute(self, caller: IWattleflow, facade: ITarget, **kwargs) -> bool:
        try:
            self.debug(msg=Event.Write.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IRepository), "Expected IRepository. Found %s" % type(caller)
            assert isinstance(facade, ITarget), "Expected ITarget. Found %s" % type(facade)
            driver = kwargs.get("driver")
            assert driver is not None, (
                "Driver not in kwargs — strategy requires RepositoryWithDriver"
            )

            document: SolrDocument = facade.request()
            if not isinstance(document.content, list) or document.size <= 0:
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="Solr record set is empty.",
                    document=document,
                )
                return False

            uri = f"solr://{document.core or 'core'}/{document.identifier}"
            commit = kwargs.pop("commit", None)
            soft_commit = kwargs.pop("soft_commit", None)
            commit_within = kwargs.pop("commit_within", None)
            driver_kwargs: dict = {
                "uri": uri,
                "data": document.content,
            }

            if commit is not None:
                driver_kwargs["commit"] = commit

            if soft_commit is not None:
                driver_kwargs["soft_commit"] = soft_commit

            if commit_within is not None:
                driver_kwargs["commit_within"] = commit_within

            output = driver.write(**driver_kwargs)  # type: ignore[attr-defined]
            document.update_metadata("storage_uri", output)
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
