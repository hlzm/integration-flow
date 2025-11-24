import asyncio
from enum import Enum
import logging
import os
from typing import List, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, Float, DateTime, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.sql import func

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mock-operator")

STARTING_BALANCE = 100.0

DB_URL = "sqlite:////data/operator.db"
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

app = FastAPI(title="Mock Operator")

SUPPPORTED_CURRENCIES = ["USD", "EUR"]
INTEGRATION_WEBHOOK_URL = os.getenv("INTEGRATION_WEBHOOK_URL")

class OperatorAction(str, Enum):
    DEPOSIT = "deposit"
    WITHDRAW = "withdraw"

class Operation(BaseModel):
    amount: float
    currency: str
    reference: str
    correlationId: str


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    player = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, nullable=False)
    reference = Column(String, index=True, nullable=False)
    direction = Column(String, nullable=False)
    status = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    correlation_id = Column(String, nullable=True)


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _existing_transaction(db: Session, reference: str, direction: str):
    return (
        db.query(Transaction)
        .filter(Transaction.reference == reference)
        .filter(Transaction.direction == direction)
        .first()
    )


def _serialize_transaction(txn: Transaction) -> dict:
    return {
        "player": txn.player,
        "amount": txn.amount,
        "currency": txn.currency,
        "reference": txn.reference,
        "direction": txn.direction,
        "status": txn.status,
        "correlationId": txn.correlation_id,
    }


async def _send_callback(event: OperatorAction, player_id: str, amount: float, currency: str, reference: str, correlation_id: str, balance: float, status: str):
    if not INTEGRATION_WEBHOOK_URL:
        return
    logger.info(
        "Sending callback event=%s refId=%s correlationId=%s status=%s player=%s",
        event.value,
        reference,
        correlation_id,
        status,
        player_id,
    )
    payload = {
        "playerId": player_id,
        "amount": amount,
        "currency": currency,
        "status": status,
        "event": event.value,
        "refId": reference,
        "correlationId": correlation_id,
        "balance": balance,
    }    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # No retry logic here for simplicity
            # We should also add authentication headers here, not added for mock simplicity
            await client.post(INTEGRATION_WEBHOOK_URL, json=payload)
    except Exception:
        # Ignore callback delivery errors to keep the mock simple.
        logger.warning(
            "Failed to send callback to integration webhook for refId=%s correlationId=%s",
            reference,
            correlation_id,
        )
        return


@app.post("/v2/players/{player_external_id}/{wallet_action}")
async def wallet_action(
    player_external_id: str,
    wallet_action: Literal[OperatorAction.DEPOSIT, OperatorAction.WITHDRAW],
    body: Operation,
    db: Session = Depends(get_db),
):
    logger.info(
        "Received wallet action=%s player=%s refId=%s amount=%s currency=%s correlationId=%s",
        wallet_action,
        player_external_id,
        body.reference,
        body.amount,
        body.currency,
        body.correlationId,
    )
    if body.currency not in SUPPPORTED_CURRENCIES:
        logger.warning("Unsupported currency=%s for refId=%s", body.currency, body.reference)
        raise HTTPException(status_code=422, detail="unsupported currency")

    direction = OperatorAction(wallet_action)

    existing = _existing_transaction(db, body.reference, direction)
    if not existing:
        wallet_action_transaction = Transaction(
            player=player_external_id,
            amount=body.amount,
            currency=body.currency,
            reference=body.reference,
            direction=direction,
            status="OK",
            correlation_id=body.correlationId,
        )
        db.add(wallet_action_transaction)
        db.commit()
        logger.info(
            "Stored operator transaction action=%s refId=%s",
            direction,
            body.reference
        )
    else:
        logger.info(
            "Existing transaction found for action=%s refId=%s, skipping new insert",
            direction,
            body.reference,
        )
    # dummy balance calculation
    balance = STARTING_BALANCE - body.amount if direction == OperatorAction.WITHDRAW else STARTING_BALANCE + body.amount
    asyncio.create_task(
        _send_callback(
            direction,
            player_external_id,
            body.amount,
            body.currency,
            body.reference,
            body.correlationId,
            balance,
            status="OK",
        )
    )
    return {"status": "OK", "correlationId": body.correlationId}


@app.get("/v2/transactions")
async def list_transactions(db: Session = Depends(get_db)):
    txns: List[Transaction] = db.query(Transaction).order_by(Transaction.created_at).all()
    logger.info("Listing %s operator transactions", len(txns))
    return [_serialize_transaction(t) for t in txns]


@app.post("/admin/clear-db")
async def clear_db(db: Session = Depends(get_db)):
    """
    Dangerous: clears all mock operator transactions.
    """
    db.query(Transaction).delete()
    db.commit()
    logger.warning("Cleared mock operator transactions via admin endpoint")
    return {"status": "cleared"}
