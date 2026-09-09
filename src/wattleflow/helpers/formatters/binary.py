# Module name: helpers/formatters/binary.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
Binary Formatter subclasses — serialise content into binary payloads.

Each Formatter only turns ``content`` into ``bytes``; file paths, FileStorage
and driver concerns stay out. Logic ported from DriverLocalStorage's
``_write_pdf`` / ``_write_pickle`` / ``_write_protobuf`` / ``_write_png``.
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import io
from typing import Any
from wattleflow.concrete.serialisation import GenericFormatter
from wattleflow.enums.imageformat import ImageFormat
from wattleflow.helpers.image_security import ImageSecurityGuard
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["PdfFormatter", "PickleFormatter", "ProtobufFormatter", "PngFormatter"]

# --------------------------------------------------------------------------- #
# region PdfFormatter                                                         #
# --------------------------------------------------------------------------- #


class PdfFormatter(GenericFormatter):
    """Pass-through for a final PDF payload produced upstream.

    Redaction, font handling and metadata stripping live in PdfConverter /
    the write strategy — this only validates and returns the bytes.
    """

    SUFFIX = ".pdf"

    def serialise(self, content: Any, **opts: Any) -> bytes:
        if not isinstance(content, (bytes, bytearray, memoryview)):
            raise TypeError(
                "PDF render expects bytes content from a strategy/converter; "
                f"got {type(content).__name__}"
            )
        return bytes(content)


# --------------------------------------------------------------------------- #
# endregion PdfFormatter                                                      #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region PickleFormatter                                                      #
# --------------------------------------------------------------------------- #


class PickleFormatter(GenericFormatter):
    SUFFIX = ".pkl"

    def serialise(self, content: Any, **opts: Any) -> bytes:
        import pickle

        return pickle.dumps(content, protocol=opts.get("protocol", pickle.HIGHEST_PROTOCOL))


# --------------------------------------------------------------------------- #
# endregion PickleFormatter                                                   #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region ProtobufFormatter                                                    #
# --------------------------------------------------------------------------- #


class ProtobufFormatter(GenericFormatter):
    SUFFIX = ".pb"

    def serialise(self, content: Any, **opts: Any) -> bytes:
        from wattleflow.helpers.protobuf import (
            encode_delimited_stream,
            resolve_message_class,
        )

        if not isinstance(content, list):
            raise TypeError(f"ProtobufFormatter: unsupported content type {type(content).__name__}")

        message_cls = opts.get("message_class") or resolve_message_class(opts.get("schema"))
        return encode_delimited_stream(content, message_cls)


# --------------------------------------------------------------------------- #
# endregion ProtobufFormatter                                                 #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region PngFormatter                                                         #
# --------------------------------------------------------------------------- #


class PngFormatter(GenericFormatter):
    """Serialise a PNG image, optionally applying PII redaction boxes.

    opts (all optional unless noted):
        source_path   : str   - origin file; read when content is not an
                                in-memory image. Required if no content
                                object is supplied.
        redact_boxes  : list[tuple[int, int, int, int]]
                              - (x0, y0, x1, y1) pixel rectangles filled with
                                opaque black to obscure PII.
        replacements  : list[tuple[tuple[int, int, int, int], str]]
                              - substitute strings drawn over the rectangles.
        strip_metadata: bool  - default True; removes EXIF/tEXt chunks.
        blackout      : bool  - default True; fill redact boxes with solid
                                black and draw replacements in white. If False,
                                fill boxes with white and draw text in black.
    """

    SUFFIX = ImageFormat.PNG.suffix

    def serialise(self, content: Any, **opts: Any) -> bytes:
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError as e:
            raise ModuleNotFoundError(
                "PIL library is missing. Add it manually: pip install Pillow"
            ) from e

        source_path = opts.get("source_path", None)
        redact_boxes = opts.get("redact_boxes", []) or []
        replacements = opts.get("replacements", []) or []
        strip_metadata = opts.get("strip_metadata", True)
        blackout = opts.get("blackout", True)

        box_fill = (0, 0, 0) if blackout else (255, 255, 255)
        text_fill = (255, 255, 255) if blackout else (0, 0, 0)

        if isinstance(content, Image.Image):
            image = content.copy()
        elif isinstance(content, (bytes, bytearray)):
            # safe_open_bytes blocks oversized payloads, format spoofing and
            # malformed streams before Pillow decodes pixel data.
            image = ImageSecurityGuard.safe_open_bytes(bytes(content), expected=(ImageFormat.PNG,))
        elif source_path:
            image = ImageSecurityGuard.safe_open(source_path, expected=(ImageFormat.PNG,))
        else:
            raise ValueError("PNG render requires in-memory image, bytes or source_path")

        image = image.convert("RGBA" if image.mode == "RGBA" else "RGB")

        draw = ImageDraw.Draw(image)

        # Tesseract bbox 'top' rides cap-line, missing the actual glyph ascender
        # (and our č/š/ž diacritics). Pad upward more than downward.
        _PAD_TOP_RATIO = 0.18
        _PAD_BOT_RATIO = 0.06

        def _pad_box(box):
            x0, y0, x1, y1 = box
            h = y1 - y0
            pad_t = max(2, int(h * _PAD_TOP_RATIO))
            pad_b = max(1, int(h * _PAD_BOT_RATIO))
            return (x0, max(0, y0 - pad_t), x1, y1 + pad_b)

        padded = [_pad_box(b) for b in redact_boxes]
        for pbox in padded:
            draw.rectangle(pbox, fill=box_fill)

        if replacements:

            def _pick_font(box_h: int):
                # Roughly 55% of box height; clamped so labels stay legible
                # without overflowing in narrow OCR cells.
                target = max(7, min(int(box_h * 0.55), 16))
                try:
                    return ImageFont.truetype("DejaVuSans.ttf", size=target)
                except (OSError, IOError):
                    try:
                        return ImageFont.load_default(size=target)
                    except TypeError:
                        return ImageFont.load_default()

            pad_map = {tuple(rb): pb for rb, pb in zip(redact_boxes, padded, strict=True)}
            for raw_box, text in replacements:
                if not text:
                    continue
                x0, y0, x1, y1 = pad_map.get(tuple(raw_box), _pad_box(raw_box))
                font = _pick_font(y1 - y0)
                try:
                    tx0, ty0, tx1, ty1 = font.getbbox(str(text))
                    th = ty1 - ty0
                except AttributeError:
                    th = y1 - y0
                cx = x0 + 2
                cy = y0 + max(0, ((y1 - y0) - th) // 2)
                draw.text((cx, cy), str(text), fill=text_fill, font=font)

        save_kwargs: dict = {"format": "PNG", "optimize": True}
        if strip_metadata:
            # Writing without pnginfo discards all ancillary chunks (tEXt, iTXt,
            # zTXt, eXIf) — required for forensically clean redaction output.
            save_kwargs["pnginfo"] = None

        buf = io.BytesIO()
        image.save(buf, **save_kwargs)
        return buf.getvalue()


# --------------------------------------------------------------------------- #
# endregion PngFormatter                                                      #
# --------------------------------------------------------------------------- #
