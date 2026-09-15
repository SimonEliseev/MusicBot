from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MusicSource(StrEnum):
    HITMO = "hitmo"
    VK = "vk"


@dataclass(slots=True)
class TrackCandidate:
    title: str
    artist: str
    stream_url: str | None = None
    track_id: str | None = None
    duration: str | None = None
    source: MusicSource = MusicSource.HITMO

    @property
    def display_name(self) -> str:
        return f"{self.artist} — {self.title}"


@dataclass(slots=True)
class QueueItem:
    track: TrackCandidate
    channel_id: int