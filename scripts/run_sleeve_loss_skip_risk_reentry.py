"""Run STU-0123 through the typed prospective engineering reentry route."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.operations.permits import (  # noqa: E402
    PermitAuthority,
    PermitKeyStore,
)
from axiom_rift.operations.study_diagnosis_projection import (  # noqa: E402
    study_claim_scoped_diagnosis,
)
from axiom_rift.operations.validation import EvidenceValidatorRegistry  # noqa: E402
from axiom_rift.operations.writer import StateWriter  # noqa: E402
from axiom_rift.research.discovery import OBSERVED_MATERIAL_ID  # noqa: E402
from axiom_rift.research.governance import StudyDiagnosis  # noqa: E402
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
from axiom_rift.research.semantic_question import (  # noqa: E402
    SemanticQuestionCore,
    SemanticQuestionLineageProposal,
    SemanticQuestionRelation,
)
from axiom_rift.research.sleeve_loss_skip_risk_chassis import (  # noqa: E402
    sleeve_loss_skip_risk_configurations,
    sleeve_loss_skip_risk_controlled_chassis,
    sleeve_loss_skip_risk_executable,
)
from axiom_rift.research.sleeve_loss_skip_risk_study import (  # noqa: E402
    build_sleeve_loss_skip_risk_job_plan,
)
from axiom_rift.research.validation_v2 import (  # noqa: E402
    ScientificAdjudicationValidatorV2,
)
from scripts.run_sleeve_loss_skip_risk_study import (  # noqa: E402
    StudyDesign,
    StudyMember,
    StudyRunBinding,
    read_only_summary,
    run_study_close,
)


MISSION_ID = "MIS-0006"
INITIATIVE_ID = "INI-0025"
STUDY_ID = "STU-0123"
PREDECESSOR_STUDY_ID = "STU-0122"
BATCH_DISPLAY_ID = "BAT-0123"
SNAPSHOT_ID = (
    "portfolio:e693ac3c70b098d3e7da5ed645e3c320d9ce73202ff6d3ed32cf13f0d96296ab"
)
AXIS_ID = "axis-sleeve-realized-loss-skip-risk"
AXIS_IDENTITY = (
    "axis:80c33cdd391ca0e0a8e5595cd41fd7c6d8eaa1bf6d296af86d13572e33b8b0e8"
)
ALTERNATE_AXIS_ID = "axis-p0-composite-audit-reanalysis"
DIAGNOSIS_ID = (
    "diagnosis:731be2e2dfa9fe0dc707b4b233d848d54e193602ce61e37fb128b92e38922840"
)
STUDY_CLOSE_RECORD_ID = (
    "2bfc731c7596538c8f2fed5f0844dd900178d1039be456915839d3b0f6f41ab5"
)
COMPLETION_RECORD_ID = (
    "f3ecc7e7934fde373998d012a455f8df0f0d85be79bc445fcd293f81469acac8"
)
DISPOSITION_RECORD_ID = (
    "e0ee048da9db4f6e4fcbc7badc243f1d7994a4c4a29ed0ac859713c1553f170a"
)
DISPOSITION_HASH = (
    "354a763a602502f763b498d8fe6591c49c9f1718c03e17342ba15ffa0fab1b42"
)
SUCCESSOR_ARTIFACT_HASH = (
    "39c45990a6e003cd71799cc64e6073ec15eaa5774a89d55c6822f11c2fbded3a"
)
EXPECTED_BASELINE_EXECUTABLE_ID = (
    "executable:d8f73761de66b1998ca639f4dbe58d5fdd0e26766855c0553ad36f97e80f71f4"
)
EXPECTED_WORK_DECISION_ID = (
    "decision:881ccf9f680d7897d487b8434d066993839ec67d4394219f4a0a8ef0c1a22aa3"
)
OPERATION_PREFIX = "goal-audit-stu0123-intent-calendar-reentry-v1-"
PERMIT_EXPIRY_UTC = "2027-12-31T23:59:59Z"


def _basis(*values: tuple[str, str]) -> tuple[DecisionBasisRecord, ...]:
    return tuple(
        DecisionBasisRecord(kind=kind, record_id=record_id)
        for kind, record_id in sorted(set(values))
    )


def _snapshot_and_predecessor(
    writer: StateWriter,
) -> tuple[PortfolioSnapshot, tuple[Any, ...], Mapping[str, Any]]:
    with writer.open_stable_index() as (control, index):
        science = control["scientific"]
        initial_action = {
            "kind": "portfolio_decision",
            "portfolio_snapshot_id": SNAPSHOT_ID,
            "study_diagnosis_id": DIAGNOSIS_ID,
        }
        decision_operation = index.get(
            "operation",
            OPERATION_PREFIX + "work-decision",
        )
        decision_result = (
            None
            if decision_operation is None
            else decision_operation.payload.get("result")
        )
        progressed = (
            decision_operation is not None
            and decision_operation.status == "success"
            and isinstance(decision_result, Mapping)
            and decision_result.get("decision_id")
            == EXPECTED_WORK_DECISION_ID
        )
        if (
            science["active_mission"] != MISSION_ID
            or science["active_initiative"] != INITIATIVE_ID
            or (
                control["next_action"] != initial_action
                and not progressed
            )
            or science.get("active_study") not in {None, STUDY_ID}
            or (
                science.get("active_batch") is not None
                and science.get("active_study") != STUDY_ID
            )
        ):
            raise RuntimeError("STU-0123 is not at its exact Portfolio boundary")
        snapshot_record = index.get("portfolio-snapshot", SNAPSHOT_ID)
        predecessor = index.get("study-open", PREDECESSOR_STUDY_ID)
        if snapshot_record is None or predecessor is None:
            raise RuntimeError("STU-0123 durable predecessor authority is absent")
        raw_axes = snapshot_record.payload.get("axes")
        if not isinstance(raw_axes, list) or any(
            not isinstance(axis, Mapping) for axis in raw_axes
        ):
            raise RuntimeError("STU-0123 Portfolio axes are malformed")
        surfaces = architecture_surfaces_from_axis_projection(raw_axes)
        component_payloads = tuple(
            record.payload
            for record in index.component_manifests_by_surfaces(
                "architecture_role",
                surfaces,
            )
        )
        axes = portfolio_axes_from_projection(
            raw_axes,
            component_surface_registry(component_payloads),
        )
        for kind, record_id in (
            ("study-diagnosis", DIAGNOSIS_ID),
            ("study-close", STUDY_CLOSE_RECORD_ID),
            ("job-completed", COMPLETION_RECORD_ID),
            ("repair-close", DISPOSITION_RECORD_ID),
        ):
            if index.get(kind, record_id) is None:
                raise RuntimeError(f"STU-0123 lacks {kind}:{record_id}")
        question = predecessor.payload.get("question")
        if not isinstance(question, Mapping):
            raise RuntimeError("STU-0123 predecessor question is malformed")
        snapshot_payload = snapshot_record.payload
    snapshot = PortfolioSnapshot(
        mission_id=MISSION_ID,
        axes=axes,
        opportunity_cost_basis=snapshot_payload["opportunity_cost_basis"],
        research_intake_id=snapshot_payload.get("research_intake_id"),
        exhaustion_standard=snapshot_payload.get("exhaustion_standard"),
    )
    if snapshot.identity != SNAPSHOT_ID:
        raise RuntimeError("STU-0123 Portfolio snapshot identity drifted")
    return snapshot, axes, dict(question)


def build_design(writer: StateWriter) -> StudyDesign:
    snapshot, axes, predecessor_question = _snapshot_and_predecessor(writer)
    axes_by_id = {axis.axis_id: axis for axis in axes}
    axis = axes_by_id.get(AXIS_ID)
    if (
        axis is None
        or axis.identity != AXIS_IDENTITY
        or ALTERNATE_AXIS_ID not in axes_by_id
    ):
        raise RuntimeError("STU-0123 Portfolio axis authority drifted")
    core = SemanticQuestionCore.from_question_manifest(predecessor_question)
    lineage = SemanticQuestionLineageProposal(
        predecessor_study_id=PREDECESSOR_STUDY_ID,
        successor_study_id=STUDY_ID,
        predecessor_core_id=core.identity,
        successor_core_id=core.identity,
        relation=SemanticQuestionRelation.ENGINEERING_REENTRY,
        rationale=(
            "reenter the same causal question under the validated eligible-day "
            "intent calendar without inheriting predecessor evidence"
        ),
        basis_record_ids=(
            "job-completed:" + COMPLETION_RECORD_ID,
            "study-close:" + STUDY_CLOSE_RECORD_ID,
            "study-diagnosis:" + DIAGNOSIS_ID,
            "study-open:" + PREDECESSOR_STUDY_ID,
        ),
    )
    chassis = sleeve_loss_skip_risk_controlled_chassis()
    configurations = sleeve_loss_skip_risk_configurations()
    executables = tuple(
        sleeve_loss_skip_risk_executable(configuration)
        for configuration in configurations
    )
    if (
        len(executables) != 2
        or executables[0].identity != EXPECTED_BASELINE_EXECUTABLE_ID
        or chassis.baseline_executable.identity != executables[0].identity
        or executables[0].identity == executables[1].identity
    ):
        raise RuntimeError("STU-0123 corrected Executable family drifted")
    reentry = ProspectiveEngineeringReentry(
        mission_id=MISSION_ID,
        portfolio_snapshot_id=SNAPSHOT_ID,
        target_axis_id=AXIS_ID,
        target_axis_identity=AXIS_IDENTITY,
        predecessor_study_id=PREDECESSOR_STUDY_ID,
        successor_study_id=STUDY_ID,
        study_diagnosis_id=DIAGNOSIS_ID,
        study_close_record_id=STUDY_CLOSE_RECORD_ID,
        completion_record_id=COMPLETION_RECORD_ID,
        disposition_record_id=DISPOSITION_RECORD_ID,
        disposition_hash=DISPOSITION_HASH,
        successor_artifact_hash=SUCCESSOR_ARTIFACT_HASH,
        successor_baseline_executable_id=executables[0].identity,
        portfolio_action=PortfolioAction.DEEPEN.value,
        semantic_question_lineage=lineage,
    )
    review_basis = _basis(
        ("job-completed", COMPLETION_RECORD_ID),
        ("portfolio-snapshot", SNAPSHOT_ID),
        ("repair-close", DISPOSITION_RECORD_ID),
        ("study-close", STUDY_CLOSE_RECORD_ID),
        ("study-diagnosis", DIAGNOSIS_ID),
    )
    chosen_option_id = "deepen-corrected-loss-skip"
    alternate_option_id = "rotate-independent-forest"
    work_decision = PortfolioDecision(
        decision_id="DEC-STU0123-CORRECTED-LOSS-SKIP-REENTRY",
        chosen_option_id=chosen_option_id,
        options=(
            DecisionOption(
                option_id=chosen_option_id,
                action=PortfolioAction.DEEPEN,
                target_id=AXIS_ID,
                expected_information_value=(
                    "recover the blocked same-sleeve causal comparison under "
                    "the validated eligible-day protocol"
                ),
                opportunity_cost="one bounded two-member corrected Batch",
            ),
            DecisionOption(
                option_id=alternate_option_id,
                action=PortfolioAction.ROTATE,
                target_id=ALTERNATE_AXIS_ID,
                expected_information_value=(
                    "advance an independent synthesis branch in the open forest"
                ),
                opportunity_cost=(
                    "leave the already materialized causal correction unresolved"
                ),
                omission_reason=(
                    "the corrected pair is preregistered, bounded, and resolves a "
                    "non-scientific gap before paying another branch switch"
                ),
            ),
        ),
        rationale=(
            "recover one repairable branch without treating its predecessor as "
            "science and without locking the independent forest"
        ),
        commitment_batches=1,
        quant_team_review=QuantTeamDecisionReview(
            assessments=(
                DecisionLensAssessment(
                    lens=DecisionLens.ARCHITECTURE,
                    position=DecisionLensPosition.SUPPORT,
                    option_ids=(chosen_option_id, alternate_option_id),
                    basis_records=review_basis,
                    finding=(
                        "the registered successor changes the protected intent "
                        "calendar and binds its exact corrected baseline"
                    ),
                ),
                DecisionLensAssessment(
                    lens=DecisionLens.CAUSALITY,
                    position=DecisionLensPosition.SUPPORT,
                    option_ids=(chosen_option_id,),
                    basis_records=review_basis,
                    finding=(
                        "the same-core lineage recovers the original estimand while "
                        "all predecessor evidence remains excluded"
                    ),
                ),
                DecisionLensAssessment(
                    lens=DecisionLens.RISK,
                    position=DecisionLensPosition.UNCERTAIN,
                    option_ids=(chosen_option_id, alternate_option_id),
                    basis_records=review_basis,
                    finding=(
                        "the skip may reduce clustering by destroying activity, so "
                        "component claims and the independent rotation stay separate"
                    ),
                ),
            ),
            claim_boundary=(
                "allocation and engineering reentry only; no scientific, candidate, "
                "negative-memory, or terminal inheritance"
            ),
            resolution_basis=(
                "run one exact corrected pair because its authority and opportunity "
                "cost are both bounded"
            ),
            disagreement_resolution=(
                "retain the independent rotation as a material future option and "
                "judge density separately from risk benefit"
            ),
        ),
        baseline_executable=executables[0],
        engineering_reentry=reentry,
    )
    if work_decision.identity != EXPECTED_WORK_DECISION_ID:
        raise RuntimeError("STU-0123 work Decision identity drifted")
    question = {
        name: predecessor_question[name]
        for name in (
            "causal_question",
            "changed_variables",
            "controlled_variables",
            "done_conditions",
            "evidence_modes",
        )
    }
    if SemanticQuestionCore.from_question_manifest(question).identity != core.identity:
        raise RuntimeError("STU-0123 semantic question core drifted")
    definition_plan = build_sleeve_loss_skip_risk_job_plan(
        repository_root=ROOT,
        mission_id=MISSION_ID,
        study_id=STUDY_ID,
        executable_id=executables[0].identity,
    )
    definition = definition_plan.definition
    if definition.prospective_executable_ids != tuple(
        executable.identity for executable in executables
    ):
        raise RuntimeError("STU-0123 corrected family definition drifted")
    proposal = {
        "candidate_eligible": False,
        "concurrent_family": {
            "control_executable_id": executables[0].identity,
            "ordered_executable_ids": list(
                definition.prospective_executable_ids
            ),
            "subject_executable_id": executables[1].identity,
        },
        "control_policy": configurations[0].configuration_id,
        "engineering_reentry_id": reentry.identity,
        "estimand": (
            "corrected subject minus corrected unrestricted control under one "
            "common preregistered eligible calendar"
        ),
        "mechanism": axis.mechanism_family,
        "predecessor_study_id": PREDECESSOR_STUDY_ID,
        "schema": "sleeve_loss_skip_risk_study.v2",
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
    batch_spec = BatchSpec(
        batch_id=BATCH_DISPLAY_ID,
        study_id=STUDY_ID,
        study_hash=study_hash,
        display_name="corrected same-sleeve realized-loss one-entry skip pair",
        max_trials=2,
        max_compute_seconds=14400,
        max_wall_seconds=21600,
        stop_rule=(
            "stop after both corrected preregistered members receive exactly one "
            "validated Job; no adaptive variant or unchanged retry"
        ),
        source_contract_ids=tuple(executables[0].source_contracts),
        acceptance_profile={
            "candidate_authority": "none_discovery_only",
            "concurrent_family_size": 2,
            "predecessor_evidence_inheritance": False,
            "required_member_completions": 2,
            "scientific_judgment": "component_aware_validator_v2",
        },
        adaptive_basis={
            "uncertainty": "one repaired binary causal policy contrast",
            "causal_complexity": "one realized event arms one eligible skip",
            "surface_curvature": "not searched; no tunable surface",
            "compute_cost": "two bounded Jobs over one corrected pair",
            "expected_information_value": (
                "resolve the blocked risk-timing question without inherited credit"
            ),
            "portfolio_opportunity_cost": (
                "one Batch while the independent forest option remains selectable"
            ),
        },
        concurrent_family=ConcurrentFamilyManifest(
            evaluation_mode=ConcurrentFamilyEvaluationMode.VECTORIZED,
            executable_ids=tuple(sorted(definition.prospective_executable_ids)),
        ),
    )
    members = tuple(
        StudyMember(
            label="control" if ordinal == 0 else "loss-skip",
            executable=executable,
            job_plan=(
                definition_plan
                if ordinal == 0
                else build_sleeve_loss_skip_risk_job_plan(
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
        raise RuntimeError("STU-0123 member definitions differ")
    return StudyDesign(
        binding=StudyRunBinding(
            study_id=STUDY_ID,
            initiative_id=INITIATIVE_ID,
            operation_prefix=OPERATION_PREFIX,
            permit_expiry_utc=PERMIT_EXPIRY_UTC,
            portfolio_snapshot_id=SNAPSHOT_ID,
            study_permit_suffix="study-permit-lineage-v2",
            superseded_operation_suffixes=("study-permit",),
        ),
        prior_axes=axes,
        axis=axis,
        structural_decision=None,
        expanded_snapshot=snapshot,
        work_decision=work_decision,
        question=question,
        proposal=proposal,
        batch_spec=batch_spec,
        members=members,
        semantic_question_lineage=lineage,
    )


def summary(writer: StateWriter, design: StudyDesign) -> Mapping[str, Any]:
    value = dict(read_only_summary(writer, design))
    value.update(
        {
            "engineering_reentry_id": (
                design.work_decision.engineering_reentry.identity
            ),
            "predecessor_study_id": PREDECESSOR_STUDY_ID,
            "semantic_question_lineage_id": (
                design.semantic_question_lineage.identity
            ),
            "successor_artifact_hash": SUCCESSOR_ARTIFACT_HASH,
        }
    )
    return value


def diagnose_study(writer: StateWriter) -> Mapping[str, Any]:
    operation_id = OPERATION_PREFIX + "diagnose-study"
    with writer.open_stable_index() as (control, index):
        existing = index.get("operation", operation_id)
        pattern = study_claim_scoped_diagnosis(
            index,
            study_id=STUDY_ID,
        )
        next_action = control["next_action"]
    if pattern is None:
        raise RuntimeError("STU-0123 claim-scoped diagnosis is unavailable")
    if existing is None:
        if next_action != {
            "kind": "diagnose_study",
            "portfolio_snapshot_id": SNAPSHOT_ID,
            "study_close_record_id": (
                "d770d99dd51b20e1a9ac908c2e72180144a6329edce4b2e1026a626e20c24e28"
            ),
            "study_id": STUDY_ID,
        }:
            raise RuntimeError("STU-0123 diagnosis is not the exact next action")
        result = writer.record_study_diagnosis(
            diagnosis=StudyDiagnosis(
                study_id=STUDY_ID,
                study_close_record_id=next_action["study_close_record_id"],
                evidence_state=pattern.evidence_state,
                confidence=pattern.confidence,
                rationale=(
                    "the corrected pair is evaluable and preserves absolute "
                    "activity, after-cost economics, validity, selection-aware, "
                    "and temporal evidence, but the registered control contrast "
                    "is uniformly contradicted and the monthly drawdown-share "
                    "diagnostic also fails; unrelated positives cannot promote "
                    "the loss-skip mechanism"
                ),
                counterfactual=(
                    "a useful one-entry loss-skip mechanism would produce a "
                    "positive registered control delta with its synchronized "
                    "uncertainty supported while retaining acceptable drawdown "
                    "share; the exact corrected evidence does not"
                ),
                reopen_condition=(
                    "do not repeat the exact skip-next policy; reopen only with "
                    "new registered material or a materially distinct causal "
                    "loss-state risk mechanism and a fresh preregistered control "
                    "contrast"
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
            raise RuntimeError("STU-0123 diagnosis operation is malformed")
    control = writer.read_control()
    if control is None:
        raise RuntimeError("STU-0123 diagnosis lost control")
    return {
        "diagnosis_pattern": pattern.to_payload(),
        "next_action": control["next_action"],
        "revision": control["revision"],
        "study_diagnosis_id": result.get("study_diagnosis_id"),
        "study_id": STUDY_ID,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plan or run corrected STU-0123 engineering reentry."
    )
    parser.add_argument(
        "--stage",
        choices=("study-close", "diagnose"),
        help="omit for a read-only exact preregistration plan",
    )
    arguments = parser.parse_args()
    registry = (
        EvidenceValidatorRegistry((ScientificAdjudicationValidatorV2(),))
        if arguments.stage == "study-close"
        else None
    )
    writer = StateWriter(
        ROOT,
        validation_registry=registry,
    )
    writer.require_stable_head()
    design = build_design(writer)
    if arguments.stage is None:
        print(json.dumps(summary(writer, design), sort_keys=True))
        return
    if arguments.stage == "diagnose":
        print(json.dumps(diagnose_study(writer), sort_keys=True))
        return
    writer.permit_authority = PermitAuthority(
        PermitKeyStore(ROOT / "local" / "permit.key").load_or_create()
    )
    print(json.dumps(run_study_close(writer, design), sort_keys=True))


if __name__ == "__main__":
    main()
