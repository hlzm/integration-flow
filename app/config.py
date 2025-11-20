from pydantic import BaseSettings, AnyHttpUrl
from typing import Optional

class Settings(BaseSettings):
    operator_base_url: AnyHttpUrl = "http://mock-operator:8001"
    webhook_target: Optional[AnyHttpUrl] = None
    hmac_secret: str = "changeme"
    db_url: str = "sqlite:///./integration.db"
    max_retries: int = 3
    retry_backoff_seconds: float = 1.0
    rate_limit_per_minute: int = 60
    timestamp_skew_seconds: int = 300

    class Config:
        env_file = ".env"

settings = Settings()
