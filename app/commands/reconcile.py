import csv
import asyncio
from pathlib import Path
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app import models
from app.operator_client import operator_client

async def reconcile(output_path: str = "reconciliation.csv") -> int:
    db: Session = SessionLocal()
    local = db.query(models.Transaction).all()
    remote = await operator_client.list_transactions()
    remote_lookup = {(r["reference"], r["direction"]): r for r in remote}
    mismatches = []
    for txn in local:
        key = (txn.ref_id, txn.direction)
        remote_txn = remote_lookup.get(key)
        if not remote_txn:
            mismatches.append((txn.ref_id, txn.direction, txn.status, "missing"))
            continue
        if remote_txn.get("status") != txn.status:
            mismatches.append((txn.ref_id, txn.direction, txn.status, remote_txn.get("status")))
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["refId", "direction", "localStatus", "remoteStatus"])
        for row in mismatches:
            writer.writerow(row)
    return 1 if mismatches else 0

if __name__ == "__main__":
    exit_code = asyncio.run(reconcile())
    raise SystemExit(exit_code)
