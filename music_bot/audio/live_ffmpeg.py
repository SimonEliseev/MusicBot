from __future__ import annotations

import subprocess
import sys

import discord


class LiveFFmpegSource(discord.AudioSource):
    FRAME_SIZE = 3840  # 20 ms, 48 kHz, stereo, s16le

    def __init__(
        self,
        input_args: list[str],
        executable: str = "ffmpeg",
    ) -> None:
        creationflags = (
            subprocess.CREATE_NO_WINDOW
            if sys.platform == "win32"
            else 0
        )

        args = [
            executable,
            "-hide_banner",
            "-loglevel",
            "error",
            *input_args,
            "-vn",
            "-f",
            "s16le",
            "-ar",
            "48000",
            "-ac",
            "2",
            "pipe:1",
        ]

        self._process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=None,
            creationflags=creationflags,
        )

        if self._process.stdout is None:
            raise RuntimeError("FFmpeg stdout недоступен")

        self._stdout = self._process.stdout
        self._closed = False

    def read(self) -> bytes:
        if self._closed:
            return b""

        buffer = bytearray()

        while len(buffer) < self.FRAME_SIZE:
            chunk = self._stdout.read(
                self.FRAME_SIZE - len(buffer)
            )

            if not chunk:
                return b""

            buffer.extend(chunk)

        return bytes(buffer)

    def is_opus(self) -> bool:
        return False

    def cleanup(self) -> None:
        if self._closed:
            return

        self._closed = True

        process = self._process

        if process.poll() is None:
            process.terminate()

            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

        try:
            self._stdout.close()
        except Exception:
            pass