# Module name: enums/mimetypes.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from enum import Enum
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Helpers                                                              #
# --------------------------------------------------------------------------- #


class MimeTypes(str, Enum):
    # --- Application ---------------------------------------------------------
    APPLICATION_JSON = "application/json"
    APPLICATION_LD_JSON = "application/ld+json"  # JSON-LD (produced by _write_graph)
    APPLICATION_PDF = "application/pdf"
    APPLICATION_XML = "application/xml"
    APPLICATION_ZIP = "application/zip"
    APPLICATION_OCTET_STREAM = "application/octet-stream"  # generic binary fallback
    APPLICATION_YOUTUBE_TRANSCRIPT = "application/vnd.youtube.transcript+json"
    APPLICATION_VND_MS_EXCEL = "application/vnd.ms-excel"  # XLS
    APPLICATION_VND_OPENXML_SPREADSHEET = (  # XLSX
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    # --- Text ----------------------------------------------------------------
    TEXT_CSV = "text/csv"
    TEXT_HTML = "text/html"
    TEXT_PLAIN = "text/plain"
    TEXT_TSV = "text/tab-separated-values"
    TEXT_XML = "text/xml"
    # --- RDF / Semantic Web --------------------------------------------------
    APPLICATION_RDF_XML = "application/rdf+xml"
    APPLICATION_N_TRIPLES = "application/n-triples"
    TEXT_TURTLE = "text/turtle"
    # --- Image ---------------------------------------------------------------
    IMAGE_BMP = "image/bmp"
    IMAGE_GIF = "image/gif"
    IMAGE_JPEG = "image/jpeg"
    IMAGE_PNG = "image/png"
    IMAGE_SVG = "image/svg+xml"
    IMAGE_TIFF = "image/tiff"
    IMAGE_WEBP = "image/webp"
    # --- Audio ---------------------------------------------------------------
    AUDIO_MPEG = "audio/mpeg"
    AUDIO_WAV = "audio/wav"
    AUDIO_OGG = "audio/ogg"
    # --- Video ---------------------------------------------------------------
    VIDEO_MP4 = "video/mp4"
    VIDEO_MPEG = "video/mpeg"
    VIDEO_WEBM = "video/webm"


# --------------------------------------------------------------------------- #
# endregion Helpers                                                           #
# --------------------------------------------------------------------------- #
