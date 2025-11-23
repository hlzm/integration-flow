import asyncio
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.config import settings
from app.helpers import IntegrationClient
from app.logging_config import get_logger
from app.models import models
from app.contracts.contracts import OperatorWalletRequest, RgsRequest
from app.schemas.app_schemas import WalletRequest, WebhookPayload

logger = get_logger(__name__)

async def enqueue_rgs_item(db: Session, payload: WebhookPayload, target_url: str):
    rgs_request = RgsRequest.from_webhook_payload(payload)
    rgs_payload_dict = rgs_request.model_dump(by_alias=True)
    return await _enqueue_item(db, models.RGSWebhookOutbox, rgs_payload_dict['event'], rgs_payload_dict, target_url)

async def enqueue_operator_item(db: Session, event_type: str, request: WalletRequest, correlation_id: str, target_url: str):
    operator_wallet_request = OperatorWalletRequest.from_wallet_request(request, correlation_id)
    operator_payload = operator_wallet_request.model_dump(by_alias=True)
    return await _enqueue_item(db, models.OperatorWebhookOutbox, event_type, operator_payload, target_url)


async def _enqueue_item(db: Session, model, event_type: str, payload: dict, target_url: str):
    record = model(
        event_type=event_type,
        payload=payload,
        target_url=str(target_url),
        status="pending",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


async def process_outbox(db: Session):
    await _process_outbox(db, models.RGSWebhookOutbox)
    await _process_outbox(db, models.OperatorWebhookOutbox)

integration_client = IntegrationClient()

async def _process_outbox(db: Session, model):
    pending = db.query(model).filter(model.status != "sent").all()
    for record in pending:
        if record.next_attempt_at and record.next_attempt_at > datetime.utcnow():
            continue
        try:
            logger.info(
                "Processing outbox record: record_id=%s event_type=%s attempt_count=%s",
                record.id,
                record.event_type,
                record.attempt_count,
            )
            resp = await integration_client._request_with_retry("POST", record.target_url, json=record.payload)
            record.attempt_count += 1
            logger.info(
                "Outbox delivery response: record_id=%s status=%s attempts=%s",
                record.id,
                resp.status_code,
                record.attempt_count,
            )
            if resp.status_code >= 500:
                raise Exception(f"remote error {resp.status_code}")
            record.status = "sent"
            record.last_error = None
        except Exception as exc:  # noqa: BLE001
            record.status = "failed"
            record.last_error = str(exc)
            record.attempt_count += 1
            record.next_attempt_at = datetime.utcnow() + timedelta(seconds=2 ** record.attempt_count)
            logger.warning(
                "Outbox delivery failed: record_id=%s error=%s next_attempt_at=%s attempt_count=%s",
                record.id,
                exc,
                record.next_attempt_at,
                record.attempt_count,
            )
        finally:
            db.add(record)
            db.commit()

async def background_outbox_worker(db_factory):
    while True:
        db = db_factory()
        try:
            await process_outbox(db)
        finally:
            db.close()
        await asyncio.sleep(2)
