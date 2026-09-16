from __future__ import annotations

import select
import subprocess
import time
from pathlib import Path

import discord


class ProcessPCMSource(discord.AudioSource):
    FRAME_SIZE = 3840

    def __init__(
        self,
        executable: Path,
        startup_timeout: float = 5.0,
    ) -> None:
        self._closed = False

        self._process = subprocess.Popen(
            [str(executable)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if self._process.stdout is None:
            raise RuntimeError(
                "PCM helper stdout недоступен"
            )

        if self._process.stderr is None:
            raise RuntimeError(
                "PCM helper stderr недоступен"
            )

        self._stdout = self._process.stdout
        self._stderr = self._process.stderr

        self._wait_until_ready(
            timeout=startup_timeout
        )

    def _wait_until_ready(
        self,
        timeout: float,
    ) -> None:
        deadline = time.monotonic() + timeout
        messages: list[str] = []

        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                remaining = (
                    self._stderr.read()
                    .decode(
                        "utf-8",
                        errors="replace",
                    )
                )

                if remaining:
                    messages.append(remaining)

                raise RuntimeError(
                    "macOS audio helper завершился:\n"
                    + "".join(messages)
                )

            readable, _, _ = select.select(
                [self._stderr],
                [],
                [],
                0.1,
            )

            if not readable:
                continue

            line = self._stderr.readline()

            if not line:
                continue

            text = line.decode(
                "utf-8",
                errors="replace",
            ).strip()

            messages.append(text + "\n")

            if text == "READY":
                return

            if text.startswith("ERROR"):
                raise RuntimeError(text)

        self.cleanup()

        raise RuntimeError(
            "macOS audio helper startup timeout:\n"
            + "".join(messages)
        )

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
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

        try:
            self._stdout.close()
        except Exception:
            pass

        try:
            self._stderr.close()
        except Exception:
            pass