from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from music_bot.music.models import TrackCandidate


BASE_URL = "https://ru.hitmoz.org"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/127.0.0.0 Safari/537.36"
)


class HitmoProvider:
    def __init__(self) -> None:
        self.client = httpx.Client(
            headers={
                "User-Agent": USER_AGENT,
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                "Referer": f"{BASE_URL}/",
            },
            timeout=15.0,
            follow_redirects=True,
        )

    def search(self, query: str, limit: int = 5) -> list[TrackCandidate]:
        response = self.client.get(
            f"{BASE_URL}/search",
            params={"q": query},
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        results: list[TrackCandidate] = []

        for element in soup.select("li.tracks__item.track[data-musmeta]"):
            if not isinstance(element, Tag):
                continue

            track = self._parse_track(element)
            if track is None:
                continue

            results.append(track)
            if len(results) >= limit:
                break

        return results

    def search_one(self, query: str) -> TrackCandidate | None:
        tracks = self.search(query, limit=1)
        return tracks[0] if tracks else None

    def close(self) -> None:
        self.client.close()

    @staticmethod
    def _parse_track(element: Tag) -> TrackCandidate | None:
        raw_meta = element.get("data-musmeta")
        if not isinstance(raw_meta, str) or not raw_meta:
            return None

        try:
            meta = json.loads(raw_meta)
        except json.JSONDecodeError:
            return None

        artist = meta.get("artist")
        title = meta.get("title")
        stream_url = meta.get("url")

        if not all(isinstance(value, str) and value for value in (artist, title, stream_url)):
            return None

        return TrackCandidate(
            artist=artist,
            title=title,
            stream_url=urljoin(BASE_URL, stream_url),
            track_id=meta.get("id") if isinstance(meta.get("id"), str) else None,
            duration=_extract_duration(element),
        )


def _extract_duration(element: Tag) -> str | None:
    for attr in ("data-duration", "data-time", "data-length"):
        value = element.get(attr)
        if not isinstance(value, str) or not value:
            continue

        if value.isdigit():
            seconds = int(value)
            return f"{seconds // 60}:{seconds % 60:02d}"

        return value

    for selector in (
        ".track__time",
        ".track__duration",
        ".track__fulltime",
        ".duration",
        "[class*='duration']",
        "[class*='time']",
    ):
        node = element.select_one(selector)
        if node is None:
            continue

        match = re.search(r"\b\d{1,2}:\d{2}\b", node.get_text(" ", strip=True))
        if match:
            return match.group(0)

    match = re.search(r"\b\d{1,2}:\d{2}\b", element.get_text(" ", strip=True))
    return match.group(0) if match else None
