# Module name: strategies/documents/image.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence

# ----------------------------------------------------------------------------#
# region Import                                                               #
# ----------------------------------------------------------------------------#
from __future__ import annotations
import io
from pathlib import Path
from typing import Any, Dict, List, Tuple
from wattleflow.core import IRepository, ITarget, IWattleflow
from wattleflow.concrete import StrategyWrite
from wattleflow.concrete.exception import StrategyException
from wattleflow.enums.event import Event
from wattleflow.enums.imageformat import ImageFormat
from wattleflow.documents.file import FileDocument
from wattleflow.concrete.helpers import Attribute
from wattleflow.helpers.image_security import ImageSecurityGuard
# ----------------------------------------------------------------------------#
# endregion Import                                                            #
# ----------------------------------------------------------------------------#

# ----------------------------------------------------------------------------#
# region Types                                                                #
# ----------------------------------------------------------------------------#
# Accepted suffixes, Pillow format names and the output suffix per format all
# come from ImageFormat (enums/imageformat.py) — this module names none of them.
SpanList = List[Dict[str, Any]]
# ----------------------------------------------------------------------------#
# endregion Types                                                             #
# ----------------------------------------------------------------------------#

# ----------------------------------------------------------------------------#
# region Classes                                                              #
# ----------------------------------------------------------------------------#


class WriteRedactedImage(StrategyWrite):
    """Apply the standard ``redact_spans`` metadata to a raster image and write
    the redacted image.

    Consumes the SAME span schema as the PDF redaction strategies —
    ``[{"page", "bbox", "replacement", "text"}]`` produced by any reduct
    pipeline (e.g. ``PipelineReductSpans``). For images ``page`` is ignored and
    ``bbox`` is in pixels; each span is blacked out."""

    def execute(self, caller: IWattleflow, facade: ITarget, **kwargs: Any) -> bool:
        self.debug(msg=Event.Write.name, step=Event.Started.name, caller=caller, facade=facade)
        try:
            Attribute.evaluate(caller=self, target=caller, expected_type=IRepository)
            Attribute.evaluate(caller=self, target=facade, expected_type=ITarget)

            driver = kwargs.get("driver") or getattr(caller, "driver", None)
            assert driver is not None, (
                "Driver not available — strategy requires RepositoryWithDriver"
            )

            document: FileDocument = facade.request()
            source_path = Path(document.filename)

            if not ImageFormat.accepts(source_path.suffix):
                self.debug(
                    msg=Event.Write.name, step=Event.Check.name, reason="non-image source, skipped"
                )
                return False

            spans: SpanList = list(document.metadata.get("redact_spans") or [])
            if not spans:
                self.debug(
                    msg=Event.Write.name,
                    step=Event.Check.name,
                    reason="no redact_spans yet, skipped",
                )
                return False

            payload, suffix = self._apply(source_path, spans)
            caller_name = getattr(caller, "name", caller.__class__.__name__)
            output = driver.write(
                payload,
                filename=f"{source_path.stem}.{caller_name}",
                suffix=suffix,
                mkdir=True,
            )
            document.update_metadata("storage_filename", output)

            self.debug(
                msg=Event.Write.name,
                step=Event.Completed.name,
                output=str(output),
                spans=len(spans),
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

    @staticmethod
    def _apply(source_path: Path, spans: SpanList) -> Tuple[bytes, str]:
        # safe_open validates magic/format/size before Pillow decodes any pixels.
        from PIL import ImageDraw

        image = ImageSecurityGuard.safe_open(source_path, expected=tuple(ImageFormat))
        fmt = image.format or "PNG"
        image = image.convert("RGB")
        draw = ImageDraw.Draw(image)
        for span in spans:
            bbox = span.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            x0, y0, x1, y1 = bbox
            draw.rectangle([x0, y0, x1, y1], fill=(0, 0, 0))

        # Preserve the source format; fall back to PNG for anything unexpected.
        target = ImageFormat.parse(fmt) or ImageFormat.PNG
        buffer = io.BytesIO()
        image.save(buffer, format=target.name)
        return buffer.getvalue(), target.suffix


# ----------------------------------------------------------------------------#
# endregion Classes                                                           #
# ----------------------------------------------------------------------------#
