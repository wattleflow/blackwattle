# Module name: strategies/documents/json.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, Optional, Union
from wattleflow.core import IBlackboard, IRepository, ITarget, IWattleflow
from wattleflow.concrete import DocumentFacade, StrategyCreate, StrategyRead, StrategyWrite
from wattleflow.concrete.exception import StrategyException
from wattleflow.enums.event import Event
from wattleflow.enums.filetype import FileType
from wattleflow.documents.file import FileDocument
from wattleflow.concrete.helpers import Attribute
from wattleflow.helpers.dtime import Now
from wattleflow.helpers.formatters.factory import FormatterFactory

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Constants                                                            #
# --------------------------------------------------------------------------- #
DEFAULT_JSON_SUFFIX = ".json"
DEFAULT_INDENT = 2
DEFAULT_ENCODING = "utf-8"
# --------------------------------------------------------------------------- #
# endregion Constants                                                         #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Helpers                                                              #
# --------------------------------------------------------------------------- #


class Serialise(IWattleflow):
    def _json_safe(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(k): self._json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._json_safe(v) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, bytes):
            return value.decode(DEFAULT_ENCODING, errors="replace")
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    def _serialise(self, payload: Any, indent: Optional[int], sort_keys: bool) -> str:
        return json.dumps(
            self._json_safe(payload),
            indent=indent,
            sort_keys=sort_keys,
            ensure_ascii=False,
        )


# --------------------------------------------------------------------------- #
# endregion Helpers                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Strategies                                                           #
# --------------------------------------------------------------------------- #


class CreateJsonDocument(StrategyCreate, Serialise):
    def execute(self, caller: IWattleflow, **kwargs) -> Optional[ITarget]:
        try:
            self.debug(msg=Event.Create.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IBlackboard), "Expected IBlackboard. Found %s" % (
                type(caller).__name__
            )

            Attribute.mandatory(self, "filename", str, **kwargs)
            Attribute.mandatory(self, "content", str, **kwargs)

            document: FileDocument = FileDocument(filename=self.filename)

            # if not self.filename.lower().endswith(DEFAULT_JSON_SUFFIX):
            #     filename = str(Path(self.filename).with_suffix(DEFAULT_JSON_SUFFIX))

            # metadata
            document.update_metadata("created_by", self.name)
            document.update_metadata("created_at", Now.utc())
            document.update_metadata("caller", caller.name)
            document.update_metadata("filename", self.filename)
            document.update_metadata("source_format", "json")

            for key, value in kwargs.items():
                if key in ("caller", "filename", "content", "schema", "processor", "blackboard"):
                    continue
                document.update_metadata(f"kwargs_{key}", value)

            if not document.size > 0:
                self.warning(
                    msg=Event.Create.name,
                    step=Event.Check.name,
                    reason="JSON document file's feeling a bit empty today!",
                    document=document,
                )

            indent = kwargs.get("indent", DEFAULT_INDENT)
            sort_keys = bool(kwargs.get("sort_keys", False))
            document.update_metadata("indent", indent)
            document.update_metadata("sort_keys", sort_keys)

            raw = kwargs["content"]
            if isinstance(raw, str):
                parsed = json.loads(raw)
                text = self._serialise(parsed, indent=indent, sort_keys=sort_keys)
            else:
                parsed = raw
                text = self._serialise(raw, indent=indent, sort_keys=sort_keys)

            document.update_metadata("json_parsed", parsed)
            document.update_content(text)

            self.debug(
                msg=Event.Create.name,
                step=Event.Completed.name,
                document=document.identifier,
                filename=self.filename,
                size=document.size,
            )

            return DocumentFacade(document)
        except AssertionError as e:
            error = f"Assertion: {str(e)}"
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        except json.JSONDecodeError as e:
            error = f"Invalid JSON content: {str(e)}"
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Create.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e


class ReadJsonDocument(StrategyRead, Serialise):
    """Read a JSON file via the repository driver and wrap it in :class:`FileDocument`.

    Expected ``kwargs``:
        identifier : Absolute or repository-relative path to the ``.json`` file.
        driver     : Provided by ``RepositoryWithDriver``; performs raw text read.
    """

    def execute(self, caller: IWattleflow, **kwargs) -> Optional[ITarget]:
        try:
            self.debug(msg=Event.Read.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IRepository), "Expected IRepository. Found %s" % (
                type(caller).__name__
            )
            Attribute.mandatory(self, "identifier", str, **kwargs)

            driver = kwargs.get("driver") or getattr(caller, "driver", None)
            assert driver is not None, (
                "Driver not in kwargs — strategy requires RepositoryWithDriver"
            )

            uri: str = kwargs["identifier"]
            encoding = kwargs.get("encoding", DEFAULT_ENCODING)
            raw_text: str = driver.read(uri=uri, encoding=encoding)
            if not isinstance(raw_text, str):
                # Driver fallbacks (e.g. pandas) may return non-string; coerce safely.
                raw_text = str(raw_text)

            parsed = json.loads(raw_text)
            # Re-serialise so on-disk style stays consistent regardless of source formatting.
            indent = kwargs.get("indent", DEFAULT_INDENT)
            sort_keys = bool(kwargs.get("sort_keys", False))
            text = self._serialise(parsed, indent=indent, sort_keys=sort_keys)

            document = FileDocument(filename=uri)
            document.update_content(text)
            document.update_metadata("source_uri", uri)
            document.update_metadata("json_parsed", parsed)

            self.debug(
                msg=Event.Read.name,
                step=Event.Completed.name,
                document=document.identifier,
                size=document.size,
            )
            return DocumentFacade(document)
        except AssertionError as e:
            error = f"Assertion: {str(e)}"
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        except json.JSONDecodeError as e:
            error = f"Invalid JSON at {kwargs.get('identifier')!r}: {str(e)}"
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e


class WriteJsonDocument(StrategyWrite, Serialise):
    def execute(self, caller: IWattleflow, facade: ITarget, **kwargs) -> bool:
        try:
            self.debug(msg=Event.Write.name, step=Event.Started.name, kwargs=kwargs)
            assert isinstance(caller, IRepository), "Expected IRepository. Found %s" % (
                type(caller).__name__
            )
            assert isinstance(facade, ITarget), "Expected ITarget. Found %s" % (
                type(facade).__name__
            )

            driver = kwargs.get("driver") or getattr(caller, "driver", None)
            assert driver is not None, (
                "Driver not in kwargs — strategy requires RepositoryWithDriver"
            )

            document: FileDocument = facade.request()
            indent = kwargs.pop("indent", DEFAULT_INDENT)
            sort_keys = bool(kwargs.pop("sort_keys", False))
            parsed = document.metadata.get("json_parsed")

            if parsed is not None:
                text = self._serialise(parsed, indent=indent, sort_keys=sort_keys)
            else:
                content = document.content or ""
                if not isinstance(content, str) or not content.strip():
                    self.warning(
                        msg=Event.Write.name,
                        step=Event.Check.name,
                        reason="JSON content is empty.",
                        document=document,
                    )
                    return False
                text = self._serialise(json.loads(content), indent=indent, sort_keys=sort_keys)

            name = document.metadata.get("filename", document.identifier)
            filename = Path(str(name)).with_suffix(DEFAULT_JSON_SUFFIX).name

            formatter = FormatterFactory.create(FileType.JSON)
            payload = formatter.render(content=text)
            output = driver.write(
                payload,
                filename=filename,
                suffix=formatter.SUFFIX,
            )

            document.update_metadata("output", output)
            document.update_metadata("stored_by", self.name)
            document.update_metadata("stored_at", Now.utc())
            document.update_metadata("document_utc", document.utc_time_stamp())
            document.update_metadata("source_format", formatter.SUFFIX)

            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                document=document.identifier,
                output=str(output),
                size=len(text),
            )
            return True
        except AssertionError as e:
            error = f"Assertion: {str(e)}"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        except json.JSONDecodeError as e:
            error = f"Invalid JSON on document: {str(e)}"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Write.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e


# --------------------------------------------------------------------------- #
# endregion Strategies                                                        #
# --------------------------------------------------------------------------- #


__all__ = ["CreateJsonDocument", "ReadJsonDocument", "WriteJsonDocument"]
