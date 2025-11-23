import httpx
from fastapi import HTTPException
from app.config import settings

class OperatorClient:
    def __init__(self):
        base_url = str(settings.operator_base_url)
        self.client = httpx.AsyncClient(base_url=base_url, timeout=10.0)
        self._tokens = []
    
    async def list_transactions(self):
        resp = await self.client.get("/v2/transactions")
        if resp.status_code == 200:
            return resp.json()
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

operator_client = OperatorClient()
