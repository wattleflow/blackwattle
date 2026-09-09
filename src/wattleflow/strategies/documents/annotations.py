# Module name: strategies/documents/annotations.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# ----------------------------------------------------------------------------#
# region Import                                                               #
# ----------------------------------------------------------------------------#
from __future__ import annotations
import json
from typing import Any, Dict, List, Optional
from wattleflow.core import IBlackboard, IRepository, ITarget, IWattleflow
from wattleflow.concrete import (
    DocumentFacade,
    StrategyCreate,
    StrategyWrite,
)
from wattleflow.concrete.exception import StrategyException
from wattleflow.documents.dataframe import DataFrameDocument
from wattleflow.enums.event import Event
from wattleflow.enums.filetype import FileType
from wattleflow.documents.file import FileDocument
from wattleflow.concrete.helpers import Attribute
from wattleflow.helpers.dtime import Now
from wattleflow.helpers.formatters.factory import FormatterFactory
from wattleflow.helpers.parsers.mail import MailKeys, MailParser
# ----------------------------------------------------------------------------#
# endregion Import                                                            #
# ----------------------------------------------------------------------------#


# ----------------------------------------------------------------------------#
# region Classes                                                              #
# ----------------------------------------------------------------------------#


class CreateAnnotationDocument(StrategyCreate):
    def execute(self, caller: IWattleflow, **kwargs) -> Optional[ITarget]:
        try:
            self.debug(msg=Event.Create.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IBlackboard), "Expected IBlackboard. Found %s" % type(caller)

            Attribute.mandatory(self, "filename", str, **kwargs)
            document: FileDocument = FileDocument(
                filename=self.filename,
                level=self._level,
                handler=self._handler,
            )

            # metadata
            document.update_metadata("created_by", self.name)
            document.update_metadata("created_at", Now.utc())
            document.update_metadata("caller", caller.name)
            document.update_metadata("filename", self.filename)
            document.update_metadata("source_format", "file")

            for key, value in kwargs.items():
                if key in ("caller", "filename", "content", "schema", "processor", "blackboard"):
                    continue
                document.update_metadata(f"kwargs_{key}", value)

            if not document.size > 0:
                self.warning(
                    msg=Event.Create.name,
                    step=Event.Check.name,
                    reason="Anotation file's feeling a bit empty today!",
                    document=document,
                )

            self.debug(
                msg=Event.Create.name,
                step=Event.Completed.name,
                document=document.identifier,
                size=document.size,
            )

            return DocumentFacade(document)
        except AssertionError as e:
            error = f"Assertion: {str(e)}"
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e


class WriteEntityAnnotations(StrategyWrite):
    """Persist one training record per document: the raw text and its labelled
    character spans (from PipelineAnnotateEntities).

    One file per document rather than one appended corpus file: a repository
    writes concurrently, and an interrupted append corrupts every record after
    it. `tools/train_ner.py` assembles the corpus from the directory.

    The record carries the provenance a later reviewer needs — digest, source
    filename, thread subject — because a training corpus outlives the run that
    produced it and its errors are only findable through the original."""

    SUBDIR: str = "annotations"
    META_KEYS: tuple = (
        "digest",
        MailKeys.raw("subject"),
        MailKeys.DATE_SENT,
        MailKeys.SENDER,
        "annotation_count",
    )

    def record(self, document: FileDocument) -> Dict[str, Any]:
        metadata = document.metadata or {}
        spans: List[Dict[str, Any]] = list(metadata.get("annotations") or [])
        return {
            "id": MailParser.compose(metadata, str(document.filename or "")),
            "filename": str(document.filename or ""),
            "text": document.content or "",
            "spans": spans,
            "meta": {key: metadata.get(key) for key in self.META_KEYS if metadata.get(key)},
        }

    def execute(self, caller: IWattleflow, facade: ITarget, **kwargs: Any) -> bool:
        self.debug(msg=Event.Write.name, step=Event.Started.name, caller=caller, facade=facade)
        output = None
        try:
            Attribute.evaluate(caller=self, target=caller, expected_type=IRepository)
            Attribute.evaluate(caller=self, target=facade, expected_type=ITarget)

            driver = kwargs.get("driver") or getattr(caller, "driver", None)
            assert driver is not None, (
                "Driver not available — strategy requires RepositoryWithDriver"
            )

            document: FileDocument = facade.request()

            # Attachment children carry a payload, not annotated text.
            if document.metadata.get(MailKeys.IS_ATTACHMENT):
                return False

            record = self.record(document)
            if not record["text"].strip():
                self.warning(
                    msg=Event.Write.name, step=Event.Check.name, reason="no text to annotate"
                )
                return False

            if not record["spans"]:
                # Kept deliberately: a document with no entity is a negative
                # example, and a corpus of positives only teaches over-tagging.
                self.debug(
                    msg=Event.Write.name, step=Event.Check.name, reason="no spans, negative example"
                )

            formatter = FormatterFactory.create(FileType.JSON)
            payload = formatter.serialise(json.dumps(record, ensure_ascii=False, indent=None))
            output = driver.write(
                payload,
                filename=record["id"],
                suffix=formatter.SUFFIX,
                subdir=kwargs.get("annotations_subdir") or self.SUBDIR,
                mkdir=True,
            )
            document.update_metadata("annotations_filename", output)
            return True
        except AssertionError as e:
            error = f"Assertion: {str(e)}"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        finally:
            self.debug(msg=Event.Write.name, step=Event.Completed.name, output=str(output))


# ----------------------------------------------------------------------------#
# endregion Classes                                                           #
# ----------------------------------------------------------------------------#

__all__ = ["WriteEntityAnnotations"]
