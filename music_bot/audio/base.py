from __future__ import annotations

from typing import Protocol

import discord


class AudioCapture(Protocol):
    def create_source(self) -> discord.AudioSource:
        ...

    async def close(self) -> None:
        ...