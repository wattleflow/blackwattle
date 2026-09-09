# Module name: strategies/documents/postgres.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# ----------------------------------------------------------------------------#
# region Import                                                               #
# ----------------------------------------------------------------------------#

from __future__ import annotations
from datetime import datetime
import json
from typing import Any, Dict, Optional
from wattleflow.core import (
    IRepository,
    ITarget,
    IWattleflow,
)

from wattleflow.concrete import (
    StrategyWrite,
)
from wattleflow.concrete.exception import StrategyException
from wattleflow.enums.event import Event
from wattleflow.documents.file import FileDocument

# ----------------------------------------------------------------------------#
# endregion Import                                                            #
# ----------------------------------------------------------------------------#

# ----------------------------------------------------------------------------#
# region Classes                                                              #
# ----------------------------------------------------------------------------#


class WriteFileToPgVector(StrategyWrite):
    """Insert a FileDocument (filename + content + metadata) into the pgvector
    ``documents`` table.

    Schema assumed (provided externally):
        documents(id UUID PK, filename TEXT, content TEXT, embedding vector(N),
                  size, mtime, atime, ctime, file_permissions, uid, gid,
                  level, document_type, metadata JSONB,
                  created_at, updated_at,
                  UNIQUE(filename, created_at))

    The ``embedding`` column is left NULL until an NLP/embedding pipeline is
    wired in (Recommended next step). The driver kwarg must be a
    :class:`DriverPostgres` whose ``connection_name`` resolves to a
    PostgresConnection pointing at the pgvector database.
    """

    INSERT_SQL: str = (
        "INSERT INTO documents ("
        "filename, content, "
        "size, mtime, atime, ctime, file_permissions, uid, gid, "
        "level, document_type, metadata) "
        "VALUES ("
        ":filename, :content, "
        ":size, :mtime, :atime, :ctime, :file_permissions, :uid, :gid, "
        ":level, :document_type, CAST(:metadata AS JSONB)"
        ") RETURNING id"
    )

    @staticmethod
    def _coerce_dt(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except Exception:
            return None

    def _build_params(self, document: FileDocument) -> Dict[str, Any]:
        meta = dict(document.metadata or {})
        non_column_meta = {
            k: (v.isoformat() if isinstance(v, datetime) else v)
            for k, v in meta.items()
            if k
            not in (
                "filename",
                "size",
                "mtime",
                "atime",
                "ctime",
                "file_permissions",
                "uid",
                "gid",
                "level",
                "document_type",
            )
        }
        return {
            "filename": document.filename,
            "content": document.content or "",
            "size": int(meta.get("size") or 0),
            "mtime": self._coerce_dt(meta.get("mtime")),
            "atime": self._coerce_dt(meta.get("atime")),
            "ctime": self._coerce_dt(meta.get("ctime")),
            "file_permissions": (meta.get("file_permissions") or "")[:10] or None,
            "uid": int(meta.get("uid")) if meta.get("uid") is not None else None,
            "gid": int(meta.get("gid")) if meta.get("gid") is not None else None,
            "level": str(meta.get("level") or "NOTSET")[:50],
            "document_type": str(meta.get("document_type") or document.__class__.__name__)[:100],
            "metadata": json.dumps(non_column_meta, default=str),
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

            try:
                from sqlalchemy import text  # noqa: PLC0415
            except ImportError as e:
                error = "SQLAlchemy is required for WriteFileToPgVector."
                self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
                raise StrategyException(self, error=error, exc=e) from e

            document: FileDocument = facade.request()
            if not document.content:
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="Empty content — refusing to insert.",
                    filename=document.filename,
                )
                return False

            params = self._build_params(document)

            with driver._get_connection().connect() as conn:  # type: ignore[attr-defined]
                with conn.begin():
                    result = conn.execute(text(self.INSERT_SQL), params)
                    row = result.fetchone()
                    new_id = row[0] if row else None

            document.update_metadata("pgvector_id", str(new_id) if new_id else None)
            document.update_metadata("stored_by", caller.name)
            document.update_metadata("stored_at", document.utc_time_stamp())

            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                document=document,
                pgvector_id=str(new_id) if new_id else None,
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


# ----------------------------------------------------------------------------#
# endregion Classes                                                           #
# ----------------------------------------------------------------------------#
