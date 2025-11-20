import asyncio
from datetime import datetime, timedelta
import httpx
from sqlalchemy.orm import Session
from app import models
from app.config import settings

async def enqueue_webhook(db: Session, event_type: str, payload: dict, target_url: str):
    record = models.WebhookOutbox(
        event_type=event_type,
        payload=payload,
        target_url=target_url,
        status="pending",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record

async def process_webhooks(db: Session):
    pending = db.query(models.WebhookOutbox).filter(models.WebhookOutbox.status != "sent").all()
    async with httpx.AsyncClient(timeout=5.0) as client:
        for record in pending:
            if record.next_attempt_at and record.next_attempt_at > datetime.utcnow():
                continue
            try:
                resp = await client.post(record.target_url, json=record.payload)
                record.attempt_count += 1
                if resp.status_code >= 500:
                    raise Exception(f"remote error {resp.status_code}")
                record.status = "sent"
                record.last_error = None
            except Exception as exc:  # noqa: BLE001
                record.status = "failed"
                record.last_error = str(exc)
                record.attempt_count += 1
                record.next_attempt_at = datetime.utcnow() + timedelta(seconds=2 ** record.attempt_count)
            finally:
                db.add(record)
                db.commit()

async def background_webhook_worker(db_factory):
    while True:
        db = db_factory()
        try:
            await process_webhooks(db)
        finally:
            db.close()
        await asyncio.sleep(2)
