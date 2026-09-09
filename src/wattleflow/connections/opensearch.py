# Module name: connections/opensearch.py
# Author: (wattleflow@outlook.com)
# Copyright: 2022-2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# Dependency:
#   pip install opensearch-py
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from contextlib import contextmanager
from typing import Any, ClassVar, Generator, List, Optional, Tuple, Union
from wattleflow.concrete.connection import (
    ConnectionAction,
    ConnectionState,
    GenericConnection,
)
from wattleflow.concrete.exception import AuditException
from wattleflow.enums.event import Event

try:
    from opensearchpy import OpenSearch  # noqa: F401
except Exception as e:
    raise ModuleNotFoundError(
        f"Missing required package to run this code: {__file__}.\n"
        "Please install it using:\n\tpip install opensearch-py"
    ) from e

from wattleflow.decorators.oscal import oscal_connection
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class OpenSearchConnectionError(AuditException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Classes                                                              #
# --------------------------------------------------------------------------- #


@oscal_connection(strict=False)
class OpenSearchConnection(GenericConnection):
    ALLOWED = [
        "connection_name",
        "lazy_loading",
        "hosts",
        "username",
        "password",
        "api_key",
        "use_ssl",
        "verify_certs",
        "ca_certs",
        "ssl_show_warn",
        "ssl_assert_hostname",
        "ssl_assert_fingerprint",
        "request_timeout",
        "client_options",
        "log_connection",
    ]
    # OSCAL: api_key/user/password, plus `use_ssl`, `ca_certs`, `verify_certs`.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ("ac-3", "ia-5", "sc-8")

    # ---------------------------------------------------------------------- #
    # region Auth helpers
    # ---------------------------------------------------------------------- #

    def _resolve_http_auth(self) -> Optional[Tuple[str, str]]:
        user = getattr(self, "username", None)
        pwd = getattr(self, "password", None)
        if user and pwd:
            return (user, pwd)
        return None

    def _resolve_api_key(self) -> Optional[Union[str, Tuple[str, str]]]:
        api_key = getattr(self, "api_key", None)
        if not api_key:
            return None
        if isinstance(api_key, (list, tuple)) and len(api_key) == 2:
            return tuple(api_key)
        return str(api_key)

    def _normalise_hosts(self, hosts: Any) -> List[Any]:
        if isinstance(hosts, (list, tuple)):
            return list(hosts)
        return [hosts]

    def _build_client_kwargs(self) -> dict:
        hosts = getattr(self, "hosts", None)
        if not hosts:
            raise OpenSearchConnectionError(
                caller=self,
                error="OpenSearchConnection requires 'hosts'.",
            )

        kwargs: dict = {"hosts": self._normalise_hosts(hosts)}

        api_key = self._resolve_api_key()
        if api_key is not None:
            kwargs["api_key"] = api_key
        else:
            basic = self._resolve_http_auth()
            if basic is not None:
                kwargs["http_auth"] = basic

        for name in (
            "use_ssl",
            "verify_certs",
            "ssl_show_warn",
            "ssl_assert_hostname",
            "ssl_assert_fingerprint",
            "ca_certs",
            "request_timeout",
        ):
            value = getattr(self, name, None)
            if value is not None:
                kwargs[name] = value

        extra = getattr(self, "client_options", None) or {}
        if isinstance(extra, dict):
            kwargs.update(extra)

        return kwargs

    # endregion Auth helpers

    # ---------------------------------------------------------------------- #
    # region Lifecycle
    # ---------------------------------------------------------------------- #

    def create_connection(self) -> None:
        self.debug(
            msg=Event.Create.name,
            step=Event.Started.name,
            name=self.connection_name,
            state=self.state.value,
        )

        if self.state in (
            ConnectionState.CREATED,
            ConnectionState.CONNECTED,
            ConnectionState.CONNECTING,
        ):
            self.debug(
                msg=Event.Create.name,
                step=Event.Check.name,
                reason="connection already created",
                state=self.state.value,
            )
            return

        if self.state is ConnectionState.FAILED:
            raise OpenSearchConnectionError(
                caller=self,
                error=f"Cannot create connection in state '{self.state.value}'",
            )

        try:
            client_kwargs = self._build_client_kwargs()
            client = OpenSearch(**client_kwargs)

            self._engine = client
            self._connection = None

            try:
                info: dict = dict(client.info())
                self._version = str(info.get("version", {}).get("number", ""))
            except Exception:
                self._version = ""

        except OpenSearchConnectionError:
            raise
        except Exception as e:
            self.notify(
                self,
                error=f"OpenSearch client cannot be created: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=str(e))
            raise OpenSearchConnectionError(
                caller=self,
                error=f"OpenSearch client cannot be created: {e}",
            ) from e

        self.debug(
            msg=Event.Create.name,
            step=Event.Completed.name,
            name=self.connection_name,
            state=self.state.value,
            os_version=self._version,
        )

    @contextmanager
    def connect(self) -> Generator[OpenSearch, None, None]:
        self._ensure_created()

        self.debug(
            msg=Event.Connect.name,
            connection_name=self.connection_name,
            state=self.state.value,
        )

        if self.state is not ConnectionState.CREATED:
            self.notify(
                self,
                error=f"Cannot connect in state '{self.state.value}'",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            raise OpenSearchConnectionError(
                caller=self,
                error=f"Cannot connect in state '{self.state.value}'",
            )

        if self._engine is None:
            self.notify(
                self,
                error="OpenSearch client is not initialised",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            raise OpenSearchConnectionError(
                caller=self,
                error=f"{self.name}.connect: engine is None",
            )

        self._fsm.apply(ConnectionAction.CONNECT)

        try:
            self._connection = self._engine
            self._fsm.apply(ConnectionAction.CONNECT_OK)
        except Exception as e:
            self._fsm.apply(ConnectionAction.CONNECT_FAIL)
            self.debug(msg=Event.Connect.name, step=Event.Failed.name, error=str(e))
            raise OpenSearchConnectionError(caller=self, error=str(e)) from e

        self.debug(
            msg=Event.Connected.name,
            connection_name=self.connection_name,
            state=self.state.value,
        )

        try:
            yield self._connection
        except Exception as e:
            self.notify(
                self,
                error=f"Error during connection use: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Connect.name, step=Event.Failed.name, error=str(e))
            raise
        finally:
            self._connection = None
            self._fsm.apply(ConnectionAction.DISCONNECT)
            self.debug(
                msg=Event.Disconnected.name,
                connection_name=self.connection_name,
                note="client still alive; call ensure_closed() to close",
            )

    def disconnect(self) -> None:
        self.debug(
            msg=Event.Disconnect.name,
            connection_name=self.connection_name,
            state=self.state.value,
        )

        try:
            if self._connection:
                self._connection = None
            if self._engine is not None:
                try:
                    # opensearch-py 2.x exposes .close(); 1.x via .transport.close()
                    close = getattr(self._engine, "close", None)
                    if callable(close):
                        close()
                    else:
                        self._engine.transport.close()
                except Exception as e:
                    self.notify(
                        self,
                        error=f"Error closing OpenSearch client: {e}",
                        connection_name=self.connection_name,
                        state=self.state.value,
                    )
                finally:
                    self._engine = None
        finally:
            self._version = ""
            self.debug(
                msg=Event.Disconnected.name,
                connection_name=self.connection_name,
                state=self.state.value,
            )

    # endregion Lifecycle

    def ping(self) -> bool:
        self._ensure_created()
        try:
            return bool(self._engine.ping())
        except Exception as e:
            self.warning(
                msg=Event.Probe.name,
                step=Event.Failed.name,
                error=str(e),
                connection_name=self.connection_name,
            )
            return False

    def __repr__(self) -> str:
        endpoint: Any = getattr(self, "hosts", "?")
        return f"{self.name}:{self.state.value}[endpoint={endpoint}]"


# --------------------------------------------------------------------------- #
# endregion Classes                                                           #
# --------------------------------------------------------------------------- #
