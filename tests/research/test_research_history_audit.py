from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest


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


class ResearchHistoryAuditTests(unittest.TestCase):
    def test_audit_is_head_bound_and_maps_typed_study_context(self) -> None:
        module = load_script()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "state").mkdir()
            (root / "local").mkdir()
            projection_digest = "d" * 64
            event_id = "e" * 64
            (root / "state" / "control.json").write_text(
                json.dumps(
                    {
                        "heads": {
                            "index": {
                                "required_projection_digest": projection_digest,
                                "required_record_count": 8,
                            },
                            "journal": {"event_id": event_id},
                        },
                        "revision": 9,
                    }
                ),
                encoding="ascii",
            )
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
                    payload_json TEXT NOT NULL,
                    authority_sequence INTEGER
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
                        "mechanism_family": "fixture-family",
                        "mission_id": "MIS-0001",
                        "portfolio_decision_id": "decision:fixture",
                        "primary_research_layer": "feature",
                        "question": {
                            "causal_question": "Does the typed feature add information?",
                            "changed_variables": ["feature"],
                            "controlled_variables": ["label", "trade"],
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
            for kind, record_id, subject, status, payload, sequence in rows:
                connection.execute(
                    "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        kind,
                        record_id,
                        subject,
                        status,
                        json.dumps(payload),
                        sequence,
                    ),
                )
            connection.commit()
            connection.close()

            audit = module.build_audit(root)

        self.assertEqual(audit["history_head"], {"event_id": event_id, "revision": 9})
        self.assertEqual(audit["summary"]["study_count"], 1)
        self.assertEqual(
            audit["summary"]["primary_research_layer_study_counts"],
            {"feature": 1},
        )
        self.assertEqual(audit["studies"][0]["component_domains"], ["feature", "model"])
        self.assertEqual(audit["studies"][0]["evidence_state"], "absent_information")
        self.assertEqual(audit["studies"][0]["diagnosis_confidence"], "high")
        self.assertEqual(audit["studies"][0]["portfolio_action"], "deepen")
        self.assertEqual(
            audit["studies"][0]["reopen_conditions"], ["new information only"]
        )


if __name__ == "__main__":
    unittest.main()
