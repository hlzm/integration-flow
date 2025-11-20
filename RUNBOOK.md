# Runbook

## Starting locally
- `docker-compose up --build` to start the hub plus mocks.
- Hub API available at `http://localhost:8000` with docs at `/docs`.

## Idempotency replay
- Re-send a request with the same `Idempotency-Key`; hub returns cached response.
- Conflicting payloads with the same key return HTTP 409.

## Webhook replay
- Pending/failed webhooks live in `webhook_outbox` (SQLite). Restarting the hub will resume delivery.
- To force replay, delete `last_error` and set `status` to `pending` for the target record; the background worker will retry.

## Signature troubleshooting
- Compute signature as `HMAC_SHA256(secret, f"{timestamp}:{sorted_json_body}")`.
- Ensure `X-Timestamp` is within ±5 minutes; otherwise hub returns 401.

## Error codes
- `401` invalid signature/timestamp skew.
- `409` idempotency conflict.
- `422` currency validation failure.
- `5xx` bubbled from Operator after retries are exhausted.

## Reconciliation job
- Run `python -m app.commands.reconcile` inside the hub container.
- Check `reconciliation.csv`; if non-empty, exit code is 1 and rows list mismatched references.
