# Module name: blackboards/bundle.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional
from wattleflow.core import (
    IBlackboard,
    IPipeline,
    IProcessor,
    IRepository,
    ITarget,
    IWattleflow,
)
from wattleflow.concrete.blackboard import (
    TRANSITIONS,
    BlackboardAction,
    BlackboardState,
    GenericBlackboard,
)
from wattleflow.concrete.exception import BlackboardException
from wattleflow.concrete.state_machine import StateMachine
from wattleflow.enums.event import Event
from wattleflow.helpers.digest import FileDigest
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

Documents = Dict[str, ITarget]

# --------------------------------------------------------------------------- #
# region Blackboard                                                           #
# --------------------------------------------------------------------------- #


class BundleBlackboard(GenericBlackboard[Documents]):
    __slots__ = ("_fsm", "_by_identifier", "_bundle", "_aliases")
    ALLOWED = ["configuration", "defer_flush", "strategy_create"]

    # region Private

    def __init__(self, **kwargs):
        super().__init__(canvas={}, **kwargs)
        self._fsm: StateMachine = StateMachine(
            TRANSITIONS,
            BlackboardState.IDLE,
            name="BundleFSM",
        )
        self._by_identifier: Dict[str, str] = {}
        self._bundle: Dict[str, List[str]] = {}
        self._aliases: Dict[str, str] = {}
        self.debug(msg=Event.Constructor, step=Event.Completed)

    @staticmethod
    def _digest_of(document: Any) -> str:
        """Content digest of a document: prefer a pre-stamped `content_digest`."""
        stamped = (
            document.metadata.get("content_digest")
            or document.metadata.get("file_digest")
            or document.metadata.get("digest")
        )
        if stamped:
            return str(stamped)
        try:
            content = document.content
        except Exception:
            content = None
        if content is None:
            return f"empty:{document.identifier}"
        if isinstance(content, (bytes, bytearray, memoryview)):
            data = bytes(content)
        else:
            data = str(content).encode("utf-8")
        return FileDigest.labelled(data)

    def _register_bundle(self, document: Any, digest: str) -> None:
        """Record the email→attachment relationship. A child carries a
        `parent_digest`; a parent flagged `has_attachments` gets an entry so the
        manifest lists it even before its children arrive."""
        parent = document.metadata.get("parent_digest")
        if parent:
            children = self._bundle.setdefault(str(parent), [])
            if digest not in children:
                children.append(digest)
        elif document.metadata.get("has_attachments"):
            self._bundle.setdefault(digest, [])

    def _resolve_key(self, identifier: str) -> Optional[str]:
        """Map a lookup key (content digest OR document uuid OR deduped alias)
        to the canvas key (content digest)."""
        if identifier in self._canvas:
            return identifier
        digest = self._by_identifier.get(identifier) or self._aliases.get(identifier)
        if digest and digest in self._canvas:
            return digest
        return None

    def __broadcast__(self, facade: ITarget, **kwargs) -> None:
        self.debug(
            msg=Event.Emit,
            step=Event.Started,
            facade=facade,
            state=self._fsm.state.name,
            kwargs=kwargs,
        )
        try:
            for repository in self._repositories:
                repository.write(caller=self, facade=facade, **kwargs)
        except Exception as e:
            if self._fsm.can(BlackboardAction.FAIL):
                self._fsm.apply(BlackboardAction.FAIL)
            self.debug(msg=Event.Emit, step=Event.Failed, error=str(e))
            raise

        if self._fsm.can(BlackboardAction.FLUSH):
            self._fsm.apply(BlackboardAction.FLUSH)

        self.debug(msg=Event.Emit, step=Event.Completed, broadcasted=True)

    def __repr__(self) -> str:
        state = self._fsm.state.name or "UNKNOWN"
        return "%s:%s" % (super().__repr__(), state)

    # endregion Private

    # region Property

    @property
    def count(self) -> int:
        return len(self._canvas) if self._canvas else 0

    @property
    def bundle(self) -> Mapping[str, List[str]]:
        return MappingProxyType(self._bundle)

    @property
    def aliases(self) -> Mapping[str, str]:
        return MappingProxyType(self._aliases)

    # endregion Property

    # region Public

    def clean(self):
        self.debug(msg=Event.Clean, step=Event.Started, state=self._fsm.state.name)
        try:
            if self._canvas and self._fsm.can(BlackboardAction.FLUSH):
                self.warning(
                    msg=Event.Clean,
                    reason="canvas has unflushed facades at lifecycle end",
                    cause="defer_flush=%s" % self.defer_flush,
                    count=len(self._canvas),
                    state=self._fsm.state.name,
                )
                self.flush(caller=self)

            self._repositories.clear()
            self._by_identifier.clear()
            self._bundle.clear()
            self._aliases.clear()

            if self._fsm.can(BlackboardAction.CLEAN):
                self._fsm.apply(BlackboardAction.CLEAN)
        except Exception as e:
            self.debug(msg=Event.Clean, step=Event.Failed, error=str(e))
            if self._fsm.can(BlackboardAction.FAIL):
                self._fsm.apply(BlackboardAction.FAIL)
            raise

        self.debug(
            msg=Event.Clean,
            step=Event.Completed,
            state=self._fsm.state.name,
            repositories=len(self._repositories),
        )

    def create(self, caller: IProcessor, **kwargs) -> Optional[ITarget]:
        self.debug(msg=Event.Create, step=Event.Started, caller=caller.name)
        assert isinstance(caller, IProcessor), "Expected IProcessor. Found %s" % type(caller)

        if not self._strategy_create:
            self.warning(
                msg=Event.Create,
                error=f"{self.name}._strategy_create is missing!",
            )
            return None

        self.debug(msg=Event.Create, step=Event.Completed)
        return self._strategy_create.create(
            caller=self, processor=caller, blackboard=self, **kwargs
        )

    def delete(self, identifier: str, **kwargs) -> None:
        self.debug(msg=Event.Delete, step=Event.Started, id=identifier)
        key = self._resolve_key(identifier)
        if key is not None:
            del self._canvas[key]
            self._by_identifier = {i: d for i, d in self._by_identifier.items() if d != key}
            self._bundle.pop(key, None)
            self.debug(msg=Event.Deleted, identifier=identifier)
        else:
            self.warning(
                msg=Event.Delete,
                reason="The blackboard neither confirms nor denies the existence!",
                identifier=identifier,
            )
        self.debug(msg=Event.Delete, step=Event.Completed, id=identifier)

    def flush(self, caller: IWattleflow, **kwargs) -> None:
        # The flush is the blackboard's unit of work — one record per cycle, never per document (NFRQ-OBS-03).
        pending = self.count
        (self.info if pending else self.debug)(
            msg=Event.Flush,
            step=Event.Started,
            documents=pending,
        )
        self.debug(msg=Event.Flush, step=Event.Started, caller=caller, kwargs=kwargs)

        assert isinstance(caller, (IProcessor, IBlackboard)), (
            "Expected IProcessor or IBlackboard. Found %s" % type(caller)
        )

        # DIRTY carries unflushed facades — broadcast the deduplicated set.
        if self._fsm.state == BlackboardState.DIRTY:
            for facade in list(self._canvas.values()):
                self.__broadcast__(facade=facade, **kwargs)

        self._canvas.clear()
        self._by_identifier.clear()
        # _bundle / _aliases are the run-level evidence record — kept until clean().

        if self._fsm.can(BlackboardAction.FLUSH):
            self._fsm.apply(BlackboardAction.FLUSH)

        self.debug(msg=Event.Flush, step=Event.Completed)

    def read(self, identifier: str, **kwargs) -> ITarget:
        self.debug(msg=Event.Read, step=Event.Started, identifier=identifier)
        key = self._resolve_key(identifier)
        if key is None:
            raise BlackboardException(self, f"Document {identifier} not found!")
        facade: ITarget = self._canvas[key]
        if self._fsm.can(BlackboardAction.READ):
            self._fsm.apply(BlackboardAction.READ)
        self.debug(msg=Event.Read, step=Event.Completed, identifier=identifier)
        return facade

    def register(self, repository: IRepository) -> None:
        self.debug(msg=Event.Register, step=Event.Started)
        assert isinstance(repository, IRepository), "Expected IRepository. Found %s" % type(
            repository
        )

        if repository in self._repositories:
            self.warning(
                msg=Event.Register,
                repository=repository,
                error="Repository already registered!",
            )
            return

        self._repositories.append(repository)
        if self._fsm.can(BlackboardAction.REGISTER):
            self._fsm.apply(BlackboardAction.REGISTER)
        self.debug(msg=Event.Register, step=Event.Completed, added=repository)

    def write(self, pipeline: IPipeline, facade: ITarget, **kwargs) -> str:
        self.debug(msg=Event.Write, step=Event.Started, facade=facade, kwargs=kwargs)

        assert isinstance(pipeline, IPipeline), "Expected IPipeline. Found %s" % type(pipeline)
        assert isinstance(facade, ITarget), "Expected ITarget. Found %s" % type(facade)

        document = facade.request()
        digest = self._digest_of(document)

        if self._fsm.can(BlackboardAction.WRITE):
            self._fsm.apply(BlackboardAction.WRITE)

            # A previously stored facade re-written with mutated content changes
            # its digest — drop the stale key so the canvas holds one entry per
            # facade (only if that slot still holds THIS facade, never a dedup
            # canonical belonging to another document).
            prev = self._by_identifier.get(facade.identifier)
            if prev is not None and prev != digest and self._canvas.get(prev) is facade:
                del self._canvas[prev]

            existing = self._canvas.get(digest)
            if existing is not None and existing is not facade:
                # DEDUP — identical content already on the canvas from a different
                # document. Record the reference; do NOT store or persist a copy.
                self._aliases[facade.identifier] = digest
                self._by_identifier[facade.identifier] = digest
                self._register_bundle(document, digest)
                self.debug(
                    msg=Event.Write,
                    action=Event.Stored.value,
                    deduplicated=True,
                    digest=digest,
                    canonical=existing.identifier,
                )
                return existing.identifier

            self._canvas[digest] = facade
            self._by_identifier[facade.identifier] = digest
            self._register_bundle(document, digest)
            self.debug(
                msg=Event.Write,
                action=Event.Stored,
                identifier=facade.identifier,
                digest=digest,
            )

        if not self._repositories:
            self.warning(msg=Event.Write, error="No repositories have been registered.")
            return ""

        if not self.defer_flush:
            self.__broadcast__(facade=facade, **kwargs)

        self.debug(msg=Event.Write, step=Event.Completed)
        return facade.identifier

    # endregion Public


# --------------------------------------------------------------------------- #
# endregion Blackboard                                                        #
# --------------------------------------------------------------------------- #

__all__ = ["BundleBlackboard"]
