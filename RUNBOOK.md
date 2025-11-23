# Runbook

# Starting locally
- Python 3.11 (same as the Docker base image).
- `docker-compose up --build` to start the hub plus mocks.
- Hub API available at `http://localhost:8000` with docs at `/docs`.
- Include `Authorization: Bearer <token>` on hub requests; token defaults to `change_token` and can be set via env `BEARER_TOKEN`.

# Idempotency replay
- Re-send a request with the same `Idempotency-Key`; hub returns cached response.
- Conflicting payloads with the same key return HTTP 409.

# Webhook replay
- Pending/failed webhooks live in `webhook_outbox` (SQLite). Restarting the hub will resume delivery.
- To force replay, delete `last_error` and set `status` to `pending` for the target record; the background worker will retry.
- Inspect queued/failed webhooks via `GET /webhooks/outbox?status=pending` (include bearer token).
- Mock operator also posts callbacks to `/webhooks/incoming`; this is fire-and-forget and errors are ignored.
- Mock RGS persists received webhooks in `/data/rgs.db` (table `received_webhooks`); list via `GET /webhooks`.

# Reconciliation Data
- Call `GET http://localhost:8000/reconciliation_data` with the bearer token; the response downloads `reconciliation.csv`.
- Inspect header `X-Mismatch-Count`; when greater than 0, the CSV rows list mismatched references/statuses between RGS webhooks and Operator transactions.
