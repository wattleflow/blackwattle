# Module name: helpers/parsers/mail.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

"""Mail-family parser: RFC 5322 headers, MIME parts, address and date normalisation.

A facade over the stdlib `email` package that adds only what it lacks; parts are
read lazily. `GenericParser` owns the source side (FRQ-PTN-15.19).
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations

import json
import mimetypes
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import policy
from email.headerregistry import Address as StdAddress
from email.message import EmailMessage
from email import message_from_string
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from enum import Enum
from fnmatch import fnmatch
from functools import cached_property
from ipaddress import ip_address
from html import unescape
from types import MappingProxyType
from typing import Any, BinaryIO, ClassVar, Iterator, Mapping, Sequence

from wattleflow.enums.event import Event
from wattleflow.enums.filetype import FileType
from wattleflow.helpers.digest import FileDigest
from wattleflow.helpers.dtime import Zone
from wattleflow.concrete.serialisation import GenericParser, ParserError

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Message facade                                                       #
# --------------------------------------------------------------------------- #
GENERIC_TYPE: str = "application/octet-stream"

HTML_DROP_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
HTML_BREAK_RE = re.compile(r"</?(br|p|div|tr|li|h[1-6]|table|blockquote)\b[^>]*>", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
HTML_WS_RE = re.compile(r"[ \t]+\n")
BLANK_RUN_RE = re.compile(r"\n{3,}")
# OLE2 strings arrive NUL-terminated; tab and newline are kept for bodies.
OLE2_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# --------------------------------------------------------------------------- #
# region Headers                                                              #
# --------------------------------------------------------------------------- #
class MailHeader(str, Enum):
    """Headers this module reads, with their RFC 5322 §3.6 metadata."""

    FROM = ("from", "From", True)
    SENDER = ("sender", "Sender", True)  # the actual sender when From has >1
    REPLY_TO = ("reply_to", "Reply-To", False)
    TO = ("to", "To", True)
    CC = ("cc", "Cc", True)
    BCC = ("bcc", "Bcc", False)  # recipient trace stays out of content
    SUBJECT = ("subject", "Subject", True)
    DATE = ("date", "Date", True)

    MESSAGE_ID = ("message_id", "Message-ID", False)
    IN_REPLY_TO = ("in_reply_to", "In-Reply-To", False)
    REFERENCES = ("references", "References", False, False)

    RECEIVED = ("received", "Received", False, False)
    DELIVERY_DATE = ("delivery_date", "Delivery-Date", False)
    # Not unique: a forwarded message carries one per hop.
    RETURN_PATH = ("return_path", "Return-Path", False, False)

    # Non-standard, but the only record of the submitting client some gateways keep.
    ORIGINATING_IP = ("originating_ip", "X-Originating-IP", False)
    SENDER_IP = ("sender_ip", "X-Sender-IP", False)
    RECEIVED_SPF = ("received_spf", "Received-SPF", False, False)
    AUTH_RESULTS = ("auth_results", "Authentication-Results", False, False)

    def __new__(cls, name: str, header: str, rendered: bool, unique: bool = True):
        member = str.__new__(cls, name)
        member._value_ = name
        member.header = header
        member.rendered = rendered
        member.unique = unique
        return member

    @classmethod
    def rendered_fields(cls) -> tuple["MailHeader", ...]:
        """Headers entering the rendered block, in declaration order."""
        return tuple(header for header in cls if header.rendered)

    @classmethod
    def recipients(cls) -> tuple["MailHeader", ...]:
        return (cls.TO, cls.CC, cls.BCC)

    @classmethod
    def resolve(cls, name: str) -> "MailHeader | None":
        """Member by internal or RFC name, case-insensitively (.msg exports use both)."""
        return _HEADER_LOOKUP.get(str(name or "").strip().lower())


_HEADER_LOOKUP: dict[str, MailHeader] = {}
for _header in MailHeader:
    _HEADER_LOOKUP[_header.value.lower()] = _header
    _HEADER_LOOKUP[_header.header.lower()] = _header


class MailKeys:
    """Metadata keys one parsed message carries."""

    RAW_PREFIX: str = "msg_"
    DATE_SENT: str = "mail_date_sent"
    DATE_RECEIVED: str = "mail_date_received"
    DATE_SENT_UTC: str = "mail_date_sent_utc"
    DATE_SENT_UTC_ASSUMED: str = "mail_date_sent_utc_assumed"
    DATE_SENT_RAW: str = "mail_date_sent_raw"
    ZONE_SOURCE: str = "mail_date_zone_source"
    OFFSET_SECONDS: str = "mail_date_offset_seconds"
    ZONE_KNOWN: str = "mail_date_zone_known"
    SENDER: str = "mail_sender"
    SENDER_NAME: str = "mail_sender_name"
    AUTHORS: str = "mail_authors"
    RECIPIENT: str = "mail_recipient"
    RECIPIENTS: str = "mail_recipients"
    CC: str = "mail_cc"
    BCC: str = "mail_bcc"
    RECIPIENTS_ALL: str = "mail_recipients_all"
    MESSAGE_ID: str = "mail_message_id"
    ATTACHMENTS: str = "mail_attachments"
    ATTACHMENT_NAMES: str = "msg_attachments"
    HAS_ATTACHMENTS: str = "has_attachments"
    IS_ATTACHMENT: str = "is_attachment"
    ATTACHMENT_INDEX: str = "attachment_index"
    ATTACHMENT_NAME: str = "attachment_name"
    CONTENT_TYPE: str = "content_type"
    PAYLOAD: str = "payload"
    HOPS: str = "mail_hops"
    HOP_COUNT: str = "mail_hop_count"
    SERVERS: str = "mail_servers"
    IP_ADDRESSES: str = "mail_ip_addresses"
    ORIGINATING_IP: str = "mail_originating_ip"
    ATTACHMENT_COUNT: str = "mail_attachment_count"
    PARENT_SOURCE: str = "parent_source"
    # FILE: the container copy; CONTENT: the subject (dedup key); PARENT: a child's origin.
    FILE_DIGEST: str = "file_digest"
    CONTENT_DIGEST: str = "content_digest"
    PARENT_DIGEST: str = "parent_digest"
    DIGEST: str = "mail_digest"
    BODY_DIGEST: str = "mail_body_digest"
    IDENTITY_DIGEST: str = "mail_identity_digest"

    @classmethod
    def raw(cls, field_name: str) -> str:
        """Raw header key: "subject" -> "msg_subject"."""
        return f"{cls.RAW_PREFIX}{field_name}"


@dataclass(frozen=True, slots=True)
class MailAddress:
    """One address, local part and domain apart: only the domain is case-insensitive."""

    name: str = ""
    local: str = ""
    domain: str = ""

    @property
    def addr_spec(self) -> str:
        return f"{self.local}@{self.domain}" if self.local and self.domain else ""

    @property
    def key(self) -> str:
        """Deduplication key."""
        return f"{self.local}@{self.domain.lower()}"

    def __bool__(self) -> bool:
        return bool(self.addr_spec or self.name)

    @classmethod
    def _split_raw_addresses(cls, value: str) -> Iterator[tuple[str, str, str]]:
        """(name, local, domain) from a bare address list."""
        try:
            pairs = getaddresses([value], strict=True)  # type: ignore[call-arg]
        except TypeError:  # Python < 3.13 has no strict parameter
            pairs = getaddresses([value])
        for name, addr_spec in pairs:
            addr_spec = (addr_spec or "").strip()
            if "@" not in addr_spec:
                continue
            local, _, domain = addr_spec.rpartition("@")
            if not local or not domain:
                continue
            yield name or "", local, domain

    @classmethod
    def from_stdlib(cls, address: StdAddress) -> "MailAddress":
        return cls(
            name=(address.display_name or "").strip(),
            local=(address.username or "").strip(),
            domain=(address.domain or "").strip(),
        )

    @classmethod
    def from_text(cls, text: str) -> "MailAddress":
        """One address from a bare string; with no address, the string becomes the name."""
        raw = str(text or "").strip()
        if not raw:
            return cls()
        name, addr_spec = parseaddr(raw)
        if "@" in addr_spec:
            local, _, domain = addr_spec.rpartition("@")
            return cls(name=(name or "").strip(), local=local.strip(), domain=domain.strip())
        return cls(name=(name or raw).strip())

    @classmethod
    def parse(cls, value: Any) -> tuple["MailAddress", ...]:
        """Addresses from a header, in order, deduplicated by `key`."""
        if value is None:
            return ()

        parsed: list[MailAddress] = []
        structured = getattr(value, "addresses", None)
        if structured is not None:
            parsed = [cls.from_stdlib(item) for item in structured]
        else:
            parsed = [
                cls(
                    name=(name or "").strip(),
                    local=local.strip(),
                    domain=domain.strip(),
                )
                for name, local, domain in cls._split_raw_addresses(str(value))
            ]

        seen: set[str] = set()
        unique: list[MailAddress] = []
        for address in parsed:
            if not address.addr_spec:
                continue
            if address.key in seen:
                continue
            seen.add(address.key)
            unique.append(address)
        return tuple(unique)

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "address": self.addr_spec}


@dataclass(frozen=True, slots=True)
class MailMoment:
    """A time from the message, the raw text it came from, and whether its zone is known.

    `-0000` means "zone unknown" (RFC 5322 §4.3); obsolete zone names are flagged in
    `zone_source`.
    """

    value: datetime | None = None
    zone_known: bool = False
    raw: str = ""
    zone_source: str = ""  # "numeric" | "obsolete_name" | "unknown" | "iso" | "printed" | ""
    leap_second: bool = False

    # A trailing (comment) after an obsolete zone name is permitted by §3.3.
    OBSOLETE_ZONE_RE = re.compile(r"(?<![+\-\w])([A-Za-z]{1,5})\s*(?:\([^)]*\))?\s*$")
    # §3.3 permits :60; `datetime` cannot hold it, so it becomes :59 and is recorded.
    LEAP_SECOND_RE = re.compile(r"(\d{1,2}:\d{2}):60(?!\d)")

    @staticmethod
    def _zone_source(text: str) -> str:
        tail = text.strip()
        if re.search(r"[+-]\d{4}\s*(?:\([^)]*\))?\s*$", tail):
            return "unknown" if re.search(r"-0000\s*(?:\([^)]*\))?\s*$", tail) else "numeric"
        return "obsolete_name" if MailMoment.OBSOLETE_ZONE_RE.search(tail) else "unknown"

    #: Not `%B`: `strptime` reads month names through the process locale.
    MONTHS: ClassVar[Mapping[str, int]] = MappingProxyType(
        {
            name: number
            for number, full in enumerate(
                ("january february march april may june july august september october november december").split(),
                start=1,
            )
            for name in (full, full[:3])
        }
    )

    #: All-numeric forms are deliberately absent: `04/09/2026` is ambiguous.
    PRINTED_RE: ClassVar[re.Pattern[str]] = re.compile(
        r"""^\s*(?:[A-Za-z]+,\s*)?
            (?:
                (?P<day>\d{1,2})\s+(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})
              | (?P<month2>[A-Za-z]+)\s+(?P<day2>\d{1,2}),\s*(?P<year2>\d{4})
            )
            (?:\s+at)?\s+
            (?P<hour>\d{1,2}):(?P<minute>\d{2})(?::(?P<second>\d{2}))?
            (?:\s*(?P<meridiem>[AaPp])\.?[Mm]\.?)?\s*$""",
        re.VERBOSE,
    )

    @classmethod
    def from_printed(cls, raw: Any) -> "MailMoment":
        """A time a mail client printed on a page; its zone is always unknown."""
        text = str(raw or "").strip()
        match = cls.PRINTED_RE.match(text)
        if not match:
            return cls(None, False, text, "unknown")

        name = (match.group("month") or match.group("month2") or "").lower()
        month = cls.MONTHS.get(name)
        if month is None:
            return cls(None, False, text, "unknown")

        hour = int(match.group("hour"))
        meridiem = (match.group("meridiem") or "").lower()
        if meridiem == "p" and hour < 12:
            hour += 12
        elif meridiem == "a" and hour == 12:
            hour = 0
        if hour > 23:
            return cls(None, False, text, "unknown")

        try:
            value = datetime(
                int(match.group("year") or match.group("year2")),
                month,
                int(match.group("day") or match.group("day2")),
                hour,
                int(match.group("minute")),
                int(match.group("second") or 0),
            )
        except ValueError:
            return cls(None, False, text, "unknown")

        return cls(value, False, text, "printed")

    @classmethod
    def parse(cls, raw: Any) -> "MailMoment":
        """From a `MailMoment`, `datetime`, `DateHeader`, RFC 2822 or ISO string.

        RFC 2822 goes first: since 3.11 `fromisoformat` accepts bare digit runs.
        """
        if isinstance(raw, MailMoment):
            return raw
        if isinstance(raw, datetime):
            return cls(raw, raw.tzinfo is not None, raw.isoformat(), "iso")

        moment = getattr(raw, "datetime", None)
        if isinstance(moment, datetime):
            return cls(moment, moment.tzinfo is not None, str(raw), cls._zone_source(str(raw)))

        text = str(raw or "").strip()
        if not text:
            return cls()

        leap = False
        try:
            moment = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            moment = None
        if moment is None and cls.LEAP_SECOND_RE.search(text):
            leap = True
            try:
                moment = parsedate_to_datetime(cls.LEAP_SECOND_RE.sub(r"\1:59", text))
            except (TypeError, ValueError, OverflowError):
                moment = None
        if isinstance(moment, datetime):
            return cls(moment, moment.tzinfo is not None, text, cls._zone_source(text), leap)

        # ISO fallback for values this module wrote; guarded against bare digit runs.
        if "-" in text and ":" in text:
            try:
                moment = datetime.fromisoformat(text)
            except (TypeError, ValueError, OverflowError):
                moment = None
            if isinstance(moment, datetime):
                return cls(moment, moment.tzinfo is not None, text, "iso")
        return cls(raw=text)

    @property
    def utc(self) -> datetime | None:
        """Aware UTC; an unknown zone is assumed to be UTC (see `utc_evidential`)."""
        if self.value is None:
            return None
        if self.value.tzinfo is None:
            return self.value.replace(tzinfo=timezone.utc)
        return self.value.astimezone(timezone.utc)

    @property
    def utc_evidential(self) -> datetime | None:
        """UTC only when the message stated a zone, otherwise None."""
        if self.value is None or self.value.tzinfo is None:
            return None
        return self.value.astimezone(timezone.utc)

    @property
    def offset_seconds(self) -> int | None:
        if self.value is None or self.value.utcoffset() is None:
            return None
        return int(self.value.utcoffset().total_seconds())

    def in_zone(self, zone: str | None = None, *, assume: str = "UTC") -> datetime | None:
        """The moment seen from `zone`, the machine's own when unnamed.

        An unstated zone is read as `assume`: UTC, per RFC 5322 §3.3 `-0000`.
        """
        if self.value is None:
            return None
        return Zone.convert(self.value, zone, default=assume)

    def isoformat(self) -> str:
        return self.value.isoformat() if self.value is not None else ""

    def utc_isoformat(self, *, evidential: bool = True) -> str:
        moment = self.utc_evidential if evidential else self.utc
        return moment.isoformat() if moment is not None else ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "parsed": self.isoformat(),
            "utc": self.utc_isoformat(),
            "utc_assumed": self.utc_isoformat(evidential=False),
            "zone_known": self.zone_known,
            "zone_source": self.zone_source,
            "leap_second": self.leap_second,
            "offset_seconds": self.offset_seconds,
        }

    def __bool__(self) -> bool:
        return self.value is not None


@dataclass(frozen=True, slots=True)
class MailHop:
    """One `Received` hop: who handed the message to whom, and when.

    Stamped by the accepting server, not the sender, so it is modelled as evidence.
    """

    index: int = 0
    from_host: str = ""
    from_ip: str = ""
    by_host: str = ""
    by_ip: str = ""
    protocol: str = ""
    moment: MailMoment = MailMoment()
    raw: str = ""

    # Anchored on a non-word boundary, not `\b`, so `envelope-from` is not read as `from`.
    FROM_RE = re.compile(r"(?<![-\w])from\s+([^\s(;]+)", re.IGNORECASE)
    BY_RE = re.compile(r"(?<![-\w])by\s+([^\s(;]+)", re.IGNORECASE)
    WITH_RE = re.compile(r"(?<![-\w])with\s+([A-Za-z0-9/_-]+)", re.IGNORECASE)
    BRACKET_RE = re.compile(
        r"\[(?:IPv6:)?\s*([0-9A-Fa-f:.]+(?:%[0-9A-Za-z._-]+)?)\s*\]"
        r"|\((?:IPv6:)?\s*([0-9A-Fa-f:.]+(?:%[0-9A-Za-z._-]+)?)\s*\)"
    )

    @staticmethod
    def address(text: str) -> str:
        """`text` as an IP address, validated rather than pattern-matched, or ""."""
        candidate = str(text or "").strip()
        if not candidate:
            return ""
        # In `[IPv6:2001:db8::1]` the brackets and the tag are syntax, not address.
        if candidate.startswith("[") and candidate.endswith("]"):
            candidate = candidate[1:-1].strip()
        if candidate.lower().startswith("ipv6:"):
            candidate = candidate[5:].strip()
        # An IPv6 zone identifier is local scope, not part of the address.
        candidate = candidate.split("%", 1)[0]
        try:
            return str(ip_address(candidate))
        except ValueError:
            return ""

    @classmethod
    def parse(cls, raw: Any, index: int = 0) -> "MailHop":
        """One `Received` value; never raises, as a broken trace is still evidence."""
        original = str(raw or "")
        text = " ".join(original.split())
        if not text:
            return cls(index=index, raw=original)

        # The timestamp is after the final `;` (RFC 5321 §4.4).
        head, _, when = text.rpartition(";")
        head = head or text
        moment = MailMoment.parse(when) if _ else MailMoment()

        from_match = cls.FROM_RE.search(head)
        by_match = cls.BY_RE.search(head)
        from_host = from_match.group(1).rstrip(".") if from_match else ""
        by_host = by_match.group(1).rstrip(".") if by_match else ""

        # A bracketed address before `by` is the sender's, after it the receiver's.
        boundary = by_match.start() if by_match else len(head)
        from_ip = by_ip = ""
        for found in cls.BRACKET_RE.finditer(head):
            address = cls.address(found.group(1) or found.group(2))
            if not address:
                continue
            if found.start() < boundary and not from_ip:
                from_ip = address
            elif found.start() >= boundary and not by_ip:
                by_ip = address

        # Some gateways put a bare address where a host name goes (`by 2002:a05:...`).
        for host_attr, ip_attr in (("from_host", "from_ip"), ("by_host", "by_ip")):  #  # ignore B007
            host = from_host if host_attr == "from_host" else by_host
            address = cls.address(host)
            if address:
                if host_attr == "from_host":
                    from_host, from_ip = "", from_ip or address
                else:
                    by_host, by_ip = "", by_ip or address

        protocol = cls.WITH_RE.search(head)
        return cls(
            index=index,
            from_host=from_host,
            from_ip=from_ip,
            by_host=by_host,
            by_ip=by_ip,
            protocol=protocol.group(1) if protocol else "",
            moment=moment,
            raw=original,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "from_host": self.from_host,
            "from_ip": self.from_ip,
            "by_host": self.by_host,
            "by_ip": self.by_ip,
            "protocol": self.protocol,
            "received_at": self.moment.isoformat(),
            "received_at_utc": self.moment.utc_isoformat(),
            "zone_known": self.moment.zone_known,
            "raw": " ".join(self.raw.split()),
        }

    def __bool__(self) -> bool:
        return bool(self.from_host or self.from_ip or self.by_host or self.by_ip)


@dataclass(frozen=True, slots=True)
class MailAttachment:
    """One attachment, digested over its content (never the name) so copies deduplicate."""

    name: str
    content_type: str = "application/octet-stream"
    payload: bytes = field(default=b"", repr=False)
    digest: str = ""
    inline: bool = False
    content_id: str = ""

    @property
    def size(self) -> int:
        return len(self.payload)

    @classmethod
    def build(
        cls,
        name: str,
        content_type: str,
        payload: bytes,
        *,
        inline: bool = False,
        content_id: str = "",
    ) -> "MailAttachment":
        data = bytes(payload)
        return cls(
            name=name,
            content_type=content_type or "application/octet-stream",
            payload=data,
            digest=FileDigest.labelled(data),
            inline=inline,
            content_id=content_id,
        )

    @classmethod
    def from_part(cls, part: EmailMessage, index: int) -> "MailAttachment | None":
        """The part as a record, or None when it has no decodable content.

        An attached `message/rfc822` is serialised and named after its subject.
        """
        content_type = part.get_content_type() or GENERIC_TYPE
        fallback = f"attachment-{index}"
        if content_type == "message/rfc822":
            payload, subject = cls._embedded(part)
            fallback = f"{subject or fallback}.eml"
        else:
            try:
                payload = part.get_payload(decode=True)
            except (LookupError, ValueError, TypeError):
                return None
        if not payload:
            return None

        name = str(part.get_filename() or "").strip() or fallback
        data = bytes(payload)
        return cls(
            name=name,
            content_type=content_type,
            payload=data,
            digest=FileDigest.labelled(data),
            inline=part.get_content_disposition() == "inline",
            content_id=str(part.get("Content-ID", "") or "").strip("<> "),
        )

    #: The stdlib keeps no raw bytes of a sub-part; rewrite unfolded, with CRLF.
    EMBEDDED_POLICY: ClassVar[Any] = policy.default.clone(max_line_length=0, linesep="\r\n")
    UNSAFE_NAME_RE: ClassVar[re.Pattern[str]] = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
    MAX_NAME: ClassVar[int] = 120

    @classmethod
    def _embedded(cls, part: EmailMessage) -> tuple[bytes, str]:
        """An attached message as bytes, and its subject made safe for a filename."""
        try:
            inner = part.get_content()
            data = inner.as_bytes(policy=cls.EMBEDDED_POLICY)
        except Exception:  # noqa: BLE001 — one broken part must not cost the message
            return b"", ""
        subject = cls.UNSAFE_NAME_RE.sub(" ", str(inner.get("Subject", "") or ""))
        return data, " ".join(subject.split()).strip(". ")[: cls.MAX_NAME].strip()

    def as_dict(self, with_payload: bool = False) -> dict[str, Any]:
        record: dict[str, Any] = {
            "name": self.name,
            MailKeys.CONTENT_TYPE: self.content_type,
            "size": self.size,
            "digest": self.digest,
            "inline": self.inline,
            "content_id": self.content_id,
        }
        if with_payload:
            record[MailKeys.PAYLOAD] = self.payload
        return record


# --------------------------------------------------------------------------- #
# region Envelope                                                             #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class MailEnvelope:
    """Parties and dates, with `From` and `Sender` kept apart (RFC 5322 §3.6.2)."""

    authors: tuple[MailAddress, ...] = ()
    sender: MailAddress | None = None
    to: tuple[MailAddress, ...] = ()
    cc: tuple[MailAddress, ...] = ()
    bcc: tuple[MailAddress, ...] = ()
    date_sent: MailMoment = MailMoment()
    date_received: MailMoment = MailMoment()
    message_id: str = ""

    @property
    def originator(self) -> MailAddress | None:
        """`Sender` when present, else the first `From`."""
        if self.sender is not None and self.sender.addr_spec:
            return self.sender
        return self.authors[0] if self.authors else None

    @property
    def everyone(self) -> tuple[MailAddress, ...]:
        """To + Cc + Bcc, in order, deduplicated by `MailAddress.key`."""
        seen: set[str] = set()
        result: list[MailAddress] = []
        for group in (self.to, self.cc, self.bcc):
            for address in group:
                if address.key in seen:
                    continue
                seen.add(address.key)
                result.append(address)
        return tuple(result)

    def as_metadata(self) -> dict[str, Any]:
        """The envelope as JSON-serialisable `MailKeys.*` values."""
        originator = self.originator or MailAddress()
        recipients = [address.addr_spec for address in self.to]
        return {
            MailKeys.DATE_SENT: self.date_sent.isoformat(),
            MailKeys.DATE_RECEIVED: (self.date_received or self.date_sent).isoformat(),
            # Only when the zone was stated; an assumed UTC goes in the next key.
            MailKeys.DATE_SENT_UTC: self.date_sent.utc_isoformat(),
            MailKeys.DATE_SENT_UTC_ASSUMED: self.date_sent.utc_isoformat(evidential=False),
            MailKeys.DATE_SENT_RAW: self.date_sent.raw,
            MailKeys.ZONE_KNOWN: self.date_sent.zone_known,
            MailKeys.ZONE_SOURCE: self.date_sent.zone_source,
            MailKeys.OFFSET_SECONDS: self.date_sent.offset_seconds,
            MailKeys.SENDER: originator.addr_spec,
            MailKeys.SENDER_NAME: originator.name,
            MailKeys.AUTHORS: [address.addr_spec for address in self.authors],
            MailKeys.RECIPIENT: recipients[0] if recipients else "",
            MailKeys.RECIPIENTS: recipients,
            MailKeys.CC: [address.addr_spec for address in self.cc],
            MailKeys.BCC: [address.addr_spec for address in self.bcc],
            MailKeys.RECIPIENTS_ALL: [address.addr_spec for address in self.everyone],
            MailKeys.MESSAGE_ID: self.message_id,
        }


@dataclass(frozen=True)
class MailMessage:
    """One message, its parts computed lazily on first access."""

    message: EmailMessage | None = field(default=None, repr=False)
    raw_headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    given_body: str | None = field(default=None, repr=False)
    given_attachments: tuple[MailAttachment, ...] | None = field(default=None, repr=False)

    # region Constructors
    @classmethod
    def from_stream(cls, reader: BinaryIO) -> "MailMessage":
        """Neither opens nor closes the source."""
        return cls(message=BytesParser(policy=policy.default).parse(reader))

    @classmethod
    def from_bytes(cls, data: bytes) -> "MailMessage":
        return cls(message=BytesParser(policy=policy.default).parsebytes(data))

    @classmethod
    def from_header_block(
        cls,
        block: str,
        body: str = "",
        attachments: Sequence[MailAttachment] = (),
    ) -> "MailMessage":
        """A message from a raw RFC header block, with body and attachments given.

        The block is re-read through `policy.default` for unfolding and encoded words.
        """
        return cls(
            message=message_from_string(block, policy=policy.default),
            given_body=body,
            given_attachments=tuple(attachments),
        )

    @classmethod
    def from_parts(
        cls,
        headers: Mapping[str, Any],
        body: str = "",
        attachments: Sequence[MailAttachment] = (),
    ) -> "MailMessage":
        """Entry point for the .msg reader; keys may be internal or RFC names."""
        normalised: dict[str, str] = {}
        for key, value in headers.items():
            header = MailHeader.resolve(str(key))
            if header is not None:
                normalised[header.value] = str(value or "").strip()
        return cls(
            raw_headers=normalised,
            given_body=body,
            given_attachments=tuple(attachments),
        )

    # endregion Constructors

    # region Private
    def _strip_html(self, html: str) -> str:
        """An HTML body as text, with script and style content dropped."""
        text = HTML_DROP_RE.sub(" ", str(html or ""))
        text = HTML_BREAK_RE.sub("\n", text)
        text = HTML_TAG_RE.sub(" ", text)
        text = unescape(text)
        text = text.replace("\xa0", " ")
        text = HTML_WS_RE.sub("\n", text)
        return BLANK_RUN_RE.sub("\n\n", text).strip()

    # endregion Private

    # region Access
    def header(self, name: MailHeader) -> Any:
        """Structured header from bytes, a string from parts, or None when absent."""
        if self.message is not None:
            return self.message.get(name.header)
        return self.raw_headers.get(name.value) or None

    def text(self, name: MailHeader) -> str:
        """The header as a decoded string; "" when absent."""
        value = self.header(name)
        return str(value).strip() if value is not None else ""

    def all_headers(self, name: MailHeader) -> tuple[str, ...]:
        """Every occurrence — meaningful only for `unique=False` (Received)."""
        if self.message is None:
            value = self.raw_headers.get(name.value)
            return (value,) if value else ()
        return tuple(str(item) for item in self.message.get_all(name.header, []))

    def addresses(self, name: MailHeader) -> tuple[MailAddress, ...]:
        return MailAddress.parse(self.header(name))

    @cached_property
    def raw(self) -> dict[str, Any]:
        """Every declared header by internal name; non-unique ones keep all occurrences."""
        values: dict[str, Any] = {}
        for header in MailHeader:
            if header.unique:
                values[header.value] = self.text(header)
            else:
                found = self.all_headers(header)
                if found:
                    values[header.value] = list(found)
        return values

    def party(self, name: MailHeader) -> tuple[MailAddress, ...]:
        """As `addresses`, falling back to a lone display name (.msg exports)."""
        found = self.addresses(name)
        if found:
            return found
        lone = MailAddress.from_text(self.text(name))
        return (lone,) if lone else ()

    @cached_property
    def envelope(self) -> MailEnvelope:
        sender_field = self.party(MailHeader.SENDER)
        return MailEnvelope(
            authors=self.party(MailHeader.FROM),
            sender=sender_field[0] if sender_field else None,
            to=self.addresses(MailHeader.TO),
            cc=self.addresses(MailHeader.CC),
            bcc=self.addresses(MailHeader.BCC),
            date_sent=MailMoment.parse(self.header(MailHeader.DATE)),
            date_received=self.received_at,
            message_id=self.text(MailHeader.MESSAGE_ID),
        )

    @cached_property
    def received_at(self) -> MailMoment:
        """Topmost `Received` stamp, else `Delivery-Date`, else the send time."""
        hops = self.all_headers(MailHeader.RECEIVED)
        if hops:
            moment = MailMoment.parse(hops[0].rsplit(";", 1)[-1])
            if moment:
                return moment

        moment = MailMoment.parse(self.header(MailHeader.DELIVERY_DATE))
        if moment:
            return moment
        return MailMoment.parse(self.header(MailHeader.DATE))

    @cached_property
    def body(self) -> str:
        """The body as text: `text/plain` if it has content, else stripped `text/html`.

        Content is tested, not presence: alternatives often carry an empty plain part.
        """
        if self.given_body is not None:
            return self.given_body.strip()
        if self.message is None:
            return ""

        try:
            plain = self.message.get_body(preferencelist=("plain",))
            if plain is not None:
                text = str(plain.get_content() or "").strip()
                if text:
                    return text

            html = self.message.get_body(preferencelist=("html",))
            if html is not None:
                text = self._strip_html(str(html.get_content() or ""))
                if text:
                    return text
        except (LookupError, ValueError, TypeError, AttributeError):
            return ""
        return ""

    @cached_property
    def attachments(self) -> tuple[MailAttachment, ...]:
        if self.given_attachments is not None:
            return self.given_attachments
        if self.message is None:
            return ()

        try:
            parts = list(self.message.iter_attachments())
        except (AttributeError, TypeError, ValueError):
            return ()

        records: list[MailAttachment] = []
        for part in parts:
            record = MailAttachment.from_part(part, len(records) + 1)
            if record is not None:
                records.append(record)
        return tuple(records)

    @cached_property
    def defects(self) -> tuple[str, ...]:
        """`email.errors` defects across every part (NFRQ-OBS-01)."""
        if self.message is None:
            return ()
        found: list[str] = []
        for part in self.message.walk():
            for defect in getattr(part, "defects", ()):
                found.append(f"{type(defect).__name__}: {defect}")
        return tuple(found)

    # endregion Access

    # region Output
    def header_lines(self) -> list[str]:
        """Rendered fields under their RFC names; `Bcc` and the trace stay out."""
        lines: list[str] = []
        for header in MailHeader.rendered_fields():
            value = self.text(header)
            if value:
                lines.append(f"{header.header}: {value}")
        return lines

    def render(self) -> str:
        """Header block, attachment names and the message body."""
        lines = self.header_lines()
        names = [attachment.name for attachment in self.attachments]
        if names:
            lines.append(f"Attachments: {', '.join(names)}")

        content = "\n".join(lines)
        if not self.body:
            return content
        return f"{content}\n\n{self.body}" if content else self.body

    @cached_property
    def hops(self) -> tuple[MailHop, ...]:
        """The transport trace, origin first (the reverse of header order)."""
        raw = self.all_headers(MailHeader.RECEIVED)
        return tuple(MailHop.parse(value, index) for index, value in enumerate(reversed(raw)))

    @cached_property
    def servers(self) -> tuple[str, ...]:
        """Host names along the route, origin first, each named once."""
        seen: dict[str, None] = {}
        for hop in self.hops:
            for host in (hop.from_host, hop.by_host):
                if host:
                    seen.setdefault(host.lower(), None)
        return tuple(seen)

    @cached_property
    def ip_addresses(self) -> tuple[str, ...]:
        """Addresses along the route, origin first, each named once."""
        seen: dict[str, None] = {}
        for hop in self.hops:
            for address in (hop.from_ip, hop.by_ip):
                if address:
                    seen.setdefault(address, None)
        for header in (MailHeader.ORIGINATING_IP, MailHeader.SENDER_IP):
            address = MailHop.address(self.text(header).strip("[] "))
            if address:
                seen.setdefault(address, None)
        return tuple(seen)

    @cached_property
    def originating_ip(self) -> str:
        """`X-Originating-IP` when recorded, else the first hop's sender; a claim, not proof."""
        declared = MailHop.address(self.text(MailHeader.ORIGINATING_IP).strip("[] "))
        if declared:
            return declared
        for hop in self.hops:
            if hop.from_ip:
                return hop.from_ip
        return ""

    def sent_at(self, zone: str | None = None) -> datetime | None:
        """The send time seen from `zone`; see `MailMoment.in_zone`."""
        return self.envelope.date_sent.in_zone(zone)

    @cached_property
    def identity(self) -> str:
        """The normalised fields that identify this message, canonically joined."""
        envelope = self.envelope
        originator = envelope.originator or MailAddress()
        sent = envelope.date_sent.utc
        return "\n".join(
            (
                envelope.message_id,
                sent.isoformat() if sent else "",
                originator.key,
                ",".join(sorted(address.key for address in envelope.everyone)),
                self.text(MailHeader.SUBJECT).strip(),
            )
        )

    @cached_property
    def digest(self) -> str:
        """Content digest of the message, not its container; part order is ignored."""
        return FileDigest.folded(
            [
                FileDigest.of(self.identity.encode("utf-8")),
                FileDigest.of(self.body.encode("utf-8")),
                *sorted(attachment.digest for attachment in self.attachments),
            ]
        )

    def as_metadata(self, with_payload: bool = False) -> dict[str, Any]:
        """The envelope, raw headers under `msg_*` and the attachment summary."""
        metadata: dict[str, Any] = {MailKeys.raw(name): value for name, value in self.raw.items() if value}
        metadata.update(self.envelope.as_metadata())
        metadata[MailKeys.ATTACHMENTS] = [attachment.as_dict(with_payload) for attachment in self.attachments]
        metadata[MailKeys.ATTACHMENT_NAMES] = [a.name for a in self.attachments]
        metadata[MailKeys.ATTACHMENT_COUNT] = len(self.attachments)
        metadata[MailKeys.HAS_ATTACHMENTS] = bool(self.attachments)
        metadata[MailKeys.HOPS] = [hop.as_dict() for hop in self.hops]
        metadata[MailKeys.HOP_COUNT] = len(self.hops)
        metadata[MailKeys.SERVERS] = list(self.servers)
        metadata[MailKeys.IP_ADDRESSES] = list(self.ip_addresses)
        metadata[MailKeys.ORIGINATING_IP] = self.originating_ip
        metadata[MailKeys.IDENTITY_DIGEST] = FileDigest.labelled(self.identity.encode("utf-8"))
        metadata[MailKeys.BODY_DIGEST] = FileDigest.labelled(self.body.encode("utf-8"))
        metadata[MailKeys.DIGEST] = self.digest
        return metadata

    def walk_attachments(self) -> Iterator[MailAttachment]:
        """Attachments one at a time, without building the cached tuple.

        OLE2 has no lazy path: its reader materialises every part on open.
        """
        if self.given_attachments is not None:
            yield from self.given_attachments
            return
        if self.message is None:
            return

        try:
            parts = self.message.iter_attachments()
        except (AttributeError, TypeError, ValueError):
            return

        index = 0
        for part in parts:
            record = MailAttachment.from_part(part, index + 1)
            if record is not None:
                index += 1
                yield record

    def __iter__(self) -> Iterator[MailAttachment]:
        return self.walk_attachments()

    # endregion Output


# --------------------------------------------------------------------------- #
# region MailParser                                                           #
# --------------------------------------------------------------------------- #
# region Print layouts                                                        #
# --------------------------------------------------------------------------- #
# A printed email keeps only the header block at the top of the page; position and
# contiguity, not labels alone, tell it from quoted mail (`FRQ-MAIL-02` §9).


#: Printed labels that are not RFC 5322 fields, mapped to the field they render.
PRINT_LABELS: Mapping[str, str | None] = MappingProxyType({"Sent": "Date", "Attachments": None})

#: Splits any printed `Label: value` line, expected label or not.
_LABEL_VALUE = re.compile(r"^\s*([A-Za-z][\w-]*)\s*:\s*(.*)$")

_ADDR_SPEC = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


@dataclass(frozen=True, slots=True)
class MailTemplate:
    """One client's print layout, declared as data.

    A template with only ``markers`` matches on those alone (footer-only webmail prints).
    """

    name: str
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    min_labels: int = 3
    start_within: int = 3
    require_address: bool = True
    markers: tuple[str, ...] = ()

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(self.required) + tuple(self.optional)

    # Not `cached_property`: __slots__ forbids it, and `re.compile` caches anyway.
    @property
    def label_pattern(self) -> re.Pattern[str] | None:
        if not self.labels:
            return None
        names = "|".join(re.escape(label) for label in self.labels)
        return re.compile(rf"^\s*({names})\s*:", re.IGNORECASE)

    @property
    def marker_pattern(self) -> re.Pattern[str] | None:
        if not self.markers:
            return None
        return re.compile("|".join(self.markers), re.IGNORECASE)

    @classmethod
    def defaults(cls) -> tuple["MailTemplate", ...]:
        """Layouts the module knows without configuration."""
        return (
            # Most specific first: the matching template's name is reported as the finding.
            cls(
                name="outlook-print",
                required=("From", "Subject", "Sent"),
                optional=("To", "Cc", "Bcc", "Attachments"),
                min_labels=3,
            ),
            cls(
                name="apple-mail-print",
                required=("From", "Subject", "Date", "To"),
                optional=("Cc", "Bcc"),
                min_labels=4,
            ),
            cls(
                name="rfc-header-block",
                required=("From", "To"),
                optional=("Subject", "Date", "Cc", "Reply-To", "Message-ID", "Sent"),
                min_labels=3,
            ),
            cls(
                name="webmail-print",
                markers=(
                    r"mail\.google\.com",
                    r"outlook\.(office|live)\.com",
                    r"mail\.yahoo\.",
                ),
                min_labels=0,
                require_address=False,
            ),
        )


@dataclass(frozen=True, slots=True)
class MailHeaderBlock:
    """A header block found at the top of printed text, and how it was found."""

    template: str
    lines: tuple[str, ...]
    labels: tuple[str, ...]
    addresses: int
    start: int

    @property
    def text(self) -> str:
        """The block exactly as the page carried it — the evidence."""
        return "\n".join(self.lines)

    @property
    def rfc_text(self) -> str:
        """The block with print labels renamed to their RFC fields (`Sent:` -> `Date:`)."""
        renamed: list[str] = []
        for line in self.lines:
            hit = _LABEL_VALUE.match(line)
            if hit is None:
                renamed.append(line)
                continue
            label, value = hit.group(1), hit.group(2)
            for printed, rfc_name in PRINT_LABELS.items():
                if rfc_name and label.lower() == printed.lower():
                    label = rfc_name
                    break
            renamed.append(f"{label}: {value}")
        return "\n".join(renamed)

    @property
    def sent(self) -> MailMoment:
        """The send time as the page states it, read as printed before RFC.

        The stdlib reads `2:22 PM` as zone `PM` and returns 02:22, so the order matters.
        """
        for line in self.lines:
            hit = _LABEL_VALUE.match(line)
            if hit is None:
                continue
            label, value = hit.group(1).lower(), hit.group(2).strip()
            if label not in ("date", "sent") or not value:
                continue
            printed = MailMoment.from_printed(value)
            return printed if printed else MailMoment.parse(value)
        return MailMoment()

    @property
    def message(self) -> "MailMessage":
        """The block read through `MailMessage.from_header_block`."""
        return MailMessage.from_header_block(self.rfc_text)

    @property
    def subject(self) -> str:
        return (self.message.header(MailHeader.SUBJECT) or "").strip()

    def as_metadata(self) -> dict[str, Any]:
        """The finding, in the shape a document stamps."""
        found: dict[str, Any] = {
            "mail_layout": self.template,
            "mail_layout_labels": list(self.labels),
            "mail_layout_addresses": self.addresses,
            "mail_layout_start": self.start,
        }
        subject = self.subject
        if subject:
            found[MailKeys.raw(MailHeader.SUBJECT.value)] = subject

        moment = self.sent
        if moment.raw:
            found[MailKeys.DATE_SENT_RAW] = moment.raw
            found[MailKeys.ZONE_KNOWN] = moment.zone_known
            found[MailKeys.ZONE_SOURCE] = moment.zone_source
        if moment:
            found[MailKeys.DATE_SENT] = moment.isoformat()
            found[MailKeys.DATE_SENT_UTC_ASSUMED] = moment.utc_isoformat(evidential=False)
            if moment.zone_known:
                found[MailKeys.DATE_SENT_UTC] = moment.utc_isoformat()
        return found

    @classmethod
    def detect(
        cls,
        text: str,
        templates: Sequence[MailTemplate] | None = None,
    ) -> "MailHeaderBlock | None":
        """The first template that matches ``text``, or None; reads only the top of it."""
        candidates = tuple(templates) if templates else MailTemplate.defaults()
        rows = [line for line in text.splitlines() if line.strip()]

        for template in candidates:
            found = cls._match(template, rows, text)
            if found is not None:
                return found
        return None

    @classmethod
    def _match(
        cls,
        template: MailTemplate,
        rows: Sequence[str],
        text: str,
    ) -> "MailHeaderBlock | None":
        pattern = template.label_pattern
        if pattern is None:
            marker = template.marker_pattern
            if marker is not None and marker.search(text):
                return cls(template.name, (), (), 0, -1)
            return None

        for start in range(min(template.start_within, len(rows))):
            if not pattern.match(rows[start]):
                continue

            lines: list[str] = []
            labels: list[str] = []
            gap = 0
            for row in rows[start:]:
                hit = pattern.match(row)
                if hit:
                    lines.append(row)
                    labels.append(hit.group(1))
                    gap = 0
                    continue
                gap += 1
                # One unlabelled line is a wrapped value; two end the block.
                if gap > 1:
                    break
                lines.append(row)

            names = {label.lower() for label in labels}
            if any(need.lower() not in names for need in template.required):
                continue
            if len(labels) < template.min_labels:
                continue

            addresses = len(set(_ADDR_SPEC.findall("\n".join(lines))))
            # A printed memo has the labels but no address; the addr-spec marks mail.
            if template.require_address and addresses < 1:
                continue

            while lines and not pattern.match(lines[-1]):
                lines.pop()

            return cls(
                template=template.name,
                lines=tuple(lines),
                labels=tuple(labels),
                addresses=addresses,
                start=start,
            )
        return None


# --------------------------------------------------------------------------- #
# endregion Print layouts                                                     #
# --------------------------------------------------------------------------- #


class MailTemplateParser(GenericParser):
    """Read print layouts from JSON into `MailTemplate` objects; not in `ParserFactory`.

    With ``extend``, `MailTemplate.defaults()` come before the file's entries.
    """

    ALLOWED = ["extend"]

    def deserialise(self, reader: BinaryIO, **opts: Any) -> tuple[MailTemplate, ...]:
        payload = json.loads(reader.read().decode(opts.pop("encoding", None) or self.ENCODING))
        if not isinstance(payload, Mapping):
            raise ParserError(caller=self, error="template file must be a JSON object")

        declared = payload.get("templates")
        if not isinstance(declared, list) or not declared:
            raise ParserError(caller=self, error="'templates' must be a non-empty list")

        known = (
            set(MailHeader.__members__)
            | {h.header.lower() for h in MailHeader}
            | {label.lower() for label in PRINT_LABELS}
        )
        templates: list[MailTemplate] = []
        for entry in declared:
            if not isinstance(entry, Mapping) or not str(entry.get("name", "")).strip():
                raise ParserError(caller=self, error=f"template needs a 'name': {entry!r}")

            required = tuple(str(x) for x in entry.get("required", ()))
            optional = tuple(str(x) for x in entry.get("optional", ()))
            unknown = sorted(label for label in required + optional if label.lower() not in known)
            if unknown:
                # Reported, not refused: the file exists for labels this module lacks.
                self.warning(
                    msg=Event.Read.name,
                    step=Event.Check.name,
                    reason="labels outside MailHeader and PRINT_LABELS",
                    template=entry.get("name"),
                    labels=unknown,
                )

            templates.append(
                MailTemplate(
                    name=str(entry["name"]),
                    required=required,
                    optional=optional,
                    min_labels=int(entry.get("min_labels", 3)),
                    start_within=int(entry.get("start_within", 3)),
                    require_address=bool(entry.get("require_address", True)),
                    markers=tuple(str(x) for x in entry.get("markers", ())),
                )
            )

        if opts.pop("extend", None) or self.extend:
            return MailTemplate.defaults() + tuple(templates)
        return tuple(templates)


# --------------------------------------------------------------------------- #
class AttachmentPolicy:
    """Which attachment records become documents, and why the rest do not.

    Inline or Content-ID parts are rejected, then small parts of a skipped type (off by default).
    """

    __slots__ = ("skip_inline", "skip_types", "skip_below")

    def __init__(
        self,
        skip_inline: bool = True,
        skip_types: Sequence[str] = (),
        skip_below: int = 0,
    ) -> None:
        self.skip_inline = bool(skip_inline)
        # fnmatch, so both "image/*" and an exact "image/gif" work.
        self.skip_types: tuple[str, ...] = tuple(
            str(pattern).strip().lower() for pattern in skip_types if str(pattern).strip()
        )
        self.skip_below = int(skip_below)

    @classmethod
    def content_type(cls, record: Mapping[str, Any]) -> str:
        """The declared type, or one guessed from the filename when it is generic."""
        declared = str(record.get(MailKeys.CONTENT_TYPE) or "").strip().lower()
        if declared and declared != GENERIC_TYPE:
            return declared
        guessed, _ = mimetypes.guess_type(str(record.get("name") or ""))
        return (guessed or declared or GENERIC_TYPE).lower()

    def rejects(self, record: Mapping[str, Any]) -> str | None:
        """Reason this record is not promoted, or None to keep it."""
        if self.skip_inline:
            if bool(record.get("inline")):
                return "inline part, not an attached document"
            if str(record.get("content_id") or "").strip():
                return "carries a content-id, addressable from the body"

        if not self.skip_types or self.skip_below <= 0:
            return None

        content_type = self.content_type(record)
        if int(record.get("size") or 0) >= self.skip_below:
            return None
        if any(fnmatch(content_type, pattern) for pattern in self.skip_types):
            return f"{content_type} below {self.skip_below} bytes"
        return None


class MailParser(GenericParser[MailMessage]):
    """Reads a message from a declared source and extracts its attachments.

    A one-slot memo (for `path`) and a walk cursor make consecutive extractions one pass.
    """

    __slots__ = ("_memo_key", "_memo", "_walk", "_walk_next")
    # Tolerated so headers and body stay reachable despite broken attachments.
    OLE2_TOLERANCE: tuple[str, ...] = (
        "ATTACH_BROKEN",
        "ATTACH_NOT_IMPLEMENTED",
        "STANDARDS_VIOLATION",
    )
    # RFC name -> OLE2 property; used only when there is no transport header block.
    OLE2_PROPERTIES: tuple[tuple[str, str], ...] = (
        ("from", "sender"),
        ("to", "to"),
        ("cc", "cc"),
        ("bcc", "bcc"),
        ("subject", "subject"),
        ("date", "date"),
        ("message_id", "messageId"),
        ("in_reply_to", "inReplyTo"),
        ("reply_to", "replyTo"),
        ("return_path", "returnPath"),
        ("delivery_date", "receivedTime"),
    )
    DATE_KEYS: tuple[str, ...] = (
        MailKeys.DATE_SENT,
        MailKeys.DATE_RECEIVED,
        MailKeys.raw(MailHeader.DATE.value),
    )
    SUBJECT_KEYS: tuple[str, ...] = (
        MailKeys.raw(MailHeader.SUBJECT.value),
        MailHeader.SUBJECT.value,
    )

    # region Public

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._memo_key: str = ""
        self._memo: MailMessage | None = None
        self._walk: Iterator[MailAttachment] | None = None
        self._walk_next: int = 0

    def read(self, **source: Any) -> MailMessage:
        """The message at the declared source, memoised when it is a `path`."""
        key = str(source.get("path", "")) if len(source) == 1 else ""
        if key and self._memo is not None and self._memo_key == key:
            return self._memo

        message = self.parse(**source)
        self._memo_key, self._memo = key, (message if key else None)
        self._walk, self._walk_next = None, 0
        return message

    def digest(self, **source: Any) -> str:
        """Content digest of the message at the declared source (`MailMessage.digest`)."""
        return self.read(**source).digest

    def extract(self, index: int, *, expected: str = "", **source: Any) -> MailAttachment:
        """One attachment (0-based), verified against `expected`; ask in order for one pass.

        Raises IndexError when the part is absent, ValueError when it no longer matches.
        """
        # Resolve the source first: a new source must drop the cursor (the memo makes it free).
        message = self.read(**source)
        if self._walk is None or index < self._walk_next:
            self._walk, self._walk_next = message.walk_attachments(), 0

        record: MailAttachment | None = None
        while self._walk_next <= index:
            record = next(self._walk, None)
            self._walk_next += 1
            if record is None:
                self._walk = None
                raise IndexError(f"attachment {index} not present in {source}")

        assert record is not None
        if expected and record.digest != expected:
            raise ValueError(
                f"attachment {index} no longer matches its manifest: expected {expected}, read {record.digest}"
            )
        return record

    def release(self) -> None:
        """Drop the memo and the walk cursor so the message does not stay resident."""
        self._memo_key, self._memo = "", None
        self._walk, self._walk_next = None, 0

    # endregion Public

    # region Private

    def _from_ole2(self, reader: BinaryIO) -> MailMessage:
        """An OLE2 export, through the reader that owns that container."""
        try:
            import extract_msg
            from extract_msg.enums import ErrorBehavior
        except ImportError as e:
            raise ModuleNotFoundError("extract-msg is required for OLE2 messages: pip install extract-msg") from e

        tolerance = ErrorBehavior(0)
        for name in self.OLE2_TOLERANCE:
            tolerance |= getattr(ErrorBehavior, name)

        message = extract_msg.openMsg(reader, delayAttachments=True, errorBehavior=tolerance)
        try:
            body = self._ole2_text(getattr(message, "body", ""))
            attachments = self._ole2_attachments(message)
            block = self._ole2_block(message)
            if block:
                return MailMessage.from_header_block(block, body, attachments)
            return MailMessage.from_parts(self._ole2_headers(message), body, attachments)
        finally:
            try:
                message.close()
            except Exception:
                pass

    @staticmethod
    def _ole2_text(value: Any) -> str:
        """One OLE2 string without its control characters, e.g. the NUL terminator."""
        return OLE2_CONTROL_RE.sub("", str(value or "")).strip()

    def _ole2_block(self, message: Any) -> str:
        """The transport header block, or "" when the message never travelled."""
        try:
            header = getattr(message, "header", None)
            return header.as_string() if header is not None else ""
        except Exception:
            return ""

    def _ole2_headers(self, message: Any) -> dict[str, str]:
        """Properties of a message that never left the client, under RFC names."""
        headers: dict[str, str] = {}
        for name, prop in MailParser.OLE2_PROPERTIES:
            header = MailHeader.resolve(name)
            value = self._ole2_text(getattr(message, prop, ""))
            if header is not None and value:
                headers[header.header] = value
        return headers

    def _ole2_attachments(self, message: Any) -> tuple[MailAttachment, ...]:
        """Payloads the OLE2 reader exposes, as the same records an RFC part yields."""
        try:
            items = list(getattr(message, "attachments", None) or ())
        except Exception:
            return ()

        def prop(item: Any, name: str) -> Any:
            # extract_msg fields are lazy, so a malformed part raises on access.
            try:
                return getattr(item, name, None)
            except Exception:
                return None

        records: list[MailAttachment] = []
        for item in items:
            payload = prop(item, "data")
            if not isinstance(payload, (bytes, bytearray)):
                continue
            name = prop(item, "longFilename") or prop(item, "shortFilename")
            name = self._ole2_text(name) or f"attachment-{len(records) + 1}.bin"
            # OLE2 has no Content-Disposition: a Content-ID or the hidden flag marks a resource.
            content_id = self._ole2_text(prop(item, "cid")).strip("<> ")
            hidden = bool(prop(item, "hidden"))
            records.append(
                MailAttachment.build(
                    name,
                    self._ole2_text(prop(item, "mimetype")),
                    bytes(payload),
                    inline=hidden or bool(content_id),
                    content_id=content_id,
                )
            )
        return tuple(records)

    # endregion Private

    # region Public

    def deserialise(self, reader: BinaryIO, **kwargs: Any) -> MailMessage:
        """One message from an open reader, container decided by its content."""
        if FileType.is_ole2(reader.read(8)):
            reader.seek(0)
            return self._from_ole2(reader)
        reader.seek(0)
        return MailMessage.from_stream(reader)

    # endregion Public


__all__ = [
    "AttachmentPolicy",
    "MailHeaderBlock",
    "MailTemplate",
    "MailTemplateParser",
    "PRINT_LABELS",
    "MailHop",
    "MailParser",
    "MailMessage",
    "MailEnvelope",
    "MailAttachment",
    "MailAddress",
    "MailMoment",
    "MailHeader",
    "MailKeys",
]
