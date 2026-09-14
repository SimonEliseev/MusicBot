from __future__ import annotations

import discord

from music_bot.music.models import QueueItem, TrackCandidate
from music_bot.music.player import MusicPlayer


class TrackSelectButton(discord.ui.Button):
    def __init__(
        self,
        number: int,
        track: TrackCandidate,
        player: MusicPlayer,
    ) -> None:
        super().__init__(
            label=str(number),
            style=discord.ButtonStyle.primary,
        )
        self.track = track
        self.player = player

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, TrackSelectView):
            return

        voice_state = getattr(interaction.user, "voice", None)
        if voice_state is None or voice_state.channel is None:
            await interaction.response.send_message(
                "Сначала зайди в голосовой канал.",
                ephemeral=True,
            )
            return

        if interaction.guild is None or interaction.channel_id is None:
            await interaction.response.send_message(
                "Эта команда доступна только на сервере.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        channel = voice_state.channel
        voice_client = interaction.guild.voice_client

        if voice_client is None:
            voice_client = await channel.connect()
        elif voice_client.channel != channel:
            await voice_client.move_to(channel)

        item = QueueItem(
            track=self.track,
            channel_id=interaction.channel_id,
        )
        position = self.player.enqueue_or_play(voice_client, item)

        for button in view.children:
            button.disabled = True
        self.style = discord.ButtonStyle.success

        if position is None:
            embed = discord.Embed(
                title="▶️ Сейчас играет",
                description=f"**{self.track.display_name}**",
            )
        else:
            embed = discord.Embed(
                title="➕ Добавлено в очередь",
                description=f"**{self.track.display_name}**",
            )
            embed.add_field(name="Позиция", value=str(position))

        if self.track.duration:
            embed.add_field(name="Длительность", value=self.track.duration)

        await interaction.message.edit(embed=embed, view=view)


class TrackSelectView(discord.ui.View):
    def __init__(
        self,
        tracks: list[TrackCandidate],
        requester_id: int,
        player: MusicPlayer,
    ) -> None:
        super().__init__(timeout=60)
        self.requester_id = requester_id

        for number, track in enumerate(tracks, start=1):
            self.add_item(
                TrackSelectButton(
                    number=number,
                    track=track,
                    player=player,
                )
            )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.requester_id:
            return True

        await interaction.response.send_message(
            "Выбирать трек может только пользователь, который запустил поиск.",
            ephemeral=True,
        )
        return False
