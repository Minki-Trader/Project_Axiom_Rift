from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from axiom_rift.core.canonical import canonical_bytes


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / ".agents"
    / "skills"
    / "run-research-portfolio"
    / "scripts"
    / "audit_research_history.py"
)


def load_script():
    spec = importlib.util.spec_from_file_location("audit_research_history", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeJournal:
    def __init__(self, events: dict[int, dict[str, object]]) -> None:
        self.events = events

    def read_event_at(
        self,
        *,
        offset: int,
        expected_sequence: int,
        expected_event_id: str,
    ) -> dict[str, object]:
        event = self.events[offset]
        if (
            event["sequence"] != expected_sequence
            or event["event_id"] != expected_event_id
        ):
            raise RuntimeError("fixture Journal authority differs")
        return event


class ResearchHistoryAuditTests(unittest.TestCase):
    def write_fixture(self, root: Path, module) -> dict[int, dict[str, object]]:
        (root / "state").mkdir()
        (root / "local").mkdir()
        (root / "records").mkdir()
        projection_digest = "d" * 64
        head_event_id = sha256(b"event-8").hexdigest()
        (root / "state" / "control.json").write_text(
            json.dumps(
                {
                    "heads": {
                        "index": {
                            "required_projection_digest": projection_digest,
                            "required_record_count": 8,
                        },
                        "journal": {"event_id": head_event_id},
                    },
                    "revision": 8,
                }
            ),
            encoding="ascii",
        )
        (root / "records" / "journal.jsonl").write_text("", encoding="ascii")
        connection = sqlite3.connect(root / "local" / "index.sqlite")
        connection.executescript(
            """
            CREATE TABLE projection_stats (
                singleton INTEGER PRIMARY KEY,
                record_count INTEGER NOT NULL,
                projection_digest TEXT NOT NULL,
                projection_valid INTEGER NOT NULL
            );
            CREATE TABLE records (
                kind TEXT NOT NULL,
                record_id TEXT NOT NULL,
                subject TEXT NOT NULL,
                status TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                event_stream TEXT,
                event_sequence INTEGER,
                authority_sequence INTEGER,
                authority_event_id TEXT,
                authority_offset INTEGER,
                record_digest TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO projection_stats VALUES (1, 8, ?, 1)",
            (projection_digest,),
        )
        rows = [
            (
                "study-open",
                "STU-0001",
                "Study:STU-0001",
                "open",
                {
                    "changed_domains": ["feature"],
                    "controlled_domains": ["label", "model", "trade"],
                    "mechanism_family": "fixture-family",
                    "mission_id": "MIS-0001",
                    "portfolio_decision_id": "decision:fixture",
                    "primary_research_layer": "feature",
                    "question": {
                        "causal_question": "Does the typed feature add information?",
                        "changed_variables": {"feature": ["fixture_feature"]},
                        "controlled_variables": {
                            "label": ["fixed_horizon"],
                            "model": ["deterministic_rule"],
                            "trade": ["next_open"],
                        },
                    },
                    "system_architecture_family": "architecture-family:fixture",
                },
                1,
            ),
            (
                "study-close",
                "close-1",
                "Study:STU-0001",
                "not_supported",
                {},
                2,
            ),
            (
                "study-kpi",
                "STU-0001",
                "Study:STU-0001",
                "not_supported",
                {"metrics": {"trade_count": 12}},
                3,
            ),
            (
                "portfolio-decision",
                "decision:fixture",
                "Mission:MIS-0001",
                "deepen",
                {
                    "chosen_option_id": "chosen",
                    "options": [
                        {"action": "deepen", "option_id": "chosen"}
                    ],
                },
                4,
            ),
            (
                "trial",
                "executable:fixture",
                "Batch:fixture",
                "evaluated",
                {
                    "executable": {
                        "component_manifests": [
                            {"protocol": "feature.fixture.v1"},
                            {"protocol": "model.fixture.v1"},
                        ]
                    },
                    "study_id": "STU-0001",
                },
                5,
            ),
            (
                "negative-memory",
                "negative:fixture",
                "Executable:fixture",
                "durable",
                {
                    "reopen_condition": "new information only",
                    "study_id": "STU-0001",
                },
                6,
            ),
            (
                "study-diagnosis",
                "diagnosis:fixture",
                "Study:STU-0001",
                "absent_information",
                {"confidence": "high"},
                7,
            ),
            (
                "mission-close",
                "mission-close-1",
                "Mission:MIS-0001",
                "closed_no_candidate",
                {},
                8,
            ),
        ]
        events: dict[int, dict[str, object]] = {}
        for kind, record_id, subject, status, payload, sequence in rows:
            event_id = sha256(f"event-{sequence}".encode("ascii")).hexdigest()
            payload_json = canonical_bytes(payload).decode("ascii")
            record = module.IndexRecord(
                kind=kind,
                record_id=record_id,
                subject=subject,
                status=status,
                fingerprint=f"fingerprint-{sequence}",
                payload=payload,
                event_stream=None,
                event_sequence=None,
                authority_sequence=sequence,
                authority_event_id=event_id,
                authority_offset=sequence,
            )
            connection.execute(
                "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.kind,
                    record.record_id,
                    record.subject,
                    record.status,
                    record.fingerprint,
                    payload_json,
                    record.event_stream,
                    record.event_sequence,
                    record.authority_sequence,
                    record.authority_event_id,
                    record.authority_offset,
                    module._record_digest(record, payload_json),
                ),
            )
            events[sequence] = {
                "event_id": event_id,
                "index_records": [module._projection_mapping(record)],
                "sequence": sequence,
            }
        connection.commit()
        connection.close()
        return events

    def test_audit_is_authority_bound_and_maps_typed_study_context(self) -> None:
        module = load_script()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            events = self.write_fixture(root, module)
            with patch.object(
                module,
                "DurableJournal",
                return_value=_FakeJournal(events),
            ):
                audit = module.build_audit(root)

        self.assertEqual(
            audit["history_head"],
            {"event_id": sha256(b"event-8").hexdigest(), "revision": 8},
        )
        self.assertEqual(audit["schema"], "research_history_audit.v2")
        self.assertEqual(audit["summary"]["study_count"], 1)
        self.assertEqual(audit["summary"]["authority_verified_record_count"], 8)
        self.assertEqual(
            audit["summary"]["primary_research_layer_study_counts"],
            {"feature": 1},
        )
        self.assertEqual(audit["summary"]["domain_alignment_counts"], {"aligned": 1})
        self.assertEqual(audit["studies"][0]["component_domains"], ["feature", "model"])
        self.assertEqual(audit["studies"][0]["domain_alignment"], "aligned")
        self.assertEqual(audit["studies"][0]["evidence_state"], "absent_information")
        self.assertEqual(audit["studies"][0]["diagnosis_confidence"], "high")
        self.assertEqual(audit["studies"][0]["portfolio_action"], "deepen")
        self.assertEqual(
            audit["studies"][0]["reopen_conditions"], ["new information only"]
        )

    def test_audit_rejects_sqlite_payload_tampering(self) -> None:
        module = load_script()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            events = self.write_fixture(root, module)
            connection = sqlite3.connect(root / "local" / "index.sqlite")
            connection.execute(
                "UPDATE records SET payload_json = ? WHERE kind = 'study-open'",
                (canonical_bytes({"tampered": True}).decode("ascii"),),
            )
            connection.commit()
            connection.close()
            with patch.object(
                module,
                "DurableJournal",
                return_value=_FakeJournal(events),
            ), self.assertRaisesRegex(RuntimeError, "record digest mismatch"):
                module.build_audit(root)


if __name__ == "__main__":
    unittest.main()
