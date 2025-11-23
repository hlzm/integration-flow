import asyncio
from datetime import datetime, timedelta, UTC
import os
import sys
from importlib import reload
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="function")
def app_module(tmp_path_factory):
    """
    Reload the app with a disposable SQLite DB and disable background workers.
    """
    db_path = tmp_path_factory.mktemp("data") / "test.db"
    new_env = {
        "DB_URL": f"sqlite:///{db_path}",
        "BEARER_TOKEN": "testtoken",
        "OPERATOR_BASE_URL": "http://mock-operator:8001",
        "RGS_WEBHOOK_URL": "http://mock-rgs:8002/webhooks",
        "TIMESTAMP_SKEW_SECONDS": "5",
    }
    old_env = {k: os.environ.get(k) for k in new_env}
    os.environ.update(new_env)

    try:
        import app.config as config
        import app.database as database
        import app.models.models as models
        import app.security as security
        import app.main as main

        reload(config)
        reload(database)
        reload(models)
        reload(security)
        reload(main)

        # Disable the endless background worker during tests.
        main.app.router.on_startup.clear()
        main.app.dependency_overrides[main.require_bearer_token] = lambda: None

        models.Base.metadata.drop_all(bind=database.engine)
        models.Base.metadata.create_all(bind=database.engine)
        return main, database, models
    finally:
        for key, value in old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


@pytest.fixture
def client(app_module):
    main, database, models = app_module
    models.Base.metadata.drop_all(bind=database.engine)
    models.Base.metadata.create_all(bind=database.engine)
    with TestClient(main.app) as client:
        yield client


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_wallet_action_creates_transaction_and_outbox(client, app_module):
    _, database, models = app_module
    payload = {
        "playerId": "player-1",
        "amountCents": 500,
        "currency": "USD",
        "refId": "ref-123",
    }
    resp = client.post("/wallet/debit", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "initiated"
    assert body["refId"] == "ref-123"
    assert "correlationId" in body

    with database.SessionLocal() as db:
        txns = db.query(models.Transaction).all()
        outbox = db.query(models.OperatorWebhookOutbox).all()
        assert len(txns) == 1
        assert txns[0].status == "initiated"
        assert len(outbox) == 1
        assert outbox[0].event_type == "debit"


def test_webhook_marks_transaction_sent_and_enqueues_rgs(client, app_module):
    main, database, models = app_module
    payload = {
        "playerId": "player-1",
        "amountCents": 500,
        "currency": "USD",
        "refId": "ref-456",
    }
    create_resp = client.post("/wallet/debit", json=payload)
    correlation_id = create_resp.json()["correlationId"]

    webhook_payload = {
        "playerId": "player-1",
        "amount": 5.00,
        "currency": "USD",
        "status": "OK",
        "event": "withdraw",
        "refId": "ref-456",
        "correlationId": correlation_id,
    }
    resp = client.post("/webhooks/incoming", json=webhook_payload)
    assert resp.status_code == 200
    assert resp.json() == {"status": "accepted"}

    with database.SessionLocal() as db:
        txn = db.query(models.Transaction).first()
        rgs_outbox = db.query(models.RGSWebhookOutbox).all()
        assert txn.status == "sent"
        assert len(rgs_outbox) == 1
        assert rgs_outbox[0].event_type == "debit"
        assert rgs_outbox[0].payload['amountCents'] == 500


# 1. Idempotent Debit (same key -> one charge).
def test_idempotency_reuses_existing_response(client, app_module):
    _, database, models = app_module
    headers = {"Idempotency-Key": "demo-key"}
    payload = {
        "playerId": "player-1",
        "amountCents": 750,
        "currency": "USD",
        "refId": "ref-789",
    }

    first = client.post("/wallet/credit", json=payload, headers=headers)
    second = client.post("/wallet/credit", json=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()

    with database.SessionLocal() as db:
        txns = db.query(models.Transaction).all()
        outbox = db.query(models.OperatorWebhookOutbox).all()
        # The second call should not create a new transaction or outbox item.
        assert len(txns) == 1
        assert len(outbox) == 1

# 2. Retry/backoff (500->500->200 success)
def test_operator_retry_on_server_errors(monkeypatch):
    from app.clients.operator_client import operator_client
    from app.helpers import IntegrationClient

    client = IntegrationClient(max_retries=5, retry_backoff_seconds=1)

    statuses = [500, 500, 200]
    calls = {"invokes": 0}

    async def fake_request(method, url, json):
        status = statuses[calls["invokes"]]
        calls["invokes"] += 1
        return type("Resp", (), {"status_code": status, "headers": {}, "json": lambda: {"ok": True}})()

    monkeypatch.setattr(client.client, "request", fake_request)

    loop = asyncio.new_event_loop()
    try:
        resp = loop.run_until_complete(client._request_with_retry("POST", "/some/url", json={"foo": "bar"}))
    finally:
        loop.close()

    assert calls["invokes"] == 3, "Should have attempted three times (500, 500, then 200)"
    assert resp.status_code == 200, "Final response should be 200 after retries"

# 3. Rate limit (429 Retry-After respected)
def test_rate_limit_returns_429_on_second_call(monkeypatch):
    from app.helpers import IntegrationClient
    
    async def fake_sleep(_):
        return None

    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code
            self.headers = {}

    monkeypatch.setattr("app.helpers.asyncio.sleep", fake_sleep)

    client = IntegrationClient(
        rate_limit_per_minute=1, 
        max_retries=0, 
        retry_backoff_seconds=3600)

    async def first_only_request(method, url, json):
        return FakeResponse(200)

    monkeypatch.setattr(client.client, "request", first_only_request)

    loop = asyncio.new_event_loop()
    try:
        first = loop.run_until_complete(client._request_with_retry("POST", "/some/url", json={"foo": "bar"}))
        second = loop.run_until_complete(client._request_with_retry("POST", "/some/url", json={"foo": "bar"}))
    finally:
        loop.close()

    assert first.status_code == 200
    assert second.status_code == 429, "Second call should return 429 when rate limit is hit"

# 4. Webhook delivery (500->200-> one delivery).
def test_rgs_outbox_retries_then_succeeds(monkeypatch, app_module):
    _, database, models = app_module
    from app.webhooks import process_outbox, integration_client

    # Seed a pending RGS outbox record.
    with database.SessionLocal() as db:
        record = models.RGSWebhookOutbox(
            event_type="debit",
            payload={"foo": "bar"},
            target_url="http://mock-rgs/webhooks",
            status="pending",
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        record_id = record.id

    responses = [500, 200]

    class FakeResponse:
        def __init__(self, status_code):
            self.status_code = status_code
            self.headers = {}

    async def fake_request(method, url, json):
        return FakeResponse(responses.pop(0))

    monkeypatch.setattr(integration_client, "_request_with_retry", fake_request)

    # First attempt fails (500).
    with database.SessionLocal() as db:
        asyncio.run(process_outbox(db))
        record = db.get(models.RGSWebhookOutbox, record_id)
        assert record.status == "failed"
        record.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        record.status = "pending"
        db.add(record)
        db.commit()

    # Second attempt succeeds (200).
    with database.SessionLocal() as db:
        asyncio.run(process_outbox(db))
        record = db.get(models.RGSWebhookOutbox, record_id)
        assert record.status == "sent"
        assert record.last_error is None
        assert record.attempt_count >= 2


# 5. Currency validation (TRY -> 422).
def test_wallet_action_currency_check(client):
    payload = {
        "playerId": "player-1",
        "amountCents": 500,
        "currency": "TRY",
        "refId": "ref-123",
    }
    resp = client.post("/wallet/debit", json=payload)
    assert resp.status_code == 422
    assert resp.json() == {"detail": "unsupported currency"}

    valid_payload = {
        "playerId": "player-1",
        "amountCents": 500,
        "currency": "EUR",
        "refId": "ref-123",
    }
    resp = client.post("/wallet/debit", json=valid_payload)
    assert resp.status_code == 200


# 7. Security (tampered signature -> 401)
def test_wallet_action_tampered_signature_rejected(client, app_module):
    main, _, _ = app_module
    payload = {
        "playerId": "player-1",
        "amountCents": 500,
        "currency": "USD",
        "refId": "ref-123",
    }
    timestamp = str(int(datetime.now().timestamp()))
    bad_signature = "invalidsignature"
    headers = {
        "X-Signature": bad_signature,
        "X-Timestamp": timestamp,
    }
    resp = client.post("/wallet/debit", json=payload, headers=headers)
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid signature"

# 6. Reconciliation mismatch detected.
def test_reconciliation_mismatch_detected(monkeypatch):
    from app.reconciliation import generate_reconciliation_csv

    async def fake_rgs():
        return [
            {"refId": "ref-local", "correlationId": "corr-1", "event": "credit", "amountCents": 1000},
            {"refId": "ref-ok1", "correlationId": "corr-ok1", "event": "credit", "amountCents": 2000},
            {"refId": "ref-ok3", "correlationId": "corr-ok3", "event": "debit", "amountCents": 3000},
        ]

    async def fake_operator():
        return [
            {"reference": "ref-remote", "correlationId": "corr-2", "direction": "deposit", "amount": 10.0},
            {"reference": "ref-ok1", "correlationId": "corr-ok1", "direction": "deposit", "amount": 10.0},
        ]

    monkeypatch.setattr("app.reconciliation.rgs_client.list_webhooks", fake_rgs)
    monkeypatch.setattr("app.reconciliation.operator_client.list_transactions", fake_operator)

    loop = asyncio.new_event_loop()
    try:
        csv_text, mismatch_count = loop.run_until_complete(generate_reconciliation_csv())
    finally:
        loop.close()

    assert mismatch_count == 3
    assert "refId,correlationId,direction,amount,inRGS,inOperator" in csv_text
    assert "ref-local,corr-1,credit,10.0,True,False" in csv_text
    assert "ref-remote,corr-2,deposit,10.0,False,True" in csv_text

def test_wallet_action_valid_signature_accepted(client, app_module):
    _, _, _ = app_module
    payload = {
        "playerId": "player-1",
        "amountCents": 500,
        "currency": "USD",
        "refId": "ref-123",
    }
    import app.security as security

    timestamp = str(int(datetime.now().timestamp()))
    signature = security.compute_signature(payload, timestamp)
    headers = {
        "X-Signature": signature,
        "X-Timestamp": timestamp,
    }
    resp = client.post("/wallet/debit", json=payload, headers=headers)
    assert resp.status_code == 200
    body = resp.json()