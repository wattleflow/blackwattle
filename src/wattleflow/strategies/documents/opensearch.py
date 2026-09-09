# Module name: strategies/documents/opensearch.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
import hashlib
from datetime import datetime
from typing import Any, Dict, Optional
from wattleflow.core import IBlackboard, IRepository, ITarget, IWattleflow
from wattleflow.concrete import DocumentFacade, StrategyCreate, StrategyRead, StrategyWrite
from wattleflow.concrete.exception import StrategyException
from wattleflow.concrete.helpers import Attribute
from wattleflow.enums.event import Event
from wattleflow.documents import FileDocument
from wattleflow.documents.opensearch import OpenSearchContent, OpenSearchDocument, OpenSearchSchema
from wattleflow.helpers.dtime import Now

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Strategies                                                           #
# --------------------------------------------------------------------------- #


class CreateOpenSearchDocument(StrategyCreate):
    def execute(self, caller: IWattleflow, **kwargs) -> Optional[ITarget]:
        try:
            self.debug(msg=Event.Create.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IBlackboard), "Expected IBlackboard. Found %s" % type(caller)

            Attribute.mandatory(self, "content", list, **kwargs)
            Attribute.mandatory(self, "filename", str, **kwargs)

            raw_schema = kwargs.get("schema")
            schema: OpenSearchSchema = raw_schema if isinstance(raw_schema, dict) else None
            records: OpenSearchContent = self.content  # type: ignore[attr-defined]

            ### OpenSearchDocument --------------------------------------------
            document: OpenSearchDocument = OpenSearchDocument(
                content=records,
                schema=schema,
                filename=kwargs.get("filename"),
                index=kwargs.get("index"),
                query=kwargs.get("query"),
                level=self._level,
                handler=self._handler,
            )

            # metadata
            document.update_metadata("created_by", self.name)
            document.update_metadata("created_at", Now.utc())
            document.update_metadata("caller", caller.name)
            document.update_metadata("filename", self.filename)
            document.update_metadata("source_format", "json")

            for key, value in kwargs.items():
                if key in ("caller", "filename", "content", "schema", "processor", "blackboard"):
                    continue
                document.update_metadata(f"kwargs_{key}", value)

            if not document.size > 0:
                self.warning(
                    msg=Event.Create.name,
                    step=Event.Check.name,
                    reason="OpenSearch record set is empty.",
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


class ReadOpenSearchDocument(StrategyRead):
    def execute(self, caller: IWattleflow, **kwargs) -> Optional[ITarget]:
        try:
            self.debug(msg=Event.Read.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IRepository), "Expected IRepository. Found %s" % type(caller)
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
            records = driver.read(uri=query, **read_options)  # type: ignore[attr-defined]
            if records is None:
                records = []
            if not isinstance(records, list):
                records = [records] if isinstance(records, dict) else list(records)
            raw_schema = kwargs.get("schema")
            schema: OpenSearchSchema = raw_schema if isinstance(raw_schema, dict) else None
            document = OpenSearchDocument(
                content=records,
                schema=schema,
                filename=query,
                index=kwargs.get("index"),
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


class WriteOpenSearchDocument(StrategyWrite):
    """Index OpenSearchDocument records into the bound OpenSearch index via
    DriverOpenSearch.write()."""

    def execute(self, caller: IWattleflow, facade: ITarget, **kwargs) -> bool:
        try:
            self.debug(msg=Event.Write.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IRepository), "Expected IRepository. Found %s" % type(caller)
            assert isinstance(facade, ITarget), "Expected ITarget. Found %s" % type(facade)
            driver = kwargs.get("driver")
            assert driver is not None, (
                "Driver not in kwargs — strategy requires RepositoryWithDriver"
            )

            document: OpenSearchDocument = facade.request()
            if not isinstance(document.content, list) or document.size <= 0:
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="OpenSearch record set is empty.",
                    document=document,
                )
                return False

            uri = f"opensearch://{document.index or 'index'}/{document.identifier}"
            mode = kwargs.pop("mode", None) or "bulk"

            output = driver.write(uri=uri, data=document.content, mode=mode)
            document.update_metadata("storage_uri", str(output))
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


class WriteFileToOpenSearch(StrategyWrite):
    """Index a FileDocument into an OpenSearch index via DriverOpenSearch.

    The document body mirrors the pgvector schema (filename, content,
    file-system metadata, document_type) so a single search returns enough
    context to navigate back to the pgvector row. The ``_id`` is derived
    deterministically from ``sha256(filename)[:16]`` to make re-indexing
    idempotent.

    The driver kwarg must be a :class:`DriverOpenSearch`. The target index
    name is taken from ``kwargs['index']`` or defaults to ``documents``.
    """

    @staticmethod
    def _resolve_doc_id(filename: str) -> str:
        return hashlib.sha256(filename.encode("utf-8")).hexdigest()[:16]

    def _build_body(self, document: FileDocument) -> Dict[str, Any]:
        meta = dict(document.metadata or {})
        # ISO-stringify datetimes so OpenSearch receives JSON-safe values.
        for key, value in list(meta.items()):
            if isinstance(value, datetime):
                meta[key] = value.isoformat()
        return {
            "filename": document.filename,
            "content": document.content or "",
            "size": int(meta.get("size") or 0),
            "mtime": meta.get("mtime"),
            "ctime": meta.get("ctime"),
            "file_permissions": meta.get("file_permissions"),
            "document_type": document.__class__.__name__,
            "metadata": {
                k: v
                for k, v in meta.items()
                if k not in ("size", "mtime", "atime", "ctime", "file_permissions")
            },
        }

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
            if not document.content:
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="Empty content — refusing to index.",
                    filename=document.filename,
                )
                return False

            index = kwargs.get("index") or "documents"
            mode = kwargs.get("mode") or "index"
            doc_id = self._resolve_doc_id(document.filename)
            uri = f"{index}:{doc_id}"
            body = self._build_body(document)

            output = driver.write(uri=uri, data=body, mode=mode)

            document.update_metadata("opensearch_id", doc_id)
            document.update_metadata("opensearch_index", index)
            document.update_metadata("stored_by", caller.name)
            document.update_metadata("stored_at", document.utc_time_stamp())

            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                document=document,
                opensearch_id=doc_id,
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
