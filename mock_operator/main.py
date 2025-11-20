from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List

app = FastAPI(title="Mock Operator")

class Operation(BaseModel):
    amount: float
    currency: str
    reference: str

transactions: List[dict] = []

@app.post("/v2/players/{player_external_id}/withdraw")
async def withdraw(player_external_id: str, body: Operation):
    if body.currency == "TRY":
        raise HTTPException(status_code=422, detail="unsupported currency")
    if body.reference in [t["reference"] for t in transactions if t["direction"] == "debit"]:
        return {"status": "OK", "balance": 1000.0, "correlationId": body.reference}
    txn = {
        "player": player_external_id,
        "amount": body.amount,
        "currency": body.currency,
        "reference": body.reference,
        "direction": "debit",
        "status": "OK",
        "balance": 1000.0 - body.amount,
    }
    transactions.append(txn)
    return {"status": "OK", "balance": txn["balance"], "correlationId": body.reference}

@app.post("/v2/players/{player_external_id}/deposit")
async def deposit(player_external_id: str, body: Operation):
    txn = {
        "player": player_external_id,
        "amount": body.amount,
        "currency": body.currency,
        "reference": body.reference,
        "direction": "credit",
        "status": "OK",
        "balance": 1000.0 + body.amount,
    }
    transactions.append(txn)
    return {"status": "OK", "balance": txn["balance"], "correlationId": body.reference}

@app.get("/v2/transactions")
async def list_transactions():
    return transactions
