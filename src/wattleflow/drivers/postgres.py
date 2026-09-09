# Module name: drivers/postgres.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# Dependencies:
#   pip install SQLAlchemy pandas
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# DriverPostgres — unified persistence layer za read i write putem PostgreSQL-a.
#   Prima PostgresConnection instancu (putem ConnectionManager-a) koja upravlja
#   SQLAlchemy Engine lifecycleom.
#   Svaki poziv read() / write() otvara context manager na PostgresConnection,
#   koji yields aktivnu SQLAlchemy Connection.
#
# Reconnect mehanizam:
#   Ako read() ili write() ne uspije zbog PostgresError (connection-level greška),
#   driver automatski pokušava reconnect: disconnect() → create_connection() → retry.
#   Reconnect se NE pokušava ako je stanje FAILED (nepovratna greška)
#   ili ako je greška na razini SQL-a (DriverPostgresError).
#
# Podrzani oblici URI-a u read():
#   "SELECT * FROM schema.table"   -> SQL upit (direktno)
#   "sql:SELECT * FROM table"      -> SQL upit (eksplicitni prefiks)
#   "schema.table"                 -> tablica (automatski SELECT *)
#
# Podrzani tipovi za data u write():
#   pandas.DataFrame               -> koristi df.to_sql()
#   list[dict]                     -> konvertira u DataFrame
#   dict                           -> wrapa u listu, konvertira
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
import re
import fnmatch
from typing import Generator, Optional

import pandas as pd

try:
    from sqlalchemy import text
except ImportError as e:
    raise ModuleNotFoundError(
        f"SQLAlchemy package is required to run this code.[{str(e)}]\n"
        "Please install it with `pip install sqlalchemy`"
    ) from e

from typing import ClassVar, Tuple
from wattleflow.concrete import ConnectionManager, GenericDriver
from wattleflow.concrete.driver import DriverMetadata
from wattleflow.concrete.exception import DriverException
from wattleflow.concrete.connection import ConnectionState
from wattleflow.connections.postgres import PostgresConnection, PostgresError
from wattleflow.enums.event import Event
from wattleflow.concrete.helpers import Attribute

from wattleflow.decorators.oscal import oscal_driver
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class DriverPostgresError(DriverException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Driver                                                               #
# --------------------------------------------------------------------------- #


@oscal_driver(strict=False)
class DriverPostgres(GenericDriver):
    SQL_KEYWORDS = ("SELECT", "WITH", "SHOW", "EXPLAIN")
    ALLOWED = [
        "connection_name",  # postgress-connection
        "connection_manager",
        "chunksize",  # 1000
        "write_method",  # multi - pandas to_sql(method)
        "safe_mode",  # True - default: no raw SQL
        "allow_raw_sql",  # False - global kill switch
        "default_transaction",  # True
        "validate_table_names",  # True
        "max_rows",  # Null - opcionalno ograničenje za read
        "log_queries",  # True
    ]
    # OSCAL: enforces authorised operations itself — `safe_mode`, `allow_raw_sql` and
    # `validate_table_names` bound what may run. Credentials and transport belong to
    # PostgresConnection, which declares them.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ("ac-3",)

    # ---------------------------------------------------------------------- #
    # region constructor
    # ---------------------------------------------------------------------- #
    # No constructor needed: PresetDecorator resolves ALLOWED from the class
    # (NFRQ-ORG-07), so GenericDriver's own __init__ is enough.
    # ---------------------------------------------------------------------- #
    # endregion constructor
    # ---------------------------------------------------------------------- #

    # ---------------------------------------------------------------------- #
    # region public methods
    # ---------------------------------------------------------------------- #
    def load(self) -> None:
        self.debug(msg=Event.Load.name, step=Event.Started.name)

        if self._loaded:
            self.warning(msg=Event.Load.name, step=Event.Check.name, error="Already loaded!")

        self.chunksize = self.chunksize if self.chunksize is not None else 1000
        self.write_method = self.write_method if self.write_method is not None else "multi"

        self.safe_mode = self.safe_mode if self.safe_mode is not None else True
        self.allow_raw_sql = self.allow_raw_sql if self.allow_raw_sql is not None else False

        self.default_transaction = (
            self.default_transaction if self.default_transaction is not None else True
        )

        self.validate_table_names = (
            self.validate_table_names if self.validate_table_names is not None else True
        )

        self.max_rows = self.max_rows if self.max_rows is not None else None
        self.log_queries = self.log_queries if self.log_queries is not None else True

        conn_name: str = self.connection_name
        manager: ConnectionManager = self.connection_manager

        Attribute.evaluate(caller=self, target=conn_name, expected_type=str)
        Attribute.evaluate(caller=self, target=manager, expected_type=ConnectionManager)

        pg_conn: PostgresConnection = manager.get_connection(conn_name)
        Attribute.evaluate(caller=self, target=pg_conn, expected_type=PostgresConnection)

        pg_conn.subscribe(self)
        self._loaded = True

        self.debug(
            msg=Event.Load.name,
            step=Event.Completed.name,
            connection_name=conn_name,
            lazy_loading=self._lazy_loading,
            chunksize=self.chunksize,
            write_method=self.write_method,
            safe_mode=self.safe_mode,
            allow_raw_sql=self.allow_raw_sql,
            default_transaction=self.default_transaction,
            validate_table_name=self.validate_table_names,
            max_rows=self.max_rows,
            log_queries=self.log_queries,
        )

    def close(self) -> None:
        # The PostgresConnection belongs to the ConnectionManager and may be
        # shared with other drivers, so close() drops only this driver's own
        # loaded state — it must never disconnect a connection it does not own.
        self.debug(msg=Event.Close.name, step=Event.Started.name)
        self._loaded = False
        self.debug(
            msg=Event.Close.name,
            step=Event.Completed.name,
            connection_name=self.connection_name,
        )

    def metadata(self) -> DriverMetadata:
        return DriverMetadata(
            name=self.__class__.__name__,
            version="1.0",
            protocol="postgresql",
            capabilities=["read", "write", "search"],
        )

    def read(self, uri: str, **kwargs) -> pd.DataFrame:
        self.debug(msg=Event.Read.name, step=Event.Started.name, uri=uri)

        if not uri:
            raise DriverPostgresError(caller=self, error="read: uri is required.")

        params: dict = kwargs.get("params", {})
        unsafe: bool = kwargs.get("unsafe", False)
        max_rows: Optional[int] = kwargs.get("max_rows", self.max_rows)

        user_override: bool = kwargs.get("allow_raw_sql", False)

        is_sql = self._is_sql(uri)
        query = self._resolve_query(uri)

        # ---------------- SECURITY ---------------- #

        if is_sql:
            # 1. Global policy:  driver:allow_raw_sql
            if not self.allow_raw_sql:
                if not user_override:
                    raise DriverPostgresError(
                        caller=self,
                        error="Raw SQL is globally disabled (allow_raw_sql=False).",
                    )
                self.warning(
                    msg=Event.Read.name,
                    step=Event.Check.name,
                    reason="User override: allow_raw_sql=True bypasses "
                    "global policy for this query.",
                    uri=uri[:120],
                )

            # 2. Safe mode: requires unsafe=True
            if self.safe_mode and not unsafe:
                if not user_override:
                    raise DriverPostgresError(
                        caller=self,
                        error="Raw SQL requires unsafe=True when safe_mode=True.",
                    )
                self.warning(
                    msg=Event.Read.name,
                    step=Event.Check.name,
                    reason="User override: safe_mode bypassed (unsafe not set).",
                    uri=uri[:120],
                )

            # 3. Safe mode: recomends bind parametre
            if self.safe_mode and not params:
                if not user_override:
                    raise DriverPostgresError(
                        caller=self,
                        error="Raw SQL requires params in safe_mode.",
                    )
                self.warning(
                    msg=Event.Read.name,
                    step=Event.Check.name,
                    reason="User override: no bind params — query may be "
                    "vulnerable to SQL injection.",
                    uri=uri[:120],
                )

        else:
            if self.validate_table_names:
                self._validate_table_name(uri)

        if max_rows:
            query = f"{query} LIMIT {int(max_rows)}"

        if self.log_queries:
            self.debug(
                msg=Event.Read.name,
                uri=query[:120],
                params=bool(params),
            )

        # ---------------- EXECUTE WITH RECONNECT ---------------- #

        try:
            df = self._execute_read(query, params)
        except PostgresError as e:
            if not self._try_reconnect():
                raise
            self.debug(
                msg=Event.Read.name,
                step=Event.Failed.name,
                error=str(e),
                uri=uri[:80],
            )
            df = self._execute_read(query, params)
        except DriverPostgresError:
            raise
        except Exception as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=str(e))
            raise DriverPostgresError(
                caller=self,
                error=f"read error: {e}",
            ) from e

        self.debug(
            msg=Event.Read.name,
            step=Event.Completed.name,
            rows=len(df),
            columns=list(df.columns),
        )

        return df

    def write(self, uri: str, data: object, **kwargs) -> str:
        if not uri:
            raise DriverPostgresError(
                caller=self,
                error="write: uri (table name) is required.",
            )

        schema: Optional[str] = kwargs.pop("schema", None)
        if_exists: str = kwargs.pop("if_exists", "append")
        index: bool = kwargs.pop("index", False)

        chunksize: int = kwargs.pop("chunksize", self.chunksize)
        method: str = kwargs.pop("method", self.write_method)
        transactional: bool = kwargs.pop("transactional", self.default_transaction)

        if self.validate_table_names:
            self._validate_table_name(uri)

        df = self._to_dataframe(data)

        if df.empty:
            self.warning(
                msg=Event.Write.name,
                step=Event.Check.name,
                error="Empty DataFrame — nothing to write.",
            )
            return uri

        self.debug(
            msg=Event.Write.name,
            step=Event.Started.name,
            uri=uri,
            schema=schema,
            rows=len(df),
            chunksize=chunksize,
        )

        # ---------------- EXECUTE WITH RECONNECT ---------------- #

        write_kwargs = dict(
            uri=uri,
            df=df,
            schema=schema,
            if_exists=if_exists,
            index=index,
            chunksize=chunksize,
            method=method,
            transactional=transactional,
            **kwargs,
        )

        if self.log_queries:
            self.debug(
                msg=Event.Write.name,
                write_kwargs=write_kwargs,
            )

        try:
            self._execute_write(**write_kwargs)
        except PostgresError as e:
            if not self._try_reconnect():
                raise
            self.debug(
                msg=Event.Write.name,
                step=Event.Failed.name,
                error=str(e),
                uri=uri,
            )
            self._execute_write(**write_kwargs)
        except DriverPostgresError:
            raise
        except Exception as e:
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=str(e))
            raise DriverPostgresError(
                caller=self,
                error=f"write error for table='{uri}': {e}",
            ) from e

        self.debug(msg=Event.Write.name, step=Event.Completed.name, uri=uri)

        return uri

    def search(self, pattern: str, **kwargs) -> Generator[str, None, None]:
        schema_filter: Optional[str] = kwargs.get("schema")

        self.debug(
            msg=Event.Search.name,
            step=Event.Started.name,
            pattern=pattern,
            schema=schema_filter or "(all)",
        )

        if schema_filter:
            stmt = text(
                "SELECT table_schema, table_name "
                "FROM information_schema.tables "
                "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
                "AND table_schema = :schema "
                "ORDER BY table_schema, table_name"
            )
            params = {"schema": schema_filter}
        else:
            stmt = text(
                "SELECT table_schema, table_name "
                "FROM information_schema.tables "
                "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
                "ORDER BY table_schema, table_name"
            )
            params = {}

        try:
            with self._get_connection().connect() as conn:
                result = conn.execute(stmt, params)
                for row in result:
                    qualified = f"{row.table_schema}.{row.table_name}"
                    if self._matches(qualified, pattern) or self._matches(row.table_name, pattern):
                        yield qualified
        except Exception as e:
            self.debug(msg=Event.Search.name, step=Event.Failed.name, error=str(e))
            raise DriverPostgresError(
                caller=self,
                error=f"search: error while listing tables: {e}",
            ) from e

        self.debug(msg=Event.Search.name, step=Event.Completed.name)

    # ---------------------------------------------------------------------- #
    # endregion public methods
    # ---------------------------------------------------------------------- #

    # ---------------------------------------------------------------------- #
    # region private methods
    # ---------------------------------------------------------------------- #
    def _get_connection(self) -> PostgresConnection:
        return self.connection_manager.get_connection(self.connection_name)

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

    def _execute_read(self, query: str, params: dict) -> pd.DataFrame:
        with self._get_connection().connect() as conn:
            return pd.read_sql(text(query), conn, params=params)

    def _execute_write(
        self,
        uri: str,
        df: pd.DataFrame,
        schema: Optional[str],
        if_exists: str,
        index: bool,
        chunksize: int,
        method: str,
        transactional: bool,
        **kwargs,
    ) -> None:
        """Executes a write operation within a managed connection context."""
        with self._get_connection().connect() as conn:
            if transactional:
                with conn.begin():
                    df.to_sql(
                        name=uri,
                        con=conn,
                        schema=schema,
                        if_exists=if_exists,
                        index=index,
                        chunksize=chunksize,
                        method=method,
                        **kwargs,
                    )
            else:
                df.to_sql(
                    name=uri,
                    con=conn,
                    schema=schema,
                    if_exists=if_exists,
                    index=index,
                    chunksize=chunksize,
                    method=method,
                    **kwargs,
                )

    def _to_dataframe(self, data: object) -> pd.DataFrame:
        if isinstance(data, pd.DataFrame):
            return data

        if isinstance(data, list):
            if not data:
                raise DriverPostgresError(
                    caller=self,
                    error="_to_dataframe: empty list.",
                )
            return pd.DataFrame(data)

        if isinstance(data, dict):
            return pd.DataFrame([data])

        raise DriverPostgresError(
            caller=self,
            error=f"_to_dataframe: unsupported type '{type(data).__name__}'.",
        )

    def _validate_table_name(self, name: str) -> None:
        if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_.]*$", name):
            raise DriverPostgresError(
                caller=self,
                error=f"Invalid table name: '{name}'",
            )

    def __repr__(self) -> str:
        return f"DriverPostgres[{self.connection_name}]"

    # ---------------------------------------------------------------------- #
    # endregion private methods
    # ---------------------------------------------------------------------- #

    # ---------------------------------------------------------------------- #
    # region static methods
    # ---------------------------------------------------------------------- #

    @classmethod
    def _is_sql(cls, uri: str) -> bool:
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
        return f"SELECT * FROM {stripped}"

    @staticmethod
    def _matches(name: str, pattern: str) -> bool:
        if not pattern or pattern == "*":
            return True
        if any(c in pattern for c in ("*", "?", "[")):
            return fnmatch.fnmatchcase(name.lower(), pattern.lower())
        return pattern.lower() in name.lower()

    # ---------------------------------------------------------------------- #
    # endregion static methods
    # ---------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# endregion Driver                                                            #
# --------------------------------------------------------------------------- #
