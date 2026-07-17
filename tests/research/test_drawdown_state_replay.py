from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import pandas as pd

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
import axiom_rift.operations.writer as writer_module
from axiom_rift.operations.running_job import (
    RunningJobExecution as BoundaryRunningJobExecution,
    running_job_authority_dependency_paths,
)
from axiom_rift.research.drawdown_fixed_hold import (
    DRAWDOWN_FIXED_HOLD_HISTORICAL_EVALUATION_HASHES,
    causal_drawdown_fixed_hold_spread,
    compute_drawdown_fixed_hold_family_trace,
    compute_drawdown_fixed_hold_score,
    drawdown_fixed_hold_components,
    drawdown_fixed_hold_controlled_chassis,
    drawdown_fixed_hold_executable_map,
    drawdown_fixed_hold_protocol_definition,
)
from axiom_rift.research.fixed_hold_historical_projection import (
    HISTORICAL_DRAWDOWN_EVALUATION_SCHEMA,
    project_historical_drawdown_evaluation,
)
from axiom_rift.research.drawdown_state_replay_job import (
    CALLABLE_IDENTITY,
    RUNTIME_ADAPTER,
    build_drawdown_replay_job_plan,
    drawdown_replay_job_implementation_artifact,
    drawdown_replay_job_implementation_sha256,
    materialize_drawdown_replay_job_implementation,
)
from axiom_rift.operations.writer import (
    RunningJobExecution,
    StateWriter,
)
from axiom_rift.research.evidence_proofs import (
    build_proof_references,
    parse_proof_references,
    parse_proof_requirements,
    validate_proof_artifacts,
)
from axiom_rift.research.fixed_hold_family_job import (
    build_fixed_hold_measurement,
    build_fixed_hold_shared_trace_calculation,
)
from axiom_rift.research.fixed_hold_family_trace import (
    FIXED_HOLD_REPLAY_CRITERIA,
    FIXED_HOLD_REPLAY_EVIDENCE_MODES,
    FIXED_HOLD_TRACE_VALIDATOR,
    bind_fixed_hold_family_trace,
    build_fixed_hold_trace_calculation,
    validate_fixed_hold_family_trace,
)
from axiom_rift.research.fixed_hold_replay_runtime import (
    fixed_hold_replay_runtime_dependency_paths,
)
from axiom_rift.research.historical_family_replay import (
    STU0048_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyReplayContext,
    historical_family_from_manifest,
)
from axiom_rift.research.historical_semantic_transition import (
    build_historical_cost_timing_transition,
    validate_historical_cost_timing_transition,
)
from axiom_rift.research.scientific_trace import (
    DRAWDOWN_REPLAY_TRACE_PROTOCOL_ID,
    ScientificTraceError,
    trace_proof_kinds,
    validate_trace_calculation_pair,
)
from axiom_rift.research.validation_v2 import adjudicate_validation_measurement_v2
from axiom_rift.storage.evidence import EvidenceStore


HISTORICAL_CONTEXT_COUNT = 578
DRAWDOWN_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT = 440
STU0048_HISTORICAL_EVALUATION_HASHES = (
    DRAWDOWN_FIXED_HOLD_HISTORICAL_EVALUATION_HASHES
)
WRITER_BOUND_FAMILY = historical_family_from_manifest(
    STU0048_HISTORICAL_FAMILY.manifest()
)
FAMILY_AUTHORITY_ID = (
    "historical-family-authority:"
    "d166d3ac4dd728de2c7968021c806908836e6f5bf9a78049e0d033b214fd64ab"
)
REPLAY_OBLIGATION_ID = (
    "historical-replay-obligation:"
    "c537b4ebc7085331cd21e52c26fbc994728c0520d5474473cc246f4e8c85322e"
)


def _replay_context(count: int) -> HistoricalFamilyReplayContext:
    return HistoricalFamilyReplayContext(
        family_authority_id=FAMILY_AUTHORITY_ID,
        replay_obligation_id=REPLAY_OBLIGATION_ID,
        family=WRITER_BOUND_FAMILY,
        prior_global_exposure_count=count,
        original_family_end_global_exposure_count=(
            DRAWDOWN_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
        ),
    )


def drawdown_replay_protocol_definition(
    *, historical_context_prior_global_exposure_count: int
):
    return drawdown_fixed_hold_protocol_definition(
        _replay_context(historical_context_prior_global_exposure_count)
    )


def drawdown_replay_components():
    return drawdown_fixed_hold_components(WRITER_BOUND_FAMILY)


def drawdown_replay_controlled_chassis(
    *, historical_context_prior_global_exposure_count: int
):
    return drawdown_fixed_hold_controlled_chassis(
        historical_family=WRITER_BOUND_FAMILY,
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
        original_family_end_global_exposure_count=(
            DRAWDOWN_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
        ),
    )


def drawdown_replay_executable_map(
    *, historical_context_prior_global_exposure_count: int
):
    return drawdown_fixed_hold_executable_map(
        historical_family=WRITER_BOUND_FAMILY,
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        ),
        original_family_end_global_exposure_count=(
            DRAWDOWN_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
        ),
    )


def compute_stu0048_drawdown_family_trace(
    repository_root: str,
    *,
    historical_context_prior_global_exposure_count: int,
):
    definition = drawdown_replay_protocol_definition(
        historical_context_prior_global_exposure_count=(
            historical_context_prior_global_exposure_count
        )
    )
    return compute_drawdown_fixed_hold_family_trace(
        repository_root,
        definition,
    )


causal_drawdown_replay_spread = causal_drawdown_fixed_hold_spread
compute_drawdown_replay_score = compute_drawdown_fixed_hold_score
_FULL_TRACE_FIXTURE = None


def _full_trace_fixture():
    global _FULL_TRACE_FIXTURE
    if _FULL_TRACE_FIXTURE is None:
        definition = drawdown_replay_protocol_definition(
            historical_context_prior_global_exposure_count=(
                HISTORICAL_CONTEXT_COUNT
            )
        )
        neutral, raw = compute_stu0048_drawdown_family_trace(
            ".",
            historical_context_prior_global_exposure_count=(
                HISTORICAL_CONTEXT_COUNT
            ),
        )
        _FULL_TRACE_FIXTURE = (definition, neutral, raw)
    return _FULL_TRACE_FIXTURE


class DrawdownReplayBoundaryTests(unittest.TestCase):
    def test_unchanged_economic_relation_is_typed_instead_of_rejected(
        self,
    ) -> None:
        configuration_id, artifact_sha256 = next(
            iter(STU0048_HISTORICAL_EVALUATION_HASHES.items())
        )
        artifact = parse_canonical(
            EvidenceStore(Path("local/evidence")).read_verified(artifact_sha256)
        )
        assert isinstance(artifact, dict)
        historical_executable_id = str(artifact["subject_executable_id"])
        surfaces = project_historical_drawdown_evaluation(
            artifact,
            expected_configuration_id=configuration_id,
            expected_historical_executable_id=historical_executable_id,
        )
        transition = build_historical_cost_timing_transition(
            configuration_id=configuration_id,
            corrected_executable_id="executable:" + "1" * 64,
            historical_reference_executable_id=historical_executable_id,
            historical_artifact_sha256=artifact_sha256,
            historical_artifact_schema=HISTORICAL_DRAWDOWN_EVALUATION_SCHEMA,
            historical_evaluation_artifact=artifact,
            corrected_structural_surfaces=surfaces["structural"],
            corrected_economic_surfaces=surfaces["economic"],
        )
        self.assertEqual(transition["changed_economic_surfaces"], [])
        self.assertTrue(transition["unchanged_numeric_relation"])
        self.assertEqual(
            validate_historical_cost_timing_transition(
                transition,
                expected_configuration_id=configuration_id,
                expected_corrected_executable_id="executable:" + "1" * 64,
                expected_historical_reference_executable_id=historical_executable_id,
                expected_historical_artifact_sha256=artifact_sha256,
                expected_historical_artifact_schema=(
                    HISTORICAL_DRAWDOWN_EVALUATION_SCHEMA
                ),
                expected_corrected_structural_surfaces=surfaces["structural"],
                expected_corrected_economic_surfaces=surfaces["economic"],
            ),
            transition,
        )

    def test_runtime_closure_uses_the_narrow_running_job_authority(self) -> None:
        dependencies = set(
            fixed_hold_replay_runtime_dependency_paths(RUNTIME_ADAPTER)
        )
        self.assertNotIn(Path(writer_module.__file__).resolve(), dependencies)
        self.assertTrue(
            set(running_job_authority_dependency_paths()).issubset(
                dependencies
            )
        )
        self.assertIs(RunningJobExecution, BoundaryRunningJobExecution)
        closure = parse_canonical(
            drawdown_replay_job_implementation_artifact()
        )
        self.assertIsInstance(closure, dict)
        assert isinstance(closure, dict)
        bound_paths = {
            item["path"] for item in closure["dependencies"]
        }
        source_root = Path(__file__).resolve().parents[2] / "src"
        expected_boundary_paths = {
            path.relative_to(source_root).as_posix()
            for path in running_job_authority_dependency_paths()
        }
        self.assertTrue(expected_boundary_paths.issubset(bound_paths))
        self.assertNotIn("axiom_rift/operations/writer.py", bound_paths)

    def test_prospective_closure_is_reusable_current_job_authority(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            writer = StateWriter(
                temporary,
                engineering_fixture=True,
                foundation_root=Path(__file__).resolve().parents[2],
            )
            writer.initialize_ready()
            identity = materialize_drawdown_replay_job_implementation(writer)
            self.assertEqual(
                identity,
                drawdown_replay_job_implementation_sha256(),
            )
            manifest = parse_canonical(writer.evidence.read_verified(identity))
            accepted = writer._require_job_implementation_evidence(
                {
                    "callable_identity": CALLABLE_IDENTITY,
                    "implementation_identity": identity,
                }
            )
            self.assertIsInstance(manifest, dict)
            self.assertEqual(accepted, manifest)
        self.assertEqual(
            manifest["schema"],
            "job_implementation_evidence.v1",
        )
        expected_artifacts = {
            sha256(drawdown_replay_job_implementation_artifact()).hexdigest(),
            *(
                sha256(path.read_bytes()).hexdigest()
                for path in fixed_hold_replay_runtime_dependency_paths(
                    RUNTIME_ADAPTER
                )
            ),
        }
        self.assertEqual(set(manifest["artifact_hashes"]), expected_artifacts)
        dependency_names = {
            path.name
            for path in fixed_hold_replay_runtime_dependency_paths(
                RUNTIME_ADAPTER
            )
        }
        self.assertIn("drawdown_fixed_hold.py", dependency_names)
        self.assertIn("historical_family_binding.py", dependency_names)
        self.assertNotIn("historical_family_stu0048.py", dependency_names)
        self.assertNotIn("historical_family_replay.py", dependency_names)

    def test_family_identity_is_new_exact_and_context_bound(self) -> None:
        definition = drawdown_replay_protocol_definition(
            historical_context_prior_global_exposure_count=(
                HISTORICAL_CONTEXT_COUNT
            )
        )
        later = drawdown_replay_protocol_definition(
            historical_context_prior_global_exposure_count=(
                HISTORICAL_CONTEXT_COUNT + 1
            )
        )
        historical_ids = {
            member.historical_reference_executable_id
            for member in STU0048_HISTORICAL_FAMILY.members
        }
        self.assertEqual(len(definition.prospective_executable_ids), 4)
        self.assertEqual(len(set(definition.prospective_executable_ids)), 4)
        self.assertTrue(
            historical_ids.isdisjoint(definition.prospective_executable_ids)
        )
        self.assertTrue(
            set(definition.prospective_executable_ids).isdisjoint(
                later.prospective_executable_ids
            )
        )
        self.assertNotEqual(definition.family_id, later.family_id)
        self.assertEqual(
            definition.inference_family_id,
            later.inference_family_id,
        )
        self.assertEqual(
            definition.protocol_id,
            DRAWDOWN_REPLAY_TRACE_PROTOCOL_ID,
        )
        self.assertEqual(len(drawdown_replay_components()), 10)
        self.assertEqual(
            len(
                drawdown_replay_executable_map(
                    historical_context_prior_global_exposure_count=(
                        HISTORICAL_CONTEXT_COUNT
                    )
                )
            ),
            4,
        )
        with self.assertRaisesRegex(ValueError, "exposure is invalid"):
            drawdown_replay_protocol_definition(
                historical_context_prior_global_exposure_count=(
                    DRAWDOWN_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
                    - 1
                )
            )

    def test_feature_and_spread_are_causal_at_segment_boundaries(self) -> None:
        frame = pd.DataFrame(
            {
                "time": pd.date_range(
                    "2024-01-01",
                    periods=400,
                    freq="5min",
                ),
                "close": np.r_[
                    np.arange(1.0, 301.0),
                    np.linspace(299.0, 200.0, 100),
                ],
            }
        )
        depth, _, _ = compute_drawdown_replay_score(
            frame,
            "drawdown_depth_288",
        )
        duration, _, _ = compute_drawdown_replay_score(
            frame,
            "drawdown_duration_288",
        )
        self.assertEqual(depth[299], 0.0)
        self.assertLess(depth[-1], 0.0)
        self.assertEqual(duration[299], 0.0)
        self.assertLess(duration[-1], 0.0)

        five_minutes = 300_000_000_000
        time_ns = np.array(
            [0, five_minutes, 2 * five_minutes, 9 * five_minutes,
             10 * five_minutes],
            dtype=np.int64,
        )
        repaired = causal_drawdown_replay_spread(
            np.array([2.0, 0.0, 4.0, 0.0, 6.0]),
            time_ns,
        )
        self.assertTrue(np.isnan(repaired[3]))
        self.assertEqual(repaired[1], 2.0)
        self.assertEqual(repaired[4], 6.0)


class DrawdownSemanticTransitionIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.definition, cls.neutral, cls.raw = _full_trace_fixture()

    def test_atomic_projection_matches_independent_producer_aggregates(self) -> None:
        names = (
            "median_fold_profit_factor_milli",
            "monthly_realized_exit_drawdown_micropoints",
            "monthly_realized_exit_drawdown_share_of_gross_profit_ppm",
            "net_profit_micropoints",
            "stress_net_profit_micropoints",
            "trade_count",
        )
        for transition in self.neutral["semantic_transition_evidence"]:
            corrected = transition["corrected_economic_surfaces"]["metrics"]
            producer = self.raw[transition["corrected_executable_id"]]
            self.assertEqual(
                {name: corrected[name] for name in names},
                {name: producer[name] for name in names},
            )

    def test_transition_rejects_readdressed_historical_artifact(self) -> None:
        tampered = deepcopy(self.neutral)
        transition = tampered["semantic_transition_evidence"][0]
        artifact = transition["historical_evaluation_artifact"]
        artifact["metrics"]["net_profit_micropoints"] += 1
        transition["historical_artifact_sha256"] = sha256(
            canonical_bytes(artifact)
        ).hexdigest()
        with self.assertRaisesRegex(
            ScientificTraceError,
            "authority binding",
        ):
            validate_fixed_hold_family_trace(
                tampered,
                definition=self.definition,
                validator=FIXED_HOLD_TRACE_VALIDATOR,
            )

    def test_transition_rejects_self_consistent_corrected_surface_forgery(
        self,
    ) -> None:
        tampered = deepcopy(self.neutral)
        original = tampered["semantic_transition_evidence"][0]
        corrected_economic = deepcopy(original["corrected_economic_surfaces"])
        corrected_economic["metrics"]["net_profit_micropoints"] += 1
        tampered["semantic_transition_evidence"][0] = (
            build_historical_cost_timing_transition(
                configuration_id=original["configuration_id"],
                corrected_executable_id=original["corrected_executable_id"],
                historical_reference_executable_id=(
                    original["historical_reference_executable_id"]
                ),
                historical_artifact_sha256=original[
                    "historical_artifact_sha256"
                ],
                historical_artifact_schema=original[
                    "historical_artifact_schema"
                ],
                historical_evaluation_artifact=original[
                    "historical_evaluation_artifact"
                ],
                corrected_structural_surfaces=original[
                    "corrected_structural_surfaces"
                ],
                corrected_economic_surfaces=corrected_economic,
            )
        )
        with self.assertRaisesRegex(
            ScientificTraceError,
            "atomic-row projection",
        ):
            validate_fixed_hold_family_trace(
                tampered,
                definition=self.definition,
                validator=FIXED_HOLD_TRACE_VALIDATOR,
            )


class DrawdownReplayIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.definition, cls.neutral, cls.raw = _full_trace_fixture()
        cls.target_id = cls.definition.prospective_executable_ids[3]
        cls.job_plan = build_drawdown_replay_job_plan(
            mission_id="MIS-0006",
            study_id="STU-test",
            executable_id=cls.target_id,
            historical_context_prior_global_exposure_count=(
                HISTORICAL_CONTEXT_COUNT
            ),
            original_family_end_global_exposure_count=(
                DRAWDOWN_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
            ),
            historical_family=WRITER_BOUND_FAMILY,
            historical_family_authority_id=FAMILY_AUTHORITY_ID,
            replay_obligation_id=REPLAY_OBLIGATION_ID,
        )
        cls.subject = bind_fixed_hold_family_trace(
            family_trace=cls.neutral,
            definition=cls.definition,
            validator=FIXED_HOLD_TRACE_VALIDATOR,
            mission_id="MIS-0006",
            executable_id=cls.target_id,
            job_id="job:drawdown-integration-test",
            job_hash="1" * 64,
        )
        cls.trace_hash = sha256(canonical_bytes(cls.subject)).hexdigest()
        cls.calculation = build_fixed_hold_trace_calculation(
            trace=cls.subject,
            definition=cls.definition,
            validator=FIXED_HOLD_TRACE_VALIDATOR,
            trace_output_name=cls.job_plan.output_names["trace"],
            trace_hash=cls.trace_hash,
        )

    def test_factorial_chassis_uses_non_evaluated_anchor(self) -> None:
        chassis = drawdown_replay_controlled_chassis(
            historical_context_prior_global_exposure_count=(
                HISTORICAL_CONTEXT_COUNT
            )
        )
        baseline = chassis.baseline_executable
        parameters = baseline.parameter_values()
        self.assertEqual(
            parameters["configuration_id"],
            "comparison-anchor",
        )
        self.assertEqual(parameters["signal_sign"], 0)
        self.assertNotIn(
            baseline.identity,
            drawdown_replay_executable_map(
                historical_context_prior_global_exposure_count=(
                    HISTORICAL_CONTEXT_COUNT
                )
            ),
        )

    def test_full_atomic_replay_preserves_structure_and_corrects_cost_timing(
        self,
    ) -> None:
        self.assertEqual(len(self.neutral["ordered_family"]), 4)
        self.assertEqual(len(self.neutral["windows"]), 9)
        self.assertEqual(len(self.neutral["trade_observations"]), 7_874)
        self.assertEqual(len(self.neutral["intent_observations"]), 29_724)
        self.assertEqual(
            len(self.neutral["eligible_day_observations"]),
            2_320,
        )
        self.assertEqual(len(self.neutral["invariance_comparisons"]), 18)
        self.assertEqual(
            self.raw[self.target_id]["net_profit_micropoints"],
            7_314_010_000,
        )
        self.assertEqual(self.raw[self.target_id]["trade_count"], 1_915)
        self.assertEqual(self.raw[self.target_id]["winning_fold_count"], 7)
        trade = self.neutral["trade_observations"][0]
        self.assertEqual(trade["spread_semantics"], "completed_period_proxy")
        self.assertEqual(
            trade["decision_spread_source_bar_index"],
            trade["decision_bar_index"],
        )
        self.assertEqual(
            trade["entry_spread_source_bar_index"],
            trade["entry_bar_index"] - 1,
        )
        self.assertEqual(
            trade["exit_spread_source_bar_index"],
            trade["exit_bar_index"] - 1,
        )
        self.assertEqual(
            trade["entry_spread_information_complete_at"],
            trade["entry_time"],
        )
        self.assertEqual(
            trade["exit_spread_information_complete_at"],
            trade["exit_time"],
        )
        transitions = self.neutral["semantic_transition_evidence"]
        self.assertEqual(len(transitions), 4)
        self.assertEqual(
            [item["configuration_id"] for item in transitions],
            [
                item["configuration_id"]
                for item in self.neutral["ordered_family"]
            ],
        )
        for transition in transitions:
            self.assertIn("metrics", transition["changed_economic_surfaces"])
            self.assertFalse(transition["unchanged_numeric_relation"])
            self.assertEqual(len(transition["structural_digest"]), 64)
            self.assertEqual(
                len(transition["historical_economic_digest"]), 64
            )
            self.assertEqual(
                len(transition["corrected_economic_digest"]), 64
            )

        tampered = deepcopy(self.neutral)
        tampered["semantic_transition_evidence"][0][
            "changed_economic_surfaces"
        ] = []
        with self.assertRaisesRegex(
            ScientificTraceError,
            "relation or digest",
        ):
            validate_fixed_hold_family_trace(
                tampered,
                definition=self.definition,
                validator=FIXED_HOLD_TRACE_VALIDATOR,
            )

    def test_exact_family_and_control_inference_replaces_global_440x(self) -> None:
        metrics = self.calculation["metrics"]
        self.assertEqual(
            metrics["registered_control_contrast"],
            {
                "feature_control_worst_delta_net_profit_micropoints": (
                    1_079_000_000
                ),
                "feature_control_worst_pvalue_upper_ppm": 530_548,
                "opposite_sign_pvalue_upper_ppm": 10_510,
                "opposite_sign_worst_delta_net_profit_micropoints": (
                    19_029_310_000
                ),
            },
        )
        self.assertEqual(
            metrics["selection_aware_signal_evidence"]
            ["selection_aware_pvalue_ppm"],
            83_885,
        )
        exposure = self.calculation["statistics"]["exposure_semantics"]
        self.assertEqual(
            exposure["exact_concurrent_family_adjustment_factor"],
            4,
        )
        self.assertEqual(
            exposure["exact_subject_control_family_adjustment_factor"],
            2,
        )
        self.assertEqual(
            exposure["original_family_end_global_exposure_count"],
            440,
        )
        self.assertEqual(
            exposure["prospective_prior_global_exposure_count"],
            HISTORICAL_CONTEXT_COUNT,
        )

    def test_team_style_adjudication_preserves_partial_result(self) -> None:
        measurement = build_fixed_hold_measurement(
            scoped_plan=self.job_plan,
            job_id=str(self.calculation["job_id"]),
            job_hash=str(self.calculation["job_hash"]),
            calculation=self.calculation,
            trace_sha256=self.trace_hash,
            calculation_sha256="a" * 64,
        )
        adjudication = adjudicate_validation_measurement_v2(
            self.job_plan.plan,
            measurement,
        )
        self.assertEqual(adjudication.state, "partial_positive")
        claim_states = {
            item.claim_id: item.state for item in adjudication.claims
        }
        self.assertEqual(
            claim_states["causal_feature_and_execution_validity"],
            "supported",
        )
        self.assertEqual(
            claim_states["registered_control_contrast"],
            "contradicted",
        )
        self.assertFalse(adjudication.candidate_eligible)

    def test_central_dispatcher_recomputes_every_registered_metric(self) -> None:
        metrics = self.calculation["metrics"]
        by_mode: dict[str, list[dict[str, object]]] = {
            mode: [] for mode in FIXED_HOLD_REPLAY_EVIDENCE_MODES
        }
        for criterion in FIXED_HOLD_REPLAY_CRITERIA:
            claim_id = str(criterion["claim_id"])
            metric = str(criterion["metric"])
            by_mode[str(criterion["evidence_mode"])].append(
                {
                    "claim_id": claim_id,
                    "metric": metric,
                    "value": metrics[claim_id][metric],
                }
            )
        self.assertEqual(
            validate_trace_calculation_pair(
                trace=self.subject,
                trace_output_name=self.job_plan.output_names["trace"],
                trace_hash=self.trace_hash,
                calculation=self.calculation,
                expected_evidence_modes=FIXED_HOLD_REPLAY_EVIDENCE_MODES,
                expected_metric_bindings_by_mode={
                    mode: tuple(values) for mode, values in by_mode.items()
                },
                mission_id="MIS-0006",
                executable_id=self.target_id,
                job_id="job:drawdown-integration-test",
                job_hash="1" * 64,
            ),
            FIXED_HOLD_REPLAY_EVIDENCE_MODES,
        )
        shared_hash = sha256(canonical_bytes(self.neutral)).hexdigest()
        shared_calculation = build_fixed_hold_shared_trace_calculation(
            trace=self.neutral,
            definition=self.definition,
            mission_id="MIS-0006",
            executable_id=self.target_id,
            job_id="job:drawdown-integration-test",
            job_hash="1" * 64,
            trace_output_name=self.job_plan.output_names["trace"],
            trace_hash=shared_hash,
        )
        self.assertEqual(
            shared_calculation["metrics"],
            self.calculation["metrics"],
        )
        self.assertEqual(
            shared_calculation["statistics"],
            self.calculation["statistics"],
        )
        requirements = parse_proof_requirements(
            self.job_plan.plan["proof_requirements"],
            evidence_modes=FIXED_HOLD_REPLAY_EVIDENCE_MODES,
        )
        calculation_hash = sha256(
            canonical_bytes(shared_calculation)
        ).hexdigest()
        artifact_hashes = {
            self.job_plan.output_names["trace"]: shared_hash,
            self.job_plan.output_names["calculation"]: calculation_hash,
        }
        references = parse_proof_references(
            build_proof_references(
                requirements=requirements,
                artifact_hashes=artifact_hashes,
            ),
            requirements=requirements,
        )
        self.assertEqual(
            validate_proof_artifacts(
                requirements=requirements,
                references=references,
                artifacts={
                    self.job_plan.output_names["trace"]: self.neutral,
                    self.job_plan.output_names["calculation"]: (
                        shared_calculation
                    ),
                },
                artifact_hashes=artifact_hashes,
                expected_metric_bindings_by_mode={
                    mode: tuple(values) for mode, values in by_mode.items()
                },
                mission_id="MIS-0006",
                executable_id=self.target_id,
                job_id="job:drawdown-integration-test",
                job_hash="1" * 64,
            ),
            FIXED_HOLD_REPLAY_EVIDENCE_MODES,
        )
        for mode in FIXED_HOLD_REPLAY_EVIDENCE_MODES:
            self.assertEqual(
                set(
                    trace_proof_kinds(
                        protocol_id=DRAWDOWN_REPLAY_TRACE_PROTOCOL_ID,
                        evidence_mode=mode,
                    )
                ),
                {
                    "atomic_evaluation_trace.v1",
                    "protocol_calculation_proof.v1",
                },
            )

    def test_durable_context_tamper_cannot_select_another_definition(self) -> None:
        forged = deepcopy(self.calculation)
        forged["parameters"][
            "historical_context_prior_global_exposure_count"
        ] += 1
        with self.assertRaises(ScientificTraceError):
            validate_trace_calculation_pair(
                trace=self.subject,
                trace_output_name=self.job_plan.output_names["trace"],
                trace_hash=self.trace_hash,
                calculation=forged,
                expected_evidence_modes=FIXED_HOLD_REPLAY_EVIDENCE_MODES,
                expected_metric_bindings_by_mode={
                    mode: () for mode in FIXED_HOLD_REPLAY_EVIDENCE_MODES
                },
                mission_id="MIS-0006",
                executable_id=self.target_id,
                job_id="job:drawdown-integration-test",
                job_hash="1" * 64,
            )


if __name__ == "__main__":
    unittest.main()
