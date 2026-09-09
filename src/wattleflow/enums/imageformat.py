# Module name: enums/imageformat.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
Raster formats the OCR and redaction paths accept.

One member carries the three facts that used to live as three separate maps in
three modules: the suffixes a format is stored under, the magic bytes that
identify it, and its MIME type. The member NAME is the Pillow format name
(`Image.format`), so a decoded image maps straight back with
`ImageFormat.parse(image.format)`.

Belongs to `enums` and not to `helpers/image_security.py` because it is a
VOCABULARY, not behaviour: the guard applies these facts, `WriteRedactedImage`
names an output suffix from them and the OCR pipeline filters sources by them.
A vocabulary that lives inside one of its consumers is a contract nobody owns
(NFRQ-ORG-01/04, CLAUDE.md §2.6).
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from enum import Enum
from wattleflow.enums.mimetypes import MimeTypes
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #
# Sizes a BMP DIB header is allowed to declare (BITMAPCOREHEADER through
# BITMAPV5HEADER). Used to confirm a bitmap whose two-byte signature is too
# short to stand on its own.
_DIB_HEADER_SIZES: frozenset[int] = frozenset({12, 40, 52, 56, 64, 108, 124})
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Formats                                                              #
# --------------------------------------------------------------------------- #
class ImageFormat(Enum):
    """(suffixes, magic, mime) per raster format.

    The FIRST suffix is canonical — the one a writer gives its output. That is
    why TIFF leads with `.tiff` and JPEG with `.jpg`: those were the values the
    format-to-suffix map carried before it was folded in here.
    """

    PNG = ((".png",), (b"\x89PNG\r\n\x1a\n",), MimeTypes.IMAGE_PNG)
    JPEG = ((".jpg", ".jpeg"), (b"\xff\xd8\xff",), MimeTypes.IMAGE_JPEG)
    # Little- and big-endian byte order marks.
    TIFF = ((".tiff", ".tif"), (b"II\x2a\x00", b"MM\x00\x2a"), MimeTypes.IMAGE_TIFF)
    BMP = ((".bmp",), (b"BM",), MimeTypes.IMAGE_BMP)
    GIF = ((".gif",), (b"GIF87a", b"GIF89a"), MimeTypes.IMAGE_GIF)

    def __init__(
        self,
        suffixes: tuple[str, ...],
        magic: tuple[bytes, ...],
        mime: MimeTypes,
    ) -> None:
        self.suffixes = suffixes
        self.magic = magic
        self.mime = mime

    @property
    def suffix(self) -> str:
        """Canonical output suffix for this format."""
        return self.suffixes[0]

    def matches(self, head: bytes) -> bool:
        """Whether a payload opens with one of this format's signatures.

        Signature only. Enough for a caller that decodes the payload afterwards
        and can act on the decoder's verdict — `ImageSecurityGuard` does exactly
        that. A caller with no second opinion wants `identifies`.
        """
        return any(head.startswith(signature) for signature in self.magic)

    def identifies(self, data: bytes) -> bool:
        """Whether a payload IS this format, with no decoder to fall back on.

        BMP is why this differs from `matches`: its signature is the two ASCII
        bytes "BM", which any prose beginning with those letters satisfies. A
        detector that returns a verdict on the signature alone would call
        `BMW,Audi` a bitmap. Every other accepted format carries at least three
        bytes and needs no confirmation.
        """
        if not self.matches(data):
            return False
        if self is type(self).BMP:
            return self._is_bitmap(data)
        return True

    @staticmethod
    def _is_bitmap(data: bytes) -> bool:
        """Confirm a bitmap by the DIB header size at offset 14."""
        if len(data) < 18:
            return False
        return int.from_bytes(data[14:18], "little") in _DIB_HEADER_SIZES

    # region Vocabulary

    @classmethod
    def extensions(cls) -> tuple[str, ...]:
        """Every suffix any accepted raster format is stored under."""
        return tuple(suffix for member in cls for suffix in member.suffixes)

    @classmethod
    def formats(cls) -> tuple[str, ...]:
        """Pillow format names of every accepted format."""
        return tuple(member.name for member in cls)

    @classmethod
    def accepts(cls, suffix: str) -> bool:
        """Whether a file suffix names an accepted raster format."""
        return str(suffix or "").lower() in cls.extensions()

    @classmethod
    def parse(cls, name: str | ImageFormat | None) -> ImageFormat | None:
        """Member for a Pillow format name; None when it is not accepted."""
        if isinstance(name, cls):
            return name
        try:
            return cls[str(name or "").upper()]
        except KeyError:
            return None

    @classmethod
    def from_suffix(cls, suffix: str) -> ImageFormat | None:
        """Member a file suffix belongs to; None when it is not accepted."""
        wanted = str(suffix or "").lower()
        return next((m for m in cls if wanted in m.suffixes), None)

    @classmethod
    def resolve(cls, values: tuple[str | ImageFormat, ...] | None) -> tuple[ImageFormat, ...]:
        """Normalise a caller's selection into members.

        Names arrive as strings from YAML configuration and as members from
        typed call sites; this is the single place that reconciles the two, so
        an unknown format fails here with the accepted list rather than silently
        matching nothing further down.
        """
        if not values:
            return (cls.PNG,)

        resolved: list[ImageFormat] = []
        for value in values:
            member = cls.parse(value)
            if member is None:
                raise ValueError(
                    f"unknown image format {value!r}; accepted: {', '.join(cls.formats())}"
                )
            if member not in resolved:
                resolved.append(member)
        return tuple(resolved)

    # endregion Vocabulary


# --------------------------------------------------------------------------- #
# endregion Formats                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["ImageFormat"]
