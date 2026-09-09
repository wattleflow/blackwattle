# Module Name: connections/aisstream.py
# Author: (wattleflow@outlook.com)
# Copyright: (c) 2022-2026 WattleFlow
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# Dependency:                                                                 #
#   pip install websockets                                                    #
# --------------------------------------------------------------------------- #
# AISStream WebSocket connection. Stores configuration (API key, WebSocket
# URL, bounding boxes, message types). Processor reads the connection
# property and manages the WebSocket session lifecycle (open/reconnect).
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from contextlib import contextmanager
from typing import Any, ClassVar, Dict, Generator, Tuple
from wattleflow.concrete.connection import (
    ConnectionAction,
    ConnectionState,
    GenericConnection,
)
from wattleflow.concrete.exception import ConnectionException
from wattleflow.enums.event import Event

try:
    import websockets  # noqa: F401
except Exception as e:
    raise ModuleNotFoundError(
        f"Missing required package to run this code: {__file__}.\n"
        "Please install it using:\n\tpip install websockets"
    ) from e

from wattleflow.decorators.oscal import oscal_connection
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #
KEY_API_KEY = "api_key"
KEY_BOUNDING_BOXES = "bounding_boxes"
KEY_CONNECTION_NAME = "connection_name"
KEY_LAZY_LOADING = "lazy_loading"
KEY_WS_URL = "ws_url"
KEY_MESSAGE_TYPES = "message_types"
AISSTREAM_DEFAULT_URL = "wss://stream.aisstream.io/v0/stream"
AISSTREAM_DEFAULT_MESSAGE_TYPES = ["PositionReport", "ShipStaticData"]

# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class AISStreamError(ConnectionException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Classes                                                              #
# --------------------------------------------------------------------------- #


@oscal_connection(strict=False)
class AISStreamConnection(GenericConnection):
    ALLOWED = [
        KEY_CONNECTION_NAME,
        KEY_LAZY_LOADING,
        KEY_API_KEY,
        KEY_WS_URL,
        KEY_BOUNDING_BOXES,
        KEY_MESSAGE_TYPES,
    ]
    # OSCAL: `api_key` on an authenticated stream; no TLS switch of its own.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ("ac-3", "ia-5")

    def __init__(self, **kwargs):
        kwargs.setdefault(KEY_WS_URL, AISSTREAM_DEFAULT_URL)
        kwargs.setdefault(KEY_BOUNDING_BOXES, [])
        kwargs.setdefault(KEY_MESSAGE_TYPES, list(AISSTREAM_DEFAULT_MESSAGE_TYPES))
        super().__init__(**kwargs)

    def create_connection(self) -> None:
        self.debug(
            msg=Event.Create.name,
            step=Event.Started.name,
            state=self.state.value,
        )

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
            raise AISStreamError(
                caller=self,
                error=f"Cannot create connection in state '{self.state.value}'",
            )

        api_key = self.api_key
        if not api_key:
            raise AISStreamError(
                caller=self,
                error=f"`{KEY_API_KEY}` is mandatory for AISStreamConnection",
            )

        # No handshake; processor opens the WebSocket per stream.
        self._connection: Dict[str, Any] = {
            KEY_API_KEY: api_key,
            KEY_WS_URL: self.ws_url,
            KEY_BOUNDING_BOXES: self.bounding_boxes,
            KEY_MESSAGE_TYPES: self.message_types,
        }

        self.debug(
            msg=Event.Create.name,
            step=Event.Completed.name,
            state=self.state.value,
        )

    @contextmanager
    def connect(self) -> Generator[Dict[str, Any], None, None]:
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
            raise AISStreamError(
                caller=self,
                error=f"Cannot connect in state '{self.state.value}'",
            )

        if self._connection is None:
            raise AISStreamError(
                caller=self,
                error=f"{self.name}.connect: configuration is None",
            )

        self._fsm.apply(ConnectionAction.CONNECT)

        try:
            self._fsm.apply(ConnectionAction.CONNECT_OK)
        except Exception as e:
            self._fsm.apply(ConnectionAction.CONNECT_FAIL)
            self.debug(msg=Event.Connect.name, step=Event.Failed.name, error=str(e))
            raise AISStreamError(
                caller=self,
                error=f"connect error: {e}",
            ) from e

        self.debug(
            msg=Event.Connected.name,
            connection_name=self.connection_name,
            state=self.state.value,
        )

        try:
            yield self._connection
        finally:
            self._fsm.apply(ConnectionAction.DISCONNECT)
            self.debug(
                msg=Event.Disconnected.name,
                connection_name=self.connection_name,
            )

    def disconnect(self) -> None:
        self.debug(
            msg=Event.Disconnect.name,
            connection_name=self.connection_name,
            state=self.state.value,
        )
        self._connection = None
        self.debug(
            msg=Event.Disconnected.name,
            connection_name=self.connection_name,
            state=self.state.value,
        )

    def __repr__(self) -> str:
        return f"{self.name}:{self.state.value}[ws_url={getattr(self, 'ws_url', '?')}]"


# --------------------------------------------------------------------------- #
# endregion Classes                                                           #
# --------------------------------------------------------------------------- #
