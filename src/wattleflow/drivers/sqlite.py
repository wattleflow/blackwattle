# Module name: drivers/sqlite.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional
from wattleflow.concrete import GenericDriver
from wattleflow.concrete.driver import DriverAction, DriverMetadata
from wattleflow.concrete.exception import DriverException
from wattleflow.enums.event import Event
from wattleflow.connections.sqlite import SqliteConnection

# endregion Imports                                                           #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class DriverSqliteError(DriverException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Driver                                                               #
# --------------------------------------------------------------------------- #


class DriverSqlite(GenericDriver):
    ALLOWED = [
        # The handle belongs to SqliteConnection, like every other driver in
        # this distribution; WorkflowFactory injects the manager because a
        # `connection_name` is declared.
        "connection_name",
        "connection_manager",
        "delete",
        "schema",
        "records",
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.ensure_live()

    # region private

    def _get_connection(self) -> SqliteConnection:
        connection = self.connection_manager.get_connection(self.connection_name)
        if not isinstance(connection, SqliteConnection):
            raise DriverSqliteError(
                caller=self,
                error=f"connection {self.connection_name!r} is a "
                f"{type(connection).__name__}, not a SqliteConnection.",
            )
        return connection

    @property
    def _conn(self) -> sqlite3.Connection:
        """The sqlite3 handle owned by the connection.

        Kept as a private property so the query methods below read unchanged;
        what moved is ownership, not the call sites.
        """
        connection = self._get_connection()
        connection.ensure_created()
        if connection._connection is None:
            raise DriverSqliteError(caller=self, error="sqlite handle is not open.")
        return connection._connection

    # region private

    def _create_schema(self) -> None:
        self.debug(msg=Event.Create.name, step=Event.Started.name)
        with self._conn:
            for table, spec in self.schema.items():
                cols = ", ".join(f'"{n}" {t}' for n, t in spec["columns"].items())
                constraints = spec.get("constraints", []) or []
                parts = [cols] + list(constraints)
                ddl = f'CREATE TABLE IF NOT EXISTS "{table}" ({", ".join(parts)})'
                self._conn.execute(ddl)
        self.debug(msg=Event.Create.name, step=Event.Completed.name)

    def _validate_schema(self, schema: Dict[str, Dict[str, Any]]) -> None:
        if not isinstance(schema, dict) or not schema:
            raise DriverSqliteError(caller=self, error="schema must be a non-empty dict")
        for table, spec in schema.items():
            if not isinstance(spec, dict) or "columns" not in spec:
                raise DriverSqliteError(
                    caller=self,
                    error=f"schema[{table!r}] missing 'columns' definition",
                )
            cols = spec["columns"]
            if not isinstance(cols, dict) or not cols:
                raise DriverSqliteError(
                    caller=self,
                    error=f"schema[{table!r}].columns must be a non-empty dict",
                )

    def _validate_table(self, table: str) -> None:
        if table not in self.schema:
            raise DriverSqliteError(
                caller=self,
                error=f"unknown table {table!r}; defined: {sorted(self.schema.keys())}",
            )

    def _validate_column(self, table: str, column: str) -> None:
        cols = self.schema[table]["columns"]
        if column not in cols:
            raise DriverSqliteError(
                caller=self,
                error=f"unknown column {column!r} in table {table!r}",
            )

    def _insert_records(self) -> None:
        self.debug(
            msg=Event.Write.name,
            step=Event.Started.name,
            scope="%s._insert_records" % self.name,
            delete=self.delete,
            count=len(self.records),
        )

        if not self.records:
            return

        if not isinstance(self.records, list):
            raise DriverSqliteError(
                caller=self,
                error="records must be a list of dicts",
            )

        first = self.records[0]
        if not isinstance(first, dict) or not first:
            raise DriverSqliteError(
                caller=self,
                error="each record must be a non-empty dict",
            )

        record_cols = set(first.keys())
        target_table: Optional[str] = None
        for table, spec in self.schema.items():
            defined = set(spec["columns"].keys())
            if record_cols.issubset(defined):
                target_table = table
                break

        if target_table is None:
            raise DriverSqliteError(
                caller=self,
                error=f"no table in schema matches record columns {sorted(record_cols)}",
            )

        for idx, row in enumerate(self.records):
            if not isinstance(row, dict) or set(row.keys()) != record_cols:
                raise DriverSqliteError(
                    caller=self,
                    error=f"records[{idx}] keys must equal {sorted(record_cols)}",
                )

        cols = sorted(record_cols)
        col_list = ", ".join(f'"{c}"' for c in cols)
        placeholders = ", ".join(["?"] * len(cols))
        sql = f'INSERT INTO "{target_table}" ({col_list}) VALUES ({placeholders})'

        try:
            with self._conn:
                if self.delete:
                    self._conn.execute(f'DELETE FROM "{target_table}"')
                    self.debug(msg=Event.Write.name, scope="insert", action="Deleting records")
                self._conn.executemany(
                    sql,
                    [[row[c] for c in cols] for row in self.records],
                )
        except sqlite3.Error as e:
            self.debug(
                msg=Event.Write.name, step=Event.Failed.name, table=target_table, error=str(e)
            )
            raise DriverSqliteError(caller=self, error=str(e), table=target_table) from e

        self.debug(
            msg=Event.Write.name,
            scope="insert",
            step=Event.Completed.name,
            table=target_table,
        )

    def __repr__(self) -> str:
        path = str(getattr(self._get_connection(), "path", None) or "?")
        return f"DriverSqlite[{path}, state={self._fsm.state.value}]"

    # endregion private

    # region Property
    def conn(self) -> Any:
        return self._conn

    # endregion Property

    # region lifecycle
    def load(self) -> None:
        self.debug(msg=Event.Load.name, step=Event.Started.name)

        self.delete = bool(self.delete) if self.delete is not None else True
        self._validate_schema(self.schema)

        connection = self._get_connection()
        path = Path(str(connection.path))
        db_existed = path.exists() and path.stat().st_size > 0

        # Opening the handle is the connection's job; the driver only asks for
        # it and then owns the schema and the seed records.
        connection.ensure_created()

        if not db_existed:
            self._create_schema()

        if self.records:
            self._insert_records()

        self.debug(
            msg=Event.Load.name,
            step=Event.Completed.name,
            path=str(self._get_connection().path),
            tables=list(self.schema.keys()),
        )

    def close(self) -> None:
        self.debug(msg=Event.Close.name, step=Event.Started.name)
        if not self.can(DriverAction.UNLOAD):
            return
        # The connection owns the handle and closes it; the driver must not.
        self.debug(msg=Event.Close.name, step=Event.Completed.name)

    # endregion lifecycle

    # region public API

    def metadata(self) -> DriverMetadata:
        return DriverMetadata(
            name=self.__class__.__name__,
            version="1.0",
            protocol="sqlite",
            capabilities=["read", "write", "validate"],
        )

    def read(self, **kwargs) -> List[Dict[str, Any]]:
        self.debug(msg=Event.Read.name, step=Event.Started.name, kwargs=kwargs)

        table_name = kwargs.pop("table", None)
        if table_name is None:
            cls_name = f"{self.name}.read(**kwargs)" or f"{self.__class__.__name__}.read(**kwargs)"
            self.exception(
                msg=Event.Read.name,
                error=f"{cls_name}: table must be supplied when calling method!",
            )
            raise DriverSqliteError(self, error=f"{cls_name}: Missing `table` name in **kwargs!")

        self._validate_table(table_name)
        where: Dict[str, Any] = kwargs.pop("where", {}) or {}
        joins: bool = bool(kwargs.pop("joins", False))

        for col in where:
            self._validate_column(table_name, col)

        sql = f'SELECT * FROM "{table_name}"'
        params: List[Any] = []
        if where:
            clauses = [f'"{c}" = ?' for c in where]
            sql += " WHERE " + " AND ".join(clauses)
            params.extend(where.values())

        try:
            cursor = self._conn.execute(sql, params)
            rows = [dict(r) for r in cursor.fetchall()]
        except sqlite3.Error as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, table=table_name, error=str(e))
            raise DriverSqliteError(caller=self, error=str(e), table=table_name) from e

        if joins:
            for row in rows:
                row["patterns"] = self.read("patterns", where={"entitet_id": row["id"]})

        self.debug(msg=Event.Read.name, step=Event.Completed.name, rows=len(rows))
        return rows

    def write(self, uri: str, row: Dict[str, Any], **kwargs) -> int:
        """Insert a single row into a schema table.

        Returns the lastrowid. WriteStrategy must call validate() prior or
        rely on internal validation done here.
        """
        self.debug(msg=Event.Write.name, step=Event.Started.name, uri=uri)

        self.validate(uri, row)

        cols = list(row.keys())
        placeholders = ", ".join(["?"] * len(cols))
        col_list = ", ".join(f'"{c}"' for c in cols)
        sql = f'INSERT INTO "{uri}" ({col_list}) VALUES ({placeholders})'

        try:
            with self._conn:
                cursor = self._conn.execute(sql, [row[c] for c in cols])
                rowid = cursor.lastrowid
        except sqlite3.IntegrityError as e:
            self.debug(msg=Event.Write.name, step=Event.Failed.name, uri=uri, error=str(e))
            raise DriverSqliteError(caller=self, error=str(e), uri=uri) from e
        except sqlite3.Error as e:
            self.debug(msg=Event.Write.name, step=Event.Failed.name, uri=uri, error=str(e))
            raise DriverSqliteError(caller=self, error=str(e), uri=uri) from e

        self.debug(msg=Event.Write.name, step=Event.Completed.name, uri=uri, rowid=rowid)
        return rowid

    def validate(self, table: str, row: Dict[str, Any]) -> None:
        self._validate_table(table)

        if not isinstance(row, dict) or not row:
            raise DriverSqliteError(
                caller=self,
                error=f"validate: row must be a non-empty dict for table {table!r}",
            )

        defined = set(self.schema[table]["columns"].keys())
        provided = set(row.keys())
        unknown = provided - defined
        if unknown:
            raise DriverSqliteError(
                caller=self,
                error=f"validate: unknown columns {sorted(unknown)} for table {table!r}",
            )

    # endregion public API


# --------------------------------------------------------------------------- #
# endregion Driver                                                            #
# --------------------------------------------------------------------------- #
