"""Run one preregistered cross-sleeve gross-exposure risk contrast.

The operation is intentionally prospective.  ``build_design`` reads only the
Foundation material identity, fold calendar, current Portfolio, and durable
diagnoses.  No trade or performance value is computed until both exact family
members have been registered and the first Job has entered its Writer-bound
execution context.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SOURCE_ROOT))

from axiom_rift.core.canonical import canonical_bytes  # noqa: E402
from axiom_rift.core.component_surface import (  # noqa: E402
    COMPONENT_SURFACE_ARCHITECTURE_ROLE,
)
from axiom_rift.core.identity import ExecutableSpec  # noqa: E402
from axiom_rift.operations.permits import (  # noqa: E402
    Permit,
    PermitAuthority,
    PermitKeyStore,
    PermitKind,
    SubjectKind,
)
from axiom_rift.operations.prospective_job_materialization import (  # noqa: E402
    materialize_prospective_job_implementation,
    prospective_job_implementation_sha256,
)
from axiom_rift.operations.running_job import RunningJobExecution  # noqa: E402
from axiom_rift.operations.study_diagnosis_projection import (  # noqa: E402
    study_claim_scoped_diagnosis,
)
from axiom_rift.operations.validation import (  # noqa: E402
    EvidenceValidatorRegistry,
)
from axiom_rift.operations.writer import (  # noqa: E402
    StateWriter,
)
from axiom_rift.research.discovery import OBSERVED_MATERIAL_ID  # noqa: E402
from axiom_rift.research.governance import (  # noqa: E402
    DiagnosisConfidence,
    EvidenceState,
    ResearchLayer,
    StudyDiagnosis,
)
from axiom_rift.research.portfolio import (  # noqa: E402
    BatchSpec,
    ConcurrentFamilyEvaluationMode,
    ConcurrentFamilyManifest,
    DecisionBasisRecord,
    DecisionLens,
    DecisionLensAssessment,
    DecisionLensPosition,
    DecisionOption,
    PortfolioAction,
    PortfolioAxis,
    PortfolioDecision,
    PortfolioSnapshot,
    QuantTeamDecisionReview,
)
from axiom_rift.research.portfolio_projection import (  # noqa: E402
    architecture_surfaces_from_axis_projection,
    component_surface_registry,
    portfolio_axes_from_projection,
)
from axiom_rift.research.prospective_engineering_reentry import (  # noqa: E402
    ProspectiveEngineeringReentry,
)
from axiom_rift.research.prospective_pair_trace import (  # noqa: E402
    PROSPECTIVE_PAIR_EVIDENCE_MODES,
)
from axiom_rift.research.protocol import (  # noqa: E402
    ResearchProtocol,
    ResearchProtocolActivation,
)
from axiom_rift.research.sleeve_exposure_cap_risk_chassis import (  # noqa: E402
    sleeve_exposure_cap_risk_configurations,
    sleeve_exposure_cap_risk_controlled_chassis,
    sleeve_exposure_cap_risk_executable,
    sleeve_exposure_cap_risk_successor_controlled_chassis,
    sleeve_exposure_cap_risk_successor_executable,
)
from axiom_rift.research.sleeve_exposure_cap_risk_runtime import (  # noqa: E402
    CALLABLE_IDENTITY,
    JOB_IMPLEMENTATION_PROTOCOL,
    execute_sleeve_exposure_cap_risk_job,
    sleeve_exposure_cap_risk_runtime_path,
)
import axiom_rift.research.sleeve_exposure_cap_risk_runtime as exposure_runtime  # noqa: E402
from axiom_rift.research.sleeve_exposure_cap_risk_study import (  # noqa: E402
    SleeveExposureCapRiskJobPlan,
    build_sleeve_exposure_cap_risk_job_plan,
)
from axiom_rift.research.semantic_question import (  # noqa: E402
    SemanticQuestionCore,
    SemanticQuestionLineageProposal,
    SemanticQuestionRelation,
)
from axiom_rift.research.trials import NegativeMemory  # noqa: E402
from axiom_rift.research.validation_v2 import (  # noqa: E402
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    ScientificAdjudicationValidatorV2,
)


MISSION_ID = "MIS-0006"
INITIATIVE_ID = "INI-0025"
STUDY_ID = "STU-0125"
BATCH_DISPLAY_ID = "BAT-0125"
BASE_SNAPSHOT_ID = (
    "portfolio:d5c40f723ecd2ed8a840289919958957629a91c86998b5bd23d1a6d8c091589d"
)
SOURCE_AXIS_ID = "axis-cost-aware-execution"
ALTERNATE_AXIS_ID = "axis-p0-composite-audit-reanalysis"
NEW_AXIS_ID = "axis-cross-sleeve-gross-exposure-cap-risk"
MECHANISM_FAMILY = "cross_sleeve_gross_exposure_cap"
SOURCE_DIAGNOSIS_ID = (
    "diagnosis:2de6bb8800c0bf098447eded5e0324e236deb4d043dc4fa3cf99471072d94d06"
)
MONTHLY_LOCK_DIAGNOSIS_ID = (
    "diagnosis:c3e0f3d73fd056af41ea4dcc5f3ddf335439e61fcf2d86a62b90ce8c211795c7"
)
POSITIVE_SLEEVE_DIAGNOSIS_ID = (
    "diagnosis:d085ff876416d1ab136a7113600dae4eae0c145374b6d466b42294b86ca06b2c"
)
LOSS_SKIP_DIAGNOSIS_ID = (
    "diagnosis:a64530b3c9d82e65abbc6f2fd2691ed1feb167472ac5b5d8c1a72dd6bed64a89"
)
PREDECESSOR_STUDY_ID = "STU-0124"
PREDECESSOR_STUDY_CLOSE_RECORD_ID = (
    "13b1fea3e18e78a7fdec10ebbdeec6fa52c92b0f8093233bdb2b540d7a529039"
)
PREDECESSOR_COMPLETION_RECORD_ID = (
    "1933f7519a3aed31a785c7621df1dacf1b7ce6f835d35bb9e73399715f2cafd8"
)
PREDECESSOR_DISPOSITION_RECORD_ID = (
    "38e14f0a958d64812fce5704eae376fc1d14259940cf656ab6465220ac3524b3"
)
PREDECESSOR_DISPOSITION_HASH = (
    "0f8662d508eb28aace1d8c1a2072400314f026c25db80ea7e6041f0e563c4b51"
)
PREDECESSOR_DIAGNOSIS_ID = (
    "diagnosis:fc0c33b139fd67be8b4f403d22123c4e1e616f45d4fe94a32849f0cb956e2004"
)
SUCCESSOR_ARTIFACT_HASH = (
    "075873d9715e02af26b5093e4799847fe5291b758f61254f3aaa1cab366eb61f"
)
SUCCESSOR_BASELINE_EXECUTABLE_ID = (
    "executable:35e73c7aaa1a427153a68add48c8d245fe6539cf1e6c45b7a4487d6ed76769de"
)
PREDECESSOR_SEMANTIC_CORE_ID = (
    "semantic-question-core:314ef57cc14460c4d51a75e1de21fb36f377172c4929f3d35b8587e063bf19c5"
)
AXIS_IDENTITY = (
    "axis:a2f843712b6a75bfb854109fe72bbe0c9698fd47a3fe63c06c6833181e8b12b9"
)
OPERATION_PREFIX = "goal-audit-cross-sleeve-exposure-cap-risk-v2-"
PERMIT_EXPIRY_UTC = "2027-12-31T23:59:59Z"


@dataclass(frozen=True, slots=True)
class StudyMember:
    label: str
    executable: ExecutableSpec
    job_plan: SleeveExposureCapRiskJobPlan


@dataclass(frozen=True, slots=True)
class StudyRunBinding:
    study_id: str
    initiative_id: str
    operation_prefix: str
    permit_expiry_utc: str
    portfolio_snapshot_id: str
    study_permit_suffix: str
    superseded_operation_suffixes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StudyDesign:
    binding: StudyRunBinding
    prior_axes: tuple[PortfolioAxis, ...]
    axis: PortfolioAxis
    structural_decision: PortfolioDecision | None
    expanded_snapshot: PortfolioSnapshot
    work_decision: PortfolioDecision
    question: Mapping[str, Any]
    proposal: Mapping[str, Any]
    batch_spec: BatchSpec
    members: tuple[StudyMember, ...]
    semantic_question_lineage: SemanticQuestionLineageProposal | None

    @property
    def control(self) -> StudyMember:
        return self.members[0]

    @property
    def subject(self) -> StudyMember:
        return self.members[1]


def _basis(*values: tuple[str, str]) -> tuple[DecisionBasisRecord, ...]:
    return tuple(
        DecisionBasisRecord(kind=kind, record_id=record_id)
        for kind, record_id in sorted(set(values))
    )


def _current_snapshot_axes(
    writer: StateWriter,
) -> tuple[tuple[PortfolioAxis, ...], Mapping[str, Any]]:
    with writer.open_stable_index() as (control, index):
        science = control["scientific"]
        initial_action = {
            "kind": "portfolio_decision",
            "portfolio_snapshot_id": BASE_SNAPSHOT_ID,
            "study_diagnosis_id": PREDECESSOR_DIAGNOSIS_ID,
        }
        progressed = index.get(
            "operation", OPERATION_PREFIX + "structural-decision"
        ) or index.get("operation", OPERATION_PREFIX + "work-decision")
        if (
            science["active_mission"] != MISSION_ID
            or science["active_initiative"] != INITIATIVE_ID
            or (
                control.get("next_action") != initial_action
                and (
                    progressed is None
                    or progressed.status != "success"
                )
            )
            or science.get("active_study") not in {None, STUDY_ID}
            or (
                science.get("active_batch") is not None
                and science.get("active_study") != STUDY_ID
            )
        ):
            raise RuntimeError("exposure-cap Study Mission or Initiative drifted")
        snapshot = index.get("portfolio-snapshot", BASE_SNAPSHOT_ID)
        if snapshot is None:
            raise RuntimeError("exposure-cap base Portfolio snapshot is absent")
        raw_axes = snapshot.payload.get("axes")
        if not isinstance(raw_axes, list) or any(
            not isinstance(axis, Mapping) for axis in raw_axes
        ):
            raise RuntimeError("exposure-cap base Portfolio axes are malformed")
        required_surfaces = architecture_surfaces_from_axis_projection(raw_axes)
        payloads = tuple(
            record.payload
            for record in index.component_manifests_by_surfaces(
                COMPONENT_SURFACE_ARCHITECTURE_ROLE,
                required_surfaces,
            )
        )
        prior_axes = portfolio_axes_from_projection(
            raw_axes,
            component_surface_registry(payloads),
        )
        for kind, record_id in (
            ("study-diagnosis", SOURCE_DIAGNOSIS_ID),
            ("study-diagnosis", MONTHLY_LOCK_DIAGNOSIS_ID),
            ("study-diagnosis", POSITIVE_SLEEVE_DIAGNOSIS_ID),
            ("study-diagnosis", LOSS_SKIP_DIAGNOSIS_ID),
            ("study-diagnosis", PREDECESSOR_DIAGNOSIS_ID),
            ("study-close", PREDECESSOR_STUDY_CLOSE_RECORD_ID),
            ("job-completed", PREDECESSOR_COMPLETION_RECORD_ID),
            ("repair-close", PREDECESSOR_DISPOSITION_RECORD_ID),
        ):
            if index.get(kind, record_id) is None:
                raise RuntimeError("exposure-cap durable diagnosis basis is absent")
        return prior_axes, snapshot.payload


def build_design(writer: StateWriter) -> StudyDesign:
    prior_axes, snapshot_payload = _current_snapshot_axes(writer)
    by_id = {axis.axis_id: axis for axis in prior_axes}
    axis = by_id.get(NEW_AXIS_ID)
    if (
        axis is None
        or axis.identity != AXIS_IDENTITY
        or SOURCE_AXIS_ID not in by_id
        or ALTERNATE_AXIS_ID not in by_id
    ):
        raise RuntimeError("exposure-cap allocation axes are absent")

    chassis = sleeve_exposure_cap_risk_successor_controlled_chassis()
    configurations = sleeve_exposure_cap_risk_configurations()
    executables = tuple(
        sleeve_exposure_cap_risk_successor_executable(item)
        for item in configurations
    )
    if executables[0].identity != SUCCESSOR_BASELINE_EXECUTABLE_ID:
        raise RuntimeError("exposure-cap successor artifact identity drifted")
    definition_plan = build_sleeve_exposure_cap_risk_job_plan(
        repository_root=ROOT,
        mission_id=MISSION_ID,
        study_id=STUDY_ID,
        executable_id=executables[0].identity,
        successor=True,
    )
    definition = definition_plan.definition
    if tuple(item.identity for item in executables) != (
        definition.prospective_executable_ids
    ):
        raise RuntimeError("exposure-cap Executable family identity drifted")
    if executables[0].identity != chassis.baseline_executable.identity:
        raise RuntimeError("exposure-cap control is not the exact prior baseline")

    structural_basis = _basis(
        ("portfolio-snapshot", BASE_SNAPSHOT_ID),
        ("study-diagnosis", MONTHLY_LOCK_DIAGNOSIS_ID),
        ("study-diagnosis", POSITIVE_SLEEVE_DIAGNOSIS_ID),
        ("study-diagnosis", SOURCE_DIAGNOSIS_ID),
        ("study-diagnosis", LOSS_SKIP_DIAGNOSIS_ID),
    )
    structural_options = (
        DecisionOption(
            option_id="add-gross-exposure-cap-risk-axis",
            action=PortfolioAction.NEW_MECHANISM,
            target_id=SOURCE_AXIS_ID,
            expected_information_value=(
                "identify whether causal concurrent gross exposure carries risk "
                "information beyond the contradicted loss-skip policy"
            ),
            opportunity_cost="one frozen two-member discovery Batch",
        ),
        DecisionOption(
            option_id="rotate-independent-forest",
            action=PortfolioAction.ROTATE,
            target_id=ALTERNATE_AXIS_ID,
            expected_information_value=(
                "advance another independent open forest branch"
            ),
            opportunity_cost=(
                "leave the exact observable overlap mechanism untested"
            ),
            omission_reason=(
                "the overlap contrast has an exact validated control and one binary "
                "capacity extreme, while prior replay branches require genuinely new "
                "material after absent-information diagnoses"
            ),
        ),
    )
    structural_review = QuantTeamDecisionReview(
        assessments=(
            DecisionLensAssessment(
                lens=DecisionLens.ARCHITECTURE,
                position=DecisionLensPosition.SUPPORT,
                option_ids=(
                    "add-gross-exposure-cap-risk-axis",
                    "rotate-independent-forest",
                ),
                basis_records=structural_basis,
                finding=(
                    "the proposed branch keeps the exact validated signal, entry, "
                    "lifecycle, portfolio composition, and execution chassis while "
                    "changing only risk acceptance"
                ),
            ),
            DecisionLensAssessment(
                lens=DecisionLens.CAUSALITY,
                position=DecisionLensPosition.SUPPORT,
                option_ids=(
                    "add-gross-exposure-cap-risk-axis",
                    "rotate-independent-forest",
                ),
                basis_records=structural_basis,
                finding=(
                    "the subject uses only accepted positions and their frozen exit "
                    "clocks at each next-bar entry, with no future trade outcome access"
                ),
            ),
            DecisionLensAssessment(
                lens=DecisionLens.RISK,
                position=DecisionLensPosition.UNCERTAIN,
                option_ids=("add-gross-exposure-cap-risk-axis",),
                basis_records=structural_basis,
                finding=(
                    "a one-lot cap can reduce density as well as overlap, so drawdown "
                    "and activity must remain claim-separated diagnostics"
                ),
            ),
        ),
        claim_boundary="allocation only; no scientific, candidate, or terminal claim",
        resolution_basis=(
            "use one concurrent fixed pair with a frozen router-first tie-break and "
            "no threshold, capacity, priority, or window grid"
        ),
        disagreement_resolution=(
            "retain activity as an independent component claim and stop after one Batch"
        ),
    )
    structural_decision = None
    expanded_snapshot = PortfolioSnapshot(
        mission_id=MISSION_ID,
        axes=prior_axes,
        opportunity_cost_basis=snapshot_payload["opportunity_cost_basis"],
        research_intake_id=snapshot_payload.get("research_intake_id"),
        exhaustion_standard=snapshot_payload.get("exhaustion_standard"),
    )
    if expanded_snapshot.identity != BASE_SNAPSHOT_ID:
        raise RuntimeError("exposure-cap successor Portfolio snapshot drifted")

    lineage = SemanticQuestionLineageProposal(
        predecessor_study_id=PREDECESSOR_STUDY_ID,
        successor_study_id=STUDY_ID,
        predecessor_core_id=PREDECESSOR_SEMANTIC_CORE_ID,
        successor_core_id=PREDECESSOR_SEMANTIC_CORE_ID,
        relation=SemanticQuestionRelation.ENGINEERING_REENTRY,
        rationale=(
            "reenter the same exposure-cap question under the registered "
            "status-normalized validator protocol without inheriting predecessor evidence"
        ),
        basis_record_ids=(
            "job-completed:" + PREDECESSOR_COMPLETION_RECORD_ID,
            "study-close:" + PREDECESSOR_STUDY_CLOSE_RECORD_ID,
            "study-diagnosis:" + PREDECESSOR_DIAGNOSIS_ID,
            "study-open:" + PREDECESSOR_STUDY_ID,
        ),
    )
    reentry = ProspectiveEngineeringReentry(
        mission_id=MISSION_ID,
        portfolio_snapshot_id=BASE_SNAPSHOT_ID,
        target_axis_id=NEW_AXIS_ID,
        target_axis_identity=AXIS_IDENTITY,
        predecessor_study_id=PREDECESSOR_STUDY_ID,
        successor_study_id=STUDY_ID,
        study_diagnosis_id=PREDECESSOR_DIAGNOSIS_ID,
        study_close_record_id=PREDECESSOR_STUDY_CLOSE_RECORD_ID,
        completion_record_id=PREDECESSOR_COMPLETION_RECORD_ID,
        disposition_record_id=PREDECESSOR_DISPOSITION_RECORD_ID,
        disposition_hash=PREDECESSOR_DISPOSITION_HASH,
        successor_artifact_hash=SUCCESSOR_ARTIFACT_HASH,
        successor_baseline_executable_id=executables[0].identity,
        portfolio_action=PortfolioAction.DEEPEN.value,
        semantic_question_lineage=lineage,
    )

    work_basis = _basis(
        ("job-completed", PREDECESSOR_COMPLETION_RECORD_ID),
        ("portfolio-snapshot", BASE_SNAPSHOT_ID),
        ("repair-close", PREDECESSOR_DISPOSITION_RECORD_ID),
        ("study-close", PREDECESSOR_STUDY_CLOSE_RECORD_ID),
        ("study-diagnosis", PREDECESSOR_DIAGNOSIS_ID),
    )
    work_decision = PortfolioDecision(
        decision_id="DEC-STU0125-STATUS-NORMALIZED-EXPOSURE-CAP-REENTRY",
        chosen_option_id="deepen-status-normalized-exposure-cap",
        options=(
            DecisionOption(
                option_id="rotate-independent-forest",
                action=PortfolioAction.ROTATE,
                target_id=ALTERNATE_AXIS_ID,
                expected_information_value="advance a distinct open forest branch",
                opportunity_cost="defer the exact gross-overlap causal contrast",
                omission_reason=(
                    "the typed successor is already bounded and directly resolves "
                    "the non-scientific validator gap"
                ),
            ),
            DecisionOption(
                option_id="deepen-status-normalized-exposure-cap",
                action=PortfolioAction.DEEPEN,
                target_id=NEW_AXIS_ID,
                expected_information_value=(
                    "recover one exact causal, economic, temporal, and risk comparison"
                ),
                opportunity_cost="two member Jobs and one bounded Batch",
            ),
        ),
        rationale=(
            "execute the typed same-question successor without granting scientific "
            "credit to STU-0124"
        ),
        commitment_batches=1,
        quant_team_review=QuantTeamDecisionReview(
            assessments=(
                DecisionLensAssessment(
                    lens=DecisionLens.ECONOMICS,
                    position=DecisionLensPosition.SUPPORT,
                    option_ids=(
                        "deepen-status-normalized-exposure-cap",
                        "rotate-independent-forest",
                    ),
                    basis_records=work_basis,
                    finding=(
                        "the pair measures native and stressed fixed-lot economics "
                        "against the exact unrestricted control"
                    ),
                ),
                DecisionLensAssessment(
                    lens=DecisionLens.RISK,
                    position=DecisionLensPosition.UNCERTAIN,
                    option_ids=("deepen-status-normalized-exposure-cap",),
                    basis_records=work_basis,
                    finding=(
                        "overlap concentration may improve at the cost of density, so neither "
                        "metric may overwrite the other"
                    ),
                ),
                DecisionLensAssessment(
                    lens=DecisionLens.STATISTICS,
                    position=DecisionLensPosition.SUPPORT,
                    option_ids=(
                        "deepen-status-normalized-exposure-cap",
                        "rotate-independent-forest",
                    ),
                    basis_records=work_basis,
                    finding=(
                        "the exact two-member family permits synchronized selection "
                        "inference without a tuning search"
                    ),
                ),
            ),
            claim_boundary=(
                "discovery allocation only; candidate eligibility remains false"
            ),
            resolution_basis=(
                "run the exact fixed pair and preserve component-aware outcomes"
            ),
            disagreement_resolution=(
                "predeclare density and drawdown separately and make neither a hidden "
                "rescue criterion"
            ),
        ),
        baseline_executable=chassis.baseline_executable,
        engineering_reentry=reentry,
    )
    question = {
        "causal_question": axis.causal_question,
        "changed_variables": [
            "cross_sleeve_gross_exposure_entry_acceptance",
            "maximum_concurrent_gross_lots_two_versus_one",
        ],
        "controlled_variables": [
            "calibration",
            "completed_bar_clock",
            "execution_cost",
            "features",
            "labels",
            "lifecycle",
            "models",
            "portfolio_composition",
            "regime",
            "selectors",
            "signal_synthesis",
            "trade_direction",
        ],
        "done_conditions": [
            "both exact family members receive one validator-v2 completion",
            "activity, economics, risk, causality, and temporal claims remain separate",
            "candidate authority remains absent",
        ],
        "evidence_modes": list(PROSPECTIVE_PAIR_EVIDENCE_MODES),
    }
    if (
        SemanticQuestionCore.from_question_manifest(question).identity
        != PREDECESSOR_SEMANTIC_CORE_ID
    ):
        raise RuntimeError("exposure-cap successor semantic question drifted")
    proposal = {
        "candidate_eligible": False,
        "concurrent_family": {
            "control_executable_id": executables[0].identity,
            "ordered_executable_ids": list(definition.prospective_executable_ids),
            "subject_executable_id": executables[1].identity,
        },
        "control_policy": configurations[0].configuration_id,
        "engineering_reentry_id": reentry.identity,
        "estimand": (
            "subject minus unrestricted control under one common eligible calendar"
        ),
        "mechanism": MECHANISM_FAMILY,
        "predecessor_study_id": PREDECESSOR_STUDY_ID,
        "schema": "sleeve_exposure_cap_risk_study.v2",
        "subject_policy": configurations[1].configuration_id,
    }
    study_hash = writer.study_input_hash(
        question=question,
        material_identity=OBSERVED_MATERIAL_ID,
        semantic_proposal=proposal,
        semantic_question_lineage=lineage,
        controlled_chassis=chassis,
        portfolio_axis_id=axis.axis_id,
        portfolio_axis_identity=axis.identity,
        portfolio_decision_id=work_decision.identity,
    )
    concurrent_family = ConcurrentFamilyManifest(
        evaluation_mode=ConcurrentFamilyEvaluationMode.VECTORIZED,
        executable_ids=tuple(sorted(definition.prospective_executable_ids)),
    )
    batch_spec = BatchSpec(
        batch_id=BATCH_DISPLAY_ID,
        study_id=STUDY_ID,
        study_hash=study_hash,
        display_name="cross-sleeve one-gross-lot exposure-cap pair",
        max_trials=2,
        max_compute_seconds=14400,
        max_wall_seconds=21600,
        stop_rule=(
            "stop after both preregistered members receive exactly one validated Job; "
            "no adaptive variant, threshold, or retry without changed information"
        ),
        source_contract_ids=tuple(chassis.baseline_executable.source_contracts),
        acceptance_profile={
            "candidate_authority": "none_discovery_only",
            "concurrent_family_size": 2,
            "required_member_completions": 2,
            "scientific_judgment": "component_aware_validator_v2",
        },
        adaptive_basis={
            "uncertainty": "one binary causal policy contrast",
            "causal_complexity": "one accepted-position clock gates overlapping entry",
            "surface_curvature": "not searched; no tunable surface",
            "compute_cost": "two bounded subject Jobs over one exact pair family",
            "expected_information_value": (
                "separate concurrent exposure value from activity destruction"
            ),
            "portfolio_opportunity_cost": (
                "one Batch while all unrelated forest axes remain selectable"
            ),
        },
        concurrent_family=concurrent_family,
    )
    members = tuple(
        StudyMember(
            label=("control" if ordinal == 0 else "exposure-cap"),
            executable=executable,
            job_plan=(
                definition_plan
                if ordinal == 0
                else build_sleeve_exposure_cap_risk_job_plan(
                    repository_root=ROOT,
                    mission_id=MISSION_ID,
                    study_id=STUDY_ID,
                    executable_id=executable.identity,
                    definition=definition,
                )
            ),
        )
        for ordinal, executable in enumerate(executables)
    )
    if any(
        member.job_plan.definition.manifest() != definition.manifest()
        for member in members
    ):
        raise RuntimeError("exposure-cap member definitions differ")
    return StudyDesign(
        binding=StudyRunBinding(
            study_id=STUDY_ID,
            initiative_id=INITIATIVE_ID,
            operation_prefix=OPERATION_PREFIX,
            permit_expiry_utc=PERMIT_EXPIRY_UTC,
            portfolio_snapshot_id=BASE_SNAPSHOT_ID,
            study_permit_suffix="study-permit",
            superseded_operation_suffixes=("batch-permit",),
        ),
        prior_axes=prior_axes,
        axis=axis,
        structural_decision=structural_decision,
        expanded_snapshot=expanded_snapshot,
        work_decision=work_decision,
        question=question,
        proposal=proposal,
        batch_spec=batch_spec,
        members=members,
        semantic_question_lineage=lineage,
    )


def _operation_record(writer: StateWriter, operation_id: str) -> Any | None:
    with writer.open_stable_index() as (_control, index):
        return index.get("operation", operation_id)


def _operation_result(writer: StateWriter, operation_id: str) -> Mapping[str, Any]:
    record = _operation_record(writer, operation_id)
    result = None if record is None else record.payload.get("result")
    if record is None or record.status != "success" or not isinstance(result, Mapping):
        raise RuntimeError(f"operation is absent or unsuccessful: {operation_id}")
    return result


def _durable_or_planned_batch_id(
    writer: StateWriter,
    design: StudyDesign,
) -> str:
    operation = _operation_record(
        writer,
        design.binding.operation_prefix + "open-batch",
    )
    if operation is None:
        return design.batch_spec.identity
    result = _operation_result(writer, operation.record_id)
    batch_id = result.get("batch_id")
    if not isinstance(batch_id, str):
        raise RuntimeError("exposure-cap Batch operation is malformed")
    return batch_id


def _permit_from_operation(writer: StateWriter, operation_id: str) -> Permit:
    raw = _operation_result(writer, operation_id).get("permit")
    if not isinstance(raw, Mapping):
        raise RuntimeError(f"permit operation is malformed: {operation_id}")
    return Permit.from_mapping(raw)


def _ensure_operation(
    writer: StateWriter,
    binding: StudyRunBinding,
    suffix: str,
    action: Callable[[], Any],
) -> Mapping[str, Any]:
    operation_id = binding.operation_prefix + suffix
    existing = _operation_record(writer, operation_id)
    if existing is None:
        print(json.dumps({"operation": operation_id, "status": "starting"}), flush=True)
        action()
    result = _operation_result(writer, operation_id)
    print(json.dumps({"operation": operation_id, "status": "complete"}), flush=True)
    return result


def _study_permit(writer: StateWriter, design: StudyDesign) -> Permit:
    binding = design.binding
    chassis = sleeve_exposure_cap_risk_successor_controlled_chassis()
    study_hash = writer.study_input_hash(
        question=design.question,
        material_identity=OBSERVED_MATERIAL_ID,
        semantic_proposal=design.proposal,
        semantic_question_lineage=design.semantic_question_lineage,
        controlled_chassis=chassis,
        portfolio_axis_id=design.axis.axis_id,
        portfolio_axis_identity=design.axis.identity,
        portfolio_decision_id=design.work_decision.identity,
    )
    return writer.issue_permit(
        kind=PermitKind.STUDY,
        subject_kind=SubjectKind.INITIATIVE,
        subject_id=binding.initiative_id,
        input_hash=study_hash,
        actions=("open_study",),
        scope=tuple(
            sorted(
                {
                    "study",
                    f"axis:{design.axis.identity}",
                    f"baseline:{chassis.baseline_executable.identity}",
                    f"chassis:{chassis.architecture.identity}",
                    f"decision:{design.work_decision.identity}",
                    f"snapshot:{design.expanded_snapshot.identity}",
                }
            )
        ),
        expires_at_utc=binding.permit_expiry_utc,
        one_shot=True,
        operation_id=(
            binding.operation_prefix + binding.study_permit_suffix
        ),
    )


def _materialize_job_authority(
    writer: StateWriter,
    design: StudyDesign,
) -> str:
    implementation = materialize_prospective_job_implementation(
        writer,
        entry_path=sleeve_exposure_cap_risk_runtime_path(),
        callable_identity=CALLABLE_IDENTITY,
        protocol=JOB_IMPLEMENTATION_PROTOCOL,
        source_root=SOURCE_ROOT,
    )
    if implementation != _job_implementation_identity():
        raise RuntimeError("exposure-cap Job implementation materialization drifted")
    for member in design.members:
        artifact = writer.evidence.finalize(canonical_bytes(member.job_plan.plan))
        if artifact.sha256 != member.job_plan.plan_hash:
            raise RuntimeError("exposure-cap validation plan materialization drifted")
    return implementation


def _activate_current_scientific_protocol(
    writer: StateWriter,
    design: StudyDesign,
) -> None:
    """Bind validator-v2 to current authority before this Study's first Job."""

    with writer.open_stable_index() as (control, index):
        authority_digest = control.get("authority", {}).get("manifest_digest")
        science = control.get("scientific", {})
        batch = science.get("active_batch") if isinstance(science, Mapping) else None
        batch_id = batch.get("id") if isinstance(batch, Mapping) else None
        head = index.event_head("research-protocol:scientific")
        prior = (
            None
            if head is None
            else index.get(head.record_kind, head.record_id)
        )
        if (
            prior is not None
            and prior.payload.get("authority_manifest_digest") == authority_digest
            and prior.payload.get("validator_id")
            == SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
        ):
            return
        if (
            type(authority_digest) is not str
            or science.get("active_study") != design.binding.study_id
            or batch_id != design.batch_spec.identity
            or control.get("next_action")
            != {"kind": "declare_job", "batch_id": batch_id}
            or index.records_by_payload_text(
                "job-declared", "batch_id", str(batch_id)
            )
        ):
            raise RuntimeError(
                "exposure-cap protocol reactivation requires the unexecuted Study boundary"
            )
        prior_record_id = None if prior is None else prior.record_id
        prior_validator_id = (
            None if prior is None else prior.payload.get("validator_id")
        )
    audit = writer.evidence.finalize(
        canonical_bytes(
            {
                "authority_manifest_digest": authority_digest,
                "batch_id": batch_id,
                "candidate_delta": 0,
                "holdout_reveal_delta": 0,
                "mission_id": MISSION_ID,
                "prior_activation_record_id": prior_record_id,
                "prior_validator_id": prior_validator_id,
                "prospective_job_declaration_count": 0,
                "prospective_job_implementation_identity": (
                    _job_implementation_identity()
                ),
                "reason": (
                    "bind the current validated implementation before the first "
                    "prospective scientific Job"
                ),
                "replacement_validator_id": (
                    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
                ),
                "schema": "scientific_protocol_reactivation_audit.v1",
                "study_id": design.binding.study_id,
                "trial_delta": 0,
            }
        )
    )
    activation = ResearchProtocolActivation(
        protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
        validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
        authority_manifest_digest=authority_digest,
        audit_artifact_hash=audit.sha256,
    )
    _ensure_operation(
        writer,
        design.binding,
        "activate-current-v2-protocol",
        lambda: writer.activate_research_protocol(
            activation=activation,
            operation_id=(
                design.binding.operation_prefix
                + "activate-current-v2-protocol"
            ),
            allow_active_unexecuted_study_boundary=True,
        ),
    )


def _job_implementation_identity() -> str:
    return prospective_job_implementation_sha256(
        entry_path=sleeve_exposure_cap_risk_runtime_path(),
        callable_identity=CALLABLE_IDENTITY,
        protocol=JOB_IMPLEMENTATION_PROTOCOL,
        source_root=SOURCE_ROOT,
    )


def _job_cache_contract(
    writer: StateWriter,
    design: StudyDesign,
    member: StudyMember,
) -> tuple[tuple[str, ...], dict[str, str], tuple[str, ...]]:
    plan = member.job_plan
    if plan.produces_family_cache:
        return (
            plan.expected_outputs(),
            plan.expected_output_classes(),
            plan.job_input_hashes(),
        )
    producer = design.control
    completion = _completion(writer, design.binding, producer)
    outputs = completion.payload.get("outputs")
    if (
        completion.status != "success"
        or not isinstance(outputs, Mapping)
        or set(outputs) != set(producer.job_plan.expected_outputs())
    ):
        raise RuntimeError(
            "exposure-cap cache consumer lacks exact producer completion"
        )
    cache_hash = outputs.get(plan.cache_output_name)
    provenance_hash = outputs.get(plan.cache_provenance_output_name)
    producer_trace_hash = outputs.get(producer.job_plan.output_names["trace"])
    if any(
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
        for value in (cache_hash, provenance_hash, producer_trace_hash)
    ):
        raise RuntimeError("exposure-cap producer cache outputs are malformed")
    assert isinstance(cache_hash, str)
    assert isinstance(provenance_hash, str)
    assert isinstance(producer_trace_hash, str)
    return (
        plan.expected_outputs(),
        plan.expected_output_classes(),
        plan.job_input_hashes(
            cache_sha256=cache_hash,
            cache_provenance_sha256=provenance_hash,
            producer_trace_sha256=producer_trace_hash,
        ),
    )


def _job_spec(
    writer: StateWriter,
    design: StudyDesign,
    member: StudyMember,
    *,
    binding: StudyRunBinding,
    implementation_identity: str,
    ordinal: int,
) -> Mapping[str, Any]:
    expected_outputs, output_classes, input_hashes = _job_cache_contract(
        writer,
        design,
        member,
    )
    return {
        "budget": {"compute_seconds": 7200, "wall_seconds": 10800},
        "callable_identity": CALLABLE_IDENTITY,
        "evidence_subject": {
            "kind": "Executable",
            "id": member.executable.identity,
        },
        "expected_outputs": list(expected_outputs),
        "implementation_identity": implementation_identity,
        "input_hashes": list(input_hashes),
        "log_path": f"local/jobs/{binding.study_id.lower()}/{member.label}.log",
        "output_classes": output_classes,
        "resume_action": "continue_batch" if ordinal == 0 else "stop_batch",
        "scientific_binding": member.job_plan.scientific_binding(),
        "timeout_or_stop_rule": "finish the exact registered exposure-cap pair member",
        "worker_claims": [],
    }


def _completion(
    writer: StateWriter,
    binding: StudyRunBinding,
    member: StudyMember,
) -> Any:
    result = _operation_result(
        writer,
        f"{binding.operation_prefix}{member.label}-complete-job",
    )
    completion_id = result.get("completion_record_id")
    with writer.open_stable_index() as (_control, index):
        completion = (
            None
            if not isinstance(completion_id, str)
            else index.get("job-completed", completion_id)
        )
    if completion is None:
        raise RuntimeError("exposure-cap Job completion is unavailable")
    return completion


def _record_negative_memory_if_required(
    writer: StateWriter,
    binding: StudyRunBinding,
    member: StudyMember,
) -> str | None:
    completion = _completion(writer, binding, member)
    scientific = completion.payload.get("scientific")
    failed = (
        isinstance(scientific, Mapping)
        and scientific.get("scientific_eligible") is True
        and scientific.get("verdict") == "failed"
    )
    operation_id = binding.operation_prefix + member.label + "-negative-memory"
    existing = _operation_record(writer, operation_id)
    if not failed:
        if existing is not None:
            raise RuntimeError("exposure-cap negative memory exists for a non-failure")
        return None
    memory = NegativeMemory(
        executable_identity=member.executable.identity,
        scope=(
            f"{binding.study_id.lower().replace('-', '')}_"
            f"{member.label.replace('-', '_')}_discovery"
        ),
        evidence_references=(completion.record_id,),
        reason=(
            "The exact registered member contradicted the decisive component paths "
            "required for its coarse scientific verdict."
        ),
        reopen_condition=(
            "Reopen only with new registered material or a materially distinct causal "
            "risk mechanism, not an unchanged retry."
        ),
    )
    result = _ensure_operation(
        writer,
        binding,
        member.label + "-negative-memory",
        lambda: writer.record_negative_memory(
            memory=memory,
            operation_id=operation_id,
        ),
    )
    memory_id = result.get("negative_memory_id")
    if memory_id != memory.identity:
        raise RuntimeError("exposure-cap negative memory identity drifted")
    return memory.identity


def _close_outcome(completion: Any) -> str:
    scientific = completion.payload.get("scientific")
    adjudication = (
        None if not isinstance(scientific, Mapping) else scientific.get("adjudication")
    )
    state = None if not isinstance(adjudication, Mapping) else adjudication.get("state")
    if state in {"confirmed", "frontier", "partial_positive"}:
        return "preserved"
    if state == "contradicted":
        return "pruned"
    if state in {"not_evaluable", "unresolved"}:
        return "not_evaluable"
    raise RuntimeError("exposure-cap subject adjudication state is malformed")


def _known_operation_ids(design: StudyDesign) -> set[str]:
    suffixes = {
        "activate-current-v2-protocol",
        "batch-permit",
        "batch-permit-v2",
        "close-initiative",
        "close-study",
        "diagnose-study",
        "dispose-batch",
        "open-batch",
        "open-study",
        "preserve-decision",
        "preserved-snapshot",
        "prune-decision",
        "pruned-snapshot",
        "register-control",
        "register-exposure-cap",
        "work-decision",
    }
    suffixes.add(design.binding.study_permit_suffix)
    suffixes.update(design.binding.superseded_operation_suffixes)
    if design.structural_decision is not None:
        suffixes.update({"record-snapshot", "structural-decision"})
    for label in ("control", "exposure-cap"):
        suffixes.update(
            {
                f"{label}-complete-job",
                f"{label}-declare-job",
                f"{label}-job-permit",
                f"{label}-judge-job",
                f"{label}-negative-memory",
                f"{label}-start-job",
            }
        )
    return {design.binding.operation_prefix + suffix for suffix in suffixes}


def _require_operation_ownership(
    writer: StateWriter,
    design: StudyDesign,
) -> None:
    with writer.open_stable_index() as (_control, index):
        observed = {
            record.record_id
            for record in index.records_by_kind_prefix(
                "operation",
                design.binding.operation_prefix,
            )
        }
    unknown = sorted(observed.difference(_known_operation_ids(design)))
    if unknown:
        raise RuntimeError("unknown exposure-cap operation ids: " + ", ".join(unknown))


def run_study_close(writer: StateWriter, design: StudyDesign) -> Mapping[str, Any]:
    binding = design.binding
    _require_operation_ownership(writer, design)
    if design.structural_decision is not None:
        _ensure_operation(
            writer,
            binding,
            "structural-decision",
            lambda: writer.record_portfolio_decision(
                decision=design.structural_decision,
                operation_id=binding.operation_prefix + "structural-decision",
            ),
        )
        _ensure_operation(
            writer,
            binding,
            "record-snapshot",
            lambda: writer.record_portfolio_snapshot(
                snapshot=design.expanded_snapshot,
                operation_id=binding.operation_prefix + "record-snapshot",
            ),
        )
    _ensure_operation(
        writer,
        binding,
        "work-decision",
        lambda: writer.record_portfolio_decision(
            decision=design.work_decision,
            operation_id=binding.operation_prefix + "work-decision",
        ),
    )
    _ensure_operation(
        writer,
        binding,
        binding.study_permit_suffix,
        lambda: _study_permit(writer, design),
    )
    chassis = sleeve_exposure_cap_risk_successor_controlled_chassis()
    _ensure_operation(
        writer,
        binding,
        "open-study",
        lambda: writer.open_study(
            study_id=binding.study_id,
            question=design.question,
            material_identity=OBSERVED_MATERIAL_ID,
            material_display_name="foundation observed development material",
            semantic_proposal=design.proposal,
            semantic_question_lineage=design.semantic_question_lineage,
            controlled_chassis=chassis,
            portfolio_axis_id=design.axis.axis_id,
            portfolio_axis_identity=design.axis.identity,
            portfolio_decision_id=design.work_decision.identity,
            permit=_permit_from_operation(
                writer,
                binding.operation_prefix + binding.study_permit_suffix,
            ),
            operation_id=binding.operation_prefix + "open-study",
        ),
    )
    _ensure_operation(
        writer,
        binding,
        "batch-permit-v2",
        lambda: writer.issue_permit(
            kind=PermitKind.BATCH,
            subject_kind=SubjectKind.STUDY,
            subject_id=binding.study_id,
            input_hash=design.batch_spec.identity.removeprefix("batch:"),
            actions=("open_batch",),
            scope=("batch",),
            expires_at_utc=binding.permit_expiry_utc,
            one_shot=True,
            operation_id=binding.operation_prefix + "batch-permit-v2",
        ),
    )
    _ensure_operation(
        writer,
        binding,
        "open-batch",
        lambda: writer.open_batch(
            batch_spec=design.batch_spec,
            permit=_permit_from_operation(
                writer,
                binding.operation_prefix + "batch-permit-v2",
            ),
            operation_id=binding.operation_prefix + "open-batch",
        ),
    )
    for member in design.members:
        _ensure_operation(
            writer,
            binding,
            "register-" + member.label,
            lambda member=member: writer.register_trial(
                executable=member.executable,
                operation_id=(
                    binding.operation_prefix + "register-" + member.label
                ),
            ),
        )

    _activate_current_scientific_protocol(writer, design)
    implementation_identity = _materialize_job_authority(writer, design)
    for ordinal, member in enumerate(design.members):
        stem = member.label
        declaration = _ensure_operation(
            writer,
            binding,
            stem + "-declare-job",
            lambda member=member, ordinal=ordinal: writer.declare_job(
                spec=_job_spec(
                    writer,
                    design,
                    member,
                    binding=binding,
                    implementation_identity=implementation_identity,
                    ordinal=ordinal,
                ),
                operation_id=(
                    binding.operation_prefix + stem + "-declare-job"
                ),
            ),
        )
        if declaration.get("disposition") == "reuse_success":
            raise RuntimeError("exposure-cap Study unexpectedly reused a prior Job")
        job_id = declaration.get("job_id")
        job_hash = declaration.get("job_hash")
        if not isinstance(job_id, str) or not isinstance(job_hash, str):
            raise RuntimeError("exposure-cap Job declaration is malformed")
        _ensure_operation(
            writer,
            binding,
            stem + "-job-permit",
            lambda job_id=job_id, job_hash=job_hash, stem=stem: writer.issue_permit(
                kind=PermitKind.JOB,
                subject_kind=SubjectKind.JOB,
                subject_id=job_id,
                input_hash=job_hash,
                actions=("start_job",),
                scope=("job",),
                expires_at_utc=binding.permit_expiry_utc,
                one_shot=True,
                operation_id=(
                    binding.operation_prefix + stem + "-job-permit"
                ),
            ),
        )
        _ensure_operation(
            writer,
            binding,
            stem + "-start-job",
            lambda stem=stem: writer.start_job(
                permit=_permit_from_operation(
                    writer,
                    binding.operation_prefix + stem + "-job-permit",
                ),
                operation_id=(
                    binding.operation_prefix + stem + "-start-job"
                ),
            ),
        )

        def complete(member: StudyMember = member, stem: str = stem) -> Any:
            execution_payload = _operation_result(
                writer,
                binding.operation_prefix + stem + "-start-job",
            ).get("execution")
            if not isinstance(execution_payload, Mapping):
                raise RuntimeError("exposure-cap running Job execution is absent")
            original_builder = exposure_runtime.build_sleeve_exposure_cap_risk_job_plan

            def successor_builder(**kwargs: Any) -> SleeveExposureCapRiskJobPlan:
                if kwargs.get("definition") is None:
                    kwargs["successor"] = True
                return original_builder(**kwargs)

            exposure_runtime.build_sleeve_exposure_cap_risk_job_plan = (
                successor_builder
            )
            try:
                packet = execute_sleeve_exposure_cap_risk_job(
                    repository_root=ROOT,
                    execution=RunningJobExecution.from_mapping(execution_payload),
                )
            finally:
                exposure_runtime.build_sleeve_exposure_cap_risk_job_plan = (
                    original_builder
                )
            return writer.complete_job(
                outcome="success",
                output_manifest=packet.outputs(),
                operation_id=(
                    binding.operation_prefix + stem + "-complete-job"
                ),
            )

        _ensure_operation(writer, binding, stem + "-complete-job", complete)
        completion = _completion(writer, binding, member)
        scientific = completion.payload.get("scientific")
        if not isinstance(scientific, Mapping):
            raise RuntimeError("exposure-cap completion lacks scientific adjudication")
        negative_memory_id = _record_negative_memory_if_required(
            writer,
            binding,
            member,
        )
        _ensure_operation(
            writer,
            binding,
            stem + "-judge-job",
            lambda completion=completion, negative_memory_id=negative_memory_id, ordinal=ordinal, stem=stem: writer.judge_job_evidence(
                completion_record_id=completion.record_id,
                disposition="continue_batch" if ordinal == 0 else "stop_batch",
                negative_memory_id=negative_memory_id,
                operation_id=(
                    binding.operation_prefix + stem + "-judge-job"
                ),
            ),
        )
    _ensure_operation(
        writer,
        binding,
        "dispose-batch",
        lambda: writer.dispose_batch(
            outcome="completed",
            operation_id=binding.operation_prefix + "dispose-batch",
        ),
    )
    subject_completion = _completion(writer, binding, design.subject)
    outcome = _close_outcome(subject_completion)
    _ensure_operation(
        writer,
        binding,
        "close-study",
        lambda: writer.close_study(
            outcome=outcome,
            kpi_completion_record_id=subject_completion.record_id,
            operation_id=binding.operation_prefix + "close-study",
        ),
    )
    close_operation = _operation_record(
        writer,
        binding.operation_prefix + "close-study",
    )
    if close_operation is None:
        raise RuntimeError("exposure-cap Study close operation is absent")
    return {
        "batch_id": _durable_or_planned_batch_id(writer, design),
        "control_executable_id": design.control.executable.identity,
        "outcome": outcome,
        "study_close_event_id": close_operation.authority_event_id,
        "study_close_revision": close_operation.authority_sequence,
        "study_id": binding.study_id,
        "subject_executable_id": design.subject.executable.identity,
    }


def diagnose_study(writer: StateWriter, design: StudyDesign) -> Mapping[str, Any]:
    operation_id = design.binding.operation_prefix + "diagnose-study"
    with writer.open_stable_index() as (control, index):
        existing = index.get("operation", operation_id)
        pattern = study_claim_scoped_diagnosis(index, study_id=STUDY_ID)
        next_action = control["next_action"]
    if pattern is None:
        raise RuntimeError("STU-0125 claim-scoped diagnosis is unavailable")
    if existing is None:
        if (
            next_action.get("kind") != "diagnose_study"
            or next_action.get("study_id") != STUDY_ID
            or not isinstance(next_action.get("study_close_record_id"), str)
        ):
            raise RuntimeError("STU-0125 diagnosis is not the exact next action")
        result = writer.record_study_diagnosis(
            diagnosis=StudyDiagnosis(
                study_id=STUDY_ID,
                study_close_record_id=next_action["study_close_record_id"],
                evidence_state=pattern.evidence_state,
                confidence=pattern.confidence,
                rationale=(
                    "the status-normalized pair is evaluable and supports absolute "
                    "activity, after-cost economics, validity, selection-aware, and "
                    "temporal evidence, but the registered exposure-cap control "
                    "contrast is uniformly contradicted and monthly drawdown share "
                    "also fails; unrelated positives do not establish cap value"
                ),
                counterfactual=(
                    "an informative one-gross-slot cap would produce a positive "
                    "registered control delta with synchronized uncertainty support "
                    "while retaining acceptable drawdown concentration"
                ),
                reopen_condition=(
                    "do not repeat this exact cap or tune capacity or slot priority; "
                    "reopen only with new registered material or a distinct causal "
                    "point-in-time exposure state"
                ),
                diagnosis_reason_code=pattern.reason_code,
                supported_claim_ids=pattern.supported_claim_ids,
                contradicted_claim_ids=pattern.contradicted_claim_ids,
                unresolved_claim_ids=pattern.unresolved_claim_ids,
                diagnostic_criterion_ids=pattern.diagnostic_criterion_ids,
            ),
            operation_id=operation_id,
        ).result
    else:
        result = existing.payload.get("result")
        if existing.status != "success" or not isinstance(result, Mapping):
            raise RuntimeError("STU-0125 diagnosis operation is malformed")
    control = writer.read_control()
    if control is None:
        raise RuntimeError("STU-0125 diagnosis lost control")
    return {
        "diagnosis_pattern": pattern.to_payload(),
        "next_action": control["next_action"],
        "revision": control["revision"],
        "study_diagnosis_id": result.get("study_diagnosis_id"),
        "study_id": STUDY_ID,
    }


def update_portfolio(writer: StateWriter, design: StudyDesign) -> Mapping[str, Any]:
    with writer.open_stable_index() as (control, index):
        next_action = control["next_action"]
        diagnosis_id = next_action.get("study_diagnosis_id")
        diagnosis = (
            None
            if not isinstance(diagnosis_id, str)
            else index.get("study-diagnosis", diagnosis_id)
        )
    if (
        next_action.get("kind") != "portfolio_decision"
        or next_action.get("portfolio_snapshot_id") != BASE_SNAPSHOT_ID
        or diagnosis is None
        or diagnosis.payload.get("study_id") != STUDY_ID
        or diagnosis.payload.get("evidence_state") != "absent_information"
    ):
        raise RuntimeError("STU-0125 Portfolio update is not the exact next action")
    basis = _basis(
        ("portfolio-snapshot", BASE_SNAPSHOT_ID),
        ("study-close", diagnosis.payload["study_close_record_id"]),
        ("study-diagnosis", diagnosis_id),
    )
    decision = PortfolioDecision(
        decision_id="DEC-STU0125-PRUNE-EXPOSURE-CAP",
        chosen_option_id="prune-exposure-cap-axis",
        options=(
            DecisionOption(
                option_id="prune-exposure-cap-axis",
                action=PortfolioAction.PRUNE,
                target_id=NEW_AXIS_ID,
                expected_information_value=(
                    "retain the supported absolute component evidence while removing "
                    "the contradicted cap mechanism from active allocation"
                ),
                opportunity_cost="forego an unchanged or tuned exposure-cap retry",
            ),
            DecisionOption(
                option_id="rotate-independent-forest",
                action=PortfolioAction.ROTATE,
                target_id=ALTERNATE_AXIS_ID,
                expected_information_value=(
                    "retain an independent future branch under a separate protocol"
                ),
                opportunity_cost=(
                    "leave the completed cap diagnosis without an explicit axis prune"
                ),
                omission_reason=(
                    "the exact cap pair has already exhausted its preregistered "
                    "information and must be resolved before another allocation"
                ),
            ),
        ),
        rationale=(
            "prune the exposure-cap mechanism because its registered control delta "
            "and uncertainty are contradicted despite useful absolute component evidence"
        ),
        commitment_batches=1,
        quant_team_review=QuantTeamDecisionReview(
            assessments=(
                DecisionLensAssessment(
                    lens=DecisionLens.CAUSALITY,
                    position=DecisionLensPosition.SUPPORT,
                    option_ids=(
                        "prune-exposure-cap-axis",
                        "rotate-independent-forest",
                    ),
                    basis_records=basis,
                    finding=(
                        "the point-in-time implementation is valid, but its exact "
                        "causal control contrast is uniformly contradicted"
                    ),
                ),
                DecisionLensAssessment(
                    lens=DecisionLens.RISK,
                    position=DecisionLensPosition.SUPPORT,
                    option_ids=("prune-exposure-cap-axis",),
                    basis_records=basis,
                    finding=(
                        "the monthly realized drawdown-share diagnostic remains above "
                        "the preregistered ceiling"
                    ),
                ),
                DecisionLensAssessment(
                    lens=DecisionLens.STATISTICS,
                    position=DecisionLensPosition.SUPPORT,
                    option_ids=(
                        "prune-exposure-cap-axis",
                        "rotate-independent-forest",
                    ),
                    basis_records=basis,
                    finding=(
                        "synchronized uncertainty does not support a positive cap delta"
                    ),
                ),
            ),
            claim_boundary=(
                "Portfolio allocation only; preserve component evidence but create no "
                "candidate or confirmation authority"
            ),
            resolution_basis=(
                "resolve the exact one-batch commitment without tuning capacity or priority"
            ),
            disagreement_resolution=(
                "keep independent forest axes available after pruning this mechanism"
            ),
        ),
    )
    _ensure_operation(
        writer,
        design.binding,
        "prune-decision",
        lambda: writer.record_portfolio_decision(
            decision=decision,
            operation_id=design.binding.operation_prefix + "prune-decision",
        ),
    )
    snapshot = PortfolioSnapshot(
        mission_id=MISSION_ID,
        axes=tuple(
            replace(axis, status="pruned")
            if axis.axis_id == NEW_AXIS_ID
            else axis
            for axis in design.prior_axes
        ),
        opportunity_cost_basis=(
            "prune the contradicted exposure-cap mechanism while preserving its "
            "absolute component evidence and every independent forest axis"
        ),
        research_intake_id=design.expanded_snapshot.research_intake_id,
        exhaustion_standard=design.expanded_snapshot.exhaustion_standard_value(),
    )
    _ensure_operation(
        writer,
        design.binding,
        "pruned-snapshot",
        lambda: writer.record_portfolio_snapshot(
            snapshot=snapshot,
            operation_id=design.binding.operation_prefix + "pruned-snapshot",
        ),
    )
    _ensure_operation(
        writer,
        design.binding,
        "close-initiative",
        lambda: writer.close_initiative(
            outcome="completed",
            operation_id=design.binding.operation_prefix + "close-initiative",
        ),
    )
    control = writer.read_control()
    if control is None:
        raise RuntimeError("STU-0125 Portfolio update lost control")
    return {
        "decision_id": decision.identity,
        "next_action": control["next_action"],
        "portfolio_snapshot_id": snapshot.identity,
        "revision": control["revision"],
        "schema": "stu0125_portfolio_closeout.v1",
    }


def read_only_summary(writer: StateWriter, design: StudyDesign) -> Mapping[str, Any]:
    with writer.open_stable_index() as (control, index):
        operations = tuple(
            index.records_by_kind_prefix(
                "operation",
                design.binding.operation_prefix,
            )
        )
    return {
        "axis_id": design.axis.axis_id,
        "axis_identity": design.axis.identity,
        "base_snapshot_id": design.binding.portfolio_snapshot_id,
        "batch_id": _durable_or_planned_batch_id(writer, design),
        "control_executable_id": design.control.executable.identity,
        "expanded_snapshot_id": design.expanded_snapshot.identity,
        "job_implementation_identity": _job_implementation_identity(),
        "job_protocol": JOB_IMPLEMENTATION_PROTOCOL,
        "next_action": control["next_action"],
        "operation_count": len(operations),
        "revision": control["revision"],
        "structural_decision_id": (
            None
            if design.structural_decision is None
            else design.structural_decision.identity
        ),
        "study_id": design.binding.study_id,
        "subject_executable_id": design.subject.executable.identity,
        "work_decision_id": design.work_decision.identity,
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan or run the prospective sleeve exposure-cap risk Study."
    )
    parser.add_argument(
        "--stage",
        choices=("study-close", "diagnose", "portfolio"),
        help="omit for a read-only preregistration plan",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    registry = (
        EvidenceValidatorRegistry((ScientificAdjudicationValidatorV2(),))
        if arguments.stage == "study-close"
        else None
    )
    writer = StateWriter(ROOT, validation_registry=registry)
    writer.require_stable_head()
    design = build_design(writer)
    _require_operation_ownership(writer, design)
    if arguments.stage is None:
        print(json.dumps(read_only_summary(writer, design), sort_keys=True))
        return
    if arguments.stage == "diagnose":
        print(json.dumps(diagnose_study(writer, design), sort_keys=True))
        return
    if arguments.stage == "portfolio":
        print(json.dumps(update_portfolio(writer, design), sort_keys=True))
        return
    writer.permit_authority = PermitAuthority(
        PermitKeyStore(ROOT / "local" / "permit.key").load_or_create()
    )
    print(json.dumps(run_study_close(writer, design), sort_keys=True))


if __name__ == "__main__":
    main()
