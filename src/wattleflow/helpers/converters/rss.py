# Module name: helpers/converters/rss.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import format_datetime, parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree as ET
from .xml import XmlConverter
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["RssConverter", "RssFeed"]

# --------------------------------------------------------------------------- #
# region RssConverter                                                         #
# --------------------------------------------------------------------------- #


@dataclass
class RssFeed:
    """An RSS channel and its items, each held as a flat record."""

    channel: dict[str, Any] = field(default_factory=dict)
    items: list[dict[str, Any]] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.items)


class RssConverter(XmlConverter):
    """RSS 0.9x/2.0 and RSS 1.0 (RDF) documents to flat records, and records to RSS 2.0."""

    ROOTS = ("rss", "RDF")
    VERSION = "2.0"
    CHANNEL = ("title", "link", "description", "language", "copyright", "pubDate", "lastBuildDate")
    ITEM = (
        "title", "link", "description", "author", "category",
        "comments", "guid", "pubDate", "source",
    )
    # RSS 2.0: a channel requires title, link and description; an enclosure all three attributes.
    REQUIRED = ("title", "link", "description")
    ENCLOSURE = ("url", "length", "type")
    DATES = ("pubDate", "lastBuildDate")
    # RSS 1.0 carries author and date in Dublin Core (dc:creator, dc:date).
    ALIASES = {"creator": "author", "date": "pubDate"}

    @classmethod
    def to_feed(cls, payload: bytes | str) -> RssFeed:
        """Channel and item records of an RSS document."""
        root = cls.parse(payload)
        if cls.local(root.tag) not in cls.ROOTS:
            raise ValueError(f"not an RSS document: <{cls.local(root.tag)}>")
        channels = cls.children(root, "channel")
        if not channels:
            raise ValueError("RSS document without <channel>")
        # RSS 2.0 nests the items inside <channel>; RSS 1.0 places them beside it.
        items = cls.children(channels[0], "item") or cls.children(root, "item")
        return RssFeed(
            channel=cls.record(channels[0], cls.CHANNEL),
            items=[cls.record(item, cls.ITEM) for item in items],
        )

    @classmethod
    def to_rss(cls, feed: RssFeed) -> str:
        """The feed as an RSS 2.0 document."""
        root = ET.Element("rss", version=cls.VERSION)
        channel = ET.SubElement(root, "channel")
        cls.fill(channel, feed.channel, cls.CHANNEL, cls.REQUIRED)
        for item in feed.items:
            cls.fill(ET.SubElement(channel, "item"), item, cls.ITEM)
        return ET.tostring(root, encoding="unicode", xml_declaration=True)

    @classmethod
    def record(cls, element: ET.Element, fields: tuple[str, ...]) -> dict[str, Any]:
        """Flat record of the named children; a repeated element is joined into one value."""
        record: dict[str, Any] = dict.fromkeys(fields)
        for child in element:
            name = cls.ALIASES.get(cls.local(child.tag), cls.local(child.tag))
            if name == "enclosure":
                record.update({f"{name}_{key}": child.get(key) for key in cls.ENCLOSURE})
            elif name in record:
                value = (child.text or "").strip()
                value = cls.iso(value) if name in cls.DATES else value
                cls.put(record, name, value)
        return record

    @classmethod
    def fill(
        cls,
        element: ET.Element,
        record: dict[str, Any],
        fields: tuple[str, ...],
        required: tuple[str, ...] = (),
    ) -> None:
        """Append a record's fields as child elements; an empty one only when required."""
        for name in fields:
            value = record.get(name)
            if not value and name not in required:
                continue
            if name == "category":
                for part in str(value).split(cls.SEPARATOR):
                    ET.SubElement(element, name).text = part
            else:
                text = cls.rfc822(value) if name in cls.DATES else str(value or "")
                ET.SubElement(element, name).text = text
        if record.get("enclosure_url"):
            attributes = {key: str(record.get(f"enclosure_{key}") or "") for key in cls.ENCLOSURE}
            ET.SubElement(element, "enclosure", attributes)

    @staticmethod
    def iso(value: str) -> str:
        """RFC 822 (RSS 2.0) or W3C-DTF (Dublin Core) date as ISO 8601; other text is kept."""
        for parse in (parsedate_to_datetime, datetime.fromisoformat):
            try:
                return parse(value).isoformat()
            except (TypeError, ValueError):
                continue
        return value

    @staticmethod
    def rfc822(value: Any) -> str:
        """ISO 8601 date (or datetime) as the RFC 822 date RSS 2.0 requires; other text is kept."""
        try:
            moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        except ValueError:
            return str(value)
        return format_datetime(moment)


# --------------------------------------------------------------------------- #
# endregion RssConverter                                                      #
# --------------------------------------------------------------------------- #
