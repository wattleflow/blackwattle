# Module name: processors/opensearch.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# IMPORTANT:
# This module requires the opensearch-py library.
#   pip install opensearch-py
#
# OpenSearchReadProcessor  — executes one or more queries via DriverOpenSearch
#                            and yields a DocumentFacade(OpenSearchDocument)
#                            per query.
# OpenSearchWriteProcessor — iterates a list of pre-built batches and yields
#                            DocumentFacade(OpenSearchDocument) per batch. The
#                            matching WriteOpenSearchDocument strategy indexes
#                            each via the driver.
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
from wattleflow.documents.opensearch import OpenSearchContent, OpenSearchSchema
from wattleflow.drivers.opensearch import DriverOpenSearch
from wattleflow.concrete.helpers import Attribute
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Processors                                                           #
# --------------------------------------------------------------------------- #


class OpenSearchReadProcessor(GenericProcessor):
    """Run a list of queries through DriverOpenSearch and emit one facade
    per query.

    Args:
        driver       : DriverOpenSearch with a live (or proxied) connection.
        queries      : list of query strings or DSL bodies. Accepts the same
                       forms as :meth:`DriverOpenSearch.read` — index name,
                       ``index:doc_id``, ``query:{json}``, or pure JSON DSL.
        index        : optional default index stamped onto each facade.
        read_options : dict forwarded to every search call (e.g. ``max_rows``).
    """

    ALLOWED = [
        "driver",
        "index",
        "queries",
        "read_options",
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.debug(
            msg=Event.Constructor.name,
            step=Event.Started.name,
            driver=repr(getattr(self, "driver", None)),
            queries=len(getattr(self, "queries", []) or []),
            index=getattr(self, "index", None),
        )

    def create_generator(self) -> Generator[ITarget, None, None]:
        self.debug(msg=Event.Generate.name, step=Event.Started.name)

        try:
            driver: Optional[DriverOpenSearch] = getattr(self, "driver", None)
            Attribute.evaluate(caller=self, target=driver, expected_type=DriverOpenSearch)

            queries: List[str] = list(getattr(self, "queries", []) or [])
            index: Optional[str] = getattr(self, "index", None)
            read_options: Dict[str, Any] = dict(getattr(self, "read_options", {}) or {})

            if not queries:
                if not index:
                    self.warning(
                        msg=Event.Generate.name,
                        step=Event.Check.name,
                        error="No queries and no default index — nothing to read.",
                    )
                    return
                queries = [index]

            self.debug(msg=Event.Generate.name, queries=len(queries), index=index)

            for query in queries:
                self.debug(msg=Event.Generate.name, scope="item", query=str(query)[:120])
                try:
                    records = driver.read(uri=query, **read_options)
                    if records is None:
                        records = []
                    if not isinstance(records, list):
                        records = [records] if isinstance(records, dict) else list(records)

                    self.debug(
                        msg=Event.Generate.name,
                        scope="item",
                        no=self.cycle + 1,
                        query=str(query)[:120],
                        hits=len(records),
                    )

                    facade: DocumentFacade = self.blackboard.create(
                        caller=self,
                        uri=f"opensearch:{query}",
                        content=records,
                        index=index,
                        query=query,
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


class OpenSearchWriteProcessor(GenericProcessor):
    """Emit one document facade per pre-built OpenSearch batch.

    Persistence (indexing into OpenSearch) is performed by
    :class:`WriteOpenSearchDocument` through the repository driver — this
    processor only assembles facades.

    Args:
        batches : list of dicts, each containing:
                    index   (str, optional) — target index name (informational).
                    schema  (dict, optional) — field-type mapping (informational).
                    records (list[dict])     — documents to index.
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
                    records: OpenSearchContent = batch.get("records", [])
                    schema: OpenSearchSchema = batch.get("schema")
                    index: Optional[str] = batch.get("index")

                    if not isinstance(records, list) or not records:
                        self.warning(
                            msg=Event.Generate.name,
                            step=Event.Check.name,
                            reason="empty/invalid batch; skipped",
                            index=index,
                        )
                        continue

                    uri = f"opensearch://{index or 'index'}/{len(records)}"
                    self.debug(
                        msg=Event.Generate.name,
                        scope="item",
                        no=self.cycle + 1,
                        uri=uri,
                        rows=len(records),
                        index=index,
                    )

                    facade: DocumentFacade = self.blackboard.create(  # type: ignore
                        caller=self,
                        uri=uri,
                        content=records,
                        schema=schema,
                        index=index,
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
