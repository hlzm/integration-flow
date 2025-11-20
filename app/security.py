import hmac
import hashlib
import json
import time
from fastapi import HTTPException
from app.config import settings


def compute_signature(body: dict, timestamp: str) -> str:
    message = f"{timestamp}:{json.dumps(body, sort_keys=True)}".encode()
    return hmac.new(settings.hmac_secret.encode(), message, hashlib.sha256).hexdigest()


def validate_signature(body: dict, signature: str, timestamp: str):
    expected = compute_signature(body, timestamp)
    now = int(time.time())
    if abs(now - int(timestamp)) > settings.timestamp_skew_seconds:
        raise HTTPException(status_code=401, detail="timestamp skew")
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="invalid signature")
