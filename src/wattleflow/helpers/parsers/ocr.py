# Module name: helpers/parsers/ocr.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
OcrParser — read-side deserialiser that turns a raster image stream into an OCR
token stream (list of {"text", "conf", "bbox"}). pytesseract is lazy-imported in
``deserialise``; ``helpers.image_security.safe_open_bytes`` validates the
payload before Pillow decodes any pixel data.

Consumed by the OCR-driven reduction pipelines (``pipelines/entity/reduct.py``)
and reachable through ``PngParser(ocr=True)`` on the driver read path.
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from typing import Any, BinaryIO
from wattleflow.concrete.serialisation import GenericParser
from wattleflow.enums.imageformat import ImageFormat
from wattleflow.helpers.image_security import ImageSecurityGuard
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Types                                                                #
# --------------------------------------------------------------------------- #
Tokens = list[dict[str, Any]]
# --------------------------------------------------------------------------- #
# endregion Types                                                             #
# --------------------------------------------------------------------------- #

__all__ = ["OcrParser", "Tokens"]

# --------------------------------------------------------------------------- #
# region Parsers                                                              #
# --------------------------------------------------------------------------- #


class OcrParser(GenericParser):
    """OCR facade over pytesseract; shared by the OCR-driven reduction pipelines."""

    def deserialise(self, reader: BinaryIO, **opts: Any) -> Tokens:
        """Return pytesseract tokens with bounding boxes:
        {"text": str, "conf": int, "bbox": (x0, y0, x1, y1)}

        ``expected`` restricts the accepted image formats. Path confinement is
        no longer a parser concern — the driver resolves and sandboxes the path,
        and GenericParser hands over an open reader (DR-COR-015).
        """
        expected = ImageFormat.resolve(opts.pop("expected", None))

        try:
            import pytesseract
        except ImportError as e:
            raise ModuleNotFoundError(
                "pytesseract library is missing. Add it manually: pip install pytesseract"
            ) from e

        # safe_open_bytes enforces magic-byte, format and size checks before
        # Pillow decodes any pixel data, blocking decompression bombs and
        # polyglots.
        image = ImageSecurityGuard.safe_open_bytes(reader.read(), expected=expected)
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        tokens: Tokens = []
        count = len(data.get("text", []))
        for i in range(count):
            text = (data["text"][i] or "").strip()
            if not text:
                continue
            x = int(data["left"][i])
            y = int(data["top"][i])
            w = int(data["width"][i])
            h = int(data["height"][i])
            conf_raw = data.get("conf", ["-1"] * count)[i]
            try:
                conf = int(float(conf_raw))
            except (TypeError, ValueError):
                conf = -1
            tokens.append({"text": text, "conf": conf, "bbox": (x, y, x + w, y + h)})
        return tokens


# --------------------------------------------------------------------------- #
# endregion Parsers                                                           #
# --------------------------------------------------------------------------- #
