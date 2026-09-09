# Module name: documents/rdf.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2025 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# Dependencies:
#   pip install rdflib
#
# --------------------------------------------------------------------------- #

"""
Description: This module defines the RDF document (RDFDocument) and
RDFGraphBuilder for constructing provenance-aware RDF graphs within the
WattleFlow framework.
"""

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
from abc import ABC
from typing import Iterable, Optional
from wattleflow.helpers.dtime import Now
import re

# rdflib is a hard requirement of this RDF-native module (class-level Namespace
# constants are built at import time). documents/ is therefore a "heavy" sub-module
# and is deferred from parent `import *` re-export (CLAUDE.md §2.7).
try:
    from rdflib import Graph, Namespace, URIRef, Node, Literal
    from rdflib.namespace import DCAT, DCTERMS, PROV, RDF
except Exception as e:
    raise ModuleNotFoundError(
        f"You need rdflib for documents/wattle.py.\nPlease run: pip install rdflib! {str(e)}"
    ) from e

from uuid import uuid4
from wattleflow.core import IWattleflow
from wattleflow.core.creational import IBuilder
from wattleflow.concrete import Document, Wattleflow
from wattleflow.enums.event import Event
from wattleflow.enums.mimetypes import MimeTypes


# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

_URI_SAFE: re.Pattern = re.compile(r"[^A-Za-z0-9_\-.]")

# --------------------------------------------------------------------------- #
# region Global methods                                                       #
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# endregion Global methods                                                    #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Builders                                                             #
# --------------------------------------------------------------------------- #


class RDFGraphBuilder(Wattleflow, IBuilder):
    # Class-level namespace constants — read-only, shared across all instances.
    # NOTE: the urn:wattle:* URN values and the WG/RES/NFO prefixes are a DATA
    # contract (already-serialised graphs carry them); they are intentionally
    # preserved across the Wattle -> RDFDocument rename and must NOT be changed
    # without a separate data migration.
    WG: Namespace = Namespace("urn:wattle:vocab#")
    RES: Namespace = Namespace("urn:wattle:resource:")
    NFO: Namespace = Namespace("http://www.semanticdesktop.org/ontologies/2007/03/22/nfo#")

    def __init__(
        self,
        caller: IWattleflow,
        mime: MimeTypes,
        uri: str,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self._require_non_empty_str(uri, "uri")
        if not isinstance(mime, MimeTypes):
            raise TypeError(f"mime must be a MimeTypes instance, got {type(mime)!r}")
        if not isinstance(caller, IWattleflow):
            raise TypeError(f"caller must be an IWattleflow instance, got {type(caller)!r}")

        self._caller: IWattleflow = caller
        self._mime: MimeTypes = mime
        self._uri: str = uri
        self._graph_identifier: Optional[str] = None

        self.debug(
            msg=Event.Constructor.name,
            step=Event.Completed.name,
            uri=uri,
        )

    @property
    def graph_identifier(self) -> Optional[str]:
        return self._graph_identifier

    # region IBuilder contract
    def build(self) -> Graph:
        self.debug(msg=Event.Constructor.name, step=Event.Started.name)

        identifier = uuid4()
        self._graph_identifier = f"urn:wattleflow:graph:{identifier}"
        graph = Graph(identifier=URIRef(self._graph_identifier))

        self._bind_namespaces(graph)

        # FIX: v0.0.0.62 - 26/3/17 - Sanitised caller.name and mime values before
        # using them in URIRef construction; raw strings could inject arbitrary URI
        # characters and produce malformed or exploitable graph identifiers.
        caller_seg: str = self._safe_uri_segment(self._caller.name)
        mime_name_seg: str = self._safe_uri_segment(self._mime.name)
        mime_value_seg: str = self._safe_uri_segment(self._mime.value)

        subject: URIRef = self.RES["wattle"]

        self._add_artifact(graph, subject)
        self._add_format(graph, mime_name_seg)
        self._add_steps(graph, caller_seg)
        self._add_provenance(graph, caller_seg, mime_name_seg, mime_value_seg)

        self.debug(msg=Event.Constructor.name, step=Event.Completed.name)
        return graph

    # --- Protected helpers ---------------------------------------------------

    def _bind_namespaces(self, graph: Graph) -> None:
        for pfx, ns in [
            ("WG", self.WG),
            ("RES", self.RES),
            ("DCAT", DCAT),
            ("PROV", PROV),
            ("NFO", self.NFO),
            ("DCTERMS", DCTERMS),
        ]:
            graph.bind(pfx, ns)

    def _add_artifact(self, graph: Graph, subject: URIRef) -> None:
        graph.add((subject, RDF.type, self.WG.Processor))
        graph.add((subject, self.WG.Processor, Literal(self._caller.name)))
        graph.add((subject, RDF.type, self.WG.Artifact))
        graph.add((subject, RDF.type, DCAT.Distribution))
        graph.add((subject, DCAT.mediaType, Literal(self._mime.name)))
        graph.add((subject, RDF.type, self.WG.Created))
        graph.add((subject, self.WG.runId, Literal(str(Now.utc()))))

    def _add_format(self, graph: Graph, mime_name_seg: str) -> None:
        graph.add((self.RES[mime_name_seg], DCTERMS.format, Literal(self._mime.value)))

    def _add_steps(self, graph: Graph, caller_seg: str) -> None:
        graph.add((self.RES[caller_seg], RDF.type, self.WG.Step))
        graph.add((self.RES[caller_seg], self.WG.hasStep, Literal("Creation")))

    def _add_provenance(
        self,
        graph: Graph,
        caller_seg: str,
        mime_name_seg: str,
        mime_value_seg: str,
    ) -> None:
        graph.add((self.RES[caller_seg], PROV.used, self.RES[mime_name_seg]))
        graph.add((self.RES[caller_seg], PROV.generated, self.RES[mime_value_seg]))

    def _safe_uri_segment(self, value: str) -> str:
        return _URI_SAFE.sub("_", value)

    def _require_non_empty_str(self, value: object, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string, got {value!r}")
        return value

    # endregion IBuilder contract


# --------------------------------------------------------------------------- #
# endregion Builders                                                          #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Document                                                             #
# --------------------------------------------------------------------------- #


class RDFDocument(Document[Graph], ABC):
    """An RDF-backed WattleFlow document representing a single provenance artefact."""

    def __init__(
        self,
        caller: IWattleflow,
        mime: MimeTypes,
        uri: str,
        **kwargs,
    ) -> None:

        builder = RDFGraphBuilder(
            caller=caller,
            mime=mime,
            uri=uri,
            **kwargs,
        )
        graph: Graph = builder.build()

        super().__init__(content=graph, **kwargs)

        self._identifier = builder.graph_identifier

        self.debug(
            msg=Event.Constructor.name,
            step=Event.Started.name,
            identifier=self.identifier,
            level=self.levelname,
            uri=uri,
        )

        subject: URIRef = RDFGraphBuilder.RES["wattle"]
        self.update_metadata("subject", subject)
        self.update_metadata("uri", uri)
        self.update_metadata("WG", RDFGraphBuilder.WG)
        self.update_metadata("RES", RDFGraphBuilder.RES)
        self.update_metadata("DCAT", DCAT)
        self.update_metadata("PROV", PROV)
        self.update_metadata("NFO", RDFGraphBuilder.NFO)

        self.debug(
            msg=Event.Constructor.name,
            step=Event.Completed.name,
        )

    # ----------------------------------------------------------
    # region Properties
    # ----------------------------------------------------------

    @property
    def namespaces(self) -> Iterable[tuple[str, URIRef]]:
        return self.content.namespace_manager.namespaces()

        # region ignore
        # def namespacemap(self):
        # for _, uri in ns_map.items():
        #     u = str(uri).rstrip("/")
        #     if u in ("http://schema.org", "https://schema.org"):
        #         return Namespace(uri)
        # raise ValueError("Schema is not found!")
        # endregion ignore

    @property
    def size(self) -> int:
        if isinstance(self.content, Graph):
            return len(self.content)
        return 0

    @property
    def uri(self) -> str:
        return str(self.metadata.get("uri", ""))

    @property
    def subject(self) -> URIRef:
        return self.metadata["subject"]  # type: ignore[return-value]

    @property
    def WG(self) -> Namespace:
        return self.metadata["WG"]  # type: ignore[return-value]

    @property
    def RES(self) -> Namespace:
        return self.metadata["RES"]  # type: ignore[return-value]

    @property
    def NFO(self) -> Namespace:
        return self.metadata["NFO"]  # type: ignore[return-value]

    # endregion Properties

    def specific_request(self) -> "RDFDocument":
        return self

    def add(self, subject: URIRef, predicate: URIRef, value: str) -> None:
        self._content.add((subject, predicate, Literal(value)))  # type: ignore
        self._metadata["last_change_key"] = "content"
        self._metadata["last_change_time"] = self.utc_time_stamp()

    def add_predicate(self, predicate: URIRef, value: str) -> None:
        self._content.add((self.subject, predicate, Literal(value)))  # type: ignore
        self._metadata["last_change_key"] = "content"
        self._metadata["last_change_time"] = self.utc_time_stamp()

    def remove(self, predicate: URIRef, value: object) -> None:
        self._content.remove((self.subject, predicate, Literal(value)))  # type: ignore
        self._metadata["last_change_key"] = "content"
        self._metadata["last_change_time"] = self.utc_time_stamp()

    def clear(self) -> None:
        self._content.remove((None, None, None))  # type: ignore
        self._content = Graph(identifier=self.subject)  # type: ignore
        self._metadata["last_change_key"] = "content"
        self._metadata["last_change_time"] = self.utc_time_stamp()

    def get(self, predicate: URIRef, default: Optional[Node] = None) -> Optional[Node]:
        try:
            result = self._content.value(  # type: ignore
                subject=self.subject,  # type: ignore
                predicate=predicate,
                default=default,
            )
            return result
        except Exception as e:
            self.error(msg=Event.Getting.name, error=str(e))
            return default

    def update_graph(self, new_graph: Graph) -> None:
        copied = Graph(identifier=new_graph.identifier)

        for triple in new_graph:
            copied.add(triple)

        for prefix, ns in new_graph.namespaces():
            copied.bind(prefix, ns, override=True)

        self.update_content(copied)


# --------------------------------------------------------------------------- #
# endregion Document                                                          #
# --------------------------------------------------------------------------- #
