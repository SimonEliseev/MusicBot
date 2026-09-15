import asyncio
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus

from playwright.async_api import (
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)


@dataclass
class VKTrack:
    index: int
    artist: str
    title: str
    duration: str

    def __str__(self) -> str:
        return f"{self.artist} — {self.title} [{self.duration}]"


class VKPlayer:
    def __init__(self):
        self.playwright: Playwright | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

        self.current_track: VKTrack | None = None

        self.profile_dir = (
            Path(__file__).resolve().parent / "browser_profile"
        )

    async def start(self) -> None:
        self.playwright = await async_playwright().start()

        self.context = await self.playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            channel="chrome",
            headless=False,
            args=[
                "--autoplay-policy=no-user-gesture-required",
            ],
        )

        if self.context.pages:
            self.page = self.context.pages[0]
        else:
            self.page = await self.context.new_page()

        await self.page.goto(
            "https://vk.ru/audio",
            wait_until="domcontentloaded",
        )

    async def search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[VKTrack]:
        if self.page is None:
            raise RuntimeError("VKPlayer не запущен")

        encoded_query = quote_plus(query)

        await self.page.goto(
            f"https://vk.ru/audio?q={encoded_query}",
            wait_until="domcontentloaded",
        )

        rows = self.page.locator(
            '[data-testid="MusicTrackRow"]'
        )

        await rows.first.wait_for(
            state="visible",
            timeout=10_000,
        )

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

            except Exception:
                continue

            if not artist or not title:
                continue

            tracks.append(
                VKTrack(
                    index=index,
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
        if self.page is None:
            raise RuntimeError("VKPlayer не запущен")

        rows = self.page.locator(
            '[data-testid="MusicTrackRow"]'
        )

        if track.index >= await rows.count():
            raise RuntimeError(
                f"Трек с index={track.index} "
                "больше не существует на странице"
            )

        row = rows.nth(track.index)

        await row.scroll_into_view_if_needed()

        button = row.locator(
            ':scope > [role="button"][aria-label="Начать прослушивание"]'
        ).first

        await button.wait_for(
            state="attached",
            timeout=5_000,
        )

        await button.press("Enter")

        self.current_track = track

    async def pause(self) -> None:
        if self.current_track is None:
            raise RuntimeError("Нет текущего трека")

        button = await self._get_current_track_button()

        aria_label = await button.get_attribute(
            "aria-label"
        )

        if aria_label == "Поставить на\u00a0паузу":
            await button.press("Enter")

    async def resume(self) -> None:
        if self.current_track is None:
            raise RuntimeError("Нет текущего трека")

        button = await self._get_current_track_button()

        aria_label = await button.get_attribute(
            "aria-label"
        )

        if aria_label == "Начать прослушивание":
            await button.press("Enter")

    async def _get_current_track_button(self):
        if self.page is None:
            raise RuntimeError("VKPlayer не запущен")

        if self.current_track is None:
            raise RuntimeError("Нет текущего трека")

        rows = self.page.locator(
            '[data-testid="MusicTrackRow"]'
        )

        if self.current_track.index >= await rows.count():
            raise RuntimeError(
                "Строка текущего трека больше не найдена"
            )

        row = rows.nth(
            self.current_track.index
        )

        return row.locator(
            ":scope > [role='button']"
        ).first

    async def stop(self) -> None:
        if self.context is not None:
            await self.context.close()
            self.context = None

        if self.playwright is not None:
            await self.playwright.stop()
            self.playwright = None

        self.page = None
        self.current_track = None


async def main():
    player = VKPlayer()

    try:
        await player.start()

        tracks = await player.search(
            "Linkin Park Numb",
            limit=10,
        )

        print("Найденные треки:\n")

        for number, track in enumerate(
            tracks,
            start=1,
        ):
            print(f"{number}. {track}")

        if len(tracks) < 2:
            print("Нужный тестовый трек не найден")
            return

        track = tracks[1]

        print(f"\n▶ {track}")
        await player.play(track)

        print("\nEnter → PAUSE")
        await asyncio.to_thread(input)

        await player.pause()

        print("Enter → RESUME")
        await asyncio.to_thread(input)

        await player.resume()

        print("Enter → EXIT")
        await asyncio.to_thread(input)

    finally:
        await player.stop()


if __name__ == "__main__":
    asyncio.run(main())