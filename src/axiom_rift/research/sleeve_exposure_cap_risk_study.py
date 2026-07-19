"""Writer-gated scientific-v2 Job for the sleeve exposure-cap risk pair."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd
import scipy

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.running_job_context import (
    running_job_execution_context_implementation_sha256,
)
from axiom_rift.research.adjudication import (
    MULTIPLICITY_CRITERION_IDS,
    RISK_DIAGNOSTIC_CRITERION_IDS,
    VALIDITY_METRICS,
)
from axiom_rift.research.evidence_proofs import (
    build_proof_references,
    parse_proof_requirements,
    proof_requirements_for_modes,
)
from axiom_rift.research.prospective_pair_trace import (
    PROSPECTIVE_PAIR_CLAIMS,
    PROSPECTIVE_PAIR_EVIDENCE_MODES,
    PROSPECTIVE_PAIR_TRACE_PROTOCOL_ID,
    ProspectivePairProtocolDefinition,
    prospective_pair_control_contrast_id,
    prospective_pair_control_family_id,
    prospective_pair_trace_implementation_sha256,
)
from axiom_rift.research.replay_coverage import (
    validated_recomputed_criterion_ids,
)
from axiom_rift.research.scientific_study import discovery_criteria
from axiom_rift.research.scientific_trace import (
    ATOMIC_TRACE_PROOF_KIND,
    CALCULATION_PROOF_KIND,
)
from axiom_rift.research.selection_inference import (
    selection_inference_implementation_sha256,
)
from axiom_rift.research.sleeve_exposure_cap_risk_chassis import (
    sleeve_exposure_cap_risk_chassis_implementation_sha256,
)
from axiom_rift.research.sleeve_exposure_cap_risk_cache import (
    sleeve_exposure_cap_risk_cache_implementation_sha256,
    sleeve_exposure_cap_risk_cache_output_name,
    sleeve_exposure_cap_risk_cache_provenance_output_name,
)
from axiom_rift.research.sleeve_exposure_cap_risk_trace import (
    build_sleeve_exposure_cap_risk_protocol_definition,
    sleeve_exposure_cap_risk_trace_implementation_sha256,
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


EVIDENCE_DEPTH = "discovery"
PRIMARY_CONTROL_DELTA_METRIC = (
    "primary_control_delta_net_profit_micropoints"
)
PRIMARY_CONTROL_PVALUE_METRIC = "primary_control_pvalue_upper_ppm"
_THIS_FILE = Path(__file__).resolve()


def sleeve_exposure_cap_risk_study_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _job_input_digest(value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError("sleeve exposure-cap Job input identity is invalid")
    if len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    ):
        return value
    return sha256(value.encode("ascii")).hexdigest()


_EVIDENCE_MODE_BY_CRITERION = {
    "A01-minimum-trades": "cost_and_execution",
    "A02-positive-density": "cost_and_execution",
    "A03-profit-day-concentration": "cost_and_execution",
    "B01-positive-native-cost": "cost_and_execution",
    "B02-fold-profit-factor": "cost_and_execution",
    "B03-slippage-stress": "sensitivity_or_stress",
    "B04-monthly-realized-drawdown-share": "cost_and_execution",
    "C01-feature-prefix-invariance": "causal_contrast",
    "C02-decision-append-invariance": "causal_contrast",
    "C03-decision-time-causality": "causal_contrast",
    "C04-resolved-cost": "cost_and_execution",
    "C05-finite-metrics": "causal_contrast",
    "D03-primary-control": "causal_contrast",
    "D04-primary-control-uncertainty": "causal_contrast",
    "E01-familywise-selection": "temporal_stability",
    "F01-evaluable-folds": "temporal_stability",
    "F02-winning-folds": "temporal_stability",
    "F03-positive-regimes": "temporal_stability",
}


def _decision_role(item: Mapping[str, object]) -> str:
    if item["metric"] in VALIDITY_METRICS:
        return "validity"
    if item["criterion_id"] in MULTIPLICITY_CRITERION_IDS:
        return "multiplicity"
    if item["criterion_id"] in RISK_DIAGNOSTIC_CRITERION_IDS:
        return "risk_diagnostic"
    return "component"


def sleeve_exposure_cap_risk_criteria() -> tuple[dict[str, object], ...]:
    legacy = discovery_criteria(
        control_delta_metric=PRIMARY_CONTROL_DELTA_METRIC,
        control_pvalue_metric=PRIMARY_CONTROL_PVALUE_METRIC,
        include_opposite_sign=False,
    )
    by_id = {str(item["criterion_id"]): item for item in legacy}
    if set(by_id) != set(_EVIDENCE_MODE_BY_CRITERION) or len(legacy) != 18:
        raise RuntimeError("sleeve exposure-cap criterion inventory drifted")
    return tuple(
        {
            **item,
            "decision_role": _decision_role(item),
            "evidence_mode": _EVIDENCE_MODE_BY_CRITERION[str(item["criterion_id"])],
        }
        for item in sorted(
            legacy,
            key=lambda value: (str(value["claim_id"]), str(value["criterion_id"])),
        )
    )


SLEEVE_EXPOSURE_CAP_RISK_CRITERIA = sleeve_exposure_cap_risk_criteria()


def output_names(executable_id: str, *, study_id: str) -> dict[str, str]:
    digest = executable_id.removeprefix("executable:")[:16]
    prefix = f"scientific/{study_id}/{digest}"
    return {
        "calculation": f"{prefix}/calculation.json",
        "environment": f"{prefix}/environment.json",
        "measurement": f"{prefix}/measurement.json",
        "plan": f"{prefix}/validation-plan.json",
        "result": f"{prefix}/result.json",
        "trace": f"{prefix}/atomic-trace.json",
    }


def _registration(
    *,
    definition: ProspectivePairProtocolDefinition,
    criterion_id: str,
    family_id: str,
    member_id: str,
    ordered_member_ids: tuple[str, ...],
) -> dict[str, object]:
    return {
        "alpha_ppm": definition.alpha_ppm,
        "criterion_id": criterion_id,
        "family_id": family_id,
        "family_registration_hash": multiplicity_family_registration_hash(
            family_id=family_id,
            alpha_ppm=definition.alpha_ppm,
            method=SCIENTIFIC_V2_SYNCHRONIZED_MAX_METHOD,
            ordered_member_ids=ordered_member_ids,
        ),
        "family_size": len(ordered_member_ids),
        "member_id": member_id,
        "method": SCIENTIFIC_V2_SYNCHRONIZED_MAX_METHOD,
        "ordered_member_ids": list(ordered_member_ids),
    }


def sleeve_exposure_cap_risk_multiplicity_registrations(
    *,
    definition: ProspectivePairProtocolDefinition,
    subject_executable_id: str,
) -> tuple[dict[str, object], ...]:
    if subject_executable_id not in definition.prospective_executable_ids:
        raise ValueError("sleeve exposure-cap subject is outside the pair")
    contrast_id = prospective_pair_control_contrast_id(
        definition, subject_executable_id
    )
    return (
        _registration(
            definition=definition,
            criterion_id="D04-primary-control-uncertainty",
            family_id=prospective_pair_control_family_id(
                definition, subject_executable_id
            ),
            member_id=contrast_id,
            ordered_member_ids=(contrast_id,),
        ),
        _registration(
            definition=definition,
            criterion_id="E01-familywise-selection",
            family_id=definition.inference_family_id,
            member_id=subject_executable_id,
            ordered_member_ids=tuple(
                sorted(definition.prospective_executable_ids)
            ),
        ),
    )


def build_sleeve_exposure_cap_risk_validation_plan(
    *,
    definition: ProspectivePairProtocolDefinition,
    mission_id: str,
    executable_id: str,
    names: Mapping[str, str],
) -> dict[str, object]:
    proof_names = {
        ATOMIC_TRACE_PROOF_KIND: names["trace"],
        CALCULATION_PROOF_KIND: names["calculation"],
    }
    profile = {
        "decisive_risk_criterion_ids": [],
        "multiplicity": list(
            sleeve_exposure_cap_risk_multiplicity_registrations(
                definition=definition,
                subject_executable_id=executable_id,
            )
        ),
        "promotion_criterion_ids": [],
        "schema": SCIENTIFIC_ADJUDICATION_PROFILE_SCHEMA,
    }
    return build_validation_plan_v2(
        mission_id=mission_id,
        executable_id=executable_id,
        evidence_depth=EVIDENCE_DEPTH,
        planned_claims=PROSPECTIVE_PAIR_CLAIMS,
        evidence_modes=PROSPECTIVE_PAIR_EVIDENCE_MODES,
        criteria=SLEEVE_EXPOSURE_CAP_RISK_CRITERIA,
        adjudication_profile=profile,
        proof_requirements=proof_requirements_for_modes(
            evidence_modes=PROSPECTIVE_PAIR_EVIDENCE_MODES,
            output_names=proof_names,
            proof_protocol_id=PROSPECTIVE_PAIR_TRACE_PROTOCOL_ID,
        ),
        candidate_eligible_on_pass=False,
        protocol_definition=definition.manifest(),
    )


@dataclass(frozen=True, slots=True)
class SleeveExposureCapRiskJobPlan:
    mission_id: str
    study_id: str
    executable_id: str
    definition: ProspectivePairProtocolDefinition
    output_name_items: tuple[tuple[str, str], ...]
    plan: Mapping[str, object]

    @property
    def output_names(self) -> dict[str, str]:
        return dict(self.output_name_items)

    @property
    def plan_hash(self) -> str:
        return sha256(canonical_bytes(self.plan)).hexdigest()

    @property
    def producer_executable_id(self) -> str:
        return self.definition.prospective_executable_ids[0]

    @property
    def produces_family_cache(self) -> bool:
        return self.executable_id == self.producer_executable_id

    @property
    def cache_output_name(self) -> str:
        return sleeve_exposure_cap_risk_cache_output_name(self.definition)

    @property
    def cache_provenance_output_name(self) -> str:
        return sleeve_exposure_cap_risk_cache_provenance_output_name(
            self.study_id
        )

    def expected_outputs(self) -> tuple[str, ...]:
        values = set(self.output_names.values())
        if self.produces_family_cache:
            values.update(
                (self.cache_output_name, self.cache_provenance_output_name)
            )
        return tuple(sorted(values))

    def expected_output_classes(self) -> dict[str, str]:
        return {
            name: (
                "reproducible_cache"
                if name == self.cache_output_name
                else "durable_evidence"
            )
            for name in self.expected_outputs()
        }

    def job_input_hashes(
        self,
        *,
        cache_sha256: str | None = None,
        cache_provenance_sha256: str | None = None,
        producer_trace_sha256: str | None = None,
    ) -> tuple[str, ...]:
        optional = (
            cache_sha256,
            cache_provenance_sha256,
            producer_trace_sha256,
        )
        missing = tuple(value is None for value in optional)
        if any(missing) and not all(missing):
            raise ValueError(
                "sleeve exposure-cap cache inputs are inseparable"
            )
        if self.produces_family_cache and not all(missing):
            raise ValueError("sleeve exposure-cap producer cannot consume its cache")
        values = {
            self.definition.dataset_sha256,
            self.definition.material_identity,
            self.definition.split_artifact_sha256,
            self.definition.identity.removeprefix("prospective-pair-definition:"),
            self.plan_hash,
            SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID.removeprefix("validator:"),
            prospective_pair_trace_implementation_sha256(),
            selection_inference_implementation_sha256(),
            sleeve_exposure_cap_risk_chassis_implementation_sha256(),
            sleeve_exposure_cap_risk_cache_implementation_sha256(),
            sleeve_exposure_cap_risk_study_implementation_sha256(),
            sleeve_exposure_cap_risk_trace_implementation_sha256(),
            running_job_execution_context_implementation_sha256(),
            *dict(self.definition.producer_implementation_identities).values(),
        }
        values.update(value for value in optional if value is not None)
        return tuple(sorted(_job_input_digest(value) for value in values))

    def scientific_binding(self) -> dict[str, object]:
        return {
            "evidence_depth": EVIDENCE_DEPTH,
            "evidence_modes": list(PROSPECTIVE_PAIR_EVIDENCE_MODES),
            "planned_claims": list(PROSPECTIVE_PAIR_CLAIMS),
            "result_manifest_output": self.output_names["result"],
            "validation_plan_hash": self.plan_hash,
            "validator_id": SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
        }

    def validated_recomputed_criterion_ids(
        self, scientific_facts: Mapping[str, object]
    ) -> tuple[str, ...]:
        return validated_recomputed_criterion_ids(
            scientific_facts,
            expected_evidence_modes=PROSPECTIVE_PAIR_EVIDENCE_MODES,
            expected_criteria=SLEEVE_EXPOSURE_CAP_RISK_CRITERIA,
            context="prospective sleeve exposure-cap risk",
        )


def build_sleeve_exposure_cap_risk_job_plan(
    *,
    repository_root: str | Path,
    mission_id: str,
    study_id: str,
    executable_id: str,
    definition: ProspectivePairProtocolDefinition | None = None,
    successor: bool = False,
) -> SleeveExposureCapRiskJobPlan:
    if definition is None:
        definition = build_sleeve_exposure_cap_risk_protocol_definition(
            repository_root,
            successor=successor,
        )
    else:
        canonical_bytes(definition.manifest())
    if executable_id not in definition.prospective_executable_ids:
        raise ValueError("sleeve exposure-cap Job subject is not registered")
    names = output_names(executable_id, study_id=study_id)
    plan = build_sleeve_exposure_cap_risk_validation_plan(
        definition=definition,
        mission_id=mission_id,
        executable_id=executable_id,
        names=names,
    )
    return SleeveExposureCapRiskJobPlan(
        mission_id=mission_id,
        study_id=study_id,
        executable_id=executable_id,
        definition=definition,
        output_name_items=tuple(sorted(names.items())),
        plan=plan,
    )


def build_environment_manifest() -> dict[str, object]:
    value = {
        "numpy_version": np.__version__,
        "pandas_version": pd.__version__,
        "prospective_pair_trace_implementation_sha256": prospective_pair_trace_implementation_sha256(),
        "python_version": ".".join(str(value) for value in sys.version_info[:3]),
        "running_job_context_implementation_sha256": running_job_execution_context_implementation_sha256(),
        "schema": "scientific_engine_environment.v2",
        "scipy_version": scipy.__version__,
        "sleeve_exposure_cap_risk_chassis_implementation_sha256": sleeve_exposure_cap_risk_chassis_implementation_sha256(),
        "sleeve_exposure_cap_risk_study_implementation_sha256": sleeve_exposure_cap_risk_study_implementation_sha256(),
        "sleeve_exposure_cap_risk_trace_implementation_sha256": sleeve_exposure_cap_risk_trace_implementation_sha256(),
        "validator_id": SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    }
    canonical_bytes(value)
    return value


def _hypothesis(
    inference: object, hypothesis_id: str
) -> Mapping[str, Any]:
    result = inference if isinstance(inference, Mapping) else {}
    statistical = result.get("statistical_manifest")
    hypotheses = (
        statistical.get("hypotheses")
        if isinstance(statistical, Mapping)
        else None
    )
    matches = [
        item
        for item in hypotheses or ()
        if isinstance(item, Mapping)
        and item.get("hypothesis_id") == hypothesis_id
    ]
    if len(matches) != 1:
        raise ValueError("sleeve exposure-cap inference subject is ambiguous")
    return matches[0]


def build_measurement(
    *,
    scoped_plan: SleeveExposureCapRiskJobPlan,
    job_id: str,
    job_hash: str,
    calculation: Mapping[str, Any],
    trace_sha256: str,
    calculation_sha256: str,
) -> dict[str, object]:
    metrics = calculation.get("metrics")
    statistics = calculation.get("statistics")
    if not isinstance(metrics, Mapping) or not isinstance(statistics, Mapping):
        raise ValueError("sleeve exposure-cap calculation is invalid")
    registrations = sleeve_exposure_cap_risk_multiplicity_registrations(
        definition=scoped_plan.definition,
        subject_executable_id=scoped_plan.executable_id,
    )
    rows: list[dict[str, object]] = []
    for registration in registrations:
        criterion_id = str(registration["criterion_id"])
        if criterion_id == "D04-primary-control-uncertainty":
            inference = statistics.get("control_inference")
            metric = metrics["registered_control_contrast"][
                PRIMARY_CONTROL_PVALUE_METRIC
            ]
        else:
            inference = statistics.get("selection_inference")
            metric = metrics["selection_aware_signal_evidence"][
                "selection_aware_pvalue_ppm"
            ]
        hypothesis = _hypothesis(inference, str(registration["member_id"]))
        raw = hypothesis.get("raw")
        familywise = hypothesis.get("familywise")
        synchronized = (
            familywise.get("synchronized_max")
            if isinstance(familywise, Mapping)
            else None
        )
        if not isinstance(raw, Mapping) or not isinstance(synchronized, Mapping):
            raise ValueError("sleeve exposure-cap inference p-values are absent")
        raw_pvalue = raw.get("monte_carlo_upper_pvalue_ppm")
        adjusted = synchronized.get("monte_carlo_upper_pvalue_ppm")
        if type(raw_pvalue) is not int or type(adjusted) is not int or adjusted != metric:
            raise ValueError("sleeve exposure-cap inference metric binding drifted")
        rows.append(
            {
                **registration,
                "adjusted_pvalue_ppm": adjusted,
                "raw_pvalue_ppm": raw_pvalue,
            }
        )
    requirements = parse_proof_requirements(
        scoped_plan.plan["proof_requirements"],
        evidence_modes=PROSPECTIVE_PAIR_EVIDENCE_MODES,
    )
    value = {
        "evidence_depth": EVIDENCE_DEPTH,
        "evidence_modes": list(PROSPECTIVE_PAIR_EVIDENCE_MODES),
        "executable_id": scoped_plan.executable_id,
        "job_hash": job_hash,
        "job_id": job_id,
        "metrics": metrics,
        "mission_id": scoped_plan.mission_id,
        "multiplicity": rows,
        "proofs": list(
            build_proof_references(
                requirements=requirements,
                artifact_hashes={
                    scoped_plan.output_names["trace"]: trace_sha256,
                    scoped_plan.output_names["calculation"]: calculation_sha256,
                },
            )
        ),
        "schema": SCIENTIFIC_MEASUREMENT_V2_SCHEMA,
    }
    canonical_bytes(value)
    return value


def build_result(
    *,
    scoped_plan: SleeveExposureCapRiskJobPlan,
    job_id: str,
    job_hash: str,
    measurement_sha256: str,
) -> dict[str, object]:
    value = {
        "evidence_depth": EVIDENCE_DEPTH,
        "executable_id": scoped_plan.executable_id,
        "job_hash": job_hash,
        "job_id": job_id,
        "mission_id": scoped_plan.mission_id,
        "observations": [
            {
                "claim_id": claim_id,
                "measurement_artifact_hash": measurement_sha256,
            }
            for claim_id in PROSPECTIVE_PAIR_CLAIMS
        ],
        "schema": SCIENTIFIC_RESULT_SCHEMA,
    }
    canonical_bytes(value)
    return value


@dataclass(frozen=True, slots=True)
class SleeveExposureCapRiskJobPacket:
    adjudication_state: str
    output_manifest: tuple[tuple[str, str], ...]

    def outputs(self) -> dict[str, str]:
        return dict(self.output_manifest)


__all__ = [
    "EVIDENCE_DEPTH",
    "PRIMARY_CONTROL_DELTA_METRIC",
    "PRIMARY_CONTROL_PVALUE_METRIC",
    "SLEEVE_EXPOSURE_CAP_RISK_CRITERIA",
    "SleeveExposureCapRiskJobPacket",
    "SleeveExposureCapRiskJobPlan",
    "build_environment_manifest",
    "build_measurement",
    "build_result",
    "build_sleeve_exposure_cap_risk_job_plan",
    "build_sleeve_exposure_cap_risk_validation_plan",
    "output_names",
    "sleeve_exposure_cap_risk_criteria",
    "sleeve_exposure_cap_risk_multiplicity_registrations",
    "sleeve_exposure_cap_risk_study_implementation_sha256",
]
