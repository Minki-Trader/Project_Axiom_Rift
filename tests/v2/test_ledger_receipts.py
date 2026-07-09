from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from axiom_rift.v2.identity import ObjectStore
from axiom_rift.v2.ledger import HashChainLedger, LedgerError
from axiom_rift.v2.validation.receipts import ValidationReceiptStore, validation_key


class HashChainLedgerTests(unittest.TestCase):
    def test_append_chain_and_tamper_detection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "events.jsonl"
            ledger = HashChainLedger(path, "test")
            first = ledger.append("E1", "created", {"value": 1}, "2026-07-10T00:00:00Z")
            second = ledger.append("E2", "created", {"value": 2}, "2026-07-10T00:00:01Z")
            self.assertEqual(first["row_sha256"], second["previous_row_sha256"])
            rows = ledger.rows()
            rows[0]["payload"]["value"] = 9
            path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="ascii")
            with self.assertRaises(LedgerError):
                ledger.rows()

    def test_duplicate_content_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            ledger = HashChainLedger(Path(temp_dir) / "events.jsonl", "test")
            ledger.append("E1", "created", {"value": 1}, "2026-07-10T00:00:00Z")
            with self.assertRaises(LedgerError):
                ledger.append("E2", "created", {"value": 1}, "2026-07-10T00:00:01Z")


class ValidationReceiptTests(unittest.TestCase):
    def test_only_success_is_cache_hit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            objects = ObjectStore(root / "objects")
            ledger = HashChainLedger(root / "receipts.jsonl", "validation_receipt")
            store = ValidationReceiptStore(objects, ledger)
            key = validation_key("v", "code", {"a": "1"}, {"c": "2"}, {"d": "3"}, ["x"])
            failure = {"validation_key": key, "outcome": "fail", "issues": ["bad"]}
            store.record("VR1", "2026-07-10T00:00:00Z", failure)
            self.assertIsNone(store.cached_success(key))
            success = {"validation_key": key, "outcome": "pass", "issues": []}
            store.record("VR2", "2026-07-10T00:00:01Z", success)
            self.assertIsNotNone(store.cached_success(key))


if __name__ == "__main__":
    unittest.main()
