import discord


class WindowsAudioCapture:
    def __init__(
        self,
        device_name: str = "CABLE Output (VB-Audio Virtual Cable)",
        ffmpeg_executable: str = "ffmpeg",
    ):
        self.device_name = device_name
        self.ffmpeg_executable = ffmpeg_executable

    def create_source(self) -> discord.FFmpegPCMAudio:
        return discord.FFmpegPCMAudio(
            source=f'audio={self.device_name}',
            executable=self.ffmpeg_executable,
            before_options="-f dshow -audio_buffer_size 100",
            options="-vn -ar 48000 -ac 2",
        )