"""Append-only, hash-chained V2 event ledgers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from axiom_rift.v2.identity import canonical_json_bytes, sha256_payload


class LedgerError(RuntimeError):
    """Raised when a V2 ledger is invalid or cannot append safely."""


class HashChainLedger:
    def __init__(self, path: Path, ledger_name: str) -> None:
        self.path = path.resolve()
        self.ledger_name = ledger_name
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def rows(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            for number, line in enumerate(self.path.read_text(encoding="ascii").splitlines(), start=1):
                if not line:
                    raise LedgerError(f"blank ledger line: {self.path}:{number}")
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise LedgerError(f"ledger row is not an object: {self.path}:{number}")
                rows.append(row)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise LedgerError(f"invalid ledger {self.path}: {exc}") from exc
        self._validate_rows(rows)
        return rows

    def append(
        self,
        record_id: str,
        record_type: str,
        payload: dict[str, Any],
        occurred_at_utc: str,
    ) -> dict[str, Any]:
        lock = self.path.with_suffix(self.path.suffix + ".lock")
        pending = self.path.with_suffix(self.path.suffix + ".pending")
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise LedgerError(f"ledger lock exists: {lock}") from exc
        os.close(descriptor)
        try:
            self.recover_pending()
            rows = self.rows()
            content_sha256 = sha256_payload(payload)
            if any(row.get("record_id") == record_id for row in rows):
                raise LedgerError(f"duplicate record id: {record_id}")
            if any(row.get("content_sha256") == content_sha256 for row in rows):
                raise LedgerError(f"duplicate semantic content: {content_sha256}")
            row = {
                "schema": "axiom_rift_v2_ledger_row_v1",
                "ledger": self.ledger_name,
                "ledger_seq": len(rows) + 1,
                "previous_row_sha256": rows[-1]["row_sha256"] if rows else None,
                "record_id": record_id,
                "record_type": record_type,
                "occurred_at_utc": occurred_at_utc,
                "content_sha256": content_sha256,
                "payload": payload,
            }
            row["row_sha256"] = sha256_payload(row)
            line = canonical_json_bytes(row) + b"\n"
            with pending.open("wb") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            with self.path.open("ab") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            pending.unlink(missing_ok=True)
            self.rows()
            return row
        finally:
            lock.unlink(missing_ok=True)

    def recover_pending(self) -> None:
        pending = self.path.with_suffix(self.path.suffix + ".pending")
        if not pending.exists():
            return
        try:
            line = pending.read_bytes()
            row = json.loads(line.decode("ascii"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise LedgerError(f"invalid pending ledger row: {pending}") from exc
        current = self.rows()
        if current and current[-1].get("row_sha256") == row.get("row_sha256"):
            pending.unlink()
            return
        expected_seq = len(current) + 1
        expected_previous = current[-1]["row_sha256"] if current else None
        if row.get("ledger_seq") != expected_seq or row.get("previous_row_sha256") != expected_previous:
            raise LedgerError("pending ledger row does not extend the current chain")
        with self.path.open("ab") as handle:
            handle.write(line if line.endswith(b"\n") else line + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        pending.unlink()
        self.rows()

    def _validate_rows(self, rows: list[dict[str, Any]]) -> None:
        previous: str | None = None
        record_ids: set[str] = set()
        for expected_seq, row in enumerate(rows, start=1):
            if row.get("schema") != "axiom_rift_v2_ledger_row_v1":
                raise LedgerError(f"ledger schema mismatch at sequence {expected_seq}")
            if row.get("ledger") != self.ledger_name:
                raise LedgerError(f"ledger name mismatch at sequence {expected_seq}")
            if row.get("ledger_seq") != expected_seq:
                raise LedgerError(f"ledger sequence mismatch at {expected_seq}")
            if row.get("previous_row_sha256") != previous:
                raise LedgerError(f"ledger chain mismatch at sequence {expected_seq}")
            record_id = row.get("record_id")
            if not isinstance(record_id, str) or record_id in record_ids:
                raise LedgerError(f"invalid or duplicate record id at sequence {expected_seq}")
            record_ids.add(record_id)
            payload = row.get("payload")
            if row.get("content_sha256") != sha256_payload(payload):
                raise LedgerError(f"content hash mismatch at sequence {expected_seq}")
            stored_hash = row.get("row_sha256")
            unhashed = {key: value for key, value in row.items() if key != "row_sha256"}
            if stored_hash != sha256_payload(unhashed):
                raise LedgerError(f"row hash mismatch at sequence {expected_seq}")
            previous = stored_hash
