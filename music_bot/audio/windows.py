import discord


class WindowsAudioCapture:
    def __init__(
        self,
        device_name: str = "CABLE Output (VB-Audio Virtual Cable)",
        ffmpeg_executable: str = "ffmpeg",
    ) -> None:
        self.device_name = device_name
        self.ffmpeg_executable = ffmpeg_executable

    def create_source(self) -> discord.AudioSource:
        return discord.FFmpegPCMAudio(
            source=f"audio={self.device_name}",
            executable=self.ffmpeg_executable,
            before_options="-f dshow",
            options="-vn",
        )

    async def close(self) -> None:
        pass