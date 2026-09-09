# Module name: strategies/helpers/loader.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import os
from importlib import import_module
from wattleflow.concrete import Wattleflow
from wattleflow.core import IStrategy
# --------------------------------------------------------------------------- #
# endregion imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Strategies                                                           #
# --------------------------------------------------------------------------- #


class StrategyClassLoader(Wattleflow, IStrategy):
    def execute(self, class_path, root_path):
        class_path, class_name = class_path.rsplit(".", 1)
        module_path = class_path.replace(".", os.path.sep)
        module_path = os.path.join(root_path, "{}.py".format(module_path))

        if not os.path.exists(module_path):
            raise ModuleNotFoundError(module_path)

        module = import_module(class_path)

        if class_name in module.__dict__:
            return getattr(module, class_name)

        raise ModuleNotFoundError(class_path)


# --------------------------------------------------------------------------- #
# endregion Strategies                                                        #
# --------------------------------------------------------------------------- #


__all__ = ["StrategyClassLoader"]
