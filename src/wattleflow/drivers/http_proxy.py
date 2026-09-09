# Module name: drivers/http_proxy.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

from __future__ import annotations

import ipaddress
import os
import pandas as pd
import tempfile as tmp

from pathlib import Path
from typing import Any, ClassVar, Tuple
from urllib.parse import urlparse

from wattleflow.concrete.driver import DriverMetadata, GenericDriver
from wattleflow.concrete.exception import AuditException, DriverException
from wattleflow.connections.proxy import ProxyConnection
from wattleflow.enums.event import Event
from wattleflow.enums.filetype import FileType
from wattleflow.drivers import FileStorage
from wattleflow.decorators.oscal import oscal_driver

_DEFAULT_CACHE_DIR: str = os.environ.get(
    "WATTLEFLOW_CACHE",
    str(Path(tmp.gettempdir()).joinpath("wattleflow_cache").absolute()),
)

_MAX_DOWNLOAD_BYTES: int = int(
    os.environ.get("WATTLEFLOW_MAX_DOWNLOAD_BYTES", 100 * 1024 * 1024)  # 100 MB
)


class DriverHttpProxyError(DriverException):
    pass


@oscal_driver(strict=False)
class DriverHttpProxy(GenericDriver):
    ALLOWED = [
        "local_path",
        "current_path",
        "create",
        "normalised",
        "timeout",
        "verify_ssl",
        "connection_name",
        # WorkflowFactory injects the manager whenever a driver declares a
        # `connection_name`; without the key here PresetDecorator dropped it and
        # the YAML-configured driver could never reach its connection.
        "connection_manager",
    ]
    # OSCAL: `X-API-Key` handling; `verify_ssl` defaults to True and a disabled
    # verification is audited as a MITM exposure.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ("ac-3", "ia-5", "sc-8")

    def load(self) -> None:
        if not self.verify_ssl:
            self.warning(
                msg=Event.Load.name,
                step=Event.Check.name,
                reason="SSL certificate verification is disabled (verify_ssl=False). "
                "This makes connections vulnerable to MITM attacks.",
            )
        if not Path(self.local_path).is_dir():
            if not self.create:
                reason = f"local_path should be a directory: {self.local_path!r}"
                self.error(
                    msg=Event.Load.name,
                    step=Event.Completed.name,
                    reason=reason,
                    local_path=self.local_path,
                )
                raise DriverHttpProxyError(caller=self, error=reason)
            Path(self.local_path).mkdir(parents=True, exist_ok=True)

        self.current_path: Path = Path(self.local_path)

    def close(self) -> None:
        # The driver owns no socket of its own: every fetch goes through the
        # ProxyConnection held by the ConnectionManager, and downloads land in
        # the cache directory, which outlives the driver on purpose.
        self.debug(msg=Event.Close.name, step=Event.Started.name)

    def metadata(self) -> DriverMetadata:
        # write() raises NotImplementedError, so "write" is deliberately absent
        # from the capability list.
        return DriverMetadata(
            name=self.__class__.__name__,
            version="1.0",
            protocol="http(s)",
            capabilities=["read"],
        )

    def download(self, uri: str, **kwargs) -> Path:
        """Fetch ``uri`` into the cache directory and return the local path.

        The download half of ``read()``, without the parse: a bulk fetch of
        formats ``read()`` would hand to pandas costs one write per file instead
        of a full parse. ``normalised`` decides the cached name — hashed digest
        when set, the origin's own name when not.
        """
        self.debug(
            msg=Event.Download.name,
            step=Event.Started.name,
            uri=uri,
            kwargs=ProxyConnection._safe_log_kwargs(**kwargs),
        )
        try:
            self._validate_uri(uri)
            storage = FileStorage(
                local_path=str(self.local_path),
                uri=uri,
                create=True,
                normalised=bool(self.normalised),
            )

            response = self._download(uri, **kwargs)
            storage.filename.write_bytes(response.content)

            if storage.filename.exists() is False:
                reason = f"Failed to save file to local cache: {storage.filename}"
                self.error(msg=Event.Download.name, uri=uri, reason=reason)
                raise IOError(reason)

            self.debug(
                msg=Event.Download.name,
                step=Event.Completed.name,
                origin=storage.origin,
                filename=storage.filename,
                size=storage.size,
            )
            return storage.filename
        except AuditException as e:
            self.debug(msg=Event.Download.name, step=Event.Failed.name, uri=uri, error=e.reason)
            raise e
        except Exception as e:
            self.debug(msg=Event.Download.name, step=Event.Failed.name, uri=uri, error=str(e))
            raise DriverHttpProxyError(caller=self, error=str(e)) from e

    def read(self, uri: str, **kwargs) -> Any:
        self.debug(
            msg=Event.Read.name,
            step=Event.Started.name,
            uri=uri,
            kwargs=ProxyConnection._safe_log_kwargs(**kwargs),
        )
        try:
            filename = self.download(uri, **kwargs)
            payload = filename.read_bytes()
            file_type = FileType.detect_content(payload)

            self.debug(
                msg=Event.Read.name,
                step=Event.Completed.name,
                filename=filename,
                size=len(payload),
                file_type=file_type.name,
            )

            if file_type == FileType.CSV:
                return pd.read_csv(filename)
            if file_type == FileType.JSON:
                return pd.read_json(filename)
            if file_type == FileType.XLS:
                return pd.read_excel(filename)
            if file_type == FileType.TXT:
                return filename.read_text()
            return payload
        except AuditException as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, uri=uri, error=e.reason)
            raise e
        except Exception as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, uri=uri, error=str(e))
            raise DriverHttpProxyError(caller=self, error=str(e)) from e

    def write(self, uri: str, filename: str, ftype: FileType, data: object, **kwargs) -> str:
        raise NotImplementedError(
            f"{self.__class__.__name__}.write() is not implemented. "
            "HTTP write operations are not supported by this driver. "
            "Use DriverLocalStorage for local persistence, or implement "
            "a dedicated upload driver for your target endpoint."
        )

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
            pass  # host is a hostname, not an IP literal — allow through

    def _build_fetch_kwargs(self, **kwargs) -> dict:
        """Map per-call auth shortcuts onto ProxyConnection.fetch() kwargs."""
        fetch_kwargs: dict = {"timeout": self.timeout}
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

        merged_headers.update(kwargs.get("headers", {}) or {})
        if merged_headers:
            fetch_kwargs["headers"] = merged_headers

        return fetch_kwargs

    def _resolve_connection(self) -> ProxyConnection:
        """Return the ProxyConnection this driver fetches through.

        YAML declares `connection_name` as a string and WorkflowFactory injects
        the manager alongside it, so the name is resolved here, the same way
        every other connection-backed driver does it. A caller constructing the
        driver by hand may pass the instance under the same key.
        """
        candidate = self.connection_name

        if isinstance(candidate, ProxyConnection):
            return candidate

        manager = self.connection_manager
        if isinstance(candidate, str) and candidate and manager is not None:
            connection = manager.get_connection(candidate)
            if isinstance(connection, ProxyConnection):
                return connection
            raise DriverHttpProxyError(
                caller=self,
                error=f"connection {candidate!r} is a "
                f"{type(connection).__name__}, not a ProxyConnection.",
            )

        raise DriverHttpProxyError(
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

        connection: ProxyConnection = self._resolve_connection()

        return connection.fetch(
            str(uri),
            max_bytes=_MAX_DOWNLOAD_BYTES,
            **self._build_fetch_kwargs(**kwargs),
        )

    def __repr__(self) -> str:
        # current_path is an allowed preset key, so before load() runs it
        # resolves to None rather than raising — getattr's default never fires.
        path = getattr(self, "current_path", None) or Path(self.local_path)
        return f"{self.__class__.__name__}:{str(path.resolve())}"
