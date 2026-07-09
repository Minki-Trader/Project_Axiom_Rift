"""Hash-keyed validation receipts; this module never runs validators."""

from __future__ import annotations

from typing import Any

from axiom_rift.v2.identity import ObjectStore, sha256_payload
from axiom_rift.v2.ledger import HashChainLedger


def validation_key(
    validator_id: str,
    validator_code_sha256: str,
    input_hashes: dict[str, str],
    config_hashes: dict[str, str],
    contract_hashes: dict[str, str],
    scope: list[str],
) -> str:
    return sha256_payload(
        {
            "validator_id": validator_id,
            "validator_code_sha256": validator_code_sha256,
            "input_hashes": input_hashes,
            "config_hashes": config_hashes,
            "contract_hashes": contract_hashes,
            "scope": sorted(scope),
        }
    )


class ValidationReceiptStore:
    def __init__(self, object_store: ObjectStore, ledger: HashChainLedger) -> None:
        self.object_store = object_store
        self.ledger = ledger

    def cached_success(self, key: str) -> dict[str, Any] | None:
        for row in self.ledger.rows():
            payload = row["payload"]
            if payload.get("validation_key") == key and payload.get("outcome") == "pass":
                receipt = self.object_store.get(payload["receipt_object_id"])
                if receipt["payload"].get("validation_key") != key:
                    raise RuntimeError("validation receipt key mismatch")
                return receipt
        return None

    def record(
        self,
        receipt_id: str,
        occurred_at_utc: str,
        receipt: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        if receipt.get("outcome") not in {"pass", "fail"}:
            raise ValueError("validation receipt outcome must be pass or fail")
        object_id = self.object_store.put("validation_receipt", receipt)
        row = self.ledger.append(
            receipt_id,
            "validation_receipt_recorded",
            {
                "validation_key": receipt["validation_key"],
                "outcome": receipt["outcome"],
                "receipt_object_id": object_id,
            },
            occurred_at_utc,
        )
        return object_id, row
