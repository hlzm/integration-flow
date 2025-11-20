import asyncio
import hashlib
import json
from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy.orm import Session
from app import models
from app.config import settings
from app.database import engine, get_db, SessionLocal
from app.schemas import WalletRequest, WalletResponse, WebhookPayload
from app.operator_client import operator_client
from app.security import validate_signature
from app.webhooks import enqueue_webhook, background_webhook_worker

models.Base.metadata.create_all(bind=engine)
app = FastAPI(title="Integration Hub")

@app.on_event("startup")
async def startup_event():
    loop = asyncio.get_event_loop()
    loop.create_task(background_webhook_worker(SessionLocal))


def _hash_request(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def _get_or_create_idempotency(db: Session, key: str, body_hash: str):
    existing = db.query(models.IdempotencyKey).filter_by(key=key).first()
    if existing:
        if existing.request_hash != body_hash:
            raise HTTPException(status_code=409, detail="idempotency conflict")
        return existing.response_body
    return None


def _store_idempotency(db: Session, key: str, body_hash: str, response_body: dict):
    record = models.IdempotencyKey(key=key, request_hash=body_hash, response_body=response_body)
    db.add(record)
    db.commit()
    return response_body


def _validate_currency(currency: str):
    allowed = {"USD", "EUR", "GBP"}
    if currency not in allowed:
        raise HTTPException(status_code=422, detail="unsupported currency")


@app.post("/wallet/debit", response_model=WalletResponse)
async def debit(
    request: WalletRequest,
    db: Session = Depends(get_db),
    Idempotency_Key: str | None = Header(None),
    x_signature: str | None = Header(None),
    x_timestamp: str | None = Header(None),
):
    body = request.dict(by_alias=True)
    if x_signature and x_timestamp:
        validate_signature(body, x_signature, x_timestamp)
    _validate_currency(request.currency)
    body_hash = _hash_request(body)
    if Idempotency_Key:
        existing = _get_or_create_idempotency(db, Idempotency_Key, body_hash)
        if existing:
            return existing
    result = await operator_client.withdraw(request.playerId, request.amountCents, request.currency, request.refId)
    response = {"status": result.get("status", "OK"), "balanceCents": int(result.get("balance", 0) * 100)}
    txn = models.Transaction(
        ref_id=request.refId,
        player_id=request.playerId,
        amount_cents=request.amountCents,
        currency=request.currency,
        direction="debit",
        status=response["status"],
        balance_cents=response.get("balanceCents"),
        correlation_id=result.get("correlationId"),
    )
    db.add(txn)
    db.commit()
    if settings.webhook_target:
        await enqueue_webhook(db, "debit", {"refId": request.refId, "status": response["status"]}, settings.webhook_target)
    if Idempotency_Key:
        _store_idempotency(db, Idempotency_Key, body_hash, response)
    return response


@app.post("/wallet/credit", response_model=WalletResponse)
async def credit(
    request: WalletRequest,
    db: Session = Depends(get_db),
    Idempotency_Key: str | None = Header(None),
    x_signature: str | None = Header(None),
    x_timestamp: str | None = Header(None),
):
    body = request.dict(by_alias=True)
    if x_signature and x_timestamp:
        validate_signature(body, x_signature, x_timestamp)
    _validate_currency(request.currency)
    body_hash = _hash_request(body)
    if Idempotency_Key:
        existing = _get_or_create_idempotency(db, Idempotency_Key, body_hash)
        if existing:
            return existing
    result = await operator_client.deposit(request.playerId, request.amountCents, request.currency, request.refId)
    response = {"status": result.get("status", "OK"), "balanceCents": int(result.get("balance", 0) * 100)}
    txn = models.Transaction(
        ref_id=request.refId,
        player_id=request.playerId,
        amount_cents=request.amountCents,
        currency=request.currency,
        direction="credit",
        status=response["status"],
        balance_cents=response.get("balanceCents"),
        correlation_id=result.get("correlationId"),
    )
    db.add(txn)
    db.commit()
    if settings.webhook_target:
        await enqueue_webhook(db, "credit", {"refId": request.refId, "status": response["status"]}, settings.webhook_target)
    if Idempotency_Key:
        _store_idempotency(db, Idempotency_Key, body_hash, response)
    return response


@app.post("/webhooks/incoming")
async def receive_webhook(payload: WebhookPayload, db: Session = Depends(get_db)):
    txn = models.Transaction(
        ref_id=payload.refId or payload.data.get("refId", "unknown"),
        player_id=payload.data.get("playerId", "unknown"),
        amount_cents=payload.data.get("amountCents", 0),
        currency=payload.data.get("currency", "USD"),
        direction=payload.event,
        status="received",
        correlation_id=payload.correlationId,
    )
    db.add(txn)
    db.commit()
    return {"status": "accepted"}


@app.get("/healthz")
async def health():
    return {"status": "ok"}
