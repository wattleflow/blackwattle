# Module name: helpers/parsers/mail.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

"""Mail-family parser — RFC 5322 headers, MIME parts, address and date
normalisation shared by both mail readers.

A facade over the stdlib `email` package, not a replacement: `policy.default`
already handles unfolding, encoded words and RFC 2231 filenames. Added here is
only what the stdlib lacks — a named header set with cardinality, the
known/unknown timezone distinction `-0000` carries, an attachment record
digested over its content, and the serialisation boundary to the pipeline.

Reading is lazy: envelope, body and attachments are computed on first access
and cached, so a caller wanting metadata does not pay for attachment decoding.

`GenericParser` owns the source side (FRQ-PTN-15.19), so this module never
opens a path.
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
# What a container reports when it knows nothing about the part's type.
GENERIC_TYPE: str = "application/octet-stream"

HTML_DROP_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
HTML_BREAK_RE = re.compile(r"</?(br|p|div|tr|li|h[1-6]|table|blockquote)\b[^>]*>", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
HTML_WS_RE = re.compile(r"[ \t]+\n")
BLANK_RUN_RE = re.compile(r"\n{3,}")
# OLE2 strings arrive NUL-terminated; the C0 range has no place in a header
# value or a filename, but tab and newline belong to a body.
OLE2_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


# --------------------------------------------------------------------------- #
# region Headers                                                              #
# --------------------------------------------------------------------------- #
class MailHeader(str, Enum):
    """Headers this module reads, with their RFC 5322 §3.6 metadata."""

    # Identity and content.
    FROM = ("from", "From", True)
    SENDER = ("sender", "Sender", True)  # the actual sender when From has >1
    REPLY_TO = ("reply_to", "Reply-To", False)
    TO = ("to", "To", True)
    CC = ("cc", "Cc", True)
    BCC = ("bcc", "Bcc", False)  # recipient trace stays out of content
    SUBJECT = ("subject", "Subject", True)
    DATE = ("date", "Date", True)

    # Message identity — without it there is neither threading nor dedup.
    MESSAGE_ID = ("message_id", "Message-ID", False)
    IN_REPLY_TO = ("in_reply_to", "In-Reply-To", False)
    REFERENCES = ("references", "References", False, False)

    # Delivery trace (RFC 5321 §4.4) — never in content.
    RECEIVED = ("received", "Received", False, False)
    DELIVERY_DATE = ("delivery_date", "Delivery-Date", False)
    # Written by the final MTA, but a forwarded message carries one per hop.
    RETURN_PATH = ("return_path", "Return-Path", False, False)

    # Where it came from. Non-standard but widely emitted, and the only place
    # some gateways record the submitting client at all.
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
        """Member by internal or RFC name, case-insensitively: input from a
        .msg export arrives in both forms."""
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
    # Three digests, three questions. FILE_DIGEST answers "is this copy of the
    # container intact"; CONTENT_DIGEST answers "is this the same SUBJECT" and
    # is what addresses and deduplicates it; PARENT_DIGEST links a child to the
    # subject it came out of. A message is not its file, so a single key cannot
    # carry both — see MailMessage.digest.
    HOPS: str = "mail_hops"
    HOP_COUNT: str = "mail_hop_count"
    SERVERS: str = "mail_servers"
    IP_ADDRESSES: str = "mail_ip_addresses"
    ORIGINATING_IP: str = "mail_originating_ip"
    ATTACHMENT_COUNT: str = "mail_attachment_count"
    PARENT_SOURCE: str = "parent_source"
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
    """One address `local` and `domain` are kept apart because RFC 5322 treats
    them differently: the domain is case-insensitive, the local part formally is
    not. Dedup therefore goes through `key`, not `addr_spec.lower()`.
    """

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
        """(name, local, domain) from a bare address list. Group syntax
        (`undisclosed-recipients:;`) carries no address and drops out by itself."""
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
        """One address from a bare string. When no address survives (a .msg
        export may leave only a display name), the whole string becomes the
        name."""
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
        """Addresses from a header,ordered, deduplicated[`key`]. (the `policy.default` path)"""
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
        """Serialisation boundary: this crosses into metadata, the object
        does not."""
        return {"name": self.name, "address": self.addr_spec}


@dataclass(frozen=True, slots=True)
class MailMoment:
    """A time from the message, the raw text it came from, and whether its zone
    is known.

    `-0000` and the military zones (RFC 5322 §4.3) mean "zone unknown", for
    which the stdlib returns a naive `datetime`. The NAMED obsolete zones
    (`EST`, `GMT`, `UT`…) it does resolve, but §4.3 warns they were routinely
    emitted by senders outside the zone they name — parsed, and recorded as
    `zone_source` so a caller can weigh them.

    `raw` is retained because a report must quote what the header said, not
    what this module made of it.
    """

    value: datetime | None = None
    zone_known: bool = False
    raw: str = ""
    zone_source: str = ""  # "numeric" | "obsolete_name" | "unknown" | "iso" | ""
    leap_second: bool = False

    # A trailing alphabetic token is an obsolete zone name; a parenthesised
    # comment after it is permitted (§3.3) and is not part of the zone.
    OBSOLETE_ZONE_RE = re.compile(r"(?<![+\-\w])([A-Za-z]{1,5})\s*(?:\([^)]*\))?\s*$")
    # §3.3 permits a leap second. `datetime` cannot represent one, so it is
    # normalised to :59 and the substitution is RECORDED rather than hidden.
    LEAP_SECOND_RE = re.compile(r"(\d{1,2}:\d{2}):60(?!\d)")

    @staticmethod
    def _zone_source(text: str) -> str:
        tail = text.strip()
        if re.search(r"[+-]\d{4}\s*(?:\([^)]*\))?\s*$", tail):
            return "unknown" if re.search(r"-0000\s*(?:\([^)]*\))?\s*$", tail) else "numeric"
        return "obsolete_name" if MailMoment.OBSOLETE_ZONE_RE.search(tail) else "unknown"

    #: English month names, spelled out and abbreviated. An explicit table, not
    #: `%B`, because `strptime` reads month names through the process LOCALE and
    #: would fail wherever the runtime is not English.
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

    #: `Thursday, 4 September 2026 14:22` / `4 September 2026 at 14:22` /
    #: `Thursday, September 4, 2026 2:22 PM`. All-numeric forms are deliberately
    #: absent: `04/09/2026` is genuinely ambiguous and guessing is worse than
    #: reporting the raw text.
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
        """A time a mail client PRINTED on a page, which is not an RFC field.

        A printed date carries no offset — the client rendered it in whatever
        zone the reader's machine used, and the page does not say which. The
        result is therefore always `zone_known=False`, so a caller that needs a
        wall-clock time applies its own zone rather than assuming the sender's
        (see the naming rule: one zone, declared, not the sender's offset).
        """
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
        """Accepts `MailMoment`, `datetime`, `DateHeader`, an RFC 2822 or an ISO
        string.

        RFC 2822 is attempted FIRST: it is the format headers actually use, and
        since 3.11 `fromisoformat` accepts bare digit runs such as `20260831`,
        so a truncated field would otherwise become a date by accident.
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

        # ISO fallback, for values this module wrote itself — guarded, so a bare
        # digit run cannot pass as a date.
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
        """Aware UTC. An unknown zone is read as UTC — an ASSUMPTION, and the
        only place in this class making one. Sorting and naming may rely on it;
        an audit trail must not."""
        if self.value is None:
            return None
        if self.value.tzinfo is None:
            return self.value.replace(tzinfo=timezone.utc)
        return self.value.astimezone(timezone.utc)

    @property
    def utc_evidential(self) -> datetime | None:
        """UTC only when the message stated a zone; `None` otherwise, so an
        assumed value cannot reach a record that reads as fact."""
        if self.value is None or self.value.tzinfo is None:
            return None
        return self.value.astimezone(timezone.utc)

    @property
    def offset_seconds(self) -> int | None:
        if self.value is None or self.value.utcoffset() is None:
            return None
        return int(self.value.utcoffset().total_seconds())

    def in_zone(self, zone: str | None = None, *, assume: str = "UTC") -> datetime | None:
        """The moment seen from `zone` — ALWAYS resolvable, so a caller that
        needs a time gets one without first asking whether the zone was known.

        `zone` unnamed means the machine's own, resolved for the instant being
        converted rather than snapshotted. A value whose zone the message never
        stated is read as `assume` — UTC by default, because RFC 5322 §3.3 gives
        `-0000` exactly that meaning: the time IS UTC, the sender's zone is
        withheld. Whether this answer rests on that assumption is `zone_known`;
        the caller can ask, and a record that must not assume uses
        `utc_evidential` instead.
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

    The trace is the one part of a message the SENDER does not write. `From`,
    `Date` and `Message-ID` all come from the sender's client and can say
    anything; each hop is stamped by the server that accepted the message, and
    only hops below a trusted boundary can be forged. That makes this the
    evidential half of the provenance, which is why it is modelled rather than
    left as raw header text.
    """

    index: int = 0
    from_host: str = ""
    from_ip: str = ""
    by_host: str = ""
    by_ip: str = ""
    protocol: str = ""
    moment: MailMoment = MailMoment()
    raw: str = ""

    # `from a.example ([10.0.0.1])`, `by mx.example`, `with ESMTPS`, `; <date>`.
    # `envelope-from` in a trailing comment must not be read as the real `from`,
    # so the keywords are anchored on a non-word boundary rather than `\b`.
    FROM_RE = re.compile(r"(?<![-\w])from\s+([^\s(;]+)", re.IGNORECASE)
    BY_RE = re.compile(r"(?<![-\w])by\s+([^\s(;]+)", re.IGNORECASE)
    WITH_RE = re.compile(r"(?<![-\w])with\s+([A-Za-z0-9/_-]+)", re.IGNORECASE)
    # Delimiters must MATCH: `[1.2.3.4)` is malformed and is not an address.
    BRACKET_RE = re.compile(
        r"\[(?:IPv6:)?\s*([0-9A-Fa-f:.]+(?:%[0-9A-Za-z._-]+)?)\s*\]"
        r"|\((?:IPv6:)?\s*([0-9A-Fa-f:.]+(?:%[0-9A-Za-z._-]+)?)\s*\)"
    )

    @staticmethod
    def address(text: str) -> str:
        """`text` as an IP, or "" — validated, never pattern-matched.

        A dotted token that merely LOOKS like an address (a version string, a
        truncated host) would otherwise enter the record as one, and an audit
        cannot tell the two apart afterwards.
        """
        candidate = str(text or "").strip()
        if not candidate:
            return ""
        # `from [IPv6:2001:db8::1]` puts the literal where a host name goes; the
        # brackets and the tag are syntax, not part of the address.
        if candidate.startswith("[") and candidate.endswith("]"):
            candidate = candidate[1:-1].strip()
        if candidate.lower().startswith("ipv6:"):
            candidate = candidate[5:].strip()
        # An IPv6 literal may carry a zone identifier; the address is still an
        # address, the zone is local scope and is dropped.
        candidate = candidate.split("%", 1)[0]
        try:
            return str(ip_address(candidate))
        except ValueError:
            return ""

    @classmethod
    def parse(cls, raw: Any, index: int = 0) -> "MailHop":
        """One `Received` value. Never raises: a malformed hop yields whatever
        could be read, because a broken trace is still evidence."""
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

        # Which side a bracketed address belongs to is decided by POSITION: the
        # one before `by` was written by the sending host, the one after it by
        # the receiving host. No regex spanning both survives the variety here.
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

        # `Received: by 2002:a05:...` — some gateways put a bare address where a
        # host name goes; it is an address, and belongs in the address column.
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
    """One attachment. The digest is taken over the CONTENT, never the name,
    so it is stable across copies and lets the bundle write strategy
    deduplicate identical payloads."""

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
        """None when the part has no decodable content: one broken attachment
        must not cost the whole message."""
        try:
            payload = part.get_payload(decode=True)
        except (LookupError, ValueError, TypeError):
            return None
        if not payload:
            return None

        name = str(part.get_filename() or "").strip() or f"attachment-{index}"
        data = bytes(payload)
        return cls(
            name=name,
            content_type=part.get_content_type() or "application/octet-stream",
            payload=data,
            digest=FileDigest.labelled(data),
            inline=part.get_content_disposition() == "inline",
            content_id=str(part.get("Content-ID", "") or "").strip("<> "),
        )

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
    """RFC 5322 §3.6.2 mandates the distinction, and a single `mail_sender` key cannot express it."""

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
        """Who actually sent it: `Sender` when present, else the first
        `From`."""
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
        """`MailKeys.*` JSON-serialisable values — objects become a dict."""
        originator = self.originator or MailAddress()
        recipients = [address.addr_spec for address in self.to]
        return {
            MailKeys.DATE_SENT: self.date_sent.isoformat(),
            MailKeys.DATE_RECEIVED: (self.date_received or self.date_sent).isoformat(),
            # Populated ONLY when the message stated a zone. A `-0000` message
            # has no true UTC, only an assumed one, and that belongs in a field
            # whose name says so.
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
    """One read message, computed lazily. Two entry points because there are two readers: `.eml`"""

    message: EmailMessage | None = field(default=None, repr=False)
    raw_headers: Mapping[str, str] = field(default_factory=dict, repr=False)
    given_body: str | None = field(default=None, repr=False)
    given_attachments: tuple[MailAttachment, ...] | None = field(default=None, repr=False)

    # region Constructors
    @classmethod
    def from_stream(cls, reader: BinaryIO) -> "MailMessage":
        """Neither opens nor closes the source — that is `GenericParser`'s
        job."""
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
        """A message whose headers arrive as a raw RFC block, with body and
        attachments supplied separately.

        The block is re-read through `policy.default` rather than taken as
        text: unfolding (RFC 5322 §2.2.3), encoded words (RFC 2047) and
        repeated fields are the standard's work, and a container that hands
        over folded text has not done it.
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
        """Entry point for the .msg reader: `extract_msg` supplies the parts,
        this supplies the meaning. Keys are accepted as internal or RFC
        names."""
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
        """An HTML body as text: block elements become breaks, script and
        style CONTENT is dropped, entities are decoded."""
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
        """The structured header object when the message came from bytes, a
        bare string when it came from parts, `None` when absent."""
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
        """Every declared header, keyed by internal name.

        A header the registry marks non-unique keeps ALL its occurrences: a
        forwarded message carries one `Return-Path` per hop, and reporting only
        the first states as the message's origin what was merely the last one
        written.
        """
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
        """As `addresses`, but when no address survives it returns the display
        name as the sole party — a .msg export routinely carries only that."""
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
        """Delivery time: the stamp on the topmost `Received` hop (RFC 5321
        §4.4 requires it to end in `; date-time`, and a new hop is prepended),
        then `Delivery-Date`, finally the send time."""
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
        """The body as text: `text/plain` when it has CONTENT, otherwise
        `text/html` stripped of markup.

        Content is tested, not the existence of a part: `multipart/alternative`
        messages routinely carry an empty plain part beside a full HTML one, so
        an `is not None` test would return an empty body for a message that has
        one.
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
        """`email.errors` across every part — the structured alternative to an
        `except Exception` with a debug record (NFRQ-OBS-01)."""
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
        """Block: `rendered` fields, under their RFC names, so `Bcc`
        and the delivery trace stay out of document content."""
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
        """The transport trace, ORIGIN FIRST.

        Each server prepends its own `Received`, so the raw header order runs
        newest to oldest — the reverse of how a route reads. It is reversed once,
        here, so every consumer sees the same direction. `index` is the position
        in this chronological order, not in the header block.
        """
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
        """Where the message entered the route.

        `X-Originating-IP` when the gateway recorded one — it names the
        submitting CLIENT, which no hop does — otherwise the sending address of
        the first hop. Both are below the trusted boundary and neither is proof
        on its own; this records what the message claims, not a verdict.
        """
        declared = MailHop.address(self.text(MailHeader.ORIGINATING_IP).strip("[] "))
        if declared:
            return declared
        for hop in self.hops:
            if hop.from_ip:
                return hop.from_ip
        return ""

    def sent_at(self, zone: str | None = None) -> datetime | None:
        """The send time seen from `zone` — always answerable.

        The one call a consumer makes when it needs a time rather than an
        argument about zones: `zone` unnamed means the machine's own, a named
        one is used, and a message that stated no zone is read as UTC (RFC 5322
        §3.3). `MailKeys.ZONE_KNOWN` says whether the answer rests on that.
        """
        return self.envelope.date_sent.in_zone(zone)

    @cached_property
    def identity(self) -> str:
        """The fields that make this message THIS message, canonically joined.

        Everything here is normalised rather than raw: the send time as UTC
        (`-0000` and `+1000` state the same instant), addresses as `addr_spec`
        (display names are the client's decoration), recipients sorted (To/Cc
        order is presentation). The raw `Date` header, the file's timestamps and
        its name are deliberately absent — none of them is the message.
        """
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
        """Content digest of the MESSAGE — not of the container that carried it.
        Attachment digests are SORTED: MIME part order is how a client chose to
        lay the message out, not part of its identity. `identity` is not sorted;
        its field order is fixed by this method.
        """
        return FileDigest.folded(
            [
                FileDigest.of(self.identity.encode("utf-8")),
                FileDigest.of(self.body.encode("utf-8")),
                *sorted(attachment.digest for attachment in self.attachments),
            ]
        )

    def as_metadata(self, with_payload: bool = False) -> dict[str, Any]:
        """The envelope, raw headers under `msg_*` + attachment summary."""
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
        """Attachments ONE AT A TIME, without building the cached tuple.

        `attachments` decodes every part and holds them all; for a message whose
        attachments weigh tens of megabytes that is the whole payload resident
        at once. This yields each record as it is decoded, so a caller that
        writes and releases pays for one attachment at a time.

        An OLE2 export has no lazy path — its reader materialises the parts on
        open — so there the cached tuple is what there is.
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
# A message that reached us as a PRINTED page — a PDF of an email — has lost its
# container: there is no RFC envelope left, only the header block the client
# rendered at the top of the page. Recognising that block is what tells a piece
# of correspondence from a document, and the block itself is then ordinary
# input for `MailMessage.from_header_block`.
#
# The decisive property is POSITION AND CONTIGUITY, not the presence of labels:
# a report that quotes an email in an annex carries the same labels further
# down, and a printed memo carries `To:/From:/Subject:` with no address at all.
# Both were measured as false positives before those two conditions were added
# (`FRQ-MAIL-02` §9).


#: Labels a mail client prints that are NOT RFC 5322 fields, mapped to the field
#: they render. `Sent` is the client's rendering of `Date`; `Attachments` renders
#: the MIME parts and has no header equivalent. Whether they join `MailHeader` —
#: whose contract is "headers this module reads, with their RFC 5322 §3.6
#: metadata" — is an open decision (`FRQ-MAIL-02` §11).
PRINT_LABELS: Mapping[str, str | None] = MappingProxyType({"Sent": "Date", "Attachments": None})

#: `Label: value` on one printed line. Kept separate from a template's pattern:
#: that one asks "is this a label we expect", this one splits a line in two.
_LABEL_VALUE = re.compile(r"^\s*([A-Za-z][\w-]*)\s*:\s*(.*)$")

_ADDR_SPEC = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


@dataclass(frozen=True, slots=True)
class MailTemplate:
    """One client's print layout, declared as data rather than written as code.

    Several may be offered at once; the first that matches names the layout, and
    that name travels with the finding — which client printed it is diagnostic
    in its own right.

    A template with no labels and only ``markers`` matches on those alone: some
    webmail prints render no header block at all and are recognisable only by
    what the browser puts in the footer.
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

    # Plain properties, not `cached_property`: this dataclass uses __slots__, and
    # `re.compile` keeps its own pattern cache, so there is nothing left to save.
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
            # Ordered most specific first: a template's name is reported as the
            # finding, so a generic one matching an Outlook page would put a
            # false name on a true answer. `Sent` is Outlook's own rendering of
            # `Date` and is what separates the two client layouts.
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
    """A header block found at the top of printed text, and how it was found.

    ``text`` is ready for `MailMessage.from_header_block`; nothing here parses
    the fields, because the standard's reader already does that better.
    """

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
        """The block with print labels renamed to the field they render.

        `MailMessage.from_header_block` reads RFC fields; a client that printed
        `Sent:` wrote a `Date:`, and renaming it here is what lets the standard's
        own reader do the work instead of this module re-deriving it.
        """
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
        """When the message was sent, as the page states it.

        The PRINTED reading is tried first, and the RFC one only when the
        printed pattern does not match. The other order is wrong: the stdlib
        reads `Thursday, September 4, 2026 2:22 PM` as a time with an obsolete
        zone named `PM`, drops the meridiem, and returns 02:22 — a value twelve
        hours out that looks perfectly successful. `PRINTED_RE` is anchored, so
        a genuine RFC date with an offset cannot match it and falls through.
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
        """The block read by the standard's own reader.

        Everything a printed block can still say — parties, subject, an RFC
        date — comes from here rather than from a second parse of the same
        lines. Encoded words (RFC 2047) survive an export and are the reason
        the subject is not simply split off the line.
        """
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
        """The first template that matches ``text``, or None.

        Deliberately deterministic and cheap: it reads only the top of the text
        and matches literal labels. Damaged input — a scan whose OCR broke the
        labels — is out of scope here and belongs to `FRQ-MAIL-02`.
        """
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
                # One unlabelled line inside the block is a wrapped value; two
                # mean the block has ended.
                if gap > 1:
                    break
                lines.append(row)

            names = {label.lower() for label in labels}
            if any(need.lower() not in names for need in template.required):
                continue
            if len(labels) < template.min_labels:
                continue

            addresses = len(set(_ADDR_SPEC.findall("\n".join(lines))))
            # A printed memo carries To/From/Subject and no address at all; the
            # addr-spec is what separates correspondence from a form.
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
    """Read print layouts from JSON into `MailTemplate` objects.

    Like `RepairDictionaryParser`, this is **not** registered in
    `ParserFactory`: a layout set is configuration, not a document travelling
    the driver read path, so the consumer opens the file and instantiates this
    directly. Same contract as every other parser — one `deserialise`.

    Payload::

        {"version": "1.0", "templates": [
            {"name": "outlook-print",
             "required": ["From", "Subject"],
             "optional": ["Sent", "To", "Cc", "Attachments"],
             "min_labels": 3, "start_within": 3, "require_address": true},
            {"name": "our-gateway", "markers": ["ticket\\.example\\.com"],
             "min_labels": 0, "require_address": false}
        ]}

    ``extend`` keeps `MailTemplate.defaults()` ahead of the file's entries, so a
    deployment adds a client without restating the ones the module knows.
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
                # Reported, not refused: a client may print a label this module
                # has never seen, and refusing would make the file unusable for
                # the one case it was written for.
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

    A signature logo and an attached invoice are both attachments; only the
    message says which is which, and it says it in three places of decreasing
    reliability:

    1. ``inline`` — Content-Disposition for RFC 822, the Content-ID / hidden
       flag for OLE2. Standards-based, so it decides first.
    2. ``content_id`` present — a Content-ID exists so the body can address the
       part as a ``cid:`` URL (RFC 2392); carrying one makes it a resource OF
       the body, not a payload sent alongside it. The body is not scanned to
       confirm: ``MailMessage.body`` strips markup, so the ``<img src="cid:…">``
       that would prove the reference is gone before this step can see it.
    3. type and size together — for clients that ship a logo as an ordinary
       attachment with no marking left to read.

    Rule 3 needs BOTH halves. A 3 MB photograph is `image/jpeg` exactly like an
    8 kB signature logo, and dropping it because of its type alone would lose a
    document the sender meant to send. Both halves are therefore off by default:
    silently discarding evidence is worse than exporting a logo.
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
        """The record's type, falling back to the filename when the container
        reported nothing usable — an OLE2 part without a MIME tag arrives as
        the generic octet-stream, which no type rule can act on."""
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
    """Reads a message from any declared source, and extracts from it.

    What a message IS — its digest, its parts, how they decode — belongs to
    `MailMessage` and is not repeated here; `read()` hands that model back.
    What this class adds is everything that spans CALLS and therefore cannot
    live on an immutable model: resolving the source, a one-slot memo over the
    last message read from a `path`, and a walk cursor so consecutive
    extractions are a single pass.

    That is why `extract()` is here rather than a caller's loop: the write path
    asks one source for the digest and then for each attachment in turn, and
    without the memo and the cursor that message would be read N+1 times and its
    parts decoded N²/2 times. Only `path` is memoised — a stream or a payload is
    consumed by the read and cannot be answered again from a key. One slot
    deliberately: a larger cache would hold several whole messages resident,
    which is the retention this exists to avoid.
    """

    __slots__ = ("_memo_key", "_memo", "_walk", "_walk_next")
    # Tolerate malformed or unknown attachments headers-body stay reachable.
    OLE2_TOLERANCE: tuple[str, ...] = (
        "ATTACH_BROKEN",
        "ATTACH_NOT_IMPLEMENTED",
        "STANDARDS_VIOLATION",
    )
    # RFC name -> property the OLE2 reader exposes. Used only when the message
    # never travelled and therefore carries no transport header block.
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
        """Content digest of the message at the declared source.

        Over the message, not over the container that carried it — identity,
        body and the attachments' own content digests. See `MailMessage.digest`.
        """
        return self.read(**source).digest

    def extract(self, index: int, *, expected: str = "", **source: Any) -> MailAttachment:
        """Extract ONE attachment (0-based), verified against `expected`.

        The whole point of asking the parser rather than walking the message
        from outside: a caller that wants to write attachment 3 says so, and
        gets bytes it can trust. Verification belongs here because the digest is
        this module's own product — it was computed the first time the message
        was read, so a mismatch means the source changed under the run, which is
        worth failing on rather than writing a file no manifest describes.

        A WALK CURSOR makes consecutive requests one pass: `extract(0)`,
        `extract(1)` … decode each part once between them. Asking out of order
        restarts the walk, which is correct but pays for the parts it re-reads,
        so a caller writing a whole bundle should ask in order.

        Raises IndexError when the part is not there, ValueError when it no
        longer matches `expected`.
        """
        # Resolve the source FIRST, even when the cursor could carry on: a new
        # source re-parses and drops the cursor, so a caller that switches
        # messages mid-sequence cannot be served the previous one's parts.
        # The memo makes this free when the source has not changed.
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
        """Drop the memo and the walk cursor — call once a source's attachments
        are all written, so one whole message does not stay resident until the
        next one arrives."""
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
        """One OLE2 string, without the control characters the container adds.

        OLE2 stores strings NUL-terminated and the terminator survives the
        reader, so a name still carrying it reaches the filesystem as one no
        `open()` accepts. Tab and newline stay — a body needs them.
        """
        return OLE2_CONTROL_RE.sub("", str(value or "")).strip()

    def _ole2_block(self, message: Any) -> str:
        """transport header block text, or "" when the message never travelled."""
        try:
            header = getattr(message, "header", None)
            return header.as_string() if header is not None else ""
        except Exception:
            return ""

    def _ole2_headers(self, message: Any) -> dict[str, str]:
        """properties of a message that never left the client, under the RFC names."""
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
            # Every extract_msg attachment field is a lazy property over the OLE2
            # stream, so a malformed part raises on access, not on open.
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
            # OLE2 has no Content-Disposition. An embedded resource is marked
            # either by a Content-ID the body references or by the hidden flag
            # (PidTagAttachmentHidden), which is what a signature image carries.
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
