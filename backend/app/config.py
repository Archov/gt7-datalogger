"""Application configuration via environment variables."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GT7_", env_file=".env", extra="ignore")

    # "udp" captures from a PlayStation, "sim" replays bundled sample data.
    source: str = "udp"
    ps_ip: str = ""  # empty -> broadcast auto-discovery
    heartbeat_port: int = 33739
    telemetry_port: int = 33740
    # Telemetry format requested from the console: "A", "B", "~", or "C".
    # "C" (game v1.68+) is the richest; older game versions only answer "A".
    packet_format: str = "C"

    db_path: Path = Path("data/gt7.db")
    cars_csv: Path = Path("data/cars.csv")
    sample_lap: Path = Path("data/sample_lap.json")

    http_host: str = "0.0.0.0"
    http_port: int = 8000

    # When set, the Admin API and all mutating endpoints require this token
    # (X-API-Key header). Empty = fully open (LAN-trusted, the old behavior).
    admin_token: str = ""
    # Comma-separated origins allowed for cross-origin API use. Empty = no
    # CORS headers at all — the bundled UI is same-origin and needs none.
    cors_origins: str = ""

    # Client stream rate (Hz). Raw capture is ~60 Hz; the UI does not need all of it.
    ws_rate: int = 30

    log_level: str = "INFO"

    # Webhook for race notifications
    # (Discord webhook URLs get a rich embed; other URLs get plain JSON).
    webhook_url: str = ""
    # Comma-separated events to send; see app.notify.ALL_EVENTS.
    webhook_events: str = "personal_best,session_summary,overtake,position_lost,off_road"

    def enabled_webhook_events(self) -> set[str]:
        from app.notify import parse_events

        return parse_events(self.webhook_events)


@lru_cache
def get_settings() -> Settings:
    return Settings()
