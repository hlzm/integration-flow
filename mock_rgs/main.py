from fastapi import FastAPI
from pydantic import BaseModel
from typing import List

app = FastAPI(title="Mock RGS")
received: List[dict] = []

class Webhook(BaseModel):
    event: str
    refId: str
    status: str

@app.post("/webhooks")
async def webhooks(payload: Webhook):
    received.append(payload.dict())
    return {"accepted": True}

@app.get("/webhooks")
async def list_webhooks():
    return received
