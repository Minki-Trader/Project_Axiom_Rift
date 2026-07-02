import unittest
from pathlib import Path

import yaml

from axiom_rift.paths import PROJECT_ROOT


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="ascii") as handle:
        return yaml.safe_load(handle)


class GoalOperationPolicyTest(unittest.TestCase):
    def test_goal_policy_preserves_top_level_numeric_target(self) -> None:
        policy = load_yaml(PROJECT_ROOT / "contracts" / "goal_operation_policy.yaml")

        target = policy["top_level_goal"]["target_entry_events_per_active_day"]
        self.assertEqual(5, target["min"])
        self.assertEqual(10, target["max"])
        self.assertTrue(policy["failure_asset_policy"]["enabled"])
        self.assertTrue(policy["failure_asset_policy"]["failure_is_asset"])
        self.assertFalse(policy["failure_asset_policy"]["broken_code_is_failure_asset"])
        self.assertTrue(policy["broken_code_policy"]["enabled"])
        self.assertFalse(policy["broken_code_policy"]["record_and_quit_allowed"])
        self.assertFalse(policy["broken_code_policy"]["broken_code_is_hypothesis_evidence"])
        self.assertFalse(policy["broken_code_policy"]["broken_code_may_close_run"])
        self.assertFalse(policy["broken_code_policy"]["missing_kpi_from_broken_code_counts_as_evidence"])
        self.assertFalse(policy["anti_drift_rules"]["proxy_only_scout_allowed"])
        self.assertFalse(policy["anti_drift_rules"]["weak_proxy_may_skip_mt5"])
        self.assertFalse(policy["anti_drift_rules"]["aggregate_mt5_may_close_run"])
        self.assertTrue(policy["anti_drift_rules"]["fold_isolated_closeout_required"])
        self.assertFalse(policy["anti_drift_rules"]["broken_code_record_and_quit_allowed"])
        self.assertFalse(policy["anti_drift_rules"]["run_closeout_without_main_push_allowed"])
        self.assertFalse(policy["claim_boundary"]["live_ready"])

    def test_goal_policy_preserves_discovery_freedom_and_sizing_order(self) -> None:
        policy = load_yaml(PROJECT_ROOT / "contracts" / "goal_operation_policy.yaml")

        discovery = policy["discovery_freedom_policy"]
        self.assertTrue(discovery["preserve_unrestricted_discovery_until_evidence_freeze"])
        for variable in ("feature_count", "model_family", "ensemble_structure", "score_surfaces"):
            self.assertIn(variable, discovery["exploration_variables"])
        self.assertIn("active_contract_or_decision_record", discovery["freeze_requires"])

        sizing = policy["sizing_policy"]
        self.assertEqual("fixed_lot", sizing["early_discovery_default"])
        self.assertTrue(sizing["equity_percent_sizing"]["allowed_later"])
        self.assertFalse(sizing["equity_percent_sizing"]["exact_rule_frozen"])

    def test_run_closeout_requires_main_push(self) -> None:
        policy = load_yaml(PROJECT_ROOT / "contracts" / "goal_operation_policy.yaml")

        git_policy = policy["run_closeout_git_policy"]
        self.assertTrue(git_policy["enabled"])
        self.assertEqual("every_run_closeout", git_policy["applies_to"])
        self.assertEqual("main", git_policy["branch"])
        self.assertEqual("origin", git_policy["remote"])
        self.assertTrue(git_policy["run_closeout_done_requires_push"])
        self.assertIn("push_main_to_origin", git_policy["required_after_validation"])
        self.assertIn("force_push", git_policy["must_not"])
        self.assertIn("stage_unrelated_files", git_policy["must_not"])

    def test_goal_skill_is_wired_and_has_no_todos(self) -> None:
        skill_path = PROJECT_ROOT / ".agents" / "skills" / "axiom-goal-campaign-operator" / "SKILL.md"
        skill_text = skill_path.read_text(encoding="ascii")

        self.assertNotIn("[TODO", skill_text)
        for required_text in (
            "contracts/goal_operation_policy.yaml",
            "5 to 10",
            "fold-isolated",
            "Failures are assets",
            "Broken code is not a failure asset",
            "equity-percent sizing is deferred",
            "push `main` to `origin`",
            "axiom-mt5-validation-guardrails",
        ):
            self.assertIn(required_text, skill_text)

        reference_path = (
            PROJECT_ROOT
            / ".agents"
            / "skills"
            / "axiom-goal-campaign-operator"
            / "references"
            / "operating_flow.md"
        )
        reference_text = reference_path.read_text(encoding="ascii")
        self.assertIn("short goal input", reference_text)
        self.assertIn("Failure is not waste", reference_text)
        self.assertIn("Broken Code Is Not Evidence", reference_text)
        self.assertIn("Sizing And Discovery Freedom", reference_text)
        self.assertIn("Run Closeout Git Sync", reference_text)
        self.assertIn("Closeout Matrix", reference_text)

        agents_text = (PROJECT_ROOT / "AGENTS.md").read_text(encoding="ascii")
        self.assertIn("axiom-goal-campaign-operator", agents_text)


if __name__ == "__main__":
    unittest.main()
