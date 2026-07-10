from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml

from axiom_rift.v2.identity import sha256_payload
from axiom_rift.v2.jobs import scout as scout_job
from axiom_rift.v2.research.evaluation import EvaluationProfile, MetricRule
from axiom_rift.v2.research.scout import (
    NestedScoutResult,
    ScoutSpec,
    ScoutSpecError,
    ScoutTrade,
    _aggregate_nested_metrics,
    _configuration_sha256,
    run_nested_causal_scout,
    validate_hypothesis_v2_payload,
)
from axiom_rift.v2.research.sensitivity import SurfaceRule, build_oat_plan


def _resolved_acceptance() -> dict[str, object]:
    rules = [
        {
            "name": "causal_checks_all_pass",
            "dimension": "integrity",
            "comparison": "equal",
            "stages": ["S"],
            "required_stages": ["S"],
            "expected": True,
            "failure_effect": "repair",
            "tuning_role": "none",
        },
        {
            "name": "evaluable_trade_count",
            "dimension": "inferential_density",
            "comparison": "minimum",
            "stages": ["S"],
            "required_stages": ["S"],
            "pass_at": 1,
            "failure_effect": "reject",
            "tuning_role": "none",
        },
        {
            "name": "unknown_cost_observation_count",
            "dimension": "economics",
            "comparison": "maximum",
            "stages": ["S"],
            "required_stages": ["S"],
            "pass_at": 0,
            "failure_effect": "evidence_gap",
            "tuning_role": "none",
        },
        {
            "name": "net_broker_points",
            "dimension": "economics",
            "comparison": "minimum",
            "stages": ["S"],
            "required_stages": ["S"],
            "pass_at": 0,
            "failure_effect": "reject",
            "tuning_role": "none",
        },
        {
            "name": "positive_net_fold_count",
            "dimension": "stability",
            "comparison": "minimum",
            "stages": ["S"],
            "required_stages": ["S"],
            "pass_at": 1,
            "failure_effect": "reject",
            "tuning_role": "none",
        },
    ]
    identity = {
        "profile_id": "V2SAP9001",
        "resolved_rules": rules,
        "dimension_order": [
            "integrity",
            "inferential_density",
            "activity",
            "economics",
            "risk",
            "stability",
            "execution",
        ],
    }
    return {
        **identity,
        "frozen_before_results": True,
        "profile_sha256": sha256_payload(identity),
    }


def _hypothesis_payload(*, enabled: bool = True) -> dict[str, object]:
    policy: dict[str, object] = (
        {
            "model": {
                "alpha": {
                    "type": "float",
                    "low": 0.1,
                    "baseline": 1.0,
                    "high": 10.0,
                }
            }
        }
        if enabled
        else {}
    )
    initial_variants = 3 if enabled else 1
    local_cells = 3 if enabled else 0
    return {
        "schema": "axiom_rift_v2_hypothesis_v2",
        "status": "preregistered",
        "goal_id": "V2G9001",
        "hypothesis_id": "V2H9001",
        "v1_evidence_inherited": False,
        "executable_programs": {
            "feature_program": {"id": "V2FP0001"},
            "label_program": {"id": "V2LP0001", "horizon_bars_after_entry": 6},
            "model_program": {"id": "V2MP0001", "alpha": 1.0},
            "calibration_program": {"id": "V2CP0001", "quantile": 0.35},
            "selector_program": {"id": "V2SEL0001", "daily_entry_safety_cap": 10},
            "trade_program": {"id": "V2TP0001", "hold_bars": 6},
        },
        "data": {
            "split_set_id": "V2SP0001",
            "scout_anchor_ids": ["V2D002", "V2D005", "V2D008"],
        },
        "falsification": {},
        "acceptance_profile": _resolved_acceptance(),
        "sensitivity_plan": {
            "enabled": enabled,
            "disabled_reason": None if enabled else "no_safe_registered_numeric_knob",
            "data_role": "validation_oos",
            "development_variant_selection_allowed": False,
            "holdout_revealed": False,
            "candidate_frozen": False,
            "policy": policy,
            "selection_feasibility": {
                "causal_checks_required": True,
                "unknown_cost_observation_count_max": 0,
                "evaluable_trade_count_min_per_fold": 1,
            },
            "surface_rule": {
                "metric_name": "net_broker_points",
                "higher_is_better": True,
                "pass_threshold": 1.0,
                "viability_threshold": 0.0,
                "plateau_tolerance": 2.0,
                "fold_consistency_min": 0.67,
            },
        },
        "trial_plan": {
            "frozen_before_results": True,
            "family_id": "V2FAM9001",
            "unique_variant_cap": initial_variants + local_cells,
            "validation_evaluation_cell_cap": initial_variants * 3 + local_cells,
            "local_calibration_new_evaluations_per_outer_fold_max": 1 if enabled else 0,
            "development_paths_per_fold_max": 1,
            "family_trials_before": 0,
            "family_configuration_hashes_before": [],
            "family_history_sha256_before": sha256_payload([]),
            "global_trials_before": 0,
            "global_configuration_hashes_before": [],
            "global_history_sha256_before": sha256_payload([]),
        },
        "routing": {},
        "evidence_budget": {},
    }


class _FakeModel:
    def __init__(self, variant_id: str) -> None:
        self.variant_id = variant_id

    def to_payload(self) -> dict[str, str]:
        return {"variant_id": self.variant_id}


class NestedScoutTests(unittest.TestCase):
    def test_configuration_identity_uses_effective_program_values(self) -> None:
        first = _hypothesis_payload()["executable_programs"]
        second = _hypothesis_payload()["executable_programs"]
        second["model_program"]["alpha"] = 99.0
        parameters = {"model": {"alpha": 10.0}, "calibration": {"quantile": 0.8}}
        self.assertEqual(
            _configuration_sha256(executable_programs=first, parameters=parameters),
            _configuration_sha256(executable_programs=second, parameters=parameters),
        )

    def test_pure_hypothesis_parser_rejects_unresolved_or_unsafe_policy(self) -> None:
        valid = _hypothesis_payload()
        parsed = validate_hypothesis_v2_payload(valid)
        self.assertEqual(len(parsed["sensitivity_plan"].variants), 3)
        self.assertEqual(parsed["surface_rule"].effective_viability_threshold, 0.0)

        unresolved = _hypothesis_payload()
        unresolved["acceptance_profile"].pop("resolved_rules")
        with self.assertRaisesRegex(ScoutSpecError, "resolved metric rules"):
            validate_hypothesis_v2_payload(unresolved)

        vacuous = _hypothesis_payload()
        vacuous_profile = vacuous["acceptance_profile"]
        vacuous_profile["resolved_rules"] = vacuous_profile["resolved_rules"][:-1]
        vacuous_profile["profile_sha256"] = sha256_payload(
            {
                "profile_id": vacuous_profile["profile_id"],
                "resolved_rules": vacuous_profile["resolved_rules"],
                "dimension_order": vacuous_profile["dimension_order"],
            }
        )
        with self.assertRaisesRegex(ScoutSpecError, "mandatory S rules"):
            validate_hypothesis_v2_payload(vacuous)

        wrong_causal_effect = _hypothesis_payload()
        wrong_profile = wrong_causal_effect["acceptance_profile"]
        wrong_profile["resolved_rules"][0]["failure_effect"] = "reject"
        wrong_profile["profile_sha256"] = sha256_payload(
            {
                "profile_id": wrong_profile["profile_id"],
                "resolved_rules": wrong_profile["resolved_rules"],
                "dimension_order": wrong_profile["dimension_order"],
            }
        )
        with self.assertRaisesRegex(ScoutSpecError, "semantics differ"):
            validate_hypothesis_v2_payload(wrong_causal_effect)

        development_selection = _hypothesis_payload()
        development_selection["sensitivity_plan"]["development_variant_selection_allowed"] = True
        with self.assertRaisesRegex(ScoutSpecError, "forbid development variant selection"):
            validate_hypothesis_v2_payload(development_selection)

        disabled = validate_hypothesis_v2_payload(_hypothesis_payload(enabled=False))
        self.assertEqual(len(disabled["sensitivity_plan"].variants), 1)
        self.assertTrue(disabled["sensitivity_plan"].disabled_reason)

    def test_nested_engine_evaluates_extremes_only_on_validation(self) -> None:
        payload = _hypothesis_payload()
        parsed = validate_hypothesis_v2_payload(payload)
        plan = parsed["sensitivity_plan"]
        profile = parsed["evaluation_profile"]
        spec = ScoutSpec(
            goal_id="V2G9001",
            hypothesis_id="V2H9001",
            feature_program_id="V2FP0001",
            feature_contract_path=Path("unused.yaml"),
            label_program_id="V2LP0001",
            model_program_id="V2MP0001",
            calibration_program_id="V2CP0001",
            selector_program_id="V2SEL0001",
            trade_program_id="V2TP0001",
            alpha=1.0,
            residual_quantile=0.35,
            hold_bars=6,
            point_size=0.01,
            maximum_daily_entries=10,
            anchors=("V2D002", "V2D005", "V2D008"),
            acceptance_profile=payload["acceptance_profile"],
            program_registry_path="configs/v2/program_registry.yaml",
            program_registry_sha256="1" * 64,
            program_identities={},
            spec_sha256="2" * 64,
            hypothesis_schema="axiom_rift_v2_hypothesis_v2",
            sensitivity_plan=payload["sensitivity_plan"],
            trial_plan=payload["trial_plan"],
            evaluation_profile=profile,
            oat_plan=plan,
            surface_rule=parsed["surface_rule"],
            selection_feasibility=parsed["selection_feasibility"],
            executable_programs=payload["executable_programs"],
            acceptance_profile_sha256=payload["acceptance_profile"]["profile_sha256"],
            split_set_id=payload["data"]["split_set_id"],
        )
        folds = tuple(
            SimpleNamespace(development_id=fold_id)
            for fold_id in ("V2D002", "V2D005", "V2D008")
        )
        prepared = {
            fold.development_id: SimpleNamespace(window=fold)
            for fold in folds
        }
        calls: list[tuple[str, str, str]] = []

        def fake_variant_model(_prepared, variant, _cache):
            return _FakeModel(variant.variant_id)

        def fake_evaluate(fold, _spec, model, *, role, availability_semantics):
            calls.append((fold.window.development_id, model.variant_id, role))
            value = 10.0
            return (), {
                "fold_id": fold.window.development_id,
                "evaluation_role": role,
                "eligible_day_count": 1,
                "entry_count": 0,
                "evaluable_trade_count": 0,
                "unknown_cost_trade_count": 0,
                "unknown_cost_decision_count": 0,
                "unknown_cost_observation_count": 0,
                "daily_entry_counts": [0],
                "gross_broker_points": 0.0,
                "spread_cost_broker_points": 0.0,
                "net_broker_points": value if role == "validation_oos" else 0.0,
                "profit_factor": None,
                "expectancy_broker_points": None,
                "maximum_drawdown_broker_points": None,
                "metric_availability": {},
            }

        with (
            patch("axiom_rift.v2.research.scout.load_feature_contract", return_value={}),
            patch("axiom_rift.v2.research.scout.load_fold_windows", return_value=folds),
            patch("axiom_rift.v2.research.scout.load_non_allow_gaps", return_value=tuple(range(57))),
            patch("axiom_rift.v2.research.scout.load_fold_bars", return_value=object()),
            patch(
                "axiom_rift.v2.research.scout._prepare_fold",
                side_effect=lambda window, *_args: prepared[window.development_id],
            ),
            patch("axiom_rift.v2.research.scout._variant_model", side_effect=fake_variant_model),
            patch("axiom_rift.v2.research.scout._evaluate_prepared_role", side_effect=fake_evaluate),
            patch(
                "axiom_rift.v2.research.scout._fold_causal_checks",
                side_effect=lambda fold: {
                    "fold_id": fold.window.development_id,
                    "feature_prefix_invariance": True,
                    "full_day_top_k": False,
                },
            ),
        ):
            result = run_nested_causal_scout(
                spec,
                base_frame_path=Path("unused.csv"),
                split_source_path=Path("unused.json"),
                boundary_source_path=Path("unused-boundary.json"),
            )

        validation_calls = [row for row in calls if row[2] == "validation_oos"]
        development_calls = [row for row in calls if row[2] == "development_cv"]
        self.assertEqual(len(validation_calls), len(plan.variants) * 3)
        self.assertEqual(len(development_calls), 3)
        self.assertEqual({row[1] for row in development_calls}, {plan.variant("baseline").variant_id})
        self.assertEqual(result.trial_accounting["development_selected_paths"], 3)
        self.assertFalse(result.trial_accounting["development_variant_selection"])
        self.assertEqual(set(result.selected_variant_hashes), {"V2D002", "V2D005", "V2D008"})

    def test_new_metric_availability_never_treats_no_trade_dd_or_zero_loss_pf_as_pass(self) -> None:
        empty_metrics, _ = _aggregate_nested_metrics(
            (
                {
                    "fold_id": "V2D002",
                    "entry_count": 0,
                    "unknown_cost_trade_count": 0,
                    "unknown_cost_decision_count": 0,
                    "unknown_cost_observation_count": 0,
                    "daily_entry_counts": [0],
                    "gross_broker_points": 0.0,
                    "spread_cost_broker_points": 0.0,
                    "net_broker_points": 0.0,
                },
            ),
            (),
            ({"fold_id": "V2D002", "feature_prefix_invariance": True, "full_day_top_k": False},),
        )
        self.assertIsNone(empty_metrics["maximum_drawdown_broker_points"])
        self.assertEqual(
            empty_metrics["metric_availability"]["maximum_drawdown_broker_points"]["state"],
            "not_evaluable",
        )

        winner = ScoutTrade(
            fold_id="V2D002",
            signal_time="2025-01-01 00:00:00",
            entry_time="2025-01-01 00:05:00",
            exit_time="2025-01-01 00:35:00",
            direction=1,
            score=1.0,
            residual_band=0.1,
            causal_cost_edge=0.01,
            gross_broker_points=11.0,
            spread_cost_broker_points=1.0,
            net_broker_points=10.0,
            evaluable_after_cost=True,
            exclusion_reason=None,
            market_day="2024-12-31",
            market_hour=17,
        )
        winner_metrics, _ = _aggregate_nested_metrics(
            (
                {
                    "fold_id": "V2D002",
                    "entry_count": 1,
                    "unknown_cost_trade_count": 0,
                    "unknown_cost_decision_count": 0,
                    "unknown_cost_observation_count": 0,
                    "daily_entry_counts": [1],
                    "gross_broker_points": 11.0,
                    "spread_cost_broker_points": 1.0,
                    "net_broker_points": 10.0,
                },
            ),
            (winner,),
            ({"fold_id": "V2D002", "feature_prefix_invariance": True, "full_day_top_k": False},),
        )
        self.assertIsNone(winner_metrics["profit_factor"])
        self.assertEqual(
            winner_metrics["metric_availability"]["profit_factor"]["state"],
            "censored",
        )

        partial_cost = dict(winner_metrics["per_fold"][0])
        partial_cost["unknown_cost_decision_count"] = 1
        partial_metrics, _ = _aggregate_nested_metrics(
            (partial_cost,),
            (winner,),
            ({"fold_id": "V2D002", "feature_prefix_invariance": True, "full_day_top_k": False},),
        )
        self.assertEqual(partial_metrics["unknown_cost_observation_count"], 1)
        self.assertEqual(
            partial_metrics["metric_availability"]["net_broker_points"]["state"],
            "not_evaluable",
        )

    def test_nested_job_receipt_carries_selection_and_trial_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_path = root / "data/base.csv"
            split_path = root / "data/splits.json"
            boundary_path = root / "data/boundaries.json"
            for path, content in (
                (data_path, "time,open,high,low,close,tick_volume,spread\n"),
                (split_path, "{}\n"),
                (boundary_path, "{}\n"),
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="ascii")

            def file_sha(path: Path) -> str:
                return hashlib.sha256(path.read_bytes()).hexdigest()

            config_dir = root / "configs/v2"
            config_dir.mkdir(parents=True)
            (config_dir / "data.yaml").write_text(
                yaml.safe_dump(
                    {
                        "processed": {"path": "data/base.csv", "sha256": file_sha(data_path)},
                        "boundary_source": {
                            "path": "data/boundaries.json",
                            "sha256": file_sha(boundary_path),
                        },
                    },
                    sort_keys=False,
                ),
                encoding="ascii",
            )
            (config_dir / "splits.yaml").write_text(
                yaml.safe_dump(
                    {"source": {"path": "data/splits.json", "sha256": file_sha(split_path)}},
                    sort_keys=False,
                ),
                encoding="ascii",
            )
            hypothesis_path = root / "campaigns/v2/V2G9001/hypotheses/V2H9001.yaml"
            hypothesis_path.parent.mkdir(parents=True)
            hypothesis_path.write_text("schema: fixture\n", encoding="ascii")
            output_dir = root / "campaigns/v2/V2G9001/evidence/V2S9001"
            fake_spec = SimpleNamespace(
                goal_id="V2G9001",
                hypothesis_id="V2H9001",
                hypothesis_schema="axiom_rift_v2_hypothesis_v2",
                spec_sha256="1" * 64,
                program_registry_path="configs/v2/program_registry.yaml",
                program_registry_sha256="2" * 64,
                program_identities={},
            )
            fake_result = NestedScoutResult(
                outcome="scout_rejected",
                gate_passed=False,
                metrics={"schema": "fixture"},
                causal_checks={"all_pass": True},
                models=(),
                trades=(),
                nested_selection={
                    "schema": "fixture_selection",
                    "development_variant_selection": False,
                },
                trial_accounting={
                    "schema": "fixture_trials",
                    "configuration_trials": 3,
                    "development_selected_paths": 3,
                },
                selection_rule_sha256="3" * 64,
                selected_variant_hashes={"V2D002": "4" * 64},
                selected_configuration_hashes={"V2D002": "6" * 64},
                selected_model_bundle_sha256s={"V2D002": "7" * 64},
                selected_path_hashes={"V2D002": "8" * 64},
                result_sha256="5" * 64,
            )
            with (
                patch.object(scout_job, "PROJECT_ROOT", root),
                patch.object(scout_job, "load_scout_spec", return_value=fake_spec),
                patch.object(scout_job, "run_nested_causal_scout", return_value=fake_result),
            ):
                receipt = scout_job.run_scout_job(
                    "V2G9001",
                    "V2H9001",
                    "V2S9001",
                    hypothesis_path,
                    output_dir,
                )
        self.assertEqual(receipt["schema"], "axiom_rift_v2_nested_scout_receipt_v1")
        self.assertEqual(receipt["selection_rule_sha256"], "3" * 64)
        self.assertFalse(receipt["development_variant_selection"])
        self.assertIn("nested_selection", receipt["artifacts"])
        self.assertIn("trial_accounting", receipt["artifacts"])


if __name__ == "__main__":
    unittest.main()
