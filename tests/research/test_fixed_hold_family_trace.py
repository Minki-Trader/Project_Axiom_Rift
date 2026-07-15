from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta
from hashlib import sha256
import unittest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.research.fixed_hold_family_trace import (
    FIXED_HOLD_REPLAY_CLAIMS,
    FIXED_HOLD_REPLAY_CRITERIA,
    FIXED_HOLD_TRACE_VALIDATOR,
    FixedHoldProtocolDefinition,
    bind_fixed_hold_family_trace,
    build_fixed_hold_family_trace,
    build_fixed_hold_trace_calculation,
    expected_fixed_hold_family_inventory,
    extract_fixed_hold_family_trace_from_subject,
    fixed_hold_observation_id,
    validate_fixed_hold_family_trace,
    validate_fixed_hold_trace_calculation,
)
from axiom_rift.research.historical_family_replay import (
    ControlBinding,
    HistoricalFamilySpec,
    HistoricalMemberSpec,
)
from axiom_rift.research.scientific_trace import (
    SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
    SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
    ScientificTraceError,
)


TRACE_FIELDS = {
    "adapter_implementation_sha256",
    "attribution",
    "controls",
    "dataset_sha256",
    "eligible_day_observations",
    "family_id",
    "invariance_comparisons",
    "intent_observations",
    "job_hash",
    "job_id",
    "material_identity",
    "mission_id",
    "ordered_family",
    "protocol_id",
    "schema",
    "split_artifact_sha256",
    "subject_executable_id",
    "trade_observations",
    "windows",
}
CALCULATION_FIELDS = {
    "evidence_modes",
    "executable_id",
    "job_hash",
    "job_id",
    "metrics",
    "mission_id",
    "parameters",
    "protocol_definition",
    "protocol_id",
    "schema",
    "statistics",
    "trace",
}


def digest(token: str) -> str:
    return sha256(token.encode("ascii")).hexdigest()


def executable(token: int) -> str:
    return f"executable:{token:064x}"


def historical_family() -> HistoricalFamilySpec:
    members = tuple(
        HistoricalMemberSpec(
            ordinal=ordinal,
            configuration_id=f"configuration-{ordinal}",
            historical_reference_executable_id=executable(ordinal),
            parameters={
                "holding_bars": 2,
                "profile": f"profile-{ordinal}",
                "signal_sign": 1 if ordinal in {1, 4} else -1,
            },
        )
        for ordinal in range(1, 5)
    )
    controls = (
        ControlBinding(
            subject_historical_executable_id=executable(1),
            opposite_historical_executable_id=executable(2),
            feature_historical_executable_ids=(executable(3),),
        ),
        ControlBinding(
            subject_historical_executable_id=executable(2),
            opposite_historical_executable_id=executable(1),
            feature_historical_executable_ids=(executable(4),),
        ),
        ControlBinding(
            subject_historical_executable_id=executable(3),
            opposite_historical_executable_id=executable(4),
            feature_historical_executable_ids=(executable(1),),
        ),
        ControlBinding(
            subject_historical_executable_id=executable(4),
            opposite_historical_executable_id=executable(3),
            feature_historical_executable_ids=(
                executable(1),
                executable(2),
            ),
        ),
    )
    return HistoricalFamilySpec(
        original_study_id="STU-9001",
        original_batch_id=f"batch:{9001:064x}",
        target_historical_executable_id=executable(4),
        members=members,
        controls=controls,
    )


def definition(*, prior_global_count: int = 600) -> FixedHoldProtocolDefinition:
    return FixedHoldProtocolDefinition(
        family=historical_family(),
        prospective_executable_ids=tuple(
            executable(100 + ordinal) for ordinal in range(1, 5)
        ),
        protocol_id="fixed_hold.test_four_member.v1",
        fold_ids=("rw_001",),
        invariance_keys=("feature-a", "feature-b", "target-feature"),
        allowed_regimes=("high", "low", "middle"),
        dataset_sha256=digest("dataset"),
        material_identity=f"development-material:{digest('material')}",
        split_artifact_sha256=digest("split"),
        clock_contract="clock:test-completed-m5-next-open-v1",
        cost_contract="cost:test-native-and-stress-v1",
        producer_implementation_identities=(
            ("fixed_hold_test_producer_sha256", digest("producer")),
        ),
        historical_context_id="historical-search:test-context",
        historical_prior_global_exposure_count=prior_global_count,
        original_family_end_global_exposure_count=500,
        alpha_ppm=100_000,
        bootstrap_samples=99,
        block_lengths=(5,),
        monte_carlo_confidence_ppm=900_000,
        base_seed=42,
    )


def daily_native(configuration_id: str, ordinal: int) -> int:
    if configuration_id == "configuration-1":
        return 6 + ordinal % 3
    if configuration_id == "configuration-2":
        return 2 - ordinal % 2
    if configuration_id == "configuration-3":
        return -3 + ordinal % 2
    if configuration_id == "configuration-4":
        return 10 + ordinal % 4
    raise AssertionError(configuration_id)


def atomic_rows(
    value: FixedHoldProtocolDefinition,
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    start = datetime(2024, 1, 1)
    dates = tuple((start + timedelta(days=index)).date().isoformat() for index in range(30))
    windows = [
        {
            "eligible_dates": list(dates),
            "fold_id": "rw_001",
            "test_end": "2024-01-30T23:55:00",
            "test_start": "2024-01-01T00:00:00",
            "train_end": "2023-12-31T23:55:00",
            "train_start": "2023-12-01T00:00:00",
        }
    ]
    invariance = [
        {
            "compared_row_count": 100,
            "fold_id": "rw_001",
            "full_feature_values_sha256": digest(key),
            "invariance_key": key,
            "prefix_feature_values_sha256": digest(key),
        }
        for key in value.invariance_keys
    ]
    trades: list[dict[str, object]] = []
    intents: list[dict[str, object]] = []
    eligible: list[dict[str, object]] = []
    inventory = expected_fixed_hold_family_inventory(value)
    for member in inventory:
        configuration_id = str(member["configuration_id"])
        executable_id = str(member["executable_id"])
        historical_id = str(member["historical_reference_executable_id"])
        for ordinal, day in enumerate(dates, start=1):
            native = 0 if ordinal == len(dates) else daily_native(
                configuration_id,
                ordinal,
            )
            stress = 0 if ordinal == len(dates) else native - 1
            eligible.append(
                {
                    "configuration_id": configuration_id,
                    "date": day,
                    "entry_count": 0 if ordinal == len(dates) else 1,
                    "executable_id": executable_id,
                    "fold_id": "rw_001",
                    "native_net_pnl_micropoints": native,
                    "stress_net_pnl_micropoints": stress,
                }
            )
            if ordinal == len(dates):
                continue
            bar_open = datetime.fromisoformat(day + "T09:00:00")
            decision = bar_open + timedelta(minutes=5)
            exit_time = decision + timedelta(minutes=10)
            decision_index = 1000 + ordinal * 10
            trade: dict[str, object] = {
                "availability_time": decision.isoformat(),
                "configuration_id": configuration_id,
                "decision_bar_index": decision_index,
                "decision_bar_open_time": bar_open.isoformat(),
                "decision_time": decision.isoformat(),
                "direction": 1,
                "entry_bar_index": decision_index + 1,
                "entry_time": decision.isoformat(),
                "executable_id": executable_id,
                "exit_bar_index": decision_index + 3,
                "exit_time": exit_time.isoformat(),
                "fold_id": "rw_001",
                "gross_pnl_micropoints": native + 2,
                "historical_reference_executable_id": historical_id,
                "holding_bars": 2,
                "native_cost_micropoints": 2,
                "native_net_pnl_micropoints": native,
                "observation_id": "pending",
                "regime": ("high", "low", "middle")[(ordinal - 1) % 3],
                "stress_cost_micropoints": 3,
                "stress_net_pnl_micropoints": stress,
            }
            trade["observation_id"] = fixed_hold_observation_id("trade", trade)
            trades.append(trade)
            for scope in ("full", "prefix"):
                intent: dict[str, object] = {
                    "availability_time": decision.isoformat(),
                    "configuration_id": configuration_id,
                    "decision_bar_index": decision_index,
                    "decision_bar_open_time": bar_open.isoformat(),
                    "decision_time": decision.isoformat(),
                    "direction": 1,
                    "entry_bar_index": decision_index + 1,
                    "entry_time": decision.isoformat(),
                    "executable_id": executable_id,
                    "exit_bar_index": decision_index + 3,
                    "exit_time": exit_time.isoformat(),
                    "fold_id": "rw_001",
                    "historical_reference_executable_id": historical_id,
                    "holding_bars": 2,
                    "observation_id": "pending",
                    "ordinal": ordinal,
                    "scope": scope,
                    "status": "executed",
                }
                intent["observation_id"] = fixed_hold_observation_id(
                    "intent",
                    intent,
                )
                intents.append(intent)
    trades.sort(
        key=lambda item: (
            item["configuration_id"],
            item["fold_id"],
            item["decision_time"],
            item["observation_id"],
        )
    )
    intents.sort(
        key=lambda item: (
            item["configuration_id"],
            item["fold_id"],
            item["scope"],
            item["ordinal"],
            item["observation_id"],
        )
    )
    eligible.sort(
        key=lambda item: (
            item["configuration_id"],
            item["fold_id"],
            item["date"],
        )
    )
    return windows, invariance, trades, intents, eligible


def family_trace(value: FixedHoldProtocolDefinition) -> dict[str, object]:
    windows, invariance, trades, intents, eligible = atomic_rows(value)
    return build_fixed_hold_family_trace(
        definition=value,
        validator=FIXED_HOLD_TRACE_VALIDATOR,
        windows=windows,
        invariance_comparisons=invariance,
        trade_observations=trades,
        intent_observations=intents,
        eligible_day_observations=eligible,
    )


def subject_trace(
    value: FixedHoldProtocolDefinition,
) -> tuple[dict[str, object], dict[str, object]]:
    neutral = family_trace(value)
    subject = bind_fixed_hold_family_trace(
        family_trace=neutral,
        definition=value,
        validator=FIXED_HOLD_TRACE_VALIDATOR,
        mission_id="MIS-9001",
        executable_id=value.prospective_executable_ids[3],
        job_id="job:test-fixed-hold",
        job_hash=digest("job"),
    )
    return neutral, subject


def calculation(
    value: FixedHoldProtocolDefinition,
    subject: dict[str, object],
) -> dict[str, object]:
    return build_fixed_hold_trace_calculation(
        trace=subject,
        definition=value,
        validator=FIXED_HOLD_TRACE_VALIDATOR,
        trace_output_name="scientific/test/evaluation-trace.json",
        trace_hash=sha256(canonical_bytes(subject)).hexdigest(),
    )


class FixedHoldFamilyTraceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.definition = definition()
        cls.neutral, cls.subject = subject_trace(cls.definition)
        cls.calculation = calculation(cls.definition, cls.subject)

    def test_end_to_end_proof_matches_common_outer_schema_and_all_metrics(self) -> None:
        self.assertEqual(set(self.subject), TRACE_FIELDS)
        self.assertEqual(self.subject["schema"], SCIENTIFIC_EVALUATION_TRACE_SCHEMA)
        self.assertEqual(set(self.calculation), CALCULATION_FIELDS)
        self.assertEqual(
            self.calculation["schema"],
            SCIENTIFIC_CALCULATION_PROOF_SCHEMA,
        )
        metrics = validate_fixed_hold_trace_calculation(
            trace=self.subject,
            calculation=self.calculation,
            definition=self.definition,
            validator=FIXED_HOLD_TRACE_VALIDATOR,
        )
        self.assertEqual(tuple(metrics), FIXED_HOLD_REPLAY_CLAIMS)
        self.assertEqual(len(FIXED_HOLD_REPLAY_CRITERIA), 20)
        for criterion in FIXED_HOLD_REPLAY_CRITERIA:
            self.assertIn(
                criterion["metric"],
                metrics[str(criterion["claim_id"])],
            )
        self.assertEqual(
            extract_fixed_hold_family_trace_from_subject(
                self.subject,
                definition=self.definition,
                validator=FIXED_HOLD_TRACE_VALIDATOR,
            ),
            self.neutral,
        )

    def test_multi_feature_controls_use_min_delta_and_max_familywise_upper(self) -> None:
        metrics = self.calculation["metrics"]["registered_control_contrast"]
        target_total = sum(daily_native("configuration-4", day) for day in range(1, 30))
        feature_totals = (
            sum(daily_native("configuration-1", day) for day in range(1, 30)),
            sum(daily_native("configuration-2", day) for day in range(1, 30)),
        )
        self.assertEqual(
            metrics["feature_control_worst_delta_net_profit_micropoints"],
            min(target_total - total for total in feature_totals),
        )
        paired = self.calculation["statistics"]["paired_control_family"]
        feature_hypotheses = [
            item
            for item in paired["hypotheses"]
            if item["hypothesis_id"].startswith("paired-control:feature:")
        ]
        self.assertEqual(len(feature_hypotheses), 2)
        self.assertEqual(paired["plan"]["family_size"], 3)
        self.assertEqual(
            metrics["feature_control_worst_pvalue_upper_ppm"],
            max(
                item["familywise"]["synchronized_max"]
                ["monte_carlo_upper_pvalue_ppm"]
                for item in feature_hypotheses
            ),
        )
        self.assertEqual(
            self.calculation["statistics"]["selection_family"]["plan"]
            ["family_size"],
            4,
        )

    def test_global_exposure_count_is_context_only_not_inference_factor(self) -> None:
        changed = replace(
            self.definition,
            historical_prior_global_exposure_count=9_999,
        )
        _, changed_subject = subject_trace(changed)
        changed_calculation = calculation(changed, changed_subject)
        self.assertEqual(
            changed_calculation["metrics"],
            self.calculation["metrics"],
        )
        for name in ("selection_family", "paired_control_family"):
            self.assertEqual(
                changed_calculation["statistics"][name],
                self.calculation["statistics"][name],
            )
        self.assertEqual(
            changed_calculation["statistics"]["historical_context"]
            ["prior_global_exposure_count"],
            9_999,
        )
        self.assertEqual(
            changed_calculation["statistics"]["historical_context"]
            ["adjustment_authority"],
            "context_only_never_adjustment_factor",
        )

    def test_trade_and_intent_fixed_hold_indices_fail_closed(self) -> None:
        trade_drift = deepcopy(self.neutral)
        trade = trade_drift["trade_observations"][0]
        trade["exit_bar_index"] += 1
        trade["observation_id"] = fixed_hold_observation_id("trade", trade)
        with self.assertRaisesRegex(ScientificTraceError, "fixed holding interval"):
            validate_fixed_hold_family_trace(
                trade_drift,
                definition=self.definition,
                validator=FIXED_HOLD_TRACE_VALIDATOR,
            )

        intent_drift = deepcopy(self.neutral)
        intent = intent_drift["intent_observations"][0]
        intent["entry_bar_index"] += 1
        intent["observation_id"] = fixed_hold_observation_id("intent", intent)
        with self.assertRaisesRegex(ScientificTraceError, "decision/entry index"):
            validate_fixed_hold_family_trace(
                intent_drift,
                definition=self.definition,
                validator=FIXED_HOLD_TRACE_VALIDATOR,
            )

    def test_negative_execution_observations_survive_as_scientific_evidence(
        self,
    ) -> None:
        def append_status_intents(
            trace: dict[str, object],
            *,
            status: str,
            decision_time: str,
            entry_time: str,
            exit_time: str,
        ) -> None:
            member = trace["ordered_family"][0]
            for scope in ("full", "prefix"):
                intent: dict[str, object] = {
                    "availability_time": "2024-01-30T09:05:00",
                    "configuration_id": member["configuration_id"],
                    "decision_bar_index": 2_000,
                    "decision_bar_open_time": "2024-01-30T09:00:00",
                    "decision_time": decision_time,
                    "direction": 1,
                    "entry_bar_index": 2_001,
                    "entry_time": entry_time,
                    "executable_id": member["executable_id"],
                    "exit_bar_index": 2_003,
                    "exit_time": exit_time,
                    "fold_id": "rw_001",
                    "historical_reference_executable_id": member[
                        "historical_reference_executable_id"
                    ],
                    "holding_bars": 2,
                    "observation_id": "pending",
                    "ordinal": 30,
                    "scope": scope,
                    "status": status,
                }
                intent["observation_id"] = fixed_hold_observation_id(
                    "intent",
                    intent,
                )
                trace["intent_observations"].append(intent)
            trace["intent_observations"].sort(
                key=lambda item: (
                    item["configuration_id"],
                    item["fold_id"],
                    item["scope"],
                    item["ordinal"],
                    item["observation_id"],
                )
            )

        gap = deepcopy(self.neutral)
        append_status_intents(
            gap,
            status="gap_excluded",
            decision_time="2024-01-30T09:05:00",
            entry_time="2024-01-30T10:00:00",
            exit_time="2024-01-30T10:10:00",
        )
        validate_fixed_hold_family_trace(
            gap,
            definition=self.definition,
            validator=FIXED_HOLD_TRACE_VALIDATOR,
        )
        forged_gap = deepcopy(gap)
        for intent in forged_gap["intent_observations"]:
            if intent["ordinal"] == 30:
                intent["status"] = "executed"
                intent["observation_id"] = fixed_hold_observation_id(
                    "intent",
                    intent,
                )
        with self.assertRaisesRegex(
            ScientificTraceError,
            "executable fixed-hold clock",
        ):
            validate_fixed_hold_family_trace(
                forged_gap,
                definition=self.definition,
                validator=FIXED_HOLD_TRACE_VALIDATOR,
            )

        causal_failure = deepcopy(self.neutral)
        append_status_intents(
            causal_failure,
            status="causality_violation",
            decision_time="2024-01-30T09:04:00",
            entry_time="2024-01-30T09:05:00",
            exit_time="2024-01-30T09:15:00",
        )
        bound = bind_fixed_hold_family_trace(
            family_trace=causal_failure,
            definition=self.definition,
            validator=FIXED_HOLD_TRACE_VALIDATOR,
            mission_id="MIS-9001",
            executable_id=self.definition.prospective_executable_ids[0],
            job_id="job:causal-negative-evidence",
            job_hash=digest("causal-negative-evidence"),
        )
        proof = calculation(self.definition, bound)
        self.assertEqual(
            proof["metrics"]["causal_feature_and_execution_validity"]
            ["causality_violation_count"],
            1,
        )

    def test_zero_day_inventory_and_code_owned_control_schema_fail_closed(self) -> None:
        missing_zero_day = deepcopy(self.neutral)
        missing_zero_day["eligible_day_observations"].pop(29)
        with self.assertRaisesRegex(ScientificTraceError, "zero-entry calendar"):
            validate_fixed_hold_family_trace(
                missing_zero_day,
                definition=self.definition,
                validator=FIXED_HOLD_TRACE_VALIDATOR,
            )

        callback_payload = deepcopy(self.neutral)
        callback_payload["controls"]["validator_import_path"] = (
            "malicious.module:callback"
        )
        with self.assertRaisesRegex(ScientificTraceError, "authority binding"):
            validate_fixed_hold_family_trace(
                callback_payload,
                definition=self.definition,
                validator=FIXED_HOLD_TRACE_VALIDATOR,
            )

    def test_subject_and_calculation_bindings_reject_forgery(self) -> None:
        with self.assertRaisesRegex(ScientificTraceError, "outside its family"):
            bind_fixed_hold_family_trace(
                family_trace=self.neutral,
                definition=self.definition,
                validator=FIXED_HOLD_TRACE_VALIDATOR,
                mission_id="MIS-9001",
                executable_id=executable(999),
                job_id="job:test-fixed-hold",
                job_hash=digest("job"),
            )
        forged = deepcopy(self.calculation)
        control_metrics = forged["metrics"]["registered_control_contrast"]
        control_metrics[
            "feature_control_worst_delta_net_profit_micropoints"
        ] += 1
        with self.assertRaisesRegex(ScientificTraceError, "metrics drifted"):
            validate_fixed_hold_trace_calculation(
                trace=self.subject,
                calculation=forged,
                definition=self.definition,
                validator=FIXED_HOLD_TRACE_VALIDATOR,
            )
        with self.assertRaisesRegex(ScientificTraceError, "opened trace"):
            build_fixed_hold_trace_calculation(
                trace=self.subject,
                definition=self.definition,
                validator=FIXED_HOLD_TRACE_VALIDATOR,
                trace_output_name="scientific/test/evaluation-trace.json",
                trace_hash=digest("wrong-trace"),
            )


if __name__ == "__main__":
    unittest.main()
