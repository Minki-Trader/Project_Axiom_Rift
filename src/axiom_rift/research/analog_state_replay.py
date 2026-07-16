"""Read-only authority-gated replay adapter for the historical analog family."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

import numpy as np
import pandas as pd

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.running_job import RunningJobExecution
from axiom_rift.operations.running_job_context import RunningJobExecutionContext
from axiom_rift.research.adjudication import adjudicate_plan_measurement
from axiom_rift.research.analog_state_family import (
    AnalogFamilyConfiguration,
    analog_family_executable,
    analog_family_executable_map,
    analog_family_implementation_sha256,
    calibrate_analog_selector,
    fit_fold_analog_family,
)
from axiom_rift.research.historical_analog_family_stu0061 import (
    STU0061_ANALOG_FAMILY as P1_STU0061_ANALOG_FAMILY,
)
from axiom_rift.research.analog_state_trace import (
    ANALOG_FAMILY_TRACE_CACHE_MANIFEST_SCHEMA,
    ANALOG_FAMILY_TRACE_SCHEMA,
    ANALOG_REPLAY_CLAIMS,
    ANALOG_REPLAY_CRITERIA,
    ANALOG_REPLAY_EVIDENCE_MODES,
    ANALOG_REPLAY_CONTROLS,
    ANALOG_REPLAY_TRACE_ATTRIBUTION,
    analog_family_execution_contracts,
    analog_family_trace_implementation_identities,
    analog_observation_id,
    analog_original_family_provenance,
    analog_trace_implementation_sha256,
    bind_analog_family_trace,
    build_analog_trace_calculation,
    expected_analog_family_inventory,
    extract_analog_family_trace_cache_material,
    validate_analog_family_trace,
    validate_analog_family_trace_cache_manifest,
)
from axiom_rift.research.analog_state_trace_rows import (
    analog_trace_rows_implementation_sha256,
    digest_causal_surfaces as _shared_digest_causal_surfaces,
    intent_rows as _shared_intent_rows,
    iso_timestamp as _shared_iso_timestamp,
    trade_rows as _shared_trade_rows,
)
from axiom_rift.research.data import load_observed_development
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
    _evaluate_configuration,
    _fold_payloads,
    _time_ns,
    _validate_engine_environment,
    _validate_fold_payloads,
    _validate_production_data,
    causal_effective_spread,
    discovery_implementation_sha256,
    loader_implementation_sha256,
    simulate_fixed_hold,
)
from axiom_rift.research.evidence_proofs import (
    ATOMIC_TRACE_PROOF_KIND,
    CALCULATION_PROOF_KIND,
    build_proof_references,
    parse_proof_requirements,
    proof_requirements_for_modes,
)
from axiom_rift.research.scientific_trace import (
    ANALOG_STATE_TRACE_PROTOCOL_ID,
    SCIENTIFIC_EVALUATION_TRACE_SCHEMA,
)
from axiom_rift.research.selection_inference import (
    selection_inference_implementation_sha256,
)
from axiom_rift.research.replay_coverage import (
    validated_recomputed_criterion_ids,
)
from axiom_rift.research.reproducible_cache import (
    publish_reproducible_cache,
    reproducible_cache_implementation_sha256,
)
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_ADJUDICATION_PROFILE_SCHEMA,
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    SCIENTIFIC_MEASUREMENT_V2_SCHEMA,
    SCIENTIFIC_RESULT_SCHEMA,
    SCIENTIFIC_V2_SYNCHRONIZED_MAX_METHOD,
    build_validation_plan_v2,
    multiplicity_family_registration_hash,
)

CALLABLE_IDENTITY = (
    "axiom_rift.research.analog_state_replay.execute_analog_replay_job.v1"
)


class AnalogReplayJobContext(Protocol):
    """Minimum non-mutating authority and evidence surface for replay Jobs."""

    evidence: Any

    def verify_running_job_execution(
        self,
        execution: RunningJobExecution,
        **kwargs: Any,
    ) -> dict[str, Any]: ...

    def verify_reproducible_cache_producer(
        self,
        producer: RunningJobExecution,
        **kwargs: Any,
    ) -> None: ...


ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME = (
    "local/cache/analog-state/stu0061-family-trace-v1.json"
)
EVIDENCE_DEPTH = "discovery"
MICROPOINTS_PER_POINT = 1_000_000
_THIS_FILE = Path(__file__).resolve()
FROZEN_STU0061_RAW_METRICS = {
    "executable:80e19339aa1562ab73a1922c1e595163d3d38963c955f46d9c8700b0830af463": {
        "append_invariance_mismatch_count": 0,
        "causality_violation_count": 0,
        "daily_entries_max_milli": 3_000,
        "daily_entries_median_milli": 2_000,
        "daily_entries_p10_milli": 1_000,
        "daily_entries_p90_milli": 3_000,
        "eligible_day_count": 580,
        "entries_per_day_milli": 1_829,
        "evaluable_folds": 9,
        "gap_excluded_signal_count": 805,
        "median_fold_profit_factor_milli": 831,
        "monthly_realized_exit_drawdown_micropoints": 3_282_930_000,
        "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": 1_156_091,
        "net_profit_micropoints": -2_620_240_000,
        "nonfinite_metric_count": 0,
        "positive_regime_count": 1,
        "prefix_invariance_mismatch_count": 0,
        "stress_net_profit_micropoints": -3_760_540_000,
        "supported_positive_regime_count": 0,
        "top5_profit_day_share_ppm": 94_725,
        "trade_count": 1_061,
        "unknown_cost_unresolved_signal_count": 0,
        "winning_fold_count": 3,
        "zero_entry_day_rate_ppm": 43_103,
    },
    "executable:050d071fae20cef41beecd5caf356f645ad4c3bcc16749e2fa5179f3a511dac7": {
        "append_invariance_mismatch_count": 0,
        "causality_violation_count": 0,
        "daily_entries_max_milli": 3_000,
        "daily_entries_median_milli": 2_000,
        "daily_entries_p10_milli": 1_000,
        "daily_entries_p90_milli": 3_000,
        "eligible_day_count": 580,
        "entries_per_day_milli": 1_829,
        "evaluable_folds": 9,
        "gap_excluded_signal_count": 805,
        "median_fold_profit_factor_milli": 1_140,
        "monthly_realized_exit_drawdown_micropoints": 1_490_530_000,
        "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": 1_592_151,
        "net_profit_micropoints": 339_640_000,
        "nonfinite_metric_count": 0,
        "positive_regime_count": 1,
        "prefix_invariance_mismatch_count": 0,
        "stress_net_profit_micropoints": -800_660_000,
        "supported_positive_regime_count": 1,
        "top5_profit_day_share_ppm": 108_531,
        "trade_count": 1_061,
        "unknown_cost_unresolved_signal_count": 0,
        "winning_fold_count": 6,
        "zero_entry_day_rate_ppm": 43_103,
    },
    "executable:4fe8293577a9aa4292bca8e5170b39528b45faeec7c7fe4453851c227869e8df": {
        "append_invariance_mismatch_count": 0,
        "causality_violation_count": 0,
        "daily_entries_max_milli": 3_000,
        "daily_entries_median_milli": 2_000,
        "daily_entries_p10_milli": 1_000,
        "daily_entries_p90_milli": 3_000,
        "eligible_day_count": 580,
        "entries_per_day_milli": 1_941,
        "evaluable_folds": 9,
        "gap_excluded_signal_count": 997,
        "median_fold_profit_factor_milli": 886,
        "monthly_realized_exit_drawdown_micropoints": 2_010_980_000,
        "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": 1_789_357,
        "net_profit_micropoints": -5_683_590_000,
        "nonfinite_metric_count": 0,
        "positive_regime_count": 0,
        "prefix_invariance_mismatch_count": 0,
        "stress_net_profit_micropoints": -6_882_725_000,
        "supported_positive_regime_count": 0,
        "top5_profit_day_share_ppm": 87_360,
        "trade_count": 1_126,
        "unknown_cost_unresolved_signal_count": 0,
        "winning_fold_count": 3,
        "zero_entry_day_rate_ppm": 34_483,
    },
    "executable:61a3e085beb97af8ab8251125463bd3106cdebdbac511915b0434f07f14589e8": {
        "append_invariance_mismatch_count": 0,
        "causality_violation_count": 0,
        "daily_entries_max_milli": 3_000,
        "daily_entries_median_milli": 2_000,
        "daily_entries_p10_milli": 1_000,
        "daily_entries_p90_milli": 3_000,
        "eligible_day_count": 580,
        "entries_per_day_milli": 1_941,
        "evaluable_folds": 9,
        "gap_excluded_signal_count": 997,
        "median_fold_profit_factor_milli": 1_074,
        "monthly_realized_exit_drawdown_micropoints": 1_670_210_000,
        "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": 2_060_487,
        "net_profit_micropoints": 3_285_320_000,
        "nonfinite_metric_count": 0,
        "positive_regime_count": 3,
        "prefix_invariance_mismatch_count": 0,
        "stress_net_profit_micropoints": 2_086_185_000,
        "supported_positive_regime_count": 2,
        "top5_profit_day_share_ppm": 96_558,
        "trade_count": 1_126,
        "unknown_cost_unresolved_signal_count": 0,
        "winning_fold_count": 5,
        "zero_entry_day_rate_ppm": 34_483,
    },
}

STU0061_REPLAY_CRITERION_IDS = tuple(
    sorted(str(item["criterion_id"]) for item in ANALOG_REPLAY_CRITERIA)
)


def analog_replay_implementation_sha256() -> str:
    return sha256(
        _THIS_FILE.read_bytes()
        + bytes.fromhex(reproducible_cache_implementation_sha256())
        + bytes.fromhex(analog_trace_rows_implementation_sha256())
    ).hexdigest()


def analog_family_trace_cache_output_name() -> str:
    return ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME


def analog_family_trace_cache_path(repository_root: str | Path) -> Path:
    root = Path(repository_root).resolve()
    target = (root / ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME).resolve()
    cache_root = (root / "local" / "cache").resolve()
    if cache_root not in target.parents:
        raise ValueError("analog family trace cache escapes local/cache")
    return target


def assert_frozen_stu0061_raw_metric_parity(
    metrics_by_new_executable: Mapping[str, Mapping[str, int]],
) -> None:
    """Fail closed if the recovered family changes historical raw semantics."""

    mapping = analog_family_executable_map(P1_STU0061_ANALOG_FAMILY)
    if set(metrics_by_new_executable) != set(mapping):
        raise ValueError("historical analog raw parity family inventory drifted")
    for new_executable_id, configuration in mapping.items():
        historical = configuration.historical_reference_executable_id
        expected = FROZEN_STU0061_RAW_METRICS.get(str(historical))
        observed = metrics_by_new_executable[new_executable_id]
        if expected is None or {
            name: observed.get(name) for name in expected
        } != expected:
            raise ValueError(
                "historical analog raw metric parity drifted for "
                f"{configuration.configuration_id}"
            )


def validated_stu0061_recomputed_criterion_ids(
    facts: Mapping[str, object],
) -> tuple[str, ...]:
    """Return exact replay coverage only for complete, scientifically valid facts.

    A failed economic or stability criterion is still a valid recomputation and
    therefore still satisfies the historical *measurement* obligation.  An
    unavailable comparison, malformed criterion definition, or failed validity
    criterion does not.  This distinction prevents replay resolution from
    silently turning a scientifically negative result into missing evidence.
    """

    result = validated_recomputed_criterion_ids(
        facts,
        expected_evidence_modes=ANALOG_REPLAY_EVIDENCE_MODES,
        expected_criteria=ANALOG_REPLAY_CRITERIA,
        context="historical analog replay",
    )
    if result != STU0061_REPLAY_CRITERION_IDS:
        raise ValueError("historical analog replay criterion order drifted")
    return result


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    return value


def _digest_causal_surfaces(
    surfaces: tuple[tuple[str, np.ndarray], ...],
) -> str:
    return _shared_digest_causal_surfaces(surfaces)


def _iso(value: object) -> str:
    return _shared_iso_timestamp(value)


def _micropoints(value: object) -> int:
    return int(round(float(value) * MICROPOINTS_PER_POINT))


def analog_replay_output_names(
    executable_id: str,
    *,
    study_id: str,
) -> dict[str, str]:
    prefix = (
        f"scientific/{_ascii('study_id', study_id)}/"
        f"{_ascii('executable_id', executable_id).removeprefix('executable:')[:16]}"
    )
    return {
        "calculation": f"{prefix}/calculation-proof.json",
        "measurement": f"{prefix}/measurement.json",
        "plan": f"{prefix}/validation-plan.json",
        "result": f"{prefix}/result.json",
        "trace": f"{prefix}/evaluation-trace.json",
    }


def _multiplicity_registration(
    *,
    criterion_id: str,
    family_id: str,
    member_id: str,
    ordered_member_ids: Sequence[str],
) -> dict[str, object]:
    family = _ascii("analog multiplicity family_id", family_id)
    member = _ascii("analog multiplicity member_id", member_id)
    if isinstance(ordered_member_ids, (str, bytes)):
        raise ValueError("analog multiplicity family must be an ordered sequence")
    members = tuple(
        _ascii("analog multiplicity family member", value)
        for value in ordered_member_ids
    )
    if (
        not members
        or len(set(members)) != len(members)
        or member not in members
    ):
        raise ValueError("analog multiplicity family membership is invalid")
    return {
        "alpha_ppm": 100_000,
        "criterion_id": criterion_id,
        "family_id": family,
        "family_registration_hash": multiplicity_family_registration_hash(
            family_id=family,
            alpha_ppm=100_000,
            method=SCIENTIFIC_V2_SYNCHRONIZED_MAX_METHOD,
            ordered_member_ids=members,
        ),
        "family_size": len(members),
        "member_id": member,
        "method": SCIENTIFIC_V2_SYNCHRONIZED_MAX_METHOD,
        "ordered_member_ids": list(members),
    }


def analog_replay_multiplicity_registrations(
    *,
    subject_executable_id: str,
    subject_configuration_id: str,
    ordered_family_executable_ids: Sequence[str],
) -> tuple[dict[str, object], ...]:
    subject = _ascii(
        "analog multiplicity subject executable",
        subject_executable_id,
    )
    configuration = _ascii(
        "analog multiplicity subject configuration",
        subject_configuration_id,
    )
    if isinstance(ordered_family_executable_ids, (str, bytes)):
        raise ValueError("analog concurrent family must be an ordered sequence")
    family_members = tuple(
        _ascii("analog concurrent family executable", value)
        for value in ordered_family_executable_ids
    )
    if (
        len(family_members) != len(P1_STU0061_ANALOG_FAMILY.configurations())
        or len(set(family_members)) != len(family_members)
        or subject not in family_members
    ):
        raise ValueError("analog concurrent executable family is not exact")
    paired_members = (
        "paired-control:feature",
        "paired-control:opposite",
    )
    return (
        _multiplicity_registration(
            criterion_id="D02-opposite-sign-uncertainty",
            family_id=f"family:{configuration}:paired-controls-v1",
            member_id="paired-control:opposite",
            ordered_member_ids=paired_members,
        ),
        _multiplicity_registration(
            criterion_id="E01-familywise-selection",
            family_id=P1_STU0061_ANALOG_FAMILY.family_id,
            member_id=subject,
            ordered_member_ids=family_members,
        ),
    )


def build_analog_replay_multiplicity_results(
    *,
    calculation: Mapping[str, Any],
    registrations: Sequence[Mapping[str, object]],
    statistical_bindings: Mapping[str, Mapping[str, object]] | None = None,
) -> tuple[dict[str, object], ...]:
    """Bind validator rows to the raw and synchronized familywise inference."""

    metrics = calculation.get("metrics")
    statistics = calculation.get("statistics")
    if not isinstance(metrics, Mapping) or not isinstance(statistics, Mapping):
        raise ValueError("analog multiplicity calculation is incomplete")
    normalized_registrations = tuple(registrations)
    registration_by_criterion: dict[str, Mapping[str, object]] = {}
    for registration in normalized_registrations:
        if not isinstance(registration, Mapping):
            raise ValueError("analog multiplicity registration is malformed")
        criterion_id = _ascii(
            "analog multiplicity criterion_id",
            registration.get("criterion_id"),
        )
        if criterion_id in registration_by_criterion:
            raise ValueError("analog multiplicity criterion is duplicated")
        registration_by_criterion[criterion_id] = registration
    expected_criteria = {
        "D02-opposite-sign-uncertainty",
        "E01-familywise-selection",
    }
    if set(registration_by_criterion) != expected_criteria:
        raise ValueError("analog multiplicity registration inventory drifted")

    default_bindings = {
        criterion_id: {
            "family_id": registration["family_id"],
            "member_id": registration["member_id"],
            "ordered_member_ids": sorted(
                str(value)
                for value in registration["ordered_member_ids"]  # type: ignore[index]
            ),
        }
        for criterion_id, registration in registration_by_criterion.items()
    }
    bindings = default_bindings if statistical_bindings is None else statistical_bindings
    if set(bindings) != expected_criteria:
        raise ValueError("analog statistical family binding inventory drifted")
    specifications = {
        "D02-opposite-sign-uncertainty": (
            "paired_control_family",
            "registered_control_contrast",
            "opposite_sign_pvalue_upper_ppm",
        ),
        "E01-familywise-selection": (
            "selection_family",
            "selection_aware_signal_evidence",
            "selection_aware_pvalue_ppm",
        ),
    }
    results: list[dict[str, object]] = []
    for criterion_id in sorted(expected_criteria):
        registration = registration_by_criterion[criterion_id]
        binding = bindings[criterion_id]
        if not isinstance(binding, Mapping):
            raise ValueError("analog statistical family binding is malformed")
        family_id = _ascii(
            "analog statistical family_id",
            binding.get("family_id"),
        )
        member_id = _ascii(
            "analog statistical member_id",
            binding.get("member_id"),
        )
        raw_members = binding.get("ordered_member_ids")
        if not isinstance(raw_members, (list, tuple)):
            raise ValueError("analog statistical family members are malformed")
        members = tuple(
            _ascii("analog statistical family member", value)
            for value in raw_members
        )
        if (
            not members
            or members != tuple(sorted(set(members)))
            or member_id not in members
        ):
            raise ValueError("analog statistical family membership drifted")

        statistic_key, claim_id, metric_id = specifications[criterion_id]
        manifest = statistics.get(statistic_key)
        if not isinstance(manifest, Mapping):
            raise ValueError("analog statistical family manifest is absent")
        plan = manifest.get("plan")
        hypotheses = manifest.get("hypotheses")
        if not isinstance(plan, Mapping) or not isinstance(hypotheses, list):
            raise ValueError("analog statistical family manifest is malformed")
        plan_hypotheses = plan.get("hypotheses")
        if not isinstance(plan_hypotheses, list):
            raise ValueError("analog statistical family plan is malformed")
        plan_members = tuple(
            item.get("hypothesis_id")
            for item in plan_hypotheses
            if isinstance(item, Mapping)
        )
        result_members = tuple(
            item.get("hypothesis_id")
            for item in hypotheses
            if isinstance(item, Mapping)
        )
        if (
            len(plan_members) != len(plan_hypotheses)
            or len(result_members) != len(hypotheses)
            or plan.get("family_id") != family_id
            or plan.get("family_size") != len(members)
            or plan_members != members
            or result_members != members
        ):
            raise ValueError("analog statistical family plan binding drifted")
        matches = [
            item
            for item in hypotheses
            if isinstance(item, Mapping)
            and item.get("hypothesis_id") == member_id
            and item.get("family_id") == family_id
            and item.get("family_size") == len(members)
        ]
        if len(matches) != 1:
            raise ValueError("analog statistical subject hypothesis is absent")
        hypothesis = matches[0]
        raw = hypothesis.get("raw")
        familywise = hypothesis.get("familywise")
        synchronized = (
            None
            if not isinstance(familywise, Mapping)
            else familywise.get("synchronized_max")
        )
        raw_pvalue = (
            None
            if not isinstance(raw, Mapping)
            else raw.get("monte_carlo_upper_pvalue_ppm")
        )
        adjusted_pvalue = (
            None
            if not isinstance(synchronized, Mapping)
            else synchronized.get("monte_carlo_upper_pvalue_ppm")
        )
        claim_metrics = metrics.get(claim_id)
        measured = (
            None
            if not isinstance(claim_metrics, Mapping)
            else claim_metrics.get(metric_id)
        )
        if (
            type(raw_pvalue) is not int
            or type(adjusted_pvalue) is not int
            or not 0 <= raw_pvalue <= adjusted_pvalue <= 1_000_000
            or measured != adjusted_pvalue
        ):
            raise ValueError("analog synchronized p-value binding drifted")
        results.append(
            {
                **registration,
                "adjusted_pvalue_ppm": adjusted_pvalue,
                "raw_pvalue_ppm": raw_pvalue,
            }
        )
    return tuple(results)


def build_analog_replay_validation_plan(
    *,
    mission_id: str,
    executable_id: str,
    output_names: Mapping[str, str],
) -> dict[str, object]:
    mapping = analog_family_executable_map(P1_STU0061_ANALOG_FAMILY)
    try:
        configuration = mapping[executable_id]
    except KeyError as exc:
        raise ValueError(
            "analog validation subject is outside the exact family"
        ) from exc
    registrations = analog_replay_multiplicity_registrations(
        subject_executable_id=executable_id,
        subject_configuration_id=configuration.configuration_id,
        ordered_family_executable_ids=tuple(mapping),
    )
    profile = {
        "decisive_risk_criterion_ids": [],
        "multiplicity": list(registrations),
        "promotion_criterion_ids": [],
        "schema": SCIENTIFIC_ADJUDICATION_PROFILE_SCHEMA,
    }
    proof_requirements = proof_requirements_for_modes(
        evidence_modes=ANALOG_REPLAY_EVIDENCE_MODES,
        output_names={
            ATOMIC_TRACE_PROOF_KIND: output_names["trace"],
            CALCULATION_PROOF_KIND: output_names["calculation"],
        },
        proof_protocol_id=ANALOG_STATE_TRACE_PROTOCOL_ID,
    )
    return build_validation_plan_v2(
        mission_id=_ascii("mission_id", mission_id),
        executable_id=_ascii("executable_id", executable_id),
        evidence_depth=EVIDENCE_DEPTH,
        planned_claims=ANALOG_REPLAY_CLAIMS,
        evidence_modes=ANALOG_REPLAY_EVIDENCE_MODES,
        criteria=ANALOG_REPLAY_CRITERIA,
        adjudication_profile=profile,
        proof_requirements=proof_requirements,
        candidate_eligible_on_pass=False,
    )


@dataclass(frozen=True, slots=True)
class AnalogReplayPlan:
    mission_id: str
    study_id: str
    configuration: AnalogFamilyConfiguration
    executable_id: str
    output_name_items: tuple[tuple[str, str], ...]
    plan: Mapping[str, object]

    @property
    def output_names(self) -> dict[str, str]:
        return dict(self.output_name_items)

    @property
    def plan_hash(self) -> str:
        return sha256(canonical_bytes(self.plan)).hexdigest()

    def expected_outputs(
        self,
        *,
        produce_family_cache: bool = False,
    ) -> tuple[str, ...]:
        values = set(self.output_names.values())
        if produce_family_cache:
            values.add(ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME)
        return tuple(sorted(values))

    def expected_output_classes(
        self,
        *,
        produce_family_cache: bool = False,
    ) -> dict[str, str]:
        return {
            output_name: (
                "reproducible_cache"
                if output_name == ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME
                else "durable_evidence"
            )
            for output_name in self.expected_outputs(
                produce_family_cache=produce_family_cache
            )
        }

    def job_input_hashes(
        self,
        *,
        family_trace_cache_hash: str | None = None,
        family_trace_manifest_hash: str | None = None,
    ) -> tuple[str, ...]:
        values = {
            DATASET_SHA256,
            OBSERVED_MATERIAL_ID,
            ROLLING_SPLIT_SHA256,
            self.plan_hash,
            analog_family_implementation_sha256(),
            analog_replay_implementation_sha256(),
            analog_trace_implementation_sha256(),
            discovery_implementation_sha256(),
            loader_implementation_sha256(),
            selection_inference_implementation_sha256(),
        }
        if (family_trace_cache_hash is None) != (
            family_trace_manifest_hash is None
        ):
            raise ValueError(
                "analog family cache and producer trace hashes are inseparable"
            )
        if family_trace_cache_hash is not None:
            bound_hashes: list[str] = []
            for name, value in (
                ("analog family trace cache hash", family_trace_cache_hash),
                (
                    "analog family trace producer manifest hash",
                    family_trace_manifest_hash,
                ),
            ):
                digest = _ascii(name, value)
                if len(digest) != 64 or any(
                    character not in "0123456789abcdef"
                    for character in digest
                ):
                    raise ValueError(f"{name} must be lowercase SHA-256")
                bound_hashes.append(digest)
            if bound_hashes[0] == bound_hashes[1]:
                raise ValueError(
                    "analog family cache and producer trace hashes must differ"
                )
            values.update(bound_hashes)
        return tuple(sorted(values))

    def scientific_binding(self) -> dict[str, object]:
        return {
            "evidence_depth": EVIDENCE_DEPTH,
            "evidence_modes": list(ANALOG_REPLAY_EVIDENCE_MODES),
            "planned_claims": list(ANALOG_REPLAY_CLAIMS),
            "result_manifest_output": self.output_names["result"],
            "validation_plan_hash": self.plan_hash,
            "validator_id": SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
        }


def build_analog_replay_plan(
    *,
    mission_id: str,
    study_id: str,
    executable_id: str,
) -> AnalogReplayPlan:
    mapping = analog_family_executable_map(P1_STU0061_ANALOG_FAMILY)
    try:
        configuration = mapping[executable_id]
    except KeyError as exc:
        raise ValueError("analog replay subject is outside the exact family") from exc
    names = analog_replay_output_names(executable_id, study_id=study_id)
    plan = build_analog_replay_validation_plan(
        mission_id=mission_id,
        executable_id=executable_id,
        output_names=names,
    )
    return AnalogReplayPlan(
        mission_id=mission_id,
        study_id=study_id,
        configuration=configuration,
        executable_id=executable_id,
        output_name_items=tuple(sorted(names.items())),
        plan=plan,
    )


def _trade_rows(
    *,
    configuration: AnalogFamilyConfiguration,
    executable_id: str,
    simulations: Mapping[tuple[str, str], Any],
    frame: pd.DataFrame,
    effective_spread: np.ndarray,
) -> list[dict[str, object]]:
    return _shared_trade_rows(
        configuration=configuration,
        executable_id=executable_id,
        simulations=simulations,
        frame=frame,
        effective_spread=effective_spread,
    )


def _intent_rows(
    *,
    configuration: AnalogFamilyConfiguration,
    executable_id: str,
    simulations: Mapping[tuple[str, str], Any],
    frame: pd.DataFrame,
    effective_spread: np.ndarray,
) -> list[dict[str, object]]:
    return _shared_intent_rows(
        configuration=configuration,
        executable_id=executable_id,
        simulations=simulations,
        frame=frame,
        effective_spread=effective_spread,
    )


def compute_analog_family_trace(
    repository_root: str | Path,
) -> tuple[dict[str, object], dict[str, dict[str, int]]]:
    """Compute the exact family once without Mission, Job, or subject fields."""

    _validate_engine_environment()
    data = load_observed_development(Path(repository_root).resolve())
    _validate_production_data(data)
    folds = _fold_payloads(data)
    _validate_fold_payloads(data.frame, folds)
    frame = data.frame
    time = pd.to_datetime(frame["time"], errors="raise")
    spread = causal_effective_spread(
        frame["spread"].to_numpy(float),
        _time_ns(frame),
    )
    prefix_frames: dict[str, pd.DataFrame] = {}
    prefix_spreads: dict[str, np.ndarray] = {}
    windows: list[dict[str, object]] = []
    for fold in folds:
        fold_id = str(fold["fold_id"])
        test = fold["test_oos"]
        prefix_end = int(
            time.searchsorted(pd.Timestamp(test["end"]), side="right")
        )
        prefix_frames[fold_id] = frame.iloc[:prefix_end]
        prefix_spreads[fold_id] = causal_effective_spread(
            prefix_frames[fold_id]["spread"].to_numpy(float),
            _time_ns(prefix_frames[fold_id]),
        )
        eligible_dates = tuple(
            sorted(
                pd.DatetimeIndex(
                    time[
                        (time >= pd.Timestamp(test["start"]))
                        & (time <= pd.Timestamp(test["end"]))
                    ]
                )
                .normalize()
                .strftime("%Y-%m-%d")
                .unique()
            )
        )
        windows.append(
            {
                "eligible_dates": list(eligible_dates),
                "fold_id": fold_id,
                "test_end": _iso(test["end"]),
                "test_start": _iso(test["start"]),
                "train_end": _iso(fold["train_is"]["end"]),
                "train_start": _iso(fold["train_is"]["start"]),
            }
        )
    feature_sets: dict[str, dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]] = {}
    prefix_sets: dict[str, dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]] = {}
    calibrations: dict[str, dict[str, tuple[float, tuple[float, float], float]]] = {}
    comparisons_by_key: dict[tuple[str, str], dict[str, object]] = {}
    for profile in P1_STU0061_ANALOG_FAMILY.profiles:
        profile_id = profile.profile_id
        feature_sets[profile_id] = {}
        prefix_sets[profile_id] = {}
        calibrations[profile_id] = {}
        for fold in folds:
            fold_id = str(fold["fold_id"])
            train = fold["train_is"]
            start = pd.Timestamp(train["start"])
            end = pd.Timestamp(train["end"])
            full = fit_fold_analog_family(
                frame,
                family=P1_STU0061_ANALOG_FAMILY,
                profile_id=profile_id,
                train_start=start,
                train_end=end,
            )
            prefix = fit_fold_analog_family(
                prefix_frames[fold_id],
                family=P1_STU0061_ANALOG_FAMILY,
                profile_id=profile_id,
                train_start=start,
                train_end=end,
            )
            feature_sets[profile_id][fold_id] = full
            prefix_sets[profile_id][fold_id] = prefix
            train_mask = ((time >= start) & (time <= end)).to_numpy()
            prefix_time = pd.to_datetime(
                prefix_frames[fold_id]["time"], errors="raise"
            )
            prefix_train_mask = (
                (prefix_time >= start) & (prefix_time <= end)
            ).to_numpy()
            volatility = full[1][train_mask & np.isfinite(full[1])]
            cutoffs = (
                float(np.quantile(volatility, 1 / 3, method="higher")),
                float(np.quantile(volatility, 2 / 3, method="higher")),
            )
            calibrations[profile_id][fold_id] = (
                calibrate_analog_selector(
                    full[0],
                    train_mask,
                    selector_quantile_bp=(
                        P1_STU0061_ANALOG_FAMILY.selector_quantile_bp
                    ),
                ),
                cutoffs,
                calibrate_analog_selector(
                    prefix[0],
                    prefix_train_mask,
                    selector_quantile_bp=(
                        P1_STU0061_ANALOG_FAMILY.selector_quantile_bp
                    ),
                ),
            )
            compared = len(prefix[0])
            full_causal_surfaces = (
                ("score", full[0][:compared]),
                ("volatility", full[1][:compared]),
                ("run", full[2][:compared]),
                ("effective_spread", spread[:compared]),
            )
            prefix_causal_surfaces = (
                ("score", prefix[0]),
                ("volatility", prefix[1]),
                ("run", prefix[2]),
                ("effective_spread", prefix_spreads[fold_id]),
            )
            comparisons_by_key[(fold_id, profile_id)] = {
                "compared_row_count": compared,
                "fold_id": fold_id,
                # Historical field names are retained as an opaque schema.
                "full_score_values_sha256": _digest_causal_surfaces(
                    full_causal_surfaces
                ),
                "prefix_score_values_sha256": _digest_causal_surfaces(
                    prefix_causal_surfaces
                ),
                "profile_id": profile_id,
            }
    all_trades: list[dict[str, object]] = []
    all_intents: list[dict[str, object]] = []
    legacy_metrics: dict[str, dict[str, int]] = {}
    for configuration in P1_STU0061_ANALOG_FAMILY.configurations():
        subject_executable = analog_family_executable(configuration).identity
        captures: dict[tuple[str, str], Any] = {}

        def capture_simulation(**kwargs: Any) -> Any:
            result = simulate_fixed_hold(**kwargs)
            fold_id = str(kwargs["fold_id"])
            scope = "full" if kwargs["frame"] is frame else "prefix"
            key = (fold_id, scope)
            if key in captures:
                raise RuntimeError("analog simulation capture is not unique")
            captures[key] = result
            return result

        result = _evaluate_configuration(
            calibrations=calibrations[configuration.profile_id],
            frame=frame,
            features=feature_sets[configuration.profile_id][str(folds[0]["fold_id"])],
            fold_features=feature_sets[configuration.profile_id],
            folds=folds,
            configuration=configuration,
            effective_spread=spread,
            prefix_features=prefix_sets[configuration.profile_id],
            prefix_spreads=prefix_spreads,
            time=time,
            executable_id=subject_executable,
            simulation_fn=capture_simulation,
        )
        expected_capture_keys = {
            (str(fold["fold_id"]), scope)
            for fold in folds
            for scope in ("full", "prefix")
        }
        if set(captures) != expected_capture_keys:
            raise RuntimeError("analog simulation trace capture is incomplete")
        legacy_metrics[subject_executable] = dict(result.metrics)
        all_trades.extend(
            _trade_rows(
                configuration=configuration,
                executable_id=subject_executable,
                simulations=captures,
                frame=frame,
                effective_spread=spread,
            )
        )
        all_intents.extend(
            _intent_rows(
                configuration=configuration,
                executable_id=subject_executable,
                simulations=captures,
                frame=frame,
                effective_spread=spread,
            )
        )
    all_trades.sort(
        key=lambda item: (
            str(item["configuration_id"]),
            str(item["fold_id"]),
            str(item["decision_time"]),
            str(item["observation_id"]),
        )
    )
    all_intents.sort(
        key=lambda item: (
            str(item["configuration_id"]),
            str(item["fold_id"]),
            str(item["scope"]),
            int(item["ordinal"]),
            str(item["observation_id"]),
        )
    )
    eligible_rows: list[dict[str, object]] = []
    trade_aggregates: dict[tuple[str, str, str], list[int]] = {}
    for trade in all_trades:
        key = (
            str(trade["configuration_id"]),
            str(trade["fold_id"]),
            str(trade["decision_time"])[:10],
        )
        values = trade_aggregates.setdefault(key, [0, 0, 0])
        values[0] += 1
        values[1] += int(trade["native_net_pnl_micropoints"])
        values[2] += int(trade["stress_net_pnl_micropoints"])
    inventory = expected_analog_family_inventory()
    member_by_configuration = {
        str(item["configuration_id"]): item for item in inventory
    }
    for configuration_id in sorted(member_by_configuration):
        member = member_by_configuration[configuration_id]
        for window in windows:
            for day in window["eligible_dates"]:
                values = trade_aggregates.get(
                    (configuration_id, str(window["fold_id"]), str(day)),
                    [0, 0, 0],
                )
                eligible_rows.append(
                    {
                        "configuration_id": configuration_id,
                        "date": day,
                        "entry_count": values[0],
                        "executable_id": member["executable_id"],
                        "fold_id": window["fold_id"],
                        "native_net_pnl_micropoints": values[1],
                        "stress_net_pnl_micropoints": values[2],
                    }
                )
    comparisons = [
        comparisons_by_key[(str(window["fold_id"]), profile.profile_id)]
        for window in windows
        for profile in P1_STU0061_ANALOG_FAMILY.profiles
    ]
    contracts = analog_family_execution_contracts()
    trace = {
        "attribution": ANALOG_REPLAY_TRACE_ATTRIBUTION,
        "clock_contract": contracts["clock_contract"],
        "controls": ANALOG_REPLAY_CONTROLS,
        "cost_contract": contracts["cost_contract"],
        "dataset_sha256": DATASET_SHA256,
        "eligible_day_observations": eligible_rows,
        "family_id": P1_STU0061_ANALOG_FAMILY.family_id,
        "implementation_identities": (
            analog_family_trace_implementation_identities()
        ),
        "intent_observations": all_intents,
        "invariance_comparisons": comparisons,
        "material_identity": OBSERVED_MATERIAL_ID,
        "ordered_family": list(inventory),
        "original_family_provenance": analog_original_family_provenance(),
        "protocol_id": ANALOG_STATE_TRACE_PROTOCOL_ID,
        "schema": ANALOG_FAMILY_TRACE_SCHEMA,
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "trade_observations": all_trades,
        "windows": windows,
    }
    canonical_bytes(trace)
    validate_analog_family_trace(trace)
    assert_frozen_stu0061_raw_metric_parity(legacy_metrics)
    return trace, legacy_metrics


def compute_analog_replay_trace(
    repository_root: str | Path,
    *,
    mission_id: str,
    executable_id: str,
    job_id: str,
    job_hash: str,
) -> tuple[dict[str, object], dict[str, dict[str, int]]]:
    """Compatibility wrapper: compute once, then bind one exact subject."""

    family_trace, legacy_metrics = compute_analog_family_trace(repository_root)
    return (
        bind_analog_family_trace(
            family_trace=family_trace,
            mission_id=mission_id,
            executable_id=executable_id,
            job_id=job_id,
            job_hash=job_hash,
        ),
        legacy_metrics,
    )


def build_analog_family_trace_cache_manifest(
    *,
    replay_plan: AnalogReplayPlan,
    execution: RunningJobExecution,
    cache_sha256: str,
) -> dict[str, object]:
    """Bind neutral cache bytes to the exact authorized first Job execution."""

    if not isinstance(replay_plan, AnalogReplayPlan) or not isinstance(
        execution,
        RunningJobExecution,
    ):
        raise TypeError("analog family cache manifest inputs are invalid")
    producer_executable_id = str(
        expected_analog_family_inventory()[0]["executable_id"]
    )
    if replay_plan.executable_id != producer_executable_id:
        raise ValueError("analog family cache producer is not the first member")
    digest = _ascii("analog family cache sha256", cache_sha256)
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ValueError("analog family cache sha256 is invalid")
    value = {
        "cache_output_name": ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME,
        "cache_schema": ANALOG_FAMILY_TRACE_SCHEMA,
        "cache_sha256": digest,
        "claim_authority": False,
        "dataset_sha256": DATASET_SHA256,
        "family_id": P1_STU0061_ANALOG_FAMILY.family_id,
        "implementation_identities": (
            analog_family_trace_implementation_identities()
        ),
        "manifest_output_name": replay_plan.output_names["trace"],
        "material_identity": OBSERVED_MATERIAL_ID,
        "mission_id": replay_plan.mission_id,
        "producer_executable_id": producer_executable_id,
        "producer_execution": {
            **execution.payload(),
            "identity": execution.identity,
        },
        "schema": ANALOG_FAMILY_TRACE_CACHE_MANIFEST_SCHEMA,
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "study_id": replay_plan.study_id,
    }
    validate_analog_family_trace_cache_manifest(value)
    canonical_bytes(value)
    return value


@dataclass(frozen=True, slots=True)
class AnalogFamilyTraceCache:
    content: bytes
    produced: bool
    sha256: str

    def __post_init__(self) -> None:
        if type(self.content) is not bytes or type(self.produced) is not bool:
            raise ValueError("analog family trace cache value is invalid")
        if (
            type(self.sha256) is not str
            or len(self.sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.sha256
            )
            or sha256(self.content).hexdigest() != self.sha256
        ):
            raise ValueError("analog family trace cache content hash drifted")

    def trace(self) -> dict[str, object]:
        value = parse_canonical(self.content)
        if not isinstance(value, dict):
            raise ValueError("analog family trace cache is not an object")
        return validate_analog_family_trace(value)


def _materialize_analog_family_trace_cache(
    repository_root: Path,
    *,
    content: bytes,
) -> None:
    publish_reproducible_cache(
        repository_root=repository_root,
        relative_path=ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME,
        content=content,
    )


def load_or_compute_analog_family_trace(
    repository_root: str | Path,
    *,
    produce_family_cache: bool,
    input_hashes: Sequence[str] = (),
) -> AnalogFamilyTraceCache:
    """Produce the neutral cache once or open one exact declared cache input."""

    if type(produce_family_cache) is not bool:
        raise ValueError("analog family trace producer signal must be boolean")
    root = Path(repository_root).resolve()
    if produce_family_cache:
        family_trace, _ = compute_analog_family_trace(root)
        normalized = validate_analog_family_trace(family_trace)
        content = canonical_bytes(normalized)
        _materialize_analog_family_trace_cache(root, content=content)
        return AnalogFamilyTraceCache(
            content=content,
            produced=True,
            sha256=sha256(content).hexdigest(),
        )
    target = analog_family_trace_cache_path(root)
    if not target.is_file():
        raise ValueError("analog family trace cache is unavailable")
    content = target.read_bytes()
    digest = sha256(content).hexdigest()
    if tuple(input_hashes).count(digest) != 1:
        raise ValueError(
            "analog family trace cache hash must be exactly one Job input"
        )
    try:
        value = parse_canonical(content)
    except (TypeError, ValueError) as exc:
        raise ValueError("analog family trace cache is not canonical") from exc
    if not isinstance(value, dict) or canonical_bytes(value) != content:
        raise ValueError("analog family trace cache bytes are not canonical")
    normalized = validate_analog_family_trace(value)
    if canonical_bytes(normalized) != content:
        raise ValueError("analog family trace cache normalization drifted")
    return AnalogFamilyTraceCache(
        content=content,
        produced=False,
        sha256=digest,
    )


def _advertises_analog_family_cache_manifest(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    attribution = value.get("attribution")
    family_binding = (
        attribution.get("family_trace_binding")
        if isinstance(attribution, Mapping)
        else None
    )
    cache_manifest = (
        family_binding.get("cache_manifest")
        if isinstance(family_binding, Mapping)
        else None
    )
    return isinstance(cache_manifest, Mapping) and (
        value.get("schema") == SCIENTIFIC_EVALUATION_TRACE_SCHEMA
        or cache_manifest.get("schema")
        == ANALOG_FAMILY_TRACE_CACHE_MANIFEST_SCHEMA
    )


def verify_analog_family_trace_cache_producer(
    context: AnalogReplayJobContext,
    *,
    replay_plan: AnalogReplayPlan,
    repository_root: str | Path,
    input_hashes: Sequence[str],
    materialize_missing: bool = True,
) -> tuple[AnalogFamilyTraceCache, str, dict[str, object]]:
    """Recover cache bytes only from the completed durable producer trace."""

    if not isinstance(replay_plan, AnalogReplayPlan):
        raise TypeError("analog family cache producer inputs are invalid")
    if type(materialize_missing) is not bool:
        raise ValueError("analog family cache materialization signal is invalid")
    root = Path(repository_root).resolve()
    inputs = tuple(input_hashes)
    matches: list[
        tuple[str, AnalogFamilyTraceCache, dict[str, object]]
    ] = []
    for input_hash in dict.fromkeys(inputs):
        try:
            content = context.evidence.read_verified(input_hash)
            value = parse_canonical(content)
        except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError):
            continue
        if not _advertises_analog_family_cache_manifest(value):
            continue
        if not isinstance(value, dict) or canonical_bytes(value) != content:
            raise ValueError(
                "analog family cache producer trace is not canonical"
            )
        try:
            neutral, manifest = extract_analog_family_trace_cache_material(
                value,
                require_producer=True,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "analog family cache producer trace is invalid"
            ) from exc
        neutral_content = canonical_bytes(neutral)
        family_cache = AnalogFamilyTraceCache(
            content=neutral_content,
            produced=False,
            sha256=str(manifest["cache_sha256"]),
        )
        matches.append((input_hash, family_cache, manifest))
    if len(matches) != 1:
        raise ValueError(
            "Job inputs require one exact analog family cache producer trace"
        )
    manifest_hash, family_cache, manifest = matches[0]
    if inputs.count(family_cache.sha256) != 1:
        raise ValueError(
            "analog family trace cache hash must be exactly one Job input"
        )
    if inputs.count(manifest_hash) != 1:
        raise ValueError(
            "analog family cache producer trace must be exactly one Job input"
        )
    producer_executable_id = str(
        expected_analog_family_inventory()[0]["executable_id"]
    )
    producer_plan = build_analog_replay_plan(
        mission_id=replay_plan.mission_id,
        study_id=replay_plan.study_id,
        executable_id=producer_executable_id,
    )
    if (
        manifest.get("cache_output_name")
        != ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME
        or manifest.get("cache_sha256") != family_cache.sha256
        or manifest.get("mission_id") != replay_plan.mission_id
        or manifest.get("study_id") != replay_plan.study_id
        or manifest.get("producer_executable_id")
        != producer_executable_id
        or manifest.get("manifest_output_name")
        != producer_plan.output_names["trace"]
    ):
        raise ValueError("analog family cache producer manifest is out of scope")
    producer_payload = manifest.get("producer_execution")
    if not isinstance(producer_payload, Mapping):
        raise ValueError("analog family cache producer execution is invalid")
    producer = RunningJobExecution.from_mapping(
        {
            name: producer_payload[name]
            for name in (
                "job_hash",
                "job_id",
                "job_permit_id",
                "start_record_id",
            )
        }
    )
    if producer_payload.get("identity") != producer.identity:
        raise ValueError("analog family cache producer identity is invalid")
    context.verify_reproducible_cache_producer(
        producer,
        cache_output_name=ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME,
        cache_hash=family_cache.sha256,
        expected_callable_identity=CALLABLE_IDENTITY,
        expected_evidence_subject={
            "kind": "Executable",
            "id": producer_executable_id,
        },
        expected_output_classes=producer_plan.expected_output_classes(
            produce_family_cache=True
        ),
        expected_study_id=replay_plan.study_id,
        manifest_output_name=producer_plan.output_names["trace"],
        manifest_hash=manifest_hash,
    )
    target = analog_family_trace_cache_path(root)
    if target.exists() or materialize_missing:
        _materialize_analog_family_trace_cache(
            root,
            content=family_cache.content,
        )
    return family_cache, manifest_hash, manifest


def build_analog_replay_measurement(
    *,
    replay_plan: AnalogReplayPlan,
    job_id: str,
    job_hash: str,
    calculation: Mapping[str, Any],
    trace_hash: str,
    calculation_hash: str,
) -> dict[str, object]:
    requirements = parse_proof_requirements(
        replay_plan.plan["proof_requirements"],
        evidence_modes=ANALOG_REPLAY_EVIDENCE_MODES,
    )
    profile = replay_plan.plan.get("adjudication_profile")
    registrations = (
        None if not isinstance(profile, Mapping) else profile.get("multiplicity")
    )
    if not isinstance(registrations, list):
        raise ValueError("analog validation multiplicity plan is malformed")
    multiplicity = build_analog_replay_multiplicity_results(
        calculation=calculation,
        registrations=registrations,
    )
    value = {
        "evidence_depth": EVIDENCE_DEPTH,
        "evidence_modes": list(ANALOG_REPLAY_EVIDENCE_MODES),
        "executable_id": replay_plan.executable_id,
        "job_hash": job_hash,
        "job_id": job_id,
        "metrics": calculation["metrics"],
        "mission_id": replay_plan.mission_id,
        "multiplicity": list(multiplicity),
        "proofs": list(
            build_proof_references(
                requirements=requirements,
                artifact_hashes={
                    replay_plan.output_names["trace"]: trace_hash,
                    replay_plan.output_names["calculation"]: calculation_hash,
                },
            )
        ),
        "schema": SCIENTIFIC_MEASUREMENT_V2_SCHEMA,
    }
    canonical_bytes(value)
    return value


def build_analog_replay_result(
    *,
    replay_plan: AnalogReplayPlan,
    job_id: str,
    job_hash: str,
    measurement_hash: str,
) -> dict[str, object]:
    value = {
        "evidence_depth": EVIDENCE_DEPTH,
        "executable_id": replay_plan.executable_id,
        "job_hash": job_hash,
        "job_id": job_id,
        "mission_id": replay_plan.mission_id,
        "observations": [
            {
                "claim_id": claim_id,
                "measurement_artifact_hash": measurement_hash,
            }
            for claim_id in ANALOG_REPLAY_CLAIMS
        ],
        "schema": SCIENTIFIC_RESULT_SCHEMA,
    }
    canonical_bytes(value)
    return value


@dataclass(frozen=True, slots=True)
class AnalogReplayJobPacket:
    adjudication_state: str
    output_manifest: tuple[tuple[str, str], ...]

    def outputs(self) -> dict[str, str]:
        return dict(self.output_manifest)


def execute_analog_replay_job(
    *,
    repository_root: str | Path,
    execution: RunningJobExecution,
) -> AnalogReplayJobPacket:
    root = Path(repository_root).resolve()
    context = RunningJobExecutionContext(root)
    binding = context.verify_running_job_execution(
        execution,
        expected_callable_identity=CALLABLE_IDENTITY,
    )
    subject = binding["spec"].get("evidence_subject")
    if not isinstance(subject, Mapping) or subject.get("kind") != "Executable":
        raise ValueError("analog replay Job subject is invalid")
    replay_plan = build_analog_replay_plan(
        mission_id=str(binding["mission_id"]),
        study_id=str(binding["study_id"]),
        executable_id=str(subject.get("id")),
    )
    expected_outputs = set(binding["spec"].get("expected_outputs", []))
    output_classes = binding["spec"].get("output_classes")
    produce_family_cache = (
        ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME in expected_outputs
    )
    producer_executable_id = str(
        expected_analog_family_inventory()[0]["executable_id"]
    )
    if produce_family_cache != (
        replay_plan.executable_id == producer_executable_id
    ):
        raise ValueError(
            "analog replay family cache producer must be the first member"
        )
    if (
        expected_outputs
        != set(
            replay_plan.expected_outputs(
                produce_family_cache=produce_family_cache
            )
        )
        or output_classes
        != replay_plan.expected_output_classes(
            produce_family_cache=produce_family_cache
        )
    ):
        raise ValueError("analog replay Job output contract drifted")
    input_hashes = tuple(binding["spec"].get("input_hashes", []))
    if not set(replay_plan.job_input_hashes()).issubset(
        set(input_hashes)
    ):
        raise ValueError("analog replay Job inputs omit a registered dependency")
    if produce_family_cache:
        family_cache = load_or_compute_analog_family_trace(
            root,
            produce_family_cache=True,
            input_hashes=input_hashes,
        )
        cache_manifest = build_analog_family_trace_cache_manifest(
            replay_plan=replay_plan,
            execution=execution,
            cache_sha256=family_cache.sha256,
        )
    else:
        (
            family_cache,
            _,
            cache_manifest,
        ) = verify_analog_family_trace_cache_producer(
            context,
            replay_plan=replay_plan,
            repository_root=root,
            input_hashes=input_hashes,
            materialize_missing=True,
        )
    cached_trace = parse_canonical(family_cache.content)
    if (
        not isinstance(cached_trace, dict)
        or canonical_bytes(cached_trace) != family_cache.content
    ):
        raise ValueError("analog family trace cache bytes are not canonical")
    trace = bind_analog_family_trace(
        family_trace=cached_trace,
        mission_id=replay_plan.mission_id,
        executable_id=replay_plan.executable_id,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
        cache_manifest=cache_manifest,
    )
    names = replay_plan.output_names
    trace_hash = context.evidence.finalize(canonical_bytes(trace)).sha256
    calculation = build_analog_trace_calculation(
        trace=trace,
        trace_output_name=names["trace"],
        trace_hash=trace_hash,
    )
    calculation_hash = context.evidence.finalize(
        canonical_bytes(calculation)
    ).sha256
    measurement = build_analog_replay_measurement(
        replay_plan=replay_plan,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
        calculation=calculation,
        trace_hash=trace_hash,
        calculation_hash=calculation_hash,
    )
    measurement_hash = context.evidence.finalize(
        canonical_bytes(measurement)
    ).sha256
    result = build_analog_replay_result(
        replay_plan=replay_plan,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
        measurement_hash=measurement_hash,
    )
    outputs = {
        names["calculation"]: calculation_hash,
        names["measurement"]: measurement_hash,
        names["plan"]: context.evidence.finalize(
            canonical_bytes(replay_plan.plan)
        ).sha256,
        names["result"]: context.evidence.finalize(
            canonical_bytes(result)
        ).sha256,
        names["trace"]: trace_hash,
    }
    if family_cache.produced:
        outputs[ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME] = family_cache.sha256
    if set(outputs) != expected_outputs:
        raise ValueError("analog replay Job materialized undeclared outputs")
    adjudication = adjudicate_plan_measurement(replay_plan.plan, measurement)
    return AnalogReplayJobPacket(
        adjudication_state=adjudication.state,
        output_manifest=tuple(sorted(outputs.items())),
    )


__all__ = [
    "ANALOG_FAMILY_TRACE_CACHE_OUTPUT_NAME",
    "CALLABLE_IDENTITY",
    "FROZEN_STU0061_RAW_METRICS",
    "STU0061_REPLAY_CRITERION_IDS",
    "AnalogFamilyTraceCache",
    "AnalogReplayJobPacket",
    "AnalogReplayPlan",
    "analog_replay_multiplicity_registrations",
    "analog_replay_output_names",
    "analog_replay_implementation_sha256",
    "analog_family_trace_cache_output_name",
    "analog_family_trace_cache_path",
    "assert_frozen_stu0061_raw_metric_parity",
    "build_analog_family_trace_cache_manifest",
    "build_analog_replay_measurement",
    "build_analog_replay_multiplicity_results",
    "build_analog_replay_plan",
    "build_analog_replay_result",
    "build_analog_replay_validation_plan",
    "compute_analog_family_trace",
    "compute_analog_replay_trace",
    "execute_analog_replay_job",
    "load_or_compute_analog_family_trace",
    "verify_analog_family_trace_cache_producer",
    "validated_stu0061_recomputed_criterion_ids",
]
