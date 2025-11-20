# Integration Hub Overview

This project provides a small adapter service that normalizes an Operator's wallet API into the internal wallet contract exposed by the RGS.

## Architecture
- **Integration Hub (FastAPI)**: exposes `/wallet/debit` and `/wallet/credit`, validates signatures, enforces idempotency and currency rules, and maps to the Operator `/v2/players/{id}/withdraw|deposit` endpoints.
- **Persistence (SQLite)**: stores idempotency keys, normalized transactions, and webhook outbox for reliable delivery.
- **Operator Mock**: lightweight FastAPI service that simulates the operator wallet including currency rejection and idempotent withdraw handling.
- **RGS Mock**: accepts outbound webhooks to validate delivery flows.
- **Webhook Worker**: background task that retries failed deliveries with exponential backoff until success.

### Sequence: Debit
1. RGS calls `POST /wallet/debit` with `Idempotency-Key`, `X-Signature`, and `X-Timestamp`.
2. Hub validates HMAC over `timestamp:body` and skew (±300s), and checks currency whitelist.
3. If idempotent key exists with same payload hash, cached response is returned.
4. Hub maps to `POST /v2/players/{playerExternalId}/withdraw` (amount converted to decimal) with retry/backoff and rate limit guard.
5. Operator response is normalized to `{status, balanceCents}` and persisted to `transactions`.
6. Outbound webhook is enqueued to RGS mock (when configured) and delivered by worker with retries.

### Sequence: Credit
Follows the same flow but calls the Operator `deposit` endpoint and stores direction `credit`.

### Idempotency Flow
- Requests supply `Idempotency-Key` header.
- Payload is hashed; if a record exists for the key and hash, the cached response is returned.
- Conflicting hash returns 409 to prevent duplicated charges.

### Signature Scheme
`X-Signature = HMAC_SHA256(secret, "{timestamp}:{sorted_json_body}")` with header `X-Timestamp`. The hub rejects tampered bodies or timestamps older than 300 seconds.

### Reconciliation
`python -m app.commands.reconcile` fetches local transactions and Operator `/v2/transactions` then writes `reconciliation.csv` containing mismatches; process exits non-zero when differences exist.

### Reliability and Observability
- Retry/backoff on 5xx/429 from the Operator client with exponential wait.
- Webhook outbox persists payloads, increases attempt_count, and backoff doubles after each failure.
- `/healthz` endpoint for liveness and structured JSON logging via FastAPI/uvicorn.

### Docker Compose
`docker-compose up --build` starts Hub (port 8000), Mock Operator (8001), and Mock RGS (8002) sharing a persisted SQLite database volume.
