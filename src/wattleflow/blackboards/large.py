# Module name: blackboards/large.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from typing import Dict, Optional
from wattleflow.core import (
    IBlackboard,
    IOriginator,
    IPipeline,
    IRepository,
    IProcessor,
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
from wattleflow.concrete.memento import GenericMemento
from wattleflow.concrete.state_machine import StateMachine
from wattleflow.enums.event import Event
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

Documents = Dict[str, ITarget]

# --------------------------------------------------------------------------- #
# region Blackboards                                                          #
# --------------------------------------------------------------------------- #


class LargeBlackboard(GenericBlackboard[Documents], IOriginator):
    __slots__ = ("_fsm",)
    ALLOWED = ["configuration", "defer_flush", "strategy_create"]

    # region Private

    def __init__(self, **kwargs):
        super().__init__(canvas={}, **kwargs)
        self._fsm: StateMachine = StateMachine(
            TRANSITIONS,
            BlackboardState.IDLE,
            name="BlackboardFSM",
        )
        self.debug(msg=Event.Constructor.name, step=Event.Completed.name)

    def __broadcast__(
        self,
        facade: ITarget,
        **kwargs,
    ) -> None:
        # Blackboard prema repozitoriju proslijeđuje SEBE kao caller-a.
        # Upstream caller (Pipeline/Processor) ne smije propasti do strategije.
        self.debug(
            msg=Event.Emit.name,
            step=Event.Started.name,
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
            self.debug(msg=Event.Emit.name, step=Event.Failed.name, error=str(e))
            raise

        if self._fsm.can(BlackboardAction.FLUSH):
            self._fsm.apply(BlackboardAction.FLUSH)

        self.debug(
            msg=Event.Emit.name,
            step=Event.Completed.name,
            state=self._fsm.state.name,
            broadcasted=True,
        )

    def __repr__(self) -> str:
        state = self._fsm.state.name or "UNKNOWN"
        return "%s:%s" % (super().__repr__(), state)

    # endregion Private

    # region Property

    @property
    def count(self) -> int:
        if self._canvas:
            return len(self._canvas)
        return 0

    # endregion Properties

    # region Public

    def clean(self):
        self.debug(
            msg=Event.Clean.name,
            step=Event.Started.name,
            state=self._fsm.state.name,
        )

        try:
            # Safety-net: ako je canvas neprazan i nije nikad flushan
            # (DIRTY state), broadcastaj prije CLEAN-a. Log warning s razlogom.
            if self._canvas and self._fsm.can(BlackboardAction.FLUSH):
                self.warning(
                    msg=Event.Clean.name,
                    reason="canvas has unflushed facades at lifecycle end",
                    cause="defer_flush=%s" % self.defer_flush,
                    count=len(self._canvas),
                    state=self._fsm.state.name,
                )
                self.flush(caller=self)

            self._repositories.clear()

            if self._fsm.can(BlackboardAction.CLEAN):
                self._fsm.apply(BlackboardAction.CLEAN)
        except Exception as e:
            self.debug(
                msg=Event.Clean.name,
                step=Event.Failed.name,
                error=str(e),
            )
            if self._fsm.can(BlackboardAction.FAIL):
                self._fsm.apply(BlackboardAction.FAIL)
            raise

        self.debug(
            msg=Event.Clean.name,
            step=Event.Completed.name,
            state=self._fsm.state.name,
            repositories=len(self._repositories),
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

        self.debug(msg=Event.Create.name, step=Event.Completed.name)

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
            self.debug(msg=Event.Deleted.name, identifier=identifier)
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
            caller=caller,
            kwargs=kwargs,
        )

        # flush smije pozvati samo Processor (kraj ciklusa) ili Blackboard
        # (samog sebe, iz clean() safety-neta).
        assert isinstance(caller, (IProcessor, IBlackboard)), (
            "Expected IProcessor or IBlackboard. Found %s" % type(caller)
        )

        # DIRTY state nosi unflushed facade — broadcast pa očisti canvas.
        if self._fsm.state == BlackboardState.DIRTY:
            for facade in list(self._canvas.values()):
                self.__broadcast__(facade=facade, **kwargs)

        self._canvas.clear()

        if self._fsm.can(BlackboardAction.FLUSH):
            self._fsm.apply(BlackboardAction.FLUSH)

        self.debug(msg=Event.Flush.name, step=Event.Completed.name)

    def read(self, identifier: str, **kwargs) -> ITarget:
        self.debug(
            msg=Event.Read.name,
            step=Event.Started.name,
            state=self._fsm.state.name,
            identifier=identifier,
            kwargs=kwargs,
        )

        if identifier not in self._canvas:
            raise BlackboardException(self, f"Document {identifier} not found!")

        facade: ITarget = self._canvas[identifier]

        # READ rezerviran (vidi BlackboardAction.READ) — _fsm.can() trenutno False.
        if self._fsm.can(BlackboardAction.READ):
            self._fsm.apply(BlackboardAction.READ)

        self.debug(
            msg=Event.Read.name,
            step=Event.Completed.name,
            state=self._fsm.state.name,
            identifier=identifier,
        )
        return facade

    def register(self, repository: IRepository) -> None:
        self.debug(msg=Event.Register.name, step=Event.Started.name)

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

        if self._fsm.can(BlackboardAction.REGISTER):
            self._fsm.apply(BlackboardAction.REGISTER)

        self.debug(
            msg=Event.Register.name,
            step=Event.Completed.name,
            added=repository,
        )

    def write(self, pipeline: IPipeline, facade: ITarget, **kwargs) -> str:
        self.debug(
            msg=Event.Write.name,
            step=Event.Started.name,
            facade=facade,
            kwargs=kwargs,
        )
        assert isinstance(pipeline, IPipeline), "Expected IPipeline. Found %s" % type(pipeline)
        assert isinstance(facade, ITarget), "Expected ITarget. Found %s" % type(facade)

        if not getattr(facade, "identifier", None):
            raise BlackboardException(self, f"Document:{facade} is missing identifier!")

        if self._fsm.can(BlackboardAction.WRITE):
            self._fsm.apply(BlackboardAction.WRITE)
            self._canvas[facade.identifier] = facade
            self.debug(
                msg=Event.Write.name,
                action=Event.Stored.name,
                identifier=facade.identifier,
            )

        if not self._repositories:
            self.warning(
                msg=Event.Write.name,
                error="No repositories have been registered.",
            )
            return ""

        # Eager broadcast (defer_flush=False) — pisanje pri svakoj izmjeni
        # (audit/debug). Normalan rad (defer_flush=True) ostavlja facade u
        # canvasu sve do flush().
        if not self.defer_flush:
            self.__broadcast__(facade=facade, **kwargs)

        self.debug(msg=Event.Write.name, step=Event.Completed.name)
        return facade.identifier

    # endregion Public

    # region Memento

    def save_state(self) -> GenericMemento:
        self.debug(msg=Event.Save.name, state=self._fsm.state.name, count=len(self._canvas))
        return GenericMemento(canvas=dict(self._canvas), state=self._fsm.state)

    def restore_state(self, memento: GenericMemento) -> None:
        self.debug(msg=Event.Restore.name, state=self._fsm.state.name, memento=memento)

        if not isinstance(memento, GenericMemento):
            raise BlackboardException(self, "Invalid memento")

        saved_state = memento.get_state()

        # LOAD recovery valid only from IDLE / STORED / FAILED.
        if (saved_state, BlackboardAction.LOAD) not in TRANSITIONS:
            raise BlackboardException(
                self,
                f"Cannot restore: LOAD not allowed from saved state {saved_state.name}",
            )

        self._fsm.state = saved_state
        self._fsm.apply(BlackboardAction.LOAD)
        self._canvas = dict(memento.canvas)

        self.debug(msg=Event.Restore.name, state=self._fsm.state.name, count=len(self._canvas))

    # endregion Memento


# --------------------------------------------------------------------------- #
# endregion Blackboards                                                       #
# --------------------------------------------------------------------------- #

__all__ = ["LargeBlackboard"]
