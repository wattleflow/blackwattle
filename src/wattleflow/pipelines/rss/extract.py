# Module name: pipelines/rss/extract.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from pathlib import Path
from typing import Any
from wattleflow.enums.filetype import FileType
from wattleflow.helpers.parsers.text import RssParser
from wattleflow.pipelines.xml.extract import PipelineXMLExtract
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["PipelineRSSExtract"]

# --------------------------------------------------------------------------- #
# region Pipelines                                                            #
# --------------------------------------------------------------------------- #


class PipelineRSSExtract(PipelineXMLExtract):
    """Read one RSS feed; an RSS target keeps the channel, any other format takes the items."""

    ALLOWED = ["format"]

    def read(self, source: Path) -> Any:
        feed = RssParser().parse(path=source)
        return feed if self.file_type is FileType.RSS else feed.items


# --------------------------------------------------------------------------- #
# endregion Pipelines                                                         #
# --------------------------------------------------------------------------- #
