# Module name: documents/file.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# region Imports                                                              #
# --------------------------------------------------------------------------- #

from __future__ import annotations
from abc import ABC
from datetime import datetime
from os import path, stat
from pathlib import Path
from stat import filemode
from wattleflow.concrete import Document
from wattleflow.enums.event import Event

# --------------------------------------------------------------------------- #
# endregion Imports                                                           #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# region Classes                                                              #
# --------------------------------------------------------------------------- #


class FileDocument(Document[str | Path], ABC):
    def __init__(self, filename: str | Path, **kwargs):
        super().__init__(content="", **kwargs)
        self.update_metadata(key="filename", value=filename)
        self.update_file_metadata()

    @property
    def filename(self) -> str:
        return str(self.metadata.get("filename", ""))

    @property
    def size(self) -> int:
        return int(self._metadata.get("size", 0))

    def refresh_metadata(self):
        filename = self.filename if isinstance(self.filename, Path) else Path(self.filename)
        if filename.exists():
            self.update_file_metadata()
        else:
            self.error(
                msg=Event.Update.name,
                reason="Cannot refresh metadata.",
                error="File does not exist.",
                filename=self.filename,
            )

    def update_filename(self, filename: str) -> None:
        self.update_metadata(key="filename", value=filename)

    def update_file_metadata(self) -> None:
        if not path.exists(self.filename):
            reason = "File does not exist yet: metadata will be empty!"
            self.warning(
                msg=Event.Updating.name,
                filename=self.filename,
                reason=reason,
            )
            return

        try:
            stats = stat(self.filename)
            self.update_metadata("size", stats.st_size)
            self.update_metadata("mtime", datetime.fromtimestamp(stats.st_mtime))
            self.update_metadata("atime", datetime.fromtimestamp(stats.st_atime))
            self.update_metadata("ctime", datetime.fromtimestamp(stats.st_ctime))
            self.update_metadata("file_permissions", filemode(stats.st_mode))
            self.update_metadata("uid", stats.st_uid)
            self.update_metadata("gid", stats.st_gid)
        except FileNotFoundError as e:
            reason = "%s.update_file_metadata not found: %s" % (
                self.__class__.__name__,
                str(e),
            )
            self.error(
                msg=Event.Update.name,
                step=Event.Failed.name,
                filename=self.filename,
                reason=reason,
            )
        except PermissionError as e:
            self.error(
                msg=Event.Update.name,
                reason="Permission denied for file.",
                filename=self.filename,
                error=str(e),
            )
        except Exception as e:
            self.error(
                msg=Event.Update.name,
                reason="Unexpected error while accessing file.",
                file=self.filename,
                error=str(e),
            )


# --------------------------------------------------------------------------- #
# endregion Classes                                                           #
# --------------------------------------------------------------------------- #


__all__ = ["FileDocument"]
