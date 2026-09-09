# Module name: connections/solr.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# Dependency:
#   pip install pysolr
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from contextlib import contextmanager
from typing import Any, ClassVar, Generator, Optional, Tuple
from wattleflow.concrete.connection import Connection
from wattleflow.concrete.connection import (
    ConnectionAction,
    ConnectionState,
    GenericConnection,
)
from wattleflow.concrete.exception import AuditException
from wattleflow.enums.event import Event

try:
    import pysolr  # noqa: F401
except Exception as e:
    raise ModuleNotFoundError(
        f"Missing required package to run this code: [{__file__}].\n"
        "Please install it using:\n\tpip install pysolr"
    ) from e
    pysolr = None
from wattleflow.decorators.oscal import oscal_connection
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class SolrConnectionError(AuditException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Connections                                                          #
# --------------------------------------------------------------------------- #


@oscal_connection(strict=False)
class SolrConnection(GenericConnection):
    """Wattleflow connection wrapping a :class:`pysolr.Solr` client.
    Resolves its endpoint from either ``url`` (full Solr core URL — e.g.
    ``http://host:8983/solr/mycore``) or from ``url`` + ``core`` (joined).
    Basic auth is supported through ``username`` / ``password``.
    """

    ALLOWED = [
        "connection_name",
        "lazy_loading",
        "url",
        "core",
        "username",
        "password",
        "timeout",
        "always_commit",
        "verify_certs",
        "client_options",
        "log_queries",
    ]
    # OSCAL: user/password, plus `verify_certs`.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ("ac-3", "ia-5", "sc-8")

    # ---------------------------------------------------------------------- #
    # region Endpoint helpers
    # ---------------------------------------------------------------------- #

    def _resolve_endpoint(self) -> str:
        url = (getattr(self, "url", None) or "").rstrip("/")
        if not url:
            raise SolrConnectionError(
                caller=self,
                error="SolrConnection requires 'url' (and optionally 'core').",
            )
        core = (getattr(self, "core", None) or "").strip("/")
        if core and not url.rstrip("/").endswith(f"/{core}"):
            url = f"{url}/{core}"
        return url

    def _resolve_basic_auth(self) -> Optional[Tuple[str, str]]:
        user = getattr(self, "username", None)
        pwd = getattr(self, "password", None)
        if user and pwd:
            return (user, pwd)
        return None

    def _build_client_kwargs(self) -> dict:
        kwargs: dict = {}
        timeout = getattr(self, "timeout", None)
        if timeout is not None:
            kwargs["timeout"] = float(timeout)
        always_commit = getattr(self, "always_commit", None)
        if always_commit is not None:
            kwargs["always_commit"] = bool(always_commit)
        basic = self._resolve_basic_auth()
        if basic is not None:
            kwargs["auth"] = basic
        extra = getattr(self, "client_options", None) or {}
        if isinstance(extra, dict):
            kwargs.update(extra)
        return kwargs

    # endregion Endpoint helpers

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
            raise SolrConnectionError(
                caller=self,
                error=f"Cannot create connection in state '{self.state.value}'",
            )

        try:
            endpoint = self._resolve_endpoint()
            client_kwargs = self._build_client_kwargs()
            client = pysolr.Solr(endpoint, **client_kwargs)
            self._engine = client
            self._connection = None
            try:
                # ping is cheap — surfaces auth/network failure early
                client.ping()
            except Exception:
                # tolerate ping failure on creation; full failure raised on use
                pass
        except SolrConnectionError:
            raise
        except Exception as e:
            self.notify(
                self,
                error=f"Solr client cannot be created: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=str(e))
            raise SolrConnectionError(
                caller=self,
                error=f"Solr client cannot be created: {e}",
            ) from e

        self.debug(
            msg=Event.Create.name,
            step=Event.Completed.name,
            name=self.connection_name,
            state=self.state.value,
            endpoint=endpoint,
        )

    @contextmanager
    def connect(self) -> Generator[Connection, None, None]:
        self._ensure_created()

        if self.state is not ConnectionState.CREATED:
            raise SolrConnectionError(
                caller=self,
                error=f"Cannot connect in state '{self.state.value}'",
            )

        if self._engine is None:
            raise SolrConnectionError(
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
            raise SolrConnectionError(caller=self, error=str(e)) from e

        try:
            yield self._connection
        finally:
            self._connection = None
            self._fsm.apply(ConnectionAction.DISCONNECT)

    def disconnect(self) -> None:
        try:
            if self._connection is not None:
                self._connection = None
            if self._engine is not None:
                self._engine = None
        finally:
            self.debug(
                msg=Event.Disconnected.name,
                connection_name=self.connection_name,
                state=self.state.value,
            )

    # endregion Lifecycle

    def ping(self) -> bool:
        self._ensure_created()
        try:
            self._engine.ping()
            return True
        except Exception as e:
            self.warning(
                msg=Event.Probe.name,
                step=Event.Failed.name,
                error=str(e),
                connection_name=self.connection_name,
            )
            return False

    def __repr__(self) -> str:
        endpoint: Any = getattr(self, "url", "?")
        core: Any = getattr(self, "core", "")
        return f"{self.name}:{self.state.value}[url={endpoint}, core={core}]"


# --------------------------------------------------------------------------- #
# endregion Connections                                                       #
# --------------------------------------------------------------------------- #
