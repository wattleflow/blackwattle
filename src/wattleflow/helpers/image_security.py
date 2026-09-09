# Module name: helpers/image_security.py
# Author: (wattleflow@outlook.com)
# Copyright: 2022-2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

"""
Defensive image loader. Mitigates known image-based attacks against the
Pillow + Tesseract pipelines used by the redaction workflows:

    - decompression bombs (small file, huge pixmap),
    - format spoofing / polyglots (.png that is actually GIF, BMP, SVG, ...),
    - truncated or malformed streams,
    - oversized inputs aimed at OCR / Tika DoS,
    - path traversal when an upstream caller controls source_path.
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations

import io
from pathlib import Path
from wattleflow.enums.imageformat import ImageFormat

try:
    from PIL import Image, ImageFile
except Exception as e:
    raise ModuleNotFoundError(
        f"Pillow package is required to run this code.[{str(e)}\n"
        "Please install it with `pip install Pillow`"
    ) from e

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #

SAFE_MAX_PIXELS: int = 64 * 1024 * 1024
SAFE_MAX_BYTES: int = 50 * 1024 * 1024

# The signatures this guard checks live with the formats they identify, in
# `enums.imageformat` — a guard applies a vocabulary, it does not own one.

# Refuse truncated decoders globally; tighten Pillow's pixel cap.
ImageFile.LOAD_TRUNCATED_IMAGES = False
Image.MAX_IMAGE_PIXELS = SAFE_MAX_PIXELS

# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Exceptions                                                           #
# --------------------------------------------------------------------------- #


class ImageSecurityError(ValueError):
    pass


# --------------------------------------------------------------------------- #
# endregion Exceptions                                                        #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Classes                                                              #
# --------------------------------------------------------------------------- #


class ImageSecurityGuard:
    @classmethod
    def _within(cls, path: Path, base: Path | None) -> bool:
        if base is None:
            return True
        try:
            return path.is_relative_to(base.resolve())
        except (ValueError, OSError):
            return False

    @classmethod
    def safe_open(
        cls,
        path: str | Path,
        expected: tuple[str | ImageFormat, ...] | None = None,
        max_bytes: int = SAFE_MAX_BYTES,
        base_dir: str | Path | None = None,
    ) -> Image.Image:
        """Return a Pillow Image only after the file passes every check.

        `expected` accepts ImageFormat members or their names; it defaults to
        PNG only. Pass base_dir to confine the resolved path to a trusted
        directory; useful when source_path comes through a strategy / facade
        boundary.
        """
        formats = ImageFormat.resolve(expected)
        p = Path(path).resolve(strict=True)

        if base_dir is not None and not cls._within(p, Path(base_dir)):
            raise ImageSecurityError(f"path outside base_dir: {p}")

        size = p.stat().st_size
        if size > max_bytes:
            raise ImageSecurityError(f"image too large: {size} > {max_bytes}")
        if size == 0:
            raise ImageSecurityError(f"empty file: {p}")

        with p.open("rb") as fh:
            head = fh.read(16)
        cls._check_magic(head, formats, subject=p.name)

        # verify() consumes the stream, so probe once then reopen for real use.
        with Image.open(p) as probe:
            probe.verify()
            cls._check_format(probe.format, formats)

        image = Image.open(p)
        image.load()
        return image

    @classmethod
    def safe_open_bytes(
        cls,
        data: bytes,
        expected: tuple[str | ImageFormat, ...] | None = None,
        max_bytes: int = SAFE_MAX_BYTES,
    ) -> Image.Image:
        """Same guarantees as safe_open() but for in-memory payloads.

        v0.0.1.11: `cls` was missing from the signature, so the classmethod
        bound the class to `data` and every call raised TypeError before a
        single check ran — the whole OCR path went through here.
        """
        formats = ImageFormat.resolve(expected)

        if not data:
            raise ImageSecurityError("empty payload")
        if len(data) > max_bytes:
            raise ImageSecurityError(f"image too large: {len(data)} > {max_bytes}")
        cls._check_magic(data, formats, subject="payload")

        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
            cls._check_format(probe.format, formats)

        image = Image.open(io.BytesIO(data))
        image.load()
        return image

    @staticmethod
    def _check_magic(head: bytes, formats: tuple[ImageFormat, ...], subject: str) -> None:
        if not any(fmt.matches(head) for fmt in formats):
            raise ImageSecurityError(f"magic-byte mismatch for {subject}")

    @staticmethod
    def _check_format(found: str | None, formats: tuple[ImageFormat, ...]) -> None:
        """The decoder's verdict must agree with the signature — a polyglot
        passes the magic check of one format and decodes as another."""
        if ImageFormat.parse(found) not in formats:
            names = ", ".join(fmt.name for fmt in formats)
            raise ImageSecurityError(f"format {found} not in ({names})")


# --------------------------------------------------------------------------- #
# endregion Classes                                                           #
# --------------------------------------------------------------------------- #


__all__ = ["SAFE_MAX_PIXELS", "SAFE_MAX_BYTES", "ImageSecurityError", "ImageSecurityGuard"]
