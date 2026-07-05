from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from axiom_rift.validation.price_quality import BASE_FRAME_RELATIVE_PATH, PRICE_QUALITY_AUDIT_RELATIVE_PATH
from axiom_rift.validation.repo_state import validate_repo_state


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")


def write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False), encoding="ascii")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RepoStateValidationTest(unittest.TestCase):
    def test_minimal_repo_state_validates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = make_repo_state(Path(temp_dir))
            result = validate_repo_state(root)
            self.assertTrue(result.ok, result.to_dict())
            payload = result.to_dict()
            self.assertEqual(payload["blocking_issues"], [])
            self.assertEqual(payload["warnings"], [])

    def test_next_action_mismatch_is_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = make_repo_state(Path(temp_dir))
            reentry_path = root / "registries" / "reentry.yaml"
            reentry = yaml.safe_load(reentry_path.read_text(encoding="ascii"))
            reentry["next_work"]["tasks"] = ["different_next_action"]
            write_yaml(reentry_path, reentry)

            result = validate_repo_state(root)

            self.assertFalse(result.ok)
            self.assertIn("next_action_mismatch", issue_codes(result))

    def test_campaign_level_latest_operation_does_not_require_gate_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = make_repo_state(Path(temp_dir))
            claim_path = root / "registries" / "claim_state.yaml"
            claim = yaml.safe_load(claim_path.read_text(encoding="ascii"))
            claim["active_run"] = None
            claim["latest_operation"]["recorded_at_source"] = (CAMPAIGN_REL / "campaign.yaml").as_posix()
            write_yaml(claim_path, claim)

            result = validate_repo_state(root)

            self.assertTrue(result.ok, result.to_dict())
            self.assertNotIn("next_action_missing", issue_codes(result))

    def test_active_synthesis_next_action_uses_synthesis_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = make_repo_state(Path(temp_dir))
            write_yaml(
                root / SYNTHESIS_REL / "synthesis.yaml",
                {
                    "synthesis_id": "SC0001",
                    "synthesis_slug": "smoke_synthesis",
                    "status": "open",
                    "opened_at_utc": "2026-01-01T00:00:00Z",
                    "synthesis_question": {"summary": "smoke", "boundary": "smoke"},
                    "claim_boundary": false_boundary(),
                },
            )
            write_yaml(
                root / SYNTHESIS_REL / "synthesis_queue.yaml",
                {
                    "synthesis_id": "SC0001",
                    "queue": [{"synthesis_run_id": "SR0001", "next_action": SYNTHESIS_NEXT_ACTION}],
                    "claim_boundary": false_boundary(),
                },
            )

            claim_path = root / "registries" / "claim_state.yaml"
            claim = yaml.safe_load(claim_path.read_text(encoding="ascii"))
            claim["active_synthesis"] = SYNTHESIS_REL.as_posix()
            claim["active_run"] = None
            claim["latest_operation"]["recorded_at_source"] = (SYNTHESIS_REL / "synthesis.yaml").as_posix()
            claim["latest_operation"]["next_required_action"] = SYNTHESIS_NEXT_ACTION
            write_yaml(claim_path, claim)

            reentry_path = root / "registries" / "reentry.yaml"
            reentry = yaml.safe_load(reentry_path.read_text(encoding="ascii"))
            reentry["project"]["active_synthesis"] = SYNTHESIS_REL.as_posix()
            reentry["next_work"]["synthesis"] = SYNTHESIS_REL.as_posix()
            reentry["next_work"]["tasks"] = [SYNTHESIS_NEXT_ACTION]
            write_yaml(reentry_path, reentry)

            result = validate_repo_state(root)

            self.assertTrue(result.ok, result.to_dict())
            self.assertNotIn("next_action_mismatch", issue_codes(result))

    def test_no_active_campaign_after_closeout_can_choose_next_major_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = make_repo_state(Path(temp_dir))
            next_action = "choose_c0002_new_major_hypothesis_after_c0001_closeout"

            claim_path = root / "registries" / "claim_state.yaml"
            claim = yaml.safe_load(claim_path.read_text(encoding="ascii"))
            claim["active_campaign"] = None
            claim["active_run"] = None
            claim["latest_operation"]["recorded_at_source"] = (RUN_REL / "gate_report.json").as_posix()
            claim["latest_operation"]["evidence_status"] = "closed_no_candidate"
            claim["latest_operation"]["next_required_action"] = next_action
            write_yaml(claim_path, claim)

            reentry_path = root / "registries" / "reentry.yaml"
            reentry = yaml.safe_load(reentry_path.read_text(encoding="ascii"))
            reentry["project"]["active_campaign"] = None
            reentry["next_work"]["campaign"] = None
            reentry["next_work"]["tasks"] = [next_action]
            write_yaml(reentry_path, reentry)

            manifest_path = root / RUN_REL / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="ascii"))
            manifest["status"] = "closed_no_candidate"
            write_json(manifest_path, manifest)

            gate_path = root / RUN_REL / "gate_report.json"
            gate = json.loads(gate_path.read_text(encoding="ascii"))
            gate["decision"] = "close_no_candidate"
            gate["next_action"] = next_action
            write_json(gate_path, gate)

            result = validate_repo_state(root)

            self.assertTrue(result.ok, result.to_dict())
            self.assertNotIn("active_campaign_missing", issue_codes(result))
            self.assertNotIn("next_action_missing", issue_codes(result))

    def test_missing_evidence_path_is_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = make_repo_state(Path(temp_dir))
            (root / RUN_REL / "kpi" / "mt5_tick_by_fold.json").unlink()

            result = validate_repo_state(root)

            self.assertFalse(result.ok)
            self.assertIn("evidence_path_missing", issue_codes(result))

    def test_artifact_hash_mismatch_is_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = make_repo_state(Path(temp_dir))
            lineage_path = root / RUN_REL / "artifact_lineage.json"
            lineage = json.loads(lineage_path.read_text(encoding="ascii"))
            lineage["artifact_records"][0]["sha256"] = "0" * 64
            write_json(lineage_path, lineage)

            result = validate_repo_state(root)

            self.assertFalse(result.ok)
            self.assertIn("artifact_lineage_hash_mismatch", issue_codes(result))

    def test_forbidden_claim_true_is_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = make_repo_state(Path(temp_dir))
            claim_path = root / "registries" / "claim_state.yaml"
            claim = yaml.safe_load(claim_path.read_text(encoding="ascii"))
            claim["latest_operation"]["claim_boundary"]["runtime_authority"] = True
            write_yaml(claim_path, claim)

            result = validate_repo_state(root)

            self.assertFalse(result.ok)
            self.assertIn("forbidden_claim_true", issue_codes(result))

    def test_runtime_config_incomplete_is_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = make_repo_state(Path(temp_dir))
            runtime_path = root / "configs" / "runtime.yaml"
            runtime = yaml.safe_load(runtime_path.read_text(encoding="ascii"))
            runtime["claim_boundary"]["active_runtime_config_complete"] = False
            write_yaml(runtime_path, runtime)

            result = validate_repo_state(root)

            self.assertTrue(result.ok, result.to_dict())
            self.assertIn("runtime_config_incomplete", issue_codes(result))
            self.assertEqual(result.to_dict()["warning_count"], 1)

    def test_missing_price_quality_audit_is_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = make_repo_state(Path(temp_dir))
            (root / PRICE_QUALITY_AUDIT_RELATIVE_PATH).unlink()

            result = validate_repo_state(root)

            self.assertFalse(result.ok)
            self.assertIn("price_quality_audit_missing", issue_codes(result))

    def test_stale_price_quality_hash_is_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = make_repo_state(Path(temp_dir))
            (root / BASE_FRAME_RELATIVE_PATH).write_text(
                "time,open,high,low,close,tick_volume,spread,real_volume\n",
                encoding="ascii",
            )

            result = validate_repo_state(root)

            self.assertFalse(result.ok)
            self.assertIn("price_quality_base_frame_hash_mismatch", issue_codes(result))

    def test_price_quality_blocker_count_is_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = make_repo_state(Path(temp_dir))
            audit_path = root / PRICE_QUALITY_AUDIT_RELATIVE_PATH
            audit = json.loads(audit_path.read_text(encoding="ascii"))
            audit["blocker_count"] = 1
            write_json(audit_path, audit)

            result = validate_repo_state(root)

            self.assertFalse(result.ok)
            self.assertIn("price_quality_blockers_recorded", issue_codes(result))

    def test_price_quality_warning_count_is_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = make_repo_state(Path(temp_dir))
            audit_path = root / PRICE_QUALITY_AUDIT_RELATIVE_PATH
            audit = json.loads(audit_path.read_text(encoding="ascii"))
            audit["warning_count"] = 3
            write_json(audit_path, audit)

            result = validate_repo_state(root)

            self.assertTrue(result.ok, result.to_dict())
            self.assertIn("price_quality_warnings_recorded", issue_codes(result))


RUN_REL = Path("campaigns/C0001_smoke/runs/R0001")
CAMPAIGN_REL = Path("campaigns/C0001_smoke")
SYNTHESIS_REL = Path("campaigns/SC0001_smoke_synthesis")
NEXT_ACTION = "review_c0001_r0001_tick_execution_kpi_and_closeout"
SYNTHESIS_NEXT_ACTION = "open_sc0001_sr0001_smoke_synthesis_run"


def issue_codes(result) -> set[str]:
    return {issue.code for issue in result.issues}


def false_boundary() -> dict[str, bool]:
    return {
        "label_selected": False,
        "feature_set_selected": False,
        "model_selected": False,
        "runtime_authority": False,
        "live_ready": False,
        "selected": False,
        "promotion_ready": False,
        "onnx_ready": False,
    }


def make_repo_state(root: Path) -> Path:
    run = root / RUN_REL
    kpi = run / "kpi"
    kpi.mkdir(parents=True, exist_ok=True)
    write_json(kpi / "mt5_tick_by_fold.json", {"required_kpis": {"mt5_tick_by_fold_status": "completed"}})
    write_json(
        kpi / "execution_divergence_by_fold.json",
        {"required_kpis": {"execution_divergence_by_fold_status": "completed"}},
    )
    write_json(kpi / "proxy.json", {"required_kpis": {}})
    write_json(run / "artifacts" / "schedule.csv", {"rows": []})
    base_frame = root / BASE_FRAME_RELATIVE_PATH
    base_frame.parent.mkdir(parents=True, exist_ok=True)
    base_frame.write_text(
        "time,open,high,low,close,tick_volume,spread,real_volume\n"
        "2026-01-01 00:00:00,100,105,95,101,10,1,0\n",
        encoding="ascii",
    )
    write_json(
        root / PRICE_QUALITY_AUDIT_RELATIVE_PATH,
        {
            "schema": "axiom_rift_us100_m5_price_quality_v1",
            "base_frame_csv": BASE_FRAME_RELATIVE_PATH,
            "base_frame_sha256": sha256_file(base_frame),
            "blocker_count": 0,
            "warning_count": 0,
        },
    )

    write_yaml(
        root / "configs" / "runtime.yaml",
        {"claim_boundary": {"active_runtime_config_complete": True, "runtime_authority": False, "live_ready": False}},
    )
    write_yaml(
        root / "registries" / "claim_state.yaml",
        {
            "active_campaign": CAMPAIGN_REL.as_posix(),
            "active_run": RUN_REL.as_posix(),
            "latest_operation": {
                "recorded_at_source": (RUN_REL / "kpi" / "mt5_tick_by_fold.json").as_posix(),
                "next_required_action": NEXT_ACTION,
                "claim_boundary": false_boundary(),
            },
            "claim_boundary": false_boundary(),
        },
    )
    write_yaml(
        root / "registries" / "reentry.yaml",
        {
            "project": {"active_campaign": CAMPAIGN_REL.as_posix()},
            "next_work": {"campaign": CAMPAIGN_REL.as_posix(), "tasks": [NEXT_ACTION]},
            "claim_boundary": false_boundary(),
        },
    )
    write_yaml(
        root / CAMPAIGN_REL / "campaign.yaml",
        {
            "run_index": {"active_run": None},
            "closeout": {"remaining_question": NEXT_ACTION},
            "claim_boundary": false_boundary(),
        },
    )
    write_json(
        run / "run_manifest.json",
        {
            "status": "fold_isolated_evidence_recorded_pending_closeout_review",
            "evidence_paths": {
                "mt5_tick_by_fold_kpi": "kpi/mt5_tick_by_fold.json",
                "execution_divergence_by_fold_kpi": "kpi/execution_divergence_by_fold.json",
                "artifact_lineage": "artifact_lineage.json",
            },
            "claim_boundary": false_boundary(),
        },
    )
    write_json(
        run / "gate_report.json",
        {
            "decision": "defer_with_reason",
            "next_action": NEXT_ACTION,
            "evidence_paths": [
                "kpi/mt5_tick_by_fold.json",
                "kpi/execution_divergence_by_fold.json",
                "artifact_lineage.json",
            ],
            "rolling_window_closeout_gate": {
                "fold_isolated_exception": {
                    "applies": False,
                    "reason": "",
                    "blocking_condition": "",
                    "revisit_when": "",
                }
            },
            "claim_boundary": false_boundary(),
        },
    )
    write_json(
        run / "artifact_lineage.json",
        {
            "artifact_records": [
                {
                    "artifact_id": "A-C0001-R0001-TICK-BY-FOLD",
                    "repo_relative_path": (RUN_REL / "kpi" / "mt5_tick_by_fold.json").as_posix(),
                    "sha256": sha256_file(kpi / "mt5_tick_by_fold.json"),
                },
                {
                    "artifact_id": "A-C0001-R0001-DIVERGENCE-BY-FOLD",
                    "repo_relative_path": (RUN_REL / "kpi" / "execution_divergence_by_fold.json").as_posix(),
                    "sha256": sha256_file(kpi / "execution_divergence_by_fold.json"),
                },
            ]
        },
    )
    return root


if __name__ == "__main__":
    unittest.main()
