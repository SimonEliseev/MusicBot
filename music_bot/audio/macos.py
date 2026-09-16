from __future__ import annotations

from pathlib import Path

import discord

from music_bot.audio.process_pcm import (
    ProcessPCMSource,
)


class MacOSAudioCapture:
    def __init__(self) -> None:
        project_root = (
            Path(__file__)
            .resolve()
            .parents[2]
        )

        self.helper_path = (
            project_root
            / "native"
            / "macos"
            / "bin"
            / "chrome_audio_tap"
        )

    def create_source(
        self,
    ) -> discord.AudioSource:
        if not self.helper_path.exists():
            raise RuntimeError(
                "macOS Chrome audio helper не найден: "
                f"{self.helper_path}"
            )

        return ProcessPCMSource(
            executable=self.helper_path,
        )

    async def close(self) -> None:
        pass