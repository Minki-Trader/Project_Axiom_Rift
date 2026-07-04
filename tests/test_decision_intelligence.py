import unittest
from pathlib import Path
from types import SimpleNamespace

from axiom_rift.validation.decision_intelligence import (
    debt_scope_summary,
    validate_pre_open_decision,
)


class DummyIssues:
    def __init__(self):
        self.items = []

    def add(self, code, path, detail, severity="error"):
        self.items.append(SimpleNamespace(code=code, path=str(path), detail=detail, severity=severity))


class DecisionIntelligenceTests(unittest.TestCase):
    def test_valid_future_pre_open_decision_passes(self):
        issues = DummyIssues()
        manifest = {
            "schema": "axiom_rift_run_manifest_v2",
            "opened_at_utc": "2026-07-05T01:00:00Z",
            "pre_open_decision": {
                "novelty_score": 4,
                "adjacent_tuning_risk": "low",
                "expected_information_gain": "high",
                "failure_memory_used": "campaigns/C0011_setup_lifecycle_timing_discovery/runs/R0002/gate_report.json",
                "surface_distance": {
                    "label_changed": True,
                    "feature_changed": False,
                    "model_changed": True,
                    "trade_logic_changed": True,
                },
                "mt5_portability": "clear",
                "decision_payoff": "high",
                "reject_if_failure_only_repeats_known_negative_memory": True,
                "true_variant_summary": "new session auction rotation question",
                "adjacent_tuning_rejection_reason": "not a threshold, stop, target, hold, session, or activity nudge",
            },
        }

        validate_pre_open_decision(issues, Path("run_manifest.json"), manifest)

        self.assertEqual([], issues.items)

    def test_missing_pre_open_decision_fails_for_future_v2_run(self):
        issues = DummyIssues()
        manifest = {
            "schema": "axiom_rift_run_manifest_v2",
            "opened_at_utc": "2026-07-05T01:00:00Z",
        }

        validate_pre_open_decision(issues, Path("run_manifest.json"), manifest)

        self.assertTrue(any(item.code == "pre_open_decision_missing" for item in issues.items))

    def test_existing_v1_run_is_not_checked_retroactively(self):
        issues = DummyIssues()
        manifest = {
            "schema": "axiom_rift_run_manifest_v1",
            "opened_at_utc": "2026-07-05T01:00:00Z",
        }

        validate_pre_open_decision(issues, Path("run_manifest.json"), manifest)

        self.assertEqual([], issues.items)

    def test_low_novelty_and_no_surface_change_fail(self):
        issues = DummyIssues()
        manifest = {
            "schema": "axiom_rift_run_manifest_v2",
            "opened_at_utc": "2026-07-05T01:00:00Z",
            "pre_open_decision": {
                "novelty_score": 2,
                "adjacent_tuning_risk": "high",
                "expected_information_gain": "low",
                "failure_memory_used": "x",
                "surface_distance": {
                    "label_changed": False,
                    "feature_changed": False,
                    "model_changed": False,
                    "trade_logic_changed": False,
                },
                "mt5_portability": "non_portable",
                "decision_payoff": "low",
                "reject_if_failure_only_repeats_known_negative_memory": False,
                "true_variant_summary": "bad",
                "adjacent_tuning_rejection_reason": "bad",
            },
        }

        validate_pre_open_decision(issues, Path("run_manifest.json"), manifest)
        codes = {item.code for item in issues.items}

        self.assertIn("pre_open_novelty_score_invalid", codes)
        self.assertIn("pre_open_adjacent_tuning_risk_invalid", codes)
        self.assertIn("pre_open_information_gain_invalid", codes)
        self.assertIn("pre_open_decision_payoff_invalid", codes)
        self.assertIn("pre_open_mt5_portability_invalid", codes)
        self.assertIn("pre_open_repeat_negative_memory_guard_missing", codes)
        self.assertIn("pre_open_surface_distance_missing", codes)

    def test_hash_mismatch_stays_error_but_gets_scope(self):
        issue = SimpleNamespace(
            severity="error",
            code="artifact_lineage_hash_mismatch",
            path="campaigns/C0001/runs/R0001/artifact_lineage.json",
            detail="hash mismatch",
        )

        summary = debt_scope_summary((issue,), active_run_path=None)

        self.assertFalse(summary["global_repo_state_ok"])
        self.assertTrue(summary["next_work_decision_may_continue"])
        self.assertEqual(
            "known_nonblocking_for_next_run_decision",
            summary["debt_classes"][0]["class"],
        )

    def test_hash_missing_gets_same_nonblocking_scope_when_historical(self):
        issue = SimpleNamespace(
            severity="error",
            code="artifact_lineage_hash_missing",
            path="campaigns/SC0001_accumulated_negative_memory_synthesis/runs/SR0001/artifact_lineage.json",
            detail="A-SC0001-SR0001-GATE has no sha256",
        )

        summary = debt_scope_summary((issue,), active_run_path=None)

        self.assertFalse(summary["global_repo_state_ok"])
        self.assertTrue(summary["next_work_decision_may_continue"])
        self.assertEqual(
            "known_nonblocking_for_next_run_decision",
            summary["debt_classes"][0]["class"],
        )


if __name__ == "__main__":
    unittest.main()
