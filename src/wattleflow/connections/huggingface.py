# Module name: connections/huggingface.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# Access to the HuggingFace subsystem: cache on disk plus the Hub behind it.   #
# Implements FR-CON-13.x / HLRQ-13; the network egress (proxy, TLS, endpoint   #
# auth) is inherited from ProxyConnection, so only Hub-specific settings are   #
# added here (analysis 2026-08-20-proxy-vs-huggingface-connection §3).         #
#                                                                             #
# Dependencies: requests (via ProxyConnection); huggingface_hub for the cache  #
# location, lazily imported.                                                   #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
from pathlib import Path
from typing import Any, ClassVar, Tuple

from wattleflow.concrete.exception import ConnectionException
from wattleflow.enums.event import Event
from wattleflow.connections.proxy import ProxyConnection

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["ConnectionHuggingFace", "HuggingFaceConnectionError"]

DEFAULT_ENDPOINT = "https://huggingface.co"

# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class HuggingFaceConnectionError(ConnectionException):
    """The cache is unusable or the connection is misconfigured."""


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Connection                                                           #
# --------------------------------------------------------------------------- #


# NOTE: OSCAL_CONTROLS is inherited unchanged — access (ac-3), credential (ia-5)
# and transport (sc-8) apply, as the Hub is reached over the same session
# (HLRQ-13 §6). The gate comes from the decorated
# parent: decorating a subclass as well wraps the FSM twice, and the outer
# wrapper consumes the `oscal_policy` kwarg before the inner one sees it — under
# strict gating the inner guard then rejects a correctly configured component
# (FR-OSCAL-14.11 §11 t.7).
class ConnectionHuggingFace(ProxyConnection):
    """Access to the HuggingFace subsystem — cache plus Hub.

    Inherits the network path from `ProxyConnection` (proxy, TLS, bearer
    token) and adds only what the Hub needs: where the cache lives, whether the
    connection may leave the machine, and which endpoint answers.
    """

    # Inherited access keys plus the Hub's own; `token` (parent) carries the HF
    # account, so the secret has exactly one home (NFRQ-SEC-06).
    # Only what this class adds: PresetGate unions ALLOWED across the MRO, so
    # naming the parent here would be both redundant and a rename hazard.
    ALLOWED = [
        "cache_dir",
        "offline",
        "endpoint",
    ]

    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ProxyConnection.OSCAL_CONTROLS

    # A generic connectivity probe against an unrelated host says nothing about
    # the Hub; this connection reports its own mode instead (analysis §5 t.2).
    PROBE_ENABLED_DEFAULT: ClassVar[bool] = False

    # region Properties
    @property
    def cache_dir(self) -> Path:
        configured = self._preset._values.get("cache_dir")
        if configured:
            return Path(str(configured)).expanduser()

        # One rule, one place: the cache lookup already exists (NFRQ-ORG-08).
        from wattleflow.connections.localmodels import DownloadedModels

        return Path(DownloadedModels().base_path)

    @property
    def offline(self) -> bool:
        return bool(self._preset._values.get("offline", False))

    @property
    def endpoint(self) -> str:
        return str(self._preset._values.get("endpoint") or DEFAULT_ENDPOINT)

    # endregion Properties

    def _configure_service(self, session: Any, kw: dict) -> None:
        """Confirm the cache is usable and record the mode.

        The connection answers "can this subsystem be reached", not "is model X
        present" — that is the driver's question (FR-CON-13.1 §5 t.4).
        """

        self.debug(
            msg=Event.Configuring.name,
            session=session,
        )

        cache = self.cache_dir
        try:
            cache.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.debug(msg=Event.Configuring.name, step=Event.Failed.name, error=str(e))
            raise HuggingFaceConnectionError(
                caller=self,
                error=f"Cache directory is not usable: {cache} ({e})",
            ) from e

        if not cache.is_dir():
            raise HuggingFaceConnectionError(
                caller=self, error=f"Cache path is not a directory: {cache}"
            )

        self.debug(
            msg=Event.Configuring.name,
            connection_name=self._connection_name,
            cache_dir=str(cache),
            endpoint=self.endpoint,
            offline=self.offline,
            authenticated=bool(kw.get("token")),
        )


# --------------------------------------------------------------------------- #
# endregion Connection                                                        #
# --------------------------------------------------------------------------- #
