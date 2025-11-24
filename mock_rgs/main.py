import logging
from typing import List

from fastapi import Depends, FastAPI
from pydantic import BaseModel, StrictInt
from sqlalchemy import JSON, Column, DateTime, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.sql import func

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("mock-rgs")

DB_URL = "sqlite:////data/rgs.db"
engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

app = FastAPI(title="Mock RGS")


class Webhook(BaseModel):
    playerId: str
    amountCents: float
    currency: str
    status: str
    event: str
    refId: str
    correlationId: str
    balanceCents: float


class ReceivedWebhook(Base):
    __tablename__ = "received_webhooks"
    id = Column(Integer, primary_key=True)
    event = Column(String, nullable=False)
    playerId = Column(String, nullable=False)
    ref_id = Column(String, nullable=False)
    status = Column(String, nullable=False)
    amountCents = Column(Integer, nullable=False)
    currency = Column(String, nullable=False)
    correlationId = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    balanceCents = Column(Integer, nullable=True)

Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _serialize(record: ReceivedWebhook) -> dict:
    return {
        "event": record.event,
        "refId": record.ref_id,
        "status": record.status,
        "playerId": record.playerId,
        "amountCents": record.amountCents,
        "currency": record.currency,
        "correlationId": record.correlationId,
        "createdAt": record.created_at.isoformat() if record.created_at else None,
        "balanceCents": record.balanceCents,
    }


@app.post("/webhooks")
async def webhooks(payload: Webhook, db: Session = Depends(get_db)):
    # We should also add authentication here to simulate real RGS behavior, not added for mock simplicity
    logger.info(
        "RGS received webhook event=%s refId=%s correlationId=%s status=%s",
        payload.event,
        payload.refId,
        payload.correlationId,
        payload.status,
    )
    record = ReceivedWebhook(
        event=payload.event, 
        ref_id=payload.refId, 
        status=payload.status,
        playerId=payload.playerId,
        amountCents=payload.amountCents,
        currency=payload.currency,
        correlationId=payload.correlationId,
        balanceCents=payload.balanceCents
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"accepted": True, "id": record.id}


@app.get("/webhooks")
async def list_webhooks(db: Session = Depends(get_db)):
    records: List[ReceivedWebhook] = db.query(ReceivedWebhook).order_by(ReceivedWebhook.created_at).all()
    logger.info("Listing %s received webhooks", len(records))
    return [_serialize(r) for r in records]


@app.post("/admin/clear-db")
async def clear_db(db: Session = Depends(get_db)):
    """
    Dangerous: clears all received webhook records.
    """
    db.query(ReceivedWebhook).delete()
    db.commit()
    logger.warning("Cleared mock RGS webhooks via admin endpoint")
    return {"status": "cleared"}
