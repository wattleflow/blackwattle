# Module name: processors/youtube.py
# Author: (wattleflow@outlook.com)
# Copyright: © 2022–2026 WattleFlow. All rights reserved.
# License: Apache 2 Licence


# --------------------------------------------------------------------------- #
# IMPORTANT: This test case requires the youtube_transcript_api library.      #
# Ensure you have it installed using:                                         #
#       pip install youtube_transcript_api                                    #
#                                                                             #
# The library is used to extract dataframes from excel worksheets.            #
# --------------------------------------------------------------------------- #

# ----------------------------------------------------------------------------#
# region Import                                                               #
# ----------------------------------------------------------------------------#
from __future__ import annotations
import re
from traceback import format_exc
from typing import Dict, Generator
from wattleflow.core import ITarget
from wattleflow.concrete import GenericProcessor
from wattleflow.concrete.exception import AuditException, ProcessorException
from wattleflow.enums.event import Event
# ----------------------------------------------------------------------------#
# endregion Import                                                            #
# ----------------------------------------------------------------------------#

# ----------------------------------------------------------------------------#
# region Exceptions                                                           #
# ----------------------------------------------------------------------------#


class YoutubeError(AuditException):
    pass


# ----------------------------------------------------------------------------#
# endregion Exceptions                                                        #
# ----------------------------------------------------------------------------#

# ----------------------------------------------------------------------------#
# region Processors                                                           #
# ----------------------------------------------------------------------------#


class YoutubeProcessor(GenericProcessor):
    ALLOWED = ["videos"]

    def _extract_video_id(self, url: str) -> str:
        self.debug(
            msg=Event.Processing.name,
            step=Event.Started.name,
            name="_extract_video_id",
            url=url,
        )
        match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11})", url)
        self.debug(
            msg=Event.Processing.name,
            step=Event.Completed.name,
            name="_extract_video_id",
            url=url,
        )

        return match.group(1) if match else ""

    def _fetch_metadata(self, url: str) -> Dict:
        self.debug(
            msg=Event.Processing.name,
            step=Event.Started.name,
            name="_fetch_metadata",
            url=url,
        )

        try:
            import yt_dlp
        except ImportError as e:
            self.debug(msg=Event.Read.name, step=Event.Failed.name, error=str(e))
            raise ModuleNotFoundError(
                "`yt_dlp` library is missing. Install:\n\tpip install yt-dlp"
            ) from e

        info = {}
        try:
            opts = {"quiet": True, "skip_download": True, "no_warnings": True}
            with yt_dlp.YoutubeDL(params=opts) as ydl:
                info = ydl.extract_info(url, download=False)

            self.debug(
                msg=Event.Processing.name,
                step=Event.Completed.name,
                name="_fetch_metadata",
                reason=info,
            )
            return info

        except Exception as e:
            self.debug(msg=Event.Error.name, step=Event.Failed.name, error=str(e))
            raise YoutubeError(caller=self, error="Failed to fetch metadata") from e

    def _fetch_transcript(self, video_id: str) -> object:
        try:
            from youtube_transcript_api._api import YouTubeTranscriptApi
            from youtube_transcript_api._transcripts import FetchedTranscript
        except ImportError as e:
            raise ModuleNotFoundError(
                "`youtube_transcript_api` library is missing.\n"
                "\tInstall: pip install youtube-transcript-api"
            ) from e

        try:
            transcript: FetchedTranscript = YouTubeTranscriptApi().fetch(video_id, languages=["en"])
            return transcript.to_raw_data()
        except Exception as e:
            self.debug(msg=Event.Error.name, step=Event.Failed.name, error=str(e))
            raise YoutubeError(caller=self, error="Failed to fetch transcript") from e

    def create_generator(self) -> Generator[ITarget, None, None]:
        self.debug(msg=Event.Generate.name, step=Event.Started.name)

        try:
            videos = list(self.videos or [])

            self.debug(msg=Event.Generate.name, videos=len(videos))

            for itm in videos:
                uri = itm.get("uri", None)
                self.debug(msg=Event.Generate.name, scope="item", uri=uri)
                try:
                    if uri is None:
                        continue

                    video_id = self._extract_video_id(uri)
                    if not video_id:
                        self.warning(
                            msg=Event.Generate.name,
                            step=Event.Check.name,
                            reason="Video ID could not be extracted.",
                            url=uri,
                        )
                        continue

                    metadata = self._fetch_metadata(uri)
                    content = self._fetch_transcript(video_id)

                    self.debug(
                        msg=Event.Generate.name,
                        scope="item",
                        no=self.cycle + 1,
                        uri=uri,
                        size=len(content),  # type: ignore
                    )

                    yield self.blackboard.create(
                        caller=self,
                        id=video_id,
                        uri=uri,
                        content=content,
                        metadata=metadata,
                    )

                except Exception as e:
                    error = f"Error: {str(e)}"
                    self.exception(
                        msg=Event.Generate.name,
                        step=Event.Failed.name,
                        error=error,
                    )
                    continue
        except Exception as e:
            error = f"Error: {str(e)}"
            self.debug(
                msg=Event.Generate.name,
                step=Event.Failed.name,
                error=error,
                trace=format_exc(),
            )
            raise ProcessorException(
                caller=self,
                error=error,
                exc=format_exc(),
            ) from e

        self.debug(
            msg=Event.Generate.name,
            step=Event.Completed.name,
            count=self.cycle,
        )


# ----------------------------------------------------------------------------#
# endregion Processors                                                        #
# ----------------------------------------------------------------------------#
