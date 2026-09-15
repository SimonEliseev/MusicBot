from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)


VK_AUDIO_URL = "https://vk.ru/audio"


@dataclass(slots=True)
class VKTrack:
    track_id: str
    artist: str
    title: str
    duration: str

    def __str__(self) -> str:
        return f"{self.artist} — {self.title} [{self.duration}]"


class VKPlayer:
    def __init__(self) -> None:
        self.playwright: Playwright | None = None
        self.context: BrowserContext | None = None
        self.prepared_track_id: str | None = None

        self.search_page: Page | None = None
        self.playback_page: Page | None = None

        self.current_track: VKTrack | None = None

        self.profile_dir = (
            Path(__file__).resolve().parent / "browser_profile"
        )

    @property
    def is_started(self) -> bool:
        return (
            self.context is not None
            and self.search_page is not None
            and self.playback_page is not None
        )

    async def prepare(
        self,
        track: VKTrack,
    ) -> None:
        page = self._get_playback_page()

        query = quote_plus(
            f"{track.artist} {track.title}"
        )

        await page.goto(
            f"{VK_AUDIO_URL}?q={query}",
            wait_until="domcontentloaded",
        )

        title = page.locator(
            (
                '[data-testid="MusicTrackRow_Title"]'
                f'[href="{track.track_id}"]'
            )
        ).first

        await title.wait_for(
            state="visible",
            timeout=10_000,
        )

        row = title.locator(
            "xpath=ancestor::*[@data-testid='MusicTrackRow'][1]"
        )

        button = row.locator(
            ":scope > [role='button']"
        ).first

        await button.wait_for(
            state="attached",
            timeout=5_000,
        )

        self.prepared_track_id = track.track_id

    async def start(self) -> None:
        if self.is_started:
            return

        self.playwright = await async_playwright().start()

        try:
            self.context = (
                await self.playwright.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir),
                    channel="chrome",
                    headless=False,
                    args=[
                        "--autoplay-policy=no-user-gesture-required",
                    ],
                )
            )

            pages = self.context.pages

            if pages:
                self.playback_page = pages[0]
            else:
                self.playback_page = await self.context.new_page()

            if len(pages) >= 2:
                self.search_page = pages[1]
            else:
                self.search_page = await self.context.new_page()

            # Закрываем лишние восстановленные вкладки.
            for page in pages[2:]:
                await page.close()

            await asyncio.gather(
                self.playback_page.goto(
                    VK_AUDIO_URL,
                    wait_until="domcontentloaded",
                ),
                self.search_page.goto(
                    VK_AUDIO_URL,
                    wait_until="domcontentloaded",
                ),
            )

        except Exception:
            await self.stop()
            raise

    async def search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[VKTrack]:
        page = self._get_search_page()

        encoded_query = quote_plus(query)

        await page.goto(
            f"{VK_AUDIO_URL}?q={encoded_query}",
            wait_until="domcontentloaded",
        )

        rows = page.locator(
            '[data-testid="MusicTrackRow"]'
        )

        try:
            await rows.first.wait_for(
                state="visible",
                timeout=10_000,
            )
        except PlaywrightTimeoutError:
            return []

        count = min(
            await rows.count(),
            limit,
        )

        tracks: list[VKTrack] = []

        for index in range(count):
            row = rows.nth(index)

            artist_locator = row.locator(
                '[data-testid="MusicTrackRow_Authors"]'
            ).first

            title_locator = row.locator(
                '[data-testid="MusicTrackRow_Title"]'
            ).first

            duration_locator = row.locator(
                '[data-testid="MusicTrackRow_Duration"]'
            ).first

            try:
                artist = (
                    await artist_locator.inner_text()
                ).strip()

                title = (
                    await title_locator.inner_text()
                ).strip()

                duration = (
                    await duration_locator.inner_text()
                ).strip()

                track_id = await title_locator.get_attribute(
                    "href"
                )

            except Exception:
                continue

            if not artist or not title or not track_id:
                continue

            tracks.append(
                VKTrack(
                    track_id=track_id,
                    artist=artist,
                    title=title,
                    duration=duration,
                )
            )

        return tracks

    async def play(
        self,
        track: VKTrack,
    ) -> None:
        if self.prepared_track_id != track.track_id:
            await self.prepare(track)

        page = self._get_playback_page()

        title = page.locator(
            (
                '[data-testid="MusicTrackRow_Title"]'
                f'[href="{track.track_id}"]'
            )
        ).first

        row = title.locator(
            "xpath=ancestor::*[@data-testid='MusicTrackRow'][1]"
        )

        button = row.locator(
            ":scope > [role='button']"
        ).first

        aria_label = self._normalize_label(
            await button.get_attribute("aria-label")
        )

        if aria_label != "Поставить на паузу":
            await button.press("Enter")

        self.current_track = track
        self.prepared_track_id = None

    async def pause(self) -> None:
        button = await self._get_current_track_button()

        aria_label = self._normalize_label(
            await button.get_attribute("aria-label")
        )

        if aria_label == "Поставить на паузу":
            await button.press("Enter")

    async def resume(self) -> None:
        button = await self._get_current_track_button()

        aria_label = self._normalize_label(
            await button.get_attribute("aria-label")
        )

        if aria_label == "Начать прослушивание":
            await button.press("Enter")

    async def pause_active(self) -> None:
        if self.playback_page is None:
            return

        button = self.playback_page.get_by_role(
            "button",
            name=re.compile(
                r"Поставить на\s+паузу",
                re.IGNORECASE,
            ),
        ).first

        if await button.count():
            try:
                await button.press(
                    "Enter",
                    timeout=2_000,
                )
            except Exception:
                pass

    async def stop(self) -> None:
        try:
            self.prepared_track_id = None
            await self.pause_active()

            if self.context is not None:
                await self.context.close()

        finally:
            if self.playwright is not None:
                await self.playwright.stop()

            self.playwright = None
            self.context = None

            self.search_page = None
            self.playback_page = None

            self.current_track = None

    async def _get_current_track_button(self):
        if self.current_track is None:
            raise RuntimeError("Нет текущего VK-трека")

        page = self._get_playback_page()

        title = page.locator(
            (
                '[data-testid="MusicTrackRow_Title"]'
                f'[href="{self.current_track.track_id}"]'
            )
        ).first

        await title.wait_for(
            state="visible",
            timeout=5_000,
        )

        row = title.locator(
            "xpath=ancestor::*[@data-testid='MusicTrackRow'][1]"
        )

        return row.locator(
            ":scope > [role='button']"
        ).first

    def _get_search_page(self) -> Page:
        if self.search_page is None:
            raise RuntimeError("VKPlayer не запущен")

        return self.search_page

    def _get_playback_page(self) -> Page:
        if self.playback_page is None:
            raise RuntimeError("VKPlayer не запущен")

        return self.playback_page

    @staticmethod
    def _normalize_label(
        label: str | None,
    ) -> str:
        if not label:
            return ""

        return " ".join(
            label.replace("\xa0", " ").split()
        )