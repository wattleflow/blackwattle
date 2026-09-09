# Module name: helpers/random_data.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""Random sample-data generators backed by numpy.

Example: generate random values
    from wattleflow.helpers.random_data import records

    data = records(5)
    print(data)

    Result:
    ndarray of 5 random floats between 0 and 1
"""

# NOTE: numpy fixes this module's home distribution (DR-WFL-002 §2.1) — a lazy
# reference still counts. The stdlib-only generators (`inc`, `text_generator`)
# stay in the clean core at `wattleflow.helpers.generators`.

__all__ = ["records"]


# --------------------------------------------------------------------------- #
# region Global methods                                                       #
# --------------------------------------------------------------------------- #


def records(n):
    # numpy is a heavy optional dependency — import lazily so importing
    # this module never pays the cost unless `records` is actually called.
    import numpy as np

    return np.random.rand(n)


# --------------------------------------------------------------------------- #
# endregion Global methods                                                   #
# --------------------------------------------------------------------------- #
