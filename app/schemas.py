from pydantic import BaseModel, Field
from typing import Optional, Any

class WalletRequest(BaseModel):
    playerId: str = Field(..., alias="playerId")
    amountCents: int
    currency: str
    refId: str
    meta: Optional[Any] = None

class WalletResponse(BaseModel):
    status: str
    balanceCents: Optional[int] = None
    reason: Optional[str] = None

class WebhookPayload(BaseModel):
    event: str
    data: Any
    refId: Optional[str] = None
    correlationId: Optional[str] = None

class ReconciliationResult(BaseModel):
    refId: str
    direction: str
    localStatus: str
    remoteStatus: str
    mismatchReason: str
