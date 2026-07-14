from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import pandas as pd

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.research.drawdown_state_replay import (
    DRAWDOWN_REPLAY_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT,
    causal_drawdown_replay_spread,
    compute_drawdown_replay_score,
    compute_stu0048_drawdown_family_trace,
    drawdown_replay_components,
    drawdown_replay_controlled_chassis,
    drawdown_replay_executable_map,
    drawdown_replay_protocol_definition,
)
from axiom_rift.research.drawdown_state_replay_job import (
    CALLABLE_IDENTITY,
    build_drawdown_replay_job_plan,
    drawdown_replay_job_implementation_sha256,
    materialize_drawdown_replay_job_implementation,
)
from axiom_rift.operations.writer import StateWriter
from axiom_rift.research.fixed_hold_family_job import (
    build_fixed_hold_measurement,
)
from axiom_rift.research.fixed_hold_family_trace import (
    FIXED_HOLD_REPLAY_CRITERIA,
    FIXED_HOLD_REPLAY_EVIDENCE_MODES,
    FIXED_HOLD_TRACE_VALIDATOR,
    bind_fixed_hold_family_trace,
    build_fixed_hold_trace_calculation,
)
from axiom_rift.research.historical_family_replay import (
    STU0048_HISTORICAL_FAMILY,
)
from axiom_rift.research.scientific_trace import (
    DRAWDOWN_REPLAY_TRACE_PROTOCOL_ID,
    ScientificTraceError,
    trace_proof_kinds,
    validate_trace_calculation_pair,
)
from axiom_rift.research.validation_v2 import (
    adjudicate_validation_measurement_v2,
)


HISTORICAL_CONTEXT_COUNT = 578


class DrawdownReplayBoundaryTests(unittest.TestCase):
    def test_job_implementation_closure_is_writer_readable(self) -> None:
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
            manifest = writer._require_job_implementation_evidence(
                {
                    "callable_identity": CALLABLE_IDENTITY,
                    "implementation_identity": identity,
                },
                allowed_historical_control_ids=("STU-0048",),
            )
        self.assertEqual(
            manifest["schema"],
            "job_implementation_evidence.v1",
        )
        self.assertEqual(len(manifest["artifact_hashes"]), 4)

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
        with self.assertRaisesRegex(ValueError, "cannot precede"):
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


class DrawdownReplayIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.definition = drawdown_replay_protocol_definition(
            historical_context_prior_global_exposure_count=(
                HISTORICAL_CONTEXT_COUNT
            )
        )
        cls.neutral, cls.raw = compute_stu0048_drawdown_family_trace(
            ".",
            historical_context_prior_global_exposure_count=(
                HISTORICAL_CONTEXT_COUNT
            ),
        )
        cls.target_id = cls.definition.prospective_executable_ids[3]
        cls.job_plan = build_drawdown_replay_job_plan(
            mission_id="MIS-0006",
            study_id="STU-test",
            executable_id=cls.target_id,
            historical_context_prior_global_exposure_count=(
                HISTORICAL_CONTEXT_COUNT
            ),
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

    def test_full_atomic_replay_matches_all_historical_raw_surfaces(self) -> None:
        self.assertEqual(len(self.neutral["ordered_family"]), 4)
        self.assertEqual(len(self.neutral["windows"]), 9)
        self.assertEqual(len(self.neutral["trade_observations"]), 7_876)
        self.assertEqual(len(self.neutral["intent_observations"]), 29_696)
        self.assertEqual(
            len(self.neutral["eligible_day_observations"]),
            2_320,
        )
        self.assertEqual(len(self.neutral["invariance_comparisons"]), 18)
        self.assertEqual(
            self.raw[self.target_id]["net_profit_micropoints"],
            7_010_130_000,
        )
        self.assertEqual(self.raw[self.target_id]["trade_count"], 1_916)
        self.assertEqual(self.raw[self.target_id]["winning_fold_count"], 7)

    def test_exact_family_and_control_inference_replaces_global_440x(self) -> None:
        metrics = self.calculation["metrics"]
        self.assertEqual(
            metrics["registered_control_contrast"],
            {
                "feature_control_worst_delta_net_profit_micropoints": (
                    858_270_000
                ),
                "feature_control_worst_pvalue_upper_ppm": 562_207,
                "opposite_sign_pvalue_upper_ppm": 11_993,
                "opposite_sign_worst_delta_net_profit_micropoints": (
                    18_424_560_000
                ),
            },
        )
        self.assertEqual(
            metrics["selection_aware_signal_evidence"]
            ["selection_aware_pvalue_ppm"],
            102_322,
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
