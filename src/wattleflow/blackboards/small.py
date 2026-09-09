# Module name: blackboards/small.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from typing import Optional
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
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Blackboard                                                           #
# --------------------------------------------------------------------------- #


class SmallBlackboard(GenericBlackboard[ITarget]):
    __slots__ = ("_fsm",)
    ALLOWED = ["configuration", "defer_flush", "strategy_create"]

    # region Private

    def __init__(self, **kwargs):
        super().__init__(canvas=None, **kwargs)
        self._fsm: StateMachine = StateMachine(
            TRANSITIONS,
            BlackboardState.IDLE,
            name="SmallBlackboard",
        )
        self.debug(msg=Event.Constructor.name, step=Event.Completed.name)

    def __repr__(self) -> str:
        state = self._fsm.state.name or "UNKNOWN"
        return "%s:%s" % (super().__repr__(), state)

    # endregion Private

    # region Property

    @property
    def count(self) -> int:
        return 1 if self._canvas else 0

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
            if self._canvas is not None and self._fsm.can(BlackboardAction.FLUSH):
                self.warning(
                    msg=Event.Clean.name,
                    reason="canvas has unflushed facade at lifecycle end",
                    cause="defer_flush=%s" % self.defer_flush,
                    state=self._fsm.state.name,
                )
                self.flush(caller=self)

            if isinstance(self._canvas, ITarget):
                self._canvas.clean()

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
        self.debug(msg=Event.Create.name, step=Event.Started.name, kwargs=kwargs)
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
        self.debug(msg=Event.Delete.name, step=Event.Started.name, id=identifier)
        if isinstance(self._canvas, ITarget):
            self.clean()
        self.debug(msg=Event.Delete.name, step=Event.Completed.name)

    def flush(self, caller: IWattleflow, **kwargs) -> None:
        pending = self.count
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

        facade = self._canvas
        if facade is not None and self._fsm.can(BlackboardAction.FLUSH):
            self.debug(
                msg=Event.Flush.name,
                step=Event.Started.name,
                documents=pending,
                repositories=len(self._repositories),
            )
            try:
                for repository in self._repositories:
                    repository.write(caller=self, facade=facade, **kwargs)
            except Exception as e:
                if self._fsm.can(BlackboardAction.FAIL):
                    self._fsm.apply(BlackboardAction.FAIL)

                self.debug(
                    msg=Event.Flush.name,
                    step=Event.Failed.name,
                    error=f"Writing repository: {str(e)}",
                )
                raise BlackboardException(
                    self,
                    error="repository.write",
                    exc=e,
                ) from e

            if self._fsm.can(BlackboardAction.FLUSH):
                self._fsm.apply(BlackboardAction.FLUSH)

            self._canvas = None

        self.debug(msg=Event.Flush.name, step=Event.Completed.name)

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

        if self._fsm.can(BlackboardAction.REGISTER):
            self._fsm.apply(BlackboardAction.REGISTER)

        self.debug(
            msg=Event.Register.name,
            step=Event.Completed.name,
            state=self._fsm.state.name,
            added=repository,
        )

    def read(self, identifier: str, **kwargs) -> ITarget:
        self.debug(msg=Event.Read.name, step=Event.Started.name, kwargs=kwargs)

        if self._canvas is None:
            raise BlackboardException(self, f"Document {identifier} not found!")

        # BlackboardAction.READ rezerviran — trenutno nema definiranu tranziciju
        # u TRANSITIONS pa _fsm.can() vraća False; ostavljeno za buduće FSM
        # proširenje (npr. READY -> READ -> READY).
        if self._fsm.can(BlackboardAction.READ):
            self._fsm.apply(BlackboardAction.READ)

        self.debug(msg=Event.Read.name, step=Event.Completed.name, identifier=identifier)
        return self._canvas

    def write(self, pipeline: IPipeline, facade: ITarget, **kwargs) -> str:
        self.debug(
            msg=Event.Write.name,
            step=Event.Started.name,
            pipeline=pipeline,
            kwargs=kwargs,
        )

        assert isinstance(pipeline, IPipeline), "Expected IPipeline. Found %s" % type(pipeline)
        assert isinstance(facade, ITarget), "Expected ITarget. Found %s" % type(facade)

        if not self._repositories:
            error = "No repositories have been registered."
            self.exception(
                msg=Event.Write.name,
                error=error,
            )
            raise BlackboardException(self, error=error)

        self._canvas = facade

        if self._fsm.can(BlackboardAction.WRITE):
            self._fsm.apply(BlackboardAction.WRITE)

        # Reported on ENTRY, before the facade is handed down, so the audit stream
        # follows the call order the activity diagram draws. Closing the unit is
        # the processor's and the workflow's job, not this layer's.
        self.debug(
            msg=Event.Write.name,
            step=Event.Started.name,
            document=facade.identifier,
            repositories=len(self._repositories),
            deferred=bool(self.defer_flush),
        )

        # Eager broadcast (defer_flush=False) — pisanje pri svakoj izmjeni,
        # korisno za audit/debug. Normalan rad (defer_flush=True) ostavlja
        # facade u canvasu sve do flush().
        if not self.defer_flush:
            for repository in self._repositories:
                repository.write(caller=self, facade=facade, **kwargs)
            if self._fsm.can(BlackboardAction.FLUSH):
                self._fsm.apply(BlackboardAction.FLUSH)
            self._canvas = None

        self.debug(
            msg=Event.Write.name,
            action=Event.Stored.value,
            facade=facade,
        )

        return facade.identifier

    # endregion Public


# --------------------------------------------------------------------------- #
# endregion Blackboard                                                        #
# --------------------------------------------------------------------------- #


__all__ = ["SmallBlackboard"]
