# Module name: processors/kafka.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2025 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# IMPORTANT: This module requires the DriverKafka                             #
# KafkaWriteProcessor — sends a pre-built list of messages to Kafka           #
#    via DriverKafka.                                                         #
#                                                                             #
# KafkaReadProcessor  — polls all available messages from configured          #
#    Kafka topics.                                                            #
#                                                                             #
# Both processors delegate all connection and serialisation logic to          #
# DriverKafka. Strategies remain unaware of Kafka — they only interact with   #
# document facades.                                                           #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from traceback import format_exc
from typing import Any, Dict, Generator, List, Optional
from wattleflow.concrete import DocumentFacade, GenericProcessor
from wattleflow.concrete.exception import ProcessorException
from wattleflow.core import ITarget
from wattleflow.enums.event import Event
from wattleflow.drivers.kafka import DriverKafka
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Processors                                                           #
# --------------------------------------------------------------------------- #


class KafkaWriteProcessor(GenericProcessor):
    # region docstr
    """
    Sends a pre-built list of messages to Kafka via DriverKafka.write().

    For each message a document facade is created via blackboard.create() and
    yielded to the registered pipelines. The facade carries uri and metadata
    describing the write result — the strategy layer decides how to persist it.

    Args:
        driver   : DriverKafka configured with write_connection.
        messages : List of dicts, each with:
                     topic (str) — Kafka topic name.
                     data        — Payload: bytes, str, dict or list.
                     key   (str) — Optional Kafka message key.
    """

    # endregion docstr

    ALLOWED = [
        "driver",
        "messages",
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.debug(
            msg=Event.Constructor.name,
            step=Event.Started.name,
            driver=repr(getattr(self, "driver", None)),
            message_count=len(getattr(self, "messages", []) or []),
        )

    def create_generator(self) -> Generator[ITarget, None, None]:
        self.debug(msg=Event.Generate.name, step=Event.Started.name)

        try:
            driver: DriverKafka = self.driver
            messages: List[Dict] = getattr(self, "messages", None) or []

            self.debug(msg=Event.Generate.name, messages=len(messages))

            for msg in messages:
                topic: str = msg.get("topic", "")
                self.debug(msg=Event.Generate.name, scope="item", topic=topic)
                try:
                    data = msg.get("data", b"")
                    key: Optional[str] = msg.get("key")

                    result_uri: str = driver.write(uri=topic, data=data, key=key)
                    metadata = {"topic": topic, "result_uri": result_uri, "key": key}

                    self.debug(
                        msg=Event.Generate.name,
                        scope="item",
                        no=self.cycle + 1,
                        topic=topic,
                        key=key,
                    )

                    facade: DocumentFacade = self.blackboard.create(
                        caller=self,
                        uri=result_uri,
                        content=[metadata],
                        metadata=metadata,
                    )
                    yield facade

                except Exception as e:
                    error = f"Error: {str(e)}"
                    self.exception(
                        msg=Event.Generate.name,
                        step=Event.Failed.name,
                        error=error,
                    )
                    continue
        except Exception as e:
            error = f"Error: {str(e)}"
            self.debug(
                msg=Event.Generate.name,
                step=Event.Failed.name,
                error=error,
                trace=format_exc(),
            )
            raise ProcessorException(
                caller=self,
                error=error,
                exc=format_exc(),
            ) from e

        self.debug(
            msg=Event.Generate.name,
            step=Event.Completed.name,
            count=self.cycle,
        )


class KafkaReadProcessor(GenericProcessor):
    # region docstr
    """
    Polls all available messages from configured Kafka topics via DriverKafka.read().

    For each message a document facade is created via blackboard.create() and
    yielded to the registered pipelines. The facade carries the Kafka URI,
    deserialized content and full message metadata.

    Args:
        driver       : DriverKafka configured with read_connection and topics.
        topic_filter : Optional topic name to filter. Empty = all configured topics.
        max_messages : Stop after this many messages. 0 = drain all available.
    """

    # endregion docstr

    ALLOWED = [
        "driver",
        "max_messages",
        "topic_filter",
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.debug(
            msg=Event.Constructor.name,
            step=Event.Started.name,
            driver=repr(getattr(self, "driver", None)),
            topic_filter=getattr(self, "topic_filter", "") or "(all)",
            max_messages=getattr(self, "max_messages", 0),
        )

    def create_generator(self) -> Generator[ITarget, None, None]:
        self.debug(msg=Event.Generate.name, step=Event.Started.name)

        try:
            driver: DriverKafka = self.driver
            topic_filter: str = getattr(self, "topic_filter", "") or ""
            max_messages: int = int(getattr(self, "max_messages", 0) or 0)

            messages = driver.read(uri=topic_filter)

            self.debug(msg=Event.Generate.name, topic_filter=topic_filter or "(all)")

            count = 0
            for msg in messages:
                topic: str = msg.get("topic", "")
                self.debug(msg=Event.Generate.name, scope="item", topic=topic)
                try:
                    msg_id: str = f"{msg['topic']}-{msg['partition']}-{msg['offset']}"
                    uri: str = f"kafka://{msg['topic']}/{msg['partition']}/{msg['offset']}"
                    raw_content = msg["value"]
                    content = raw_content if isinstance(raw_content, list) else [raw_content]

                    self.debug(
                        msg=Event.Generate.name,
                        scope="item",
                        no=self.cycle + 1,
                        uri=uri,
                        size=len(content),
                    )

                    facade: DocumentFacade = self.blackboard.create(
                        caller=self,
                        id=msg_id,
                        uri=uri,
                        content=content,
                        metadata=msg,
                    )
                    yield facade

                    count += 1
                    if max_messages > 0 and count >= max_messages:
                        break

                except Exception as e:
                    error = f"Error: {str(e)}"
                    self.exception(
                        msg=Event.Generate.name,
                        step=Event.Failed.name,
                        error=error,
                    )
                    continue
        except Exception as e:
            error = f"Error: {str(e)}"
            self.debug(
                msg=Event.Generate.name,
                step=Event.Failed.name,
                error=error,
                trace=format_exc(),
            )
            raise ProcessorException(
                caller=self,
                error=error,
                exc=format_exc(),
            ) from e

        self.debug(
            msg=Event.Generate.name,
            step=Event.Completed.name,
            count=self.cycle,
        )


# --------------------------------------------------------------------------- #
# endregion Processors                                                        #
# --------------------------------------------------------------------------- #
