# Module name: helpers/config_validator.py
# Author: (wattleflow@outlook.com)
# Copyright: 2022-2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import Iterable

# NOTE: Guarded optional dependency (DR-WFL-003) — `helpers/yaml.py` is a functionally
# complete stdlib fallback, so the effective closure stays stdlib and this module keeps
# its place in the clean core (DR-WFL-002 §2.1 exception). Verified by masking test.
try:
    import yaml as _yaml
except Exception:
    from wattleflow.helpers.yaml import yaml as _yaml

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Types                                                                #
# --------------------------------------------------------------------------- #

REQUIRED_APP_FIELDS = ("type", "name", "description", "version", "environment")
REQUIRED_ENV_FIELDS = ("logging", "managers", "workflows")
REQUIRED_LOGGING_FIELDS = ("level", "format")
REQUIRED_MANAGER_FIELDS = ("connections", "drivers")

REQUIRED_NAMED_FIELDS = ("name", "type")
REQUIRED_DRIVER_FIELDS = ("name", "type", "configuration")
REQUIRED_CONNECTION_FIELDS = ("name", "type", "configuration")

REQUIRED_WORKFLOW_FIELDS = ("name", "type", "processors")
REQUIRED_PROCESSOR_FIELDS = (
    "name",
    "type",
    "configuration",
    "blackboard",
    "pipelines",
)
REQUIRED_BLACKBOARD_FIELDS = ("name", "type", "strategy_create", "repositories")
REQUIRED_REPOSITORY_FIELDS = ("name", "type", "configuration")
REQUIRED_REPOSITORY_CFG_FIELDS = ("driver", "strategy_read", "strategy_write")
REQUIRED_PIPELINE_FIELDS = ("name", "type")

PATH_FIELDS_INPUT = ("source_path", "read_path")
PATH_FIELDS_OUTPUT = ("write_path", "local_path", "repository_path", "path")

STRATEGY_FIELDS = ("strategy_create", "strategy_read", "strategy_write")

# --------------------------------------------------------------------------- #
# endregion Types                                                             #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Classes                                                              #
# --------------------------------------------------------------------------- #


@dataclass
class ValidationError:
    path: str
    message: str

    def __str__(self) -> str:
        return f"[{self.path}] {self.message}"


@dataclass
class ConfigValidator:
    data: Any
    check_paths: bool = False
    strict_paths: bool = False
    check_types: bool = True
    registered_types: set | None = None
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    _driver_names: set = field(default_factory=set)
    _connection_names: set = field(default_factory=set)
    _types: set = field(default_factory=set)

    @classmethod
    def from_file(cls, path: str | Path, **kwargs) -> "ConfigValidator":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {p}")
        with open(p, "r") as f:
            data = _yaml.safe_load(f)
        return cls(data=data, **kwargs)

    # region public API
    def validate(self) -> list:
        self.errors.clear()
        self.warnings.clear()
        self._driver_names.clear()
        self._connection_names.clear()
        self._resolve_types()

        if not isinstance(self.data, dict):
            self._err("$", "root config must be a mapping/dict")
            return self.errors

        self._check_required(self.data, ("app", "infrastructure"), "$")

        app = self.data.get("app")
        env_name = self._validate_app(app)
        self._validate_infrastructure(self.data.get("infrastructure"), env_name)

        return self.errors

    def is_valid(self) -> bool:
        return not self.validate()

    def report(self) -> str:
        parts: list = []
        if self.errors:
            parts.append(f"Config has {len(self.errors)} error(s):")
            parts.extend(f"  - {e}" for e in self.errors)
        if self.warnings:
            parts.append(f"Config has {len(self.warnings)} warning(s):")
            parts.extend(f"  ~ {w}" for w in self.warnings)
        if not parts:
            return "Config is valid."
        return "\n".join(parts)

    def raise_if_invalid(self) -> None:
        errs = self.validate()
        if errs:
            raise ValueError(self.report())

    # endregion

    # region helpers
    def _err(self, path: str, message: str) -> None:
        self.errors.append(ValidationError(path=path, message=message))

    def _warn(self, path: str, message: str) -> None:
        self.warnings.append(ValidationError(path=path, message=message))

    def _resolve_types(self) -> None:
        if self.registered_types is not None:
            self._types = set(self.registered_types)
            return
        if not self.check_types:
            self._types = set()
            return

        self._types = set()

    def _check_type(self, type_name: Any, path: str, kind: str) -> None:
        if not self.check_types or not self._types:
            return
        if type_name is None:
            return
        if not isinstance(type_name, str):
            return
        if type_name not in self._types:
            self._err(
                path,
                f"unknown {kind} type '{type_name}' (not registered in WorkflowFactory)",
            )

    def _check_strategy(self, name: Any, path: str) -> None:
        if not self.check_types or not self._types:
            return
        if name is None or not isinstance(name, str):
            return
        if name not in self._types:
            self._err(
                path,
                f"unknown strategy '{name}' (not registered in WorkflowFactory)",
            )

    def _path_check_one(
        self, value: Any, path: str, must_exist: bool, is_file: bool = False
    ) -> None:
        if not self.check_paths:
            return
        if value is None or not isinstance(value, str) or not value.strip():
            return
        if "$" in value or "{" in value:
            return
        target = Path(value).expanduser()
        if must_exist:
            if not target.exists():
                msg = f"path does not exist: {value}"
                if self.strict_paths:
                    self._err(path, msg)
                else:
                    self._warn(path, msg)
                return
            if is_file and target.is_dir():
                self._err(path, f"expected file, found directory: {value}")
            elif not is_file and target.is_file():
                self._err(path, f"expected directory, found file: {value}")
        else:
            parent = target.parent
            if not parent.exists():
                msg = f"parent directory does not exist: {parent}"
                if self.strict_paths:
                    self._err(path, msg)
                else:
                    self._warn(path, msg)

    def _check_paths_in_cfg(self, cfg: Any, base_path: str) -> None:
        if not self.check_paths or not isinstance(cfg, dict):
            return
        creatable = bool(cfg.get("create"))
        for key in PATH_FIELDS_INPUT:
            if key in cfg:
                self._path_check_one(cfg[key], f"{base_path}.{key}", must_exist=True)
        for key in PATH_FIELDS_OUTPUT:
            if key not in cfg:
                continue
            if creatable:
                continue
            self._path_check_one(cfg[key], f"{base_path}.{key}", must_exist=False)

    def _check_required(self, obj: Any, fields: Iterable[str], path: str) -> bool:
        if not isinstance(obj, dict):
            self._err(path, f"expected mapping, got {type(obj).__name__}")
            return False
        ok = True
        for f in fields:
            if f not in obj or obj[f] in (None, ""):
                self._err(path, f"missing required field '{f}'")
                ok = False
        return ok

    def _check_named_list(self, items: Any, path: str, kind: str) -> list:
        if items is None:
            return []
        if not isinstance(items, list):
            self._err(path, f"{kind} must be a list, got {type(items).__name__}")
            return []
        seen: dict = {}
        valid: list = []
        for idx, item in enumerate(items):
            ipath = f"{path}[{idx}]"
            if not isinstance(item, dict):
                self._err(ipath, f"{kind} item must be a mapping")
                continue
            name = item.get("name")
            if not name:
                self._err(ipath, f"{kind} item missing 'name'")
            else:
                if name in seen:
                    self._err(
                        ipath,
                        f"duplicate {kind} name '{name}' (also at {path}[{seen[name]}])",
                    )
                else:
                    seen[name] = idx
            valid.append((idx, item))
        return valid

    # endregion

    # region app
    def _validate_app(self, app: Any) -> str | None:
        path = "$.app"
        if not isinstance(app, dict):
            self._err(path, "missing or invalid 'app' section")
            return None

        self._check_required(app, REQUIRED_APP_FIELDS, path)

        env = app.get("environment")
        if env is not None and not isinstance(env, str):
            self._err(f"{path}.environment", "must be a string")
            return None
        return env if isinstance(env, str) else None

    # endregion

    # region infrastructure
    def _validate_infrastructure(self, infra: Any, env_name: str | None) -> None:
        path = "$.infrastructure"
        if not isinstance(infra, dict):
            self._err(path, "missing or invalid 'infrastructure' section")
            return

        if not infra:
            self._err(path, "no environments defined")
            return

        if env_name is None:
            return

        if env_name not in infra:
            available = ", ".join(sorted(infra.keys())) or "<none>"
            self._err(
                path,
                f"environment '{env_name}' not found "
                f"(declared in app.environment). Available: {available}",
            )
            return

        env_block = infra[env_name]
        env_path = f"{path}.{env_name}"
        if not isinstance(env_block, dict):
            self._err(env_path, "environment block must be a mapping")
            return

        self._check_required(env_block, REQUIRED_ENV_FIELDS, env_path)
        self._validate_logging(env_block.get("logging"), f"{env_path}.logging")
        self._validate_managers(env_block.get("managers"), f"{env_path}.managers")
        self._validate_workflows(env_block.get("workflows"), f"{env_path}.workflows")

    def _validate_logging(self, logging: Any, path: str) -> None:
        if logging is None:
            return
        if not isinstance(logging, dict):
            self._err(path, "logging must be a mapping")
            return
        self._check_required(logging, REQUIRED_LOGGING_FIELDS, path)

        level = logging.get("level")
        if level is not None and level not in (
            "NOTSET",
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        ):
            self._err(f"{path}.level", f"invalid log level '{level}'")

    # endregion

    # region managers
    def _validate_managers(self, managers: Any, path: str) -> None:
        if managers is None:
            self._err(path, "managers section is missing")
            return
        if not isinstance(managers, dict):
            self._err(path, "managers must be a mapping")
            return

        for f in REQUIRED_MANAGER_FIELDS:
            if f not in managers:
                self._err(path, f"missing '{f}' under managers")

        self._validate_connections(managers.get("connections"), f"{path}.connections")
        self._validate_drivers(managers.get("drivers"), f"{path}.drivers")

    def _validate_connections(self, connections: Any, path: str) -> None:
        items = self._check_named_list(connections, path, "connection")
        for idx, item in items:
            ipath = f"{path}[{idx}]"
            self._check_required(item, REQUIRED_CONNECTION_FIELDS, ipath)
            self._check_type(item.get("type"), f"{ipath}.type", "connection")
            name = item.get("name")
            if isinstance(name, str):
                self._connection_names.add(name)

            cfg = item.get("configuration")
            if isinstance(cfg, dict):
                cn = cfg.get("connection_name")
                if cn and cn != name:
                    self._err(
                        f"{ipath}.configuration.connection_name",
                        f"'{cn}' does not match parent name '{name}'",
                    )

    def _validate_drivers(self, drivers: Any, path: str) -> None:
        items = self._check_named_list(drivers, path, "driver")
        for idx, item in items:
            ipath = f"{path}[{idx}]"
            self._check_required(item, REQUIRED_DRIVER_FIELDS, ipath)
            self._check_type(item.get("type"), f"{ipath}.type", "driver")
            name = item.get("name")
            if isinstance(name, str):
                self._driver_names.add(name)

            cfg = item.get("configuration")
            if isinstance(cfg, dict):
                cn = cfg.get("connection_name")
                if cn and cn not in self._connection_names:
                    self._err(
                        f"{ipath}.configuration.connection_name",
                        f"references unknown connection '{cn}'",
                    )
                self._check_paths_in_cfg(cfg, f"{ipath}.configuration")

    # endregion

    # region workflows
    def _validate_workflows(self, workflows: Any, path: str) -> None:
        if workflows is None:
            self._err(path, "no workflows defined")
            return
        items = self._check_named_list(workflows, path, "workflow")
        for idx, wf in items:
            wpath = f"{path}[{idx}]"
            self._check_required(wf, REQUIRED_WORKFLOW_FIELDS, wpath)
            self._check_type(wf.get("type"), f"{wpath}.type", "workflow")
            self._validate_processors(wf.get("processors"), f"{wpath}.processors")

    def _validate_processors(self, processors: Any, path: str) -> None:
        if processors is None:
            self._err(path, "no processors defined")
            return
        items = self._check_named_list(processors, path, "processor")
        for idx, proc in items:
            ppath = f"{path}[{idx}]"
            self._check_required(proc, REQUIRED_PROCESSOR_FIELDS, ppath)
            self._check_type(proc.get("type"), f"{ppath}.type", "processor")

            cfg = proc.get("configuration")
            if isinstance(cfg, dict):
                self._check_driver_ref(
                    cfg.get("driver"), f"{ppath}.configuration.driver"
                )
                self._check_paths_in_cfg(cfg, f"{ppath}.configuration")

            self._validate_blackboard(proc.get("blackboard"), f"{ppath}.blackboard")
            self._validate_pipelines(proc.get("pipelines"), f"{ppath}.pipelines")

    def _validate_blackboard(self, bb: Any, path: str) -> None:
        if bb is None:
            self._err(path, "blackboard section is missing")
            return
        if not isinstance(bb, dict):
            self._err(path, "blackboard must be a mapping")
            return
        self._check_required(bb, REQUIRED_BLACKBOARD_FIELDS, path)
        self._check_type(bb.get("type"), f"{path}.type", "blackboard")
        self._check_strategy(bb.get("strategy_create"), f"{path}.strategy_create")
        self._validate_repositories(bb.get("repositories"), f"{path}.repositories")

    def _validate_repositories(self, repos: Any, path: str) -> None:
        if repos is None:
            self._err(path, "no repositories defined")
            return
        items = self._check_named_list(repos, path, "repository")
        for idx, repo in items:
            rpath = f"{path}[{idx}]"
            self._check_required(repo, REQUIRED_REPOSITORY_FIELDS, rpath)
            self._check_type(repo.get("type"), f"{rpath}.type", "repository")
            cfg = repo.get("configuration")
            cpath = f"{rpath}.configuration"
            if cfg is None:
                continue
            if not isinstance(cfg, dict):
                self._err(cpath, "configuration must be a mapping")
                continue
            self._check_required(cfg, REQUIRED_REPOSITORY_CFG_FIELDS, cpath)
            self._check_driver_ref(cfg.get("driver"), f"{cpath}.driver")
            self._check_strategy(cfg.get("strategy_read"), f"{cpath}.strategy_read")
            self._check_strategy(cfg.get("strategy_write"), f"{cpath}.strategy_write")

    def _validate_pipelines(self, pipelines: Any, path: str) -> None:
        if pipelines is None:
            self._err(path, "no pipelines defined")
            return
        items = self._check_named_list(pipelines, path, "pipeline")
        for idx, pipe in items:
            ipath = f"{path}[{idx}]"
            self._check_required(pipe, REQUIRED_PIPELINE_FIELDS, ipath)
            self._check_type(pipe.get("type"), f"{ipath}.type", "pipeline")

    def _check_driver_ref(self, ref: Any, path: str) -> None:
        if ref is None:
            return
        if not isinstance(ref, str):
            self._err(
                path, f"driver reference must be a string, got {type(ref).__name__}"
            )
            return
        if ref not in self._driver_names:
            available = ", ".join(sorted(self._driver_names)) or "<none registered>"
            self._err(
                path,
                f"references unknown driver '{ref}'. Available: {available}",
            )

    # endregion


# --------------------------------------------------------------------------- #
# endregion Classes                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Main                                                                 #
# --------------------------------------------------------------------------- #
