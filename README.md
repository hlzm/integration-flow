# Integration Hub

Integration Hub as connecting piece between operator and RGS
At the moment I have outbox for both operator and rgs as both are services on its own, but this can be adjusted so oubox is only used for RGS...

# Running
```
docker-compose up --build
```
Hub available at `http://localhost:8000`, mocks at `8001` and `8002`.
Requests must include `Authorization: Bearer <token>` (default token `change_token`, override with env `BEARER_TOKEN`).
Swagger UI at `http://localhost:8000/swagger`.

# Key features
- Idempotent wallet debit/credit endpoints with HMAC validation and currency whitelist.
- Operator client with retry/backoff and rate-limit protection.
- Webhook outbox with background retry worker.
- Reconciliation endpoint comparing RGS webhooks to Operator transactions and returning a CSV mismatch report.
- Postman collection: `postman_collection.json`.

# Admin replay and error codes
- Replay outbox: `POST /admin/replay/{queue}/{record_id}` (queue: `rgs` or `operator`, bearer auth required). Resets status to `pending`, clears `last_error`, resets `next_attempt_at`.
  - Find `record_id` via `GET /webhooks/outbox?queue=rgs|operator` (requires bearer token); use the `id` field returned.
- Signature errors: `401 invalid signature` (HMAC mismatch) or `401 timestamp skew` (timestamp outside allowed skew).
- Currency errors: `422 unsupported currency` when currency not in `supported_currencies`.
- Idempotency conflicts: `409 idempotency conflict` when the same `Idempotency-Key` is reused with a different payload hash.
- Unknown webhook: `404 unknown reference/correlation` when correlation/ref do not match a stored transaction.

# Tests
- docker
    ```
    docker compose build hub
    docker compose run --rm hub pytest -s
    ```

- local run be in app root
    ```
    pytest tests
    ```
