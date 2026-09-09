# Module name: drivers/language_model.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# Persistence layer for language models — FR-DRV-13 / HLRQ-13.                 #
#                                                                             #
# The download trigger belongs to the library (transformers / huggingface_hub);#
# this driver does not reimplement it. It moves the trigger to workflow start  #
# (BR-07), refuses a silent fetch (BR-08) and makes a long fetch visible       #
# (BR-09), so a pipeline always finds the model locally.                       #
#                                                                             #
# Dependencies (lazy): huggingface_hub                                         #
#       pip install huggingface_hub                                            #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
import time
from pathlib import Path
from typing import ClassVar, Optional, Tuple

from wattleflow.concrete.exception import DriverException
from wattleflow.enums.event import Event

from wattleflow.concrete.driver import DriverAction, DriverMetadata, GenericDriver
from wattleflow.decorators.oscal import oscal_driver
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["DriverLanguageModel", "DriverLanguageModelError", "ModelStatus"]

# Presence is decided on the two files every model repository carries; the exact
# definition of "valid model" is still open (FR-CON-13.1 §11).
CONFIG_FILE = "config.json"
WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin")

DEFAULT_PROGRESS_INTERVAL = 10.0

# --------------------------------------------------------------------------- #
# region Types                                                                #
# --------------------------------------------------------------------------- #


class DriverLanguageModelError(DriverException):
    """Model is unreachable, unusable, or fetching it is not permitted."""


class ModelStatus(str):
    """Status of a model in the local store (FR-DRV-13 §5 t.3)."""

    PRESENT = "present"
    MISSING = "missing"
    INCOMPLETE = "incomplete"


# --------------------------------------------------------------------------- #
# endregion Types                                                             #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Driver                                                               #
# --------------------------------------------------------------------------- #


# NOTE: the gate is carried by this class, not by a base. The declaration is
# empty on purpose: the Hub is reached only through ConnectionHuggingFace, which
# declares access (ac-3), credential (ia-5) and transport (sc-8). Restating them
# here would claim the same control at two levels (BR-OSCAL-04).
@oscal_driver(strict=False)
class DriverLanguageModel(GenericDriver):
    """Guarantees a locally available model and reports on the way there."""

    # Access — how the subsystem is reached (FR-DRV-13 §4).
    ACCESS = [
        "connection_manager",
        "connection_name",
        "model",
        "revision",
    ]

    # Call — how this driver behaves per run (BR-08, BR-09).
    CALL = [
        "allow_download",
        "progress_interval",
    ]

    ALLOWED = ACCESS + CALL

    # OSCAL: reaches the Hub only through ConnectionHuggingFace, which declares the
    # controls; this class holds no authenticator of its own.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._local_path: Optional[Path] = None
        self.ensure_live()

    def metadata(self) -> DriverMetadata:
        return DriverMetadata(
            name=self.__class__.__name__,
            version="1.0",
            protocol="https",
            capabilities=["read", "download", "update"],
        )

    # region lifecycle
    def load(self) -> None:
        """EV01/EV02 — everything here happens before the first document."""
        self.debug(msg=Event.Load.name, step=Event.Started.name)

        self._install_http_backend()
        self._local_path = self.ensure_local()

        self.debug(
            msg=Event.Load.name,
            step=Event.Completed.name,
            model=self.model,
            local_path=str(self._local_path),
        )

    def close(self) -> None:
        self.debug(msg=Event.Close.name, step=Event.Started.name)
        if not self.can(DriverAction.UNLOAD):
            return
        self._local_path = None
        self.debug(msg=Event.Close.name, step=Event.Completed.name)

    # endregion lifecycle

    # region public API
    def status(self, model: Optional[str] = None) -> str:
        """Cheap check against the local store; never fetches (FR-DRV-13 §5 t.3)."""
        from huggingface_hub import try_to_load_from_cache

        connection = self._connection()
        repo_id = model or self.model
        cache_dir = str(connection.cache_dir)
        revision = getattr(self, "revision", None)

        config = try_to_load_from_cache(
            repo_id=repo_id, filename=CONFIG_FILE, cache_dir=cache_dir, revision=revision
        )
        if not isinstance(config, str):
            return ModelStatus.MISSING

        weights = [
            try_to_load_from_cache(
                repo_id=repo_id, filename=name, cache_dir=cache_dir, revision=revision
            )
            for name in WEIGHT_FILES
        ]
        if not any(isinstance(found, str) for found in weights):
            # A repository half-fetched earlier must not pass as usable.
            return ModelStatus.INCOMPLETE
        return ModelStatus.PRESENT

    def ensure_local(self, model: Optional[str] = None) -> Path:
        """Return the local snapshot path, fetching only when permitted (BR-07, BR-08)."""
        repo_id = model or self.model
        state = self.status(repo_id)

        self.debug(
            msg=Event.Load.name,
            step=Event.Started.name,
            model=repo_id,
            cache_dir=str(self._connection().cache_dir),
        )

        if state == ModelStatus.PRESENT:
            return self._snapshot_path(repo_id)

        if not self._download_allowed():
            raise DriverLanguageModelError(
                caller=self,
                error=(
                    f"Model {repo_id!r} is {state} in the local store and fetching is not "
                    "permitted. Set configuration.allow_download: true, or place the model "
                    "in the cache, or point the connection at a store that holds it."
                ),
                category="permission",
            )

        return self.download(repo_id)

    def download(self, uri: Optional[str] = None, **kwargs) -> Path:
        """EV04 — run the library's own fetch, with progress in the audit log."""
        from huggingface_hub import snapshot_download

        connection = self._connection()
        repo_id = uri or self.model
        started = time.monotonic()

        self.debug(
            msg=Event.Download.name,
            step=Event.Started.name,
            model=repo_id,
            revision=getattr(self, "revision", None),
            endpoint=connection.endpoint,
        )

        try:
            path = snapshot_download(
                repo_id=repo_id,
                revision=getattr(self, "revision", None),
                cache_dir=str(connection.cache_dir),
                tqdm_class=self._progress_class(repo_id),
                **kwargs,
            )
        except Exception as e:
            self.debug(msg=Event.Download.name, step=Event.Failed.name, error=str(e))
            raise self._as_driver_error(e, repo_id) from e

        self.debug(
            msg=Event.Download.name,
            step=Event.Completed.name,
            model=repo_id,
            local_path=path,
            seconds=round(time.monotonic() - started, 1),
        )
        return Path(path)

    def update(self, uri: Optional[str] = None, **kwargs) -> Path:
        """Refresh the local copy against the configured revision."""
        return self.download(uri, **kwargs)

    def read(self, uri: str, **kwargs) -> str:
        """Local path of a model that is guaranteed present (FR-DRV-13 §5 t.6)."""
        return str(self.ensure_local(uri))

    def write(self, uri: str, **kwargs) -> str:
        raise DriverLanguageModelError(
            caller=self,
            error=(
                "write() over a model has no agreed meaning yet — storing inference "
                "output, feeding content, or fine-tuning (FR-DRV-13 §11). Until the "
                "decision is recorded this driver refuses rather than guesses."
            ),
        )

    # endregion public API

    # region private
    def _connection(self):
        """The only route to the subsystem: manager plus name (FR-DRV-13 §4)."""
        manager = getattr(self, "connection_manager", None)
        name = getattr(self, "connection_name", None)
        if manager is None or not name:
            raise DriverLanguageModelError(
                caller=self,
                error="`connection_manager` and `connection_name` are required (BR-01).",
            )
        return manager.get_connection(name)

    def _download_allowed(self) -> bool:
        connection = self._connection()
        if getattr(connection, "offline", False):
            return False
        return bool(getattr(self, "allow_download", False))

    def _install_http_backend(self) -> None:
        """Route the Hub through the connection's session.

        `configure_http_backend` is process-global, so this is logged: two drivers
        with different proxies in one process would overwrite each other
        (analysis 2026-08-20-proxy-vs-huggingface-connection §3).
        """
        from huggingface_hub import configure_http_backend

        connection = self._connection()
        if not hasattr(connection, "connect"):
            return

        def backend_factory():
            with connection.connect() as session:
                return session

        configure_http_backend(backend_factory)
        self.debug(
            msg=Event.Configure.name,
            step=Event.Started.name,
            connection=getattr(connection, "connection_name", None),
            scope="process-global",
        )

    def _snapshot_path(self, repo_id: str) -> Path:
        from huggingface_hub import try_to_load_from_cache

        cached = try_to_load_from_cache(
            repo_id=repo_id,
            filename=CONFIG_FILE,
            cache_dir=str(self._connection().cache_dir),
            revision=getattr(self, "revision", None),
        )
        return Path(str(cached)).parent

    def _progress_class(self, repo_id: str):
        """tqdm replacement that reports into the audit log (BR-09)."""
        from tqdm.auto import tqdm as _tqdm

        driver = self
        interval = float(getattr(self, "progress_interval", None) or DEFAULT_PROGRESS_INTERVAL)

        class _AuditProgress(_tqdm):
            def __init__(self, *args, **kwargs):
                kwargs.setdefault("disable", True)  # no bars on the terminal
                self._done = 0
                self._size = kwargs.get("total") or 0
                super().__init__(*args, **kwargs)
                self._started = time.monotonic()
                self._reported = 0.0

            def update(self, n=1):
                result = super().update(n)
                # A disabled tqdm keeps no counter, so the transferred amount is
                # tracked here — otherwise every progress line would report zero.
                self._done += int(n or 0)
                now = time.monotonic()
                if now - self._reported < interval:
                    return result
                self._reported = now
                total = self._size or getattr(self, "total", None) or 0
                done = self._done
                driver.info(
                    msg=Event.Downloading.name,
                    step="progress",
                    model=repo_id,
                    transferred=done,
                    total=total,
                    percent=round(done * 100.0 / total, 1) if total else None,
                    elapsed=round(now - self._started, 1),
                )
                return result

        return _AuditProgress

    def _as_driver_error(self, error: Exception, repo_id: str) -> DriverLanguageModelError:
        """Map the library's failures onto the classes the flow names (FR-DRV-13 §6)."""
        from huggingface_hub.errors import (
            GatedRepoError,
            LocalEntryNotFoundError,
            OfflineModeIsEnabled,
            RepositoryNotFoundError,
            RevisionNotFoundError,
        )

        # Order matters: GatedRepoError subclasses RepositoryNotFoundError, so the
        # specific class must be tested first or a gated model reads as "missing".
        categories = (
            (GatedRepoError, "permission", "access conditions are not accepted for this account"),
            (RevisionNotFoundError, "not-found", "revision does not exist"),
            (RepositoryNotFoundError, "not-found", "repository does not exist"),
            (OfflineModeIsEnabled, "offline", "offline mode forbids the fetch"),
            (LocalEntryNotFoundError, "reachability", "not in the store and not reachable"),
        )
        for kind, category, reason in categories:
            if isinstance(error, kind):
                return DriverLanguageModelError(
                    caller=self,
                    error=f"{repo_id}: {reason} ({category}).",
                    category=category,
                )
        return DriverLanguageModelError(
            caller=self, error=f"{repo_id}: fetch failed — {error}", category="unknown"
        )

    # endregion private


# --------------------------------------------------------------------------- #
# endregion Driver                                                            #
# --------------------------------------------------------------------------- #
