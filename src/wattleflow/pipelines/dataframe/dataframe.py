# Module name: pipelines/dataframe/dataframe.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region imports                                                              #
# --------------------------------------------------------------------------- #
from wattleflow.core import IProcessor, ITarget
from wattleflow.concrete import GenericPipeline
from wattleflow.enums.event import Event
from wattleflow.documents.dataframe import DataFrameDocument

try:
    import pandas as pd
except ImportError as e:
    raise ModuleNotFoundError(
        f"Missing required package to run this code: {__file__}.\n"
        "Please install it using:\n\tpip install pandas"
    ) from e

# --------------------------------------------------------------------------- #
# endregion imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Pipelines
# --------------------------------------------------------------------------- #


class PipelineDataFrameClean(GenericPipeline):
    def transform(
        self,
        processor: IProcessor,
        facade: ITarget,
        **kwargs,
    ) -> str | None:
        document: DataFrameDocument = facade.request()

        if not isinstance(document, DataFrameDocument):
            raise TypeError(f"Expected DataFrameDocument, found {type(document).__name__}")

        content: pd.DataFrame = document.content

        if not isinstance(content, pd.DataFrame):
            raise TypeError(
                f"Expected document.content to be pd.DataFrame, found {type(content).__name__}"
            )

        if content.empty:
            self.warning(
                msg=Event.Transform.name,
                step=Event.Check.name,
                reason="Nothing to process here!",
                document=document,
                size=content.size,
            )
            return None

        content = content.fillna("")
        document.update_content(content)
        uid = processor.blackboard.write(
            facade=facade,
            processor=processor,
            pipeline=self,
        )

        self.debug(
            msg=Event.Transform.name,
            step=Event.Completed.name,
            uid=uid,
            size=content.size,
        )

        return uid


# --------------------------------------------------------------------------- #
# endregion Pipelines
# --------------------------------------------------------------------------- #c
