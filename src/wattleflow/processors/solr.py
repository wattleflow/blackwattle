# Module name: processors/solr.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# IMPORTANT:
# This module requires the pysolr library.
#   pip install pysolr
#
# SolrReadProcessor  — executes one or more Solr queries via DriverSolr and
#                      yields a DocumentFacade(SolrDocument) per query.
# SolrWriteProcessor — iterates a list of pre-built batches and yields
#                      DocumentFacade(SolrDocument) per batch. The matching
#                      WriteSolrDocument strategy indexes each via the driver.
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from traceback import format_exc
from typing import Any, Dict, Generator, List, Optional
from wattleflow.concrete import DocumentFacade, GenericProcessor
from wattleflow.concrete.exception import ProcessorException
from wattleflow.enums.event import Event
from wattleflow.core import ITarget
from wattleflow.documents.solr import SolrContent, SolrSchema
from wattleflow.drivers.solr import DriverSolr
from wattleflow.concrete.helpers import Attribute
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Processors                                                           #
# --------------------------------------------------------------------------- #


class SolrReadProcessor(GenericProcessor):
    """Run a list of Solr queries through :class:`DriverSolr` and emit one
    facade per query.

    Args:
        driver       : DriverSolr with a live SolrConnection.
        queries      : list of query strings (``*:*`` if empty).
        core         : optional core name to stamp on each emitted document.
        read_options : dict of Solr search options applied to every query
                       (``rows``, ``fl``, ``fq``, ``sort``, …).
    """

    ALLOWED = [
        "core",
        "driver",
        "queries",
        "read_options",
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.debug(
            msg=Event.Constructor.name,
            step=Event.Started.name,
            driver=repr(getattr(self, "driver", None)),
            queries=len(getattr(self, "queries", []) or ["*:*"]),
            core=getattr(self, "core", None),
        )

    def create_generator(self) -> Generator[ITarget, None, None]:
        self.debug(msg=Event.Generate.name, step=Event.Started.name)

        try:
            driver: Optional[DriverSolr] = getattr(self, "driver", None)
            Attribute.evaluate(caller=self, target=driver, expected_type=DriverSolr)

            queries: List[str] = list(getattr(self, "queries", None) or ["*:*"])
            core: Optional[str] = getattr(self, "core", None)
            read_options: Dict[str, Any] = dict(getattr(self, "read_options", {}) or {})

            self.debug(msg=Event.Generate.name, queries=len(queries), core=core)

            for query in queries:
                self.debug(msg=Event.Generate.name, scope="item", query=str(query)[:120])
                try:
                    records: SolrContent = driver.read(uri=query, **read_options)
                    if not isinstance(records, list):
                        records = list(records)

                    self.debug(
                        msg=Event.Generate.name,
                        scope="item",
                        no=self.cycle + 1,
                        query=str(query)[:120],
                        hits=len(records),
                    )

                    facade: DocumentFacade = self.blackboard.create(
                        caller=self,
                        uri=f"solr:{query}",
                        content=records,
                        core=core,
                        filename=query,
                    )
                    yield facade

                except Exception as e:
                    error = f"Error: {str(e)} with {query!r}"
                    self.exception(
                        msg=Event.Generate.name,
                        step=Event.Failed.name,
                        error=error,
                        query=str(query),
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


class SolrWriteProcessor(GenericProcessor):
    """Emit one document facade per pre-built Solr document batch.

    Persistence (indexing into Solr) is performed by
    :class:`WriteSolrDocument` through the repository driver — this processor
    only assembles facades.

    Args:
        batches : list of dicts, each containing:
                    core     (str, optional) — target core (informational).
                    schema   (dict, optional) — field-type mapping.
                    records  (list[dict])     — Solr documents to index.
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
                try:
                    records: SolrContent = batch.get("records", [])
                    schema: SolrSchema = batch.get("schema")
                    core: Optional[str] = batch.get("core")

                    if not isinstance(records, list) or not records:
                        self.warning(
                            msg=Event.Generate.name,
                            step=Event.Check.name,
                            reason="empty/invalid batch; skipped",
                            core=core,
                        )
                        continue

                    uri = f"solr://{core or 'core'}/{len(records)}"
                    self.debug(
                        msg=Event.Generate.name,
                        scope="item",
                        no=self.cycle + 1,
                        uri=uri,
                        rows=len(records),
                        core=core,
                    )

                    facade: DocumentFacade = self.blackboard.create(  # type: ignore
                        caller=self,
                        uri=uri,
                        content=records,
                        schema=schema,
                        core=core,
                        filename=uri,
                    )
                    yield facade

                except Exception as e:
                    error = f"Error: {str(e)}"
                    self.exception(
                        msg=Event.Generate.name,
                        step=Event.Failed.name,
                        error=error,
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
