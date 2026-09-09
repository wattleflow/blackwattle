# Module name: drivers/kibana.py
# Author: (wattleflow@outlook.com)
# Copyright: @ 2022-2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# IMPORTANT: This driver talks to the Kibana Saved Objects REST API (8.x).    #
# Ensure you have it installed using:                                         #
#     pip install requests                                                    #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import fnmatch
import json
import re
from typing import Any, ClassVar, Dict, Generator, List, Optional, Tuple
from urllib.parse import quote, urljoin

try:
    import requests
except ImportError as e:
    raise ModuleNotFoundError(
        f"requests library is required to run this code.[{str(e)}]\n"
        "Please install it with `pip install requests`"
    ) from e

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


WriteMode = str  # one of: create, update, upsert, delete, bulk

_SAVED_OBJECT_TYPE_RE = re.compile(r"^[a-z0-9][a-z0-9._\-]*$")

# --------------------------------------------------------------------------- #
# endregion Constatns                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class DriverKibanaError(DriverException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Driver                                                               #
# --------------------------------------------------------------------------- #


@oscal_driver(strict=False)
class DriverKibana(GenericDriver):
    ALLOWED = [
        "base_url",  # e.g. "http://kibana:5601"
        "space",  # optional Kibana space id
        "api_key",  # Kibana API key (preferred)
        "bearer",  # Bearer token
        "username",  # basic auth user
        "password",  # basic auth password
        "default_type",  # default saved-object type
        "mode",  # default write mode
        "headers",  # extra headers dict
        "verify_ssl",
        "request_timeout",
        "max_rows",  # cap on _find per_page
        "read_options",
        "write_options",
        "log_queries",
    ]
    # OSCAL: ApiKey/Bearer authorisation, plus `verify_ssl` on every request.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ("ac-3", "ia-5", "sc-8")
    WRITE_MODES = ("create", "update", "upsert", "delete", "bulk")
    DEFAULT_PER_PAGE = 100

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
            raise DriverKibanaError(
                caller=self,
                error="DriverKibana: 'base_url' is required (e.g. 'http://kibana:5601').",
            )

        self.mode = self.mode if self.mode is not None else "create"
        self.verify_ssl = True if self.verify_ssl is None else bool(self.verify_ssl)
        self.request_timeout = self.request_timeout if self.request_timeout is not None else 30
        self.max_rows = self.max_rows if self.max_rows is not None else None
        self.log_queries = self.log_queries if self.log_queries is not None else True

        if self.mode not in self.WRITE_MODES:
            raise DriverKibanaError(
                caller=self,
                error=f"Invalid mode '{self.mode}'. Allowed: {self.WRITE_MODES}",
            )

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
            space=self.space,
            default_type=self.default_type,
            mode=self.mode,
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
            protocol="http(s)/kibana",
            capabilities=["read", "write", "search", "find"],
        )

    # endregion Lifecycle

    # ---------------------------------------------------------------------- #
    # region Read / Write
    # ---------------------------------------------------------------------- #

    def read(self, uri: str, **kwargs) -> Any:
        self.debug(msg=Event.Read.name, step=Event.Started.name, uri=uri)

        if not uri:
            raise DriverKibanaError(caller=self, error="read: uri is required.")

        so_type, so_id, find_params = self._parse_read_uri(uri, kwargs)
        read_options: dict = {
            **(self.read_options or {}),
            **(kwargs.pop("read_options", {}) or {}),
        }

        self._validate_type(so_type)

        if self.log_queries:
            self.debug(
                msg=Event.Read.name,
                step=Event.Completed.name,
                type=so_type,
                id=so_id,
                find=bool(find_params),
            )

        try:
            if so_id is not None:
                path = self._object_path(so_type, so_id)
                response = self._request("GET", path, params=read_options)
                return self._json(response)

            params = dict(find_params or {})
            if "per_page" not in params:
                params["per_page"] = self.max_rows or self.DEFAULT_PER_PAGE
            params.setdefault("type", so_type)
            params.update(read_options)

            path = self._space_path("/api/saved_objects/_find")
            response = self._request("GET", path, params=params)
            payload = self._json(response) or {}
            return payload.get("saved_objects", payload)

        except DriverKibanaError:
            raise
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                self.debug(msg=Event.Read.name, step=Event.Failed.name, type=so_type, id=so_id)
                return None
            raise DriverKibanaError(
                caller=self,
                error=f"read error for type={so_type!r}: {e}",
            ) from e
        except Exception as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=str(e))
            raise DriverKibanaError(
                caller=self,
                error=f"read error for type={so_type!r}: {e}",
            ) from e

    def write(self, uri: str, data: Any = None, **kwargs) -> Any:
        if not uri:
            raise DriverKibanaError(caller=self, error="write: uri is required.")

        so_type, so_id = self._parse_write_uri(uri)
        mode: WriteMode = kwargs.pop("mode", None) or self.mode or "create"
        write_options: dict = {
            **(self.write_options or {}),
            **(kwargs.pop("write_options", {}) or {}),
        }

        if mode not in self.WRITE_MODES:
            raise DriverKibanaError(
                caller=self,
                error=f"Invalid write mode '{mode}'. Allowed: {self.WRITE_MODES}",
            )

        self._validate_type(so_type)

        self.debug(
            msg=Event.Write.name,
            step=Event.Started.name,
            type=so_type,
            id=so_id,
            mode=mode,
        )

        try:
            result = self._execute_write(so_type, so_id, data, mode, write_options)
        except DriverKibanaError:
            raise
        except requests.HTTPError as e:
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=str(e))
            raise DriverKibanaError(
                caller=self,
                error=f"write error for type={so_type!r}: {e}",
            ) from e
        except Exception as e:
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=str(e))
            raise DriverKibanaError(
                caller=self,
                error=f"write error for type={so_type!r}: {e}",
            ) from e

        self.debug(msg=Event.Write.name, step=Event.Completed.name, type=so_type)
        return result

    def search(self, pattern: str, **kwargs) -> Generator[Dict[str, Any], None, None]:
        """Yield saved objects whose `id` or `attributes.title` matches pattern."""
        self.debug(msg=Event.Search.name, step=Event.Started.name, pattern=pattern)

        so_type: Optional[str] = kwargs.pop("type", None) or self.default_type
        per_page = int(kwargs.pop("per_page", self.max_rows or self.DEFAULT_PER_PAGE))
        page = 1

        params: dict = {"per_page": per_page}
        if so_type:
            params["type"] = so_type

        path = self._space_path("/api/saved_objects/_find")

        while True:
            params["page"] = page
            response = self._request("GET", path, params=params)
            payload = self._json(response) or {}
            items: List[Dict[str, Any]] = payload.get("saved_objects") or []
            if not items:
                break

            for item in items:
                label = item.get("id") or ""
                title = (item.get("attributes") or {}).get("title") or ""
                if self._matches(label, pattern) or self._matches(title, pattern):
                    yield item

            total = int(payload.get("total") or 0)
            if page * per_page >= total:
                break
            page += 1

        self.debug(msg=Event.Search.name, step=Event.Completed.name)

    # endregion Read / Write

    # ---------------------------------------------------------------------- #
    # region Internal helpers
    # ---------------------------------------------------------------------- #

    def _execute_write(
        self,
        so_type: str,
        so_id: Optional[str],
        data: Any,
        mode: WriteMode,
        write_options: dict,
    ) -> Any:
        if mode == "delete":
            if so_id is None:
                raise DriverKibanaError(caller=self, error="write(delete): id is required.")
            path = self._object_path(so_type, so_id)
            response = self._request("DELETE", path, params=write_options)
            return self._json(response)

        if mode == "bulk":
            documents = self._coerce_documents(data, expect_list=True)
            actions: List[Dict[str, Any]] = []
            for doc in documents:
                action = {"type": doc.get("type", so_type)}
                if "id" in doc:
                    action["id"] = str(doc["id"])
                action["attributes"] = doc.get("attributes") or doc.get("doc") or {}
                actions.append(action)
            path = self._space_path("/api/saved_objects/_bulk_create")
            response = self._request("POST", path, json=actions, params=write_options)
            return self._json(response)

        doc = self._coerce_documents(data, expect_list=False)
        attributes = doc.get("attributes") if "attributes" in doc else doc
        body: Dict[str, Any] = {"attributes": attributes}
        references = doc.get("references")
        if references is not None:
            body["references"] = references

        if mode == "create":
            if so_id is not None:
                path = self._object_path(so_type, so_id)
            else:
                path = self._space_path(f"/api/saved_objects/{quote(so_type, safe='')}")
            response = self._request("POST", path, json=body, params=write_options)
            return self._json(response)

        if mode in ("update", "upsert"):
            if so_id is None:
                raise DriverKibanaError(caller=self, error=f"write({mode}): id is required.")
            path = self._object_path(so_type, so_id)
            if mode == "upsert":
                opts = dict(write_options)
                opts["overwrite"] = "true"
                response = self._request("POST", path, json=body, params=opts)
            else:
                response = self._request("PUT", path, json=body, params=write_options)
            return self._json(response)

        raise DriverKibanaError(caller=self, error=f"_execute_write: unsupported mode '{mode}'.")

    def _coerce_documents(self, data: Any, expect_list: bool) -> Any:
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (TypeError, ValueError) as e:
                self.debug(msg=Event.Validate.name, step=Event.Failed.name, error=str(e))
                raise DriverKibanaError(
                    caller=self,
                    error=f"_coerce_documents: payload is not valid JSON: {e}",
                ) from e

        if expect_list:
            if isinstance(data, dict):
                return [data]
            if isinstance(data, list):
                if not data:
                    raise DriverKibanaError(caller=self, error="_coerce_documents: empty list.")
                for item in data:
                    if not isinstance(item, dict):
                        raise DriverKibanaError(
                            caller=self,
                            error="_coerce_documents: list must contain dicts only.",
                        )
                return data
            raise DriverKibanaError(
                caller=self,
                error=f"_coerce_documents: unsupported type '{type(data).__name__}'.",
            )

        if isinstance(data, dict):
            return data
        raise DriverKibanaError(
            caller=self,
            error=f"_coerce_documents: dict expected, got '{type(data).__name__}'.",
        )

    def _parse_read_uri(self, uri: str, kwargs: dict) -> Tuple[str, Optional[str], Optional[dict]]:
        """Resolve (type, id, find_params) from uri + kwargs.

        Supported forms:
          * ``type``                       - _find on type
          * ``type/id`` or ``type:id``     - get single object
          * ``find:type?search=...``       - find with inline params
        """
        find_params: Optional[dict] = kwargs.pop("params", None) or kwargs.pop("find", None)
        if isinstance(find_params, str):
            find_params = self._parse_json(find_params, "find")

        stripped = uri.strip()
        if not stripped:
            raise DriverKibanaError(caller=self, error="read: uri is empty.")

        if stripped.lower().startswith("find:"):
            tail = stripped[5:].strip()
            so_type, _, qs = tail.partition("?")
            so_type = so_type.strip() or self.default_type
            if not so_type:
                raise DriverKibanaError(
                    caller=self,
                    error="read: 'find:' uri requires type or default_type.",
                )
            params: dict = dict(find_params or {})
            if qs:
                for pair in qs.split("&"):
                    if "=" in pair:
                        k, v = pair.split("=", 1)
                        params[k] = v
            return so_type, None, params

        for sep in ("/", ":"):
            if sep in stripped:
                head, tail = stripped.split(sep, 1)
                head = head.strip()
                tail = tail.strip()
                if head and tail:
                    return head, tail, find_params

        return stripped, None, find_params

    @staticmethod
    def _parse_write_uri(uri: str) -> Tuple[str, Optional[str]]:
        stripped = uri.strip()
        if not stripped:
            raise DriverKibanaError(caller=None, error="write: uri is empty.")
        for sep in ("/", ":"):
            if sep in stripped:
                head, tail = stripped.split(sep, 1)
                head = head.strip()
                tail = tail.strip()
                if head and tail:
                    return head, tail
                return head or stripped, None
        return stripped, None

    def _object_path(self, so_type: str, so_id: str) -> str:
        return self._space_path(
            f"/api/saved_objects/{quote(so_type, safe='')}/{quote(so_id, safe='')}"
        )

    def _space_path(self, path: str) -> str:
        space = (self.space or "").strip()
        if space and space != "default":
            return f"/s/{quote(space, safe='')}{path}"
        return path

    def _build_default_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "kbn-xsrf": "true",
        }
        if self.api_key:
            headers["Authorization"] = f"ApiKey {self.api_key}"
        elif self.bearer:
            headers["Authorization"] = f"Bearer {self.bearer}"
        extra = self.headers or {}
        if isinstance(extra, dict):
            headers.update(extra)
        return headers

    def _resolve_auth(self) -> Optional[Tuple[str, str]]:
        if self.api_key or self.bearer:
            return None
        if self.username and self.password:
            return (self.username, self.password)
        return None

    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        if self._session is None:
            raise DriverKibanaError(caller=self, error="HTTP session is not initialised.")
        url = urljoin(self.base_url.rstrip("/") + "/", path.lstrip("/"))
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

    @staticmethod
    def _parse_json(payload: str, label: str) -> dict:
        try:
            value = json.loads(payload)
        except (TypeError, ValueError) as e:
            raise DriverKibanaError(
                caller=None,
                error=f"_parse_json: {label} is not valid JSON: {e}",
            ) from e
        if not isinstance(value, dict):
            raise DriverKibanaError(
                caller=None,
                error=f"_parse_json: {label} must decode to a JSON object.",
            )
        return value

    @staticmethod
    def _validate_type(so_type: str) -> None:
        if not so_type:
            raise DriverKibanaError(caller=None, error="Saved object type is empty.")
        if not _SAVED_OBJECT_TYPE_RE.match(so_type):
            raise DriverKibanaError(
                caller=None,
                error=f"Invalid saved object type: '{so_type}'",
            )

    @staticmethod
    def _matches(name: str, pattern: str) -> bool:
        if not pattern or pattern == "*":
            return True
        if any(c in pattern for c in ("*", "?", "[")):
            return fnmatch.fnmatchcase(name.lower(), pattern.lower())
        return pattern.lower() in name.lower()

    # endregion Internal helpers

    def __repr__(self) -> str:
        return f"DriverKibana[{self.base_url}]"


# --------------------------------------------------------------------------- #
# endregion Driver                                                            #
# --------------------------------------------------------------------------- #
