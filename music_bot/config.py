from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    guild_id: int
    idle_timeout_seconds: int = 10 * 60
    search_limit: int = 5

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        token = os.getenv("DISCORD_TOKEN")
        guild_id = os.getenv("GUILD_ID")

        if not token:
            raise RuntimeError("DISCORD_TOKEN is not set in .env")

        if not guild_id:
            raise RuntimeError("GUILD_ID is not set in .env")

        try:
            parsed_guild_id = int(guild_id)
        except ValueError as exc:
            raise RuntimeError("GUILD_ID must be an integer") from exc

        idle_timeout = cls._read_positive_int(
            "IDLE_TIMEOUT_SECONDS",
            default=10 * 60,
        )
        search_limit = cls._read_positive_int(
            "SEARCH_LIMIT",
            default=5,
        )

        return cls(
            discord_token=token,
            guild_id=parsed_guild_id,
            idle_timeout_seconds=idle_timeout,
            search_limit=search_limit,
        )

    @staticmethod
    def _read_positive_int(name: str, default: int) -> int:
        raw_value = os.getenv(name)
        if raw_value is None:
            return default

        try:
            value = int(raw_value)
        except ValueError as exc:
            raise RuntimeError(f"{name} must be an integer") from exc

        if value <= 0:
            raise RuntimeError(f"{name} must be greater than zero")

        return value
