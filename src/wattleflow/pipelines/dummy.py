# Module name: pipelines/dummy.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from typing import Any
from wattleflow.core import IProcessor, ITarget
from wattleflow.concrete import GenericPipeline
from wattleflow.enums.event import Event
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Pipelines                                                            #
# --------------------------------------------------------------------------- #


class PipelineDummyWrite(GenericPipeline):
    """Publish the facade unchanged — the no-op step of a wiring smoke test.

    Grammar (NFRQ-ORG-02 §1): Subject `Dummy` + Operation `Write`. There is no
    transformation to name, and `Write` is what the class actually performs:
    the blackboard write is its whole body.
    """

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> str:
        self.debug(msg=Event.Transform.name, step=Event.Started.name)
        uid = processor.blackboard.write(pipeline=self, processor=processor, facade=facade)
        self.debug(msg=Event.Transform.name, step=Event.Completed.name, uid=uid)
        return uid


# --------------------------------------------------------------------------- #
# endregion Pipelines                                                         #
# --------------------------------------------------------------------------- #


__all__ = ["PipelineDummyWrite"]
