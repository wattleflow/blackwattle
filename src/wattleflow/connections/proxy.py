# Module name: connections/proxy.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# Dependencies:
#   pip install requests
#
# Optional enterprise auth libraries:
#   pip install requests-ntlm       (NTLM auth — proxy or endpoint)
#   pip install requests-kerberos   (Kerberos/SPNEGO auth)
#
# Supported configuration kwargs
# ─── Proxy ─────────────────────────────────────────────────────────────────
# proxy_url          str          Base proxy URL applied to both http and https
#                                 unless proxy_http / proxy_https are set.
# proxy_http         str          HTTP proxy URL.
# proxy_https        str          HTTPS proxy URL.
# proxy_username     str          Proxy authentication username.
# proxy_password     str          Proxy authentication password.
# proxy_auth         str          Proxy auth scheme:
#                                   "basic"    — credentials embedded in URL (default)
#                                   "ntlm"     — NTLM (requires requests-ntlm)
#                                   "kerberos" — Kerberos/SPNEGO (requires requests-kerberos)
# no_proxy           str | list   Hostnames to bypass the proxy (comma-separated
#                                 string or list of strings).
#
# ─── SSL / TLS ──────────────────────────────────────────────────────────────
# verify_ssl         bool = True  Verify the server's SSL certificate.
# ca_bundle          str          Path to a custom CA certificate bundle (PEM).
#                                 Overrides verify_ssl when set.
# client_cert        str          Path to the client certificate (PEM) for
#                                 mutual TLS.
# client_key         str          Path to the client private key (PEM).
#                                 Omit if the key is bundled in client_cert.
#
# ─── Endpoint authentication ────────────────────────────────────────────────
# api_key            str          Added as X-API-Key session header.
# token              str          Added as Authorization: Bearer <token>.
# basic_auth         (str, str)   (username, password) — Basic auth for the
#                                 target endpoint.
# ntlm_auth          (str, str)   (username, password) — NTLM auth for the
#                                 target endpoint (requires requests-ntlm).
# kerberos_auth      bool         Kerberos/SPNEGO auth for the endpoint
#                                 (requires requests-kerberos).
# headers            dict         Extra headers merged into the session.
#
# ─── Session ────────────────────────────────────────────────────────────────
# timeout            int = 30     Default per-request timeout (seconds).
#                                 Exposed via the timeout property.
#
# ─── Connectivity probe ─────────────────────────────────────────────────────
# probe_enabled      bool = True  Run a lightweight connectivity probe at
#                                 create_connection(). Warns the user when a
#                                 proxy is required but not configured.
# probe_url          str          URL used for the probe.
#                                 Default: https://connectivitycheck.gstatic.com
#                                          /generate_204  (returns 204, minimal overhead)
# probe_timeout      int = 10     Timeout for the probe request in seconds.
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from contextlib import contextmanager
from typing import Any, ClassVar, Generator, Optional, Tuple
from urllib.parse import urlparse
from wattleflow.concrete.connection import ConnectionAction
from wattleflow.concrete.exception import ConnectionException
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
_DEFAULT_PROBE_URL = (
    "https://www.google.com/generate_204"  # Alternative probe URL that also returns 204 No Content.
)
_DEFAULT_TIMEOUT = 30
_DEFAULT_MAX_BYTES = 100 * 1024 * 1024  # 100 MB cap for fetch()
_SENSITIVE_KWARGS: frozenset = frozenset(
    {
        "api_key",
        "token",
        "basic_auth",
        "password",
        "proxy_password",
        "ntlm_auth",
        "client_key",
    }
)

# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class ProxyConnectionError(ConnectionException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Classes                                                              #
# --------------------------------------------------------------------------- #


@oscal_connection(strict=False)
class ProxyConnection(GenericConnection):
    ALLOWED = [
        # proxy
        "proxy_url",
        "proxy_http",
        "proxy_https",
        "proxy_username",
        "proxy_password",
        "proxy_auth",
        "no_proxy",
        # ssl / tls
        "verify_ssl",
        "ca_bundle",
        "client_cert",
        "client_key",
        # endpoint auth
        "api_key",
        "token",
        "basic_auth",
        "ntlm_auth",
        "kerberos_auth",
        "headers",
        # session
        "timeout",
        "max_bytes",
        # probe
        "probe_enabled",
        "probe_url",
        "probe_timeout",
    ]
    # OSCAL: api_key/bearer credentials, plus TLS verification it enforces itself.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ("ac-3", "ia-5", "sc-8")

    # A subclass that talks to one named service probes THAT service, not the
    # generic connectivity endpoint, so it turns the default probe off.
    PROBE_ENABLED_DEFAULT: ClassVar[bool] = True

    # ---------------------------------------------------------------------- #
    # Public API
    # ---------------------------------------------------------------------- #

    @property
    def timeout(self) -> int:
        return self._preset._values.get("timeout", _DEFAULT_TIMEOUT)

    @property
    def max_bytes(self) -> int:
        return self._preset._values.get("max_bytes", _DEFAULT_MAX_BYTES)

    def fetch(
        self,
        uri: str,
        *,
        method: str = "GET",
        max_bytes: Optional[int] = None,
        timeout: Optional[int] = None,
        headers: Optional[dict] = None,
        auth: Optional[Any] = None,
        **request_kwargs: Any,
    ) -> "requests.Response":
        with self.connect() as session:
            request_kwargs.setdefault("timeout", timeout if timeout is not None else self.timeout)
            request_kwargs.setdefault("stream", True)
            if headers:
                merged = dict(session.headers)
                merged.update(headers)
                request_kwargs["headers"] = merged
            if auth is not None:
                request_kwargs["auth"] = auth

            _parsed = urlparse(str(uri))
            _safe_uri = _parsed._replace(query="", fragment="").geturl()
            self.debug(msg=Event.Downloading.name, step=Event.Started.name, uri=_safe_uri)

            response = session.request(method.upper(), str(uri), **request_kwargs)
            response.raise_for_status()

            cap: int = max_bytes if max_bytes is not None else self.max_bytes
            chunks: list[bytes] = []
            received: int = 0
            for chunk in response.iter_content(chunk_size=65536):
                received += len(chunk)
                if received > cap:
                    response.close()
                    reason = f"Download exceeds {cap} bytes limit: {_safe_uri}"
                    self.error(msg=Event.Read.name, uri=_safe_uri, reason=reason)
                    raise ValueError(reason)
                chunks.append(chunk)

            response._content = b"".join(chunks)
            self.debug(
                msg=Event.Downloading.name,
                step=Event.Completed.name,
                uri=_safe_uri,
                size=received,
            )
            return response

    # ---------------------------------------------------------------------- #
    # GenericConnection implementation
    # ---------------------------------------------------------------------- #

    def create_connection(self) -> None:
        kw = self._preset._values
        session = requests.Session()

        self._configure_proxy(session, kw)
        self._configure_ssl(session, kw)
        self._configure_auth(session, kw)
        self._configure_headers(session, kw)

        self._connection = session

        self.debug(
            msg=Event.Create.name,
            connection_name=self._connection_name,
            proxied=bool(kw.get("proxy_url") or kw.get("proxy_http") or kw.get("proxy_https")),
            verify=session.verify,
            state=self.state.value,
        )

        # Extension point for subclasses: the session is built and configured, so a
        # child adds only what its own service needs (analysis 2026-08-20, §5 t.1).
        self._configure_service(session, kw)

        if kw.get("probe_enabled", self.PROBE_ENABLED_DEFAULT):
            self._probe(session, kw)

    def _configure_service(self, session: "requests.Session", kw: dict) -> None:
        """Service-specific configuration; empty here, overridden by subclasses."""

    # region Context manager
    @contextmanager
    def connect(self) -> Generator[requests.Session, None, None]:
        self.debug(msg=Event.Connecting.name, connection=self._connection_name)

        if not self._connection:
            raise ProxyConnectionError(
                caller=self,
                error="Session is not initialised — create_connection() must succeed first.",
            )

        self._fsm.apply(ConnectionAction.CONNECT)
        try:
            self._fsm.apply(ConnectionAction.CONNECT_OK)
        except Exception as e:
            self._fsm.apply(ConnectionAction.CONNECT_FAIL)
            self.debug(msg=Event.Connecting.name, step=Event.Failed.name, error=str(e))
            raise ProxyConnectionError(caller=self, error=str(e)) from e

        self.debug(msg=Event.Connected.name, connection=self._connection_name)

        try:
            yield self._connection
        except ProxyConnectionError:
            raise
        except Exception as e:
            self.notify(self, error=str(e), connection_name=self.connection_name)
            self.debug(msg=Event.Connecting.name, step=Event.Failed.name, error=str(e))
            raise ProxyConnectionError(caller=self, error=f"Session error: {e}") from e
        finally:
            self._fsm.apply(ConnectionAction.DISCONNECT)
            self.debug(msg=Event.Disconnecting.name, connection=self._connection_name)

    def disconnect(self) -> None:
        self.debug(msg=Event.Disconnecting.name, connection=self._connection_name)
        try:
            if self._connection:
                try:
                    self._connection.close()
                except Exception as e:
                    self.warning(msg=Event.Disconnect.name, error=str(e))
                finally:
                    self._connection = None  # type: ignore
        finally:
            self.debug(msg=Event.Disconnected.name, connection=self._connection_name)

    # endregion Context manager

    # ---------------------------------------------------------------------- #
    # Private configuration helpers
    # ---------------------------------------------------------------------- #

    def _configure_proxy(self, session: requests.Session, kw: dict) -> None:
        proxy_url: Optional[str] = kw.get("proxy_url")
        http_proxy: Optional[str] = kw.get("proxy_http") or proxy_url
        https_proxy: Optional[str] = kw.get("proxy_https") or proxy_url

        if not (http_proxy or https_proxy):
            return

        username: Optional[str] = kw.get("proxy_username")
        password: str = kw.get("proxy_password") or ""
        scheme: str = (kw.get("proxy_auth") or "basic").lower()

        if username:
            if scheme == "ntlm":
                try:
                    from requests_ntlm import HttpNtlmAuth  # noqa: PLC0415

                    session.auth = HttpNtlmAuth(username, password)
                    self.debug(msg=Event.Authentication.name, scope="proxy", scheme="ntlm")
                except ImportError:
                    self.warning(
                        msg=Event.Authentication.name,
                        scope="proxy",
                        error="requests-ntlm is not installed — falling back to "
                        "basic credential embedding for NTLM proxy.",
                    )
                    http_proxy = (
                        self._embed_credentials(http_proxy, username, password)
                        if http_proxy
                        else None
                    )
                    https_proxy = (
                        self._embed_credentials(https_proxy, username, password)
                        if https_proxy
                        else None
                    )
            elif scheme == "kerberos":
                try:
                    from requests_kerberos import HTTPKerberosAuth, OPTIONAL  # noqa: PLC0415

                    session.auth = HTTPKerberosAuth(mutual_authentication=OPTIONAL)
                    self.debug(msg=Event.Authentication.name, scope="proxy", scheme="kerberos")
                except ImportError:
                    self.warning(
                        msg=Event.Authentication.name,
                        scope="proxy",
                        error="requests-kerberos is not installed — "
                        "Kerberos proxy auth unavailable.",
                    )
            else:
                # Basic: embed credentials directly in the proxy URL.
                if http_proxy:
                    http_proxy = self._embed_credentials(http_proxy, username, password)
                if https_proxy:
                    https_proxy = self._embed_credentials(https_proxy, username, password)

        proxies: dict = {}
        if http_proxy:
            proxies["http"] = http_proxy
        if https_proxy:
            proxies["https"] = https_proxy

        no_proxy = kw.get("no_proxy")
        if no_proxy:
            proxies["no_proxy"] = ",".join(no_proxy) if isinstance(no_proxy, list) else no_proxy

        session.proxies.update(proxies)
        self.debug(
            msg=Event.Configure.name,
            component="proxy",
            schemes=list(proxies.keys()),
            no_proxy=bool(no_proxy),
        )

    # ---------------------------------------------------------------------- #
    # Static methods
    # ---------------------------------------------------------------------- #

    @staticmethod
    def _embed_credentials(url: str, username: str, password: str) -> str:
        """Return the proxy URL with username:password embedded in the netloc."""
        from urllib.parse import urlparse, urlunparse, quote  # noqa: PLC0415

        p = urlparse(url)
        userinfo = f"{quote(username, safe='')}:{quote(password, safe='')}"
        netloc = f"{userinfo}@{p.hostname}"
        if p.port:
            netloc += f":{p.port}"
        return urlunparse((p.scheme, netloc, p.path, p.params, p.query, p.fragment))

    def _configure_ssl(self, session: requests.Session, kw: dict) -> None:
        ca_bundle: Optional[str] = kw.get("ca_bundle")
        verify_ssl: bool = kw.get("verify_ssl", True)
        client_cert: Optional[str] = kw.get("client_cert")
        client_key: Optional[str] = kw.get("client_key")

        if ca_bundle:
            session.verify = ca_bundle
            self.debug(msg=Event.Configure.name, component="ssl", ca_bundle=ca_bundle)
        elif not verify_ssl:
            session.verify = False
            self.warning(
                msg=Event.Configure.name,
                component="ssl",
                connection_name=self._connection_name,
                reason="SSL certificate verification is disabled (verify_ssl=False). "
                "Connections are vulnerable to MITM attacks.",
            )
        else:
            session.verify = True

        if client_cert:
            session.cert = (client_cert, client_key) if client_key else client_cert
            self.debug(
                msg=Event.Configure.name,
                component="ssl",
                mutual_tls=True,
                has_separate_key=bool(client_key),
            )

    def _configure_auth(self, session: requests.Session, kw: dict) -> None:
        ntlm_auth = kw.get("ntlm_auth")
        kerberos_auth = kw.get("kerberos_auth")
        basic_auth = kw.get("basic_auth")

        if ntlm_auth:
            try:
                from requests_ntlm import HttpNtlmAuth  # noqa: PLC0415

                session.auth = HttpNtlmAuth(*ntlm_auth)
                self.debug(msg=Event.Authentication.name, scheme="ntlm")
                return
            except ImportError:
                self.warning(
                    msg=Event.Authentication.name,
                    error="requests-ntlm is not installed — NTLM endpoint auth unavailable.",
                )

        if kerberos_auth:
            try:
                from requests_kerberos import HTTPKerberosAuth, OPTIONAL  # noqa: PLC0415

                session.auth = HTTPKerberosAuth(mutual_authentication=OPTIONAL)
                self.debug(msg=Event.Authentication.name, scheme="kerberos")
                return
            except ImportError:
                self.warning(
                    msg=Event.Authentication.name,
                    error="requests-kerberos is not installed — "
                    "Kerberos endpoint auth unavailable.",
                )

        if basic_auth:
            session.auth = tuple(basic_auth)
            self.debug(msg=Event.Authentication.name, scheme="basic")

    def _configure_headers(self, session: requests.Session, kw: dict) -> None:
        merged: dict = {}
        api_key: Optional[str] = kw.get("api_key")
        if api_key:
            merged["X-API-Key"] = api_key
        token: Optional[str] = kw.get("token")
        if token:
            merged["Authorization"] = f"Bearer {token}"
        extra: dict = kw.get("headers") or {}
        merged.update(extra)
        if merged:
            session.headers.update(merged)

    @staticmethod
    def _safe_log_kwargs(**kwargs) -> dict:
        """Mask sensitive values for audit/debug logs."""
        return {k: ("***" if k in _SENSITIVE_KWARGS else v) for k, v in kwargs.items()}

    # ---------------------------------------------------------------------- #
    # Connectivity probe
    # ---------------------------------------------------------------------- #

    def _probe(self, session: requests.Session, kw: dict) -> None:
        url: str = kw.get("probe_url", _DEFAULT_PROBE_URL)
        timeout: int = kw.get("probe_timeout", 10)

        try:
            resp = session.get(url, timeout=timeout)

            if resp.status_code == 407:
                self.warning(
                    msg=Event.Probe.name,
                    connection_name=self._connection_name,
                    error="Connectivity probe returned 407 Proxy Authentication Required. "
                    "Provide proxy_username and proxy_password to authenticate "
                    "with your enterprise proxy server.",
                )
                return

            self.debug(
                msg=Event.Probe.name,
                connection_name=self._connection_name,
                url=url,
                status=resp.status_code,
            )

        except requests.exceptions.ProxyError as e:
            self.warning(
                msg=Event.Probe.name,
                connection_name=self._connection_name,
                error="Connectivity probe failed: a proxy error was detected. "
                "Set proxy_url (and proxy_username / proxy_password if authentication "
                "is required) to route traffic through your enterprise proxy server.",
                detail=str(e)[:300],
            )

        except requests.exceptions.ConnectionError as e:
            detail = str(e).lower()
            if any(k in detail for k in ("proxy", "407", "tunnel connection", "407 proxy")):
                self.warning(
                    msg=Event.Probe.name,
                    connection_name=self._connection_name,
                    error="Connectivity probe suggests a proxy is required but none is configured. "
                    "Set proxy_url (and proxy_username / proxy_password if credentials "
                    "are needed) to reach the internet via your enterprise proxy server.",
                )
            else:
                self.debug(
                    msg=Event.Probe.name,
                    connection_name=self._connection_name,
                    url=url,
                    note="Connectivity probe failed — network may be unavailable or restricted.",
                    detail=str(e)[:200],
                )

        except Exception as e:
            self.debug(
                msg=Event.Probe.name,
                connection_name=self._connection_name,
                url=url,
                note=f"Connectivity probe failed: {type(e).__name__}",
                detail=str(e)[:200],
            )


# --------------------------------------------------------------------------- #
# endregion Connections                                                       #
# --------------------------------------------------------------------------- #
