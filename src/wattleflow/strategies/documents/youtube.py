# Module name: strategies/documents/youtube.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# --------------------------------------------------------------------------- #
# IMPORTANT: This test case requires the openpyxl library.                    #
# Ensure you have it installed using:                                         #
#       pip install rdflib                                                    #
#                                                                             #
# The library is used to extract dataframes from excel worksheets.            #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
from abc import ABC
from pathlib import Path
from wattleflow.helpers.dtime import Now

try:
    from rdflib import Graph, Literal, Namespace, Node, URIRef
except ImportError as e:
    raise ModuleNotFoundError("rdflib library is missing.\n\tInstall: pip install rdflib") from e
from typing import Dict, List, Optional
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
    StrategyWrite,
)
from wattleflow.concrete.exception import StrategyException
from wattleflow.enums.event import Event
from wattleflow.enums.filetype import FileType
from wattleflow.concrete.helpers import Attribute
from wattleflow.helpers.formatters.factory import FormatterFactory

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Documents                                                            #
# --------------------------------------------------------------------------- #


class YoutubeGraph(Document[Graph], ABC):  # type: ignore
    def __init__(
        self,
        source: str,
        **kwargs,
    ):
        graph = Graph()
        namespace = Namespace("urn:wattleflow:youtubegraph#")  # EX
        subject = URIRef(f"urn:wattleflow:youtubegraph:{source}")  # type: ignore # DOC
        graph.bind("ex", namespace)
        graph.bind("doc", subject)

        super().__init__(content=graph, **kwargs)
        self.update_metadata("namespace", namespace)
        self.update_metadata("subject", subject)

    @property
    def graph(self) -> Graph:
        return self._content  # type: ignore

    @property
    def size(self) -> int:
        content = self.metadata.get("transcript", [{}])
        return len(content)  # type: ignore

    @property
    def uri(self) -> str:
        return self.metadata.uri  # type: ignore

    def specific_request(self) -> "YoutubeGraph":
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


# --------------------------------------------------------------------------- #
# endregion Documents                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Strategies                                                           #
# --------------------------------------------------------------------------- #


class CreateYoutubeDocument(StrategyCreate):
    def execute(self, caller: IWattleflow, *args, **kwargs) -> Optional[ITarget]:
        try:
            self.debug(msg=Event.Create.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IBlackboard), "Expected IBlackboard. Found %s" % type(caller)

            Attribute.mandatory(self, "id", str, **kwargs)
            Attribute.mandatory(self, "uri", str, **kwargs)
            Attribute.mandatory(self, "content", List, **kwargs)
            Attribute.mandatory(self, "metadata", Dict, **kwargs)

            if not len(self.content) > 0:  # type: ignore
                self.warning(
                    msg=Event.Create.name,
                    step=Event.Check.name,
                    reason="Transcript's feeling a bit empty today!",
                )
                return

            document = YoutubeGraph(source=self.uri)  # type: ignore

            # The source URI names the document when no filename is supplied.
            filename: str = kwargs.get("filename") or str(self.uri)

            # metadata
            document.update_metadata("created_by", self.name)
            document.update_metadata("created_at", Now.utc())
            document.update_metadata("caller", caller.name)
            document.update_metadata("filename", filename)
            document.update_metadata("source_format", "transcript")

            for key, value in kwargs.items():
                if key in ("caller", "filename", "content", "schema", "processor", "blackboard"):
                    continue
                document.update_metadata(f"kwargs_{key}", value)

            document.update_metadata("id", self.id)  # type: ignore
            document.update_metadata("uri", self.uri)  # type: ignore
            document.update_metadata("source", "YouTube")

            facade: DocumentFacade = DocumentFacade(document)
            # graph metadata
            document.add_predicate(
                predicate=document.namespace.hasIdentifier,  # type: ignore
                value=facade.identifier,
            )
            document.add_predicate(
                predicate=document.namespace.hasId,  # type: ignore
                value=self.id,  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasUri,  # type: ignore
                value=self.uri,  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasSource,  # type: ignore
                value="YouTube",  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasVideoId,  # type: ignore
                value=self.metadata.get("id", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasUploader,  # type: ignore
                value=self.metadata.get("uploader", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasTitle,  # type: ignore
                value=self.metadata.get("title", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasDescription,  # type: ignore
                value=self.metadata.get("Description", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasCategories,  # type: ignore
                value=self.metadata.get("categories", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasTags,  # type: ignore
                value=self.metadata.get("tags", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasAgeLimit,  # type: ignore
                value=self.metadata.get("age_limit", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasUploaderId,  # type: ignore
                value=self.metadata.get("uploader_id", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasUploaderUrl,  # type: ignore
                value=self.metadata.get("uploader_url", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasChannelId,  # type: ignore
                value=self.metadata.get("channel_id", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasChannelUrl,  # type: ignore
                value=self.metadata.get("channel_url", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasUploadDate,  # type: ignore
                value=self.metadata.get("upload_date", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasTimeStamp,  # type: ignore
                value=self.metadata.get("timestamp", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasDuration,  # type: ignore
                value=self.metadata.get("duration", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasViewCount,  # type: ignore
                value=self.metadata.get("view_count", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasLikeCount,  # type: ignore
                value=self.metadata.get("like_count", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasCommentCount,  # type: ignore
                value=self.metadata.get("comment_count", ""),  # type: ignore
            )

            document.add_predicate(
                predicate=document.namespace.hasLiveStatus,  # type: ignore
                value=self.metadata.get("live_status", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasResolution,  # type: ignore
                value=self.metadata.get("resolution", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasHeight,  # type: ignore
                value=self.metadata.get("height", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasWidth,  # type: ignore
                value=self.metadata.get("width", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasFPS,  # type: ignore
                value=self.metadata.get("fps", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasFileSize,  # type: ignore
                value=self.metadata.get("filesize", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasExtension,  # type: ignore
                value=self.metadata.get("ext", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.hasTranscript,  # type: ignore
                value=self.content,  # type: ignore
            )
            document.update_metadata("transcript", self.content)  # type: ignore
            # thumbnails – list of all available thumbnail urls
            document.add_predicate(
                predicate=document.namespace.hasFormat,  # type: ignore
                value=self.metadata.get("formats", ""),  # type: ignore
            )
            document.add_predicate(
                predicate=document.namespace.metadata,  # type: ignore
                value=self.metadata,  # type: ignore
            )
            self.debug(
                msg=Event.Create.name,
                step=Event.Completed.name,
                size=document.size,
                document=document,
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


class WriteYoutubeDocument(StrategyWrite):
    def execute(self, caller: IWattleflow, facade: ITarget, *args, **kwargs) -> bool:
        try:
            self.debug(msg=Event.Write.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IRepository), "Expected IRepository. Found %s" % type(caller)
            assert isinstance(facade, ITarget), "Expected ITarget. Found %s" % type(facade)

            driver = kwargs.get("driver")
            assert driver is not None, (
                "Driver not in kwargs — strategy requires RepositoryWithDriver"
            )

            document: YoutubeGraph = facade.request()  # type: ignore
            filename: str = document.get(URIRef("hasFilename"), document.identifier)  # type: ignore
            filename = Path(filename).with_suffix(".json")  # type: ignore
            if not document.size > 0:  # type: ignore
                self.warning(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="Graph’s feeling a bit empty today!",
                    document=document,
                    size=document.size,
                    filename=filename,
                )
                return False

            document.update_metadata("stored_by", self.name)
            document.update_metadata("stored_at", Now.utc())
            formatter = FormatterFactory.create(FileType.GRAPH)
            payload = formatter.render(content=document.content, format="json-ld", indent=2)
            output = driver.write(
                payload,
                filename=filename.name,
                suffix=formatter.SUFFIX,
            )
            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                document=document,
                output=output,
                size=document.size,
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


# --------------------------------------------------------------------------- #
# endregion Strategies                                                        #
# --------------------------------------------------------------------------- #
