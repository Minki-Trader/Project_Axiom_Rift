from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import yaml

from axiom_rift.v2.identity import ObjectStore, sha256_payload
from axiom_rift.v2.git_closeout import GitCheckpointVerification
from axiom_rift.v2.ledger import HashChainLedger
from axiom_rift.v2.operations import OperationStateError, V2OperationWriter
from axiom_rift.v2.research.autonomy import HypothesisBatch, NumericKnob
from axiom_rift.v2.research.evaluation import (
    EvaluationProfile,
    FailureEffect,
    MetricRule,
    Stage,
    interpret_kpis,
)
from axiom_rift.v2.research.scientific_scout import (
    SCIENTIFIC_SELECTION_RULE_SHA256,
    scientific_kpi_observations,
)
from axiom_rift.v2.research.scout import _configuration_sha256
from axiom_rift.v2.research.sensitivity import build_oat_plan
from axiom_rift.v2.state import ControlStateError, ControlStore
from axiom_rift.v2.state.transitions import TransitionError, make_next_action


def v21_state() -> dict:
    return {
        "schema": "axiom_rift_v2_control_state_v2",
        "revision": 1,
        "status": "active",
        "encoding": "ascii_only",
        "active_truth": "v2",
        "root_mission": {
            "mission_id": "AXIOM_ROOT_0001",
            "contract_path": "contracts/v2/project_contract.yaml",
            "contract_sha256": "1" * 64,
            "status": "ready",
            "terminal_outcome": None,
            "user_goal_received": False,
        },
        "mission_budget": {
            "frozen": False,
            "limits": {
                "hypothesis_batches": 12,
                "scout_jobs": 12,
                "confirmation_jobs": 4,
                "promotion_candidates": 2,
                "full_nine_fold_mt5_batches": 2,
                "holdout_reveals": 1,
            },
            "remaining": {
                "hypothesis_batches": 12,
                "scout_jobs": 12,
                "confirmation_jobs": 4,
                "promotion_candidates": 2,
                "full_nine_fold_mt5_batches": 2,
                "holdout_reveals": 1,
            },
        },
        "slice_budget": None,
        "namespace": {
            "next_goal": 1,
            "next_hypothesis": 1,
            "next_scout": 1,
            "next_confirmation": 1,
            "next_promotion": 1,
            "next_materialization": 1,
        },
        "cursor": {
            "active_goal_id": None,
            "active_goal_object_id": None,
            "goal_status": "closed",
            "active_hypothesis_id": None,
            "stage": "idle",
            "stage_id": None,
            "stage_status": "idle",
            "terminal_outcome": None,
            "next_action": make_next_action("open_goal", goal_id="V2G0001", summary="open first goal"),
        },
        "reentry": {
            "active_job": None,
            "current_object_ids": [],
            "current_artifact_hashes": {},
            "completed_receipt_ids": [],
            "completed_evidence_ids": [],
            "validation_batches_remaining": 1,
            "repair_batches_remaining": 1,
            "blocker": None,
        },
        "claim": {
            "subject_kind": "none",
            "subject_id": None,
            "current_level": "none",
            "claim_ceiling": "none",
            "identity_bundle_object_id": None,
            "basis_receipt_ids": [],
            "blocked_by": [],
        },
        "holdout": {"reveal_count": 0, "max_reveals": 1, "permit": None},
        "history": {"recent_closed_goals": []},
        "ledger_heads": {},
        "applied_idempotency_keys": [],
    }


def v1_activated_state(activation_object_id: str) -> dict:
    return {
        "schema": "axiom_rift_v2_control_state_v1",
        "revision": 1,
        "status": "active",
        "active_truth": "v2",
        "goal_id": "V2G0001",
        "namespace": {
            "next_goal": 2,
            "next_hypothesis": 2,
            "next_scout": 2,
            "next_confirmation": 1,
            "next_promotion": 1,
            "next_materialization": 1,
        },
        "cursor": {
            "active_goal_id": "V2G0001",
            "active_hypothesis_id": "V2H0001",
            "stage": "S",
            "stage_id": "V2S0001",
            "stage_status": "completed",
            "terminal_outcome": None,
            "exact_next_action": "open_V2G0002",
        },
        "reentry": {"active_job": None, "git_closeout": {"validated_commit": "a" * 40}},
        "claim": {
            "current_level": "diagnostic_observation",
            "claim_ceiling": "diagnostic_observation",
            "basis_receipt_ids": ["V2E000006"],
        },
        "ledger_heads": {},
        "applied_idempotency_keys": [],
        "bootstrap_goal_outcome": "activated",
        "activation": {
            "activation_evidence_id": "V2E000008",
            "activation_object_id": activation_object_id,
            "candidate_validation_receipt_id": "V2VR000005",
        },
    }


def build_writer(root: Path, state: dict) -> V2OperationWriter:
    control = root / "control_state.yaml"
    control.write_text(yaml.safe_dump(state, sort_keys=False), encoding="ascii")
    return V2OperationWriter(
        object_dir=root / "objects",
        control_state=control,
        hypothesis_ledger=root / "hypothesis.jsonl",
        evidence_ledger=root / "evidence.jsonl",
        material_ledger=root / "material.jsonl",
        validation_receipt_ledger=root / "validation.jsonl",
        content_checkpoint_probe=lambda commit, _paths: GitCheckpointVerification(
            True, "test_content_verified", commit, commit, commit
        ),
        metadata_checkpoint_probe=lambda sync: GitCheckpointVerification(
            True,
            "test_metadata_verified",
            "b" * 40,
            "b" * 40,
            sync.get("validated_content_commit") if isinstance(sync, dict) else None,
        ),
    )


def v22_hypothesis_payload(goal_id: str, hypothesis_id: str) -> dict:
    rules = [
        {
            "name": "causal_checks_all_pass",
            "dimension": "integrity",
            "comparison": "equal",
            "stages": ["S"],
            "required_stages": ["S"],
            "failure_effect": "repair",
            "tuning_role": "none",
            "expected": True,
        },
        {
            "name": "evaluable_trade_count",
            "dimension": "inferential_density",
            "comparison": "minimum",
            "stages": ["S"],
            "required_stages": ["S"],
            "failure_effect": "reject",
            "tuning_role": "sensitivity_only",
            "pass_at": 1.0,
        },
        {
            "name": "unknown_cost_observation_count",
            "dimension": "integrity",
            "comparison": "maximum",
            "stages": ["S"],
            "required_stages": ["S"],
            "failure_effect": "evidence_gap",
            "tuning_role": "none",
            "pass_at": 0.0,
        },
        {
            "name": "net_broker_points",
            "dimension": "economics",
            "comparison": "minimum",
            "stages": ["S"],
            "required_stages": ["S"],
            "failure_effect": "reject",
            "tuning_role": "sensitivity_only",
            "pass_at": 0.0,
        },
        {
            "name": "positive_net_fold_count",
            "dimension": "stability",
            "comparison": "minimum",
            "stages": ["S"],
            "required_stages": ["S"],
            "failure_effect": "reject",
            "tuning_role": "none",
            "pass_at": 1.0,
        },
    ]
    dimensions = [
        "integrity",
        "inferential_density",
        "activity",
        "economics",
        "risk",
        "stability",
        "execution",
        "portfolio_fit",
    ]
    profile_hash = sha256_payload(
        {
            "profile_id": "V2SAP0001",
            "resolved_rules": rules,
            "dimension_order": dimensions,
        }
    )
    payload = {
        "schema": "axiom_rift_v2_hypothesis_v2",
        "status": "preregistered",
        "goal_id": goal_id,
        "hypothesis_id": hypothesis_id,
        "scientific_origin": "v2_current",
        "scientific_epoch_id": "V2EPOCH0001",
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
        "falsification": {
            "scientific_reject_conditions": ["a required S hard dimension fails"],
            "repair_conditions": ["a required metric is missing or invalid"],
            "scale_miss_conditions": ["the registered surface ends at a boundary trend"],
        },
        "acceptance_profile": {
            "profile_id": "V2SAP0001",
            "frozen_before_results": True,
            "resolved_rules": rules,
            "dimension_order": dimensions,
            "profile_sha256": profile_hash,
        },
        "sensitivity_plan": {
            "enabled": True,
            "data_role": "validation_oos",
            "development_variant_selection_allowed": False,
            "holdout_revealed": False,
            "candidate_frozen": False,
            "selection_feasibility": {
                "causal_checks_required": True,
                "unknown_cost_observation_count_max": 0,
                "evaluable_trade_count_min_per_fold": 1,
            },
            "policy": {
                "model": {
                    "alpha": {
                        "type": "float",
                        "low": 0.1,
                        "baseline": 1.0,
                        "high": 10.0,
                    }
                }
            },
            "surface_rule": {
                "metric_name": "net_broker_points",
                "higher_is_better": True,
                "viability_threshold": -10.0,
                "pass_threshold": 0.0,
                "plateau_tolerance": 10.0,
                "fold_consistency_min": 0.67,
            },
        },
        "trial_plan": {
            "frozen_before_results": True,
            "family_id": "v2fam_test",
            "unique_variant_cap": 6,
            "validation_evaluation_cell_cap": 12,
            "local_calibration_new_evaluations_per_outer_fold_max": 1,
            "development_paths_per_fold_max": 1,
            "family_trials_before": 0,
            "family_configuration_hashes_before": [],
            "family_history_sha256_before": sha256_payload([]),
            "global_trials_before": 0,
            "global_configuration_hashes_before": [],
            "global_history_sha256_before": sha256_payload([]),
        },
        "routing": {
            "broken_execution": "repair_same_scope",
            "scientific_reject": "record_negative_memory_then_rotate",
            "scientific_survive": "advance_by_stage_gate",
            "holdout_informed_redesign": "forbidden",
        },
        "evidence_budget": {
            "scout_jobs_max": 1,
            "configuration_trials_max": 6,
            "validation_evaluation_cells_max": 12,
            "development_paths_per_fold_max": 1,
            "mt5_runs_max": 0,
            "holdout_reveals_max": 0,
            "job_timeout_seconds": 1800,
        },
    }
    plan = build_oat_plan(
        hypothesis_id=hypothesis_id,
        stage="S",
        baseline_parameters={"model": {"alpha": 1.0}, "calibration": {"quantile": 0.35}},
        nested_policy=payload["sensitivity_plan"]["policy"],
    )
    configuration_hashes = sorted(
        {
            _configuration_sha256(
                executable_programs=payload["executable_programs"],
                parameters=variant.parameters,
            )
            for variant in plan.variants
        }
    )
    payload["autonomy_batch"] = HypothesisBatch(
        hypothesis_id=hypothesis_id,
        family_id=payload["trial_plan"]["family_id"],
        hypothesis_type="structural_batch",
        dominant_axis="axis_model",
        scientific_epoch_id="V2EPOCH0001",
        scout_mode="s_breadth",
        bundle_roles={
            f"configuration_{index}": value
            for index, value in enumerate(configuration_hashes, start=1)
        },
        semantic_signature_sha256=sha256_payload(
            {
                "family_id": payload["trial_plan"]["family_id"],
                "dominant_axis": "axis_model",
                "configuration_hashes": configuration_hashes,
            }
        ),
        numeric_knobs=(NumericKnob("model.alpha", 0.1, 1.0, 10.0),),
        local_calibration_rounds=1,
    ).to_payload()
    return payload


class V21GenericLifecycleTests(unittest.TestCase):
    def test_rectifiable_falsifier_gap_requires_identified_cost_and_causality(self) -> None:
        receipt = {
            "outcome": "evidence_gap",
            "metrics_summary": {"unknown_cost_observation_count": 0},
            "causal_summary": {"all_role_checks_passed": True},
        }
        selections = [{"falsifier_triggered": True}]
        self.assertTrue(
            V2OperationWriter._rectifiable_scientific_falsifier_gap(
                receipt, selections
            )
        )
        receipt["metrics_summary"]["unknown_cost_observation_count"] = 1
        self.assertFalse(
            V2OperationWriter._rectifiable_scientific_falsifier_gap(
                receipt, selections
            )
        )
        receipt["metrics_summary"]["unknown_cost_observation_count"] = 0
        receipt["causal_summary"]["all_role_checks_passed"] = False
        self.assertFalse(
            V2OperationWriter._rectifiable_scientific_falsifier_gap(
                receipt, selections
            )
        )

    def test_nested_receipt_reconciles_family_global_and_selected_path_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = build_writer(Path(temp_dir), v21_state())
            configuration_hash = "a" * 64
            receipt = {
                "schema": "axiom_rift_v2_nested_scout_receipt_v1",
                "stage": "S",
                "nested_selection": True,
                "selection_source_data_role": "validation_oos",
                "development_paths_per_fold": 1,
                "development_variant_selection": False,
                "selection_rule_sha256": "b" * 64,
                "result_sha256": "c" * 64,
                "selected_variant_hashes": {"V2D002": "d" * 64},
                "selected_configuration_hashes": {"V2D002": configuration_hash},
                "selected_model_bundle_sha256s": {"V2D002": "e" * 64},
                "selected_path_hashes": {"V2D002": "f" * 64},
                "artifacts": {
                    name: {"path": f"artifacts/{name}"}
                    for name in (
                        "metrics",
                        "models",
                        "trades",
                        "causal_checks",
                        "nested_selection",
                        "trial_accounting",
                    )
                },
                "trial_accounting": {
                    "family_id": "v2fam_test",
                    "configuration_hashes": [configuration_hash],
                    "job_unique_configuration_count": 1,
                    "new_family_configuration_trials": 1,
                    "family_trials_before": 0,
                    "family_configuration_hashes_before": [],
                    "family_history_sha256_before": sha256_payload([]),
                    "family_configuration_hashes_after": [configuration_hash],
                    "family_history_sha256_after": sha256_payload([configuration_hash]),
                    "family_trials_cumulative": 1,
                    "global_trials_before": 0,
                    "global_configuration_hashes_before": [],
                    "global_history_sha256_before": sha256_payload([]),
                    "global_configuration_hashes_after": [configuration_hash],
                    "global_history_sha256_after": sha256_payload([configuration_hash]),
                    "global_trials_cumulative": 1,
                    "development_selected_paths": 1,
                    "development_variant_selection": False,
                },
            }
            writer._validate_nested_scout_receipt(receipt)
            receipt["trial_accounting"]["global_trials_cumulative"] = 0
            with self.assertRaises(OperationStateError):
                writer._validate_nested_scout_receipt(receipt)

    def test_scientific_receipt_accepts_valid_empty_path_rejection_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = build_writer(Path(temp_dir), v21_state())
            roles = (
                "continuation_low",
                "continuation_base",
                "continuation_high",
                "failed_break_reversal",
                "compression_ablation",
            )
            bundle_hashes = {
                role: sha256_payload({"scientific_bundle_role": role})
                for role in roles
            }
            release_hashes = {
                role: sha256_payload({"release_configuration": role})
                for role in roles
            }
            configuration_hashes = sorted(bundle_hashes.values())
            program_kinds = (
                "feature",
                "label",
                "model",
                "calibration",
                "selector",
                "trade",
                "sizing",
                "portfolio_risk",
            )
            programs = {
                role: {
                    kind: {"id": f"{role}_{kind}", "kind": kind}
                    for kind in program_kinds
                }
                for role in roles
            }
            selection_rule_sha256 = SCIENTIFIC_SELECTION_RULE_SHA256
            receipt = {
                "schema": "axiom_rift_v2_scientific_scout_receipt_v1",
                "stage": "S",
                "scientific_programs": True,
                "nested_selection": True,
                "selection_source_data_role": "validation_oos",
                "development_paths_per_fold": 1,
                "development_variant_selection": False,
                "claim_ceiling": "diagnostic_observation",
                "economics_claim_allowed": False,
                "mt5_executed": False,
                "isolated_nine_fold_executed": False,
                "scout_anchor_ids": ["V2D002", "V2D005", "V2D008"],
                "selection_rule_sha256": selection_rule_sha256,
                "result_sha256": "1" * 64,
                "spec_sha256": "2" * 64,
                "spec_payload_sha256": "3" * 64,
                "program_registry_path": "configs/v2/scientific/program_registry.yaml",
                "program_registry_sha256": "4" * 64,
                "dataset_sha256": "5" * 64,
                "split_source_sha256": "6" * 64,
                "boundary_source_sha256": "7" * 64,
                "bundle_role_hashes": bundle_hashes,
                "release_configuration_hashes": release_hashes,
                "runtime_sha256": "8" * 64,
                "runtime_executable_sha256": "9" * 64,
                "programs": programs,
                "selected_roles": {},
                "selected_variant_hashes": {},
                "selected_configuration_hashes": {},
                "selected_model_bundle_sha256s": {},
                "selected_path_hashes": {},
                "artifacts": {},
                "metrics_summary": {
                    "unknown_cost_observation_count": 0,
                    "validation_unknown_cost_observation_count": 0,
                    "development_unknown_cost_observation_count": 0,
                },
                "causal_summary": {"all_role_checks_passed": True},
                "outcome": "scientific_reject",
                "gate_passed": False,
                "trial_accounting": {
                    "family_id": "compression_release_event_v1",
                    "configuration_trials": 5,
                    "job_unique_configuration_count": 5,
                    "new_family_configuration_trials": 5,
                    "validation_evaluation_cells": 15,
                    "local_calibration_trials": 0,
                    "inner_selection_events": 3,
                    "development_selected_paths": 0,
                    "development_variant_selection": False,
                    "family_trials_before": 0,
                    "family_configuration_hashes_before": [],
                    "family_history_sha256_before": sha256_payload([]),
                    "family_configuration_hashes_after": configuration_hashes,
                    "family_history_sha256_after": sha256_payload(configuration_hashes),
                    "family_trials_cumulative": 5,
                    "global_trials_before": 0,
                    "global_configuration_hashes_before": [],
                    "global_history_sha256_before": sha256_payload([]),
                    "global_configuration_hashes_after": configuration_hashes,
                    "global_history_sha256_after": sha256_payload(configuration_hashes),
                    "global_trials_cumulative": 5,
                    "configuration_hashes": configuration_hashes,
                    "holdout_reveals": 0,
                    "trial_accounting_complete": True,
                },
            }
            selection_payload = {
                "schema": "axiom_rift_v2_scientific_nested_selection_v1",
                "validation_evaluations": [],
                "selections": [],
                "development_evaluations": [],
                "selection_source_data_role": "validation_oos",
                "development_variant_selection": False,
                "selection_rule_sha256": selection_rule_sha256,
            }
            artifact_payloads = {
                "metrics": receipt["metrics_summary"],
                "models": {
                    "schema": "axiom_rift_v2_scientific_program_bundle_selections_v1",
                    "program_identities": programs,
                    "bundle_role_hashes": bundle_hashes,
                    "release_configuration_hashes": release_hashes,
                    "runtime_sha256": receipt["runtime_sha256"],
                    "runtime_executable_sha256": receipt[
                        "runtime_executable_sha256"
                    ],
                    "selections": [],
                    "claim_ceiling": "diagnostic_observation",
                },
                "causal_checks": receipt["causal_summary"],
                "nested_selection": selection_payload,
                "trial_accounting": receipt["trial_accounting"],
            }
            artifact_dir = Path(temp_dir) / "campaigns/v2/fixture"
            artifact_dir.mkdir(parents=True)
            for name, payload in artifact_payloads.items():
                path = artifact_dir / f"{name}.json"
                raw = (
                    json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)
                    + "\n"
                ).encode("ascii")
                path.write_bytes(raw)
                receipt["artifacts"][name] = {
                    "path": path.relative_to(Path(temp_dir)).as_posix(),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            trades_path = artifact_dir / "trades.csv"
            trades_raw = b"fold_id\n"
            trades_path.write_bytes(trades_raw)
            receipt["artifacts"]["trades"] = {
                "path": trades_path.relative_to(Path(temp_dir)).as_posix(),
                "sha256": hashlib.sha256(trades_raw).hexdigest(),
            }
            receipt["result_sha256"] = sha256_payload(
                {
                    "outcome": receipt["outcome"],
                    "gate_passed": receipt["gate_passed"],
                    "metrics": receipt["metrics_summary"],
                    "causal_checks": receipt["causal_summary"],
                    "validation_evaluations": [],
                    "selections": [],
                    "development_evaluations": [],
                    "selected_path_hashes": {},
                    "trial_accounting": receipt["trial_accounting"],
                    "claim_ceiling": "diagnostic_observation",
                    "mt5_executed": False,
                    "economics_claim_allowed": False,
                }
            )
            writer._validate_scientific_scout_receipt(receipt)
            receipt_object_id = writer.objects.put("evidence_receipt", receipt)
            writer.evidence.append(
                "V2E000001",
                "scientific_scout_completed",
                {"receipt_object_id": receipt_object_id},
                "2026-01-01T00:00:00Z",
            )
            self.assertEqual(
                receipt,
                writer.validate_recorded_scientific_scout_receipt(
                    receipt_object_id
                ),
            )
            future_hash = sha256_payload({"future_configuration": 1})
            future_receipt_object_id = writer.objects.put(
                "evidence_receipt",
                {
                    "trial_accounting": {
                        "family_id": "compression_release_event_v1",
                        "configuration_hashes": [future_hash],
                    }
                },
            )
            writer.evidence.append(
                "V2E000002",
                "scientific_scout_completed",
                {"receipt_object_id": future_receipt_object_id},
                "2026-01-02T00:00:00Z",
            )
            self.assertEqual(
                receipt,
                writer.validate_recorded_scientific_scout_receipt(
                    receipt_object_id
                ),
            )
            receipt["outcome"] = "route_to_R"
            receipt["gate_passed"] = True
            with self.assertRaises(OperationStateError):
                writer._validate_scientific_scout_receipt(receipt)

    def test_causal_shadow_kpi_replay_routes_gap_and_blocks_forged_R(self) -> None:
        profile = EvaluationProfile(
            profile_id="V2SAP_CAUSAL_TEST",
            rules=(
                MetricRule.equal(
                    "causal_checks_all_pass",
                    "integrity",
                    stages=(Stage.S,),
                    expected=True,
                    failure_effect=FailureEffect.REPAIR,
                ),
                MetricRule.minimum(
                    "evaluable_trade_count",
                    "inferential_density",
                    stages=(Stage.S,),
                    pass_at=60,
                ),
                MetricRule.maximum(
                    "unknown_cost_observation_count",
                    "integrity",
                    stages=(Stage.S,),
                    pass_at=0,
                    failure_effect=FailureEffect.EVIDENCE_GAP,
                ),
                MetricRule.minimum(
                    "net_broker_points",
                    "economics",
                    stages=(Stage.S,),
                    pass_at=0.01,
                ),
                MetricRule.minimum(
                    "positive_net_fold_count",
                    "stability",
                    stages=(Stage.S,),
                    pass_at=2,
                ),
                MetricRule.minimum(
                    "shadow_evaluable_trade_count",
                    "inferential_density",
                    stages=(Stage.S,),
                    pass_at=60,
                    failure_effect=FailureEffect.EVIDENCE_GAP,
                ),
                MetricRule.minimum(
                    "shadow_net_broker_points",
                    "economics",
                    stages=(Stage.S,),
                    pass_at=0.01,
                ),
                MetricRule.minimum(
                    "shadow_positive_net_fold_count",
                    "stability",
                    stages=(Stage.S,),
                    pass_at=2,
                ),
            ),
        )
        metrics = {
            "evaluable_trade_count": 60,
            "unknown_cost_observation_count": 0,
            "net_broker_points": 10.0,
            "positive_net_fold_count": 3,
            "shadow_evaluable_trade_count": 0,
            "shadow_net_broker_points": 10.0,
            "shadow_positive_net_fold_count": 3,
        }
        observations = scientific_kpi_observations(
            metrics,
            causal_checks_passed=True,
            trade_implementation_key="fixed_6bar_causal_spread_floor_v1",
        )
        evaluation = interpret_kpis("S", observations, profile).to_payload()
        self.assertEqual("evidence_gap", evaluation["route"])
        metrics["kpi_evaluation"] = evaluation
        causal = {
            "all_role_checks_passed": True,
            "kpi_route": "evidence_gap",
            "hard_profile_passed": False,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = build_writer(Path(temp_dir), v21_state())
            self.assertEqual(
                "evidence_gap",
                writer._replay_scientific_kpi_evaluation(
                    metrics=metrics,
                    causal=causal,
                    trade_implementation_key=(
                        "fixed_6bar_causal_spread_floor_v1"
                    ),
                    evaluation_profile=profile,
                ),
            )
            forged_metrics = deepcopy(metrics)
            forged_metrics["kpi_evaluation"]["route"] = "route_to_R"
            forged_causal = {
                **causal,
                "kpi_route": "route_to_R",
                "hard_profile_passed": True,
            }
            with self.assertRaisesRegex(
                OperationStateError,
                "differs from preregistration",
            ):
                writer._replay_scientific_kpi_evaluation(
                    metrics=forged_metrics,
                    causal=forged_causal,
                    trade_implementation_key=(
                        "fixed_6bar_causal_spread_floor_v1"
                    ),
                    evaluation_profile=profile,
                )
            passing_metrics = {
                **metrics,
                "shadow_evaluable_trade_count": 60,
            }
            passing_metrics["kpi_evaluation"] = interpret_kpis(
                "S",
                scientific_kpi_observations(
                    passing_metrics,
                    causal_checks_passed=True,
                    trade_implementation_key=(
                        "fixed_6bar_causal_spread_floor_v1"
                    ),
                ),
                profile,
            ).to_payload()
            passing_causal = {
                "all_role_checks_passed": True,
                "kpi_route": "route_to_R",
                "hard_profile_passed": True,
            }
            self.assertEqual(
                "route_to_R",
                writer._replay_scientific_kpi_evaluation(
                    metrics=passing_metrics,
                    causal=passing_causal,
                    trade_implementation_key=(
                        "fixed_6bar_causal_spread_floor_v1"
                    ),
                    evaluation_profile=profile,
                ),
            )
            rejecting_metrics = {
                **passing_metrics,
                "net_broker_points": -1.0,
                "positive_net_fold_count": 0,
                "shadow_net_broker_points": -1.0,
                "shadow_positive_net_fold_count": 0,
            }
            rejecting_metrics["kpi_evaluation"] = interpret_kpis(
                "S",
                scientific_kpi_observations(
                    rejecting_metrics,
                    causal_checks_passed=True,
                    trade_implementation_key=(
                        "fixed_6bar_causal_spread_floor_v1"
                    ),
                ),
                profile,
            ).to_payload()
            self.assertEqual(
                "scout_rejected",
                rejecting_metrics["kpi_evaluation"]["route"],
            )
            rejecting_causal = {
                "all_role_checks_passed": True,
                "kpi_route": "scout_rejected",
                "hard_profile_passed": False,
            }
            self.assertEqual(
                "scout_rejected",
                writer._replay_scientific_kpi_evaluation(
                    metrics=rejecting_metrics,
                    causal=rejecting_causal,
                    trade_implementation_key=(
                        "fixed_6bar_causal_spread_floor_v1"
                    ),
                    evaluation_profile=profile,
                ),
            )

    def test_ready_mission_contract_can_be_repinned_but_active_mission_cannot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = build_writer(Path(temp_dir), v21_state())
            state = writer.refresh_ready_mission_contract(
                expected_previous_sha256="1" * 64,
                new_contract_sha256="2" * 64,
                idempotency_key="repin_ready_mission",
            )
            self.assertEqual(state["root_mission"]["contract_sha256"], "2" * 64)

            active = v21_state()
            active["root_mission"]["status"] = "active"
            active["root_mission"]["user_goal_received"] = True
            active_root = Path(temp_dir) / "active"
            active_root.mkdir()
            active_writer = build_writer(active_root, active)
            with self.assertRaises(OperationStateError):
                active_writer.refresh_ready_mission_contract(
                    expected_previous_sha256="1" * 64,
                    new_contract_sha256="2" * 64,
                    idempotency_key="reject_active_repin",
                )

    def test_generic_goal_stage_job_evidence_and_closeout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = build_writer(Path(temp_dir), v21_state())
            state = writer.create_goal(goal_payload={"objective": "test"}, idempotency_key="create")
            self.assertEqual("V2G0001", state["cursor"]["active_goal_id"])
            revision = state["revision"]
            self.assertEqual(
                revision,
                writer.create_goal(goal_payload={"objective": "test"}, idempotency_key="create")["revision"],
            )
            writer.open_goal(goal_id="V2G0001", idempotency_key="open")
            writer.preregister_hypothesis(
                hypothesis_id=None,
                spec_path="campaigns/v2/G1/H1.yaml",
                spec_sha256="2" * 64,
                spec_payload=v22_hypothesis_payload("V2G0001", "V2H0001"),
                split_set_id="V2SP0001",
                material_ids=[],
                idempotency_key="hypothesis",
            )
            state = writer.open_stage(new_stage="S", idempotency_key="stage")
            self.assertEqual("V2S0001", state["cursor"]["stage_id"])
            job_spec_id = writer.objects.put("job_spec", {"stage": "S"})
            input_hash = sha256_payload({"input": 1})
            writer.declare_active_job(
                job_id="V2J0001",
                kind="causal_scout",
                spec_object_id=job_spec_id,
                input_hash=input_hash,
                timeout_seconds=60,
                output_path="campaigns/v2/G1/S1/receipt.json",
                command="axiom-rift goal-run",
                expected_artifacts=[
                    "campaigns/v2/G1/S1/receipt.json",
                    "campaigns/v2/G1/S1/job.log",
                ],
                log_path="campaigns/v2/G1/S1/job.log",
                resume_action="resume V2J0001",
                idempotency_key="declare",
            )
            writer.start_active_job(job_id="V2J0001", idempotency_key="start")
            action = make_next_action("close_goal", goal_id="V2G0001", summary="close rejected scout")
            receipt = {
                "job_id": "V2J0001",
                "goal_id": "V2G0001",
                "hypothesis_id": "V2H0001",
                "stage": "S",
                "stage_id": "V2S0001",
                "input_hash": "3" * 64,
                "outcome": "scout_rejected",
                "claim_ceiling": "diagnostic_observation",
                "artifacts": {},
            }
            with self.assertRaises(OperationStateError):
                writer.record_evidence(
                    evidence_id="V2E000001",
                    record_type="scout_completed",
                    receipt=receipt,
                    idempotency_key="bad-evidence",
                    exact_next_action=action,
                )
            self.assertIsNotNone(writer.control.load()["reentry"]["active_job"])
            receipt["input_hash"] = input_hash
            artifact_dir = Path(temp_dir) / "campaigns/v2/G1/S1"
            artifact_dir.mkdir(parents=True)
            output_path = artifact_dir / "receipt.json"
            log_path = artifact_dir / "job.log"
            output_path.write_text(
                json.dumps({**receipt, "outcome": "tampered"}, sort_keys=True),
                encoding="ascii",
            )
            log_path.write_text("job completed\n", encoding="ascii")
            with self.assertRaisesRegex(
                OperationStateError,
                "output receipt differs",
            ):
                writer.record_evidence(
                    evidence_id="V2E000001",
                    record_type="scout_completed",
                    receipt=receipt,
                    idempotency_key="tampered-evidence",
                    exact_next_action=action,
                )
            output_path.write_text(
                json.dumps(receipt, sort_keys=True),
                encoding="ascii",
            )
            log_path.unlink()
            with self.assertRaisesRegex(
                OperationStateError,
                "auxiliary artifact is missing: log_path",
            ):
                writer.record_evidence(
                    evidence_id="V2E000001",
                    record_type="scout_completed",
                    receipt=receipt,
                    idempotency_key="missing-log-evidence",
                    exact_next_action=action,
                )
            log_path.write_text("job completed\n", encoding="ascii")
            state = writer.record_evidence(
                evidence_id="V2E000001",
                record_type="scout_completed",
                receipt=receipt,
                idempotency_key="evidence",
                exact_next_action=action,
                promote_diagnostic_observation=True,
            )
            self.assertIsNone(state["reentry"]["active_job"])
            writer.record_hypothesis_disposition(
                hypothesis_id="V2H0001",
                evidence_id="V2E000001",
                outcome="scout_rejected",
                memory_path="campaigns/v2/G1/negative/H1.yaml",
                memory_sha256="4" * 64,
                memory_payload={"outcome": "scout_rejected"},
                idempotency_key="disposition",
                exact_next_action=action,
            )
            state = writer.close_goal(
                outcome="closed_no_candidate",
                basis_evidence_id="V2E000001",
                summary_payload={"reason": "scout_rejected"},
                idempotency_key="close",
            )
            self.assertIsNone(state["cursor"]["active_goal_id"])
            self.assertEqual("idle", state["cursor"]["stage"])
            self.assertEqual("open_goal", state["cursor"]["next_action"]["kind"])
            self.assertEqual("closed_no_candidate", state["history"]["recent_closed_goals"][-1]["outcome"])

    def test_active_job_failure_is_not_scientific_evidence_and_resumes_after_repair(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = build_writer(Path(temp_dir), v21_state())
            writer.create_goal(goal_payload={"objective": "test"}, idempotency_key="create")
            writer.open_goal(goal_id="V2G0001", idempotency_key="open")
            writer.preregister_hypothesis(
                hypothesis_id=None,
                spec_path="campaigns/v2/G1/H1.yaml",
                spec_sha256="2" * 64,
                spec_payload=v22_hypothesis_payload("V2G0001", "V2H0001"),
                split_set_id="V2SP0001",
                material_ids=[],
                idempotency_key="hypothesis",
            )
            writer.open_stage(new_stage="S", idempotency_key="stage")
            writer.consume_slice_budget(
                phase="implementation",
                expected_slice_id="V2S0001",
                idempotency_key="implementation",
            )
            job_spec_id = writer.objects.put("job_spec", {"stage": "S"})
            input_hash = sha256_payload({"input": 1})
            writer.declare_active_job(
                job_id="V2J0001",
                kind="scientific_scout",
                spec_object_id=job_spec_id,
                input_hash=input_hash,
                timeout_seconds=60,
                output_path="campaigns/v2/G1/S1",
                command="axiom-rift goal-run",
                expected_artifacts=["campaigns/v2/G1/S1/receipt.json"],
                log_path="campaigns/v2/G1/S1/job.log",
                resume_action="resume V2J0001",
                idempotency_key="declare",
            )
            writer.start_active_job(job_id="V2J0001", idempotency_key="start")

            failed = writer.record_active_job_failure(
                job_id="V2J0001",
                failure_id="V2S0001_FAILURE_1",
                failure_code="receipt_serialization",
                summary="Receipt serialization failed after artifact generation.",
                idempotency_key="failure",
            )
            failure_object_id = failed["reentry"]["active_job"]["failure_object_id"]
            failure = writer.objects.get(failure_object_id)["payload"]
            self.assertFalse(failure["scientific_evidence"])
            self.assertEqual(0, failure["trial_count_delta"])
            self.assertEqual("failed", failed["reentry"]["active_job"]["status"])
            self.assertEqual("repair", failed["cursor"]["next_action"]["kind"])
            row = writer.evidence.rows()[-1]
            self.assertEqual("evidence_job_failed", row["record_type"])
            self.assertEqual(failure_object_id, row["payload"]["failure_object_id"])

            with self.assertRaisesRegex(OperationStateError, "consumed repair budget"):
                writer.resume_active_job_after_repair(
                    job_id="V2J0001",
                    repaired_code_sha256="3" * 64,
                    idempotency_key="early-resume",
                )
            writer.consume_slice_budget(
                phase="repair",
                expected_slice_id="V2S0001",
                idempotency_key="repair",
            )
            resumed = writer.resume_active_job_after_repair(
                job_id="V2J0001",
                repaired_code_sha256="3" * 64,
                idempotency_key="resume",
            )
            job = resumed["reentry"]["active_job"]
            self.assertEqual("running", job["status"])
            self.assertEqual(input_hash, job["input_hash"])
            self.assertEqual("V2S0001_FAILURE_1", job["resumed_after_failure_id"])
            self.assertEqual(1, job["resume_count"])
            self.assertEqual("record_evidence", resumed["cursor"]["next_action"]["kind"])

    def test_mismatched_identity_does_not_consume_namespace_or_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = build_writer(Path(temp_dir), v21_state())
            with self.assertRaises(TransitionError):
                writer.create_goal(
                    goal_id="V2G0002",
                    goal_payload={"objective": "wrong id"},
                    idempotency_key="bad",
                )
            self.assertEqual(1, writer.control.load()["namespace"]["next_goal"])
            self.assertEqual([], writer.evidence.rows())

    def test_orphan_ledger_is_reported_and_blocks_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = build_writer(Path(temp_dir), v21_state())
            writer.evidence.append("ORPHAN", "test", {"value": 1}, "2026-01-01T00:00:00Z")
            report = writer.reconciliation_report()
            self.assertFalse(report["ok"])
            self.assertEqual("ledger_ahead_orphan_detected", report["ledgers"]["evidence"]["status"])
            with self.assertRaises(OperationStateError):
                writer.create_goal(goal_payload={"objective": "blocked"}, idempotency_key="blocked")

    def test_ledger_append_then_control_replace_failure_is_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = build_writer(Path(temp_dir), v21_state())
            writer.control.replace_func = lambda _source, _target: (_ for _ in ()).throw(
                OSError("replace failed")
            )
            with self.assertRaises(ControlStateError):
                writer.create_goal(goal_payload={"objective": "recover"}, idempotency_key="create")
            self.assertTrue(writer.control.recovery_path.is_file())
            self.assertFalse(writer.reconciliation_report()["ok"])
            recovered = writer.recover_pending_control()
            self.assertEqual("V2G0001", recovered["cursor"]["active_goal_id"])
            self.assertFalse(writer.control.recovery_path.exists())
            self.assertTrue(writer.reconciliation_report()["ok"])

    def test_mission_and_slice_budgets_are_consumed_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = build_writer(Path(temp_dir), v21_state())
            writer.create_goal(goal_payload={"objective": "budget"}, idempotency_key="create")
            writer.open_goal(goal_id="V2G0001", idempotency_key="open")
            state = writer.preregister_hypothesis(
                hypothesis_id=None,
                spec_path="campaigns/v2/G1/H1.yaml",
                spec_sha256="2" * 64,
                spec_payload=v22_hypothesis_payload("V2G0001", "V2H0001"),
                split_set_id="V2SP0001",
                material_ids=[],
                idempotency_key="hypothesis",
            )
            self.assertEqual(11, state["mission_budget"]["remaining"]["hypothesis_batches"])
            state = writer.open_stage(new_stage="S", idempotency_key="stage")
            self.assertEqual(11, state["mission_budget"]["remaining"]["scout_jobs"])
            state = writer.consume_slice_budget(
                phase="validation",
                validation_key="validation-key",
                expected_slice_id="V2S0001",
                idempotency_key="validation-budget",
            )
            self.assertEqual(0, state["slice_budget"]["validation_remaining"])
            with self.assertRaises(OperationStateError):
                writer.consume_slice_budget(
                    phase="validation",
                    validation_key="different-key",
                    expected_slice_id="V2S0001",
                    idempotency_key="second-validation",
                )

    def test_root_terminal_guard_rejects_new_goal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = v21_state()
            state["root_mission"].update(
                {
                    "status": "terminal",
                    "terminal_outcome": "completed_pre_live_handoff",
                    "terminal_request": {
                        "mission_id": "AXIOM_ROOT_0001",
                        "outcome": "completed_pre_live_handoff",
                        "basis_evidence_id": "V2E000200",
                        "requested_by_goal_id": "V2G0001",
                        "request_object_id": "a" * 64,
                    },
                    "closeout_object_id": "b" * 64,
                }
            )
            state["cursor"]["terminal_outcome"] = "completed_pre_live_handoff"
            state["cursor"]["next_action"] = make_next_action("none", summary="complete")
            writer = build_writer(Path(temp_dir), state)
            with self.assertRaises(OperationStateError):
                writer.create_goal(goal_payload={"objective": "forbidden"}, idempotency_key="forbidden")

    def test_closeout_history_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = v21_state()
            state["history"]["recent_closed_goals"] = [
                {
                    "goal_id": f"V2G{index:04d}",
                    "outcome": "closed_no_candidate",
                    "summary_object_id": "a" * 64,
                }
                for index in range(1, 9)
            ]
            state["namespace"]["next_goal"] = 9
            writer = build_writer(Path(temp_dir), state)
            writer.create_goal(goal_payload={"objective": "ninth"}, idempotency_key="create")
            writer.open_goal(goal_id="V2G0009", idempotency_key="open")
            writer.preregister_hypothesis(
                hypothesis_id=None,
                spec_path="campaigns/v2/G9/H1.yaml",
                spec_sha256="2" * 64,
                spec_payload=v22_hypothesis_payload("V2G0009", "V2H0001"),
                split_set_id="V2SP0001",
                material_ids=[],
                idempotency_key="hypothesis",
            )
            receipt = {
                "goal_id": "V2G0009",
                "hypothesis_id": "V2H0001",
                "stage": "H",
                "stage_id": "V2H0001",
                "outcome": "closed_no_candidate",
            }
            writer.record_evidence(
                evidence_id="V2E000009",
                record_type="hypothesis_closed",
                receipt=receipt,
                idempotency_key="evidence",
                exact_next_action=make_next_action("close_goal", goal_id="V2G0009"),
            )
            state = writer.close_goal(
                outcome="closed_no_candidate",
                basis_evidence_id="V2E000009",
                summary_payload={"reason": "done"},
                idempotency_key="close",
            )
            self.assertEqual(8, len(state["history"]["recent_closed_goals"]))
            self.assertEqual("V2G0002", state["history"]["recent_closed_goals"][0]["goal_id"])

    def test_successful_internal_close_snapshots_claim_and_builds_exact_root_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            objects = ObjectStore(root / "objects")
            receipt = {
                "mission_id": "AXIOM_ROOT_0001",
                "goal_id": "V2G0001",
                "outcome": "completed_pre_live_handoff",
            }
            receipt_object_id = objects.put("evidence_receipt", receipt)
            evidence = HashChainLedger(root / "evidence.jsonl", "evidence")
            row = evidence.append(
                "V2E000200",
                "materialization_complete",
                {"goal_id": "V2G0001", "receipt_object_id": receipt_object_id},
                "2026-01-01T00:00:00Z",
            )
            state = v21_state()
            state["root_mission"].update({"status": "active", "user_goal_received": True})
            state["cursor"].update(
                {
                    "active_goal_id": "V2G0001",
                    "goal_status": "open",
                    "active_hypothesis_id": "V2H0001",
                    "stage": "M",
                    "stage_id": "V2M0001",
                    "stage_status": "completed",
                    "next_action": make_next_action("close_goal", goal_id="V2G0001"),
                }
            )
            state["claim"].update(
                {
                    "subject_kind": "hypothesis",
                    "subject_id": "V2H0001",
                    "current_level": "pre_live_ready",
                    "claim_ceiling": "pre_live_ready",
                }
            )
            state["ledger_heads"]["evidence"] = {
                "ledger_seq": row["ledger_seq"],
                "row_sha256": row["row_sha256"],
            }
            writer = build_writer(root, state)

            closed_goal = writer.close_goal(
                outcome="completed_internal_goal",
                basis_evidence_id="V2E000200",
                summary_payload={"status": "materialized"},
                idempotency_key="close-success-goal",
            )

            self.assertEqual("none", closed_goal["claim"]["current_level"])
            action = closed_goal["cursor"]["next_action"]
            self.assertEqual("close_root_mission", action["kind"])
            self.assertEqual("AXIOM_ROOT_0001", action["mission_id"])
            self.assertEqual("completed_pre_live_handoff", action["terminal_outcome"])
            self.assertEqual("V2E000200", action["basis_evidence_id"])
            request_id = closed_goal["root_mission"]["terminal_request"]["request_object_id"]
            self.assertEqual(
                "pre_live_ready",
                writer.objects.get(request_id)["payload"]["claim_snapshot"]["current_level"],
            )

            pending = writer.close_root_mission(
                outcome="completed_pre_live_handoff",
                basis_evidence_id="V2E000200",
                idempotency_key="close-success-root",
            )
            self.assertEqual("terminal_validation_pending", pending["root_mission"]["status"])
            self.assertEqual("validate_root_closeout", pending["cursor"]["next_action"]["kind"])
            terminal_slice = "AXIOM_ROOT_0001_terminal_closeout"
            writer.consume_slice_budget(
                phase="validation",
                validation_key="root-validation-key",
                expected_slice_id=terminal_slice,
                idempotency_key="authorize-root-validation",
            )
            writer.record_validation_receipt(
                receipt_id="V2VRROOT",
                receipt={
                    "validation_key": "root-validation-key",
                    "outcome": "pass",
                    "validator_id": "root-close-validator",
                    "duration_seconds": 0.01,
                    "slice_id": terminal_slice,
                },
                idempotency_key="record-root-validation",
                exact_next_action=pending["cursor"]["next_action"],
            )
            validated = writer.close_slice(
                slice_id=terminal_slice,
                validation_receipt_id="V2VRROOT",
                declared_content_paths=("registries/v2/control_state.yaml",),
                idempotency_key="close-root-validation-slice",
            )
            self.assertEqual("terminal_validation_pending", validated["root_mission"]["status"])
            self.assertEqual("verify_git_closeout", validated["cursor"]["next_action"]["kind"])
            self.assertEqual("V2VRROOT", validated["reentry"]["git_sync"]["validation_receipt_id"])

    def test_slice_close_rejects_directory_scope_before_git_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = build_writer(Path(temp_dir), v21_state())
            slice_id = "V2SL_SCOPE"
            writer.open_slice(slice_id=slice_id, idempotency_key="open-scope-slice")
            writer.consume_slice_budget(
                phase="validation",
                validation_key="scope-validation-key",
                expected_slice_id=slice_id,
                idempotency_key="authorize-scope-validation",
            )
            writer.record_validation_receipt(
                receipt_id="V2VRSCOPE",
                receipt={
                    "validation_key": "scope-validation-key",
                    "outcome": "pass",
                    "validator_id": "scope-validator",
                    "duration_seconds": 0.01,
                    "slice_id": slice_id,
                },
                idempotency_key="record-scope-validation",
                exact_next_action=writer.control.load()["cursor"]["next_action"],
            )

            with self.assertRaisesRegex(OperationStateError, "declared content paths"):
                writer.close_slice(
                    slice_id=slice_id,
                    validation_receipt_id="V2VRSCOPE",
                    declared_content_paths=("registries/v2/scientific/",),
                    idempotency_key="close-directory-scope",
                )

    def test_internal_close_rejects_root_outcome_and_store_rejects_direct_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = build_writer(Path(temp_dir), v21_state())
            with self.assertRaises(OperationStateError):
                writer.close_goal(
                    outcome="completed_pre_live_handoff",
                    basis_evidence_id="missing",
                    summary_payload={},
                    idempotency_key="bad-root-as-internal",
                )

            state = writer.control.load()

            def bypass(draft: dict) -> None:
                draft["root_mission"]["status"] = "terminal_pending_push"
                draft["root_mission"]["terminal_outcome"] = "stopped_by_user"

            with self.assertRaises(ControlStateError):
                writer.control.commit(state["revision"], "direct-terminal", bypass)

            injected = v21_state()
            injected["root_mission"].update({"status": "active", "user_goal_received": True})
            injected["cursor"]["next_action"] = make_next_action(
                "close_root_mission",
                mission_id="AXIOM_ROOT_0001",
                terminal_outcome="closed_no_candidate",
                basis_evidence_id="V2E000999",
                prerequisite_receipt_ids=["V2E000999"],
            )
            injected_root = Path(temp_dir) / "injected"
            injected_root.mkdir()
            with self.assertRaises(ControlStateError):
                build_writer(injected_root, injected).control.load()


class V21MigrationAndHoldoutTests(unittest.TestCase):
    def test_normal_control_load_rejects_unbound_active_science(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state = v21_state()
            state["scientific"] = {
                "status": "active",
                "root_mission_id": "AXIOM_ROOT_0001",
                "epoch_id": "V2EPOCH0001",
                "index_path": "registries/v2/scientific/index.yaml",
                "research_map_path": "registries/v2/scientific/research_map.yaml",
                "hypothesis_ledger_path": (
                    "registries/v2/scientific/hypothesis_ledger.jsonl"
                ),
                "hypothesis_object_ids": [],
                "trial_receipt_ids": [],
                "negative_memory_object_ids": [],
                "ingredient_object_ids": [],
                "candidate_object_ids": [],
                "selected_bundle_id": None,
                "holdout_reveals": 0,
            }
            path = root / "control_state.yaml"
            path.write_text(yaml.safe_dump(state, sort_keys=False), encoding="ascii")
            store = ControlStore(path, object_store=ObjectStore(root / "objects"))
            with self.assertRaisesRegex(
                ControlStateError, "requires a bound control-state index"
            ):
                store.load()

    def test_v1_activation_state_migrates_idempotently_to_ready_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            objects = ObjectStore(root / "objects")
            activation_object_id = objects.put("activation_receipt", {"outcome": "v2_activated"})
            writer = build_writer(root, v1_activated_state(activation_object_id))
            state = writer.migrate_control_state_v1_to_v2(
                mission_id="AXIOM_ROOT_0001",
                mission_contract_path="contracts/v2/project_contract.yaml",
                mission_contract_sha256="1" * 64,
            )
            self.assertEqual("axiom_rift_v2_control_state_v2", state["schema"])
            self.assertEqual("ready", state["root_mission"]["status"])
            self.assertEqual("V2G0002", state["cursor"]["next_action"]["goal_id"])
            self.assertEqual("V2G0001", state["history"]["recent_closed_goals"][0]["goal_id"])
            self.assertEqual("V2B0001", state["history"]["recent_closed_goals"][0]["work_unit_id"])
            self.assertEqual(activation_object_id, state["activation"]["activation_object_id"])
            revision = state["revision"]
            repeated = writer.migrate_control_state_v1_to_v2(
                mission_id="AXIOM_ROOT_0001",
                mission_contract_path="contracts/v2/project_contract.yaml",
                mission_contract_sha256="1" * 64,
            )
            self.assertEqual(revision, repeated["revision"])

    def test_holdout_permit_requires_sync_and_matching_frozen_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            objects = ObjectStore(root / "objects")
            frozen_payload = {"candidate_id": "V2H0001", "frozen": True}
            frozen_object_id = objects.put("frozen_identity", frozen_payload)
            frozen_hash = sha256_payload(frozen_payload)
            p_gate_object_id = objects.put(
                "evidence_receipt",
                {
                    "stage": "P",
                    "gate_passed": True,
                    "candidate_id": "V2H0001",
                    "frozen_identity_bundle_sha256": frozen_hash,
                },
            )
            trial_object_id = objects.put(
                "evidence_receipt",
                {"candidate_id": "V2H0001", "trial_accounting_complete": True},
            )
            evidence = HashChainLedger(root / "evidence.jsonl", "evidence")
            evidence.append(
                "V2E000101",
                "p_gate_receipt",
                {"receipt_object_id": p_gate_object_id, "goal_id": "V2G0001"},
                "2026-01-01T00:00:00Z",
            )
            trial_row = evidence.append(
                "V2E000102",
                "trial_accounting_receipt",
                {"receipt_object_id": trial_object_id, "goal_id": "V2G0001"},
                "2026-01-01T00:00:01Z",
            )
            state = v21_state()
            state["root_mission"]["status"] = "active"
            state["root_mission"]["user_goal_received"] = True
            state["mission_budget"]["frozen"] = True
            state["namespace"].update(
                {
                    "next_goal": 2,
                    "next_hypothesis": 2,
                    "next_scout": 2,
                    "next_confirmation": 2,
                    "next_promotion": 2,
                }
            )
            state["cursor"].update(
                {
                    "active_goal_id": "V2G0001",
                    "goal_status": "open",
                    "active_hypothesis_id": "V2H0001",
                    "stage": "P",
                    "stage_id": "V2P0001",
                    "stage_status": "completed",
                    "next_action": make_next_action(
                        "declare_job",
                        goal_id="V2G0001",
                        stage="P",
                        subject_id="V2P0001",
                        job_kind="holdout",
                    ),
                }
            )
            state["claim"].update(
                {
                    "subject_kind": "hypothesis",
                    "subject_id": "V2H0001",
                    "current_level": "economics_pass",
                    "claim_ceiling": "selected",
                    "identity_bundle_object_id": frozen_object_id,
                    "frozen_identity_bundle_sha256": frozen_hash,
                    "identity_frozen": True,
                }
            )
            state["ledger_heads"]["evidence"] = {
                "ledger_seq": trial_row["ledger_seq"],
                "row_sha256": trial_row["row_sha256"],
            }
            state["reentry"]["git_sync"] = {"status": "unsynced"}
            writer = build_writer(root, state)
            with self.assertRaises(OperationStateError):
                writer.issue_holdout_permit(
                    permit_id="V2HP0001",
                    candidate_id="V2H0001",
                    frozen_identity_bundle_sha256=frozen_hash,
                    p_gate_receipt_id="V2E000101",
                    trial_accounting_receipt_id="V2E000102",
                    idempotency_key="permit",
                )
            dirty = writer.control.commit(
                writer.control.load()["revision"],
                "touch-freeze-state",
                lambda _draft: None,
            )
            dirty_fingerprint = dirty["reentry"]["git_sync"]["dirty_state_fingerprint"]
            writer.control.commit(
                dirty["revision"],
                "sync",
                lambda draft: draft["reentry"].update(
                    {
                        "git_sync": {
                            "status": "metadata_pending_push",
                            "validated_content_commit": "a" * 40,
                            "local_head": "a" * 40,
                            "origin_main_head": "a" * 40,
                            "validation_receipt_id": "V2VRTEST",
                            "closeout_object_id": "c" * 64,
                            "content_state_fingerprint": dirty_fingerprint,
                            "metadata_allowed_paths": ["registries/v2"],
                        }
                    }
                ),
                git_sync_policy="record_metadata",
            )
            state = writer.issue_holdout_permit(
                permit_id="V2HP0001",
                candidate_id="V2H0001",
                frozen_identity_bundle_sha256=frozen_hash,
                p_gate_receipt_id="V2E000101",
                trial_accounting_receipt_id="V2E000102",
                idempotency_key="permit",
            )
            self.assertEqual("V2HP0001", state["holdout"]["permit"]["permit_id"])
            revision = state["revision"]
            repeated = writer.issue_holdout_permit(
                permit_id="V2HP0001",
                candidate_id="V2H0001",
                frozen_identity_bundle_sha256=frozen_hash,
                p_gate_receipt_id="V2E000101",
                trial_accounting_receipt_id="V2E000102",
                idempotency_key="permit",
            )
            self.assertEqual(revision, repeated["revision"])

    def test_root_closed_no_candidate_requires_exhaustion_and_git_sync(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            objects = ObjectStore(root / "objects")
            receipt = {
                "mission_id": "AXIOM_ROOT_0001",
                "outcome": "closed_no_candidate",
                "material_exhaustion_complete": True,
                "mission_budget_exhausted": False,
                "remaining_axes_low_information_value": True,
            }
            receipt_object_id = objects.put("evidence_receipt", receipt)
            evidence = HashChainLedger(root / "evidence.jsonl", "evidence")
            row = evidence.append(
                "V2E000199",
                "material_exhaustion",
                {"receipt_object_id": receipt_object_id},
                "2026-01-01T00:00:00Z",
            )
            state = v21_state()
            state["root_mission"]["status"] = "active"
            state["root_mission"]["user_goal_received"] = True
            request_payload = {
                "mission_id": "AXIOM_ROOT_0001",
                "outcome": "closed_no_candidate",
                "basis_evidence_id": "V2E000199",
                "requested_by_goal_id": "V2G0001",
                "claim_snapshot": state["claim"],
            }
            request_object_id = objects.put("root_terminal_request", request_payload)
            state["root_mission"]["terminal_request"] = {
                "mission_id": "AXIOM_ROOT_0001",
                "outcome": "closed_no_candidate",
                "basis_evidence_id": "V2E000199",
                "requested_by_goal_id": "V2G0001",
                "request_object_id": request_object_id,
            }
            state["cursor"]["next_action"] = make_next_action(
                "close_root_mission",
                mission_id="AXIOM_ROOT_0001",
                terminal_outcome="closed_no_candidate",
                basis_evidence_id="V2E000199",
                prerequisite_receipt_ids=["V2E000199"],
            )
            state["mission_budget"]["frozen"] = True
            state["ledger_heads"]["evidence"] = {
                "ledger_seq": row["ledger_seq"],
                "row_sha256": row["row_sha256"],
            }
            writer = build_writer(root, state)
            closed = writer.close_root_mission(
                outcome="closed_no_candidate",
                basis_evidence_id="V2E000199",
                idempotency_key="root-close",
            )
            self.assertEqual("terminal_validation_pending", closed["root_mission"]["status"])
            self.assertEqual("closed_no_candidate", closed["root_mission"]["terminal_outcome"])
            self.assertEqual("validate_root_closeout", closed["cursor"]["next_action"]["kind"])
            self.assertEqual("unsynced", closed["reentry"]["git_sync"]["status"])


if __name__ == "__main__":
    unittest.main()
