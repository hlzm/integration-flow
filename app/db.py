from sqlalchemy.orm import Session
from fastapi import HTTPException
from app.models import models


def get_or_create_idempotency(db: Session, key: str, body_hash: str):
    existing = db.query(models.IdempotencyKey).filter_by(key=key).first()
    if existing:
        if existing.request_hash != body_hash:
            raise HTTPException(status_code=409, detail="idempotency conflict")
        return existing.response_body
    return None


def store_idempotency(db: Session, key: str, body_hash: str, response_body: dict):
    record = models.IdempotencyKey(key=key, request_hash=body_hash, response_body=response_body)
    db.add(record)
    db.commit()
    return response_body