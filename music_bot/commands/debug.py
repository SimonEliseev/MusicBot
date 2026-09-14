from __future__ import annotations

from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands


class DebugCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="playtest",
        description="Проиграть локальный test.mp3",
    )
    async def playtest(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild.voice_client is None:
            await interaction.response.send_message(
                "Сначала используй /join.",
                ephemeral=True,
            )
            return

        test_file = Path("test.mp3")
        if not test_file.exists():
            await interaction.response.send_message(
                "Файл test.mp3 не найден в корне проекта.",
                ephemeral=True,
            )
            return

        voice_client = interaction.guild.voice_client
        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()

        voice_client.play(discord.FFmpegPCMAudio(str(test_file)))
        await interaction.response.send_message("▶️ Воспроизвожу test.mp3")
