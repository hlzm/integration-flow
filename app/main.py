import asyncio
import json
import uuid
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.openapi.docs import get_swagger_ui_html
from sqlalchemy.orm import Session

from app.config import WalletAction, hub_operator_action_map, operator_hub_action_map, settings
from app.database import SessionLocal, engine, get_db
from app.db import get_or_create_idempotency, store_idempotency
from app.helpers import hash_request, serialize_outbox, validate_currency
from app.logging_config import get_logger
from app.models import models
from app.reconciliation import generate_reconciliation_csv
from app.schemas.app_schemas import WalletRequest, WalletResponse, WebhookPayload
from app.security import require_bearer_token, validate_signature
from app.webhooks import background_outbox_worker, enqueue_operator_item, enqueue_rgs_item


logger = get_logger(__name__)

models.Base.metadata.create_all(bind=engine)
app = FastAPI(title="Integration Hub")

STARTING_BALANCE_CENTS = 0

def _resolve_external_player_id(player_id: str) -> str:
    # In a real implementation, this would query a mapping service or database
    return f'{player_id}_ext'  # For mock purposes, return as is

@app.on_event("startup")
async def startup_event():
    logger.info("Starting Integration Hub background outbox worker")
    loop = asyncio.get_event_loop()
    loop.create_task(background_outbox_worker(SessionLocal))

@app.post("/wallet/{wallet_action}", response_model=WalletResponse)
async def wallet_action_route(
    wallet_action: Literal[WalletAction.DEBIT, WalletAction.CREDIT],
    request: WalletRequest,
    _auth=Depends(require_bearer_token),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(None),
    x_signature: str | None = Header(None),
    x_timestamp: str | None = Header(None),
):
    body = request.model_dump(by_alias=True)
    if x_signature and x_timestamp:
        validate_signature(body, x_signature, x_timestamp)
    validate_currency(request.currency)
    body_hash = hash_request(body)
    if idempotency_key:
        existing = get_or_create_idempotency(db, idempotency_key, body_hash)
        if existing:
            return existing
    if request.playerId.endswith("_bad"):
        return {
            'status': 'REJECTED',
            'reason': "User Account Is Blocked",
        }
    external_player_id = _resolve_external_player_id(request.playerId)
    operator_action = hub_operator_action_map[wallet_action]
    operator_url = str(settings.operator_base_url) + f"v2/players/{external_player_id}/{operator_action}"
    initial_status = "initiated"
    correlation_id = str(uuid.uuid4())
    await enqueue_operator_item(db, wallet_action, request, correlation_id, operator_url)
    transaction_data = {
        "ref_id": request.refId,
        "player_id": request.playerId,
        "amount_cents": request.amountCents,
        "currency": request.currency,
        "direction": wallet_action,
        "status": initial_status,
        "correlation_id": correlation_id,
    }
    wallet_transaction = models.Transaction(**transaction_data)
    db.add(wallet_transaction)
    db.commit()
    logger.info(
        "Stored wallet transaction action=%s refId=%s correlationId=%s status=%s",
        wallet_action,
        request.refId,
        correlation_id,
        initial_status,
    )
    # dummy balance calculation
    balance = STARTING_BALANCE_CENTS - request.amountCents if wallet_action == WalletAction.DEBIT else STARTING_BALANCE_CENTS + request.amountCents

    response = {
        'status': initial_status,
        'refId': request.refId,
        'correlationId': correlation_id,
        'balanceCents': balance,
        'reason': None
    }
    if idempotency_key:
        store_idempotency(db, idempotency_key, body_hash, response)
    return response

@app.post("/webhooks/incoming")
async def receive_webhook(payload: WebhookPayload, db: Session = Depends(get_db)):
    logger.info(
        "Received webhook event=%s refId=%s correlationId=%s status=%s",
        payload.event,
        payload.refId,
        payload.correlationId,
        payload.status,
    )
    ref_id = payload.refId
    correlation_id = payload.correlationId
    existing = (
        db.query(models.Transaction)
        .filter(models.Transaction.ref_id == ref_id)
        .filter(models.Transaction.correlation_id == correlation_id)
        .first()
    )
    if not existing:
        logger.warning(
            "Unknown webhook received: refId=%s correlationId=%s payload=%s",
            ref_id,
            correlation_id,
            payload.model_dump(by_alias=True),
        )
        raise HTTPException(status_code=404, detail="unknown reference/correlation")
    existing.status = "sent" # type: ignore
    db.add(existing)
    db.commit()
    logger.info(
        "Updated transaction status to sent: refId=%s correlationId=%s event=%s",
        ref_id,
        correlation_id,
        payload.event,
    )
    await enqueue_rgs_item(db, payload, str(settings.rgs_webhook_url))
    return {"status": "accepted"}

@app.get("/webhooks/outbox")
async def list_outbox(
    status: str | None = None,
    queue: Literal["rgs", "operator"] = "rgs",
    limit: int = Query(100, ge=1, le=500),
    _auth=Depends(require_bearer_token),
    db: Session = Depends(get_db),
):
    model = models.RGSWebhookOutbox if queue == "rgs" else models.OperatorWebhookOutbox
    query = db.query(model)
    if status:
        query = query.filter(model.status == status)
    records = query.order_by(model.created_at.desc()).limit(limit).all()
    return [serialize_outbox(r) for r in records]

@app.get("/reconciliation_data")
async def download_reconciliation_csv(_auth=Depends(require_bearer_token)):
    csv_text, mismatch_count = await generate_reconciliation_csv()
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="reconciliation.csv"',
            "X-Mismatch-Count": str(mismatch_count),
        },
    )


@app.post("/admin/clear-db")
async def clear_db(_auth=Depends(require_bearer_token), db: Session = Depends(get_db)):
    """
    Dangerous: clears transactions, idempotency, and webhook outbox tables.
    """
    logger.warning("Clearing hub database tables via admin endpoint")
    db.query(models.Transaction).delete()
    db.query(models.IdempotencyKey).delete()
    db.query(models.RGSWebhookOutbox).delete()
    db.query(models.OperatorWebhookOutbox).delete()
    db.commit()
    return {"status": "cleared"}

@app.post("/admin/replay/{queue}/{record_id}")
async def force_replay(
    queue: Literal["rgs", "operator"],
    record_id: int,
    _auth=Depends(require_bearer_token),
    db: Session = Depends(get_db),
):
    """
    Force a single outbox record back to pending and clear the last_error.
    """
    model = models.RGSWebhookOutbox if queue == "rgs" else models.OperatorWebhookOutbox
    record = db.query(model).filter(model.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="outbox record not found")
    record.status = "pending"  # noqa: S105
    record.last_error = None
    record.next_attempt_at = None
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info("Forced replay for %s outbox record_id=%s", queue, record_id)
    return serialize_outbox(record)

@app.get("/swagger", include_in_schema=False)
async def swagger_ui():
    return get_swagger_ui_html(openapi_url=str(app.openapi_url), title="Integration Hub - Swagger UI")

@app.get("/health")
async def health():
    return {"status": "ok"}
