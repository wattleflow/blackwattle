# Module name: connections/sqlite.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import ClassVar, Generator, Tuple
from wattleflow.concrete.connection import (
    ConnectionAction,
    ConnectionState,
    GenericConnection,
)
from wattleflow.concrete.exception import ConnectionException
from wattleflow.enums.event import Event
from wattleflow.decorators.oscal import oscal_connection
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["SqliteConnection", "SqliteConnectionError"]


class SqliteConnectionError(ConnectionException):
    pass


# --------------------------------------------------------------------------- #
# region Connection                                                           #
# --------------------------------------------------------------------------- #


@oscal_connection(strict=False)
class SqliteConnection(GenericConnection):
    """Owns the sqlite3 handle so the driver does not open one of its own.

    `sqlite3` is stdlib, but the database is still an external store reached
    through a path and a schema — the driver must not hold the handle itself.
    """

    ALLOWED = [
        "connection_name",
        "lazy_loading",
        "path",
        "create",
        "timeout",
        "log_connection",
    ]
    # OSCAL: the file path is the whole access boundary — no authenticator is
    # exchanged and no transport is involved, so neither ia-5 nor sc-8 applies.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ("ac-3",)

    def create_connection(self) -> None:
        self.debug(msg=Event.Create.name, step=Event.Started.name, state=self.state.value)

        if self.state in (
            ConnectionState.CREATED,
            ConnectionState.CONNECTED,
            ConnectionState.CONNECTING,
        ):
            self.warning(
                msg=Event.Create.name,
                step=Event.Check.name,
                reason="connection already created",
                state=self.state.value,
            )
            return

        if self.state is ConnectionState.FAILED:
            raise SqliteConnectionError(
                caller=self,
                error=f"Cannot create connection in state '{self.state.value}'",
            )

        path = Path(str(getattr(self, "path", "") or ""))
        if not str(path):
            raise SqliteConnectionError(caller=self, error="path is required.")

        # `create` governs the DIRECTORY; sqlite3 makes the file itself.
        if not path.parent.exists():
            if not getattr(self, "create", True):
                raise SqliteConnectionError(
                    caller=self,
                    error=f"parent directory does not exist: {path.parent}",
                )
            path.parent.mkdir(parents=True, exist_ok=True)

        # The FSM is driven by GenericConnection.ensure_created(), which wraps
        # this call with CREATE / CREATE_OK / CREATE_FAIL — touching it here
        # would double-apply and land the machine in FAILED.
        try:
            self._connection = sqlite3.connect(
                str(path),
                timeout=float(getattr(self, "timeout", None) or 5.0),
                check_same_thread=False,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON;")
        except Exception as e:
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=str(e))
            raise SqliteConnectionError(caller=self, error=f"create error: {e}") from e

        self.debug(msg=Event.Created.name, path=str(path), state=self.state.value)

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        self._ensure_created()

        if self._connection is None:
            raise SqliteConnectionError(caller=self, error=f"{self.name}.connect: handle is None")

        if self._fsm.can(ConnectionAction.CONNECT):
            self._fsm.apply(ConnectionAction.CONNECT)
            self._fsm.apply(ConnectionAction.CONNECT_OK)

        self.debug(msg=Event.Connected.name, state=self.state.value)

        # A file handle is not a pooled session: it stays open for the process
        # and only `disconnect()` closes it, so the block must not close it.
        try:
            yield self._connection
        except Exception as e:
            self.notify(self, error=f"Error during connection use: {e}", state=self.state.value)
            self.debug(msg=Event.Connect.name, step=Event.Failed.name, error=str(e))
            raise

    def disconnect(self) -> None:
        self.debug(msg=Event.Disconnect.name, state=self.state.value)
        try:
            if self._connection is not None:
                try:
                    self._connection.close()
                except Exception as e:
                    self.notify(self, error=f"Error closing connection: {e}")
                finally:
                    self._connection = None
                    if self._fsm.can(ConnectionAction.DISCONNECT):
                        self._fsm.apply(ConnectionAction.DISCONNECT)
        finally:
            self.debug(msg=Event.Disconnected.name, state=self.state.value)

    def __repr__(self) -> str:
        return f"{self.name}({getattr(self, 'path', None)}, state={self.state.value})"


# --------------------------------------------------------------------------- #
# endregion Connection                                                        #
# --------------------------------------------------------------------------- #
