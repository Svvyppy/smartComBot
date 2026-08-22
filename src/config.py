from __future__ import annotations

from decimal import Decimal
from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.domain.enums import UtilityType


class Settings(BaseSettings):
    """Application settings loaded from environment variables and an optional .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    bot_token: SecretStr = SecretStr("")

    supabase_url: str = ""
    supabase_service_role_key: SecretStr = SecretStr("")
    supabase_storage_bucket: str = "meter-photos"
    log_level: str = "INFO"

    cold_water_max_monthly_delta: Decimal = Decimal("100")
    hot_water_max_monthly_delta: Decimal = Decimal("100")
    electricity_max_monthly_delta: Decimal = Decimal("3000")

    @property
    def reading_delta_limits(self) -> dict[UtilityType, Decimal]:
        return {
            UtilityType.COLD_WATER: self.cold_water_max_monthly_delta,
            UtilityType.HOT_WATER: self.hot_water_max_monthly_delta,
            UtilityType.ELECTRICITY: self.electricity_max_monthly_delta,
        }

    def validate_runtime_secrets(self) -> None:
        missing: list[str] = []
        if not self.bot_token.get_secret_value():
            missing.append("BOT_TOKEN")
        if not self.supabase_url:
            missing.append("SUPABASE_URL")
        if not self.supabase_service_role_key.get_secret_value():
            missing.append("SUPABASE_SERVICE_ROLE_KEY")
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
