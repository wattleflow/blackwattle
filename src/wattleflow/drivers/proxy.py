# Module name: drivers/proxy.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations

import ipaddress
import os
import pandas as pd
import tempfile as tmp

from pathlib import Path
from typing import Any, ClassVar, Optional, Tuple
from urllib.parse import urlparse

from wattleflow.concrete.driver import GenericDriver, DriverMetadata
from wattleflow.concrete.exception import AuditException, DriverException
from wattleflow.connections.proxy import ProxyConnection
from wattleflow.enums.event import Event
from wattleflow.enums.filetype import FileType
from wattleflow.drivers.file_storage import FileStorage
from wattleflow.decorators.oscal import oscal_driver

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #

_DEFAULT_CACHE_DIR: str = os.environ.get(
    "WATTLEFLOW_CACHE",
    str(Path(tmp.gettempdir()).joinpath("wattleflow_cache").absolute()),
)

_MAX_DOWNLOAD_BYTES: int = int(os.environ.get("WATTLEFLOW_MAX_DOWNLOAD_BYTES", 100 * 1024 * 1024))


# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class DriverProxyError(DriverException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Driver                                                               #
# --------------------------------------------------------------------------- #


@oscal_driver(strict=False)
class DriverProxy(GenericDriver):
    ALLOWED = [
        "local_path",
        "create",
        "normalised",
        "timeout",
        "verify_ssl",
        "connection_name",
        # WorkflowFactory injects the manager whenever a driver declares a
        # `connection_name`; without the key here PresetDecorator discards it
        # and a YAML-configured driver can never reach its connection.
        "connection_manager",
    ]
    # OSCAL: credentialed proxy path; `verify_ssl` defaults to True and a disabled
    # verification is audited as a MITM exposure.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ("ac-3", "ia-5", "sc-8")

    def __init__(self, **kwargs) -> None:
        # No named parameters: they only repeated ALLOWED, and every read site
        # already carries its own default (`getattr(self, key, default)`).
        super().__init__(**kwargs)
        self._current_path: Optional[Path] = None

    # region GenericDriver lifecycle

    def load(self) -> None:
        verify_ssl: bool = getattr(self, "verify_ssl", True)
        if not verify_ssl:
            self.warning(
                msg=Event.Load.name,
                step=Event.Check.name,
                reason="SSL verification disabled (verify_ssl=False) — vulnerable to MITM attacks.",
            )

        local_path = Path(getattr(self, "local_path", _DEFAULT_CACHE_DIR))
        if not local_path.is_dir():
            if not getattr(self, "create", True):
                reason = f"local_path must be a directory: {local_path!r}"
                self.error(
                    msg=Event.Load.name,
                    reason=reason,
                    local_path=str(local_path),
                )
                raise RuntimeError(reason)
            local_path.mkdir(parents=True, exist_ok=True)

        self._current_path = local_path
        self.debug(msg=Event.Load.name, step=Event.Completed.name, path=str(self._current_path))

    def close(self) -> None:
        self.debug(msg=Event.Close.name, step=Event.Started.name)
        self._current_path = None
        self.debug(msg=Event.Close.name, step=Event.Completed.name)

    # endregion

    # region Public API

    def read(self, uri: str, **kwargs) -> Any:
        self.ensure_live()
        self.debug(
            msg=Event.Read.name,
            step=Event.Started.name,
            uri=uri,
            kwargs=ProxyConnection._safe_log_kwargs(**kwargs),
        )
        try:
            self._validate_uri(uri)
            storage = FileStorage(
                local_path=str(self._current_path),
                uri=uri,
                create=True,
                normalised=True,
            )
            response = self._download(uri, **kwargs)
            storage.filename.write_bytes(response.content)

            if not storage.filename.exists():
                reason = f"Failed to save file to local cache: {storage.filename}"
                self.error(msg=Event.Read.name, uri=uri, reason=reason)
                raise IOError(reason)

            file_type = FileType.detect_content(response.content)
            self.debug(
                msg=Event.Read.name,
                step=Event.Completed.name,
                origin=storage.origin,
                filename=storage.filename,
                size=storage.size,
                file_type=file_type.name,
            )

            if file_type == FileType.CSV:
                return pd.read_csv(storage.filename)
            if file_type == FileType.JSON:
                return pd.read_json(storage.filename)
            if file_type == FileType.XLS:
                return pd.read_excel(storage.filename)
            if file_type == FileType.TXT:
                return storage.filename.read_text()
            return storage.filename.read_bytes()

        except AuditException as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, uri=uri, error=e.reason)
            raise
        except Exception as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, uri=uri, error=str(e))
            raise DriverProxyError(caller=self, error=str(e)) from e

    def write(self, uri: str, **kwargs) -> str:
        raise NotImplementedError(
            f"{self.__class__.__name__}.write() is not implemented. "
            "HTTP write operations are not supported by this driver."
        )

    def metadata(self) -> DriverMetadata:
        return DriverMetadata(
            name=self.__class__.__name__,
            version="1.0",
            protocol="https",
            capabilities=["read"],
        )

    # endregion

    # region Private helpers

    def _validate_uri(self, uri: str) -> None:
        self.debug(msg=Event.Validate.name, step=Event.Started.name, uri=uri)
        parsed = urlparse(uri)

        if parsed.scheme not in ("http", "https"):
            reason = (
                f"Unsupported URI scheme '{parsed.scheme}'. "
                f"{self.__class__.__name__} supports http and https only."
            )
            self.error(msg=Event.Validate.name, uri=uri, reason=reason)
            raise ValueError(reason)

        host = parsed.hostname or ""
        if host.lower() in ("localhost", "0.0.0.0"):
            reason = f"Access to localhost is not allowed: {host!r}"
            self.error(msg=Event.Validate.name, uri=uri, reason=reason)
            raise PermissionError(reason)

        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                reason = f"Access to private/internal addresses is not allowed: {host!r}"
                self.error(
                    msg=Event.Validate.name, step=Event.Completed.name, uri=uri, reason=reason
                )
                raise PermissionError(reason)
        except ValueError:
            pass  # hostname, not an IP literal — allowed

    def _build_fetch_kwargs(self, **kwargs) -> dict:
        """Map per-call auth shortcuts onto ProxyConnection.fetch() kwargs."""
        fetch_kwargs: dict = {}
        merged_headers: dict = {}

        api_key = kwargs.get("api_key")
        if api_key:
            merged_headers["X-API-Key"] = api_key

        token = kwargs.get("token")
        if token:
            merged_headers["Authorization"] = f"Bearer {token}"

        basic_auth = kwargs.get("basic_auth")
        if basic_auth:
            fetch_kwargs["auth"] = tuple(basic_auth)

        merged_headers.update(kwargs.get("headers") or {})
        if merged_headers:
            fetch_kwargs["headers"] = merged_headers

        timeout = getattr(self, "timeout", None)
        if timeout is not None:
            fetch_kwargs["timeout"] = timeout

        return fetch_kwargs

    def _resolve_connection(self) -> ProxyConnection:
        """Return the ProxyConnection this driver fetches through.

        YAML declares `connection_name` as a string and WorkflowFactory injects
        the manager alongside it, so the name is resolved here — the same way
        every other connection-backed driver does it. A caller constructing the
        driver by hand may pass the instance under the same key.
        """
        candidate = getattr(self, "connection_name", None)
        if isinstance(candidate, ProxyConnection):
            return candidate

        manager = getattr(self, "connection_manager", None)
        if isinstance(candidate, str) and candidate and manager is not None:
            connection = manager.get_connection(candidate)
            if isinstance(connection, ProxyConnection):
                return connection
            raise DriverProxyError(
                caller=self,
                error=f"connection {candidate!r} is a "
                f"{type(connection).__name__}, not a ProxyConnection.",
            )

        raise DriverProxyError(
            caller=self,
            error="connection_name must name a registered ProxyConnection (or be "
            "one) — direct requests.get() bypass is not allowed (audit/OSCAL policy).",
        )

    def _download(self, uri: str, **kwargs):
        self.debug(
            msg=Event.Download.name,
            step=Event.Started.name,
            uri=uri,
            kwargs=ProxyConnection._safe_log_kwargs(**kwargs),
        )

        connection = self._resolve_connection()

        return connection.fetch(
            str(uri),
            max_bytes=_MAX_DOWNLOAD_BYTES,
            **self._build_fetch_kwargs(**kwargs),
        )

    # endregion

    def __repr__(self) -> str:
        path = self._current_path or Path(getattr(self, "local_path", _DEFAULT_CACHE_DIR))
        return f"{self.__class__.__name__}(state={self._fsm.state.value}, path={path.resolve()})"


# --------------------------------------------------------------------------- #
# endregion Driver                                                            #
# --------------------------------------------------------------------------- #
