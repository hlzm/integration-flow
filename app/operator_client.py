import asyncio
import time
from typing import Optional
import httpx
from fastapi import HTTPException
from app.config import settings

class OperatorClient:
    def __init__(self):
        self.client = httpx.AsyncClient(base_url=settings.operator_base_url, timeout=10.0)
        self._tokens = []

    async def _respect_rate_limit(self):
        now = time.time()
        self._tokens = [t for t in self._tokens if now - t < 60]
        if len(self._tokens) >= settings.rate_limit_per_minute:
            sleep_for = 60 - (now - self._tokens[0])
            await asyncio.sleep(sleep_for)
        self._tokens.append(time.time())

    async def _request_with_retry(self, method: str, url: str, json: dict) -> httpx.Response:
        retries = 0
        backoff = settings.retry_backoff_seconds
        while retries <= settings.max_retries:
            await self._respect_rate_limit()
            response = await self.client.request(method, url, json=json)
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else backoff
                await asyncio.sleep(wait)
                retries += 1
                backoff *= 2
                continue
            if response.status_code >= 500:
                if retries == settings.max_retries:
                    return response
                await asyncio.sleep(backoff)
                retries += 1
                backoff *= 2
                continue
            return response
        return response

    async def withdraw(self, player_external_id: str, amount_cents: int, currency: str, ref_id: str):
        payload = {
            "amount": amount_cents / 100,
            "currency": currency,
            "reference": ref_id,
        }
        resp = await self._request_with_retry("POST", f"/v2/players/{player_external_id}/withdraw", json=payload)
        if resp.status_code == 200:
            return resp.json()
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    async def deposit(self, player_external_id: str, amount_cents: int, currency: str, ref_id: str):
        payload = {
            "amount": amount_cents / 100,
            "currency": currency,
            "reference": ref_id,
        }
        resp = await self._request_with_retry("POST", f"/v2/players/{player_external_id}/deposit", json=payload)
        if resp.status_code == 200:
            return resp.json()
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    async def list_transactions(self):
        resp = await self._request_with_retry("GET", "/v2/transactions", json={})
        if resp.status_code == 200:
            return resp.json()
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

operator_client = OperatorClient()
