# Module name: strategies/helpers/huggingface.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
import shutil
from pathlib import Path
from wattleflow.core import IStrategy, IWattleflow
from wattleflow.concrete import Wattleflow
from wattleflow.concrete.exception import StrategyException
from wattleflow.concrete.helpers import Attribute
from wattleflow.enums.event import Event

# --------------------------------------------------------------------------- #
# endregion imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Strategy                                                             #
# --------------------------------------------------------------------------- #


class StrategyCopyHuggingfaceModels(Wattleflow, IStrategy):
    """Copy a local model cache tree (Hugging Face hub layout) to another root.

    Helper strategy, not a document strategy: there is no repository, facade or
    driver in play, so the only inputs are the two directories, taken from
    kwargs and validated through Attribute.mandatory:

        StrategyCopyHuggingfaceModels().execute(
            source_dir="~/.cache/huggingface/hub",
            destination_dir="/opt/models/hub",
        )

    Symlinks are followed (`copy2(follow_symlinks=True)`): a hub cache links
    snapshots to blobs, and the copy must stand on its own once the source is
    gone — at the cost of duplicating a blob shared by several snapshots.
    """

    @staticmethod
    def file_size(path: str | Path) -> str:
        if isinstance(path, str):
            path = Path(path)

        if path.exists() is False:
            raise FileNotFoundError(str(path.absolute()))

        size: float = float(path.stat().st_size)

        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.2f} {unit}"
            size /= 1024

        return f"{size:.2f} PB"

    def execute(self, caller: IWattleflow | None = None, **kwargs) -> bool:
        # kwargs go in as one value, never splatted: a caller key such as
        # `msg` or `exc_info` would collide with the audit call's own.
        self.debug(msg=Event.Execute.name, step=Event.Started.name, kwargs=kwargs)

        try:
            Attribute.mandatory(self, "source_dir", (str, Path), **kwargs)
            Attribute.mandatory(self, "destination_dir", (str, Path), **kwargs)

            source = Path(self.source_dir).expanduser()
            destination = Path(self.destination_dir).expanduser()

            self.debug(
                msg=Event.Copy.name,
                step=Event.Started.name,
                source=str(source),
                destination=str(destination),
            )

            if not source.exists() or not source.is_dir():
                error = f"Source directory not found or not a directory: {source}"
                self.debug(
                    msg=Event.Copy.name,
                    step=Event.Failed.name,
                    reason=error,
                    source=str(source),
                )
                raise FileNotFoundError(error)

            source = source.resolve()
            destination = destination.resolve()

            # A destination inside the source would be fed its own output:
            # rglob yields lazily, so freshly written files reappear as input.
            if destination == source or source in destination.parents:
                error = f"Destination is inside the source tree: {destination}"
                self.debug(
                    msg=Event.Copy.name,
                    step=Event.Failed.name,
                    reason=error,
                    source=str(source),
                    destination=str(destination),
                )
                raise ValueError(error)

            destination.mkdir(parents=True, exist_ok=True)

            count = 0
            for path in source.rglob("*"):  # rglob already recurses; no "**/*"
                target = destination / path.relative_to(source)

                if path.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target, follow_symlinks=True)
                self.debug(
                    msg=Event.Copied.name,
                    scope="file",
                    source=str(path),
                    target=str(target),
                )
                count += 1

            self.info(
                msg=Event.TaskCompleted.name,
                destination=str(destination),
                files=count,
            )
            return True
        except StrategyException:
            raise
        except Exception as e:
            error = f"{self.name} caught exception: {str(e)}"
            self.debug(msg=Event.Execute.name, step=Event.Failed.name, error=error)
            raise StrategyException(self, error=error, exc=e) from e


# --------------------------------------------------------------------------- #
# endregion Strategy                                                          #
# --------------------------------------------------------------------------- #

__all__ = ["StrategyCopyHuggingfaceModels"]
