# Module name: enums/audit.py
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


# Connection status
class ConnectionStatus(Enum):
    CONNECTING = "a0e1a519-f04a-9b3e-9837-233d253b10ae"
    CONNECTED = "1f914c43-86c0-676e-e418-458a20c91d9d"
    DISCONNECTING = "ad7b66a9-13a4-6286-8e32-d16cae6ab3bd"
    DISCONNECTED = "5541de95-1552-2b98-1f16-c3078357b06e"
    RELEASE_DATE = "20241030"
    VERSION = "0.0.0.1"


# Event logging and monitoring
class EventLog(Enum):
    AUDIT_EVENT = "91a8c41c-bf8c-f0ac-5516-85124f1df375"
    DEBUG_EVENT = "b68c763b-9c01-b2bf-0b75-26ea6fcf5a55"
    LOG_EVENT = "7c77d0ef-187a-0e7c-f162-6d53d110c4d1"
    PERFORMANCE_EVENT = "5fd83ab9-8e05-ff05-0907-eeb3974dc78d"
    UNKNOWN = "unknown"
    RELEASE_DATE = "20241030"
    VERSION = "0.0.0.1"


# Protective markings and classification levels
class ProtectiveMarkings(Enum):
    BASELINE = "678bf03b-47ad-9601-2e4b-7cf24f90a91a"
    PROTECTED = "a2da5a89-14a4-3f9d-2ff7-883c5125f70c"
    SECRET = "0917b13a-9091-915d-54b6-336f45909539"
    TOP_SECRET = "0ceda85f-1d80-0bf2-470c-5042e790b1f4"
    POSITVE_VETING = "5d3dad84-c40d-d25d-f1ea-57e30b7e0a52"
    RELEASE_DATE = "20241030"
    VERSION = "0.0.0.1"


# Wattleflow OSCAL identifiers for audit and compliance
class WattleflowOSCAL(Enum):
    VERSION = "0.0.0.1"
    RELEASE_DATE = "2024/10/10"
    POLICY_VERSION = "0.0.0.1"
    GUIDELINES_FOR_DATABASE_SYSTEMS = "3f349d16-11a1-459a-a299-c9446aea7597"
    GUIDELINES_FOR_SOFTWARE_DEVELOPMENT = "506198a8-7ae8-4c95-8b7b-2a4833cfab4b"
    BEST_PRACTICES_FOR_EVENT_LOGGING_AND_THREAT_DETECTION = "b95c4745-572a-4121-b4e1-d0baa90a84fc"
    WINDOWS_EVENT_LOGGING_AND_FORWARDING = "de239dae-d1e8-4969-9680-ef3444d32a83"

# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #
