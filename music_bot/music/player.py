from __future__ import annotations

import asyncio
from collections import defaultdict, deque

import discord

from music_bot.music.models import QueueItem
from music_bot.providers.hitmo import USER_AGENT


class MusicPlayer:
    def __init__(
        self,
        client: discord.Client,
        idle_timeout_seconds: int,
    ) -> None:
        self.client = client
        self.idle_timeout_seconds = idle_timeout_seconds
        self.queues: defaultdict[int, deque[QueueItem]] = defaultdict(deque)
        self.current_tracks: dict[int, QueueItem] = {}
        self.idle_tasks: dict[int, asyncio.Task[None]] = {}

    def get_queue(self, guild_id: int) -> deque[QueueItem]:
        return self.queues[guild_id]

    def get_current(self, guild_id: int) -> QueueItem | None:
        return self.current_tracks.get(guild_id)

    def start_live_source(
        self,
        voice_client: discord.VoiceClient,
        source: discord.AudioSource,
    ) -> None:
        guild_id = voice_client.guild.id

        self.cancel_idle_timer(guild_id)

        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()

        voice_client.play(source)

    def enqueue_or_play(
        self,
        voice_client: discord.VoiceClient,
        item: QueueItem,
    ) -> int | None:
        guild_id = voice_client.guild.id

        if voice_client.is_playing() or voice_client.is_paused():
            queue = self.queues[guild_id]
            queue.append(item)
            return len(queue)

        self.start_track(voice_client, item)
        return None

    def start_track(
        self,
        voice_client: discord.VoiceClient,
        item: QueueItem,
    ) -> None:
        guild_id = voice_client.guild.id
        self.cancel_idle_timer(guild_id)
        self.current_tracks[guild_id] = item

        source = discord.FFmpegPCMAudio(
            item.track.stream_url,
            before_options=(
                "-reconnect 1 "
                "-reconnect_streamed 1 "
                "-reconnect_delay_max 5 "
                f'-user_agent "{USER_AGENT}"'
            ),
            options="-vn",
        )

        loop = asyncio.get_running_loop()

        def after_playback(error: Exception | None) -> None:
            if error:
                print(f"Playback error: {error}")

            asyncio.run_coroutine_threadsafe(
                self.play_next(guild_id),
                loop,
            )

        voice_client.play(source, after=after_playback)

    async def play_next(self, guild_id: int) -> None:
        guild = self.client.get_guild(guild_id)
        if guild is None:
            return

        voice_client = guild.voice_client
        if voice_client is None:
            return

        queue = self.queues[guild_id]
        if not queue:
            self.current_tracks.pop(guild_id, None)
            self.schedule_idle_disconnect(guild_id)
            return

        item = queue.popleft()
        self.start_track(voice_client, item)

        channel = self.client.get_channel(item.channel_id)
        if channel is not None and hasattr(channel, "send"):
            duration = item.track.duration or "?:??"
            await channel.send(
                f"▶️ **Сейчас играет:** "
                f"{item.track.display_name} · `{duration}`"
            )

    def clear(self, guild_id: int) -> None:
        self.queues[guild_id].clear()
        self.current_tracks.pop(guild_id, None)

    def stop(self, voice_client: discord.VoiceClient) -> None:
        guild_id = voice_client.guild.id
        self.clear(guild_id)

        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()
        else:
            self.schedule_idle_disconnect(guild_id)

    def skip(self, voice_client: discord.VoiceClient) -> bool:
        if not voice_client.is_playing() and not voice_client.is_paused():
            return False

        voice_client.stop()
        return True

    async def disconnect(self, voice_client: discord.VoiceClient) -> None:
        guild_id = voice_client.guild.id
        self.cancel_idle_timer(guild_id)
        self.clear(guild_id)
        await voice_client.disconnect()

    def mark_idle(self, guild_id: int) -> None:
        guild = self.client.get_guild(guild_id)
        if guild is None or guild.voice_client is None:
            return

        voice_client = guild.voice_client
        if (
            voice_client.is_playing()
            or voice_client.is_paused()
            or self.queues[guild_id]
        ):
            return

        self.schedule_idle_disconnect(guild_id)

    def cancel_idle_timer(self, guild_id: int) -> None:
        task = self.idle_tasks.pop(guild_id, None)
        if task and not task.done():
            task.cancel()

    def schedule_idle_disconnect(self, guild_id: int) -> None:
        self.cancel_idle_timer(guild_id)
        self.idle_tasks[guild_id] = asyncio.create_task(
            self._idle_disconnect(guild_id)
        )

    async def _idle_disconnect(self, guild_id: int) -> None:
        try:
            await asyncio.sleep(self.idle_timeout_seconds)

            guild = self.client.get_guild(guild_id)
            if guild is None or guild.voice_client is None:
                return

            voice_client = guild.voice_client
            if (
                voice_client.is_playing()
                or voice_client.is_paused()
                or self.queues[guild_id]
            ):
                return

            print(f"Guild {guild.name}: отключаюсь из-за бездействия")
            self.current_tracks.pop(guild_id, None)
            await voice_client.disconnect()
        except asyncio.CancelledError:
            pass
        finally:
            current_task = asyncio.current_task()
            if self.idle_tasks.get(guild_id) is current_task:
                self.idle_tasks.pop(guild_id, None)
