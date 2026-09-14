from __future__ import annotations

import discord
from discord.ext import commands

from music_bot.commands.debug import DebugCog
from music_bot.commands.music import MusicCog
from music_bot.config import Settings
from music_bot.music.player import MusicPlayer
from music_bot.providers.hitmo import HitmoProvider


class MusicBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.voice_states = True

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
        )

        self.settings = settings
        self.provider = HitmoProvider()
        self.player = MusicPlayer(
            client=self,
            idle_timeout_seconds=settings.idle_timeout_seconds,
        )

    async def setup_hook(self) -> None:
        await self.add_cog(
            MusicCog(
                bot=self,
                settings=self.settings,
                provider=self.provider,
                player=self.player,
            )
        )
        await self.add_cog(DebugCog(self))

        guild = discord.Object(id=self.settings.guild_id)
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)

        print(f"Slash-команды зарегистрированы: {len(synced)}")

    async def on_ready(self) -> None:
        print(f"Бот запущен: {self.user}")

    async def close(self) -> None:
        self.provider.close()
        await super().close()


def run() -> None:
    settings = Settings.from_env()
    bot = MusicBot(settings)
    bot.run(settings.discord_token)
