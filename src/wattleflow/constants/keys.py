# Module name: constants/keys.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #

# All keys, must be in a small caps.
KEY_AUDIT_MANAGER = "audit_manager"
KEY_NAME = "name"

KEY_BLACKBOARD = "blackboard"
KEY_CLASSIFICATION = "classification"
KEY_CLASSIFICATION_DLM = "classification_dlm"
KEY_CLASS_NAME = "class_name"
KEY_CONFIGURATION = "configuration"
KEY_CONTENT = "content"
KEY_DATA_CONTENT = "data_content"
KEY_DATA_FRAME = "data_frame"
KEY_DLM = "dlm"
KEY_DOCUMENT = "document"
KEY_DOCUMENTATION = "documentation"

KEY_FILE_LIST = "file_list"
KEY_LABEL_NAMES = "labelnames"
KEY_LICENCE = "licence"
KEY_NAMESPACE = "name_space"
KEY_METADATA = "metadata"
KEY_PIPELINE_NAME = "pipeline_name"
KEY_PIPELINE_TYPE = "pipeline_type"
KEY_PRIVATE_KEY = "private_key"
KEY_PROCESSING_TYPE = "processing_type"
KEY_PUBLISHER = "publisher"
KEY_REPOSITORY_PATH = "repository_path"
KEY_SERVER = "server"
KEY_HEADERS = "headers"

KEY_SSH_KEY_FILENAME = "key_filename"
KEY_SUBSYSTEM = "subsystem"
KEY_TEMP_PATH = "temp_path"
KEY_UNIT = "unit"
KEY_URI = "uri"

KEY_STATUS = "status"

# Strategies
KEY_STRATEGY = "strategy"
KEY_STRATEGY_AUDIT = "strategy_audit"
KEY_STRATEGY_CREATE = "strategy_create"
KEY_STRATEGY_DOCUMENT = "strategy_document"
KEY_STRATEGY_KEY = "strategy_key"
KEY_STRATEGY_READ = "strategy_read"
KEY_STRATEGY_WRITE = "strategy_write"

# Config environments
CONFIG_FILE = "config.yaml"
UTF8 = "utf-8"
KEY_REPOSITORY_PATH = "repository_path"
KEY_SECTION_DEV = "dev"
KEY_SECTION_PROD = "prod"
KEY_SECTION_PROJECT = "project"
KEY_SECTION_TEST = "test"
KEY_PATH = "path"
KEY_PKEY = "pkey"
KEY_SALT = "salt"


# Server
KEY_SERVER_URL = "server_url"

# Sftp
KEY_PIPELINES = "pipelines"
KEY_REMOTE_PATH = "remote_path"
KEY_REMOTE_PATTERN = "pattern"
KEY_PASSPHRASE = "passphrase"
KEY_LOOK_FOR_KEYS = "look_for_keys"
KEY_ALLOW_AGENT = "allow_agent"
KEY_COMPRESS = "compress"
# Database
KEY_DATABASE = "database"
KEY_HOST = "host"
KEY_PORT = "port"
KEY_USER = "user"
KEY_PASSWORD = "password"
KEY_QUERY_TIMESTAMP = "query_timestamp"
KEY_QUERY_DURATION = "query_duration"
KEY_PRIVILEGES = "privileges"
KEY_RECORD_COUNT = "record_count"
KEY_SCHEMA = "schema"
KEY_SQL = "sql"
KEY_ENGINE = "engine"
KEY_DRIVER = "driver"
KEY_URL = "url"
KEY_VERSION = "version"

# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

__all__ = [
    "CONFIG_FILE",
    "KEY_ALLOW_AGENT",
    "KEY_AUDIT_MANAGER",
    "KEY_BLACKBOARD",
    "KEY_CLASSIFICATION",
    "KEY_CLASSIFICATION_DLM",
    "KEY_CLASS_NAME",
    "KEY_COMPRESS",
    "KEY_CONFIGURATION",
    "KEY_CONTENT",
    "KEY_DATABASE",
    "KEY_DATA_CONTENT",
    "KEY_DATA_FRAME",
    "KEY_DLM",
    "KEY_DOCUMENT",
    "KEY_DOCUMENTATION",
    "KEY_DRIVER",
    "KEY_ENGINE",
    "KEY_FILE_LIST",
    "KEY_HEADERS",
    "KEY_HOST",
    "KEY_LABEL_NAMES",
    "KEY_LICENCE",
    "KEY_LOOK_FOR_KEYS",
    "KEY_METADATA",
    "KEY_NAME",
    "KEY_NAMESPACE",
    "KEY_PASSPHRASE",
    "KEY_PASSWORD",
    "KEY_PATH",
    "KEY_PIPELINES",
    "KEY_PIPELINE_NAME",
    "KEY_PIPELINE_TYPE",
    "KEY_PKEY",
    "KEY_PORT",
    "KEY_PRIVATE_KEY",
    "KEY_PRIVILEGES",
    "KEY_PROCESSING_TYPE",
    "KEY_PUBLISHER",
    "KEY_QUERY_DURATION",
    "KEY_QUERY_TIMESTAMP",
    "KEY_RECORD_COUNT",
    "KEY_REMOTE_PATH",
    "KEY_REMOTE_PATTERN",
    "KEY_REPOSITORY_PATH",
    "KEY_SALT",
    "KEY_SCHEMA",
    "KEY_SECTION_DEV",
    "KEY_SECTION_PROD",
    "KEY_SECTION_PROJECT",
    "KEY_SECTION_TEST",
    "KEY_SERVER",
    "KEY_SERVER_URL",
    "KEY_SQL",
    "KEY_SSH_KEY_FILENAME",
    "KEY_STATUS",
    "KEY_STRATEGY",
    "KEY_STRATEGY_AUDIT",
    "KEY_STRATEGY_CREATE",
    "KEY_STRATEGY_DOCUMENT",
    "KEY_STRATEGY_KEY",
    "KEY_STRATEGY_READ",
    "KEY_STRATEGY_WRITE",
    "KEY_SUBSYSTEM",
    "KEY_TEMP_PATH",
    "KEY_UNIT",
    "KEY_URI",
    "KEY_URL",
    "KEY_USER",
    "KEY_VERSION",
    "UTF8",
]
