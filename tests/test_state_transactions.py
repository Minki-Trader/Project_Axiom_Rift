from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from axiom_rift.state.c0008 import validate_c0008_transaction
from axiom_rift.state.transactions import StateTransaction, TransactionError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
C0008_PROBES = (
    PROJECT_ROOT / "src" / "axiom_rift" / "mt5" / "c0008_r0002_probe.py",
    PROJECT_ROOT / "src" / "axiom_rift" / "mt5" / "c0008_r0003_probe.py",
)


class StateTransactionTests(unittest.TestCase):
    def test_success_replaces_all_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            json_path = root / "state.json"
            yaml_path = root / "state.yaml"
            json_path.write_text('{"old": true}\n', encoding="ascii")
            yaml_path.write_text("old: true\n", encoding="ascii")

            tx = StateTransaction(root=root, label="success")
            tx.write_json(json_path, {"new": True})
            tx.write_yaml(yaml_path, {"new": True})
            tx.commit()

            self.assertEqual(json.loads(json_path.read_text(encoding="ascii")), {"new": True})
            self.assertEqual(yaml.safe_load(yaml_path.read_text(encoding="ascii")), {"new": True})

    def test_validator_failure_leaves_targets_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "state.json"
            path.write_text('{"old": true}\n', encoding="ascii")

            tx = StateTransaction(root=root, label="blocked")
            tx.write_json(path, {"new": True})
            tx.add_validator(lambda _: (_ for _ in ()).throw(TransactionError("blocked")))

            with self.assertRaises(TransactionError):
                tx.commit()
            self.assertEqual(json.loads(path.read_text(encoding="ascii")), {"old": True})

    def test_non_ascii_payload_fails_fast(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tx = StateTransaction(root=root, label="ascii")
            with self.assertRaises(TransactionError):
                tx.write_text(root / "state.txt", "non-ascii: cafe \u00e9")

    def test_invalid_json_and_missing_parent_fail_fast(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaises(json.JSONDecodeError):
                StateTransaction(root=root).write_text(root / "bad.json", "{", kind="json")

            tx = StateTransaction(root=root, label="missing-parent")
            tx.write_json(root / "missing" / "state.json", {"new": True})
            with self.assertRaises(TransactionError):
                tx.commit()


class C0008StateValidationTests(unittest.TestCase):
    def test_c0008_validator_accepts_aligned_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tx, paths, expected = self._build_c0008_draft(root)

            validate_c0008_transaction(
                tx,
                run_dir=paths["run_dir"],
                campaign_path=paths["campaign"],
                reentry_path=paths["reentry"],
                claim_state_path=paths["claim_state"],
                expected_next_action=expected,
                run_id="R0003",
            )

    def test_c0008_validator_rejects_next_action_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tx, paths, expected = self._build_c0008_draft(root)
            campaign = tx.read_yaml(paths["campaign"])
            campaign["closeout"]["remaining_question"] = "different_next_step"
            tx.write_yaml(paths["campaign"], campaign)

            with self.assertRaises(TransactionError):
                validate_c0008_transaction(
                    tx,
                    run_dir=paths["run_dir"],
                    campaign_path=paths["campaign"],
                    reentry_path=paths["reentry"],
                    claim_state_path=paths["claim_state"],
                    expected_next_action=expected,
                    run_id="R0003",
                )

    def test_c0008_validator_rejects_forbidden_claim_flags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tx, paths, expected = self._build_c0008_draft(root)
            claim_state = tx.read_yaml(paths["claim_state"])
            claim_state["latest_operation"]["claim_boundary"]["runtime_authority"] = True
            tx.write_yaml(paths["claim_state"], claim_state)

            with self.assertRaises(TransactionError):
                validate_c0008_transaction(
                    tx,
                    run_dir=paths["run_dir"],
                    campaign_path=paths["campaign"],
                    reentry_path=paths["reentry"],
                    claim_state_path=paths["claim_state"],
                    expected_next_action=expected,
                    run_id="R0003",
                )

    def test_c0008_probes_use_transaction_for_state_writes(self) -> None:
        forbidden = (
            "RUN_MANIFEST.write_text",
            "GATE_REPORT.write_text",
            "ARTIFACT_LINEAGE.write_text",
            "CLAIM_STATE.write_text",
            "CAMPAIGN.write_text",
            "MT5_LOGIC_KPI.write_text",
            "MT5_TICK_KPI.write_text",
            "MT5_TICK_BY_FOLD_KPI.write_text",
            "LOGIC_PARITY_KPI.write_text",
            "EXECUTION_DIVERGENCE_KPI.write_text",
            "EXECUTION_DIVERGENCE_BY_FOLD_KPI.write_text",
            "kpi_path.write_text",
            "path.write_text(yaml.safe_dump",
        )
        offenders: list[str] = []
        for path in C0008_PROBES:
            text = path.read_text(encoding="ascii")
            for pattern in forbidden:
                if pattern in text:
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {pattern}")
        self.assertEqual(offenders, [])

    def _build_c0008_draft(self, root: Path) -> tuple[StateTransaction, dict[str, Path], str]:
        run_dir = root / "campaigns" / "C0008" / "runs" / "R0003"
        (run_dir / "kpi").mkdir(parents=True)
        (run_dir / "artifacts").mkdir()
        for rel_path in (
            "kpi/mt5_tick_by_fold.json",
            "kpi/execution_divergence_by_fold.json",
            "artifact_lineage.json",
            "artifacts/c0008_r0003_schedule.csv",
        ):
            (run_dir / rel_path).write_text("{}\n", encoding="ascii")
        campaign = root / "campaigns" / "C0008" / "campaign.yaml"
        reentry = root / "registries" / "reentry.yaml"
        claim_state = root / "registries" / "claim_state.yaml"
        campaign.parent.mkdir(parents=True, exist_ok=True)
        reentry.parent.mkdir(parents=True, exist_ok=True)
        expected = "review_c0008_r0003_tick_execution_kpi_and_closeout"
        false_boundary = {
            "claim_authority": False,
            "selected": False,
            "label_selected": False,
            "feature_set_selected": False,
            "model_selected": False,
            "runtime_authority": False,
            "onnx_ready": False,
            "promotion_ready": False,
            "live_ready": False,
        }

        tx = StateTransaction(root=root, label="c0008")
        tx.write_json(
            run_dir / "run_manifest.json",
            {
                "run_id": "R0003",
                "gate_status": "fold_isolated_evidence_recorded_pending_closeout_review",
                "evidence_paths": {
                    "mt5_tick_by_fold_kpi": "kpi/mt5_tick_by_fold.json",
                    "execution_divergence_by_fold_kpi": "kpi/execution_divergence_by_fold.json",
                    "artifact_lineage": "artifact_lineage.json",
                    "mt5_schedule_artifact": "artifacts/c0008_r0003_schedule.csv",
                },
                "claim_boundary": false_boundary,
            },
        )
        tx.write_json(
            run_dir / "gate_report.json",
            {
                "evidence_gate": {"status": "fold_isolated_evidence_recorded"},
                "rolling_window_closeout_gate": {
                    "status": "fold_isolated_evidence_recorded_pending_closeout_review"
                },
                "evidence_paths": [
                    "kpi/mt5_tick_by_fold.json",
                    "kpi/execution_divergence_by_fold.json",
                    "artifact_lineage.json",
                    "artifacts/c0008_r0003_schedule.csv",
                ],
                "next_action": expected,
                "claim_boundary": false_boundary,
            },
        )
        tx.write_yaml(campaign, {"closeout": {"remaining_question": expected}, "claim_boundary": false_boundary})
        tx.write_yaml(reentry, {"next_work": {"tasks": [expected]}, "claim_boundary": false_boundary})
        tx.write_yaml(
            claim_state,
            {
                "latest_operation": {
                    "next_required_action": expected,
                    "claim_boundary": false_boundary,
                },
                "claim_boundary": false_boundary,
            },
        )
        return tx, {"run_dir": run_dir, "campaign": campaign, "reentry": reentry, "claim_state": claim_state}, expected


if __name__ == "__main__":
    unittest.main()
