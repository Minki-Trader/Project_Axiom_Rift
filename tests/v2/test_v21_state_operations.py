from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from axiom_rift.v2.identity import ObjectStore, sha256_payload
from axiom_rift.v2.ledger import HashChainLedger
from axiom_rift.v2.operations import OperationStateError, V2OperationWriter
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
    return {
        "schema": "axiom_rift_v2_hypothesis_v2",
        "status": "preregistered",
        "goal_id": goal_id,
        "hypothesis_id": hypothesis_id,
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
            "family_id": "V2FAM_TEST",
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
        "routing": {},
        "evidence_budget": {},
    }


class V21GenericLifecycleTests(unittest.TestCase):
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
                    "family_id": "V2FAM_TEST",
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
                output_path="campaigns/v2/G1/S1",
                command="axiom-rift goal-run",
                expected_artifacts=["campaigns/v2/G1/S1/receipt.json"],
                log_path="artifacts/v2/G1/S1.log",
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
                "artifacts": {
                    "receipt": {"path": "campaigns/v2/G1/S1/receipt.json"}
                },
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
                {"status": "terminal", "terminal_outcome": "completed_pre_live_handoff"}
            )
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


class V21MigrationAndHoldoutTests(unittest.TestCase):
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
            writer.control.commit(
                writer.control.load()["revision"],
                "sync",
                lambda draft: draft["reentry"].update(
                    {
                        "git_sync": {
                            "status": "synced",
                            "local_head": "b" * 40,
                            "origin_main_head": "b" * 40,
                        }
                    }
                ),
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
            state["mission_budget"]["frozen"] = True
            state["ledger_heads"]["evidence"] = {
                "ledger_seq": row["ledger_seq"],
                "row_sha256": row["row_sha256"],
            }
            state["reentry"]["git_sync"] = {
                "status": "synced",
                "local_head": "a" * 40,
                "origin_main_head": "a" * 40,
            }
            writer = build_writer(root, state)
            closed = writer.close_root_mission(
                outcome="closed_no_candidate",
                basis_evidence_id="V2E000199",
                idempotency_key="root-close",
            )
            self.assertEqual("terminal", closed["root_mission"]["status"])
            self.assertEqual("closed_no_candidate", closed["root_mission"]["terminal_outcome"])
            self.assertEqual("none", closed["cursor"]["next_action"]["kind"])


if __name__ == "__main__":
    unittest.main()
