# Module name: processors/spark.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# IMPORTANT:
# This module requires the pyspark library.
# Ensure you have it installed using:
#   pip install pyspark
#
# SparkReadProcessor  — reads a DataFrame from each configured source via DriverSpark
#                       and yields a facade with schema/stats metadata per source.
# SparkWriteProcessor — reads a DataFrame from source, writes it to destination
#                       via DriverSpark and yields a facade with write result metadata.
#
# Both processors delegate all session and format logic to DriverSpark.
# Strategies remain unaware of Spark — they only interact with document facades.
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
from wattleflow.drivers import DriverSpark
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Processors                                                           #
# --------------------------------------------------------------------------- #


class SparkReadProcessor(GenericProcessor):
    ALLOWED = [
        "driver",
        "sources",
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.debug(
            msg=Event.Constructor.name,
            step=Event.Started.name,
            driver=repr(getattr(self, "driver", None)),
            sources=[s.get("uri") for s in (getattr(self, "sources", []) or [])],
        )

    def create_generator(self) -> Generator[ITarget, None, None]:
        self.debug(msg=Event.Generate.name, step=Event.Started.name)

        try:
            driver: DriverSpark = self.driver
            sources: List[Dict] = getattr(self, "sources", []) or []

            self.debug(msg=Event.Generate.name, source_count=len(sources))

            for source in sources:
                uri: str = source.get("uri", "")
                fmt: Optional[str] = source.get("format")
                read_options: dict = source.get("read_options", {})

                self.debug(msg=Event.Generate.name, scope="item", uri=uri, format=fmt)

                try:
                    df = driver.read(uri, format=fmt, read_options=read_options)
                    row_count: int = df.count()
                    schema: str = df.schema.simpleString()
                    columns: List[str] = df.columns

                    metadata = {
                        "operation": "read",
                        "source_uri": uri,
                        "format": fmt,
                        "columns": columns,
                        "row_count": row_count,
                        "schema": schema,
                    }

                    self.debug(
                        msg=Event.Generate.name,
                        scope="item",
                        no=self.cycle + 1,
                        uri=uri,
                        row_count=row_count,
                    )

                    facade: DocumentFacade = self.blackboard.create(
                        caller=self,
                        uri=uri,
                        content=[metadata],
                        metadata=metadata,
                    )
                    yield facade

                except Exception as e:
                    error = f"Error: {str(e)}"
                    self.exception(msg=Event.Generate.name, step=Event.Failed.name, error=error)
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


# endregion SparkReadProcessor
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region SparkWriteProcessor
# --------------------------------------------------------------------------- #


class SparkWriteProcessor(GenericProcessor):
    """
    Reads a DataFrame from source and writes it to destination via DriverSpark.

    Yields a single document facade via blackboard.create() with write result
    metadata (destination URI, row count, format, mode).

    Args:
        driver             : DriverSpark with an active SparkConnection.
        source_uri         : Source file path, HDFS/S3 URI or SQL query.
        source_format      : Optional read format for the source.
        destination_uri    : Output path or "db.table" for saveAsTable.
        destination_format : Write format — json | parquet | orc | csv | delta.
        mode               : Write mode — overwrite | append | ignore | error.
    """

    ALLOWED = [
        "destination_format",
        "destination_uri",
        "driver",
        "mode",
        "source_format",
        "source_uri",
    ]

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("mode", "overwrite")
        super().__init__(**kwargs)
        self.debug(
            msg=Event.Constructor.name,
            step=Event.Started.name,
            driver=repr(getattr(self, "driver", None)),
            source_uri=getattr(self, "source_uri", None),
            destination_uri=getattr(self, "destination_uri", None),
            format=getattr(self, "destination_format", None),
            mode=getattr(self, "mode", "overwrite"),
        )

    def create_generator(self) -> Generator[ITarget, None, None]:
        self.debug(msg=Event.Generate.name, step=Event.Started.name)

        try:
            driver: DriverSpark = self.driver
            source_uri: str = self.source_uri
            source_format: Optional[str] = getattr(self, "source_format", None)
            destination_uri: str = self.destination_uri
            destination_format: str = self.destination_format
            mode: str = getattr(self, "mode", "overwrite")

            self.debug(
                msg=Event.Generate.name,
                source=source_uri,
                destination=destination_uri,
            )

            df = driver.read(source_uri, format=source_format)
            row_count: int = df.count()
            columns: List[str] = df.columns

            result_uri: str = driver.write(
                destination_uri,
                df,
                format=destination_format,
                mode=mode,
            )

            metadata = {
                "operation": "write",
                "source_uri": source_uri,
                "source_format": source_format,
                "destination_uri": result_uri,
                "destination_format": destination_format,
                "mode": mode,
                "columns": columns,
                "row_count": row_count,
            }

            self.debug(
                msg=Event.Generate.name,
                no=self.cycle + 1,
                result_uri=result_uri,
                row_count=row_count,
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
