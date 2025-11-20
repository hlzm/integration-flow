# Integration Hub

FastAPI-based adapter that normalizes the Operator wallet API to the internal wallet contract. Includes mock operator/RGS services and reconciliation tooling.

## Running
```
docker-compose up --build
```
Hub available at `http://localhost:8000`, mocks at `8001` and `8002`.

## Key features
- Idempotent wallet debit/credit endpoints with HMAC validation and currency whitelist.
- Operator client with retry/backoff and rate-limit protection.
- Webhook outbox with background retry worker.
- Reconciliation script producing CSV mismatches.
- Postman collection: `postman_collection.json`.
