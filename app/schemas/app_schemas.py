from pydantic import BaseModel
from typing import Optional, Any

class WalletRequest(BaseModel):
    playerId: str
    amountCents: int
    currency: str
    refId: str

class WalletResponse(BaseModel):
    status: str
    balanceCents: Optional[int] = None
    reason: Optional[str] = None
    refId: Optional[str] = None
    correlationId: Optional[str] = None

class WebhookPayload(BaseModel):
    playerId: str
    amount: float
    currency: str
    status: str
    event: str
    refId: str
    correlationId: str
    
class ReconciliationResult(BaseModel):
    refId: str
    correlationId: str
    direction: str
    localStatus: str
    remoteStatus: str
    mismatchReason: str
