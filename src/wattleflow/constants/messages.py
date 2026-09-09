# Module name: constants/messages.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #
# Authentication
ERROR_AUTHENTICATION = "Authentication failed: %s"

# Classification
ERROR_CLASSIFICATION = "Classification processing error: %s"

# Files, paths
ERROR_PATH_NOT_FOUND = "File or directory not found: %s"
ERROR_READING_FILE = "Failed to read file: %s"
ERROR_READING_URI = "Failed to read URI: %s"
ERROR_WRITING_FILE = "Failed to write file: %s"

# Classes, types, and object handling
ERROR_CREATION_FAILED = "Unable to create %s: %s"
ERROR_HANDLING_FILE = "File handling error: %s"
ERROR_CLASS_EXCEPTION_CAUGHT = "Exception caught in class %s: %s — %s"
ERROR_INCORRECT_TYPE = "Invalid type detected: %s"
ERROR_KWARGS_ERROR = "Keyword argument error for key '%s': %s"

# Keys, attributes, and values
ERROR_MISSING_ATTRIBUTE = "Missing attribute: [%s]"
ERROR_MANDATORY_ATTRIBUTE = "Mandatory attribute not provided: [%s]"
ERROR_NOT_FOUND = "%s not found in %s"
ERROR_NOT_IMPLEMENTED = "Not implemented: %s"
ERROR_RESTRICTED_NAME = "Restricted or reserved name: %s"

# Server Connections
ERROR_SERVER_CONNECTION = "Server connection failed: %s"
ERROR_SERVER_RESPONSE = "Error processing server response: %s"
ERROR_NOT_INITIALISED = "Connection not initialised or invalid"

# Strategies
ERROR_STRATEGY = "Strategy execution error: %s"
ERROR_MISSING_STRATEGY_CREATE = "Create strategy not configured: %s"
ERROR_MISSING_STRATEGY_READ = "Read strategy not configured: %s"
ERROR_MISSING_STRATEGY_WRITE = "Write strategy not configured: %s"

# Iteration
ERROR_ITERATION = "Iteration error at line [%s]: %s"

# Processing
ERROR_PROCESSING = "Processing failure: %s"
ERROR_PROCESSING_TASK = "Task processing error: %s"

# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

__all__ = [
    "ERROR_AUTHENTICATION",
    "ERROR_CLASSIFICATION",
    "ERROR_CLASS_EXCEPTION_CAUGHT",
    "ERROR_CREATION_FAILED",
    "ERROR_HANDLING_FILE",
    "ERROR_INCORRECT_TYPE",
    "ERROR_ITERATION",
    "ERROR_KWARGS_ERROR",
    "ERROR_MANDATORY_ATTRIBUTE",
    "ERROR_MISSING_ATTRIBUTE",
    "ERROR_MISSING_STRATEGY_CREATE",
    "ERROR_MISSING_STRATEGY_READ",
    "ERROR_MISSING_STRATEGY_WRITE",
    "ERROR_NOT_FOUND",
    "ERROR_NOT_IMPLEMENTED",
    "ERROR_NOT_INITIALISED",
    "ERROR_PATH_NOT_FOUND",
    "ERROR_PROCESSING",
    "ERROR_PROCESSING_TASK",
    "ERROR_READING_FILE",
    "ERROR_READING_URI",
    "ERROR_RESTRICTED_NAME",
    "ERROR_SERVER_CONNECTION",
    "ERROR_SERVER_RESPONSE",
    "ERROR_STRATEGY",
    "ERROR_WRITING_FILE",
]
