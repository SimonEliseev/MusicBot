from __future__ import annotations

import discord

from music_bot.audio.live_ffmpeg import LiveFFmpegSource


class MacOSAudioCapture:
    def __init__(
        self,
        device_name: str = "BlackHole 2ch",
        ffmpeg_executable: str = "ffmpeg",
    ) -> None:
        self.device_name = device_name
        self.ffmpeg_executable = ffmpeg_executable

    def create_source(self) -> discord.AudioSource:
        return LiveFFmpegSource(
            executable=self.ffmpeg_executable,
            input_args=[
                "-f",
                "avfoundation",
                "-thread_queue_size",
                "512",
                "-i",
                f":{self.device_name}",
            ],
        )

    async def close(self) -> None:
        pass