import discord


class MacOSAudioCapture:
    def create_source(self) -> discord.AudioSource:
        raise RuntimeError(
            "Захват аудио macOS пока не настроен"
        )

    async def close(self) -> None:
        pass