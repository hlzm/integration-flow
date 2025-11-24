from typing import Optional

from pydantic import BaseModel, StrictInt

from app.config import operator_hub_action_map
from app.schemas.app_schemas import WalletRequest, WebhookPayload


class OperatorWalletRequest(BaseModel):
    amount: float
    currency: str
    reference: str
    correlationId: str

    @classmethod
    def from_wallet_request(cls, wallet_request: WalletRequest, correlation_id: str) -> "OperatorWalletRequest":
        return cls(
            amount=wallet_request.amountCents / 100,  # convert cents to operator unit
            currency=wallet_request.currency,
            reference=wallet_request.refId,
            correlationId=correlation_id,
        )


class RgsRequest(BaseModel):
    playerId: str
    amountCents: float
    currency: str
    status: str
    event: str
    refId: str
    correlationId: str
    balanceCents: float

    @classmethod
    def from_webhook_payload(cls, webhook_payload: WebhookPayload) -> "RgsRequest":
        event_value = operator_hub_action_map[webhook_payload.event]
        return cls(
            playerId=webhook_payload.playerId,
            amountCents=webhook_payload.amount * 100,  # convert to cents
            currency=webhook_payload.currency,
            status=webhook_payload.status,
            event=event_value,
            refId=webhook_payload.refId,
            correlationId=webhook_payload.correlationId,
            balanceCents=webhook_payload.balance * 100,  # convert to cents
        )
