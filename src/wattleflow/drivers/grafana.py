# Module name: drivers/grafana.py
# Author: (wattleflow@outlook.com)
# Copyright: @ 2022-2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# IMPORTANT: This driver requires the `requests` library.                     #
#     pip install requests                                                    #
#                                                                             #
# DriverGrafana - push annotations to Grafana via HTTP Annotations API.       #
# Write-only driver: create / update / delete annotations on a Grafana        #
# instance (tested against the official Grafana Docker image on :3000).      #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
import time as _time

try:
    import requests
except ImportError as e:
    raise ModuleNotFoundError(
        f"requests library is required to run this code.[{str(e)}]\n"
        "Please install it with\n\t`pip install requests`"
    ) from e

from typing import Any, ClassVar, Dict, List, Mapping, Optional, Tuple
from urllib.parse import urljoin
from wattleflow.concrete.driver import (
    DriverAction,
    DriverMetadata,
    GenericDriver,
)
from wattleflow.concrete.exception import DriverException
from wattleflow.enums.event import Event
from wattleflow.decorators.oscal import oscal_driver

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #


WRITE_MODES = ("create", "update", "patch", "delete")
ANNOTATIONS_PATH = "/api/annotations"
HEALTH_PATH = "/api/health"

# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class DriverGrafanaError(DriverException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Driver                                                               #
# --------------------------------------------------------------------------- #


@oscal_driver(strict=False)
class DriverGrafana(GenericDriver):
    ALLOWED = [
        "base_url",  # http(s)://host:port  (e.g. http://localhost:3000)
        "api_token",  # Grafana service-account / API token (Bearer)
        "username",  # basic-auth user (e.g. "admin")
        "password",  # basic-auth password
        "org_id",  # X-Grafana-Org-Id header (defaults to 1)
        "dashboard_uid",  # default dashboardUID for annotations
        "dashboard_id",  # default dashboardId for annotations (legacy)
        "panel_id",  # default panelId
        "tags",  # default tags merged into every annotation
        "headers",  # extra HTTP headers
        "verify_ssl",
        "request_timeout",
        "write_options",  # extra kwargs forwarded to requests
    ]
    # OSCAL: API token or basic auth, plus `verify_ssl` on every request.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ("ac-3", "ia-5", "sc-8")

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._session: Optional[requests.Session] = None
        self.ensure_live()

    # ---------------------------------------------------------------------- #
    # region Lifecycle
    # ---------------------------------------------------------------------- #

    def load(self) -> None:
        self.debug(msg=Event.Load.name, step=Event.Started.name)

        if not self.base_url:
            raise DriverGrafanaError(
                caller=self,
                error="DriverGrafana: 'base_url' is required.",
            )

        self.verify_ssl = True if self.verify_ssl is None else bool(self.verify_ssl)
        self.request_timeout = self.request_timeout if self.request_timeout is not None else 10
        self.org_id = self.org_id if self.org_id is not None else 1
        self.tags = list(self.tags) if isinstance(self.tags, (list, tuple)) else []

        session = requests.Session()
        session.headers.update(self._build_default_headers())
        auth = self._resolve_auth()
        if auth is not None:
            session.auth = auth
        self._session = session

        self.debug(
            msg=Event.Load.name,
            step=Event.Completed.name,
            base_url=self.base_url,
            org_id=self.org_id,
            auth=self._auth_kind(),
        )

    def close(self) -> None:
        self.debug(msg=Event.Close.name, step=Event.Started.name)
        if not self.can(DriverAction.UNLOAD):
            return
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None
        self.debug(msg=Event.Close.name, step=Event.Completed.name)

    def metadata(self) -> DriverMetadata:
        return DriverMetadata(
            name=self.__class__.__name__,
            version="1.0",
            protocol="http(s)/grafana-annotations",
            capabilities=["write", "annotation:create", "annotation:update", "annotation:delete"],
        )

    # endregion Lifecycle

    # ---------------------------------------------------------------------- #
    # region Public API
    # ---------------------------------------------------------------------- #

    def health(self) -> Dict[str, Any]:
        """Hit /api/health — useful for smoke-testing local Docker Grafana."""
        response = self._request("GET", HEALTH_PATH)
        return self._json(response) or {}

    def write(self, uri: str = "annotation", data: Any = None, **kwargs) -> Dict[str, Any]:
        """Create / update / delete a Grafana annotation.

        uri forms:
          * ``annotation`` or empty           - create new annotation
          * ``annotation:<id>`` / ``<id>``    - target an existing annotation

        mode (kwarg):
          * ``create`` (default for new)      - POST /api/annotations
          * ``update``                        - PUT  /api/annotations/{id}
          * ``patch``                         - PATCH /api/annotations/{id}
          * ``delete``                        - DELETE /api/annotations/{id}
        """
        annotation_id, default_mode = self._parse_uri(uri)
        mode = (kwargs.pop("mode", None) or default_mode).lower()

        if mode not in WRITE_MODES:
            raise DriverGrafanaError(
                caller=self,
                error=f"Invalid mode '{mode}'. Allowed: {WRITE_MODES}",
            )
        if mode != "create" and annotation_id is None:
            raise DriverGrafanaError(
                caller=self,
                error=f"mode={mode!r} requires an annotation id (uri='annotation:<id>').",
            )

        write_options: dict = {
            **(self.write_options or {}),
            **(kwargs.pop("write_options", {}) or {}),
        }

        self.debug(
            msg=Event.Write.name,
            step=Event.Started.name,
            mode=mode,
            annotation_id=annotation_id,
        )

        try:
            if mode == "delete":
                response = self._request(
                    "DELETE",
                    f"{ANNOTATIONS_PATH}/{annotation_id}",
                    **write_options,
                )
                return self._json(response) or {"deleted": True, "id": annotation_id}

            payload = self._build_payload(data, kwargs)

            if mode == "create":
                response = self._request(
                    "POST",
                    ANNOTATIONS_PATH,
                    json=payload,
                    **write_options,
                )
            elif mode == "patch":
                response = self._request(
                    "PATCH",
                    f"{ANNOTATIONS_PATH}/{annotation_id}",
                    json=payload,
                    **write_options,
                )
            else:  # update
                response = self._request(
                    "PUT",
                    f"{ANNOTATIONS_PATH}/{annotation_id}",
                    json=payload,
                    **write_options,
                )

            result = self._json(response) or {}

            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                mode=mode,
                annotation_id=annotation_id or result.get("id"),
            )
            return result

        except DriverGrafanaError:
            raise
        except requests.HTTPError as e:
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=str(e))
            raise DriverGrafanaError(
                caller=self,
                error=f"write error (mode={mode}, id={annotation_id}): {e}",
            ) from e
        except Exception as e:
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=str(e))
            raise DriverGrafanaError(
                caller=self,
                error=f"write error (mode={mode}, id={annotation_id}): {e}",
            ) from e

    def read(self, *args, **kwargs):  # pragma: no cover - write-only driver
        raise DriverGrafanaError(
            caller=self,
            error="DriverGrafana is write-only (annotations). 'read' is not supported.",
        )

    def search(self, *args, **kwargs):  # pragma: no cover
        raise DriverGrafanaError(
            caller=self,
            error="DriverGrafana is write-only (annotations). 'search' is not supported.",
        )

    # endregion Public API

    # ---------------------------------------------------------------------- #
    # region Internal helpers
    # ---------------------------------------------------------------------- #

    @staticmethod
    def _parse_uri(uri: Optional[str]) -> Tuple[Optional[int], str]:
        if not uri:
            return None, "create"
        text = str(uri).strip()
        if ":" in text:
            head, tail = text.split(":", 1)
            head = head.strip().lower()
            tail = tail.strip()
            if head in ("annotation", "annotations") and tail.isdigit():
                return int(tail), "update"
            if head.isdigit() and not tail:
                return int(head), "update"
        if text.lower() in ("annotation", "annotations", ""):
            return None, "create"
        if text.isdigit():
            return int(text), "update"
        raise DriverGrafanaError(
            caller=None,
            error=f"Unrecognised annotation uri: {uri!r}",
        )

    def _build_payload(self, data: Any, extra: Mapping[str, Any]) -> Dict[str, Any]:
        if data is None:
            payload: Dict[str, Any] = {}
        elif isinstance(data, Mapping):
            payload = dict(data)
        else:
            raise DriverGrafanaError(
                caller=self,
                error=f"Annotation data must be a mapping; got {type(data).__name__}.",
            )

        for k, v in (extra or {}).items():
            payload.setdefault(k, v)

        payload.setdefault("time", self._now_ms())

        if "dashboardUID" not in payload and self.dashboard_uid:
            payload["dashboardUID"] = self.dashboard_uid
        if "dashboardId" not in payload and self.dashboard_id and "dashboardUID" not in payload:
            payload["dashboardId"] = int(self.dashboard_id)
        if "panelId" not in payload and self.panel_id:
            payload["panelId"] = int(self.panel_id)

        merged_tags: List[str] = []
        merged_tags.extend(self.tags or [])
        user_tags = payload.get("tags") or []
        if isinstance(user_tags, str):
            user_tags = [user_tags]
        merged_tags.extend(user_tags)
        seen = set()
        payload["tags"] = [t for t in merged_tags if not (t in seen or seen.add(t))]

        if not payload.get("text"):
            payload["text"] = "wattleflow"

        return payload

    @staticmethod
    def _now_ms() -> int:
        return int(_time.time() * 1000)

    def _build_default_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        if self.org_id is not None:
            headers["X-Grafana-Org-Id"] = str(self.org_id)
        extra = self.headers or {}
        if isinstance(extra, dict):
            headers.update(extra)
        return headers

    def _resolve_auth(self) -> Optional[Tuple[str, str]]:
        if self.api_token:
            return None
        if self.username and self.password:
            return (str(self.username), str(self.password))
        return None

    def _auth_kind(self) -> str:
        if self.api_token:
            return "bearer"
        if self.username and self.password:
            return "basic"
        return "none"

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        if self._session is None:
            raise DriverGrafanaError(caller=self, error="HTTP session is not initialised.")
        url = urljoin(str(self.base_url).rstrip("/") + "/", path.lstrip("/"))
        kwargs.setdefault("timeout", self.request_timeout)
        kwargs.setdefault("verify", self.verify_ssl)
        response = self._session.request(method, url, **kwargs)
        response.raise_for_status()
        return response

    @staticmethod
    def _json(response: requests.Response) -> Any:
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    # endregion Internal helpers

    def __repr__(self) -> str:
        return f"DriverGrafana[{self.base_url}|{self._auth_kind()}]"


# --------------------------------------------------------------------------- #
# endregion Driver                                                            #
# --------------------------------------------------------------------------- #
