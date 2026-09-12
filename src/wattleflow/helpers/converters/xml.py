# Module name: helpers/converters/xml.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import pyexpat
import re
from typing import Any
from xml.etree import ElementTree as ET
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["XmlConverter"]

# --------------------------------------------------------------------------- #
# region XmlConverter                                                         #
# --------------------------------------------------------------------------- #


class XmlConverter:
    """Parse XML payloads, read elements by local name, and convert between XML and flat records."""

    # xml.etree never fetches external entities or DTDs; expat bounds entity expansion
    # from 2.4.1 and large tokens from 2.6.0 (Python docs, "XML vulnerabilities").
    EXPAT: tuple[int, int, int] = (2, 6, 0)
    # An XML Name without the namespace colon; element names from_records may write.
    NAME = re.compile(r"[A-Za-z_][\w.\-]*")
    SEPARATOR = "; "

    @classmethod
    def parse(cls, payload: bytes | str) -> ET.Element:
        """Root element of an XML payload; refused on an expat without expansion limits."""
        if pyexpat.version_info < cls.EXPAT:
            raise RuntimeError(f"{pyexpat.EXPAT_VERSION} predates the entity-expansion limits")
        return ET.fromstring(payload)

    @staticmethod
    def local(tag: str) -> str:
        """Tag name without its `{namespace}` prefix."""
        return tag.rpartition("}")[2]

    @classmethod
    def children(cls, element: ET.Element, name: str) -> list[ET.Element]:
        """Direct children carrying the given local name."""
        return [child for child in element if cls.local(child.tag) == name]

    @classmethod
    def to_records(cls, payload: bytes | str, record: str | None = None) -> list[dict[str, Any]]:
        """Flat records of a document: every element named `record`, else each child of the root."""
        root = cls.parse(payload)
        elements = [e for e in root.iter() if cls.local(e.tag) == record] if record else list(root)
        return [cls.flatten(element) for element in elements]

    @classmethod
    def from_records(
        cls,
        records: list[dict[str, Any]],
        root: str = "records",
        record: str = "record",
    ) -> str:
        """Records as an XML document; a dotted key becomes nested elements."""
        document = ET.Element(root)
        for fields in records:
            element = ET.SubElement(document, record)
            for key, value in fields.items():
                if value is not None:
                    cls.node(element, key).text = str(value)
        return ET.tostring(document, encoding="unicode", xml_declaration=True)

    @classmethod
    def flatten(cls, element: ET.Element, prefix: str = "") -> dict[str, Any]:
        """Text, attributes and descendants of an element as one flat record (dotted paths)."""
        record: dict[str, Any] = {}
        text = (element.text or "").strip()
        if text or not (len(element) or element.attrib):
            cls.put(record, prefix.rstrip(".") or cls.local(element.tag), text)
        for key, value in element.attrib.items():
            cls.put(record, f"{prefix}{cls.local(key)}", value)
        for child in element:
            for key, value in cls.flatten(child, f"{prefix}{cls.local(child.tag)}.").items():
                cls.put(record, key, value)
        return record

    @classmethod
    def put(cls, record: dict[str, Any], key: str, value: Any) -> None:
        """Set a field; a repeated one is joined into one value."""
        if key in record:
            value = cls.SEPARATOR.join(filter(None, (record[key], value)))
        record[key] = value

    @classmethod
    def node(cls, element: ET.Element, path: str) -> ET.Element:
        """The element at a dotted path below `element`, created where missing."""
        for part in path.split("."):
            if not cls.NAME.fullmatch(part):
                raise ValueError(f"not an XML element name: {part!r}")
            found = element.find(part)
            element = found if found is not None else ET.SubElement(element, part)
        return element


# --------------------------------------------------------------------------- #
# endregion XmlConverter                                                      #
# --------------------------------------------------------------------------- #
