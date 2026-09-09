# Module name: processors/postgres.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2025 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import pandas as pd
from traceback import format_exc
from typing import Any, ClassVar, Generator, Tuple
from wattleflow.core import IDriver, ITarget
from wattleflow.concrete.exception import ProcessorException
from wattleflow.enums.event import Event
from wattleflow.concrete.helpers import Attribute
from wattleflow.concrete import DocumentFacade, GenericProcessor
from wattleflow.decorators.oscal import oscal_processor
# --------------------------------------------------------------------------- #
# endregion Imports                                                            #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Processor                                                            #
# --------------------------------------------------------------------------- #


@oscal_processor(strict=False)
class PostgresReadProcessor(GenericProcessor):
    ALLOWED = [
        "driver",
        "queries",
        "connection_name",
    ]
    # OSCAL: runs queries through DriverPostgres and PostgresConnection; it holds no
    # access path, authenticator or transport setting of its own.
    OSCAL_CONTROLS: ClassVar[Tuple[str, ...]] = ()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.debug(
            msg=Event.Constructor.name,
            step=Event.Started.name,
            driver=getattr(getattr(self, "driver", None), "name", None),
            queries=len(getattr(self, "queries", []) or []),
        )

    def _get_uri(self, sql) -> str:
        source = getattr(self, "connection_name", None) or self.driver.name
        return "postgres://%s/%s" % (source, hash(sql))

    def _get_content(self, sql) -> pd.DataFrame:
        # The driver owns the connection, the SQL safety switches and the row
        # cap; the processor only decides which statements to run.
        frame = self.driver.read(sql)
        return frame if frame is not None else pd.DataFrame({})

    def create_generator(self) -> Generator[ITarget, None, None]:
        self.debug(msg=Event.Generate.name, step=Event.Started.name)

        try:
            Attribute.mandatory(self, "driver", IDriver, driver=self.driver)
            Attribute.mandatory(self, "queries", list, queries=self.queries)

            self.debug(
                msg=Event.Generate.name,
                driver=self.driver.name,
                queries=len(self.queries),
            )

            for sql in self.queries:
                self.debug(msg=Event.Generate.name, scope="item", sql=str(sql)[:120])
                uri = self._get_uri(sql=sql)
                try:
                    content = self._get_content(sql=sql).to_dict()

                    self.debug(
                        msg=Event.Generate.name,
                        scope="item",
                        no=self.cycle + 1,
                        uri=uri,
                        size=len(content),
                    )

                    facade: DocumentFacade = self.blackboard.create(  # type: ignore
                        caller=self,
                        uri=uri,
                        content=content,
                    )
                    yield facade

                except Exception as e:
                    error = f"Error: {str(e)} with {uri!r}"
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


# --------------------------------------------------------------------------- #
# endregion Processor                                                         #
# --------------------------------------------------------------------------- #
