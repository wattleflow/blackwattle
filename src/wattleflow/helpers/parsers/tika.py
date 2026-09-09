# Module name: helpers/parsers/tika.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


"""
TikaParser — read-side deserialiser that turns any stream Apache Tika can read
into text, through a client supplied by the caller.

Unlike the format-specific parsers, this one is not resolved by FileType: Tika
is the universal fallback for a source no local library could read (a scanned
PDF, an unknown container), so the driver constructs it with the ``client`` its
connection yielded. Path confinement is not a parser concern — the driver
resolves and sandboxes the path and GenericParser hands over an open reader
(DR-COR-015).
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #
from __future__ import annotations
from typing import Any, BinaryIO
from wattleflow.concrete.serialisation import GenericParser, ParserError
# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

__all__ = ["TikaParser"]

# --------------------------------------------------------------------------- #
# region Parsers                                                              #
# --------------------------------------------------------------------------- #


class TikaParser(GenericParser):
    """Extract text from a stream via an Apache Tika client.

    ``client`` is the handle a Tika connection yields; it is held as an opaque
    collaborator (anything exposing ``from_buffer``) so this helper keeps no
    edge to the connections package.

    Per call: ``headers`` for the request, ``raw=True`` to receive Tika's own
    ``{'status', 'content', 'metadata'}`` mapping instead of the text alone.
    """

    # PresetGate.resolve unions ALLOWED across the MRO, so only the added keys
    # are declared here; `encoding` comes from GenericParser.
    ALLOWED = ["client", "headers"]

    def deserialise(self, reader: BinaryIO, **opts: Any) -> Any:
        client = opts.pop("client", None) or self.client
        if client is None:
            raise ParserError(
                caller=self,
                error="TikaParser requires a `client` (a connected Tika handle).",
            )

        raw = bool(opts.pop("raw", False))
        headers = opts.pop("headers", None) or self.headers

        parsed = client.from_buffer(reader, headers=headers)
        if raw:
            return parsed

        # Tika answers with content None for a source it could read but found
        # nothing in; an empty string is the honest reading of that, and the
        # caller decides whether nothing is a failure.
        return (parsed.get("content") or "").strip()


# --------------------------------------------------------------------------- #
# endregion Parsers                                                           #
# --------------------------------------------------------------------------- #
