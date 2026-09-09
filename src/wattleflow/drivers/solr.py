# Module name: drivers/solr.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# IMPORTANT: This driver requires the pysolr library.                         #
# Ensure you have it installed using:                                         #
#       pip install pysolr                                                    #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import fnmatch
from typing import Any, Dict, Generator, Optional
from wattleflow.concrete import ConnectionManager, GenericDriver
from wattleflow.concrete.driver import DriverMetadata
from wattleflow.concrete.exception import DriverException
from wattleflow.connections.solr import SolrConnection, SolrConnectionError
from wattleflow.enums.event import Event
from wattleflow.documents.solr import SolrContent
from wattleflow.concrete.helpers import Attribute
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class DriverSolrError(DriverException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Driver                                                               #
# --------------------------------------------------------------------------- #


class DriverSolr(GenericDriver):
    """Driver wrapping a :class:`SolrConnection` for read/write operations.
    Read:   :meth:`read` accepts either a Solr query string (default ``*:*``)
            or a URI with ``solr:`` prefix; returns ``list[dict]``.
    Write:  :meth:`write` indexes a list of documents through ``pysolr.add``;
            ``commit`` / ``soft_commit`` semantics are configurable.
    Search: :meth:`search` runs a faceted query and yields matching IDs.
    """

    ALLOWED = [
        "connection_name",
        "connection_manager",
        "id_field",
        "commit",
        "soft_commit",
        "commit_within_ms",
        "max_rows",
        "read_options",
        "write_options",
        "log_queries",
    ]

    DEFAULT_QUERY = "*:*"
    DEFAULT_ROWS = 100

    def __repr__(self) -> str:
        return f"DriverSolr[{getattr(self, 'connection_name', '?')}]"

    def _get_connection(self) -> SolrConnection:
        return self.connection_manager.get_connection(self.connection_name)

    def load(self) -> None:
        self.debug(msg=Event.Load.name, step=Event.Started.name)
        if self._loaded:
            self.warning(msg=Event.Load.name, step=Event.Check.name, error="Already loaded!")

        self.id_field = self.id_field or "id"
        self.commit = self.commit if self.commit is not None else True
        self.soft_commit = self.soft_commit if self.soft_commit is not None else False
        self.commit_within_ms = self.commit_within_ms or None
        self.max_rows = self.max_rows or None
        self.log_queries = self.log_queries if self.log_queries is not None else True

        conn_name: str = self.connection_name
        mgr: ConnectionManager = self.connection_manager
        Attribute.evaluate(caller=self, target=conn_name, expected_type=str)
        Attribute.evaluate(caller=self, target=mgr, expected_type=ConnectionManager)

        solr_conn: SolrConnection = mgr.get_connection(conn_name)
        Attribute.evaluate(caller=self, target=solr_conn, expected_type=SolrConnection)
        solr_conn.subscribe(self)
        self._loaded = True

        self.debug(
            msg=Event.Load.name,
            step=Event.Completed.name,
            connection_name=conn_name,
            id_field=self.id_field,
            commit=self.commit,
            soft_commit=self.soft_commit,
            commit_within_ms=self.commit_within_ms,
        )

    def close(self) -> None:
        self.debug(msg=Event.Close.name, step=Event.Started.name)

    def metadata(self) -> DriverMetadata:
        return DriverMetadata(
            name=self.__class__.__name__,
            version="1.0",
            protocol="solr",
            capabilities=["read", "write", "search"],
        )

    # ---------------------------------------------------------------------- #
    # region Read / Write                                                    #
    # ---------------------------------------------------------------------- #

    def read(self, uri: str, **kwargs) -> SolrContent:
        """Run a Solr query and return the matching documents.
        ``uri`` is either a raw query string (``status:DEPARTED AND airline:OU``)
        or prefixed with ``solr:`` for clarity. Empty string or ``None`` defaults
        to ``*:*``.
        """
        query = self._resolve_query(uri)
        rows = int(kwargs.pop("rows", None) or self.max_rows or self.DEFAULT_ROWS)
        search_options = {
            **(self.read_options or {}),
            **kwargs.pop("read_options", {}),
            **kwargs,
        }
        search_options.setdefault("rows", rows)

        if self.log_queries:
            self.debug(
                msg=Event.Read.name,
                step=Event.Started.name,
                query=query[:120],
                rows=rows,
            )

        try:
            with self._get_connection().connect() as client:
                results = client.search(query, **search_options)
                docs: SolrContent = [dict(doc) for doc in results]
        except SolrConnectionError:
            raise
        except Exception as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=str(e))
            raise DriverSolrError(caller=self, error=f"read error: {e}") from e

        self.debug(
            msg=Event.Read.name,
            step=Event.Completed.name,
            query=query[:120],
            hits=len(docs),
        )
        return docs

    def write(self, uri: str, data: SolrContent, **kwargs) -> str:
        """Index a list of dict documents.

        ``uri`` is informational (the strategy passes a synthetic URI such as
        ``solr://core/<batch-id>``) — the actual target is dictated by the
        bound connection's core.
        """
        if not isinstance(data, list):
            raise DriverSolrError(
                caller=self,
                error="write: data must be list[dict] (SolrContent).",
            )
        if not data:
            self.warning(
                msg=Event.Write.name, step=Event.Check.name, reason="empty batch, nothing to index."
            )
            return uri

        commit = bool(kwargs.pop("commit", self.commit))
        soft_commit = bool(kwargs.pop("soft_commit", self.soft_commit))
        commit_within = kwargs.pop("commit_within", None) or self.commit_within_ms
        write_options = {
            **(self.write_options or {}),
            **kwargs.pop("write_options", {}),
        }

        add_kwargs: Dict[str, Any] = {}
        if commit_within:
            add_kwargs["commitWithin"] = int(commit_within)
        else:
            add_kwargs["commit"] = commit
            if soft_commit:
                add_kwargs["softCommit"] = True
        add_kwargs.update(write_options)

        try:
            with self._get_connection().connect() as client:
                client.add(data, **add_kwargs)
        except SolrConnectionError:
            raise
        except Exception as e:
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=str(e))
            raise DriverSolrError(caller=self, error=f"write error: {e}") from e

        self.debug(
            msg=Event.Write.name,
            step=Event.Completed.name,
            uri=uri,
            indexed=len(data),
            commit=commit,
        )
        return uri

    def delete(self, query: str, **kwargs) -> None:
        commit = bool(kwargs.pop("commit", self.commit))
        try:
            with self._get_connection().connect() as client:
                client.delete(q=query, commit=commit)
        except Exception as e:
            self.debug(msg=Event.Delete.name, step=Event.Failed.name, error=str(e))
            raise DriverSolrError(caller=self, error=f"delete error: {e}") from e

    def search(
        self,
        pattern: str = "*:*",
        **kwargs,
    ) -> Generator[str, None, None]:
        """Yield document IDs matching ``pattern``."""
        rows = int(kwargs.pop("rows", None) or self.max_rows or self.DEFAULT_ROWS)
        id_field = kwargs.pop("id_field", None) or self.id_field
        fields = kwargs.pop("fl", id_field)

        try:
            with self._get_connection().connect() as client:
                results = client.search(pattern, rows=rows, fl=fields, **kwargs)
                for doc in results:
                    value = doc.get(id_field)
                    if value is None:
                        continue
                    sval = str(value)
                    if any(c in pattern for c in ("*", "?")):
                        # pattern may already be Solr-side filter — accept all
                        yield sval
                    else:
                        if fnmatch.fnmatch(sval, pattern):
                            yield sval
        except Exception as e:
            self.debug(msg=Event.Search.name, step=Event.Failed.name, error=str(e))
            raise DriverSolrError(caller=self, error=f"search error: {e}") from e

    # ---------------------------------------------------------------------- #
    # endregion Read / Write                                                 #
    # ---------------------------------------------------------------------- #

    @classmethod
    def _resolve_query(cls, uri: Optional[str]) -> str:
        if not uri:
            return cls.DEFAULT_QUERY
        stripped = uri.strip()
        if stripped.lower().startswith("solr:"):
            stripped = stripped[5:].lstrip("/")
        return stripped or cls.DEFAULT_QUERY


# --------------------------------------------------------------------------- #
# endregion Driver                                                            #
# --------------------------------------------------------------------------- #
