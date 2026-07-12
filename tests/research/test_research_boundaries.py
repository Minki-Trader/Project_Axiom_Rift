from __future__ import annotations

import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from axiom_rift.core.identity import canonical_digest
from axiom_rift.research import (
    BatchSpec,
    CandidateBinding,
    DecisionOption,
    InferenceDependency,
    InferenceDependencyKind,
    MaterialReference,
    MissionResearchIntake,
    NegativeMemory,
    PortfolioAction,
    PortfolioAxis as _PortfolioAxis,
    PortfolioDecision,
    PortfolioDecisionError,
    PortfolioSnapshot,
    REQUIRED_INTAKE_SURFACES,
    ResearchGovernanceError,
    ResearchLayer,
    RuntimeObservation,
    RuntimeObservationState,
    SleeveDependencySpec,
    SourceAction,
    SourceContract,
    SourceContractError,
    SourceEligibility,
    SourceEligibilityError,
    SourceEligibilityState,
    SourceType,
    TrialAccountant,
    TrialAccountingError,
    bind_candidate_source,
    evaluate_sleeves,
    recertify_source,
)


def PortfolioAxis(
    *,
    axis_id: str,
    causal_question: str,
    mechanism_family: str,
    status: str = "open",
) -> _PortfolioAxis:
    token = axis_id.rsplit("-", 1)[-1]
    slot = {"a": 0, "b": 1, "c": 2, "0": 0, "1": 1, "2": 2}.get(
        token, 0
    )
    layer = (
        ResearchLayer.FEATURE,
        ResearchLayer.LABEL,
        ResearchLayer.LIFECYCLE,
    )[slot]
    controlled = tuple(
        candidate
        for candidate in (
            ResearchLayer.FEATURE,
            ResearchLayer.LABEL,
            ResearchLayer.MODEL,
            ResearchLayer.TRADE,
            ResearchLayer.LIFECYCLE,
            ResearchLayer.EXECUTION,
        )
        if candidate != layer
    )
    return _PortfolioAxis(
        axis_id=axis_id,
        causal_question=causal_question,
        mechanism_family=mechanism_family,
        primary_research_layer=layer,
        system_architecture_family=(
            "architecture-family:fixture-baseline"
            if slot < 2
            else "architecture-family:fixture-alternate"
        ),
        changed_domains=(layer,),
        controlled_domains=controlled,
        why_now="fixture requires a causally distinct research axis",
        stop_or_reopen_condition="stop at the frozen fixture evidence boundary",
        status=status,
    )


def make_contract(
    *,
    display_name: str = "external index",
    runtime_identifier: str = "EXT.A",
    mapping_version: str = "one",
) -> SourceContract:
    return SourceContract(
        display_name=display_name,
        canonical_instrument="canonical-index",
        runtime_identifier=runtime_identifier,
        source_type=SourceType.BAR,
        instrument_semantics={
            "asset_type": "cash_index",
            "contract_size": "one",
            "currency": "USD",
            "digits": 2,
            "point": "0.01",
            "quote_basis": "bid",
            "session": "declared-session",
            "timezone": "UTC",
            "adjustment": "none",
            "roll": "none",
        },
        mapping_semantics={
            "runtime_symbol": runtime_identifier,
            "mapping_rule": mapping_version,
        },
        schema_semantics={
            "columns": ["time", "open", "high", "low", "close"],
            "schema_revision": "fixture-one",
        },
        field_semantics={
            "bar_open": "open",
            "bar_close": "close",
            "event_time": "bar_open_time",
            "information_complete_at": "bar_close_time",
            "first_available_at": "first_local_observation",
        },
        clock_semantics={
            "decision_alignment": "completed_m5_bar",
            "timezone_conversion": "server_to_utc_declared",
        },
        availability_semantics={
            "acquisition": "local_fixture_connector",
            "content_hash": "sha256",
            "coverage": "declared_fixture_window",
            "gap_policy": "fail_closed",
            "revision_or_vintage": "immutable_fixture",
            "causal_ttl_seconds": 60,
            "runtime_retrieval_method": "local_fixture_poll",
        },
    )


def make_runtime_eligible(
    contract: SourceContract,
) -> SourceEligibility:
    return (
        SourceEligibility.register(contract)
        .complete_historical_audit("receipt-historical")
        .prove_runtime_availability("receipt-runtime")
    )


def make_observation(
    contract: SourceContract,
    *,
    dependency_id: str = "dep-external",
    state: RuntimeObservationState = RuntimeObservationState.FRESH,
) -> tuple[RuntimeObservation, datetime]:
    decision_time = datetime(2040, 1, 1, 12, 0, tzinfo=timezone.utc)
    observation = RuntimeObservation(
        dependency_id=dependency_id,
        source_contract_id=contract.source_contract_id,
        state=state,
        information_complete_at=decision_time - timedelta(seconds=30),
        first_available_at=decision_time - timedelta(seconds=20),
        observed_at=decision_time - timedelta(seconds=5),
        ttl_seconds=60,
        mapping_identity=contract.mapping_identity,
        schema_identity=contract.schema_identity,
        field_identity=contract.field_identity,
        clock_identity=contract.clock_identity,
    )
    return observation, decision_time


def make_batch(
    *,
    batch_id: str = "BAT-1",
    study_id: str = "STU-1",
    study_hash: str = "a" * 64,
    display_name: str = "wide adaptive batch",
) -> BatchSpec:
    return BatchSpec(
        batch_id=batch_id,
        study_id=study_id,
        study_hash=study_hash,
        display_name=display_name,
        max_trials=1_000_000,
        max_compute_seconds=20_000_000,
        max_wall_seconds=30_000_000,
        stop_rule="stop at frozen budget or decisive evidence",
        acceptance_profile={"causality": "required", "unknown_cost": "reject"},
        adaptive_basis={
            "uncertainty": "high",
            "causal_complexity": "high",
            "surface_curvature": "unknown",
            "compute_cost": "bounded",
            "expected_information_value": "positive",
            "portfolio_opportunity_cost": "recorded",
        },
    )


class SourceEligibilityTests(unittest.TestCase):
    def test_empty_source_semantics_cannot_enter_eligibility(self) -> None:
        with self.assertRaises(SourceContractError):
            SourceContract(
                display_name="empty source",
                canonical_instrument="empty",
                runtime_identifier="EMPTY",
                source_type=SourceType.BAR,
                instrument_semantics={},
                mapping_semantics={},
                schema_semantics={},
                field_semantics={},
                clock_semantics={},
                availability_semantics={},
            )

    def test_exact_state_permissions_and_transitions(self) -> None:
        source = SourceEligibility.register(make_contract())
        self.assertTrue(source.allows(SourceAction.QUALITATIVE_CONTEXT))
        self.assertFalse(source.allows(SourceAction.PERFORMANCE_BATCH))
        with self.assertRaises(SourceEligibilityError):
            source.require(SourceAction.PERFORMANCE_BATCH)
        with self.assertRaises(SourceContractError):
            source.prove_runtime_availability("receipt-too-early")

        historical = source.complete_historical_audit("receipt-historical")
        eligible = historical.prove_runtime_availability("receipt-runtime")
        self.assertEqual(eligible.state, SourceEligibilityState.RUNTIME_ELIGIBLE)
        self.assertTrue(eligible.allows(SourceAction.ISSUE_SOURCE_PERMIT))
        suspended = eligible.suspend(receipt_id="receipt-drift", reason="mapping drift")
        self.assertEqual(suspended.state, SourceEligibilityState.SUSPENDED)
        self.assertFalse(suspended.allows(SourceAction.PERFORMANCE_BATCH))
        self.assertFalse(suspended.alpha_failure)
        self.assertEqual(suspended.scientific_trial_delta, 0)

    def test_candidate_binding_is_separate_and_current_receipt_bound(self) -> None:
        eligible = make_runtime_eligible(make_contract())
        binding = bind_candidate_source(
            executable_id="executable:fixture",
            eligibility=eligible,
            eligibility_receipt_id="receipt-runtime",
            runtime_identity="runtime:fixture",
        )
        self.assertIsInstance(binding, CandidateBinding)
        self.assertEqual(
            binding.source_contract_id,
            eligible.contract.source_contract_id,
        )
        self.assertNotIn(eligible.state.value, binding.identity)
        with self.assertRaises(SourceEligibilityError):
            bind_candidate_source(
                executable_id="executable:fixture",
                eligibility=eligible,
                eligibility_receipt_id="receipt-old",
                runtime_identity="runtime:fixture",
            )

    def test_recertification_preserves_or_changes_identity_by_semantics(self) -> None:
        contract = make_contract()
        suspended = make_runtime_eligible(contract).suspend(
            receipt_id="receipt-drift",
            reason="broker build changed",
        )
        renamed_same_semantics = make_contract(display_name="renamed external")
        same = recertify_source(
            suspended,
            proposed_contract=renamed_same_semantics,
            receipt_id="receipt-recertified",
        )
        self.assertTrue(same.identity_preserved)
        self.assertEqual(same.scientific_trial_delta, 0)
        self.assertEqual(
            same.eligibility.state,
            SourceEligibilityState.RUNTIME_ELIGIBLE,
        )
        self.assertEqual(
            same.source_contract_id,
            contract.source_contract_id,
        )

        changed = recertify_source(
            suspended,
            proposed_contract=make_contract(mapping_version="two"),
            receipt_id="receipt-semantic-change",
        )
        self.assertFalse(changed.identity_preserved)
        self.assertNotEqual(changed.source_contract_id, contract.source_contract_id)
        self.assertEqual(changed.scientific_trial_delta, 0)
        self.assertTrue(changed.next_performance_experiment_counts)
        self.assertEqual(
            changed.eligibility.state,
            SourceEligibilityState.CONTEXT_ONLY,
        )


class RuntimeDependencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = make_contract()
        self.eligibility = make_runtime_eligible(self.contract)
        self.dependency = InferenceDependency(
            dependency_id="dep-external",
            kind=InferenceDependencyKind.ROUTER,
            source_contract_id=self.contract.source_contract_id,
        )

    def test_causal_fresh_parity_path_is_operable(self) -> None:
        observation, decision_time = make_observation(self.contract)
        result = evaluate_sleeves(
            sleeves=(SleeveDependencySpec(sleeve_id="dependent", dependency_ids=("dep-external",)),),
            dependencies={"dep-external": self.dependency},
            eligibilities={self.contract.source_contract_id: self.eligibility},
            observations={"dep-external": observation},
            decision_time=decision_time,
        )
        self.assertTrue(result["dependent"].operable)

    def test_late_stale_and_field_mapping_mismatch_fail_closed(self) -> None:
        observation, decision_time = make_observation(self.contract)
        with self.assertRaises(ValueError):
            replace(observation, observed_at=datetime(2040, 1, 1, 11, 59))
        invalid = replace(
            observation,
            state=RuntimeObservationState.STALE,
            first_available_at=decision_time + timedelta(seconds=1),
            mapping_identity="mapping:changed",
            field_identity="fields:changed",
        )
        result = evaluate_sleeves(
            sleeves=(
                SleeveDependencySpec(
                    sleeve_id="dependent",
                    dependency_ids=("dep-external",),
                ),
                SleeveDependencySpec(sleeve_id="independent"),
            ),
            dependencies={"dep-external": self.dependency},
            eligibilities={self.contract.source_contract_id: self.eligibility},
            observations={"dep-external": invalid},
            decision_time=decision_time,
        )
        dependent = result["dependent"]
        self.assertFalse(dependent.operable)
        self.assertTrue(dependent.assessments[0].requires_suspension)
        self.assertFalse(dependent.assessments[0].alpha_failure)
        self.assertIn(
            "causal_availability_invalid",
            dependent.assessments[0].reason_codes,
        )
        self.assertTrue(result["independent"].operable)

    def test_all_position_intent_dependency_kinds_are_explicit(self) -> None:
        self.assertEqual(
            {kind.value for kind in InferenceDependencyKind},
            {
                "feature",
                "regime",
                "selector",
                "router",
                "risk",
                "sizing",
                "trade",
                "lifecycle",
                "other_position_intent",
            },
        )
        self.assertEqual(RuntimeObservationState.CLOSED.value, "source_market_closed")


class PortfolioBoundaryTests(unittest.TestCase):
    def test_contract_routes_intake_diagnosis_and_architecture_review(self) -> None:
        root = Path(__file__).resolve().parents[2]
        operations = yaml.safe_load(
            (root / "contracts" / "operations.yaml").read_text(encoding="ascii")
        )
        science = yaml.safe_load(
            (root / "contracts" / "science.yaml").read_text(encoding="ascii")
        )
        evidence = yaml.safe_load(
            (root / "contracts" / "evidence.yaml").read_text(encoding="ascii")
        )
        self.assertEqual(
            operations["research_direction"]["study_close_order"],
            [
                "study_closed",
                "local_main_checkpoint_and_initial_push_attempt",
                "study_diagnosis_recorded",
                "optional_architecture_review_recorded",
                "portfolio_decision",
            ],
        )
        self.assertTrue(
            science["research_direction"]["mission_intake"][
                "required_before_first_initiative"
            ]
        )
        self.assertIn(
            "system_architecture_family_diversity",
            science["research_direction"]["exhaustion_requires"],
        )
        self.assertFalse(
            evidence["research_interpretation"]["architecture_review"][
                "scientific_evidence"
            ]
        )

    def test_research_intake_and_axis_layers_are_typed(self) -> None:
        with self.assertRaises(ResearchGovernanceError):
            MissionResearchIntake(
                mission_id="MIS-TYPED",
                history_head_sequence=1,
                history_head_event_id="a" * 64,
                reviewed_surfaces=tuple(
                    sorted(REQUIRED_INTAKE_SURFACES - {"validator_evidence"})
                ),
                mission_thesis="test typed intake",
                architecture_findings=("one finding",),
                bottleneck_hypotheses=("first hypothesis", "second hypothesis"),
                underexplored_layers=(ResearchLayer.LABEL,),
                legacy_limitations="none",
            )
        with self.assertRaises(PortfolioDecisionError):
            _PortfolioAxis(
                axis_id="axis-hidden-multi-layer",
                causal_question="Does a hidden multi-layer change remain identifiable?",
                mechanism_family="hidden-multi-layer",
                primary_research_layer=ResearchLayer.FEATURE,
                system_architecture_family="architecture-family:typed-fixture",
                changed_domains=(ResearchLayer.FEATURE, ResearchLayer.LABEL),
                controlled_domains=(ResearchLayer.MODEL,),
                why_now="test one-layer enforcement",
                stop_or_reopen_condition="stop when construction rejects",
            )

    def test_batch_is_frozen_and_has_no_global_tiny_cap(self) -> None:
        batch = make_batch()
        self.assertEqual(batch.max_trials, 1_000_000)
        with self.assertRaises(FrozenInstanceError):
            batch.max_trials = 2  # type: ignore[misc]

    def test_batch_handles_and_names_cannot_reset_semantic_identity(self) -> None:
        original = make_batch()
        renamed = make_batch(
            batch_id="BAT-RENAMED",
            study_id="STU-RENAMED-HANDLE",
            display_name="renamed display only",
        )
        self.assertEqual(original.identity, renamed.identity)
        different_study = make_batch(study_hash="b" * 64)
        self.assertNotEqual(original.identity, different_study.identity)

    def test_recent_positive_requires_bounded_non_monopoly_comparison(self) -> None:
        deepen = DecisionOption(
            option_id="deepen-positive",
            action=PortfolioAction.DEEPEN,
            target_id="lineage-positive",
            expected_information_value="high",
            opportunity_cost="one contrast deferred",
        )
        rotate = DecisionOption(
            option_id="rotate-axis",
            action=PortfolioAction.ROTATE,
            target_id="new-axis",
            expected_information_value="medium",
            opportunity_cost="delays confirmation",
            omission_reason="bounded confirmation has higher immediate value",
        )
        decision = PortfolioDecision(
            decision_id="DEC-1",
            chosen_option_id="deepen-positive",
            options=(deepen, rotate),
            rationale="bounded confirmation while preserving a divergent axis",
            commitment_batches=3,
            recent_positive_lineage_id="lineage-positive",
        )
        self.assertEqual(decision.chosen, deepen)

        with self.assertRaises(PortfolioDecisionError):
            PortfolioDecision(
                decision_id="DEC-monopoly",
                chosen_option_id="deepen-positive",
                options=(deepen,),
                rationale="recent result alone",
                commitment_batches=3,
                recent_positive_lineage_id="lineage-positive",
            )
        adjacent = DecisionOption(
            option_id="deepen-adjacent",
            action=PortfolioAction.DEEPEN,
            target_id="same-lineage-other-executable",
            expected_information_value="medium",
            opportunity_cost="another adjacent fit",
            omission_reason="chosen neighbor has slightly higher immediate value",
        )
        with self.assertRaises(PortfolioDecisionError):
            PortfolioDecision(
                decision_id="DEC-adjacent-monopoly",
                chosen_option_id="deepen-positive",
                options=(deepen, adjacent),
                rationale="two adjacent Executables are not structural diversification",
                commitment_batches=1_000_000,
                recent_positive_lineage_id="lineage-positive",
            )
        with self.assertRaises(PortfolioDecisionError):
            PortfolioDecision(
                decision_id="DEC-hidden-monopoly",
                chosen_option_id="deepen-positive",
                options=(deepen,),
                rationale="caller omitted the recent-positive flag",
                commitment_batches=3,
            )
        with self.assertRaises(PortfolioDecisionError):
            PortfolioDecision(
                decision_id="DEC-unbounded",
                chosen_option_id="deepen-positive",
                options=(deepen, rotate),
                rationale="unbounded",
                commitment_batches=None,
                recent_positive_lineage_id="lineage-positive",
            )

    def test_set_like_portfolio_and_negative_memory_identity_is_order_stable(self) -> None:
        axis_a = PortfolioAxis(
            axis_id="axis-a",
            causal_question="Does A carry distinct information?",
            mechanism_family="family-a",
        )
        axis_b = PortfolioAxis(
            axis_id="axis-b",
            causal_question="Does B carry distinct information?",
            mechanism_family="family-b",
        )
        first_snapshot = PortfolioSnapshot(
            mission_id="MIS-ORDER",
            axes=(axis_b, axis_a),
            opportunity_cost_basis="compare independent axes",
        )
        second_snapshot = PortfolioSnapshot(
            mission_id="MIS-ORDER",
            axes=(axis_a, axis_b),
            opportunity_cost_basis="compare independent axes",
        )
        self.assertEqual(first_snapshot.identity, second_snapshot.identity)

        option_a = DecisionOption(
            option_id="option-a",
            action=PortfolioAction.DEEPEN,
            target_id="axis-a",
            expected_information_value="high",
            opportunity_cost="bounded",
        )
        option_b = DecisionOption(
            option_id="option-b",
            action=PortfolioAction.CONTRAST,
            target_id="axis-b",
            expected_information_value="moderate",
            opportunity_cost="one Batch",
            omission_reason="option A is chosen for this commitment",
        )
        first_decision = PortfolioDecision(
            decision_id="DEC-ORDER",
            chosen_option_id="option-a",
            options=(option_b, option_a),
            rationale="order must not manufacture a new Decision",
            commitment_batches=1,
        )
        second_decision = PortfolioDecision(
            decision_id="DEC-ORDER",
            chosen_option_id="option-a",
            options=(option_a, option_b),
            rationale="order must not manufacture a new Decision",
            commitment_batches=1,
        )
        self.assertEqual(first_decision.identity, second_decision.identity)

        executable_id = "executable:" + "a" * 64
        memory_a = NegativeMemory(
            executable_identity=executable_id,
            scope="axis-a",
            evidence_references=("completion-b", "completion-a"),
            reason="falsified",
            reopen_condition="new information",
        )
        memory_b = NegativeMemory(
            executable_identity=executable_id,
            scope="axis-a",
            evidence_references=("completion-a", "completion-b"),
            reason="falsified",
            reopen_condition="new information",
        )
        self.assertEqual(memory_a.identity, memory_b.identity)

    def test_exhaustion_standard_rejects_a_few_shallow_failures(self) -> None:
        axes = tuple(
            PortfolioAxis(
                axis_id=f"axis-{index}",
                causal_question=f"Does axis {index} carry information?",
                mechanism_family=f"family-{index}",
            )
            for index in range(3)
        )
        shallow = {
            "minimum_axes": 3,
            "minimum_distinct_studies_per_axis": 1,
            "minimum_mechanism_families": 3,
            "minimum_negative_executables_per_family": 1,
            "required_evidence_modes": ["causal_contrast"],
            "stop_basis": "stop after a few failures",
        }
        with self.assertRaises(PortfolioDecisionError):
            PortfolioSnapshot(
                mission_id="MIS-SHALLOW",
                axes=axes,
                opportunity_cost_basis="shallow terminal must fail closed",
                exhaustion_standard=shallow,
            )


class TrialAccountantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.observed_identity = canonical_digest(
            domain="test-development-material", payload={"fixture": "observed"}
        )
        foundation = root / "foundation"
        foundation.mkdir()
        (foundation / "data_exposure.yaml").write_text(
            yaml.safe_dump(
                {
                    "observed_development_material": {
                        "identity": self.observed_identity,
                        "identity_domain": "test-development-material",
                        "identity_inputs": {"fixture": "observed"},
                        "display_name": "old dataset label",
                        "prior_global_multiplicity_floor": 18,
                    },
                },
                sort_keys=True,
            ),
            encoding="ascii",
        )
        (foundation / "prior_scientific_memory.yaml").write_text(
            yaml.safe_dump(
                {
                    "scheduler_weight": "none",
                    "reuse_rule": "explicit_identity_equivalence_required",
                    "warnings": [
                        {
                            "warning_id": "WARN-1",
                            "semantic_key": "breakout",
                            "mechanism": "breakout",
                            "disposition": "shallow_negative",
                            "reopen_condition": "new causal mechanism",
                        },
                        {
                            "warning_id": "WARN-2",
                            "semantic_key": "mean-reversion",
                            "mechanism": "mean-reversion",
                            "disposition": "evidence_gap",
                        },
                    ],
                },
                sort_keys=True,
            ),
            encoding="ascii",
        )
        self.accountant = TrialAccountant.from_foundation(root)

    def test_same_material_floor_ignores_display_name(self) -> None:
        renamed = MaterialReference(
            identity=self.observed_identity,
            display_name="completely different display label",
        )
        context = self.accountant.open_study(
            material=renamed,
            semantic_proposal={"mechanism": "breakout"},
        )
        self.assertEqual(context.prior_global_multiplicity, 18)
        self.assertEqual(
            tuple(w.warning_id for w in context.semantic_warnings),
            ("WARN-1",),
        )
        self.assertEqual(context.warning_scheduler_weight, "none")

        different = MaterialReference(
            identity="material:new",
            display_name="old dataset label",
        )
        self.assertEqual(self.accountant.prior_global_multiplicity(different), 0)
        with self.assertRaises(TrialAccountingError):
            self.accountant.open_study(material=different)

    def test_negative_reuse_has_no_caller_forgeable_authority(self) -> None:
        self.assertFalse(hasattr(self.accountant, "authorize_negative_reuse"))

    def test_unique_trial_counts_above_manifest_floor_and_success_reuses(self) -> None:
        material = MaterialReference(
            identity=self.observed_identity,
            display_name="renamed",
        )
        first = self.accountant.account_trial(
            material=material,
            executable_identity="executable:first",
            result="success",
        )
        self.assertEqual(first.trial_delta, 1)
        self.assertEqual(first.global_multiplicity, 19)
        cached = self.accountant.account_trial(
            material=material,
            executable_identity="executable:first",
            result="success",
        )
        self.assertEqual(cached.trial_delta, 0)
        self.assertEqual(cached.global_multiplicity, 19)

    def test_manifest_cannot_give_warnings_scheduler_weight(self) -> None:
        with self.assertRaises(TrialAccountingError):
            TrialAccountant(
                observed_material_identity="material:observed",
                prior_global_multiplicity_floor=18,
                warnings=(),
                scheduler_weight="positive",
                reuse_rule="explicit_identity_equivalence_required",
            )


if __name__ == "__main__":
    unittest.main()
