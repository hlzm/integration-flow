from enum import Enum
from pydantic import AnyHttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    operator_base_url: AnyHttpUrl = "http://mock-operator:8001"
    rgs_webhook_url: Optional[AnyHttpUrl] = None
    hmac_secret: str = "change_secret"
    bearer_token: Optional[str] = None
    db_url: str = "sqlite:///./integration.db"
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0
    rate_limit_per_minute: int = 60
    timestamp_skew_seconds: int = 5
    supported_currencies: list[str] = ["USD", "EUR"]

settings = Settings()

class WalletAction(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"

hub_operator_action_map = {
    WalletAction.DEBIT: "withdraw",
    WalletAction.CREDIT: "deposit",
}

operator_hub_action_map = {
    'withdraw': WalletAction.DEBIT.value,
    'deposit': WalletAction.CREDIT.value
}
