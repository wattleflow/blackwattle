# Module name: pipelines/nlp/annotate.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence
#
# Training-data generation for the PII recogniser: character spans over the RAW
# extracted text. Runs BEFORE any reduction pipeline — once entities have been
# replaced, the offsets no longer address the text a model would see.


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
import re
from typing import Any, Dict, List, Optional, Tuple
from wattleflow.core import IProcessor, ITarget
from wattleflow.concrete import GenericPipeline
from wattleflow.enums.event import Event
from wattleflow.documents.file import FileDocument
from wattleflow.helpers.parsers.mail import MailAddress, MailHeader, MailKeys
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Types                                                                #
# --------------------------------------------------------------------------- #
# One labelled character span over document.content:
# {"start", "end", "label", "text", "source"}. Offsets are Python string
# indices into the content as extracted, which is what a tokeniser's
# offset mapping aligns against.
Annotation = Dict[str, Any]
AnnotationList = List[Annotation]
# (label, pattern, capture group) — group 0 unless a cue word anchors the match.
PatternRow = Tuple[str, str, int]
# --------------------------------------------------------------------------- #
# endregion Types                                                             #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Catalogue                                                            #
# --------------------------------------------------------------------------- #
class PiiCatalogue:
    """Identifiers that carry a checkable format in UK/AU correspondence.

    A closed-form identifier needs no model: the pattern IS the ground truth,
    which is what makes these labels gold rather than silver. Patterns avoid
    nested quantifiers (the ReDoS shape `TextMacros` rejects) deliberately —
    they run over every document of the corpus."""

    PATTERNS: Tuple[PatternRow, ...] = (
        ("EMAIL", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", 0),
        # AU landline and mobile, national and +61 form.
        ("PHONE", r"(?:\+61[\s-]?|0)[2-478][\s-]?\d{4}[\s-]?\d{4}", 0),
        # UK national and +44 form; the trunk 0 is dropped after +44.
        ("PHONE", r"(?:\+44[\s-]?|0)\d{2,5}[\s-]?\d{3,4}[\s-]?\d{3,4}", 0),
        ("ABN", r"\b\d{2}[\s]?\d{3}[\s]?\d{3}[\s]?\d{3}\b", 0),
        ("ACN", r"\b\d{3}[\s]\d{3}[\s]\d{3}\b", 0),
        ("MEDICARE", r"\b\d{4}[\s]?\d{5}[\s]?\d(?:[/-]\d)?\b", 0),
        # Separators required: the run-together form is indistinguishable from
        # a 10-digit AU landline.
        ("NHS_NUMBER", r"\b\d{3}[\s-]\d{3}[\s-]\d{4}\b", 0),
        ("NI_NUMBER", r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b", 0),
        ("POSTCODE", r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", 0),
        ("POSTCODE", r"\b(?:NSW|VIC|QLD|SA|WA|TAS|NT|ACT)\s+\d{4}\b", 0),
        ("BANK_ACCOUNT", r"\b\d{3}-\d{3}\s?\d{6,10}\b", 0),
        ("BANK_ACCOUNT", r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b", 0),
        ("CARD_NUMBER", r"\b(?:\d{4}[\s-]){3}\d{4}\b", 0),
        # Case/claim references: "1386119/1", "REF: 2026-004512".
        ("CASE_REFERENCE", r"\b\d{6,9}/\d{1,3}\b", 0),
        # Cue-anchored: the reference must carry a digit, or the cue word
        # itself gets captured as its own reference.
        (
            "CASE_REFERENCE",
            r"\b(?:ref(?:erence)?|case|claim|matter)\b\W{0,6}([A-Z]{0,4}[-/]?\d[A-Z0-9/-]{3,20})\b",
            1,
        ),
        # A date is PII only where a cue makes it one; a bare date is not.
        ("DATE_OF_BIRTH", r"(?:d\.?o\.?b\.?|date of birth)\W{0,10}(\d{1,2}\W\d{1,2}\W\d{2,4})", 1),
    )

    # Longest first so a card number is not pre-empted by a phone-shaped prefix.
    PRIORITY: int = 20

    @classmethod
    def compiled(cls) -> List[Tuple[re.Pattern, str, int]]:
        return [
            (re.compile(pattern, re.IGNORECASE), label, group)
            for label, pattern, group in cls.PATTERNS
        ]

    @classmethod
    def scan(cls, text: str) -> AnnotationList:
        found: AnnotationList = []
        for pattern, label, group in cls.compiled():
            for match in pattern.finditer(text):
                start, end = match.span(group)
                surface = text[start:end].strip()
                if not surface:
                    continue
                found.append(
                    {
                        "start": start,
                        "end": start + len(surface),
                        "label": label,
                        "text": surface,
                        "source": "catalogue",
                        "priority": cls.PRIORITY,
                    }
                )
        return found


# --------------------------------------------------------------------------- #
# endregion Catalogue                                                         #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Envelope                                                             #
# --------------------------------------------------------------------------- #
class EnvelopeAnnotator:
    """Turns the message envelope into ground truth about its own body.

    The parties a message names in its headers are known — no model guesses
    them. Their names and addresses recur in the salutation, the signature and
    the quoted thread, so the envelope labels most of the PERSON and EMAIL
    occurrences in the body for free. This is the corpus-specific reason a
    trained recogniser is reachable without a manual annotation project."""

    ADDRESS_KEYS: Tuple[str, ...] = (MailKeys.SENDER, MailKeys.RECIPIENTS_ALL)
    # `From` and `Sender` are distinct parties (RFC 5322 §3.6.2); both vouch.
    # `msg_sender` is kept for documents extracted before the author's raw key
    # became `msg_from` — an old archive still annotates.
    HEADER_KEYS: Tuple[str, ...] = tuple(
        MailKeys.raw(header.value)
        for header in (MailHeader.FROM, MailHeader.SENDER, *MailHeader.recipients())
    )
    NAME_KEYS: Tuple[str, ...] = (MailKeys.SENDER_NAME,)
    # Header-derived labels outrank catalogue matches on the same span.
    PRIORITY: int = 40
    # Below this, a token is too generic to label from a header ("Jo", "Ltd").
    MIN_TOKEN: int = 4

    @classmethod
    def terms(cls, metadata: Dict[str, Any]) -> List[Tuple[str, str, bool]]:
        """(surface, label, case_sensitive) the envelope vouches for."""
        addresses: List[str] = []
        names: List[str] = []

        for key in cls.ADDRESS_KEYS:
            value = metadata.get(key)
            addresses.extend([value] if isinstance(value, str) else list(value or []))

        # Display names live only in the raw headers; the envelope keeps addresses.
        for key in cls.HEADER_KEYS:
            for address in MailAddress.parse(str(metadata.get(key) or "")):
                addresses.append(address.addr_spec)
                names.append(address.name)

        for key in cls.NAME_KEYS:
            names.append(str(metadata.get(key) or ""))

        terms: List[Tuple[str, str, bool]] = []
        seen: List[str] = []

        for address in addresses:
            address = str(address or "").strip()
            if "@" not in address or address.lower() in seen:
                continue
            seen.append(address.lower())
            terms.append((address, "EMAIL", False))
            # john.smith@acme.test vouches for "John Smith" in the body.
            names.append(cls.name_from(address))

        for name in names:
            for token in cls.tokens(name):
                if token.lower() in seen:
                    continue
                seen.append(token.lower())
                terms.append((token, "PERSON", True))

        return terms

    @staticmethod
    def name_from(address: str) -> str:
        """Person name a structured local part carries; "" when it carries none."""
        local = address.split("@", 1)[0]
        if "." not in local or not local.replace(".", "").isalpha():
            return ""
        return " ".join(part.capitalize() for part in local.split(".") if part)

    @classmethod
    def tokens(cls, name: str) -> List[str]:
        """The full name and each of its parts — a signature gives the full form,
        a salutation only the first name."""
        cleaned = re.sub(r"[^A-Za-z' -]+", " ", str(name or "")).strip()
        if not cleaned:
            return []

        parts = [p for p in re.split(r"[\s-]+", cleaned) if len(p) >= cls.MIN_TOKEN]
        out = parts[:]
        if len(parts) > 1:
            out.insert(0, cleaned)
        return out

    @classmethod
    def scan(cls, text: str, metadata: Dict[str, Any]) -> AnnotationList:
        found: AnnotationList = []
        for surface, label, cased in cls.terms(metadata):
            if not surface:
                continue
            flags = 0 if cased else re.IGNORECASE
            pattern = re.compile(rf"(?<![\w@.]){re.escape(surface)}(?![\w@.])", flags)
            for match in pattern.finditer(text):
                found.append(
                    {
                        "start": match.start(),
                        "end": match.end(),
                        "label": label,
                        "text": match.group(0),
                        "source": "envelope",
                        "priority": cls.PRIORITY,
                    }
                )
        return found


# --------------------------------------------------------------------------- #
# endregion Envelope                                                          #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# region Pipeline                                                             #
# --------------------------------------------------------------------------- #
class PipelineAnnotateEntities(GenericPipeline):
    """Character-span annotations over the raw text, for training a recogniser.
    Processor config (with defaults):
        annotate_labels:  tuple | None = None   # None = keep every label
        annotate_driver:  bool = True           # include DriverEntity patterns
    """

    DRIVER_PRIORITY: int = 10

    def driver_spans(self, processor: IProcessor, text: str) -> AnnotationList:
        """Spans the processor's redaction patterns claim. The `category` column
        names the label where the entity table declares one."""
        driver = getattr(processor, "driver", None)
        if driver is None or not hasattr(driver, "read"):
            return []

        try:
            rows = driver.read(table="entitet")
        except Exception as e:
            self.warning(
                msg=Event.Transform.name,
                step=Event.Check.name,
                reason="entity table unreadable",
                error=str(e),
            )
            return []

        found: AnnotationList = []
        for row in rows or []:
            pattern = str(row.get("pattern") or "")
            if not pattern:
                continue
            label = str(row.get("category") or "ENTITY").upper()
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
            except re.error:
                continue
            for match in compiled.finditer(text):
                surface = match.group(0).strip()
                if not surface:
                    continue
                found.append(
                    {
                        "start": match.start(),
                        "end": match.start() + len(surface),
                        "label": label,
                        "text": surface,
                        "source": "driver",
                        "priority": self.DRIVER_PRIORITY,
                    }
                )
        return found

    @staticmethod
    def resolve(spans: AnnotationList, labels: Optional[Tuple[str, ...]] = None) -> AnnotationList:
        """Non-overlapping spans, left to right. A tokeniser cannot represent two
        labels on one token, so overlaps must be decided here: higher priority
        first, then the longer span — a full name beats one of its parts."""
        candidates = [s for s in spans if not labels or s["label"] in labels]
        candidates.sort(key=lambda s: (-s["priority"], s["start"] - s["end"], s["start"]))

        kept: AnnotationList = []
        for span in candidates:
            if any(span["start"] < k["end"] and k["start"] < span["end"] for k in kept):
                continue
            kept.append(span)

        kept.sort(key=lambda s: s["start"])
        return [{k: v for k, v in span.items() if k != "priority"} for span in kept]

    def transform(self, processor: IProcessor, facade: ITarget, **kwargs: Any) -> None:
        document: FileDocument = facade.request()
        text: str = document.content or ""

        if not text.strip():
            self.warning(
                msg=Event.Transform.name, step=Event.Check.name, reason="no content to annotate"
            )
            return

        labels = getattr(processor, "annotate_labels", None)
        labels = tuple(labels) if labels else None

        spans: AnnotationList = []
        spans.extend(EnvelopeAnnotator.scan(text, document.metadata or {}))
        spans.extend(PiiCatalogue.scan(text))
        if bool(getattr(processor, "annotate_driver", True)):
            spans.extend(self.driver_spans(processor, text))

        annotations = self.resolve(spans, labels)

        document.update_metadata("annotations", annotations)
        document.update_metadata("annotation_count", len(annotations))

        uid = processor.blackboard.write(
            facade=facade,
            processor=processor,
            pipeline=self,
        )

        self.debug(
            msg=Event.Transform.name,
            step=Event.Completed.name,
            uid=uid,
            annotations=len(annotations),
            size=len(text),
        )


# --------------------------------------------------------------------------- #
# endregion Pipeline                                                          #
# --------------------------------------------------------------------------- #

__all__ = [
    "Annotation",
    "AnnotationList",
    "EnvelopeAnnotator",
    "PiiCatalogue",
    "PipelineAnnotateEntities",
]
