from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TrackCandidate:
    title: str
    artist: str
    stream_url: str
    track_id: str | None = None
    duration: str | None = None

    @property
    def display_name(self) -> str:
        return f"{self.artist} — {self.title}"


@dataclass(slots=True)
class QueueItem:
    track: TrackCandidate
    channel_id: int
