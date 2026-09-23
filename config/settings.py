"""Central configuration, loaded from environment variables."""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


# Project root (two levels up from this file: config/settings.py → project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite:///data/listings.db"
    log_level: str = "INFO"
    scrape_user_agent: str = "NigerianPriceIntel/0.1"
    request_delay_seconds: float = 2.0

    # --- Paystack ---
    paystack_secret_key: str = ""
    paystack_public_key: str = ""

    @property
    def data_dir(self) -> Path:
        path = PROJECT_ROOT / "data"
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()