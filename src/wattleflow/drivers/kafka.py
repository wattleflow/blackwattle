# Module name: drivers/kafka.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# IMPORTANT: This driver requires the kafka-python-ng library.                #
# Ensure you have it installed using:                                         #
#     pip install kafka-python-ng                                             #
# DriverKafka — unified persistence layer for sending and receiving Kafka     #
# messages.                                                                   #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports
# --------------------------------------------------------------------------- #
from __future__ import annotations
import re
from enum import Enum
from typing import Any, List, Optional
from wattleflow.concrete.connection import Connection
from wattleflow.concrete.driver import (
    DriverAction,
    GenericDriver,
    DriverState,
    DriverMetadata,
)

from wattleflow.concrete.manager import ConnectionManager
from wattleflow.concrete.exception import DriverException
from wattleflow.enums.event import Event
# --------------------------------------------------------------------------- #
# endregion Imports
# --------------------------------------------------------------------------- #

# if TYPE_CHECKING:
#     from wattleflow.connections.kafka import KafkaConnection

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #

_TOPIC_NAME_RE = re.compile(r"^[a-zA-Z0-9._-]{1,249}$")

# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class KafkaConnectionError(DriverException):
    pass


class DriverKafkaError(DriverException):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region ConnectionType                                                       #
# --------------------------------------------------------------------------- #


class ConnectionType(str, Enum):
    Consumer = "consumer"
    Producer = "producer"


# --------------------------------------------------------------------------- #
# endregion ConnectionType                                                    #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region ConnectionManager                                                    #
# --------------------------------------------------------------------------- #


class DriverKafkaConnectionManager:
    # try:
    #     from kafka import KafkaConsumer, KafkaProducer
    #     from kafka.errors import NoBrokersAvailable, NodeNotReadyError
    # except Exception as e:
    #     raise ModuleNotFoundError(
    #         f"Kafka library is required to run this code.[{str(e)}\n"
    #         "Please install it with `pip install kafka-python`"
    #     ) from e

    def __init__(self, driver: "DriverKafka", shared_manager) -> None:
        self._driver = driver
        self._shared_manager = shared_manager
        self._clients: dict[str, object] = {}

    def _generate_group_id(self) -> str:
        return f"{self._driver.__class__.__name__}-{abs(hash(self._driver))}"

    def _get_base_connection(self, conn_name: str) -> "Connection":
        conn = self._shared_manager.get_connection(conn_name)
        if conn is None:
            raise KafkaConnectionError(
                caller=self._driver,
                error=f"Connection '{conn_name}' not found in manager",
            )
        conn._ensure_created()
        return conn

    def get_consumer(
        self, conn_name: str, topics: List[str], **overrides
    ) -> Any:  # "KafkaConsumer"
        if "read" in self._clients:
            return self._clients["read"]

        try:
            from kafka import KafkaConsumer
        except ImportError as e:
            raise ModuleNotFoundError(
                f"Kafka library is required to run this code.[{str(e)}\n"
                "Please install it with `pip install kafka-python`"
            ) from e

        conn = self._get_base_connection(conn_name)
        overrides.setdefault("group_id", self._generate_group_id())
        overrides.setdefault("auto_offset_reset", "earliest")
        config = conn._build_consumer_config(**overrides)

        consumer = KafkaConsumer(**config)
        if topics:
            consumer.subscribe(topics)
        self._clients["read"] = consumer
        return consumer

    def get_producer(self, conn_name: str, **overrides) -> Any:  # "KafkaProducer"
        if "write" in self._clients:
            return self._clients["write"]

        try:
            from kafka import KafkaProducer
        except ImportError as e:
            raise ModuleNotFoundError(
                f"Kafka library is required to run this code.[{str(e)}\n"
                "Please install it with `pip install kafka-python`"
            ) from e

        conn = self._get_base_connection(conn_name)
        config = conn._build_producer_config(**overrides)

        producer = KafkaProducer(**config)
        self._clients["write"] = producer
        return producer

    def invalidate(self, role: Optional[str] = None) -> None:
        if role and role in self._clients:
            self._close_client(self._clients.pop(role))
        elif role is None:
            for client in self._clients.values():
                self._close_client(client)
            self._clients.clear()

    def clear(self) -> None:
        self.invalidate()

    @staticmethod
    def _close_client(client) -> None:

        try:
            from kafka import KafkaConsumer, KafkaProducer

            if isinstance(client, KafkaConsumer):
                client.close(autocommit=True)
            elif isinstance(client, KafkaProducer):
                client.close(timeout=10)
        except ImportError as e:
            raise ModuleNotFoundError(
                f"Kafka library is required to run this code.[{str(e)}\n"
                "Please install it with `pip install kafka-python`"
            ) from e
        except Exception:
            pass

    def __repr__(self) -> str:
        return f"DriverKafkaConnectionManager(clients={list(self._clients.keys())})"


# --------------------------------------------------------------------------- #
# endregion ConnectionManager                                                 #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Driver                                                               #
# --------------------------------------------------------------------------- #


class DriverKafka(GenericDriver):
    ALLOWED = ["consumer", "producer", "topics"]

    def __init__(
        self,
        connection_name: str,
        manager: ConnectionManager = None,
        **kwargs,
    ) -> None:

        if not connection_name or connection_name == "":
            raise KafkaConnectionError("DriverKafka: connection_name must be provided!")

        # The kafka client is chatty; this driver stays quiet unless the caller
        # (YAML `level:` or the owning component) asks otherwise. `setdefault`
        # supplies a default without consuming the keyword — the split stays in
        # `Wattleflow.__init__`.
        kwargs.setdefault("level", "ERROR")

        super().__init__(
            connection_name=connection_name,
            manager=manager,
            **kwargs,
        )
        self._connection_name = connection_name
        self._manager = manager

        # manager: if not provied, create internally
        if not isinstance(self._manager, ConnectionManager):
            self._manager = ConnectionManager(self._level, self._handler)

        self.ensure_live()
        self.debug(
            msg=Event.Constructor.name,
            step=Event.Started.name,
            manager=self._manager,
            connection=self._connection_name,
            topics=self.topics,
            state=self.state,
        )

    def load(self):
        self.debug(
            msg=Event.Load.name,
            step=Event.Started.name,
            connection=self._connection_name,
            manager=self._manager,
            state=self.state.name,
        )

        if self.consumer is None or len(self.consumer) < 1:
            raise ValueError("Kafka: Consumer confiugration must be provided!")

        if self.producer is None or len(self.producer) < 1:
            raise ValueError("Kafka: consumer & producer confiugration must be provided!")

        if self.state != DriverState.LOADING:
            raise RuntimeError(f"Loading: state runtime error: {self.state.name}")

        try:
            from kafka import KafkaConsumer, KafkaProducer
            from kafka.errors import NoBrokersAvailable, NodeNotReadyError
        except ImportError as e:
            self.debug(msg=Event.Load.name, step=Event.Failed.name, error=str(e))
            raise ModuleNotFoundError(
                f"Kafka library is required to run this code.[{str(e)}\n"
                "Please install it with `pip install kafka-python`"
            ) from e

        try:
            # -------------------------------------------------------------------
            # consumer: create, register and subscribe -------------------------
            # -------------------------------------------------------------------
            raw_topics = self.topics or []
            if isinstance(raw_topics, str):
                raw_topics = [t.strip() for t in raw_topics.split(",") if t.strip()]
            topics = list(raw_topics)
            consumer_name = self._get_conn_name(ConnectionType.Consumer)
            self._manager.register_connection(
                KafkaConsumer(*topics, **self.consumer),
                connection_name=consumer_name,
            )
            # Kafka Conusmer nema subscribe metodu.

            # -------------------------------------------------------------------
            # producer: create, register and subscribe --------------------------
            # -------------------------------------------------------------------
            producer_name = self._get_conn_name(ConnectionType.Producer)
            self._manager.register_connection(
                KafkaProducer(**self.producer),
                connection_name=producer_name,
            )
        except NoBrokersAvailable as e:
            error_msg = f"{str(e)}: no brokers available for connection '{self._connection_name}'!"
            self.debug(
                msg=Event.Load.name,
                step=Event.Failed.name,
                error=error_msg,
                connection=self._connection_name,
            )
            raise KafkaConnectionError(self, error_msg) from e
        except NodeNotReadyError as e:
            error_msg = f"Node is not ready: {str(e)} - '{self._connection_name}'!"
            self.debug(
                msg=Event.Load.name,
                step=Event.Failed.name,
                error=error_msg,
                connection=self._connection_name,
            )
            raise KafkaConnectionError(self, error_msg) from e
        except Exception as e:
            self.debug(msg=Event.Load.name, step=Event.Failed.name, error=str(e))
            raise DriverKafkaError(caller=self, error=str(e)) from e

        self.debug(msg=Event.Load.name, step=Event.Completed.name)

    def close(self):
        self.debug(msg=Event.Close.name, step=Event.Started.name)

        if not self.can(DriverAction.UNLOAD):
            return

        try:
            from kafka import KafkaConsumer, KafkaProducer
        except ImportError as e:
            self.debug(msg=Event.Close.name, step=Event.Failed.name, error=str(e))
            raise ModuleNotFoundError(
                f"Kafka library is required to run this code.[{str(e)}\n"
                "Please install it with `pip install kafka-python`"
            ) from e

        try:
            # name: str = self._connection_name
            # connection: Optional[Connection] = self._manager.get_connection(name)
            consumer: KafkaConsumer = self._manager.get_connection(
                self._get_conn_name(ConnectionType.Consumer)
            )
            if consumer:
                self.debug(
                    msg=Event.Close.name,
                    conn=ConnectionType.Consumer.name,
                )

            producer: KafkaProducer = self._manager.get_connection(
                self._get_conn_name(ConnectionType.Producer)
            )
            if producer:
                self.debug(
                    msg=Event.Close.name,
                    conn=ConnectionType.Producer.name,
                )
                producer.close(timeout=10)

            self._manager.unregister_connection(self._get_conn_name(ConnectionType.Consumer))
            self._manager.unregister_connection(self._get_conn_name(ConnectionType.Producer))

            self.debug(msg=Event.Close.name, step=Event.Completed.name)
        except Exception as e:
            error = f"{str(e)}: caught while closing {self!r}!"
            self.error(
                msg=Event.Close.name,
                step=Event.Failed.name,
                error=error,
                connection=self._connection_name,
                manager=self._manager,
            )

    def read(self, uri: str, **kwargs) -> list:
        self.debug(msg=Event.Read.name, step=Event.Started.name, uri=uri, kwargs=kwargs)

        poll_timeout_ms: int = kwargs.get("poll_timeout_ms", 5000)
        max_records: int = kwargs.get("max_records", 100)
        topic_filter: Optional[str] = uri or None

        self.debug(
            msg=Event.Read.name,
            step=Event.Started.name,
            topic_filter=topic_filter or "(all)",
            poll_timeout_ms=poll_timeout_ms,
            max_records=max_records,
        )

        try:
            from kafka import KafkaConsumer
        except ImportError as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=str(e))
            raise ModuleNotFoundError(
                f"Kafka library is required to run this code.[{str(e)}\n"
                "Please install it with `pip install kafka-python`"
            ) from e

        consumer_name = self._get_conn_name(ConnectionType.Consumer)
        consumer: KafkaConsumer = self._manager.get_connection(consumer_name)

        if not isinstance(consumer, KafkaConsumer):
            raise DriverKafkaError(
                caller=self,
                error=f"read: unexpected connection type: {consumer.__class__.__name__!r}!",
            )

        self.debug(msg=Event.Read.name, consumer=consumer_name)

        messages = []
        try:
            raw = consumer.poll(timeout_ms=poll_timeout_ms, max_records=max_records)
            for tp, msgs in raw.items():
                if topic_filter and tp.topic != topic_filter:
                    continue
                for msg in msgs:
                    messages.append(
                        {
                            "topic": msg.topic,
                            "partition": msg.partition,
                            "offset": msg.offset,
                            "key": msg.key.decode("utf-8") if msg.key else None,
                            "value": msg.value,
                            "timestamp": msg.timestamp,
                        }
                    )
        except KafkaConnectionError as e:
            error = f"{self.name!r} connection error caught while handling read request: {str(e)}!"
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=error)
            raise DriverKafkaError(caller=self, error=error) from e
        except Exception as e:
            error = (
                f"{self.name!r} unexpected exception caught while handling read request: {str(e)}!"
            )
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=error)
            raise DriverKafkaError(caller=self, error=error) from e

        self.debug(msg=Event.Read.name, step=Event.Completed.name, count=len(messages))
        return messages

    def write(self, uri: str, **kwargs) -> str:
        self.debug(msg=Event.Write.name, step=Event.Started.name, uri=uri, kwargs=kwargs)

        topic: str = kwargs.get("topic") or uri
        data = kwargs.get("data")
        key = kwargs.get("key")
        flush_timeout: int = kwargs.get("flush_timeout", 10)

        if not topic:
            raise DriverKafkaError(caller=self, error="write: 'topic' is required!")
        if data is None:
            raise DriverKafkaError(caller=self, error="write: 'data' is required!")

        if isinstance(key, str):
            key = key.encode("utf-8")

        value: bytes = data if isinstance(data, bytes) else str(data).encode("utf-8")

        self.debug(
            msg=Event.Write.name,
            step=Event.Started.name,
            topic=topic,
            key=key,
            value_size=len(value),
        )

        try:
            from kafka import KafkaProducer
        except ImportError as e:
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=str(e))
            raise ModuleNotFoundError(
                f"Kafka library is required to run this code.[{str(e)}\n"
                "Please install it with `pip install kafka-python`"
            ) from e

        producer_name = self._get_conn_name(ConnectionType.Producer)
        producer: KafkaProducer = self._manager.get_connection(producer_name)

        if not isinstance(producer, KafkaProducer):
            raise DriverKafkaError(
                caller=self,
                error=f"write: unexpected connection type: {producer.__class__.__name__!r}!",
            )

        self.debug(msg=Event.Write.name, producer=producer_name)

        try:
            future = producer.send(topic, key=key, value=value)
            producer.flush(timeout=flush_timeout)
            record = future.get(timeout=flush_timeout)
        except KafkaConnectionError as e:
            error = f"{self.name!r} connection error caught while handling write request: {str(e)}!"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise DriverKafkaError(caller=self, error=error) from e
        except Exception as e:
            error = (
                f"{self.name!r} unexpected exception caught while handling write request: {str(e)}!"
            )
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise DriverKafkaError(caller=self, error=error) from e

        result_uri = f"kafka://{topic}/{record.partition}/{record.offset}"

        self.debug(
            msg=Event.Write.name,
            step=Event.Completed.name,
            topic=topic,
            partition=record.partition,
            offset=record.offset,
            uri=result_uri,
        )

        return result_uri

    def metadata(self) -> DriverMetadata:
        try:
            from kafka import __version__ as _kafka_version
        except ImportError:
            _kafka_version = "unknown"

        return DriverMetadata(
            name=self.__class__.__name__,
            version=_kafka_version,
            protocol="kafka",
            capabilities=["read", "write"],
        )

    def update(self, event: Event, **kwargs) -> None:
        event_name = event.name if hasattr(event, "name") else str(event)
        self.debug(msg=Event.Update.name, step=Event.Started.name, event=event_name)

        connection_name = kwargs.get("connection_name", self._connection_name)
        state = kwargs.get("state", "")
        error = kwargs.get("error", "")

        if error:
            self.error(
                msg=Event.Update.name,
                event=event_name,
                connection_name=connection_name,
                error=error,
                state=state,
            )
        elif event in (Event.Disconnected, Event.Disconnecting):
            self.warning(
                msg=Event.Update.name,
                step=Event.Check.name,
                event=event_name,
                connection_name=connection_name,
                state=state,
            )
        else:
            self.debug(
                msg=Event.Update.name,
                event=event_name,
                connection_name=connection_name,
                state=state,
            )

        self.debug(msg=Event.Update.name, step=Event.Completed.name)

    def _get_conn_name(self, conn_type: ConnectionType) -> str:
        return f"{self.name}-{id(self)}-{conn_type.name}"


# --------------------------------------------------------------------------- #
# endregion Driver                                                            #
# --------------------------------------------------------------------------- #
