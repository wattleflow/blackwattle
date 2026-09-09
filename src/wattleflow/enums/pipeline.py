# Module name: enums/pipeline.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from enum import Enum
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #


# Action
class PipelineAction(Enum):
    CONNECT = "5bb4dc6f-47d4-c040-9844-a72464984b14"
    DISCONNECT = "6ab06dcf-aa51-790d-d7c9-6d52d3be8ae0"
    EXTRACT = "40803834-9041-9ffc-e52d-9a66c5fac20b"
    TRANSFORM = "00c9bf50-c91c-2d07-e985-1cd554537678"
    LOAD = "d438686e-54df-812d-53df-373e2ca6a962"
    SCHEDULE = "5a40b6fd-b0ca-155a-3050-4aa62f93a7c5"
    RELEASE_DATE = "20241030"
    VERSION = "0.0.0.1"


# Supported pipeline types
class PipelineType(Enum):
    ASYNC_PIPELINE = "ASYNC_PIPELINE"  # "2a6737f3-93f5-950b-832c-cfd78829c69c"
    BASE_PIPELINE = "BASE_PIPELINE"  # "1916fa2b-7d51-c4f2-e28e-61e8fc4c386d"
    CONFIGURATION_PIPELINE = "CONFIGURATION_PIPELINE"
    CONNECTION_PIPELINE = "CONNECTION_PIPELINE"  # "c3535bf0-a399-8fce-a609-92c0b072fe52"
    EXTRACTION_PIPELINE = "EXTRACTION_PIPELINE"  # "df1999d3-28f7-a17d-764e-8d0eb9c01dca"
    LOAD_PIPELINE = "LOAD_PIPELINE"  # "85593db0-62ba-e953-b9da-aa1860025880"
    STRATEGY_PIPELINE = "STRATEGY_PIPELINE"
    TRANSFORMATION_PIPELINE = "TRANSFORMATION_PIPELINE"  # "fa7a9304-7b92-bf00-2374-a899ee239dfe"
    RELEASE_DATE = "20241030"
    VERSION = "0.0.0.1"


class ProvenanceHandler(Enum):
    Processor = "Processor"
    Pipeline = "Pipeline"
    CreateStrategy = "Create Strategy"
    WriteStrategy = "Write Strategy"

# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #
