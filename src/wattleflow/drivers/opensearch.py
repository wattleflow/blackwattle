# Module name: drivers/opensearch.py
# Author: (wattleflow@outlook.com)
# Copyright: @ 2022-2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# IMPORTANT: This driver requires the opensearch-py library (2.x or newer).   #
# Install with:                                                               #
#       pip install opensearch-py                                             #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
import fnmatch
import json
import re
from typing import Any, ClassVar, Dict, Generator, Iterable, List, Optional, Tuple, Union

try:
    from opensearchpy.exceptions import NotFoundError
    from opensearchpy.helpers import bulk as os_bulk
except ImportError as e:
    raise ModuleNotFoundError(
        f"OpenSearch library is required to run this code.[{str(e)}]\n"
        "Please install it with `pip install opensearch-py`"
    ) from e

from wattleflow.concrete import ConnectionManager, GenericDriver
from wattleflow.concrete.connection import ConnectionState, GenericConnection
from wattleflow.concrete.driver import DriverMetadata
from wattleflow.concrete.exception import DriverException
from wattleflow.concrete.helpers import Attribute
from wattleflow.decorators.oscal import oscal_driver
from wattleflow.enums.event import Event

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #


WriteMode = str  # one of: index, create, update, upsert, delete, bulk

# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class DriverOpenSearchError(DriverException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Driver                                                               #
# --------------------------------------------------------------------------- #


@oscal_driver(strict=False)
class DriverOpenSearch(GenericDriver):
    """OpenSearch driver — agnostic to the concrete connection subclass.

    Works with any ``GenericConnection`` whose ``connect()`` context manager
    yields an ``opensearchpy.OpenSearch`` client (local, enterprise proxy,
    or AWS sigv4 variants — to be added incrementally).
    """

    ALLOWED = [
        "connection_name",
        "connection_manager",
        "index",  # default index when uri lacks one
        "id_field",  # field in doc whose value becomes _id
        "mode",  # default write mode (index/create/update/upsert/delete)
        "refresh",  # bool | "wait_for"
        "request_timeout",  # per-request override (seconds)
        "max_rows",  # cap on read result size
        "read_options",  # extra kwargs forwarded to client.search
        "write_options",  # extra kwargs forwarded to write calls
        "validate_index_names",
        "log_queries",
    ]
    # OSCAL: reaches the cluster only through OpenSearchConnection, which declares the
    # controls; this class holds no authenticator and no transport setting.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ()

    WRITE_MODES = ("index", "create", "update", "upsert", "delete", "bulk")
    DEFAULT_SEARCH_SIZE = 100

    # ---------------------------------------------------------------------- #
    # region Lifecycle
    # ---------------------------------------------------------------------- #

    def _get_connection(self) -> GenericConnection:
        return self.connection_manager.get_connection(self.connection_name)

    def load(self) -> None:
        self.debug(msg=Event.Load.name, step=Event.Started.name)

        if self._loaded:
            self.warning(msg=Event.Load.name, step=Event.Check.name, error="Already loaded!")

        self.mode = self.mode if self.mode is not None else "index"
        self.refresh = self.refresh if self.refresh is not None else False
        self.max_rows = self.max_rows if self.max_rows is not None else None
        self.log_queries = self.log_queries if self.log_queries is not None else True
        self.validate_index_names = (
            self.validate_index_names if self.validate_index_names is not None else True
        )

        if self.mode not in self.WRITE_MODES:
            raise DriverOpenSearchError(
                caller=self,
                error=f"Invalid mode '{self.mode}'. Allowed: {self.WRITE_MODES}",
            )

        conn_name: str = self.connection_name
        mgr: ConnectionManager = self.connection_manager

        Attribute.evaluate(caller=self, target=conn_name, expected_type=str)
        Attribute.evaluate(caller=self, target=mgr, expected_type=ConnectionManager)

        os_conn: GenericConnection = mgr.get_connection(conn_name)
        Attribute.evaluate(caller=self, target=os_conn, expected_type=GenericConnection)

        os_conn.subscribe(self)
        self._loaded = True

        self.debug(
            msg=Event.Load.name,
            step=Event.Completed.name,
            connection_name=conn_name,
            connection_type=type(os_conn).__name__,
            lazy_loading=self._lazy_loading,
            index=self.index,
            mode=self.mode,
            refresh=self.refresh,
            max_rows=self.max_rows,
            log_queries=self.log_queries,
        )

    def close(self) -> None:
        self.debug(msg=Event.Close.name, step=Event.Started.name)

    def metadata(self) -> DriverMetadata:
        return DriverMetadata(
            name=self.__class__.__name__,
            version="1.0",
            protocol="opensearch",
            capabilities=["read", "write", "search"],
        )

    # endregion Lifecycle

    # ---------------------------------------------------------------------- #
    # region Read / Write
    # ---------------------------------------------------------------------- #

    def read(self, uri: str, **kwargs) -> Any:
        self.debug(msg=Event.Read.name, step=Event.Started.name, uri=uri)

        if not uri:
            raise DriverOpenSearchError(caller=self, error="read: uri is required.")

        index, doc_id, body = self._parse_read_uri(uri, kwargs)
        max_rows: Optional[int] = kwargs.pop("max_rows", self.max_rows)
        read_options: dict = {
            **(self.read_options or {}),
            **(kwargs.pop("read_options", {}) or {}),
        }

        if self.validate_index_names and index:
            self._validate_index_name(index)

        if self.log_queries:
            self.debug(
                msg=Event.Read.name,
                index=index,
                doc_id=doc_id,
                has_body=body is not None,
            )

        try:
            result = self._execute_read(
                index=index,
                doc_id=doc_id,
                body=body,
                max_rows=max_rows,
                read_options=read_options,
                **kwargs,
            )
        except DriverOpenSearchError:
            raise
        except NotFoundError:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, index=index, doc_id=doc_id)
            return None
        except Exception as e:
            if self._is_transient(e) and self._try_reconnect():
                self.debug(
                    msg=Event.Read.name,
                    step=Event.Failed.name,
                    error=str(e),
                    index=index,
                )
                result = self._execute_read(
                    index=index,
                    doc_id=doc_id,
                    body=body,
                    max_rows=max_rows,
                    read_options=read_options,
                    **kwargs,
                )
            else:
                raise DriverOpenSearchError(
                    caller=self,
                    error=f"read error for index={index!r}: {e}",
                ) from e

        self.debug(
            msg=Event.Read.name,
            step=Event.Completed.name,
            index=index,
            count=len(result) if isinstance(result, list) else 1,
        )
        return result

    def write(self, uri: str, data: Any = None, **kwargs) -> Any:
        if not uri:
            raise DriverOpenSearchError(caller=self, error="write: uri is required.")

        index, doc_id = self._parse_write_uri(uri)
        mode: WriteMode = kwargs.pop("mode", None) or self.mode or "index"
        refresh = kwargs.pop("refresh", self.refresh)
        write_options: dict = {
            **(self.write_options or {}),
            **(kwargs.pop("write_options", {}) or {}),
        }
        if refresh is not None:
            write_options.setdefault("refresh", refresh)

        if mode not in self.WRITE_MODES:
            raise DriverOpenSearchError(
                caller=self,
                error=f"Invalid write mode '{mode}'. Allowed: {self.WRITE_MODES}",
            )

        if self.validate_index_names and index:
            self._validate_index_name(index)

        self.debug(
            msg=Event.Write.name,
            step=Event.Started.name,
            index=index,
            doc_id=doc_id,
            mode=mode,
        )

        write_kwargs = dict(
            index=index,
            doc_id=doc_id,
            data=data,
            mode=mode,
            write_options=write_options,
        )

        try:
            result = self._execute_write(**write_kwargs)
        except DriverOpenSearchError:
            raise
        except Exception as e:
            if self._is_transient(e) and self._try_reconnect():
                self.debug(
                    msg=Event.Write.name,
                    step=Event.Failed.name,
                    error=str(e),
                    index=index,
                )
                result = self._execute_write(**write_kwargs)
            else:
                raise DriverOpenSearchError(
                    caller=self,
                    error=f"write error for index={index!r}: {e}",
                ) from e

        self.debug(msg=Event.Write.name, step=Event.Completed.name, index=index)
        return result

    def search(self, pattern: str, **kwargs) -> Generator[str, None, None]:
        """Yield index names matching pattern via _cat/indices."""
        self.debug(msg=Event.Search.name, step=Event.Started.name, pattern=pattern)

        with self._get_connection().connect() as client:
            try:
                rows = client.cat.indices(format="json")
            except Exception as e:
                self.debug(msg=Event.Search.name, step=Event.Failed.name, error=str(e))
                raise DriverOpenSearchError(
                    caller=self,
                    error=f"search: cat.indices failed: {e}",
                ) from e

            for row in rows:
                name = row.get("index") if isinstance(row, dict) else None
                if not name:
                    continue
                if self._matches(name, pattern):
                    yield name

        self.debug(msg=Event.Search.name, step=Event.Completed.name)

    # endregion Read / Write

    # ---------------------------------------------------------------------- #
    # region Reconnect
    # ---------------------------------------------------------------------- #

    @staticmethod
    def _is_transient(exc: BaseException) -> bool:
        """opensearch-py uses ConnectionError / TransportError for transport
        layer failures. Driver-side exceptions (AuditException subclasses)
        are never transient."""
        from opensearchpy.exceptions import (  # noqa: PLC0415
            ConnectionError as OSConnectionError,
            ConnectionTimeout,
            TransportError,
        )

        if isinstance(exc, (OSConnectionError, ConnectionTimeout)):
            return True
        if isinstance(exc, TransportError):
            status = getattr(exc, "status_code", None)
            return status in (502, 503, 504)
        return False

    def _try_reconnect(self) -> bool:
        conn = self._get_connection()
        if conn.state == ConnectionState.FAILED:
            self.error(
                msg=Event.Connect.name,
                step=Event.Started.name,
                error="Connection has FAILED - reconnect not possible.",
                connection_name=self.connection_name,
            )
            return False

        try:
            conn.disconnect()
            conn.create_connection()
            self.debug(
                msg=Event.Connect.name,
                step=Event.Completed.name,
                connection_name=self.connection_name,
                state=conn.state.name,
            )
            return True
        except Exception as e:
            self.error(
                msg=Event.Connect.name,
                step=Event.Failed.name,
                error=str(e),
                connection_name=self.connection_name,
            )
            return False

    # endregion Reconnect

    # ---------------------------------------------------------------------- #
    # region Internal helpers - read
    # ---------------------------------------------------------------------- #

    def _execute_read(
        self,
        index: str,
        doc_id: Optional[str],
        body: Optional[dict],
        max_rows: Optional[int],
        read_options: dict,
        **kwargs,
    ) -> Any:
        with self._get_connection().connect() as client:
            if doc_id is not None:
                resp = client.get(index=index, id=doc_id)
                return self._extract_source(resp)

            search_body: dict = dict(body) if body else {}
            if max_rows is not None:
                search_body.setdefault("size", int(max_rows))
            else:
                search_body.setdefault("size", self.DEFAULT_SEARCH_SIZE)
            if "query" not in search_body:
                search_body["query"] = {"match_all": {}}

            search_kwargs: dict = {"index": index, "body": search_body}
            if read_options:
                search_kwargs.update(read_options)

            resp = client.search(**search_kwargs)
            hits = (resp.get("hits") or {}).get("hits") or []
            return [self._extract_source(hit) for hit in hits]

    @staticmethod
    def _extract_source(hit: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(hit, dict):
            return None
        source = hit.get("_source")
        if source is None:
            return None
        record = dict(source)
        if "_id" in hit:
            record.setdefault("_id", hit["_id"])
        if "_index" in hit:
            record.setdefault("_index", hit["_index"])
        return record

    def _parse_read_uri(self, uri: str, kwargs: dict) -> Tuple[str, Optional[str], Optional[dict]]:
        """Resolve (index, doc_id, body) from uri + kwargs.

        Supported forms:
          * ``index_name``                 - match_all search
          * ``index_name:doc_id``          - get single doc
          * JSON DSL string starting with ``{`` - body, index from kwargs/self.index
          * ``query:{json}``               - body inline, index from kwargs/self.index
        """
        index: Optional[str] = kwargs.pop("index", None) or self.index
        body: Optional[dict] = kwargs.pop("query", None) or kwargs.pop("body", None)
        if isinstance(body, str):
            body = self._parse_json(body, "query")

        stripped = uri.strip()
        if stripped.startswith("{"):
            body = self._parse_json(stripped, "uri")
            if not index:
                raise DriverOpenSearchError(
                    caller=self,
                    error="read: JSON body provided but index is unresolved.",
                )
            return index, None, body

        if stripped.lower().startswith("query:"):
            body = self._parse_json(stripped[6:].strip(), "query")
            if not index:
                raise DriverOpenSearchError(
                    caller=self,
                    error="read: 'query:' uri requires index in kwargs or driver config.",
                )
            return index, None, body

        if ":" in stripped:
            head, tail = stripped.split(":", 1)
            head = head.strip()
            tail = tail.strip()
            if head and tail:
                return head, tail, body

        if not stripped:
            raise DriverOpenSearchError(caller=self, error="read: uri is empty.")
        return stripped, None, body

    @staticmethod
    def _parse_json(payload: str, label: str) -> dict:
        try:
            value = json.loads(payload)
        except (TypeError, ValueError) as e:
            raise DriverOpenSearchError(
                caller=None,
                error=f"_parse_json: {label} is not valid JSON: {e}",
            ) from e
        if not isinstance(value, dict):
            raise DriverOpenSearchError(
                caller=None,
                error=f"_parse_json: {label} must decode to a JSON object.",
            )
        return value

    # endregion Internal helpers - read

    # ---------------------------------------------------------------------- #
    # region Internal helpers - write
    # ---------------------------------------------------------------------- #

    def _execute_write(
        self,
        index: str,
        doc_id: Optional[str],
        data: Any,
        mode: WriteMode,
        write_options: dict,
    ) -> Any:
        with self._get_connection().connect() as client:
            if mode == "delete":
                if doc_id is None:
                    raise DriverOpenSearchError(
                        caller=self,
                        error="write(delete): doc_id is required.",
                    )
                return client.delete(index=index, id=doc_id, **write_options)

            if mode == "bulk":
                actions = self._coerce_bulk_actions(data, index)
                success, errors = os_bulk(
                    client,
                    actions,
                    raise_on_error=False,
                    **write_options,
                )
                if errors:
                    self.warning(
                        msg=Event.Write.name,
                        step=Event.Check.name,
                        success=success,
                        errors=len(errors) if isinstance(errors, list) else errors,
                    )
                return {"success": success, "errors": errors}

            documents = self._coerce_documents(data)
            if isinstance(documents, list):
                actions = [self._build_bulk_action(doc, index, mode) for doc in documents]
                success, errors = os_bulk(
                    client,
                    actions,
                    raise_on_error=False,
                    **write_options,
                )
                if errors:
                    self.warning(
                        msg=Event.Write.name,
                        step=Event.Check.name,
                        success=success,
                        errors=len(errors) if isinstance(errors, list) else errors,
                    )
                return {"success": success, "errors": errors}

            doc: Dict[str, Any] = documents
            resolved_id = doc_id or self._extract_doc_id(doc)

            if mode == "index":
                return client.index(index=index, id=resolved_id, body=doc, **write_options)

            if mode == "create":
                if resolved_id is None:
                    raise DriverOpenSearchError(
                        caller=self,
                        error="write(create): doc id is required.",
                    )
                # opensearch-py uses op_type='create' to enforce create semantics
                return client.index(
                    index=index,
                    id=resolved_id,
                    body=doc,
                    op_type="create",
                    **write_options,
                )

            if mode in ("update", "upsert"):
                if resolved_id is None:
                    raise DriverOpenSearchError(
                        caller=self,
                        error=f"write({mode}): doc id is required.",
                    )
                update_body: Dict[str, Any] = {"doc": doc}
                if mode == "upsert":
                    update_body["doc_as_upsert"] = True
                return client.update(
                    index=index,
                    id=resolved_id,
                    body=update_body,
                    **write_options,
                )

            raise DriverOpenSearchError(
                caller=self,
                error=f"_execute_write: unsupported mode '{mode}'.",
            )

    def _coerce_documents(self, data: Any) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        if isinstance(data, dict):
            return data
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        if isinstance(data, str):
            try:
                parsed = json.loads(data)
            except (TypeError, ValueError) as e:
                self.debug(msg=Event.Validate.name, step=Event.Failed.name, error=str(e))
                raise DriverOpenSearchError(
                    caller=self,
                    error=f"_coerce_documents: payload is not valid JSON: {e}",
                ) from e
            return self._coerce_documents(parsed)
        if isinstance(data, list):
            if not data:
                raise DriverOpenSearchError(
                    caller=self,
                    error="_coerce_documents: empty list.",
                )
            for item in data:
                if not isinstance(item, dict):
                    raise DriverOpenSearchError(
                        caller=self,
                        error="_coerce_documents: list must contain dicts only.",
                    )
            return data
        raise DriverOpenSearchError(
            caller=self,
            error=f"_coerce_documents: unsupported type '{type(data).__name__}'.",
        )

    def _coerce_bulk_actions(self, data: Any, index: str) -> Iterable[Dict[str, Any]]:
        """Accepts either pre-built bulk actions (with ``_op_type``/``_index``)
        or plain documents that get wrapped into ``index`` actions."""
        documents = self._coerce_documents(data)
        if isinstance(documents, dict):
            documents = [documents]

        actions: List[Dict[str, Any]] = []
        for item in documents:
            if any(key.startswith("_") for key in item.keys()):
                action = dict(item)
                action.setdefault("_index", index)
                actions.append(action)
            else:
                actions.append(self._build_bulk_action(item, index, "index"))
        return actions

    def _build_bulk_action(
        self, doc: Dict[str, Any], index: str, mode: WriteMode
    ) -> Dict[str, Any]:
        doc_id = self._extract_doc_id(doc)
        if mode == "index":
            action: Dict[str, Any] = {
                "_op_type": "index",
                "_index": index,
                "_source": doc,
            }
        elif mode == "create":
            if doc_id is None:
                raise DriverOpenSearchError(
                    caller=self,
                    error="bulk create: doc id is required.",
                )
            action = {"_op_type": "create", "_index": index, "_source": doc}
        elif mode in ("update", "upsert"):
            if doc_id is None:
                raise DriverOpenSearchError(
                    caller=self,
                    error=f"bulk {mode}: doc id is required.",
                )
            action = {"_op_type": "update", "_index": index, "doc": doc}
            if mode == "upsert":
                action["doc_as_upsert"] = True
        else:
            raise DriverOpenSearchError(
                caller=self,
                error=f"_build_bulk_action: unsupported mode '{mode}'.",
            )

        if doc_id is not None:
            action["_id"] = doc_id
        return action

    def _extract_doc_id(self, doc: Dict[str, Any]) -> Optional[str]:
        if "_id" in doc:
            return str(doc["_id"])
        id_field = self.id_field
        if id_field and id_field in doc:
            return str(doc[id_field])
        return None

    @staticmethod
    def _parse_write_uri(uri: str) -> Tuple[str, Optional[str]]:
        stripped = uri.strip()
        if not stripped:
            raise DriverOpenSearchError(caller=None, error="write: uri is empty.")
        if ":" in stripped:
            head, tail = stripped.split(":", 1)
            head = head.strip()
            tail = tail.strip()
            if head and tail:
                return head, tail
            return head or stripped, None
        return stripped, None

    @staticmethod
    def _validate_index_name(name: str) -> None:
        # OpenSearch follows the Elasticsearch index-name rules (subset):
        # lowercase, no leading -/_/+, no spaces, no \\/*?"<>|,#:
        if not name:
            raise DriverOpenSearchError(caller=None, error="Index name is empty.")
        if name != name.lower():
            raise DriverOpenSearchError(
                caller=None,
                error=f"Index name must be lowercase: '{name}'",
            )
        if name[0] in ("-", "_", "+"):
            raise DriverOpenSearchError(
                caller=None,
                error=f"Index name cannot start with '-', '_' or '+': '{name}'",
            )
        if not re.match(r"^[a-z0-9][a-z0-9._\-]*$", name):
            raise DriverOpenSearchError(
                caller=None,
                error=f"Invalid index name: '{name}'",
            )

    # endregion Internal helpers - write

    # ---------------------------------------------------------------------- #
    # region Static helpers
    # ---------------------------------------------------------------------- #

    @staticmethod
    def _matches(name: str, pattern: str) -> bool:
        if not pattern or pattern == "*":
            return True
        if any(c in pattern for c in ("*", "?", "[")):
            return fnmatch.fnmatchcase(name.lower(), pattern.lower())
        return pattern.lower() in name.lower()

    # endregion Static helpers

    def __repr__(self) -> str:
        return f"DriverOpenSearch[{self.connection_name}]"


# --------------------------------------------------------------------------- #
# endregion Driver                                                            #
# --------------------------------------------------------------------------- #
