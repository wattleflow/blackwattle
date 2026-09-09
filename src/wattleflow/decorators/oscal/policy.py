# Module name: decorators/oscal/policy.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from functools import wraps
from typing import Callable, ClassVar, Optional, Tuple
from wattleflow.concrete.state_machine import GuardedStateMachine, StateMachine
from wattleflow.enums.event import Event
from wattleflow.oscal.policy import OSCALPolicy, OSCALPolicyError
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #
__author__ = "WattleFlow"
__copyright__ = "© 2022–2026 WattleFlow. All rights reserved"

__all__ = ["oscal_policy", "OSCALGate"]
# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Gate                                                                 #
# --------------------------------------------------------------------------- #


# v0.0.0.97 (NFRQ-ORG-05): the attribute name, the control resolution, the audit
# emission and the guard factory are one class — the decorator only wires them.
class OSCALGate:
    """Mechanics behind `oscal_policy`: control resolution and FSM guarding."""

    CONTROLS_ATTR: ClassVar[str] = "OSCAL_CONTROLS"

    @classmethod
    def resolve_controls(cls, target: type, strategy: str) -> Tuple[str, ...]:
        """Collect declared OSCAL controls for a class.

        ``merge`` walks the MRO and unions every ``OSCAL_CONTROLS`` it sees;
        ``replace`` returns only the immediate class attribute.
        """
        if strategy == "replace":
            return tuple(getattr(target, cls.CONTROLS_ATTR, ()))
        merged: set[str] = set()
        for klass in target.__mro__:
            merged.update(getattr(klass, cls.CONTROLS_ATTR, ()))
        return tuple(sorted(merged))

    @staticmethod
    def emit(instance, event: Event, **extra) -> None:
        """Audit log if the instance carries an Audit mixin."""
        if hasattr(instance, "debug"):
            instance.debug(msg=event.value, step="oscal", **extra)

    @classmethod
    def verify_now(
        cls,
        instance,
        policy: Optional[OSCALPolicy],
        declared: Tuple[str, ...],
        strict: bool,
    ) -> None:
        """Verify before the component's __init__ runs.

        The FSM guard cannot cover the constructor itself: a base whose
        __init__ already performs work (GenericConnection calls
        ensure_created() unless lazy) would do that work before the guard is
        installed. This runs first, so a component that fails the baseline
        never gets that far. Audit is not emitted here — the instance has no
        logger yet; the guard emits it on the first transition.
        """
        if not declared:
            return
        component_name = getattr(instance, "name", type(instance).__name__)
        if policy is None:
            if strict:
                raise OSCALPolicyError(
                    f"{component_name}: oscal_policy kwarg is required "
                    f"for compliance-gated component "
                    f"(declares {sorted(declared)})"
                )
            return
        policy.verify(component_name, declared)

    @classmethod
    def guard_for(
        cls,
        instance,
        policy: Optional[OSCALPolicy],
        declared: Tuple[str, ...],
        kind: Optional[str],
        strict: bool,
    ) -> Callable[[StateMachine], None]:
        """Build a one-shot guard suitable for ``GuardedStateMachine``."""
        component_name = getattr(instance, "name", type(instance).__name__)

        def guard(_inner: StateMachine) -> None:
            if not declared:
                # Decorated component declares no controls: opt-out of gating.
                return
            if policy is None:
                if strict:
                    raise OSCALPolicyError(
                        f"{component_name}: oscal_policy kwarg is required "
                        f"for compliance-gated component "
                        f"(declares {sorted(declared)})"
                    )
                return
            cls.emit(
                instance,
                Event.Validating,
                profile=policy.profile_uuid,
                kind=kind,
                declared=declared,
            )
            policy.verify(component_name, declared)
            cls.emit(
                instance,
                Event.Validated,
                profile=policy.profile_uuid,
                kind=kind,
            )

        return guard


# --------------------------------------------------------------------------- #
# endregion Gate                                                              #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Decorator                                                            #
# --------------------------------------------------------------------------- #


def oscal_policy(
    *,
    kind: Optional[str] = None,
    strict: bool = True,
    controls_strategy: str = "merge",
):
    """Guard a component's FSM with OSCALPolicy.verify before its first transition.

    The decorated class must build `_fsm` in __init__. `kind` is an audit label,
    not a filter. `strict=False` turns the gate into a no-op.
    `controls_strategy="merge"` unions OSCAL_CONTROLS across the MRO.
    """

    def wrap(cls):
        original_init = cls.__init__

        @wraps(original_init)
        def __init__(self, *args, **kwargs):
            policy = kwargs.pop("oscal_policy", None)
            declared = OSCALGate.resolve_controls(type(self), controls_strategy)

            # Gate before construction: a base whose __init__ opens resources
            # would otherwise do so before the FSM guard exists.
            OSCALGate.verify_now(self, policy, declared, strict)

            original_init(self, *args, **kwargs)

            fsm = getattr(self, "_fsm", None)
            if fsm is None:
                # Component does not expose an FSM lifecycle: the constructor
                # check above is then the whole gate.
                return

            guard = OSCALGate.guard_for(self, policy, declared, kind, strict)
            self._fsm = GuardedStateMachine(fsm, guard)

        cls.__init__ = __init__
        cls.__oscal_meta__ = {
            "kind": kind,
            "strict": strict,
            "controls_strategy": controls_strategy,
        }
        return cls

    return wrap


# --------------------------------------------------------------------------- #
# endregion Decorator                                                         #
# --------------------------------------------------------------------------- #
