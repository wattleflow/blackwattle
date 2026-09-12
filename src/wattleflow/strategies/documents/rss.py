# Module name: strategies/documents/rss.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from wattleflow.enums.filetype import FileType
from wattleflow.helpers.converters.rss import RssFeed
from .records import ReadDocumentRecords
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["ReadRssDocument"]

# --------------------------------------------------------------------------- #
# region Strategies                                                           #
# --------------------------------------------------------------------------- #


class ReadRssDocument(ReadDocumentRecords):
    """Read a stored RSS document; the feed travels with its channel."""

    CONTENT = RssFeed
    FILE_TYPE = FileType.RSS


# --------------------------------------------------------------------------- #
# endregion Strategies                                                        #
# --------------------------------------------------------------------------- #
