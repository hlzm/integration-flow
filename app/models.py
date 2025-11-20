from sqlalchemy import Column, Integer, String, DateTime, JSON, UniqueConstraint, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base

class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, index=True, nullable=False)
    request_hash = Column(String, nullable=False)
    response_body = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True)
    ref_id = Column(String, index=True, nullable=False)
    player_id = Column(String, index=True, nullable=False)
    amount_cents = Column(Integer, nullable=False)
    currency = Column(String, nullable=False)
    direction = Column(String, nullable=False)  # debit|credit
    status = Column(String, nullable=False)
    reason = Column(String, nullable=True)
    balance_cents = Column(Integer, nullable=True)
    correlation_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (UniqueConstraint('ref_id', 'direction', name='uq_ref_direction'),)

class WebhookOutbox(Base):
    __tablename__ = "webhook_outbox"
    id = Column(Integer, primary_key=True)
    event_type = Column(String, nullable=False)
    target_url = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(String, nullable=False, default="pending")
    attempt_count = Column(Integer, default=0)
    next_attempt_at = Column(DateTime(timezone=True), server_default=func.now())
    last_error = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
