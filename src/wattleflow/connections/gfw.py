# Module name: connections/gfw.py
# Author: (wattleflow@outlook.com)
# Copyright: 2022-2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# Dependency:
#   pip install requests
# --------------------------------------------------------------------------- #
# Description: Global Fishing Watch v3 REST API connection. Wraps an
# authenticated requests.Session and exposes it as the connection engine. The
# session is reused across requests; per-call lifecycle is handled via the
# connect() context manager defined by GenericConnection.
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from contextlib import contextmanager
from typing import ClassVar, Generator, Optional, Tuple
from wattleflow.concrete.connection import Connection
from wattleflow.concrete.connection import (
    ConnectionAction,
    ConnectionState,
)
from wattleflow.concrete.exception import AuditException
from wattleflow.enums.event import Event
from wattleflow.concrete.connection import GenericConnection

try:
    import requests  # noqa: F401
except Exception as e:
    raise ModuleNotFoundError(
        f"Missing required package to run this code: {__file__}.\n"
        "Please install it using:\n\tpip install requests"
    ) from e

from wattleflow.decorators.oscal import oscal_connection
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #
GFW_DEFAULT_BASE_URL = "https://gateway.api.globalfishingwatch.org"
GFW_AUTH_PATH = "/v3/auth/user"

# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class GFWConnectionError(AuditException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Classes                                                              #
# --------------------------------------------------------------------------- #


@oscal_connection(strict=False)
class GFWConnection(GenericConnection):
    ALLOWED = [
        "connection_name",
        "lazy_loading",
        "api_key",
        "base_url",
        "request_timeout",
        "verify_certs",
        "validate_token",
        "log_connection",
    ]
    # OSCAL: api_key/bearer token, plus `verify_certs`.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ("ac-3", "ia-5", "sc-8")

    # ---------------------------------------------------------------------- #
    # region Helpers
    # ---------------------------------------------------------------------- #

    def _resolve_base_url(self) -> str:
        # Preset attribute lookup goes through GenericConnection.__getattr__;
        # avoid declaring a class-level property that would shadow it.
        url = self._preset._values.get("base_url") or GFW_DEFAULT_BASE_URL
        return str(url).rstrip("/")

    def _build_session(self) -> "requests.Session":
        api_key: Optional[str] = getattr(self, "api_key", None)
        if not api_key:
            raise GFWConnectionError(
                caller=self,
                error="GFWConnection requires 'api_key' "
                "(set GFW_API_KEY in env or pass via kwargs).",
            )

        session = requests.Session()
        session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

        verify_certs = getattr(self, "verify_certs", None)
        if verify_certs is not None:
            session.verify = bool(verify_certs)

        return session

    def _validate_token(self, session: "requests.Session") -> None:
        timeout: int = int(getattr(self, "request_timeout", 15) or 15)
        url = f"{self._resolve_base_url()}{GFW_AUTH_PATH}"

        try:
            resp = session.get(url, timeout=timeout)
        except requests.RequestException as e:
            self.debug(msg=Event.Validate.name, step=Event.Failed.name, error=str(e))
            raise GFWConnectionError(
                caller=self,
                error=f"GFW auth probe network error: {e}",
            ) from e

        if resp.status_code in (401, 403):
            raise GFWConnectionError(
                caller=self,
                error=f"GFW auth probe rejected token (HTTP {resp.status_code}).",
            )

        if resp.status_code >= 400:
            raise GFWConnectionError(
                caller=self,
                error=f"GFW auth probe failed: HTTP {resp.status_code} at {url}",
            )

    # endregion Helpers

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
            raise GFWConnectionError(
                caller=self,
                error=f"Cannot create connection in state '{self.state.value}'",
            )

        try:
            session = self._build_session()

            validate = getattr(self, "validate_token", None)
            if validate is None or bool(validate):
                self._validate_token(session)

            self._engine = session
            self._connection = None
            self._version = "v3"

        except GFWConnectionError:
            raise
        except Exception as e:
            self.notify(
                self,
                error=f"GFW session cannot be created: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=str(e))
            raise GFWConnectionError(
                caller=self,
                error=f"GFW session cannot be created: {e}",
            ) from e

        self.debug(
            msg=Event.Create.name,
            step=Event.Completed.name,
            name=self.connection_name,
            state=self.state.value,
            base_url=self._resolve_base_url(),
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
            raise GFWConnectionError(
                caller=self,
                error=f"Cannot connect in state '{self.state.value}'",
            )

        if self._engine is None:
            self.notify(
                self,
                error="GFW session is not initialised",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            raise GFWConnectionError(
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
            raise GFWConnectionError(caller=self, error=str(e)) from e

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
                note="session still alive; call ensure_closed() to release",
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
                        error=f"Error closing GFW session: {e}",
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

    def __repr__(self) -> str:
        return f"{self.name}:{self.state.value}[base_url={self._resolve_base_url()}]"


# --------------------------------------------------------------------------- #
# endregion Classes                                                           #
# --------------------------------------------------------------------------- #
