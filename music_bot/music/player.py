from __future__ import annotations

import asyncio
from collections import defaultdict, deque

import discord

from music_bot.music.models import QueueItem, TrackCandidate
from music_bot.providers.hitmo import USER_AGENT
from music_bot.providers.vk.player import VKPlayer, VKTrack

from music_bot.audio.factory import create_audio_capture
from music_bot.music.models import (
    MusicSource,
    QueueItem,
    TrackCandidate,
)


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
        self.live_end_tasks: dict[int, asyncio.Task[None]] = {}

        self.vk_player = VKPlayer()
        self.audio_capture = create_audio_capture()

    def get_queue(self, guild_id: int) -> deque[QueueItem]:
        return self.queues[guild_id]

    def get_current(self, guild_id: int) -> QueueItem | None:
        return self.current_tracks.get(guild_id)

    async def search_vk(
        self,
        query: str,
        limit: int,
    ) -> list[TrackCandidate]:
        if self.vk_player.page is None:
            await self.vk_player.start()

        tracks = await self.vk_player.search(
            query,
            limit=limit,
        )

        return [
            TrackCandidate(
                title=track.title,
                artist=track.artist,
                track_id=track.track_id,
                duration=track.duration,
                source=MusicSource.VK,
            )
            for track in tracks
        ]

    async def enqueue_or_play(
        self,
        voice_client: discord.VoiceClient,
        item: QueueItem,
    ) -> int | None:
        guild_id = voice_client.guild.id

        if voice_client.is_playing() or voice_client.is_paused():
            queue = self.queues[guild_id]
            queue.append(item)
            return len(queue)

        await self.start_track(
            voice_client,
            item,
        )

        return None

    async def start_track(
        self,
        voice_client: discord.VoiceClient,
        item: QueueItem,
    ) -> None:
        guild_id = voice_client.guild.id

        self.cancel_idle_timer(guild_id)
        self.cancel_live_end_timer(guild_id)

        self.current_tracks[guild_id] = item

        if item.track.source is MusicSource.VK:
            await self._start_vk_track(
                voice_client,
                item,
            )
        else:
            self._start_hitmo_track(
                voice_client,
                item,
            )

    def _start_hitmo_track(
        self,
        voice_client: discord.VoiceClient,
        item: QueueItem,
    ) -> None:
        if not item.track.stream_url:
            raise RuntimeError("У Hitmo-трека отсутствует stream_url")

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

        self._play_source(
            voice_client,
            source,
        )

    async def _start_vk_track(
        self,
        voice_client: discord.VoiceClient,
        item: QueueItem,
    ) -> None:
        if self.vk_player.page is None:
            await self.vk_player.start()

        if not item.track.track_id:
            raise RuntimeError(
                "У VK-трека отсутствует track_id"
            )

        query = f"{item.track.artist} {item.track.title}"

        vk_track = await self.vk_player.find_track(
            query=query,
            track_id=item.track.track_id,
        )

        source = self.audio_capture.create_source()

        try:
            await asyncio.sleep(0.2)
            await self.vk_player.play(vk_track)
        except Exception:
            source.cleanup()
            raise

        self._play_source(
            voice_client,
            source,
        )

        duration_seconds = self._duration_to_seconds(
            item.track.duration
        )

        if duration_seconds is not None:
            guild_id = voice_client.guild.id

            self.live_end_tasks[guild_id] = asyncio.create_task(
                self._finish_live_track_after(
                    guild_id=guild_id,
                    voice_client=voice_client,
                    item=item,
                    seconds=duration_seconds,
                )
            )

    def _play_source(
        self,
        voice_client: discord.VoiceClient,
        source: discord.AudioSource,
    ) -> None:
        guild_id = voice_client.guild.id
        loop = asyncio.get_running_loop()

        def after_playback(
            error: Exception | None,
        ) -> None:
            if error:
                print(f"Playback error: {error}")

            asyncio.run_coroutine_threadsafe(
                self.play_next(guild_id),
                loop,
            )

        voice_client.play(
            source,
            after=after_playback,
        )

    async def play_next(
        self,
        guild_id: int,
    ) -> None:
        guild = self.client.get_guild(guild_id)

        if guild is None:
            return

        voice_client = guild.voice_client

        if voice_client is None:
            return

        self.cancel_live_end_timer(guild_id)
        self.current_tracks.pop(guild_id, None)

        queue = self.queues[guild_id]

        if not queue:
            self.schedule_idle_disconnect(guild_id)
            return

        item = queue.popleft()

        try:
            await self.start_track(
                voice_client,
                item,
            )
        except Exception as exc:
            print(
                f"Не удалось запустить "
                f"{item.track.display_name}: {exc}"
            )

            await self.play_next(guild_id)
            return

        channel = self.client.get_channel(
            item.channel_id
        )

        if channel is not None and hasattr(channel, "send"):
            duration = item.track.duration or "?:??"

            provider = (
                "VK"
                if item.track.source is MusicSource.VK
                else "Hitmo"
            )

            await channel.send(
                f"▶️ **Сейчас играет [{provider}]:** "
                f"{item.track.display_name} · "
                f"`{duration}`"
            )

    async def stop(
        self,
        voice_client: discord.VoiceClient,
    ) -> None:
        guild_id = voice_client.guild.id

        await self._pause_vk_if_needed(guild_id)

        self.clear(guild_id)

        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()
        else:
            self.schedule_idle_disconnect(guild_id)

    async def skip(
        self,
        voice_client: discord.VoiceClient,
    ) -> bool:
        if (
            not voice_client.is_playing()
            and not voice_client.is_paused()
        ):
            return False

        guild_id = voice_client.guild.id

        await self._pause_vk_if_needed(guild_id)
        self.cancel_live_end_timer(guild_id)

        voice_client.stop()

        return True

    async def disconnect(
        self,
        voice_client: discord.VoiceClient,
    ) -> None:
        guild_id = voice_client.guild.id

        await self._pause_vk_if_needed(guild_id)

        self.cancel_idle_timer(guild_id)
        self.clear(guild_id)

        await voice_client.disconnect()

    async def _pause_vk_if_needed(
        self,
        guild_id: int,
    ) -> None:
        current = self.current_tracks.get(guild_id)

        if current is None:
            return

        if current.track.source is not MusicSource.VK:
            return

        try:
            await self.vk_player.pause()
        except Exception:
            pass

    def clear(
        self,
        guild_id: int,
    ) -> None:
        self.cancel_live_end_timer(guild_id)
        self.queues[guild_id].clear()
        self.current_tracks.pop(guild_id, None)

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
        task = self.idle_tasks.pop(
            guild_id,
            None,
        )

        if task and not task.done():
            task.cancel()

    def schedule_idle_disconnect(
        self,
        guild_id: int,
    ) -> None:
        self.cancel_idle_timer(guild_id)

        self.idle_tasks[guild_id] = asyncio.create_task(
            self._idle_disconnect(guild_id)
        )

    def cancel_live_end_timer(
        self,
        guild_id: int,
    ) -> None:
        task = self.live_end_tasks.pop(
            guild_id,
            None,
        )

        if (
            task
            and not task.done()
            and task is not asyncio.current_task()
        ):
            task.cancel()

    async def _finish_live_track_after(
        self,
        guild_id: int,
        voice_client: discord.VoiceClient,
        item: QueueItem,
        seconds: int,
    ) -> None:
        try:
            await asyncio.sleep(seconds)

            if self.current_tracks.get(guild_id) is not item:
                return

            try:
                await self.vk_player.pause_active()
            except Exception as exc:
                print(f"Не удалось остановить VK: {exc}")

            if (
                voice_client.is_playing()
                or voice_client.is_paused()
            ):
                voice_client.stop()

        except asyncio.CancelledError:
            pass

        finally:
            current_task = asyncio.current_task()

            if (
                self.live_end_tasks.get(guild_id)
                is current_task
            ):
                self.live_end_tasks.pop(
                    guild_id,
                    None,
                )

    async def _idle_disconnect(
        self,
        guild_id: int,
    ) -> None:
        try:
            await asyncio.sleep(
                self.idle_timeout_seconds
            )

            guild = self.client.get_guild(
                guild_id
            )

            if guild is None or guild.voice_client is None:
                return

            voice_client = guild.voice_client

            if (
                voice_client.is_playing()
                or voice_client.is_paused()
                or self.queues[guild_id]
            ):
                return

            print(
                f"Guild {guild.name}: "
                "отключаюсь из-за бездействия"
            )

            self.current_tracks.pop(
                guild_id,
                None,
            )

            await voice_client.disconnect()

        except asyncio.CancelledError:
            pass

        finally:
            current_task = asyncio.current_task()

            if (
                self.idle_tasks.get(guild_id)
                is current_task
            ):
                self.idle_tasks.pop(
                    guild_id,
                    None,
                )

    @staticmethod
    def _duration_to_seconds(
        duration: str | None,
    ) -> int | None:
        if not duration:
            return None

        try:
            parts = [
                int(part)
                for part in duration.split(":")
            ]
        except ValueError:
            return None

        if len(parts) == 2:
            minutes, seconds = parts
            return minutes * 60 + seconds

        if len(parts) == 3:
            hours, minutes, seconds = parts

            return (
                hours * 3600
                + minutes * 60
                + seconds
            )

        return None
