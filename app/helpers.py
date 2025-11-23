import hashlib
import json
import asyncio
import time
import httpx
from typing import Union, List

from app.config import settings
from app.models import models
from fastapi import HTTPException


def hash_request(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def validate_currency(currency: str):
    if currency not in settings.supported_currencies:
        raise HTTPException(status_code=422, detail="unsupported currency")


def serialize_outbox(record: Union[models.RGSWebhookOutbox, models.OperatorWebhookOutbox]) -> dict:
    queue = "rgs" if isinstance(record, models.RGSWebhookOutbox) else "operator"
    return {
        "id": record.id,
        "eventType": record.event_type,
        "targetUrl": record.target_url,
        "status": record.status,
        "attemptCount": record.attempt_count,
        "nextAttemptAt": record.next_attempt_at.isoformat() if record.next_attempt_at else None,
        "lastError": record.last_error,
        "createdAt": record.created_at.isoformat() if record.created_at else None,
        "payload": record.payload,
        "queue": queue,
    }


class IntegrationClient:
    def __init__(
        self,
        rate_limit_per_minute: int | None = None,
        max_retries: int | None = None,
        retry_backoff_seconds: float | None = None,
    ):
        base_url = str(settings.operator_base_url)
        self.client = httpx.AsyncClient(base_url=base_url, timeout=10.0)
        self._tokens: List[float] = []
        self.rate_limit_per_minute = rate_limit_per_minute if rate_limit_per_minute is not None else settings.rate_limit_per_minute
        self.max_retries = max_retries if max_retries is not None else settings.max_retries
        self.retry_backoff_seconds = retry_backoff_seconds if retry_backoff_seconds is not None else settings.retry_backoff_seconds

    async def _respect_rate_limit(self) -> bool:
        now = time.time()
        self._tokens = [t for t in self._tokens if now - t < 60]
        if len(self._tokens) >= self.rate_limit_per_minute:
            return False
        self._tokens.append(time.time())
        return True

    async def _request_with_retry(self, method: str, url: str, json: dict) -> httpx.Response:
        retries = 0
        backoff = self.retry_backoff_seconds
        while retries <= self.max_retries:
            allowed = await self._respect_rate_limit()
            if not allowed:
                headers = {"Retry-After": str(backoff)}
                return httpx.Response(status_code=429, headers=headers, request=httpx.Request(method, url))
            try:
                response = await self.client.request(method, url, json=json)
            except httpx.RequestError as exc:
                # Surface network/DNS errors as a downstream failure.
                raise HTTPException(status_code=502, detail=f"operator request error: {exc}") from exc
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else backoff
                await asyncio.sleep(wait)
                retries += 1
                backoff *= 2
                continue
            if response.status_code >= 500:
                if retries == self.max_retries:
                    return response
                await asyncio.sleep(backoff)
                retries += 1
                backoff *= 2
                continue
            return response
        return response
