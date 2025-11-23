import httpx
from fastapi import HTTPException
from app.config import settings


class RGSClient:
    def __init__(self) -> None:
        self.client = httpx.AsyncClient(timeout=10.0)

    async def list_webhooks(self) -> list[dict]:
        resp = await self.client.get(str(settings.rgs_webhook_url))
        if resp.status_code == 200:
            return resp.json()
        raise HTTPException(status_code=resp.status_code, detail=resp.text)


rgs_client = RGSClient()
