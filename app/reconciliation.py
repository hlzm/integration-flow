import csv
from io import StringIO
from typing import List, Tuple

from app.clients.operator_client import operator_client
from app.clients.rgs_client import rgs_client
from app.config import operator_hub_action_map
from app.logging_config import get_logger


logger = get_logger(__name__)

def _item_data(items: List[dict]) -> dict:
    return {f'{txn.get("correlationId")}': txn for txn in items if txn.get("correlationId")}

async def generate_reconciliation_csv() -> Tuple[str, int]:
    """
    Compare RGS-received transactions to operator transactions and return CSV text plus mismatch count.
    """
    local_data: List[dict] = await rgs_client.list_webhooks()
    remote_data: List[dict] = await operator_client.list_transactions()

    local_items = _item_data(local_data)
    remote_items = _item_data(remote_data)

    local_correlation_ids = local_items.keys()
    remote_correlation_ids = remote_items.keys()

    missing_in_remote = list(local_correlation_ids - remote_correlation_ids)
    missing_in_local = list(remote_correlation_ids - local_correlation_ids)

    mismatches: List[tuple] = []
    for corr_id in list(missing_in_remote + missing_in_local):
        if corr_id in missing_in_remote:
            # means its in local but not remote
            local_txn = local_items[corr_id]
            mismatches.append((
                local_txn["refId"],
                local_txn["correlationId"],
                local_txn["event"],
                local_txn["amountCents"] / 100, # convert to higher unit
                True,
                False,
            ))
        elif corr_id in missing_in_local:
            # means its in remote but not local
            remote_txn = remote_items[corr_id]
            mismatches.append((
                remote_txn["reference"],
                remote_txn["correlationId"],
                remote_txn["direction"],
                remote_txn["amount"],
                False,
                True,
            ))

    logger.info("Reconciliation complete with %s mismatches", len(mismatches))
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["refId", "correlationId","direction", "amount", "inRGS", "inOperator"])
    for row in mismatches:
        writer.writerow(row)

    return output.getvalue(), len(mismatches)
