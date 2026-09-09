# Module name: drivers/prometheus.py
# Author: (wattleflow@outlook.com)
# Copyright: @ 2022-2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# IMPORTANT: This driver requires requests library.                           #
# Ensure you have it installed using:                                         #
#     pip install requests                                                    #
#                                                                             #
# DriverPrometheus — read PromQL via Prometheus HTTP API and write metrics    #
# via Pushgateway exposition format.                                          #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
import fnmatch
import re

try:
    import requests
except ImportError as e:
    raise ModuleNotFoundError(
        f"requests library is required to run this code.[{str(e)}]\n"
        "Please install it with `pip install requests`"
    ) from e

from typing import Any, ClassVar, Dict, Generator, List, Mapping, Optional, Tuple
from urllib.parse import quote, urljoin
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
# region Constans                                                             #
# --------------------------------------------------------------------------- #


WriteMode = str  # one of: push, delete, replace

_METRIC_NAME_RE = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
_LABEL_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# --------------------------------------------------------------------------- #
# endregion Constans                                                          #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class DriverPrometheusError(DriverException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Driver                                                               #
# --------------------------------------------------------------------------- #


@oscal_driver(strict=False)
class DriverPrometheus(GenericDriver):
    ALLOWED = [
        "base_url",  # Prometheus base URL (e.g. "http://prom:9090")
        "pushgateway_url",  # optional pushgateway base URL
        "job",  # default job name for writes
        "instance",  # default instance label for writes
        "api_key",  # optional bearer-style token
        "bearer",  # bearer token
        "username",
        "password",
        "headers",
        "verify_ssl",
        "request_timeout",
        "step",  # default range step (e.g. "30s")
        "max_rows",  # cap on returned series
        "read_options",
        "write_options",
        "log_queries",
    ]
    # OSCAL: bearer/api-key/basic auth, plus `verify_ssl` on every request.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ("ac-3", "ia-5", "sc-8")
    WRITE_MODES = ("push", "replace", "delete")
    READ_ROUTES = {
        "query": "/api/v1/query",
        "query_range": "/api/v1/query_range",
        "series": "/api/v1/series",
        "labels": "/api/v1/labels",
        "label_values": "/api/v1/label/{name}/values",
        "targets": "/api/v1/targets",
        "alerts": "/api/v1/alerts",
        "rules": "/api/v1/rules",
    }

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._session: Optional[requests.Session] = None
        self.ensure_live()

    # ---------------------------------------------------------------------- #
    # region Lifecycle
    # ---------------------------------------------------------------------- #

    def load(self) -> None:
        self.debug(msg=Event.Load.name, step=Event.Started.name)

        if not self.base_url and not self.pushgateway_url:
            raise DriverPrometheusError(
                caller=self,
                error="DriverPrometheus: 'base_url' or 'pushgateway_url' is required.",
            )

        self.verify_ssl = True if self.verify_ssl is None else bool(self.verify_ssl)
        self.request_timeout = self.request_timeout if self.request_timeout is not None else 30
        self.max_rows = self.max_rows if self.max_rows is not None else None
        self.log_queries = self.log_queries if self.log_queries is not None else True
        self.step = self.step or "30s"

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
            pushgateway_url=self.pushgateway_url,
            job=self.job,
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
            protocol="http(s)/prometheus",
            capabilities=["read", "write", "query", "query_range", "push"],
        )

    # endregion Lifecycle

    # ---------------------------------------------------------------------- #
    # region Read / Write
    # ---------------------------------------------------------------------- #

    def read(self, uri: str, **kwargs) -> Any:
        """Execute a PromQL or metadata read.

        Supported uri forms:
          * ``<promql>``                       - instant query
          * ``query:<promql>``                 - instant query
          * ``query_range:<promql>``           - range query (needs start/end/step)
          * ``series:<match[]>[,<match[]>...]``- /api/v1/series
          * ``labels``                         - list label names
          * ``label_values:<name>``            - list values for a label
          * ``targets`` / ``alerts`` / ``rules``
        """
        self.debug(msg=Event.Read.name, step=Event.Started.name, uri=uri)

        if not uri:
            raise DriverPrometheusError(caller=self, error="read: uri is required.")
        if not self.base_url:
            raise DriverPrometheusError(caller=self, error="read: 'base_url' is not configured.")

        route, path, params = self._parse_read_uri(uri, kwargs)
        read_options: dict = {
            **(self.read_options or {}),
            **(kwargs.pop("read_options", {}) or {}),
        }
        if read_options:
            params.update(read_options)

        if self.log_queries:
            self.debug(
                msg=Event.Read.name,
                route=route,
                params=self._safe_params(params),
            )

        try:
            response = self._request("GET", path, params=params, base=self.base_url)
            payload = self._json(response) or {}
        except requests.HTTPError as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=str(e))
            raise DriverPrometheusError(
                caller=self,
                error=f"read error for route={route!r}: {e}",
            ) from e
        except Exception as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=str(e))
            raise DriverPrometheusError(
                caller=self,
                error=f"read error for route={route!r}: {e}",
            ) from e

        result = self._extract_result(payload)
        if isinstance(result, list) and self.max_rows:
            result = result[: int(self.max_rows)]

        self.debug(
            msg=Event.Read.name,
            step=Event.Completed.name,
            route=route,
            count=len(result) if isinstance(result, list) else 1,
        )
        return result

    def write(self, uri: str, data: Any = None, **kwargs) -> Any:
        """Push metrics to a Pushgateway grouping.

        Supported uri forms:
          * ``<job>``                  - job grouping (uses default instance if set)
          * ``<job>/<label>=<value>...``
          * ``<job>:<instance>``       - shorthand: job + instance label
        """
        if not uri:
            raise DriverPrometheusError(caller=self, error="write: uri is required.")
        if not self.pushgateway_url:
            raise DriverPrometheusError(
                caller=self,
                error="write: 'pushgateway_url' is not configured.",
            )

        job, grouping = self._parse_write_uri(uri)
        mode: WriteMode = kwargs.pop("mode", None) or "push"
        write_options: dict = {
            **(self.write_options or {}),
            **(kwargs.pop("write_options", {}) or {}),
        }

        if mode not in self.WRITE_MODES:
            raise DriverPrometheusError(
                caller=self,
                error=f"Invalid write mode '{mode}'. Allowed: {self.WRITE_MODES}",
            )

        self._validate_label("job", job)
        for label, value in grouping.items():
            self._validate_label(label, value)

        path = self._pushgateway_path(job, grouping)

        self.debug(
            msg=Event.Write.name,
            step=Event.Started.name,
            job=job,
            grouping=grouping,
            mode=mode,
        )

        try:
            if mode == "delete":
                response = self._request("DELETE", path, base=self.pushgateway_url)
                return self._json(response) or {"deleted": True}

            body = self._coerce_exposition(data, kwargs.pop("timestamp_ms", None))
            method = "PUT" if mode == "replace" else "POST"
            headers = {"Content-Type": "text/plain; version=0.0.4"}

            response = self._request(
                method,
                path,
                base=self.pushgateway_url,
                data=body.encode("utf-8"),
                headers=headers,
                **write_options,
            )
            return self._json(response) or {"status": "ok", "bytes": len(body)}

        except DriverPrometheusError:
            raise
        except requests.HTTPError as e:
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=str(e))
            raise DriverPrometheusError(
                caller=self,
                error=f"write error for job={job!r}: {e}",
            ) from e
        except Exception as e:
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=str(e))
            raise DriverPrometheusError(
                caller=self,
                error=f"write error for job={job!r}: {e}",
            ) from e

    def search(self, pattern: str, **kwargs) -> Generator[str, None, None]:
        """Yield metric names whose label matches the given fnmatch pattern.

        Uses Prometheus /api/v1/label/__name__/values.
        """
        if not self.base_url:
            raise DriverPrometheusError(caller=self, error="search: 'base_url' is not configured.")

        self.debug(msg=Event.Search.name, step=Event.Started.name, pattern=pattern)

        path = "/api/v1/label/__name__/values"
        try:
            response = self._request("GET", path, base=self.base_url)
            payload = self._json(response) or {}
        except Exception as e:
            self.debug(msg=Event.Search.name, step=Event.Failed.name, error=str(e))
            raise DriverPrometheusError(caller=self, error=f"search error: {e}") from e

        names: List[str] = payload.get("data") or []
        for name in names:
            if self._matches(name, pattern):
                yield name

        self.debug(msg=Event.Search.name, step=Event.Completed.name)

    # endregion Read / Write

    # ---------------------------------------------------------------------- #
    # region Internal helpers - read
    # ---------------------------------------------------------------------- #

    def _parse_read_uri(self, uri: str, kwargs: dict) -> Tuple[str, str, Dict[str, Any]]:
        stripped = uri.strip()
        params: Dict[str, Any] = dict(kwargs.pop("params", None) or {})

        for keyword in (
            "query_range",
            "query",
            "series",
            "label_values",
            "labels",
            "targets",
            "alerts",
            "rules",
        ):
            if stripped == keyword or stripped.lower().startswith(f"{keyword}:"):
                tail = stripped[len(keyword) + 1 :].strip() if ":" in stripped else ""
                return self._build_read_route(keyword, tail, params, kwargs)

        # Bare PromQL → instant query
        params.setdefault("query", stripped)
        return "query", self.READ_ROUTES["query"], params

    def _build_read_route(
        self, route: str, tail: str, params: Dict[str, Any], kwargs: dict
    ) -> Tuple[str, str, Dict[str, Any]]:
        path_tmpl = self.READ_ROUTES[route]

        if route == "query":
            if tail:
                params.setdefault("query", tail)
            params.setdefault("query", kwargs.pop("query", None))
            if not params.get("query"):
                raise DriverPrometheusError(caller=self, error="read(query): PromQL is required.")
            time = kwargs.pop("time", None)
            if time is not None:
                params.setdefault("time", time)
            return route, path_tmpl, params

        if route == "query_range":
            if tail:
                params.setdefault("query", tail)
            params.setdefault("query", kwargs.pop("query", None))
            for k in ("start", "end", "step"):
                val = kwargs.pop(k, None)
                if val is not None:
                    params.setdefault(k, val)
            params.setdefault("step", self.step)
            for k in ("query", "start", "end"):
                if not params.get(k):
                    raise DriverPrometheusError(
                        caller=self,
                        error=f"read(query_range): '{k}' is required.",
                    )
            return route, path_tmpl, params

        if route == "series":
            matches = [m.strip() for m in tail.split(",") if m.strip()]
            extra = kwargs.pop("match", None)
            if isinstance(extra, str):
                matches.append(extra)
            elif isinstance(extra, (list, tuple)):
                matches.extend(extra)
            if not matches:
                raise DriverPrometheusError(
                    caller=self, error="read(series): at least one match[] is required."
                )
            params.setdefault("match[]", matches)
            for k in ("start", "end"):
                val = kwargs.pop(k, None)
                if val is not None:
                    params.setdefault(k, val)
            return route, path_tmpl, params

        if route == "labels":
            for k in ("start", "end"):
                val = kwargs.pop(k, None)
                if val is not None:
                    params.setdefault(k, val)
            return route, path_tmpl, params

        if route == "label_values":
            name = tail or kwargs.pop("name", None)
            if not name:
                raise DriverPrometheusError(
                    caller=self, error="read(label_values): label name is required."
                )
            self._validate_label_name(name)
            return route, path_tmpl.format(name=quote(name, safe="")), params

        return route, path_tmpl, params

    @staticmethod
    def _extract_result(payload: Dict[str, Any]) -> Any:
        if not isinstance(payload, dict):
            return payload
        if payload.get("status") and payload.get("status") != "success":
            return payload
        data = payload.get("data")
        if isinstance(data, dict) and "result" in data:
            return data["result"]
        return data if data is not None else payload

    # endregion Internal helpers - read

    # ---------------------------------------------------------------------- #
    # region Internal helpers - write
    # ---------------------------------------------------------------------- #

    def _parse_write_uri(self, uri: str) -> Tuple[str, Dict[str, str]]:
        stripped = uri.strip()
        if not stripped:
            raise DriverPrometheusError(caller=self, error="write: uri is empty.")

        grouping: Dict[str, str] = {}
        if self.instance:
            grouping["instance"] = str(self.instance)

        if ":" in stripped and "/" not in stripped:
            head, tail = stripped.split(":", 1)
            head = head.strip() or (self.job or "")
            tail = tail.strip()
            if tail:
                grouping["instance"] = tail
            return head, grouping

        parts = [p for p in stripped.split("/") if p]
        if not parts:
            raise DriverPrometheusError(caller=self, error="write: job is required.")
        job = parts[0]
        if job == "job" and len(parts) >= 2:
            job = parts[1]
            parts = parts[2:]
        else:
            parts = parts[1:]

        i = 0
        while i + 1 < len(parts):
            label, value = parts[i], parts[i + 1]
            if "=" in label and i + 1 >= len(parts):
                k, v = label.split("=", 1)
                grouping[k] = v
                i += 1
            else:
                grouping[label] = value
                i += 2

        if not job and self.job:
            job = self.job
        return job, grouping

    def _pushgateway_path(self, job: str, grouping: Mapping[str, str]) -> str:
        if not job:
            raise DriverPrometheusError(caller=self, error="pushgateway: job is required.")
        segments = [f"metrics/job/{quote(job, safe='')}"]
        for label, value in grouping.items():
            segments.append(f"{quote(label, safe='')}/{quote(str(value), safe='')}")
        return "/" + "/".join(segments)

    def _coerce_exposition(self, data: Any, timestamp_ms: Optional[int]) -> str:
        """Build Prometheus exposition format from dict/list/str payloads."""
        if isinstance(data, bytes):
            data = data.decode("utf-8")

        if isinstance(data, str):
            text = data.strip()
            if not text.endswith("\n"):
                text += "\n"
            return text

        samples: List[Tuple[str, Dict[str, str], float]] = []

        if isinstance(data, Mapping):
            for metric, value in data.items():
                samples.extend(self._unpack_metric(metric, value))
        elif isinstance(data, list):
            for entry in data:
                if not isinstance(entry, Mapping):
                    raise DriverPrometheusError(
                        caller=self,
                        error="_coerce_exposition: list entries must be dicts.",
                    )
                name = entry.get("name") or entry.get("metric")
                if not name:
                    raise DriverPrometheusError(
                        caller=self,
                        error="_coerce_exposition: each entry needs a 'name'.",
                    )
                value = entry.get("value")
                if value is None:
                    raise DriverPrometheusError(
                        caller=self,
                        error=f"_coerce_exposition: metric '{name}' missing 'value'.",
                    )
                labels = dict(entry.get("labels") or {})
                samples.append((name, labels, float(value)))
        else:
            raise DriverPrometheusError(
                caller=self,
                error=f"_coerce_exposition: unsupported type '{type(data).__name__}'.",
            )

        if not samples:
            raise DriverPrometheusError(
                caller=self, error="_coerce_exposition: no samples to push."
            )

        lines: List[str] = []
        for name, labels, value in samples:
            self._validate_metric_name(name)
            for label in labels:
                self._validate_label_name(label)
            label_str = self._format_labels(labels)
            suffix = f" {int(timestamp_ms)}" if timestamp_ms else ""
            lines.append(f"{name}{label_str} {value}{suffix}")

        return "\n".join(lines) + "\n"

    def _unpack_metric(self, metric: str, value: Any) -> List[Tuple[str, Dict[str, str], float]]:
        if isinstance(value, (int, float)):
            return [(metric, {}, float(value))]
        if isinstance(value, Mapping):
            if "value" in value:
                labels = dict(value.get("labels") or {})
                return [(metric, labels, float(value["value"]))]
            out: List[Tuple[str, Dict[str, str], float]] = []
            for label_combo, sample in value.items():
                labels = self._parse_label_combo(label_combo)
                if isinstance(sample, (int, float)):
                    out.append((metric, labels, float(sample)))
                elif isinstance(sample, Mapping) and "value" in sample:
                    merged = {**labels, **(sample.get("labels") or {})}
                    out.append((metric, merged, float(sample["value"])))
                else:
                    raise DriverPrometheusError(
                        caller=self,
                        error=f"_unpack_metric: unsupported value for '{metric}'.",
                    )
            return out
        if isinstance(value, list):
            return [(metric, {}, float(v)) for v in value]
        raise DriverPrometheusError(
            caller=self,
            error=f"_unpack_metric: unsupported value type for '{metric}'.",
        )

    @staticmethod
    def _parse_label_combo(combo: str) -> Dict[str, str]:
        if not combo:
            return {}
        labels: Dict[str, str] = {}
        for pair in combo.split(","):
            if "=" not in pair:
                continue
            k, v = pair.split("=", 1)
            labels[k.strip()] = v.strip().strip('"')
        return labels

    @staticmethod
    def _format_labels(labels: Mapping[str, str]) -> str:
        if not labels:
            return ""
        parts = []
        for k, v in labels.items():
            escaped = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            parts.append(f'{k}="{escaped}"')
        return "{" + ",".join(parts) + "}"

    # endregion Internal helpers - write

    # ---------------------------------------------------------------------- #
    # region HTTP / static helpers
    # ---------------------------------------------------------------------- #

    def _build_default_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Accept": "application/json"}
        token = self.bearer or self.api_key
        if token:
            headers["Authorization"] = f"Bearer {token}"
        extra = self.headers or {}
        if isinstance(extra, dict):
            headers.update(extra)
        return headers

    def _resolve_auth(self) -> Optional[Tuple[str, str]]:
        if self.bearer or self.api_key:
            return None
        if self.username and self.password:
            return (self.username, self.password)
        return None

    def _request(self, method: str, path: str, base: str, **kwargs) -> requests.Response:
        if self._session is None:
            raise DriverPrometheusError(caller=self, error="HTTP session is not initialised.")
        url = urljoin(base.rstrip("/") + "/", path.lstrip("/"))
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
    def _safe_params(params: Mapping[str, Any]) -> Dict[str, Any]:
        return {
            k: ("***" if k in ("api_key", "token", "password") else v) for k, v in params.items()
        }

    @staticmethod
    def _validate_metric_name(name: str) -> None:
        if not _METRIC_NAME_RE.match(name or ""):
            raise DriverPrometheusError(caller=None, error=f"Invalid metric name: '{name}'")

    @staticmethod
    def _validate_label_name(name: str) -> None:
        if not _LABEL_NAME_RE.match(name or ""):
            raise DriverPrometheusError(caller=None, error=f"Invalid label name: '{name}'")

    def _validate_label(self, label: str, value: str) -> None:
        if not value:
            raise DriverPrometheusError(caller=self, error=f"Label '{label}' has empty value.")
        if label != "job":
            self._validate_label_name(label)

    @staticmethod
    def _matches(name: str, pattern: str) -> bool:
        if not pattern or pattern == "*":
            return True
        if any(c in pattern for c in ("*", "?", "[")):
            return fnmatch.fnmatchcase(name.lower(), pattern.lower())
        return pattern.lower() in name.lower()

    # endregion HTTP / static helpers

    def __repr__(self) -> str:
        return f"DriverPrometheus[{self.base_url or self.pushgateway_url}]"


# --------------------------------------------------------------------------- #
# endregion Driver                                                            #
# --------------------------------------------------------------------------- #
