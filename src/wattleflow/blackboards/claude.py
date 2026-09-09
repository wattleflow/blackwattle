# Module name: blackboards/claude.py
# Author: (wattleflow@outlook.com)
# Copyright: 2022-2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import hashlib
from abc import ABC
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional
from types import MappingProxyType
from wattleflow.core import (
    IBlackboard,
    IPipeline,
    IProcessor,
    IRepository,
    ITarget,
    IWattleflow,
)
from wattleflow.concrete import Document
from wattleflow.concrete.blackboard import GenericBlackboard
from wattleflow.concrete.exception import BlackboardException
from wattleflow.concrete.memento import GenericMemento
from wattleflow.concrete.strategy import StrategyCreate
from wattleflow.enums.event import Event
from wattleflow.decorators.preset import PresetDecorator
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

Repositories = List[IRepository]


# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class MemoryFileError(Exception):
    pass


class StrNotFoundError(MemoryFileError):
    def __init__(self, path: str, old_str: str):
        self.path = path
        self.old_str = old_str
        super().__init__(f"old_str not found in {path}")


class StrAmbiguousError(MemoryFileError):
    def __init__(self, path: str, old_str: str, line_numbers: list[int]):
        self.path = path
        self.old_str = old_str
        self.line_numbers = line_numbers
        super().__init__(f"Multiple occurrences of old_str in {path} on lines {line_numbers}")


class InvalidLineError(MemoryFileError):
    def __init__(self, line: int, max_line: int):
        self.line = line
        self.max_line = max_line
        super().__init__(f"Invalid line {line}, must be in [0, {max_line}]")


class FileTooLargeError(MemoryFileError):
    LIMIT = 999_999

    def __init__(self, path: str):
        self.path = path
        super().__init__(f"File {path} exceeds maximum line limit of {self.LIMIT}")


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region DataClasses                                                          #
# --------------------------------------------------------------------------- #


@dataclass
class MemoryFile:
    # Anthropic Memory Tool file (path + UTF-8 data). Reference:
    # https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool

    path: str
    data: str = ""

    @property
    def size(self) -> int:
        return len(self.data.encode("utf-8"))

    @property
    def line_count(self) -> int:
        return len(self.data.splitlines())

    def view(self, view_range: Optional[tuple[int, int]] = None) -> str:
        lines = self.data.splitlines()
        if len(lines) > FileTooLargeError.LIMIT:
            raise FileTooLargeError(self.path)

        if view_range is not None:
            start, end = view_range
            end = len(lines) if end == -1 else end
            visible = lines[start - 1 : end]
            start_idx = start
        else:
            visible = lines
            start_idx = 1

        numbered = "\n".join(f"{i + start_idx:>6}\t{line}" for i, line in enumerate(visible))
        return f"Here's the content of {self.path} with line numbers:\n{numbered}"

    def apply_str_replace(self, old_str: str, new_str: str) -> str:
        count = self.data.count(old_str)
        if count == 0:
            raise StrNotFoundError(self.path, old_str)
        if count > 1:
            line_numbers = [
                i + 1 for i, line in enumerate(self.data.splitlines()) if old_str in line
            ]
            raise StrAmbiguousError(self.path, old_str, line_numbers)

        self.data = self.data.replace(old_str, new_str, 1)
        return "\n".join(f"{i + 1:>6}\t{line}" for i, line in enumerate(self.data.splitlines()))

    def apply_insert(self, insert_line: int, insert_text: str) -> None:
        lines = self.data.splitlines(keepends=True)
        n = len(lines)
        if insert_line < 0 or insert_line > n:
            raise InvalidLineError(insert_line, n)
        if not insert_text.endswith("\n"):
            insert_text += "\n"
        lines.insert(insert_line, insert_text)
        self.data = "".join(lines)

    def apply_rename(self, new_path: str) -> None:
        self.path = new_path

    def serialize(self) -> dict:
        return {"path": self.path, "data": self.data}

    @classmethod
    def deserialize(cls, payload: dict) -> "MemoryFile":
        return cls(path=payload["path"], data=payload.get("data", ""))

    def __repr__(self) -> str:
        return f"MemoryFile(path={self.path!r}, size={self.size}B)"


# --------------------------------------------------------------------------- #
# endregion DataClasses                                                       #
# --------------------------------------------------------------------------- #

# ---------------------------------------------------------------------------
# Memory Tool API content type (orthogonal — for future Anthropic Memory Tool
# integration). Not used by the cache flow, but kept as a Document[T] candidate.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# ClaudeDocument — Document[str] specialised for AI summarisation flow.
# Cache state lives directly on the document via metadata (ai_prompt /
# ai_summary), so ClaudeBlackboard.cache_lookup can match by content digest
# against documents already on the canvas — no separate LRU map.
# --------------------------------------------------------------------------- #
# region Documents                                                            #
# --------------------------------------------------------------------------- #


class ClaudeDocument(Document[str], ABC):
    def __init__(
        self,
        filename: str = "",
        **kwargs,
    ):
        super().__init__(content="", **kwargs)
        self.update_metadata(key="filename", value=filename)

    @property
    def filename(self) -> str:
        return str(self._metadata.get("filename", ""))

    @property
    def size(self) -> int:
        try:
            return len(self.content)
        except ValueError:
            return 0

    @property
    def digest(self) -> str:
        return ClaudeDocument.digest_of(self._content or "")

    @staticmethod
    def digest_of(text: str) -> str:
        return hashlib.sha256((text or "").encode("utf-8")).hexdigest()

    @property
    def prompt(self) -> Optional[str]:
        value = self._metadata.get("ai_prompt")
        return str(value) if value else None

    @property
    def summary(self) -> Optional[str]:
        value = self._metadata.get("ai_summary")
        return str(value) if value else None

    def set_summary(self, prompt: str, summary: str) -> None:
        self.update_metadata(key="ai_prompt", value=prompt)
        self.update_metadata(key="ai_summary", value=summary)

    def clean(self) -> None:
        self.debug(msg=Event.Clean.name, step=Event.Started.name)
        self._metadata.clear()
        self._content = None
        self.debug(msg=Event.Clean.name, step=Event.Completed.name)

    def __del__(self) -> None:
        try:
            self.clean()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# endregion Documents                                                         #
# --------------------------------------------------------------------------- #

# ---------------------------------------------------------------------------
# ClaudeBlackboard — extends GenericBlackboard with a singular _content slot
# that tracks the most recently written ClaudeDocument facade. Cache lookups
# scan the canvas by content digest; cache stores route through the
# document's own metadata via standard update_metadata.
# ---------------------------------------------------------------------------

# --------------------------------------------------------------------------- #
# region Blackboard                                                           #
# --------------------------------------------------------------------------- #


class ClaudeBlackboard(GenericBlackboard[ClaudeDocument]):
    __slots__ = (
        "_canvas",
        "_defer_flush",
        "_flushed",
        "_preset",
        "_repositories",
        "_strategy_create",
    )

    # Same declaration as the sibling blackboards: these keys are forwarded to
    # the parent, so the preset must recognise them rather than discard them.
    ALLOWED = ["configuration", "defer_flush", "strategy_create"]

    def __init__(
        self,
        strategy_create: StrategyCreate,
        defer_flush: bool = True,
        **kwargs,
    ):
        # The parent already opens the cooperative chain (Wattleflow ->
        # AuditLogger), asserts the strategy type and builds preset/canvas/
        # repositories; calling AuditLogger.__init__ directly used to skip all
        # of it and re-implement it here.
        super().__init__(
            strategy_create=strategy_create,
            canvas={},
            defer_flush=defer_flush,
            **kwargs,
        )

        self._flushed = False
        self._defer_flush = bool(defer_flush)

        self.debug(
            msg=Event.Constructor.name,
            step=Event.Completed.name,
            preset=self._preset,
            canvas=self._canvas,
            repositories=self._repositories,
        )

    # region Private
    def __del__(self):
        try:
            self.debug(msg=Event.Delete.name, step=Event.Started.name)
            self.clean()
            # Release structural references kept across clean() calls.
            # Use None instead of del to keep slots intact for __getattr__.
            self._strategy_create = None
            self._preset = None
            self.debug(msg=Event.Delete.name, step=Event.Completed.name)
        except Exception:
            pass

    def __emit__(
        self,
        facade: ITarget,
        **kwargs,
    ) -> None:
        """
        Broadcast document (facade) to the registered repositories.
        Blackboard proslijeđuje SEBE kao caller-a — Strategy.execute asertira
        (IRepository, IDriver), pa upstream Pipeline ne smije curiti dalje.
        """
        self.debug(
            msg=Event.Emit.name,
            step=Event.Started.name,
            facade=facade,
            kwargs=kwargs,
        )

        for repository in self._repositories:
            repository.write(caller=self, facade=facade, **kwargs)

        self._flushed = True

        self.debug(
            msg=Event.Emit.name,
            step=Event.Completed.name,
            broadcasted=True,
        )

    # Must be implemented if using PresetDecorator
    def __getattr__(self, name: str) -> Any:
        preset: PresetDecorator = object.__getattribute__(self, "_preset")
        if preset:
            return preset.__getattr__(name)
        return None

    def __repr__(self) -> str:
        return f"{self.name}:{self.count}:{len(self._repositories)}:[{self.levelname}]"

    def _find_by_digest(self, content: str) -> Optional[ITarget]:
        target = ClaudeDocument.digest_of(content)
        for facade in self._canvas.values():
            try:
                document = facade.request()
            except Exception:
                continue
            if isinstance(document, ClaudeDocument) and document.digest == target:
                return facade
        return None

    # Public pair: a pipeline calls these across objects (see the module
    # header). Under a leading underscore they fell through __getattr__ into
    # PresetDecorator, which reported them as "not permitted" rather than
    # as the API they are.
    def cache_lookup(self, content: str) -> Optional[Dict[str, Any]]:
        facade = self._find_by_digest(content)
        if facade is None:
            self.debug(msg=Event.Read.name, cache="miss")
            return None
        document: ClaudeDocument = facade.request()
        if not document.summary:
            self.debug(msg=Event.Read.name, cache="miss-no-summary")
            return None
        self.debug(
            msg=Event.Read.name,
            cache="hit",
            identifier=facade.identifier,
        )
        return {"prompt": document.prompt, "summary": document.summary}

    def cache_store(self, content: str, payload: Dict[str, Any]) -> str:
        facade = self._find_by_digest(content)
        if facade is None:
            self.debug(msg=Event.Write.name, cache="store-skip-not-on-canvas")
            return ""
        document: ClaudeDocument = facade.request()
        document.set_summary(
            prompt=str(payload.get("prompt", "")),
            summary=str(payload.get("summary", "")),
        )
        self.debug(
            msg=Event.Write.name,
            cache="store",
            identifier=facade.identifier,
        )
        return facade.identifier

    # endregion Private

    # region Properties
    @property
    def canvas(self) -> Mapping[str, ITarget]:
        return MappingProxyType(self._canvas)  # Read only

    @property
    def count(self) -> int:
        return len(self._canvas)

    @property
    def defer_flush(self) -> bool:
        return self._defer_flush

    @property
    def repositories(self) -> Repositories:
        return list(self._repositories)

    # endregion Properties

    def clean(self):
        self.debug(
            msg=Event.Clean.name,
            step=Event.Started.name,
            repositories=len(self._repositories),
            canvases=len(self._canvas),
        )

        # Safety-net: ako je canvas neprazan i nije nikad flushan, broadcastaj
        # prije CLEAN-a. Log warning s razlogom.
        if self._canvas and not self._flushed:
            self.warning(
                msg=Event.Clean.name,
                reason="canvas has unflushed facades at lifecycle end",
                cause="defer_flush=%s" % self._defer_flush,
                count=len(self._canvas),
            )
            try:
                for facade in list(self._canvas.values()):
                    self.__emit__(facade=facade)
            except Exception as e:
                self.exception(msg=Event.Clean.name, error=str(e))

        self._canvas.clear()
        self._repositories.clear()
        self._flushed = False

        self.debug(
            msg=Event.Clean.name,
            step=Event.Completed.name,
            repositories=len(self._repositories),
            canvases=len(self._canvas),
        )

    def create(self, caller: IProcessor, **kwargs) -> Optional[ITarget]:
        self.debug(
            msg=Event.Create.name,
            step=Event.Started.name,
            caller=caller.name,
        )

        assert isinstance(caller, IProcessor), "Expected IProcessor. Found %s" % type(caller)

        if not self._strategy_create:
            self.warning(
                msg=Event.Create.name,
                error=f"{self.name}._strategy_create is missing!",
            )
            return None

        self.debug(
            msg=Event.Create.name,
            step=Event.Completed.name,
        )

        # Blackboard proslijeđuje SEBE kao caller-a prema strategiji
        # (strategija asertira IBlackboard). Processor putuje kao kwarg.
        return self._strategy_create.create(
            caller=self, processor=caller, blackboard=self, **kwargs
        )

    def delete(self, identifier: str, **kwargs) -> None:
        self.debug(
            msg=Event.Delete.name,
            step=Event.Started.name,
            id=identifier,
            kwargs=kwargs,
        )

        if identifier in self._canvas:
            del self._canvas[identifier]
            self.debug(
                msg=Event.Deleted.name,
                identifier=identifier,
            )
        else:
            self.warning(
                msg=Event.Delete.name,
                reason="The blackboard neither confirms nor denies the existence!",
                identifier=identifier,
            )
        self.debug(
            msg=Event.Delete.name,
            step=Event.Completed.name,
            id=identifier,
        )

    def flush(self, caller: IWattleflow, **kwargs) -> None:
        # The flush is the blackboard's unit of work — one record per cycle, never
        # per document (NFRQ-OBS-03). A flush with an empty canvas moved nothing, so
        # it is a trace, not a unit: reporting it as INFO would put a line in the
        # operator's stream for work that did not happen.
        pending = self.count
        (self.info if pending else self.debug)(
            msg=Event.Flush.name,
            step=Event.Started.name,
            documents=pending,
        )
        self.debug(
            msg=Event.Flush.name,
            step=Event.Started.name,
            caller=caller.name,
            count=len(self._canvas),
            kwargs=kwargs,
        )

        # flush smije pozvati samo Processor (kraj ciklusa) ili Blackboard
        # (samog sebe, iz clean() safety-neta).
        assert isinstance(caller, (IProcessor, IBlackboard)), (
            "Expected IProcessor or IBlackboard. Found %s" % type(caller)
        )

        if self._defer_flush and not self._flushed:
            for facade in list(self._canvas.values()):
                self.__emit__(facade=facade, **kwargs)

        self._canvas.clear()
        self._flushed = False

        self.debug(
            msg=Event.Flush.name,
            step=Event.Completed.name,
            caller=caller.name,
            count=len(self._canvas),
        )

    def read(self, identifier: str) -> ITarget:
        self.debug(
            msg=Event.Read.name,
            step=Event.Started.name,
            identifier=identifier,
        )

        if identifier not in self._canvas:
            raise BlackboardException(self, f"Document {identifier} not found!")

        facade: ITarget = self._canvas[identifier]

        self.debug(
            msg=Event.Read.name,
            step=Event.Completed.name,
            identifier=identifier,
        )
        return facade

    def read_from(
        self,
        repository_name: str,
        identifier: str,
        **kwargs,
    ) -> ITarget:
        self.debug(
            msg=Event.Read.name,
            step=Event.Started.name,
            repository_name=repository_name,
            identifier=identifier,
        )

        repository = None
        for obj in self._repositories:
            # if hash(repository) == repository_name:
            if obj.name == repository_name:
                repository = obj
                break

        if not repository:
            msg = f"Repository {repository_name} not registered!"
            raise BlackboardException(self, msg)

        self.debug(msg=Event.Read.name, step=Event.Completed.name, repository=repository)

        return repository.read(identifier=identifier, **kwargs)

    def register(self, repository: IRepository) -> None:
        self.debug(msg=Event.Register.name, step=Event.Started.name, repository=repository)

        assert isinstance(repository, IRepository), "Expected IRepository. Found %s" % type(
            repository
        )

        if repository in self._repositories:
            self.warning(
                msg=Event.Register.name,
                repository=repository,
                error="Repository already registered!",
            )
            return

        self._repositories.append(repository)

        self.debug(msg=Event.Register.name, step=Event.Completed.name, added=repository)

    def write(self, pipeline: IPipeline, facade: ITarget, **kwargs) -> str:
        self.debug(
            msg=Event.Write.name,
            step=Event.Started.name,
            pipeline=pipeline.name,
            facade=facade,
            kwargs=kwargs,
        )

        assert isinstance(pipeline, IPipeline), "Expected IPipeline. Found %s" % type(pipeline)
        assert isinstance(facade, ITarget), "Expected ITarget. Found %s" % type(facade)

        if not getattr(facade, "identifier", None):
            raise BlackboardException(self, f"Document:{facade} is missing identifier!")

        document = facade.request()
        self._canvas[facade.identifier] = facade  # type: ignore

        self.debug(
            msg=Event.Write.name,
            action=Event.Stored.value,
            document=document,
            flush=self._defer_flush,
        )

        if not self._repositories:
            self.warning(
                msg=Event.Write.name,
                error="No repositories have been registered.",
            )
            return ""

        # Eager broadcast (defer_flush=False) — audit/debug; normalan rad
        # (defer_flush=True) drži facade na canvasu do explicit flush().
        if not self._defer_flush:
            self.__emit__(facade=facade, **kwargs)

        self.debug(
            msg=Event.Write.name,
            step=Event.Completed.name,
            document=document,  # type: ignore
        )

        return document.identifier  # type: ignore

    # region Memento
    def save_state(self) -> GenericMemento:
        self.debug(msg=Event.Save.name, count=len(self._canvas))
        return GenericMemento(canvas=self._canvas)

    def restore_state(self, memento: GenericMemento) -> None:
        self._canvas = dict(memento.canvas)
        self.debug(msg=Event.Restore.name, count=len(self._canvas))

    # endregion Memento


# --------------------------------------------------------------------------- #
# endregion Blackboard                                                        #
# --------------------------------------------------------------------------- #

__all__ = [
    "ClaudeBlackboard",
    "ClaudeDocument",
    "FileTooLargeError",
    "InvalidLineError",
    "MemoryFile",
    "MemoryFileError",
    "StrAmbiguousError",
    "StrNotFoundError",
]
