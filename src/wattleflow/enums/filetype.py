# Module name: enums/filetype.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
Description: This module provides utilities for detecting file types from URI
extensions and raw byte content using magic signatures and content heuristics.
Supports files downloaded from the web or read from local disk.
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import io
import re
from enum import Enum, auto
from wattleflow.enums.imageformat import ImageFormat
from pathlib import Path
from urllib.parse import urlparse
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #
# Module-level constants — defined here to avoid Enum member pollution
# OLE2 Compound Document header shared by legacy .xls and .doc files
_OLE2_MAGIC: bytes = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
# Compiled pattern for log-line recognition (reused across calls)
_LOG_RE: re.Pattern[str] = re.compile(
    r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})"  # ISO-8601 timestamp
    r"|\[?(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL|FATAL)\]?"  # log level keyword
    r"|\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}",  # US date + time
    re.IGNORECASE,
)
# Extension → FileType mapping. Raster extensions are NOT listed here: they are
# derived from ImageFormat below the class, so the suffix per format is written
# down once for the whole distribution.
_EXT_MAP: dict[str, str] = {
    ".avro": "AVRO",
    ".csv": "CSV",
    ".doc": "DOC",
    ".docx": "DOCX",
    ".json": "JSON",
    ".jsonld": "GRAPH",
    ".log": "LOG",
    ".graph": "GRAPH",
    ".md": "MARKDOWN",
    ".markdown": "MARKDOWN",
    ".orc": "ORC",
    ".pb": "PROTOBUF",
    ".protobuf": "PROTOBUF",
    ".ttl": "GRAPH",
    ".n3": "GRAPH",
    ".nt": "GRAPH",
    ".pdf": "PDF",
    ".pkl": "PICKLE",
    ".pickle": "PICKLE",
    ".txt": "TXT",
    ".xls": "XLS",
    ".xlsx": "XLS",
}
# Apache Avro Object Container File — header magic "Obj\x01"
_AVRO_MAGIC: bytes = b"Obj\x01"
# Apache ORC — "ORC" at file start (writer-emitted) and again as the very
# last 3 bytes of the postscript (mandatory per ORC v1 spec).
_ORC_MAGIC: bytes = b"ORC"
# Markdown heuristics — ATX heading, fenced code block, setext underline.
_MD_RE: re.Pattern[str] = re.compile(
    r"(?m)^(#{1,6}\s+\S"  # ATX heading: '# foo'
    r"|```[\w]*$"  # fenced code block opener
    r"|[-=]{3,}\s*$)"  # setext underline
)
# Maximum bytes read from disk during content-based detection (prevents OOM)
_DETECT_MAX_BYTES: int = 50 * 1024 * 1024  # 50 MB
# XLS stream names encoded as UTF-16LE (present in OLE2 directory sectors)
_XLS_STREAM_UTF16: tuple[bytes, ...] = (
    b"W\x00o\x00r\x00k\x00b\x00o\x00o\x00k\x00",
    b"B\x00o\x00o\x00k\x00",
)
# DOC stream name encoded as UTF-16LE
_DOC_STREAM_UTF16: bytes = b"W\x00o\x00r\x00d\x00D\x00o\x00c\x00u\x00m\x00e\x00n\x00t\x00"
# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Helpers                                                              #
# --------------------------------------------------------------------------- #


class FileType(Enum):
    AVRO = auto()
    BMP = auto()
    CSV = auto()
    DOC = auto()
    DOCX = auto()
    DATAFRAME = auto()  # not detectable from content — assigned externally by callers
    GIF = auto()
    JPEG = auto()
    JSON = auto()
    LOG = auto()
    GRAPH = auto()
    MARKDOWN = auto()
    ORC = auto()
    PDF = auto()
    PICKLE = auto()
    PROTOBUF = auto()
    PNG = auto()
    TIFF = auto()
    TXT = auto()
    XLS = auto()
    UNKNOWN = auto()

    @classmethod
    def detect(cls, uri: str) -> "FileType":
        """Detect FileType from a URI or file-system path.

        First attempts extension lookup (zero-I/O). If the extension is
        unrecognised *and* the URI points to a local file, falls back to
        content-based detection by reading the file from disk.
        Remote URLs with unknown extensions return UNKNOWN without I/O.

        Note: PROTOBUF and DATAFRAME have no magic header and are only
        recognised by extension (``.pb`` / ``.protobuf``) or by explicit
        caller assignment, respectively.
        """
        suffix = Path(urlparse(uri).path).suffix.lower()
        name = _EXT_MAP.get(suffix)
        result = cls[name] if name else cls.UNKNOWN
        if result is cls.UNKNOWN:
            path = Path(uri)
            if path.is_file():
                if path.stat().st_size > _DETECT_MAX_BYTES:
                    return cls.UNKNOWN
                result = cls.detect_content(path.read_bytes())
        return result

    @classmethod
    def detect_content(cls, data: bytes) -> "FileType":
        """Detect FileType from raw bytes using magic signatures and heuristics.

        Detection order:
          1. PDF      — %PDF magic header
          2. RASTER   — PNG / JPEG / TIFF / BMP / GIF signatures (see ImageFormat)
          3. AVRO     — Obj\\x01 magic
          4. ORC      — "ORC" at file start, or postscript tail
          5. OLE2     — legacy .xls / .doc (D0 CF 11 E0 …)
          6. OOXML    — ZIP-based .xlsx / .docx (PK\\x03\\x04)
          7. PICKLE   — protocol 2-5 magic (\\x80\\x02 … \\x80\\x05)
          8. GRAPH    — JSON-LD (@context), Turtle (@prefix/@base), N-Triples
          9. JSON     — UTF-8 starting with { or [
         10. MARKDOWN — heading / fenced code / setext heuristics
         11. LOG      — lines with timestamps / log-level keywords
         12. CSV      — consistent comma / semicolon / tab columns
         13. TXT      — any valid UTF-8 text
         14. UNKNOWN  — binary or unrecognised
        """
        if not data:
            return cls.UNKNOWN

        # --- Binary magic checks (fast, fixed-cost) ---

        if data[:4] == b"%PDF":
            return cls.PDF

        raster = cls._detect_raster(data)
        if raster is not None:
            return raster

        if data[:4] == _AVRO_MAGIC:
            return cls.AVRO

        # ORC: writer emits "ORC" at file start; the postscript also ends
        # with the magic. Checking both covers truncated reads of the head
        # and full reads where only the tail is canonical.
        if data[:3] == _ORC_MAGIC or data[-3:] == _ORC_MAGIC:
            return cls.ORC

        if cls.is_ole2(data):
            return cls._detect_ole2(data)

        if data[:4] == b"PK\x03\x04":
            return cls._detect_zip(data)

        # Pickle protocols 2–5: \x80 followed by protocol byte (0x02–0x05)
        if data[0:1] == b"\x80" and data[1:2] in (b"\x02", b"\x03", b"\x04", b"\x05"):
            return cls.PICKLE

        # --- Text-based heuristics ---
        return cls._detect_text(data)

    @classmethod
    def suffixes(cls, *types: "FileType") -> tuple[str, ...]:
        """Every suffix the named types are recognised by, in map order.

        The reverse of `detect`'s extension lookup, so a caller that filters
        sources by extension reads the answer off the same map detection uses
        instead of retyping the literals (NFRQ-ORG-08).
        """
        wanted = {member.name for member in types} or set(_EXT_MAP.values())
        return tuple(ext for ext, name in _EXT_MAP.items() if name in wanted)

    @classmethod
    def accepts(cls, suffix: str, *types: "FileType") -> bool:
        """Whether a file suffix belongs to one of the named types."""
        return str(suffix or "").lower() in cls.suffixes(*types)

    @classmethod
    def _detect_raster(cls, data: bytes) -> "FileType | None":
        """Raster format whose signature the payload opens with, or None.

        Iterates only the formats FileType actually declares, so the vocabulary
        and the detector cannot drift: adding a member above is enough to make
        both the magic check and the extension map recognise it.

        Uses `identifies`, not `matches`: this detector returns a verdict with
        no decoder behind it, and BMP's two-byte signature is not evidence on
        its own (ImageFormat.identifies).
        """
        for image in cls._raster_formats():
            if image.identifies(data):
                return cls[image.name]
        return None

    @classmethod
    def _raster_formats(cls) -> tuple[ImageFormat, ...]:
        """ImageFormat members this enum has a counterpart for."""
        return tuple(image for image in ImageFormat if image.name in cls.__members__)

    @classmethod
    def is_ole2(cls, data: bytes) -> bool:
        """True when the payload opens with the OLE2 Compound File signature.

        Exposed because the signature identifies a CONTAINER, not a file type:
        an Outlook .msg is OLE2 yet has no FileType member, so a caller that
        only needs "is this compound binary" cannot go through detect_content.
        Keeps the signature in one place."""
        return data[:8] == _OLE2_MAGIC

    @classmethod
    def _detect_ole2(cls, data: bytes) -> "FileType":
        """Distinguish XLS from DOC within an OLE2 Compound Document.

        OLE2 root directory entries begin at sector 0 (file offset 512).
        Each entry stores its name as UTF-16LE (max 32 UTF-16 code units).
        Scanning the first 4 KiB covers the root and first-level child
        directory entries in the vast majority of real-world files.
        """
        header = data[:4096]
        if any(marker in header for marker in _XLS_STREAM_UTF16):
            return cls.XLS
        if _DOC_STREAM_UTF16 in header:
            return cls.DOC
        # Fallback — XLS is the most common OLE2 type in data pipelines
        return cls.XLS

    @classmethod
    def _detect_zip(cls, data: bytes) -> "FileType":
        """Identify OOXML sub-type (.xlsx / .docx) from ZIP central directory.
        Uses infolist() iteration with early exit so that ZIP archives with
        a large number of entries (potential zip-list exhaustion) are handled
        safely without loading the full name list into memory.
        """
        import zipfile

        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for info in zf.infolist():
                    if info.filename.startswith("xl/"):
                        return cls.XLS
                    if info.filename.startswith("word/"):
                        return cls.DOCX
        except Exception:  # BadZipFile, EOFError, ValueError, etc.
            pass
        return cls.UNKNOWN

    @classmethod
    def _detect_text(cls, data: bytes) -> "FileType":
        """Detect text-based types: GRAPH, JSON, LOG, CSV, TXT.

        Reads at most 8 KiB to keep detection fast for large files.
        Binary data that cannot be decoded as strict UTF-8 returns UNKNOWN.
        """
        try:
            # utf-8-sig strips the UTF-8 BOM (\xef\xbb\xbf) when present,
            # preventing it from corrupting stripped[0] checks below.
            text: str = data[:8192].decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError:
            return cls.UNKNOWN

        stripped: str = text.lstrip()
        if not stripped:
            return cls.UNKNOWN

        # --- JSON / JSON-LD ---
        if stripped[0] in ("{", "["):
            # JSON-LD: top-level object contains "@context" key.
            # Search the raw bytes for speed — avoids full JSON parse.
            if b'"@context"' in data[:1024]:
                return cls.GRAPH
            return cls.JSON

        # --- RDF Turtle / N3 / N-Triples ---
        prefix = stripped[:256].lower()
        if prefix.startswith(("@prefix", "@base")):
            return cls.GRAPH
        # N-Triples lines: <subject> <predicate> <object|literal> .
        if (
            stripped[0] == "<"
            and stripped.count("<") >= 2
            and stripped[: stripped.find("\n", 0, 512) + 1 or 512].rstrip().endswith(".")
        ):
            return cls.GRAPH

        lines: list[str] = [ln for ln in stripped.splitlines() if ln.strip()]

        # --- MARKDOWN ---
        # Checked before LOG so that headings (# ...) and fenced code blocks
        # are not mis-classified as log lines.
        if _MD_RE.search(text):
            return cls.MARKDOWN

        # --- LOG ---
        if cls._is_log(lines):
            return cls.LOG

        # --- CSV / TSV ---
        if len(lines) >= 2:
            ft = cls._detect_delimited(lines)
            if ft is not None:
                return ft

        return cls.TXT

    @classmethod
    def _is_log(cls, lines: list[str]) -> bool:
        """Return True if *lines* resemble structured log output.

        At least half of the sampled lines (min 2) must match a timestamp or
        log-level pattern to avoid false positives on regular prose text.
        """
        sample = lines[:20]
        if len(sample) < 2:
            return False
        hits = sum(1 for ln in sample if _LOG_RE.search(ln))
        return hits >= max(2, len(sample) // 2)

    @classmethod
    def _detect_delimited(cls, lines: list[str]) -> "FileType | None":
        """Return FileType.CSV if content uses a consistent delimiter, else None.

        Checks comma, semicolon, and tab in that order. A format is considered
        consistent when all sampled rows share the same delimiter count (allowing
        one count difference to tolerate a trailing delimiter or quoted fields).
        """
        for delimiter in (",", ";", "\t"):
            counts = [ln.count(delimiter) for ln in lines[:10]]
            if counts[0] > 0 and len(set(counts)) <= 2:
                return cls.CSV
        return None


# Raster extensions are derived, never retyped: ImageFormat owns the suffix per
# format, FileType owns which formats it recognises, and this line joins them
# once the members exist. A format without a member here keeps its suffixes out
# of the map by construction rather than by omission.
_EXT_MAP.update(
    {suffix: image.name for image in FileType._raster_formats() for suffix in image.suffixes}
)


# --------------------------------------------------------------------------- #
# endregion Helpers                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["FileType"]
