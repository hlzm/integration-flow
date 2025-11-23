# Integration Hub Overview

This project provides a small adapter service that normalizes an Operator's wallet API into the internal wallet contract exposed by the RGS.

## Architecture
- **Integration Hub (FastAPI)**: exposes `/wallet/{debit|credit}`  wherre action is `debit` or ` credit`. Code validates signatures, enforces idempotency and currency rules, and maps to the Operator `/v2/players/{playerExternalId}/{withdraw|deposit}` endpoint.
- **Persistence (SQLite)**: stores idempotency keys, normalized transactions, and webhook outbox for reliable delivery.
- **Operator Mock**: lightweight FastAPI service that simulates the operator wallet including currency rejection and idempotent withdraw handling.
- **RGS Mock**: accepts outbound webhooks to validate delivery flows and persists received payloads
- **Webhook Worker**: background task that retries failed deliveries with exponential backoff until success.
- **Operator callbacks**: mock operator asynchronously calls back `POST /webhooks/incoming` after processing withdraw/deposit to simulate operator-originated notifications.

### Sequence: Debit|Credit
1. RGS calls `POST /wallet/{credit|debit}` with `Idempotency-Key`, `X-Signature`, and `X-Timestamp`.
2. Hub validates HMAC over `timestamp:body` and skew (±5s), and checks currency whitelist.
3. If idempotent key exists with same payload hash, cached response is returned.
4. Hub maps to `POST /v2/players/{playerExternalId}/{withdraw|deposit}` - add it to out box (amount converted to decimal) with retry/backoff and rate limit guard.
5. Outbound webhook is enqueued to RGS mock (when configured) and delivered by worker with retries.

### Idempotency Flow
- Requests supply `Idempotency-Key` header.
- Payload is hashed; if a record exists for the key and hash, the cached response is returned.
- Conflicting hash returns 409 to prevent duplicated charges.

### Signature Scheme
`X-Signature = HMAC_SHA256(secret, "{timestamp}:{sorted_json_body}")` with header `X-Timestamp`. The hub rejects tampered bodies or timestamps older than 300 seconds.

### Reconciliation
`GET /reconciliation_data` (with bearer token) compares RGS `/webhooks` records to Operator `/v2/transactions` and returns a `reconciliation.csv` attachment; header `X-Mismatch-Count` is non-zero when differences exist.

### Reliability and Observability
- Retry/backoff on 5xx/429 from the Operator client with exponential wait.
- Webhook outbox persists payloads, increases attempt_count, and backoff doubles after each failure.
- `/health` integration hub health check endpoint

### Docker Compose
`docker-compose up --build` starts Hub (port 8000), Mock Operator (8001), and Mock RGS (8002) sharing a persisted SQLite database volume.
