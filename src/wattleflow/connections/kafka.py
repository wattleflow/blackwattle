# Module name: connections/kafka.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2025 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# Dependencies:
#   pip install kafka-python-ng
# --------------------------------------------------------------------------- #
# KafkaProducerConnection — persistent producer connection via kafka-python-ng.
# KafkaConsumerConnection — persistent consumer connection via kafka-python-ng.
#
# Thread safety: KafkaConsumer and KafkaProducer are NOT thread-safe.
# Do not share a single connection instance across threads.
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import re
from contextlib import contextmanager
from typing import ClassVar, Generator, List, Optional, Tuple
from wattleflow.concrete.connection import (
    ConnectionAction,
)
from wattleflow.concrete.exception import ConnectionException
from wattleflow.enums.event import Event
from wattleflow.concrete.connection import GenericConnection

try:
    from kafka import KafkaConsumer, KafkaProducer  # noqa: F401
    from kafka.errors import KafkaError, NoBrokersAvailable, NodeNotReadyError  # noqa: F401
except Exception as e:
    raise ModuleNotFoundError(
        f"Missing required package to run this code: {__file__}.\n"
        "Please install it using:\n\tpip install kafka-python-ng"
        "\n\tconda install -c conda-forge openjdk=17\n"
    ) from e

from wattleflow.decorators.oscal import oscal_connection
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #
_VALID_SECURITY_PROTOCOLS = frozenset({"PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL"})
_VALID_AUTO_OFFSET_RESET = frozenset({"earliest", "latest", "none"})
_VALID_COMPRESSION_TYPES = frozenset({"none", "gzip", "snappy", "lz4", "zstd"})
# Keys that kafka_config must not override — changing these silently would
# bypass security settings configured explicitly via constructor kwargs.
_PROTECTED_CONFIG_KEYS = frozenset(
    {
        "bootstrap_servers",
        "security_protocol",
        "group_id",
        "sasl_plain_username",
    }
)
# Kafka topic names: alphanumeric, dot, underscore, hyphen; max 249 chars.
_TOPIC_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]{1,249}$")
# Bootstrap server entry: host:port or [ipv6]:port.
# Allows hostnames, IPv4, and bracketed IPv6. Prevents shell metacharacters.
_BOOTSTRAP_ENTRY_RE = re.compile(r"^[a-zA-Z0-9.\-\[\]:]{2,253}:\d{1,5}$")
_DEFAULT_FLUSH_TIMEOUT = 30  # seconds
_DEFAULT_CLOSE_TIMEOUT = 30  # seconds
# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class KafkaConnectionError(ConnectionException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region HelperClasses                                                        #
# --------------------------------------------------------------------------- #


class _KafkaMixin:
    # ---------------------------------------------------------------------- #
    # Validation
    # ---------------------------------------------------------------------- #
    def _validated_bootstrap_servers(self) -> str:
        servers = getattr(self, "bootstrap_servers", None)
        if not servers or not str(servers).strip():
            raise KafkaConnectionError(
                caller=self,
                error="'bootstrap_servers' is required and must not be empty.",
            )
        servers_str = str(servers).strip()
        if len(servers_str) > 2048:
            raise KafkaConnectionError(
                caller=self,
                error="'bootstrap_servers' exceeds maximum allowed length (2048 chars).",
            )
        for entry in servers_str.split(","):
            entry = entry.strip()
            if not entry:
                continue
            if not _BOOTSTRAP_ENTRY_RE.match(entry):
                raise KafkaConnectionError(
                    caller=self,
                    error=(
                        f"Invalid bootstrap server entry '{entry}'. "
                        "Expected 'host:port' format (e.g. 'kafka.example.com:9092')."
                    ),
                )
        return servers_str

    def _validated_security_protocol(self) -> str:
        protocol = str(getattr(self, "security_protocol", "PLAINTEXT")).strip().upper()
        if protocol not in _VALID_SECURITY_PROTOCOLS:
            raise KafkaConnectionError(
                caller=self,
                error=(
                    f"Invalid security_protocol '{protocol}'. "
                    f"Allowed: {sorted(_VALID_SECURITY_PROTOCOLS)}"
                ),
            )
        return protocol

    def _validated_topics(self, raw) -> List[str]:
        if not raw:
            return []
        if isinstance(raw, str):
            raw = [t.strip() for t in raw.split(",") if t.strip()]
        result: List[str] = []
        for topic in raw:
            topic = str(topic).strip()
            if not _TOPIC_NAME_RE.match(topic):
                raise KafkaConnectionError(
                    caller=self,
                    error=(
                        f"Invalid topic name '{topic}'. "
                        "Allowed characters: [a-zA-Z0-9._-], max 249 chars."
                    ),
                )
            result.append(topic)
        return result

    # ---------------------------------------------------------------------- #
    # Config building
    # ---------------------------------------------------------------------- #

    def _apply_extra_config(self, config: dict) -> dict:
        """
        Merges kafka_config dict into config, blocking protected keys.
        Use kafka_config in YAML for advanced settings (SSL certs, SASL tokens, etc.)
        that are not exposed as first-class kwargs.
        """
        extra: dict = getattr(self, "kafka_config", {})
        if not isinstance(extra, dict):
            return config
        overrides = {k: v for k, v in extra.items() if k not in _PROTECTED_CONFIG_KEYS}
        blocked = {k for k in extra if k in _PROTECTED_CONFIG_KEYS}
        if blocked:
            self.warning(
                msg=Event.Configure.name,
                reason="kafka_config contains protected keys that were ignored",
                blocked_keys=sorted(blocked),
                connection_name=self.connection_name,
            )
        config.update(overrides)
        return config

    def _apply_ssl_params(self, config: dict) -> dict:
        """Appends SSL parameters to config if present. Passwords are accepted but never logged."""
        for key in (
            "ssl_cafile",
            "ssl_certfile",
            "ssl_keyfile",
            "ssl_password",
            "ssl_check_hostname",
        ):
            val = getattr(self, key, None)
            if val is not None:
                config[key] = val
        return config

    def _apply_sasl_params(self, config: dict) -> dict:
        """Appends SASL parameters to config if present. Credentials are never logged."""
        for key in ("sasl_mechanism", "sasl_plain_username", "sasl_plain_password"):
            val = getattr(self, key, None)
            if val is not None:
                config[key] = val
        return config

    def _safe_config_repr(self, config: dict) -> dict:
        """Returns a copy of config with sensitive values masked for logging."""
        _sensitive = frozenset(
            {
                "ssl_password",
                "ssl_keyfile",
                "sasl_plain_password",
                "sasl_plain_username",
            }
        )
        return {k: ("***" if k in _sensitive else v) for k, v in config.items()}


# --------------------------------------------------------------------------- #
# endregion HelperClasses                                                     #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region KafkaProducerConnection                                              #
# --------------------------------------------------------------------------- #


@oscal_connection(strict=False)
class KafkaProducerConnection(_KafkaMixin, GenericConnection):
    """
    Persistent Kafka producer connection backed by kafka-python-ng.

    The underlying KafkaProducer is created once in create_connection() and
    reused across connect() calls. Each connect() context yields the live
    producer and flushes pending messages on exit. The engine is closed only
    when ensure_closed() is called (e.g. during cleanup).

    Required kwargs:
        bootstrap_servers (str): Comma-separated broker host:port pairs.

    Optional kwargs:
        client_id         (str):  Client identifier. Default: 'wattleflow-producer'.
        security_protocol (str):  PLAINTEXT | SSL | SASL_PLAINTEXT | SASL_SSL.
                                  Default: 'PLAINTEXT'.
        acks              (str):  '0' | '1' | 'all'. Default: 'all'.
        retries           (int):  Retry attempts on transient errors. Default: 3.
        retry_backoff_ms  (int):  Backoff between retries (ms). Default: 500.
        compression_type  (str):  none | gzip | snappy | lz4 | zstd. Default: None.
        max_request_size  (int):  Max message size in bytes. Default: 1048576 (1 MB).
        request_timeout_ms(int):  Request timeout (ms). Default: 30000.
        linger_ms         (int):  Delay before sending batch (ms).
        batch_size        (int):  Max batch size in bytes.
        buffer_memory     (int):  Total producer buffer memory in bytes.
        max_block_ms      (int):  Max block time when buffer is full (ms). Default: 60000.
        flush_timeout     (int):  Flush timeout per connect() exit (s). Default: 30.
        close_timeout     (int):  Close timeout for disconnect() (s). Default: 30.
        ssl_cafile        (str):  Path to CA certificate file.
        ssl_certfile      (str):  Path to client certificate file.
        ssl_keyfile       (str):  Path to client private key file.
        ssl_password      (str):  Password for ssl_keyfile.
        ssl_check_hostname(bool): Verify hostname against certificate. Default: True.
        sasl_mechanism    (str):  PLAIN | GSSAPI | OAUTHBEARER | SCRAM-SHA-256 | SCRAM-SHA-512.
        sasl_plain_username(str): SASL/PLAIN username.
        sasl_plain_password(str): SASL/PLAIN password.
        kafka_config      (dict): Additional kafka-python kwargs (merged last;
                                  protected keys are silently dropped).

    YAML config example::

        connections:
          kafka_producer:
            connection_name: kafka_producer
            bootstrap_servers: "kafka.example.com:9092"
            client_id: "wattleflow-producer"
            security_protocol: "SASL_SSL"
            sasl_mechanism: "PLAIN"
            sasl_plain_username: "user"
            sasl_plain_password: "secret"
            acks: "all"
            retries: 5
            compression_type: "gzip"

    Usage::

        with manager.get_connection("kafka_producer").connect() as producer:
            producer.send("my-topic", key=b"k", value=b"v")
            producer.flush()
    """

    ALLOWED = [
        "connection_name",
        "lazy_loading",
        "level",
        "handler",
        "bootstrap_servers",
        "client_id",
        "security_protocol",
        "acks",
        "retries",
        "retry_backoff_ms",
        "compression_type",
        "max_request_size",
        "request_timeout_ms",
        "linger_ms",
        "batch_size",
        "buffer_memory",
        "max_block_ms",
        "flush_timeout",
        "close_timeout",
        "ssl_cafile",
        "ssl_certfile",
        "ssl_keyfile",
        "ssl_password",
        "ssl_check_hostname",
        "sasl_mechanism",
        "sasl_plain_username",
        "sasl_plain_password",
        "kafka_config",
    ]
    # OSCAL: SASL credentials, plus `security_protocol` and the SSL settings.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ("ac-3", "ia-5", "sc-8")

    # ---------------------------------------------------------------------- #
    # Internal
    # ---------------------------------------------------------------------- #

    def _build_producer_config(self) -> dict:
        config: dict = {
            "bootstrap_servers": self._validated_bootstrap_servers(),
            "client_id": str(getattr(self, "client_id", "wattleflow-producer")),
            "security_protocol": self._validated_security_protocol(),
            "acks": getattr(self, "acks", "all"),
            "retries": int(getattr(self, "retries", 3)),
            "retry_backoff_ms": int(getattr(self, "retry_backoff_ms", 500)),
            "max_request_size": int(getattr(self, "max_request_size", 1048576)),
            "request_timeout_ms": int(getattr(self, "request_timeout_ms", 30000)),
            "max_block_ms": int(getattr(self, "max_block_ms", 60000)),
        }

        compression = getattr(self, "compression_type", None)
        if compression and str(compression).lower() not in ("none", ""):
            compression = str(compression).lower()
            if compression not in _VALID_COMPRESSION_TYPES:
                raise KafkaConnectionError(
                    caller=self,
                    error=(
                        f"Invalid compression_type '{compression}'. "
                        f"Allowed: {sorted(_VALID_COMPRESSION_TYPES)}"
                    ),
                )
            config["compression_type"] = compression

        for opt_key in ("linger_ms", "batch_size", "buffer_memory"):
            val = getattr(self, opt_key, None)
            if val is not None:
                config[opt_key] = int(val)

        self._apply_ssl_params(config)
        self._apply_sasl_params(config)
        return self._apply_extra_config(config)

    # ---------------------------------------------------------------------- #
    # GenericConnection API
    # ---------------------------------------------------------------------- #

    def create_connection(self) -> None:
        self.debug(
            msg=Event.Create.name,
            step=Event.Started.name,
            connection_name=self.connection_name,
            state=self.state.value,
        )

        try:
            config = self._build_producer_config()
            self.debug(
                msg=Event.Create.name,
                step=Event.Configuring.name,
                config=self._safe_config_repr(config),
            )
            self._engine = KafkaProducer(**config)
        except KafkaConnectionError:
            raise
        except NoBrokersAvailable as e:
            self.notify(
                self,
                error=f"No brokers available: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=str(e))
            raise KafkaConnectionError(
                caller=self,
                error=f"No brokers available at '{getattr(self, 'bootstrap_servers', '?')}': {e}",
            ) from e
        except NodeNotReadyError as e:
            self.notify(
                self,
                error=f"Node not ready: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=str(e))
            raise KafkaConnectionError(
                caller=self,
                error=f"Kafka node not ready: {e}",
            ) from e
        except KafkaError as e:
            self.notify(
                self,
                error=f"Kafka error during producer init: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=str(e))
            raise KafkaConnectionError(
                caller=self,
                error=f"Kafka error during KafkaProducer creation: {e}",
            ) from e
        except Exception as e:
            self.notify(
                self,
                error=f"Unexpected error during producer init: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=str(e))
            raise KafkaConnectionError(
                caller=self,
                error=f"Unexpected error during KafkaProducer creation: {e}",
            ) from e

        self._connection = None
        self.debug(
            msg=Event.Create.name,
            step=Event.Completed.name,
            connection_name=self.connection_name,
            state=self.state.value,
        )

    @contextmanager
    def connect(self) -> Generator[KafkaProducer, None, None]:
        self._ensure_created()

        flush_timeout = int(getattr(self, "flush_timeout", _DEFAULT_FLUSH_TIMEOUT))

        self.debug(
            msg=Event.Connect.name,
            connection_name=self.connection_name,
            state=self.state.value,
        )

        if self._engine is None:
            raise KafkaConnectionError(
                caller=self,
                error=f"{self.name}.connect: producer engine is None — "
                "create_connection() was not called.",
            )

        self._fsm.apply(ConnectionAction.CONNECT)

        try:
            self._fsm.apply(ConnectionAction.CONNECT_OK)
        except Exception as e:
            self._fsm.apply(ConnectionAction.CONNECT_FAIL)
            self.debug(msg=Event.Connect.name, step=Event.Failed.name, error=str(e))
            raise KafkaConnectionError(caller=self, error=str(e)) from e

        self.debug(
            msg=Event.Connected.name,
            connection_name=self.connection_name,
            state=self.state.value,
        )

        try:
            yield self._engine
        except Exception as e:
            self.notify(
                self,
                error=f"Error during producer session: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Connect.name, step=Event.Failed.name, error=str(e))
            raise
        finally:
            try:
                remaining = self._engine.flush(timeout=flush_timeout)
                if remaining > 0:
                    self.warning(
                        msg=Event.Flush.name,
                        reason="incomplete",
                        remaining=remaining,
                        connection_name=self.connection_name,
                    )
                    self.notify(
                        self,
                        error=f"Producer flush incomplete — {remaining} messages may be lost",
                        connection_name=self.connection_name,
                        state=self.state.value,
                    )
            except Exception as e:
                self.warning(
                    msg=Event.Flush.name,
                    reason="error",
                    error=str(e),
                    connection_name=self.connection_name,
                )
            self._fsm.apply(ConnectionAction.DISCONNECT)
            self.debug(
                msg=Event.Disconnected.name,
                connection_name=self.connection_name,
                note="producer engine still alive; call ensure_closed() to close",
            )

    def disconnect(self) -> None:
        self.debug(
            msg=Event.Disconnect.name,
            connection_name=self.connection_name,
            state=self.state.value,
        )

        close_timeout = int(getattr(self, "close_timeout", _DEFAULT_CLOSE_TIMEOUT))

        try:
            if self._engine:
                try:
                    self._engine.close(timeout=close_timeout)
                except Exception as e:
                    self.notify(
                        self,
                        error=f"Error closing KafkaProducer: {e}",
                        connection_name=self.connection_name,
                        state=self.state.value,
                    )
                finally:
                    self._engine = None
        finally:
            self._connection = None
            self.debug(
                msg=Event.Disconnected.name,
                connection_name=self.connection_name,
                state=self.state.value,
            )

    def __repr__(self) -> str:
        bootstrap = getattr(self, "bootstrap_servers", "?")
        return f"{self.name}:{self.state.value}[bootstrap={bootstrap}]"


# --------------------------------------------------------------------------- #
# endregion KafkaProducerConnection                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region KafkaConsumerConnection                                              #
# --------------------------------------------------------------------------- #


@oscal_connection(strict=False)
class KafkaConsumerConnection(_KafkaMixin, GenericConnection):
    """
    Persistent Kafka consumer connection backed by kafka-python-ng.

    The underlying KafkaConsumer is created once in create_connection() and
    reused across connect() calls. On each connect(), the consumer subscribes
    to the configured topics (if not already subscribed) and yields the live
    consumer. The engine is closed only when ensure_closed() is called.

    Required kwargs:
        bootstrap_servers (str): Comma-separated broker host:port pairs.
        group_id          (str): Consumer group identifier (required).

    Optional kwargs:
        client_id           (str):  Client identifier. Default: 'wattleflow-consumer'.
        security_protocol   (str):  PLAINTEXT | SSL | SASL_PLAINTEXT | SASL_SSL.
                                    Default: 'PLAINTEXT'.
        topics              (list | str): Topic(s) to subscribe to. Can be a list
                                    or comma-separated string. Validated against
                                    the Kafka topic name regex.
        auto_offset_reset   (str):  earliest | latest | none. Default: 'earliest'.
        enable_auto_commit  (bool): Auto-commit offsets. Default: True.
        auto_commit_interval_ms(int): Auto-commit interval (ms). Default: 5000.
        session_timeout_ms  (int):  Session timeout (ms). Default: 10000.
        heartbeat_interval_ms(int): Heartbeat interval (ms). Default: 3000.
        max_poll_records    (int):  Max records per poll(). Default: 500.
        max_poll_interval_ms(int):  Max time between polls before rebalance (ms).
        consumer_timeout_ms (int):  StopIteration after this ms if no messages.
        fetch_max_wait_ms   (int):  Max wait on server side (ms). Default: 500.
        fetch_min_bytes     (int):  Min data fetched per request. Default: 1.
        ssl_cafile, ssl_certfile, ssl_keyfile, ssl_password, ssl_check_hostname:
                                    SSL configuration.
        sasl_mechanism, sasl_plain_username, sasl_plain_password:
                                    SASL configuration.
        kafka_config        (dict): Additional kafka-python kwargs (merged last;
                                    protected keys are silently dropped).

    YAML config example::

        connections:
          kafka_consumer:
            connection_name: kafka_consumer
            bootstrap_servers: "kafka.example.com:9092"
            group_id: "wattleflow-group"
            client_id: "wattleflow-consumer"
            security_protocol: "PLAINTEXT"
            topics:
              - "wattleflow.events"
              - "wattleflow.files"
            auto_offset_reset: "earliest"
            enable_auto_commit: true
            session_timeout_ms: 10000

    Usage::

        with manager.get_connection("kafka_consumer").connect() as consumer:
            batch = consumer.poll(timeout_ms=1000, max_records=100)
            for tp, messages in batch.items():
                for msg in messages:
                    process(msg.value)
    """

    ALLOWED = [
        "connection_name",
        "lazy_loading",
        "level",
        "handler",
        "bootstrap_servers",
        "group_id",
        "client_id",
        "security_protocol",
        "auto_offset_reset",
        "enable_auto_commit",
        "auto_commit_interval_ms",
        "session_timeout_ms",
        "heartbeat_interval_ms",
        "max_poll_records",
        "max_poll_interval_ms",
        "consumer_timeout_ms",
        "fetch_max_wait_ms",
        "fetch_min_bytes",
        "topics",
        "ssl_cafile",
        "ssl_certfile",
        "ssl_keyfile",
        "ssl_password",
        "ssl_check_hostname",
        "sasl_mechanism",
        "sasl_plain_username",
        "sasl_plain_password",
        "kafka_config",
    ]
    # OSCAL: SASL credentials, plus `security_protocol` and the SSL settings.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ("ac-3", "ia-5", "sc-8")

    # ---------------------------------------------------------------------- #
    # Properties
    # ---------------------------------------------------------------------- #

    @property
    def subscribed_topics(self) -> Optional[frozenset]:
        """Returns the current subscription set, or None if the consumer is not initialised."""
        if not self._engine:
            return None
        try:
            return frozenset(self._engine.subscription() or set())
        except Exception:
            return None

    # ---------------------------------------------------------------------- #
    # Internal
    # ---------------------------------------------------------------------- #

    def _build_consumer_config(self) -> dict:
        group_id: Optional[str] = getattr(self, "group_id", None)
        if not group_id or not str(group_id).strip():
            raise KafkaConnectionError(
                caller=self,
                error="'group_id' is required for KafkaConsumerConnection.",
            )

        auto_offset_reset = str(getattr(self, "auto_offset_reset", "earliest")).lower()
        if auto_offset_reset not in _VALID_AUTO_OFFSET_RESET:
            raise KafkaConnectionError(
                caller=self,
                error=(
                    f"Invalid auto_offset_reset '{auto_offset_reset}'. "
                    f"Allowed: {sorted(_VALID_AUTO_OFFSET_RESET)}"
                ),
            )

        config: dict = {
            "bootstrap_servers": self._validated_bootstrap_servers(),
            "group_id": str(group_id).strip(),
            "client_id": str(getattr(self, "client_id", "wattleflow-consumer")),
            "security_protocol": self._validated_security_protocol(),
            "auto_offset_reset": auto_offset_reset,
            "enable_auto_commit": bool(getattr(self, "enable_auto_commit", True)),
            "auto_commit_interval_ms": int(getattr(self, "auto_commit_interval_ms", 5000)),
            "session_timeout_ms": int(getattr(self, "session_timeout_ms", 10000)),
            "heartbeat_interval_ms": int(getattr(self, "heartbeat_interval_ms", 3000)),
            "max_poll_records": int(getattr(self, "max_poll_records", 500)),
            "fetch_max_wait_ms": int(getattr(self, "fetch_max_wait_ms", 500)),
            "fetch_min_bytes": int(getattr(self, "fetch_min_bytes", 1)),
        }

        for opt_key in ("max_poll_interval_ms", "consumer_timeout_ms"):
            val = getattr(self, opt_key, None)
            if val is not None:
                config[opt_key] = int(val)

        self._apply_ssl_params(config)
        self._apply_sasl_params(config)
        return self._apply_extra_config(config)

    # ---------------------------------------------------------------------- #
    # GenericConnection API
    # ---------------------------------------------------------------------- #

    def create_connection(self) -> None:
        self.debug(
            msg=Event.Create.name,
            step=Event.Started.name,
            connection_name=self.connection_name,
            state=self.state.value,
        )

        try:
            config = self._build_consumer_config()
            self.debug(
                msg=Event.Create.name,
                step=Event.Configuring.name,
                config=self._safe_config_repr(config),
            )
            self._engine = KafkaConsumer(**config)
        except KafkaConnectionError:
            raise
        except NoBrokersAvailable as e:
            self.notify(
                self,
                error=f"No brokers available: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=str(e))
            raise KafkaConnectionError(
                caller=self,
                error=f"No brokers available at '{getattr(self, 'bootstrap_servers', '?')}': {e}",
            ) from e
        except NodeNotReadyError as e:
            self.notify(
                self,
                error=f"Node not ready: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=str(e))
            raise KafkaConnectionError(
                caller=self,
                error=f"Kafka node not ready: {e}",
            ) from e
        except KafkaError as e:
            self.notify(
                self,
                error=f"Kafka error during consumer init: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=str(e))
            raise KafkaConnectionError(
                caller=self,
                error=f"Kafka error during KafkaConsumer creation: {e}",
            ) from e
        except Exception as e:
            self.notify(
                self,
                error=f"Unexpected error during consumer init: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=str(e))
            raise KafkaConnectionError(
                caller=self,
                error=f"Unexpected error during KafkaConsumer creation: {e}",
            ) from e

        self._connection = None
        self.debug(
            msg=Event.Create.name,
            step=Event.Completed.name,
            connection_name=self.connection_name,
            state=self.state.value,
        )

    @contextmanager
    def connect(self) -> Generator[KafkaConsumer, None, None]:
        self._ensure_created()

        self.debug(
            msg=Event.Connect.name,
            connection_name=self.connection_name,
            state=self.state.value,
        )

        if self._engine is None:
            raise KafkaConnectionError(
                caller=self,
                error=f"{self.name}.connect: consumer engine is None — "
                "create_connection() was not called.",
            )

        self._fsm.apply(ConnectionAction.CONNECT)

        try:
            topics = self._validated_topics(getattr(self, "topics", []))
            if topics:
                current = self._engine.subscription() or set()
                if set(topics) != current:
                    self._engine.subscribe(topics)
                    self.debug(
                        msg=Event.Connect.name,
                        scope=Event.Subscribe.name,
                        topics=topics,
                        connection_name=self.connection_name,
                    )
            self._fsm.apply(ConnectionAction.CONNECT_OK)
        except KafkaConnectionError as e:
            self._fsm.apply(ConnectionAction.CONNECT_FAIL)
            self.debug(msg=Event.Connect.name, step=Event.Failed.name, error=str(e))
            raise
        except Exception as e:
            self._fsm.apply(ConnectionAction.CONNECT_FAIL)
            self.notify(
                self,
                error=f"Failed to subscribe to topics: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Connect.name, step=Event.Failed.name, error=str(e))
            raise KafkaConnectionError(
                caller=self,
                error=f"Failed to subscribe to topics: {e}",
            ) from e

        self.debug(
            msg=Event.Connected.name,
            connection_name=self.connection_name,
            group_id=getattr(self, "group_id", "?"),
            topics=list(self._engine.subscription() or []),
            state=self.state.value,
        )

        try:
            yield self._engine
        except Exception as e:
            self.notify(
                self,
                error=f"Error during consumer session: {e}",
                connection_name=self.connection_name,
                state=self.state.value,
            )
            self.debug(msg=Event.Connect.name, step=Event.Failed.name, error=str(e))
            raise
        finally:
            self._fsm.apply(ConnectionAction.DISCONNECT)
            self.debug(
                msg=Event.Disconnected.name,
                connection_name=self.connection_name,
                note="consumer engine still alive; call ensure_closed() to close",
            )

    def disconnect(self) -> None:
        self.debug(
            msg=Event.Disconnect.name,
            connection_name=self.connection_name,
            state=self.state.value,
        )

        try:
            if self._engine:
                try:
                    self._engine.close(autocommit=True)
                except Exception as e:
                    self.notify(
                        self,
                        error=f"Error closing KafkaConsumer: {e}",
                        connection_name=self.connection_name,
                        state=self.state.value,
                    )
                finally:
                    self._engine = None
        finally:
            self._connection = None
            self.debug(
                msg=Event.Disconnected.name,
                connection_name=self.connection_name,
                state=self.state.value,
            )

    def __repr__(self) -> str:
        return f"{self.name}:{self.state.value}[group={getattr(self, 'group_id', '?')}]"


# --------------------------------------------------------------------------- #
# endregion KafkaConsumerConnection                                           #
# --------------------------------------------------------------------------- #
