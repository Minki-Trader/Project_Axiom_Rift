from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

import yaml

from axiom_rift.v2.operations import OperationStateError
from axiom_rift.v2.state.transitions import make_next_action
from tests.v2.test_v21_state_operations import (
    build_writer,
    v21_state,
    v22_hypothesis_payload,
)

from axiom_rift.v2.research.autonomy import (
    AutonomyGuardError,
    HypothesisBatch,
    MissionResearchBudget,
    NumericKnob,
    ResearchMap,
    SchedulerProposal,
    ScopedNegativeMemory,
    assert_no_scientific_inheritance,
    choose_next_hypothesis,
    route_s_disposition,
    validate_stage_entry,
)
from axiom_rift.v2.research.dispatch import (
    CallableProgramRegistry,
    GenericProgramRunner,
    JITRegistrationReceipt,
    PROGRAM_KINDS,
    ProgramDefinition,
    ProgramDispatchError,
    callable_sha256,
)
from axiom_rift.v2.research.runtime_data import (
    PortfolioRiskDescriptor,
    REQUIRED_RISK_ACCOUNTING,
    RuntimeDataEligibilityRegistry,
    RuntimeDataError,
    RuntimeSourceProbe,
    SizingDescriptor,
    SizingGateContext,
    validate_sizing_gate,
)


PROGRAM_IDS = {
    "feature": "V2FP9001",
    "label": "V2LP9001",
    "model": "V2MP9001",
    "calibration": "V2CP9001",
    "selector": "V2SEL9001",
    "trade": "V2TP9001",
    "sizing": "V2SZ9001",
    "portfolio_risk": "V2PR9001",
}


def synthetic_adapter(payload, parameters, context):
    trace = list(payload.get("trace", []))
    trace.append(context["kind"])
    return {"trace": trace, "tag": parameters["tag"]}


def program_definition(kind: str, *, program_id: str | None = None) -> ProgramDefinition:
    return ProgramDefinition(
        program_id=program_id or PROGRAM_IDS[kind],
        kind=kind,
        implementation_key=f"synthetic_{kind}",
        implementation_sha256=callable_sha256(synthetic_adapter),
        contract_sha256="a" * 64,
        parameters={"tag": kind},
        input_schema="synthetic_mapping_v1",
        output_schema="synthetic_mapping_v1",
        causal_requirements=("no_future_input",),
        portability_status="synthetic_only",
        onnx_requirement="deferred",
        mql_requirement="deferred",
    )


def registration_receipt(definition: ProgramDefinition) -> JITRegistrationReceipt:
    return JITRegistrationReceipt(
        program_id=definition.program_id,
        implementation_key=definition.implementation_key,
        implementation_sha256=definition.implementation_sha256,
        contract_sha256=definition.contract_sha256,
        fixture_checks_passed=True,
        causality_checks_passed=True,
        interface_checks_passed=True,
    )


def populated_registry() -> CallableProgramRegistry:
    registry = CallableProgramRegistry()
    for kind in PROGRAM_KINDS:
        definition = program_definition(kind)
        registry.jit_register(
            definition,
            synthetic_adapter,
            registration_receipt(definition),
        )
    return registry


def runtime_probe(**overrides) -> RuntimeSourceProbe:
    values = {
        "source_id": "V2SRC9001",
        "provider": "synthetic_provider",
        "symbol": "SYNTHETIC",
        "timeframe": "M5",
        "terminal_sha256": "1" * 64,
        "account_capability_sha256": "2" * 64,
        "adapter_sha256": "3" * 64,
        "alignment_policy_sha256": "4" * 64,
        "historical_access": True,
        "live_access": True,
        "recent_closed_bars": True,
        "causal_at_us100_m5_close": True,
        "cold_start_history": True,
        "freshness_observable": True,
        "deterministic_missing_policy": True,
        "python_runtime_access": True,
        "ea_runtime_access": True,
        "python_ea_parity_passed": True,
        "live_conformance_observed": True,
    }
    values.update(overrides)
    return RuntimeSourceProbe(**values)


class EmptyResearchAndHypothesisTests(unittest.TestCase):
    def test_empty_research_map_has_only_generic_unseen_axes(self) -> None:
        research_map = ResearchMap.empty()

        self.assertTrue(research_map.is_empty)
        self.assertIsNone(research_map.scientific_epoch_id)
        self.assertTrue(all(axis.state == "unseen" for axis in research_map.axes.values()))
        self.assertTrue(
            all(not axis.evidence_ids for axis in research_map.axes.values())
        )

    def test_scientific_inheritance_guard_rejects_keys_and_values(self) -> None:
        with self.assertRaises(AutonomyGuardError):
            assert_no_scientific_inheritance({"prior_kpi": 1.0})
        with self.assertRaises(AutonomyGuardError):
            assert_no_scientific_inheritance({"note": "stage 59 result"})
        assert_no_scientific_inheritance({"origin": "current_epoch_only"})

    def test_hypothesis_types_enforce_bundle_shape_and_bounded_knobs(self) -> None:
        hashes = [f"{value:064x}" for value in range(1, 6)]
        structural = HypothesisBatch(
            hypothesis_id="V2H9001",
            family_id="family_alpha",
            hypothesis_type="structural_batch",
            dominant_axis="axis_feature",
            scientific_epoch_id="V2EPOCH0001",
            scout_mode="s_breadth",
            bundle_roles={"control": hashes[0], "variant_a": hashes[1], "variant_b": hashes[2]},
            semantic_signature_sha256="f" * 64,
            numeric_knobs=(NumericKnob("model.alpha", 0.1, 1.0, 10.0),),
            local_calibration_rounds=1,
        )
        coupled = HypothesisBatch(
            hypothesis_id="V2H9002",
            family_id="family_beta",
            hypothesis_type="coupled_mechanism",
            dominant_axis="axis_lifecycle",
            scientific_epoch_id="V2EPOCH0001",
            scout_mode="s_depth",
            bundle_roles={"control": hashes[0], "coupled": hashes[1]},
            semantic_signature_sha256="e" * 64,
            coupled_program_kinds=("label", "trade"),
        )
        synthesis = HypothesisBatch(
            hypothesis_id="V2H9003",
            family_id="family_gamma",
            hypothesis_type="synthesis_ablation",
            dominant_axis="axis_synthesis",
            scientific_epoch_id="V2EPOCH0001",
            scout_mode="s_synthesis",
            bundle_roles={
                "parent_a": hashes[0],
                "parent_b": hashes[1],
                "combined": hashes[2],
                "ablation": hashes[3],
            },
            semantic_signature_sha256="d" * 64,
            parent_evidence_ids=("V2E9001", "V2E9002"),
        )

        self.assertEqual(structural.scout_mode, "s_breadth")
        self.assertEqual(coupled.coupled_program_kinds, ("label", "trade"))
        self.assertEqual(set(synthesis.bundle_roles), {"parent_a", "parent_b", "combined", "ablation"})

        with self.assertRaises(AutonomyGuardError):
            HypothesisBatch(
                hypothesis_id="V2H9004",
                family_id="family_bad",
                hypothesis_type="structural_batch",
                dominant_axis="axis_feature",
                scientific_epoch_id="V2EPOCH0001",
                scout_mode="s_breadth",
                bundle_roles={"a": hashes[0], "b": hashes[0], "c": hashes[1]},
                semantic_signature_sha256="c" * 64,
            )

    def test_scout_routes_keep_broken_execution_out_of_scientific_failure(self) -> None:
        self.assertEqual(route_s_disposition("promising", "s_breadth").next_route, "s_depth")
        self.assertEqual(route_s_disposition("promising", "s_depth").next_route, "route_to_R")
        broken = route_s_disposition("broken_execution", "s_synthesis")
        self.assertEqual(broken.next_route, "repair")
        self.assertFalse(broken.scientific_failure)


class DispatchTests(unittest.TestCase):
    def test_empty_registry_and_hash_verified_jit_registration(self) -> None:
        registry = CallableProgramRegistry()
        self.assertEqual(registry.program_count, 0)

        definition = program_definition("feature")
        observed = registry.jit_register(
            definition,
            synthetic_adapter,
            registration_receipt(definition),
        )

        self.assertEqual(observed.program_sha256, definition.program_sha256)
        self.assertEqual(registry.program_count, 1)
        with self.assertRaises(ProgramDispatchError):
            registry.register_callable(
                "bad_hash",
                synthetic_adapter,
                expected_sha256="0" * 64,
            )

    def test_renamed_identical_program_is_rejected(self) -> None:
        registry = CallableProgramRegistry()
        original = program_definition("feature")
        registry.jit_register(original, synthetic_adapter, registration_receipt(original))
        renamed = program_definition("feature", program_id="V2FP9002")

        with self.assertRaisesRegex(ProgramDispatchError, "renaming"):
            registry.register_program(renamed, registration_receipt(renamed))

    def test_all_eight_kinds_form_one_callable_pure_bundle(self) -> None:
        registry = populated_registry()
        bundle = registry.make_bundle(PROGRAM_IDS)
        result = GenericProgramRunner(registry).run(
            bundle,
            {"trace": []},
            stage="S",
            mode="s_breadth",
        )

        self.assertEqual(set(bundle.programs), set(PROGRAM_KINDS))
        self.assertEqual(result.outputs["portfolio_risk"]["trace"], list(PROGRAM_KINDS))
        self.assertFalse(result.state_mutated)
        self.assertFalse(result.evidence_claim_created)
        self.assertEqual(len(result.result_sha256), 64)

    def test_fixture_only_program_cannot_enter_active_bundle(self) -> None:
        definitions = {
            kind: program_definition(kind)
            for kind in PROGRAM_KINDS
        }
        feature = definitions["feature"]
        definitions["feature"] = ProgramDefinition(
            **{
                **feature.__dict__,
                "parameters": dict(feature.parameters),
                "fixture_only": True,
            }
        )
        with self.assertRaisesRegex(ProgramDispatchError, "fixture-only"):
            from axiom_rift.v2.research.dispatch import ProgramBundle

            ProgramBundle(definitions)


class SchedulerAndNegativeMemoryTests(unittest.TestCase):
    @staticmethod
    def proposal(
        hypothesis_id: str,
        axis: str,
        executable_hash: str,
        signature: str,
        *,
        information: float = 0.8,
    ) -> SchedulerProposal:
        return SchedulerProposal(
            hypothesis_id=hypothesis_id,
            family_id=f"family_{hypothesis_id.lower()}",
            dominant_axis=axis,
            executable_hashes=(executable_hash,),
            semantic_signature_sha256=signature,
            expected_information_value=information,
            structural_novelty=0.7,
            complementary_potential=0.4,
            scientific_trial_cost=0.1,
            adjacency_penalty=0.0,
            causal_executable=True,
            data_identifiable=True,
        )

    def test_scheduler_is_deterministic_and_coverage_aware(self) -> None:
        proposals = (
            self.proposal("V2H9101", "axis_feature", "1" * 64, "a" * 64),
            self.proposal("V2H9102", "axis_model", "2" * 64, "b" * 64),
        )
        first = choose_next_hypothesis(proposals, ResearchMap.empty())
        second = choose_next_hypothesis(reversed(proposals), ResearchMap.empty())

        self.assertEqual(first.selected_hypothesis_id, "V2H9101")
        self.assertEqual(first.decision_sha256, second.decision_sha256)

    def test_scheduler_blocks_renames_identical_retries_and_axis_monopoly(self) -> None:
        proposals = (
            self.proposal("V2H9201", "axis_feature", "1" * 64, "a" * 64),
            self.proposal("V2H9202", "axis_model", "2" * 64, "b" * 64),
            self.proposal("V2H9203", "axis_trade", "3" * 64, "c" * 64),
        )
        decision = choose_next_hypothesis(
            proposals,
            ResearchMap.empty(),
            recent_dominant_axes=(
                "axis_feature",
                "axis_model",
                "axis_feature",
                "axis_session",
                "axis_selector",
            ),
            evaluated_executable_hashes=frozenset({"2" * 64}),
            seen_semantic_signatures=frozenset({"c" * 64}),
        )
        codes = {
            row.hypothesis_id: set(row.rejection_codes)
            for row in decision.candidate_records
        }

        self.assertIn("dominant_axis_rotation_required", codes["V2H9201"])
        self.assertIn("identical_executable_retry", codes["V2H9202"])
        self.assertIn("renamed_duplicate", codes["V2H9203"])
        self.assertIsNone(decision.selected_hypothesis_id)

    def test_one_context_failure_cannot_refute_a_family(self) -> None:
        context = {
            "program_bundle_sha256": "1" * 64,
            "data_identity_sha256": "2" * 64,
            "split_identity_sha256": "3" * 64,
            "cost_identity_sha256": "4" * 64,
            "direction_context": "both",
            "session_context": "all_sessions",
            "regime_context": "unpartitioned",
            "lifecycle_context": "registered_lifecycle",
        }
        shallow = ScopedNegativeMemory(
            hypothesis_id="V2H9301",
            family_id="family_delta",
            strength="shallow_negative",
            evidence_ids=("V2E9301",),
            tested_context=context,
            untested_contexts=("orthogonal_context",),
            do_not_retry_hashes=("5" * 64,),
        )
        self.assertTrue(shallow.blocks(family_id="family_other", executable_hashes=("5" * 64,)))
        self.assertFalse(shallow.blocks(family_id="family_delta", executable_hashes=("6" * 64,)))

        with self.assertRaisesRegex(AutonomyGuardError, "family refutation"):
            ScopedNegativeMemory(
                hypothesis_id="V2H9301",
                family_id="family_delta",
                strength="family_refuted",
                evidence_ids=("V2E9301",),
                tested_context=context,
                untested_contexts=(),
                do_not_retry_hashes=("5" * 64,),
            )

    def test_future_root_requires_frozen_result_independent_emergency_ceiling(self) -> None:
        MissionResearchBudget(
            rolling_window_size=8,
            emergency_hypothesis_ceiling=80,
            frozen_before_first_h=True,
            result_independent=True,
        ).validate_for_open()
        with self.assertRaises(AutonomyGuardError):
            MissionResearchBudget(
                rolling_window_size=8,
                emergency_hypothesis_ceiling=8,
                frozen_before_first_h=True,
                result_independent=True,
            ).validate_for_open()


class RuntimeEligibilityAndSizingTests(unittest.TestCase):
    def test_runtime_registry_starts_empty_and_pending_does_not_block_unrelated_work(self) -> None:
        registry = RuntimeDataEligibilityRegistry.empty()
        self.assertTrue(registry.is_empty)
        registry.require_eligible(())

        pending = runtime_probe(live_conformance_observed=False, pending_reason="market_closed").evaluate()
        self.assertEqual(pending.status, "pending")
        updated = registry.register(pending)
        updated.require_eligible(())
        with self.assertRaisesRegex(RuntimeDataError, "pending"):
            updated.require_eligible((pending.source_id,))

    def test_historical_only_source_is_ineligible_and_live_equivalent_source_passes(self) -> None:
        historical = runtime_probe(live_access=False).evaluate()
        eligible = runtime_probe().evaluate()

        self.assertEqual(historical.status, "ineligible")
        self.assertIn("historical_only", historical.reason_codes)
        self.assertEqual(eligible.status, "eligible")
        registry = RuntimeDataEligibilityRegistry.empty().register(eligible)
        registry.require_eligible((eligible.source_id,))
        self.assertIs(registry.register(eligible), registry)

    def test_fixed_lot_is_mandatory_early_and_dynamic_sizing_cannot_rescue(self) -> None:
        fixed = SizingDescriptor("V2SZ9001", "fixed_lot", False)
        dynamic = SizingDescriptor("V2SZ9002", "dynamic_equity", False)
        risk = PortfolioRiskDescriptor("V2PR9001", False, frozenset())
        validate_sizing_gate(fixed, risk, SizingGateContext("S"))
        with self.assertRaisesRegex(RuntimeDataError, "forbidden"):
            validate_sizing_gate(dynamic, risk, SizingGateContext("S"))
        with self.assertRaisesRegex(RuntimeDataError, "cannot rescue"):
            validate_sizing_gate(
                dynamic,
                risk,
                SizingGateContext(
                    "R_sizing",
                    fixed_lot_candidate_quality_passed=True,
                    fixed_lot_economics_passed=False,
                ),
            )

    def test_dynamic_sizing_requires_full_risk_accounting_and_freeze_before_p(self) -> None:
        dynamic = SizingDescriptor("V2SZ9002", "dynamic_equity", True)
        risk = PortfolioRiskDescriptor(
            "V2PR9001",
            True,
            REQUIRED_RISK_ACCOUNTING,
        )
        validate_sizing_gate(
            dynamic,
            risk,
            SizingGateContext(
                "P",
                fixed_lot_candidate_quality_passed=True,
                fixed_lot_economics_passed=True,
            ),
        )
        with self.assertRaisesRegex(RuntimeDataError, "missing risk accounting"):
            validate_sizing_gate(
                dynamic,
                PortfolioRiskDescriptor("V2PR9002", True, frozenset()),
                SizingGateContext(
                    "R_sizing",
                    fixed_lot_candidate_quality_passed=True,
                    fixed_lot_economics_passed=True,
                ),
            )

    def test_r_p_m_guards_require_stage_specific_complete_receipts(self) -> None:
        bundle = "9" * 64
        validate_stage_entry(
            "R",
            {
                "stage": "S",
                "outcome": "route_to_R",
                "gate_passed": True,
                "trial_accounting_complete": True,
                "sizing_mode": "fixed_lot",
                "program_bundle_sha256": bundle,
            },
        )
        validate_stage_entry(
            "P",
            {
                "stage": "R",
                "outcome": "research_candidate_confirmed",
                "candidate_identity_frozen": True,
                "trial_accounting_complete": True,
                "minimum_mt5_confirmation_passed": True,
                "git_checkpoint_verified": True,
                "program_bundle_sha256": bundle,
            },
        )
        validate_stage_entry(
            "M",
            {
                "stage": "P",
                "outcome": "selected",
                "candidate_identity_frozen": True,
                "isolated_nine_fold_mt5_passed": True,
                "sealed_holdout_receipt": True,
                "sizing_and_risk_frozen": True,
                "git_checkpoint_verified": True,
                "program_bundle_sha256": bundle,
            },
        )
        with self.assertRaisesRegex(AutonomyGuardError, "P entry evidence"):
            validate_stage_entry("P", {"stage": "R", "program_bundle_sha256": bundle})


class ReadyBoundaryWriterTests(unittest.TestCase):
    def ready_writer(self, root: Path):
        state = v21_state()
        state["cursor"]["next_action"] = make_next_action(
            "await_new_root_goal",
            summary="await future root",
        )
        writer = build_writer(root, state)
        return writer, writer.complete_reinforcement_ready(
            baseline_commit="a" * 40,
            mission_contract_sha256="b" * 64,
            idempotency_key="ready",
        )

    def test_ready_boundary_is_empty_and_waits_for_another_goal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            writer, state = self.ready_writer(Path(temporary))
            self.assertEqual(state["harness"]["status"], "ready")
            self.assertFalse(state["harness"]["real_research_started"])
            self.assertEqual(state["scientific"]["status"], "not_started")
            self.assertEqual(state["scientific"]["hypothesis_object_ids"], [])
            self.assertEqual(state["cursor"]["next_action"]["kind"], "await_new_root_goal")
            self.assertEqual(writer.hypotheses.rows(), [])

    def test_future_goal_requires_result_independent_emergency_ceiling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            writer, _state = self.ready_writer(Path(temporary))
            with self.assertRaisesRegex(OperationStateError, "mission-open policy"):
                writer.create_goal(goal_payload={}, idempotency_key="invalid")
            state = writer.create_goal(
                goal_payload={
                    "scientific_mission": {
                        "scientific_origin": "v2_current",
                        "epoch_id": "V2EPOCH0001",
                        "emergency_hypothesis_ceiling": 24,
                        "result_independent": True,
                    }
                },
                idempotency_key="valid",
            )
            self.assertEqual(state["scientific"]["status"], "active")
            self.assertEqual(state["mission_budget"]["limits"]["hypothesis_batches"], 24)
            self.assertEqual(state["cursor"]["goal_status"], "created")
            self.assertEqual(state["cursor"]["next_action"]["kind"], "open_goal")

    def test_future_writer_preregisters_one_full_bound_scientific_spec(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            writer, _state = self.ready_writer(root)
            writer.create_goal(
                goal_payload={
                    "scientific_mission": {
                        "scientific_origin": "v2_current",
                        "epoch_id": "V2EPOCH0001",
                        "emergency_hypothesis_ceiling": 24,
                        "result_independent": True,
                    }
                },
                idempotency_key="goal",
            )
            writer.open_goal(goal_id="V2G0001", idempotency_key="open")
            payload = v22_hypothesis_payload("V2G0001", "V2H0001")
            relative = Path("campaigns/v2/V2G0001/hypotheses/V2H0001.yaml")
            path = root / relative
            path.parent.mkdir(parents=True)
            raw = yaml.safe_dump(payload, sort_keys=False).encode("ascii")
            path.write_bytes(raw)
            state = writer.preregister_hypothesis(
                hypothesis_id="V2H0001",
                spec_path=relative.as_posix(),
                spec_sha256=hashlib.sha256(raw).hexdigest(),
                spec_payload=payload,
                split_set_id="V2SP0001",
                material_ids=[],
                idempotency_key="full_h",
            )
            object_id = state["claim"]["identity_bundle_object_id"]
            self.assertEqual(state["cursor"]["stage"], "H")
            self.assertEqual([object_id], state["scientific"]["hypothesis_object_ids"])
            self.assertEqual("hypothesis_spec", writer.objects.get(object_id)["kind"])
            self.assertEqual(1, len(writer.hypotheses.rows()))
            replay = writer.preregister_hypothesis(
                hypothesis_id="V2H0001",
                spec_path=relative.as_posix(),
                spec_sha256=hashlib.sha256(raw).hexdigest(),
                spec_payload=payload,
                split_set_id="V2SP0001",
                material_ids=[],
                idempotency_key="full_h",
            )
            self.assertEqual(state["revision"], replay["revision"])
            self.assertEqual(1, len(writer.hypotheses.rows()))

    def test_future_writer_rejects_incomplete_batch_only_preregistration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            writer, _state = self.ready_writer(Path(temporary))
            writer.create_goal(
                goal_payload={
                    "scientific_mission": {
                        "scientific_origin": "v2_current",
                        "epoch_id": "V2EPOCH0001",
                        "emergency_hypothesis_ceiling": 24,
                        "result_independent": True,
                    }
                },
                idempotency_key="goal",
            )
            writer.open_goal(goal_id="V2G0001", idempotency_key="open")
            batch = HypothesisBatch(
                hypothesis_id="V2H0001",
                family_id="synthetic_family",
                hypothesis_type="structural_batch",
                dominant_axis="axis_feature",
                scientific_epoch_id="V2EPOCH0001",
                scout_mode="s_breadth",
                bundle_roles={
                    "control": "1" * 64,
                    "variant_a": "2" * 64,
                    "variant_b": "3" * 64,
                },
                semantic_signature_sha256="4" * 64,
            )
            before = writer.control.load()
            with self.assertRaisesRegex(OperationStateError, "batch-only"):
                writer.preregister_autonomous_hypothesis(
                    batch_payload=batch.to_payload(),
                    idempotency_key="batch",
                )
            after = writer.control.load()
            self.assertEqual(before["revision"], after["revision"])
            self.assertEqual([], writer.hypotheses.rows())
            self.assertEqual([], after["scientific"]["hypothesis_object_ids"])


if __name__ == "__main__":
    unittest.main()
