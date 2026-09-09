# Module name: connections/elasticsearch.py
# Author: (wattleflow@outlook.com)
# Copyright: 2022-2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# Dependency:
#   pip install elasticsearch
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from contextlib import contextmanager
from typing import Any, ClassVar, Generator, Optional, Tuple, Union
from wattleflow.concrete.connection import (
    Connection,
    ConnectionAction,
    ConnectionState,
    GenericConnection,
)
from wattleflow.concrete.exception import ConnectionException
from wattleflow.enums.event import Event

try:
    from elasticsearch import Elasticsearch  # noqa: F401
except Exception as e:
    raise ModuleNotFoundError(
        f"Missing required package to run this code: {__file__}.\n"
        "Please install it using:\n\t`pip install elasticsearch`"
    ) from e
from wattleflow.decorators.oscal import oscal_connection
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Errors                                                               #
# --------------------------------------------------------------------------- #


class ElasticSearchConnectionError(ConnectionException):
    pass


# --------------------------------------------------------------------------- #
# endregion Errors                                                            #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Classes                                                              #
# --------------------------------------------------------------------------- #


@oscal_connection(strict=False)
class ElasticSearchConnection(GenericConnection):
    ALLOWED = [
        "connection_name",
        "lazy_loading",
        "hosts",
        "cloud_id",
        "username",
        "password",
        "api_key",
        "bearer_auth",
        "ca_certs",
        "verify_certs",
        "ssl_show_warn",
        "request_timeout",
        "client_options",
        "log_connection",
    ]
    # OSCAL: api_key/bearer/password, plus `ca_certs` and `verify_certs`.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ("ac-3", "ia-5", "sc-8")

    # ---------------------------------------------------------------------- #
    # region Auth helpers
    # ---------------------------------------------------------------------- #

    def _resolve_basic_auth(self) -> Optional[Tuple[str, str]]:
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

    def _build_client_kwargs(self) -> dict:
        kwargs: dict = {}

        cloud_id = getattr(self, "cloud_id", None)
        hosts = getattr(self, "hosts", None)
        if cloud_id:
            kwargs["cloud_id"] = cloud_id
        elif hosts:
            kwargs["hosts"] = list(hosts) if isinstance(hosts, (list, tuple)) else [hosts]
        else:
            raise ElasticSearchConnectionError(
                caller=self,
                error="ElasticSearchConnection requires either 'hosts' or 'cloud_id'.",
            )

        api_key = self._resolve_api_key()
        if api_key is not None:
            kwargs["api_key"] = api_key
        else:
            basic = self._resolve_basic_auth()
            if basic is not None:
                kwargs["basic_auth"] = basic

        bearer = getattr(self, "bearer_auth", None)
        if bearer:
            kwargs["bearer_auth"] = bearer

        ca_certs = getattr(self, "ca_certs", None)
        if ca_certs:
            kwargs["ca_certs"] = ca_certs

        verify_certs = getattr(self, "verify_certs", None)
        if verify_certs is not None:
            kwargs["verify_certs"] = bool(verify_certs)

        ssl_show_warn = getattr(self, "ssl_show_warn", None)
        if ssl_show_warn is not None:
            kwargs["ssl_show_warn"] = bool(ssl_show_warn)

        request_timeout = getattr(self, "request_timeout", None)
        if request_timeout is not None:
            kwargs["request_timeout"] = request_timeout

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
            raise ElasticSearchConnectionError(
                caller=self,
                error=f"Cannot create connection in state '{self.state.value}'",
            )

        try:
            client_kwargs = self._build_client_kwargs()
            client = Elasticsearch(**client_kwargs)

            self._engine = client
            self._connection = None

            try:
                info: dict = dict(client.info())
                self._version = str(info.get("version", {}).get("number", ""))
            except Exception:
                self._version = ""

        except ElasticSearchConnectionError:
            raise
        except Exception as e:
            self.notify(
                self,
                error=f"Elasticsearch client cannot be created: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=str(e))
            raise ElasticSearchConnectionError(
                caller=self,
                error=f"Elasticsearch client cannot be created: {e}",
            ) from e

        self.debug(
            msg=Event.Create.name,
            step=Event.Completed.name,
            name=self.connection_name,
            state=self.state.value,
            es_version=self._version,
        )

    @contextmanager
    def connect(self) -> Generator[Connection, None, None]:
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
            raise ElasticSearchConnectionError(
                caller=self,
                error=f"Cannot connect in state '{self.state.value}'",
            )

        if self._engine is None:
            self.notify(
                self,
                error="Elasticsearch client is not initialised",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            raise ElasticSearchConnectionError(
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
            raise ElasticSearchConnectionError(caller=self, error=str(e)) from e

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
                    self._engine.close()
                except Exception as e:
                    self.notify(
                        self,
                        error=f"Error closing Elasticsearch client: {e}",
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
        endpoint: Any = getattr(self, "cloud_id", None) or getattr(self, "hosts", "?")
        return f"{self.name}:{self.state.value}[endpoint={endpoint}]"


# --------------------------------------------------------------------------- #
# endregion Classes                                                           #
# --------------------------------------------------------------------------- #
