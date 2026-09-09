# Module name: drivers/spark.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# IMPORTANT: This driver requires the pyspark library.                        #
# Ensure you have it installed using:                                         #
#   pip install pyspark                                                       #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations

import re
import fnmatch
import json
from pathlib import Path
from typing import Generator, List, Optional
from pyspark.sql import DataFrame, SparkSession
from wattleflow.concrete import ConnectionManager, GenericDriver
from wattleflow.concrete.driver import DriverMetadata
from wattleflow.concrete.exception import DriverException
from wattleflow.concrete.connection import ConnectionState
from wattleflow.connections.spark import (
    SparkConnection,
    SparkConnectionError,
)
from wattleflow.enums.event import Event
from wattleflow.concrete.helpers import Attribute

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class DriverSparkError(DriverException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Driver                                                               #
# --------------------------------------------------------------------------- #


class DriverSpark(GenericDriver):
    ALLOWED = [
        "connection_name",
        "connection_manager",
        "format",
        "mode",
        "partition_by",
        "read_options",
        "write_options",
        "safe_mode",  # True - default: no raw SQL
        "allow_raw_sql",  # False - global kill switch
        "validate_table_names",  # True
        "max_rows",  # None - opcionalno ograničenje za read
        "log_queries",  # True
    ]
    SQL_KEYWORDS = ("SELECT", "WITH", "SHOW", "DESCRIBE", "EXPLAIN")
    FORMAT_BY_SUFFIX = {
        ".csv": "csv",
        ".json": "json",
        ".parquet": "parquet",
        ".orc": "orc",
        ".txt": "text",
        ".delta": "delta",
    }

    def _get_connection(self) -> SparkConnection:
        return self.connection_manager.get_connection(self.connection_name)

    def load(self) -> None:
        self.debug(msg=Event.Load.name, step=Event.Started.name)

        if self._loaded:
            self.warning(msg=Event.Load.name, step=Event.Check.name, error="Already loaded!")

        self.safe_mode = self.safe_mode if self.safe_mode is not None else True
        self.allow_raw_sql = self.allow_raw_sql if self.allow_raw_sql is not None else False

        self.validate_table_names = (
            self.validate_table_names if self.validate_table_names is not None else True
        )

        self.max_rows = self.max_rows if self.max_rows is not None else None
        self.log_queries = self.log_queries if self.log_queries is not None else True

        conn_name: str = self.connection_name
        mgr: ConnectionManager = self.connection_manager

        Attribute.evaluate(caller=self, target=conn_name, expected_type=str)
        Attribute.evaluate(caller=self, target=mgr, expected_type=ConnectionManager)

        spark_conn: SparkConnection = mgr.get_connection(conn_name)
        Attribute.evaluate(caller=self, target=spark_conn, expected_type=SparkConnection)

        spark_conn.subscribe(self)
        self._loaded = True

        self.debug(
            msg=Event.Load.name,
            step=Event.Completed.name,
            connection_name=conn_name,
            lazy_loading=self._lazy_loading,
            format=self.format,
            mode=self.mode or "overwrite",
            partition_by=self.partition_by or [],
            read_options=self.read_options or {},
            write_options=self.write_options or {},
            safe_mode=self.safe_mode,
            allow_raw_sql=self.allow_raw_sql,
            validate_table_names=self.validate_table_names,
            max_rows=self.max_rows,
            log_queries=self.log_queries,
        )

    def close(self) -> None:
        self.debug(msg=Event.Close.name, step=Event.Started.name)

    def metadata(self) -> DriverMetadata:
        return DriverMetadata(
            name=self.__class__.__name__,
            version="1.0",
            protocol="spark",
            capabilities=["read", "write", "search"],
        )

    # ---------------------------------------------------------------------- #
    # region Read / Write                                                    #
    # ---------------------------------------------------------------------- #

    def read(self, uri: str, **kwargs) -> DataFrame:
        self.debug(msg=Event.Read.name, step=Event.Started.name, uri=uri)

        if not uri:
            raise DriverSparkError(caller=self, error="read: uri is required.")

        max_rows: Optional[int] = kwargs.get("max_rows", self.max_rows)
        user_override: bool = kwargs.get("allow_raw_sql", False)

        is_sql = self.is_sql(str(uri))

        # ---------------- SECURITY ---------------- #

        if is_sql:
            # 1. Global policy: driver:allow_raw_sql
            if not self.allow_raw_sql:
                if not user_override:
                    raise DriverSparkError(
                        caller=self,
                        error="Raw SQL is globally disabled (allow_raw_sql=False).",
                    )
                self.warning(
                    msg=Event.Read.name,
                    step=Event.Check.name,
                    reason="User override: allow_raw_sql=True bypasses "
                    "global policy for this query.",
                    uri=str(uri)[:120],
                )

            # 2. Safe mode
            if self.safe_mode:
                if not user_override:
                    raise DriverSparkError(
                        caller=self,
                        error="Raw SQL requires allow_raw_sql=True when safe_mode=True.",
                    )
                self.warning(
                    msg=Event.Read.name,
                    step=Event.Check.name,
                    reason="User override: safe_mode bypassed.",
                    uri=str(uri)[:120],
                )

        if self.log_queries:
            self.debug(
                msg=Event.Read.name,
                uri=str(uri)[:120],
                is_sql=is_sql,
            )

        # ---------------- EXECUTE WITH RECONNECT ---------------- #

        try:
            df = self._execute_read(str(uri), **kwargs)
        except SparkConnectionError as e:
            if not self._try_reconnect():
                raise
            self.debug(
                msg=Event.Read.name,
                step=Event.Failed.name,
                error=str(e),
                uri=str(uri)[:80],
            )
            df = self._execute_read(str(uri), **kwargs)
        except DriverSparkError:
            raise
        except Exception as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=str(e))
            raise DriverSparkError(
                caller=self,
                error=f"read error: {e}",
            ) from e

        if max_rows:
            df = df.limit(int(max_rows))

        self.debug(
            msg=Event.Read.name,
            step=Event.Completed.name,
            uri=uri,
            columns=df.columns,
        )
        return df

    def write(self, uri: str, data: object, **kwargs) -> str:
        if not uri:
            raise DriverSparkError(caller=self, error="write: uri is required.")

        fmt = kwargs.pop("format", None) or self.format or self._detect_format(uri) or "parquet"
        mode: str = kwargs.pop("mode", None) or self.mode or "overwrite"
        partition_by: List[str] = kwargs.pop("partition_by", None) or self.partition_by or []
        write_options: dict = {
            **(self.write_options or {}),
            **kwargs.pop("write_options", {}),
        }
        is_table = self._is_table_uri(uri)

        if is_table and self.validate_table_names:
            self._validate_table_name(uri)

        self.debug(
            msg=Event.Write.name,
            step=Event.Started.name,
            uri=uri,
            format=fmt,
            mode=mode,
            is_table=is_table,
        )

        # ---------------- EXECUTE WITH RECONNECT ---------------- #

        write_kwargs = dict(
            uri=uri,
            data=data,
            fmt=fmt,
            mode=mode,
            partition_by=partition_by,
            write_options=write_options,
            is_table=is_table,
        )

        try:
            self._execute_write(**write_kwargs)
        except SparkConnectionError as e:
            if not self._try_reconnect():
                raise
            self.debug(
                msg=Event.Write.name,
                step=Event.Failed.name,
                error=str(e),
                uri=uri,
            )
            self._execute_write(**write_kwargs)
        except DriverSparkError:
            raise
        except Exception as e:
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=str(e))
            raise DriverSparkError(
                caller=self,
                error=f"write error for uri={uri!r}: {e}",
            ) from e

        self.debug(msg=Event.Write.name, step=Event.Completed.name, uri=uri)
        return uri

    def search(self, pattern: str, **kwargs) -> Generator[str, None, None]:
        database: Optional[str] = kwargs.get("database")
        list_dbs: bool = bool(kwargs.get("list_dbs", False))

        self.debug(
            msg=Event.Search.name,
            step=Event.Started.name,
            pattern=pattern,
            database=database or "(default)",
        )

        with self._get_connection().connect() as session:
            if list_dbs:
                for db in session.catalog.listDatabases():
                    if self._matches(db.name, pattern):
                        yield db.name

            try:
                tables = (
                    session.catalog.listTables(database)
                    if database
                    else session.catalog.listTables()
                )
            except Exception as e:
                self.debug(msg=Event.Search.name, step=Event.Failed.name, error=str(e))
                raise DriverSparkError(
                    caller=self,
                    error=f"search: error while searching for table: {e}",
                ) from e

            for table in tables:
                qualified = f"{table.database}.{table.name}" if table.database else table.name
                if self._matches(qualified, pattern) or self._matches(table.name, pattern):
                    yield qualified

        self.debug(msg=Event.Search.name, step=Event.Completed.name)

    # ---------------------------------------------------------------------- #
    # endregion Read / Write                                                 #
    # ---------------------------------------------------------------------- #

    # ---------------------------------------------------------------------- #
    # region Reconnect
    # ---------------------------------------------------------------------- #

    def _try_reconnect(self) -> bool:
        conn = self._get_connection()
        if conn.state == ConnectionState.FAILED:
            self.error(
                msg=Event.Connect.name,
                step=Event.Started.name,
                error="Connection has FAILED — reconnect not possible.",
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
    # region Internal helpers — read                                         #
    # ---------------------------------------------------------------------- #

    def _execute_read(self, uri: str, **kwargs) -> DataFrame:
        with self._get_connection().connect() as session:
            return (
                self._read_sql(session, uri)
                if self.is_sql(uri)
                else self._read_source(session, uri, **kwargs)
            )

    def _read_sql(self, session: SparkSession, uri: str) -> DataFrame:
        query = self._resolve_query(uri)
        self.debug(msg=Event.Read.name, step=Event.Started.name, query=query[:120])
        return session.sql(query)

    def _read_source(self, session: SparkSession, uri: str, **kwargs) -> DataFrame:
        fmt = kwargs.pop("format", None) or self.format or self._detect_format(uri)
        read_options: dict = {
            **(self.read_options or {}),
            **kwargs.pop("read_options", {}),
        }
        schema = kwargs.pop("schema", None)

        self.debug(
            msg=Event.Read.name,
            step=Event.Started.name,
            uri=uri,
            format=fmt,
            options=read_options,
        )

        reader = session.read
        if fmt:
            reader = reader.format(fmt)
        if read_options:
            reader = reader.options(**read_options)
        if schema is not None:
            reader = reader.schema(schema)
        return reader.load(uri)

    # ---------------------------------------------------------------------- #
    # endregion Internal helpers — read                                      #
    # ---------------------------------------------------------------------- #

    # ---------------------------------------------------------------------- #
    # region Internal helpers — write                                        #
    # ---------------------------------------------------------------------- #

    def _execute_write(
        self,
        uri: str,
        data: object,
        fmt: str,
        mode: str,
        partition_by: List[str],
        write_options: dict,
        is_table: bool,
    ) -> None:
        """Executes a write operation within a managed connection context."""
        with self._get_connection().connect() as session:
            df: DataFrame = self._to_dataframe(session, data)

            writer = df.write.format(fmt).mode(mode)
            if write_options:
                writer = writer.options(**write_options)
            if partition_by:
                writer = writer.partitionBy(*partition_by)

            if is_table:
                writer.saveAsTable(uri)
            else:
                writer.save(uri)

    def _to_dataframe(self, session: SparkSession, data: object) -> DataFrame:
        if isinstance(data, DataFrame):
            return data

        try:
            import pandas as pd

            if isinstance(data, pd.DataFrame):
                return session.createDataFrame(data)
        except ImportError:
            pass

        if isinstance(data, bytes):
            data = data.decode("utf-8")

        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (ValueError, TypeError) as e:
                self.debug(msg=Event.Transform.name, step=Event.Failed.name, error=str(e))
                raise DriverSparkError(
                    caller=self,
                    error=f"_to_dataframe: can't parse as JSON: {e}",
                ) from e

        if isinstance(data, list):
            if not data:
                raise DriverSparkError(
                    caller=self,
                    error="_to_dataframe: empty list.",
                )
            return session.createDataFrame(data)

        if isinstance(data, dict):
            return session.createDataFrame([data])

        raise DriverSparkError(
            caller=self,
            error=f"_to_dataframe: unsupported type '{type(data).__name__}'.",
        )

    def _validate_table_name(self, name: str) -> None:
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_.]*$", name):
            raise DriverSparkError(
                caller=self,
                error=f"Invalid table name: '{name}'",
            )

    # ---------------------------------------------------------------------- #
    # endregion Internal helpers — write                                     #
    # ---------------------------------------------------------------------- #

    # ---------------------------------------------------------------------- #
    # region Static helpers                                                  #
    # ---------------------------------------------------------------------- #

    @classmethod
    def is_sql(cls, uri: str) -> bool:
        stripped = uri.strip()
        if stripped.lower().startswith("sql:"):
            return True
        upper = stripped.upper()
        return any(upper.startswith(kw) for kw in cls.SQL_KEYWORDS)

    @classmethod
    def _resolve_query(cls, uri: str) -> str:
        stripped = uri.strip()
        if stripped.lower().startswith("sql:"):
            return stripped[4:].strip().rstrip(";")
        upper = stripped.upper()
        if any(upper.startswith(kw) for kw in cls.SQL_KEYWORDS):
            return stripped.rstrip(";")
        return stripped

    @classmethod
    def _detect_format(cls, uri: str) -> Optional[str]:
        suffix = Path(uri.split("?")[0].rstrip("/")).suffix.lower()
        return cls.FORMAT_BY_SUFFIX.get(suffix)

    @staticmethod
    def _is_table_uri(uri: str) -> bool:
        if "://" in uri or uri.startswith("/") or uri.startswith("."):
            return False
        return "." not in Path(uri).suffix

    @staticmethod
    def _matches(name: str, pattern: str) -> bool:
        if not pattern or pattern == "*":
            return True
        if any(c in pattern for c in ("*", "?", "[")):
            return fnmatch.fnmatchcase(name.lower(), pattern.lower())
        return pattern.lower() in name.lower()

    # ---------------------------------------------------------------------- #
    # endregion Static helpers                                               #
    # ---------------------------------------------------------------------- #

    def __repr__(self) -> str:
        return f"DriverSpark[{self.connection_name}]"


# --------------------------------------------------------------------------- #
# endregion Driver                                                            #
# --------------------------------------------------------------------------- #
