# Module name: connections/sftp_paramiko.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2025 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# Dependencies:
#   pip install paramiko
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import os
from contextlib import contextmanager
from typing import ClassVar, Generator, Tuple
from wattleflow.concrete.connection import Connection
from wattleflow.concrete.connection import (
    ConnectionAction,
    ConnectionState,
    GenericConnection,
)
from wattleflow.concrete.exception import ConnectionException
from wattleflow.enums.event import Event

try:
    from paramiko import (
        AuthenticationException,
        BadHostKeyException,
        RejectPolicy,
        SSHClient,
        SFTPClient,  # noqa: F401
        SSHException,
        __version__,
    )  # noqa: F401
except Exception as e:
    raise ModuleNotFoundError(
        f"Missing required package to run this code: [{__file__}].\n"
        "Please install it using:\n\tpip install paramiko"
    ) from e


from wattleflow.decorators.oscal import oscal_connection
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class SFTPConnectionError(ConnectionException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Connections                                                          #
# --------------------------------------------------------------------------- #


@oscal_connection(strict=False)
class SFTPConnection(GenericConnection):
    ALLOWED = [
        "connection_name",
        "lazy_loading",
        "host",
        "port",
        "username",
        "password",
        "passphrase",
        "key_filename",
        "look_for_keys",
        "allow_agent",
        "timeout",
        "compress",
        "log_connection",
    ]
    # OSCAL: key_filename/passphrase/password over SSH — not a TLS path, so sc-8 is
    # not claimed; the SSH transport crypto belongs to paramiko.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ("ac-3", "ia-5")

    def create_connection(self) -> None:
        self._engine = None
        self._connection = None
        self._version = str(__version__)

    @contextmanager
    def connect(self) -> Generator[Connection, None, None]:
        self._ensure_created()

        self.debug(
            msg=Event.Connecting.name,
            connection=self._connection_name,
            status=Event.Authenticating.value,
            state=self.state.value,
        )

        self._fsm.apply(ConnectionAction.CONNECT)

        try:
            self._engine = SSHClient()

            self._engine.load_system_host_keys()

            known_hosts = os.path.expanduser("~/.ssh/known_hosts")

            if os.path.isfile(known_hosts):
                self._engine.load_host_keys(known_hosts)

            self._engine.set_missing_host_key_policy(RejectPolicy())

            self._engine.connect(
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                passphrase=self.passphrase,
                key_filename=self.key_filename,
                look_for_keys=self.look_for_keys,
                allow_agent=self.allow_agent,
                timeout=self.timeout,
                compress=self.compress,
            )

            self._connection = self._engine.open_sftp()
            self._fsm.apply(ConnectionAction.CONNECT_OK)

            self.debug(
                msg=Event.Connected.name,
                host=self.host,
                port=self.port,
                user=self.username,
                state=self.state.value,
            )

            try:
                yield self._connection  # type: ignore
            finally:
                if self._connection:
                    try:
                        self._connection.close()
                    except Exception:
                        pass
                    finally:
                        self._connection = None  # type: ignore
                if self._engine:
                    try:
                        self._engine.close()  # type: ignore
                    except Exception:
                        pass
                    finally:
                        self._engine = None
                self._fsm.apply(ConnectionAction.DISCONNECT)
                self.debug(msg=Event.Disconnected.name, state=self.state.value)

        except AuthenticationException as e:
            self._fsm.apply(ConnectionAction.CONNECT_FAIL)
            self.notify(
                self,
                error=f"Authentication failed: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Connecting.name, step=Event.Failed.name, error=str(e))
            raise SFTPConnectionError(caller=self, error=f"Authentication failed: {e}") from e
        except BadHostKeyException as e:
            self._fsm.apply(ConnectionAction.CONNECT_FAIL)
            self.notify(
                self,
                error=f"Bad host key: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Connecting.name, step=Event.Failed.name, error=str(e))
            raise SFTPConnectionError(caller=self, error=f"Bad host key: {e}") from e
        except SSHException as e:
            self._fsm.apply(ConnectionAction.CONNECT_FAIL)
            self.notify(
                self,
                error=f"SSH error: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Connecting.name, step=Event.Failed.name, error=str(e))
            raise SFTPConnectionError(caller=self, error=f"SSH error: {e}") from e
        except Exception as e:
            if self._fsm.state is ConnectionState.CONNECTING:
                self._fsm.apply(ConnectionAction.CONNECT_FAIL)
            self.notify(
                self,
                error=f"Connection error: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Connecting.name, step=Event.Failed.name, error=str(e))
            raise SFTPConnectionError(caller=self, error=f"Connection error: {e}") from e

    def disconnect(self) -> None:
        self.debug(msg=Event.Disconnecting.name, state=self.state.value)

        try:
            if getattr(self, "_connection", None):
                try:
                    self._connection.close()
                except Exception:
                    pass
                finally:
                    self._connection = None  # type: ignore

            if getattr(self, "_engine", None):
                try:
                    self._engine.close()  # type: ignore
                except Exception:
                    pass
                finally:
                    self._engine = None
        finally:
            self.debug(msg=Event.Disconnected.name, state=self.state.value)


# --------------------------------------------------------------------------- #
# endregion Connections                                                       #
# --------------------------------------------------------------------------- #
