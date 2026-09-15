from __future__ import annotations

import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from music_bot.config import Settings
from music_bot.music.player import MusicPlayer
from music_bot.providers.hitmo import HitmoProvider
from music_bot.ui.track_select import TrackSelectView
from music_bot.audio.windows import WindowsAudioCapture
from music_bot.providers.vk.player import VKPlayer

class MusicCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        settings: Settings,
        provider: HitmoProvider,
        player: MusicPlayer,
    ) -> None:
        self.bot = bot
        self.settings = settings
        self.provider = provider
        self.player = player

        self.vk_player = VKPlayer()
        self.windows_audio = WindowsAudioCapture()

    @app_commands.command(name="ping", description="Проверить работу бота")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message("Pong!")

    async def cog_unload(self) -> None:
        await self.player.close()

    @app_commands.command(
        name="help",
        description="Показать список команд бота",
    )
    async def help(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="🎵 Команды бота",
            description=(
                "`/play <запрос>` — найти и выбрать трек\n"
                "`/queue` — показать очередь воспроизведения\n"
                "`/skip` — пропустить текущий трек\n"
                "`/stop` — остановить музыку и очистить очередь\n"
                "`/join` — подключить бота к твоему голосовому каналу\n"
                "`/leave` — отключить бота от голосового канала\n"
                "`/ping` — проверить работу бота"
            ),
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )

    @app_commands.command(
        name="join",
        description="Подключить бота к твоему голосовому каналу",
    )
    async def join(self, interaction: discord.Interaction) -> None:
        voice_state = getattr(interaction.user, "voice", None)
        if voice_state is None or voice_state.channel is None:
            await interaction.response.send_message(
                "Сначала зайди в голосовой канал.",
                ephemeral=True,
            )
            return

        if interaction.guild is None:
            await interaction.response.send_message(
                "Эта команда доступна только на сервере.",
                ephemeral=True,
            )
            return

        channel = voice_state.channel
        voice_client = interaction.guild.voice_client

        if voice_client is None:
            await channel.connect()
        elif voice_client.channel != channel:
            await voice_client.move_to(channel)

        self.player.mark_idle(interaction.guild.id)

        await interaction.response.send_message(
            f"Подключился к **{channel.name}**"
        )

    @app_commands.command(
        name="leave",
        description="Отключить бота от голосового канала",
    )
    async def leave(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild.voice_client is None:
            await interaction.response.send_message(
                "Я сейчас не в голосовом канале.",
                ephemeral=True,
            )
            return

        await self.player.disconnect(interaction.guild.voice_client)
        await interaction.response.send_message("Отключился.")

    @app_commands.command(
        name="stop",
        description="Остановить воспроизведение и очистить очередь",
    )
    async def stop(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild.voice_client is None:
            await interaction.response.send_message(
                "Я не подключен к голосовому каналу.",
                ephemeral=True,
            )
            return

        voice_client = interaction.guild.voice_client
        if not voice_client.is_playing() and not voice_client.is_paused():
            await interaction.response.send_message(
                "Сейчас ничего не играет.",
                ephemeral=True,
            )
            return

        await self.player.stop(voice_client)
        await interaction.response.send_message("⏹ Воспроизведение остановлено.")

    @app_commands.command(
    name="play",
    description="Найти и включить трек",
    )
    @app_commands.describe(
        query="Название трека или исполнитель",
        source="Источник музыки",
    )
    @app_commands.choices(
        source=[
            app_commands.Choice(
                name="Hitmo",
                value="hitmo",
            ),
            app_commands.Choice(
                name="VK Музыка",
                value="vk",
            ),
        ]
    )
    async def play(
        self,
        interaction: discord.Interaction,
        query: str,
        source: app_commands.Choice[str] | None = None,
    ) -> None:
        await interaction.response.defer()

        source_name = (
            source.value
            if source is not None
            else "hitmo"
        )

        try:
            if source_name == "vk":
                tracks = await self.player.search_vk(
                    query,
                    self.settings.search_limit,
                )
            else:
                tracks = await asyncio.to_thread(
                    self.provider.search,
                    query,
                    self.settings.search_limit,
                )

        except Exception as exc:
            print("SEARCH ERROR:", repr(exc))

            await interaction.followup.send(
                f"Ошибка поиска: `{exc}`"
            )
            return

        if not tracks:
            await interaction.followup.send(
                "Ничего не найдено."
            )
            return

        lines = [
            (
                f"**{number}. {track.display_name}** "
                f"· `{track.duration or '?:??'}`"
            )
            for number, track in enumerate(
                tracks,
                start=1,
            )
        ]

        provider_title = (
            "VK"
            if source_name == "vk"
            else "Hitmo"
        )

        embed = discord.Embed(
            title=f"🔎 {provider_title}: {query}",
            description="\n".join(lines),
        )

        embed.set_footer(
            text="Выбери трек кнопкой ниже"
        )

        view = TrackSelectView(
            tracks=tracks,
            requester_id=interaction.user.id,
            player=self.player,
        )

        await interaction.followup.send(
            embed=embed,
            view=view,
        )

    @app_commands.command(
        name="queue",
        description="Показать очередь воспроизведения",
    )
    async def show_queue(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                "Эта команда доступна только на сервере.",
                ephemeral=True,
            )
            return

        guild_id = interaction.guild.id
        current = self.player.get_current(guild_id)
        queue = self.player.get_queue(guild_id)
        lines: list[str] = []

        if current:
            duration = current.track.duration or "?:??"
            lines.append(
                f"▶️ **Сейчас:** {current.track.display_name} · `{duration}`"
            )

        if queue:
            lines.append("")
            lines.extend(
                f"**{number}.** {item.track.display_name} · "
                f"`{item.track.duration or '?:??'}`"
                for number, item in enumerate(queue, start=1)
            )

        if not lines:
            await interaction.response.send_message(
                "Очередь пуста.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=discord.Embed(
                title="🎵 Очередь",
                description="\n".join(lines),
            )
        )

    @app_commands.command(
        name="skip",
        description="Пропустить текущий трек",
    )
    async def skip(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.guild.voice_client is None:
            await interaction.response.send_message(
                "Сейчас ничего не играет.",
                ephemeral=True,
            )
            return

        if not await self.player.skip(interaction.guild.voice_client):
            await interaction.response.send_message(
                "Сейчас ничего не играет.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message("⏭ Трек пропущен.")
