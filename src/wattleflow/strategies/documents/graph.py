# Module name: strategies/documents/graph.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# ----------------------------------------------------------------------------#
# region Import                                                               #
# ----------------------------------------------------------------------------#

from __future__ import annotations
from pathlib import Path
from rdflib import Graph, Literal, Namespace, Node, URIRef
from typing import Optional
from wattleflow.helpers.dtime import Now

from wattleflow.core import (
    IBlackboard,
    IRepository,
    ITarget,
    IWattleflow,
)

from wattleflow.concrete import (
    Document,
    DocumentFacade,
    StrategyCreate,
    StrategyRead,
    StrategyWrite,
)
from wattleflow.concrete.exception import StrategyException
from wattleflow.enums.event import Event
from wattleflow.concrete.helpers import Attribute
from wattleflow.helpers.normaliser import Normaliser
from wattleflow.helpers.formatters.factory import FormatterFactory
from wattleflow.enums.filetype import FileType

# ----------------------------------------------------------------------------#
# endregion Import                                                            #
# ----------------------------------------------------------------------------#

# ----------------------------------------------------------------------------#
# region Document: RDF                                                        #
# ----------------------------------------------------------------------------#


class GraphHtml(Document[Graph]):
    def __init__(self, uri: str, **kwargs):
        graph = Graph()

        self.namespace = Namespace("urn:wattleflow:htmlgraph#")
        self.subject = URIRef(f"urn:wattleflow:htmlgraph:{uri}")

        graph.bind("ex", self.namespace)
        graph.bind("doc", self.subject)

        super().__init__(content=graph, **kwargs)

        self.debug(
            msg=Event.Constructor.name,
            step=Event.Started.name,
            level=self.levelname,
            uri=uri,
        )

        self.update_metadata("namespace", self.namespace)
        self.update_metadata("subject", self.subject)

        self.add_predicate(self.namespace.hasUri, uri)  # type: ignore
        self.add_predicate(self.namespace.hasIdentifier, self.identifier)  # type: ignore
        self.add_predicate(self.namespace.hasNamespace, str(self.namespace))  # type: ignore
        self.add_predicate(self.namespace.hasSubject, str(self.subject))  # type: ignore
        self.add_predicate(self.namespace.hasCreatedAt, str(Now.utc()))  # type: ignore

        self.debug(
            msg=Event.Constructor.name,
            step=Event.Completed.name,
        )

    @property
    def uri(self) -> str:
        return self.get(URIRef("hasUri"), self.identifier)  # type: ignore
        # return self.get(URIRef(document.namespace.hasUri), "")

    @property
    def identifier(self) -> str:
        # return self.identifier  # RecursionError!
        return super().identifier

    @property
    def size(self) -> int:
        if isinstance(self.content, Graph):
            return len(self.content)
        return 0

    @property
    def graph(self) -> Graph:
        return self._content  # type: ignore

    def specific_request(self) -> "GraphHtml":
        return self

    def add_predicate(self, predicate: URIRef, value: str):
        self._content.add((self.subject, predicate, Literal(value)))  # type: ignore
        self._lastchange = Now.utc()

    def remove(self, predicate: URIRef, value: object):
        self._content.remove((self._subject, predicate, Literal(value)))  # type: ignore
        self._lastchange = Now.utc()

    def clear(self):
        self._content.remove((None, None, None))  # type: ignore
        self._content = Graph(identifier=self.subject)  # type: ignore
        self._lastchange = Now.utc()

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

    def update_graph(self, new_graph: Graph):
        copied = Graph(identifier=new_graph.identifier)

        for triple in new_graph:
            copied.add(triple)

        for prefix, ns in new_graph.namespaces():
            copied.bind(prefix, ns, override=True)

        self.update_content(copied)

    def __getattr__(self, name: str) -> object:
        obj = self.metadata.get(name, None)
        if obj is None:
            raise ValueError(f"Property: {name} does not exist in the document!")
        return obj


# ----------------------------------------------------------------------------#
# endregion Document
# ----------------------------------------------------------------------------#

# ----------------------------------------------------------------------------#
# region Strategies                                                           #
# ----------------------------------------------------------------------------#


class CreateGraphFromHtml(StrategyCreate):
    def execute(self, caller: IWattleflow, *args, **kwargs) -> Optional[ITarget]:
        try:
            self.debug(msg=Event.Create.name, step=Event.Started.name, caller=caller, kwargs=kwargs)
            assert isinstance(caller, IBlackboard), "Expected type: IBlackboard. Found %s" % type(
                caller
            )
            downloaded_at = Now.utc()
            Attribute.mandatory(self, "uri", str, **kwargs)
            Attribute.mandatory(self, "content", str, **kwargs)
            Attribute.mandatory(self, "metadata", dict, **kwargs)

            document = GraphHtml(uri=self.uri, level=self._level, handler=self._handler)

            # The source URI is the document's name when no filename is supplied.
            filename: str = kwargs.get("filename") or str(self.uri)

            # metadata
            document.update_metadata("created_by", self.name)
            document.update_metadata("created_at", Now.utc())
            document.update_metadata("caller", caller.name)
            document.update_metadata("filename", filename)
            document.update_metadata("source_format", "html")

            for key, value in kwargs.items():
                if key in ("caller", "filename", "content", "schema", "processor", "blackboard"):
                    continue
                document.update_metadata(f"kwargs_{key}", value)

            if not len(self.content) > 0:  # type: ignore
                self.warning(
                    msg=Event.Create.name,
                    step=Event.Check.name,
                    reason="Web page's feeling a bit empty today!",
                    uri=self.uri,  # type: ignore
                )

            facade: DocumentFacade = DocumentFacade(document)
            # graph metadata: predicate, value
            document.add_predicate(document.namespace.hasIdentifier, facade.identifier)  # type: ignore
            document.add_predicate(document.namespace.hasUri, self.uri)  # type: ignore
            document.add_predicate(
                document.namespace.hasSource,
                self.metadata.get("source", "?"),  # type: ignore
            )
            document.add_predicate(
                document.namespace.hasTitle,
                self.metadata.get("title", "?"),  # type: ignore
            )
            document.add_predicate(
                document.namespace.hasDescription,
                self.metadata.get("description", "?"),  # type: ignore
            )
            document.add_predicate(document.namespace.hasDownloadedAt, downloaded_at)  # type: ignore
            processor = kwargs.get("processor")
            processor_name = processor.name if processor is not None else "<unknown>"
            document.add_predicate(
                document.namespace.hasDownloadedBy,
                processor_name,
            )
            filename = kwargs.get("filename", "")
            document.add_predicate(document.namespace.hasFileName, filename)  # type: ignore
            document.add_predicate(
                document.namespace.hasLinks,
                self.metadata.get("links", "?"),  # type: ignore
            )
            document.add_predicate(
                document.namespace.hasFileSize,
                self.metadata.get("filesize", ""),  # type: ignore
            )
            document.add_predicate(document.namespace.hasContent, self.content)  # type: ignore
            document.add_predicate(document.namespace.hasTranscript, "")  # type: ignore

            self.debug(
                msg=Event.Create.name,
                step=Event.Completed.name,
                document=document,
                size=document.size,
            )

            return facade
        except AssertionError as e:
            error = f"Assertion: {str(e)}"
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e


class ReadHtmlGraphDocument(StrategyRead):
    def execute(self, caller: IWattleflow, *args, **kwargs) -> ITarget | None:
        return super().execute(caller, *args, **kwargs)


class WriteGraphHtmlDocument(StrategyWrite):
    def get_schema_ns(self, graph: Graph) -> Namespace:
        ns_map = dict(graph.namespace_manager.namespaces())
        ns = ns_map.get("schema")
        if ns is not None:
            return Namespace(ns)

        for _, uri in ns_map.items():
            u = str(uri).rstrip("/")
            if u in ("http://schema.org", "https://schema.org"):
                return Namespace(uri)

        raise ValueError("Schema is not found!")

    def execute(self, caller: IWattleflow, facade: ITarget, *args, **kwargs) -> bool:
        self.debug(
            msg=Event.Write.name,
            step=Event.Started.name,
            caller=caller,
            facade=facade,
            kwargs=kwargs,
        )

        try:
            assert isinstance(caller, IRepository), "Expected IRepository. Found %s" % type(caller)
            assert isinstance(facade, ITarget), "Expected ITarget. Found %s" % type(facade)

            driver = kwargs.get("driver")
            assert driver is not None, (
                "Driver not in kwargs — strategy requires RepositoryWithDriver"
            )

            # processor je opcionalan ovdje (samo za log/audit info)
            processor = kwargs.get("processor")

            graph: GraphHtml = facade.request()  # type: ignore
            assert isinstance(graph, GraphHtml), "Expected type: GraphHtml. Found %s" % type(graph)
            assert isinstance(graph.content, Graph), "Expected type: Graph. Found %s" % type(
                graph.content
            )

            if not graph.size > 0:  # type: ignore
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    graph=graph,
                    reason="Is this graph half empty or half full?",
                )
                return False

            suffix = kwargs.get("suffix", ".json")
            name = graph.get(URIRef("hasFilename"), graph.identifier)  # type: ignore
            filename = Path(name).with_suffix(suffix)  # type: ignore

            sheetname = graph.get(URIRef("hasSheetname"), None)  # type: ignore
            if sheetname is None:
                sheetname: str = graph.metadata.get("sheetname", None)
                if sheetname:
                    filename = filename.with_stem(
                        "%s-%s" % filename.stem % Normaliser(sheetname).name().date()
                    )
            self.debug(
                msg=Event.Write.name,
                scope="render",
                step=Event.Completed.name,
                filename=str(filename),
                sheetname=sheetname,
            )

            ns_map = dict(graph.content.namespace_manager.namespaces())  # type: ignore
            EX = Namespace(ns_map.get("ex", "https://example.org/"))
            subject = URIRef(graph.content.identifier)  # type: ignore

            for key, value in graph.metadata.items():
                predicate = EX[key]
                graph.content.add((subject, predicate, Literal(value)))  # type: ignore

            graph.update_metadata("storage_pipeline", caller.name.lower())
            graph.update_metadata("storage_time", graph.utc_time_stamp())
            if processor is not None:
                graph.update_metadata("storage_processor", processor.name)
            formatter = FormatterFactory.create(FileType.GRAPH)
            payload = formatter.render(content=graph.content, format="json-ld", indent=2)
            output = driver.write(  # type: ignore
                payload,
                filename=filename.name,
                suffix=formatter.SUFFIX,
                subdir=caller.name.lower(),
                mkdir=True,
            )
            graph.update_metadata("storage_filename", output)
            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                document=graph,
                size=graph.size,
                output=output,
            )

            return True
        except AssertionError as e:
            error = f"Assertion: {str(e)}"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e


# ----------------------------------------------------------------------------#
# endregion Strategies
# ----------------------------------------------------------------------------#
