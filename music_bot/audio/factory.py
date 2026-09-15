import platform

from music_bot.audio.base import AudioCapture


def create_audio_capture() -> AudioCapture:
    system = platform.system()

    if system == "Windows":
        from music_bot.audio.windows import WindowsAudioCapture

        return WindowsAudioCapture()

    if system == "Darwin":
        from music_bot.audio.macos import MacOSAudioCapture

        return MacOSAudioCapture()

    raise RuntimeError(
        f"Неподдерживаемая ОС: {system}"
    )