from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator
from unittest.mock import patch

import pytest

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec, canonical_digest
from axiom_rift.operations.permits import PermitAuthority
from axiom_rift.operations.replay_job_implementation_preflight import (
    REPLACEMENT_REQUIRED,
    ReplayJobImplementationPreflightError,
    ReplayJobImplementationPreflightRequest,
    ReplayJobImplementationPreflightResult,
    replay_executable_reference_map,
)
from axiom_rift.operations.replay_projection import (
    initial_obligation_record,
    obligation_heads,
)
from axiom_rift.operations.writer import (
    RecoveryRequired,
    StateWriter,
    TransitionError,
)
from axiom_rift.research.governance import (
    DiagnosisConfidence,
    EvidenceState,
    StudyDiagnosis,
)
from axiom_rift.research.historical_adjudication import ReplayPriority
from axiom_rift.research.replay_obligation import (
    ReplayDeferral,
    ReplayDeferralBasis,
    ReplayDeferralBasisKind,
    ReplayDeferralExecutionBinding,
    ReplayResumeCondition,
    ReplayResumeConditionKind,
    ReplayResumeEvidence,
    derive_historical_replay_obligation,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex
from tests.operations import test_replay_partial_recertification as recert
from tests.operations.test_writer import (
    FIXED_NOW,
    FIXTURE_DELIVERY_CAPABILITY,
    REPO_ROOT,
    scientific_executable_spec,
)


_ORIGINAL_STUDY_ID = "STU-PARTIAL-TERMINAL-ORIGINAL"
_REJECTION_REASON = "pre_job_implementation_authority_invalid"


@dataclass(frozen=True, slots=True)
class _PartialReplayCase:
    fixture: recert._LegacyReplay
    obligation: object
    historical_reference_ids: tuple[str, ...]
    target_ordinal: int

    @property
    def target_member(self) -> ExecutableSpec:
        return self.fixture.members[self.target_ordinal]  # type: ignore[return-value]

    @property
    def request(self) -> ReplayJobImplementationPreflightRequest:
        return _request(
            self,
            executables=self.fixture.members,  # type: ignore[arg-type]
            implementation_identity="f" * 64,
        )


@dataclass(frozen=True, slots=True)
class _DiagnosedPartialReplay:
    case: _PartialReplayCase
    preflight_id: str
    study_close_id: str
    diagnosis_id: str
    trial_delta: int


def _typed_member(
    tag: str,
    *,
    historical_reference_id: str,
) -> ExecutableSpec:
    base = scientific_executable_spec(tag)
    owner = base.components[-1]
    typed_owner = ComponentSpec(
        display_name=owner.display_name,
        protocol=owner.protocol,
        implementation=owner.implementation,
        spec={
            **owner.specification(),
            "parameter_fields": ["historical_reference_executable_id"],
        },
        semantic_dependencies=owner.semantic_dependencies,
    )
    return ExecutableSpec(
        display_name=base.display_name,
        components=(*base.components[:-1], typed_owner),
        parameters={
            **base.parameter_values(),
            "historical_reference_executable_id": historical_reference_id,
        },
        data_contract=base.data_contract,
        split_contract=base.split_contract,
        clock_contract=base.clock_contract,
        cost_contract=base.cost_contract,
        engine_contract=base.engine_contract,
        source_contracts=base.source_contracts,
    )


def _replacement_member(member: ExecutableSpec, ordinal: int) -> ExecutableSpec:
    owner = member.components[-1]
    replacement_owner = ComponentSpec(
        display_name=owner.display_name,
        protocol=owner.protocol,
        implementation=(
            f"fixture.partial_terminal.replacement_{ordinal:02d}@sha256:"
            + f"{ordinal + 20:064x}"
        ),
        spec=owner.specification(),
        semantic_dependencies=owner.semantic_dependencies,
    )
    return ExecutableSpec(
        display_name=member.display_name,
        components=(*member.components[:-1], replacement_owner),
        parameters=member.parameter_values(),
        data_contract=member.data_contract,
        split_contract=member.split_contract,
        clock_contract=member.clock_contract,
        cost_contract=member.cost_contract,
        engine_contract=member.engine_contract,
        source_contracts=member.source_contracts,
    )


def _adjudication_payload(target_reference_id: str) -> dict[str, object]:
    return {
        "adjudication": {
            "candidate_eligible": False,
            "claims": [{"claim_id": "claim-partial-terminal"}],
            "criteria": [
                {"criterion_id": "criterion-a"},
                {"criterion_id": "criterion-b"},
            ],
        },
        "audit_artifact_hash": "1" * 64,
        "completion_record_id": "2" * 64,
        "disposition": "replay_required",
        "executable_id": target_reference_id,
        "measurement_artifact_hash": "4" * 64,
        "reason_codes": ["missing_exact_uncertainty"],
        "replay_priority": ReplayPriority.P0.value,
        "schema": "historical_scientific_adjudication.v2",
        "study_close_record_id": "5" * 64,
        "study_id": _ORIGINAL_STUDY_ID,
        "validation_plan_hash": "6" * 64,
    }


def _build_case(tmp_path: Path, *, target_ordinal: int) -> _PartialReplayCase:
    references = tuple(
        f"executable:{ordinal:064x}" for ordinal in range(1, 5)
    )
    adjudication_payload = _adjudication_payload(references[target_ordinal])
    adjudication_id = "historical-adjudication:" + "7" * 64
    obligation = derive_historical_replay_obligation(
        governing_mission_id=recert.MISSION_ID,
        historical_adjudication_id=adjudication_id,
        adjudication_payload=adjudication_payload,
    )

    def member_factory(tag: str, **_kwargs: object) -> ExecutableSpec:
        ordinal = int(tag.rsplit("-", 1)[-1])
        return _typed_member(
            tag,
            historical_reference_id=references[ordinal - 1],
        )

    with (
        patch.object(recert, "OBLIGATION_ID", obligation.identity),
        patch.object(
            recert,
            "scientific_executable_spec",
            side_effect=member_factory,
        ),
    ):
        fixture = recert._build_legacy_replay(tmp_path)

    adjudication = IndexRecord(
        kind="historical-scientific-adjudication",
        record_id=adjudication_id,
        subject=f"Study:{_ORIGINAL_STUDY_ID}",
        status="replay_required",
        fingerprint="7" * 64,
        payload=adjudication_payload,
    )

    def prepare(current: dict[str, object] | None, _index: LocalIndex):
        assert current is not None
        return fixture.writer._body(current), [
            adjudication,
            initial_obligation_record(obligation),
        ], {"obligation_id": obligation.identity, "trial_delta": 0}

    fixture.writer._commit(
        event_kind="partial_replay_obligation_fixture_seeded",
        operation_id="partial-terminal-seed-obligation",
        subject=f"Mission:{recert.MISSION_ID}",
        payload={"obligation_id": obligation.identity},
        prepare=prepare,
    )
    return _PartialReplayCase(
        fixture=fixture,
        obligation=obligation,
        historical_reference_ids=references,
        target_ordinal=target_ordinal,
    )


def _request(
    case: _PartialReplayCase,
    *,
    executables: tuple[ExecutableSpec, ...],
    implementation_identity: str,
    replacement_for_preflight_id: str | None = None,
    protocol_id: str = recert.PROTOCOL_ID,
    callable_identity: str = recert.CALLABLE_IDENTITY,
) -> ReplayJobImplementationPreflightRequest:
    return ReplayJobImplementationPreflightRequest(
        mission_id=recert.MISSION_ID,
        protocol_id=protocol_id,
        callable_identity=callable_identity,
        implementation_identity=implementation_identity,
        executables=executables,
        scientific_bindings=tuple(
            {
                "validation_plan_hash": f"{ordinal:064x}",
                "validator_id": recert.ScientificAdjudicationValidatorV2.validator_id,
            }
            for ordinal in range(1, len(executables) + 1)
        ),
        replay_obligation_ids=(case.obligation.identity,),
        replacement_for_preflight_id=replacement_for_preflight_id,
    )


def _surface(
    request: ReplayJobImplementationPreflightRequest,
    **_kwargs: object,
) -> dict[str, object]:
    references = replay_executable_reference_map(request.executables)
    return {
        "callable_identity": request.callable_identity,
        "historical_reference_ids": sorted(references),
        "mission_id": request.mission_id,
        "protocol_id": request.protocol_id,
        "replay_obligation_ids": list(request.replay_obligation_ids),
        "schema": "partial_replay_terminal_surface.v1",
    }


def _surface_hash(surface: object) -> str:
    return canonical_digest(
        domain="partial-replay-terminal-surface",
        payload=surface,
    )


def _require_replacement_surface(
    *,
    prior_preflight_id: str,
    prior_payload: dict[str, object],
    replacement_payload: dict[str, object],
) -> None:
    """Fixture adapter that preserves the production replacement invariants.

    The integration test intentionally uses compact validation-plan fixtures,
    so the expensive scientific-surface parser is replaced.  Family reference
    equality, fresh Executable identity, implementation replacement, Mission,
    obligation, exact prior-preflight binding, and each technical identity's
    own surface binding remain independently checked here.  Protocol and
    callable names are implementation authority, not scientific equivalence.
    The Writer, Journal, SQLite streams, trial accounting, terminal, deferral,
    replacement, and resume paths stay real.
    """

    prior_surface = prior_payload.get("scientific_surface")
    replacement_surface = replacement_payload.get("scientific_surface")
    prior_references = replay_executable_reference_map(
        prior_payload.get("executable_manifests")
    )
    replacement_references = replay_executable_reference_map(
        replacement_payload.get("executable_manifests")
    )
    prior_ids = prior_payload.get("executable_ids")
    replacement_ids = replacement_payload.get("executable_ids")
    prior_equivalence = (
        {
            key: value
            for key, value in prior_surface.items()
            if key not in {"callable_identity", "protocol_id"}
        }
        if isinstance(prior_surface, dict)
        else None
    )
    replacement_equivalence = (
        {
            key: value
            for key, value in replacement_surface.items()
            if key not in {"callable_identity", "protocol_id"}
        }
        if isinstance(replacement_surface, dict)
        else None
    )
    invalid = (
        prior_payload.get("outcome") != "rejected"
        or prior_payload.get("remediation_kind") != REPLACEMENT_REQUIRED
        or replacement_payload.get("replacement_for_preflight_id")
        != prior_preflight_id
        or replacement_payload.get("mission_id")
        != prior_payload.get("mission_id")
        or replacement_payload.get("replay_obligation_ids")
        != prior_payload.get("replay_obligation_ids")
        or not isinstance(prior_surface, dict)
        or not isinstance(replacement_surface, dict)
        or prior_surface.get("protocol_id")
        != prior_payload.get("protocol_id")
        or replacement_surface.get("protocol_id")
        != replacement_payload.get("protocol_id")
        or prior_surface.get("callable_identity")
        != prior_payload.get("callable_identity")
        or replacement_surface.get("callable_identity")
        != replacement_payload.get("callable_identity")
        or prior_payload.get("scientific_surface_hash")
        != _surface_hash(prior_surface)
        or replacement_payload.get("scientific_surface_hash")
        != _surface_hash(replacement_surface)
        or replacement_equivalence != prior_equivalence
        or set(prior_references) != set(replacement_references)
        or not isinstance(prior_ids, list)
        or not isinstance(replacement_ids, list)
        or set(prior_ids) != set(prior_references.values())
        or set(replacement_ids) != set(replacement_references.values())
        or set(prior_ids).intersection(replacement_ids)
        or replacement_payload.get("implementation_identity")
        == prior_payload.get("implementation_identity")
    )
    if invalid:
        raise ReplayJobImplementationPreflightError(
            "replacement replay implementation changed its scientific surface"
        )


@contextmanager
def _compact_scientific_surface_boundary() -> Iterator[None]:
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "axiom_rift.operations.replay_job_implementation_preflight."
                "derive_replay_job_scientific_surface",
                side_effect=_surface,
            )
        )
        stack.enter_context(
            patch(
                "axiom_rift.operations.replay_job_implementation_preflight."
                "replay_job_scientific_surface_hash",
                side_effect=_surface_hash,
            )
        )
        stack.enter_context(
            patch(
                "axiom_rift.operations.replay_job_implementation_preflight."
                "require_replacement_replay_job_scientific_surface",
                side_effect=_require_replacement_surface,
            )
        )
        yield


def _register_legacy_member(case: _PartialReplayCase, ordinal: int) -> object:
    admission = SimpleNamespace(
        payload={
            "request": {
                "executable_manifests": [
                    member.to_identity_payload()
                    for member in case.fixture.members
                ]
            }
        }
    )
    with (
        patch.object(
            case.fixture.writer,
            "_study_replay_implementation_admission",
            return_value=admission,
        ),
        patch.object(
            case.fixture.writer,
            "_require_replay_registration_source_authority",
            return_value=None,
        ),
        patch(
            "axiom_rift.research.chassis.validate_controlled_executable",
            return_value=None,
        ),
    ):
        return case.fixture.writer.register_trial(
            executable=case.fixture.members[ordinal],
            operation_id=f"partial-terminal-register-{ordinal + 1}",
        )


def _preflight_result(
    request: ReplayJobImplementationPreflightRequest,
    *,
    accepted: bool,
) -> ReplayJobImplementationPreflightResult:
    if accepted:
        return ReplayJobImplementationPreflightResult(
            request=request,
            accepted=True,
            artifact_hashes=("e" * 64,),
            source_closure_authority={
                "callable_module_path": (
                    "axiom_rift/research/partial_replay_terminal.py"
                ),
                "dependency_count": 1,
                "path_inventory_hash": "d" * 64,
                "schema": "job_implementation_source_authority.v1",
                "source_closure_hash": "c" * 64,
            },
        )
    return ReplayJobImplementationPreflightResult(
        request=request,
        accepted=False,
        reason_code="source_closure_invalid",
        failure_detail="the historical replay implementation closure is invalid",
        failure_fingerprint="b" * 64,
        remediation_kind=REPLACEMENT_REQUIRED,
    )


def _record_preflight(
    case: _PartialReplayCase,
    *,
    request: ReplayJobImplementationPreflightRequest,
    accepted: bool,
    operation_id: str,
):
    expected = _preflight_result(request, accepted=accepted)

    def evaluate(
        active_request: ReplayJobImplementationPreflightRequest,
        **_kwargs: object,
    ) -> ReplayJobImplementationPreflightResult:
        assert active_request == request
        return expected

    with (
        patch(
            "axiom_rift.operations.replay_job_implementation_preflight."
            "evaluate_replay_job_implementation_preflight",
            side_effect=evaluate,
        ),
        patch.object(
            case.fixture.writer,
            "_preflight_scientific_binding",
            return_value=None,
        ),
    ):
        return case.fixture.writer.record_replay_job_implementation_preflight(
            request=request,
            operation_id=operation_id,
        )


def _head(case: _PartialReplayCase) -> IndexRecord:
    with LocalIndex(case.fixture.writer.index_path) as index:
        pairs = obligation_heads(index, mission_id=recert.MISSION_ID)
    assert len(pairs) == 1
    return pairs[0][1]


def _trial_delta(writer: StateWriter) -> int:
    with LocalIndex(writer.index_path) as index:
        return sum(
            int(record.payload.get("result", {}).get("trial_delta", 0))
            for record in index.records_by_kind("operation")
        )


def _advance_to_diagnosis(
    case: _PartialReplayCase,
    *,
    prefix_count: int,
    tag: str,
) -> _DiagnosedPartialReplay:
    for ordinal in range(prefix_count):
        _register_legacy_member(case, ordinal)
    assert _head(case).status == (
        "in_progress" if case.target_ordinal < prefix_count else "pending"
    )
    recert._activate_protocol(case.fixture)
    request = case.request
    rejected = _record_preflight(
        case,
        request=request,
        accepted=False,
        operation_id=f"partial-terminal-{tag}-reject-preflight",
    )
    assert rejected.result["status"] == "rejected"
    trial_delta = _trial_delta(case.fixture.writer)

    # Once the rejection is durable, no further family member may be counted.
    next_ordinal = prefix_count
    if next_ordinal < len(case.fixture.members):
        before = case.fixture.writer.read_control()
        with pytest.raises(
            RecoveryRequired,
            match="requires a current implementation admission",
        ):
            case.fixture.writer.register_trial(
                executable=case.fixture.members[next_ordinal],
                operation_id=f"partial-terminal-{tag}-reject-post-preflight-trial",
            )
        assert case.fixture.writer.read_control() == before
        assert _trial_delta(case.fixture.writer) == trial_delta

    case.fixture.writer.dispose_batch(
        outcome="not_evaluable",
        operation_id=f"partial-terminal-{tag}-dispose-batch",
    )
    closed = case.fixture.writer.close_study(
        outcome="not_evaluable",
        operation_id=f"partial-terminal-{tag}-close-study",
    )
    control = case.fixture.writer.read_control()
    assert control is not None
    study_close_id = control["next_action"]["study_close_record_id"]
    assert closed.result["outcome"] == "not_evaluable"
    diagnosis = StudyDiagnosis(
        study_id=recert.STUDY_ID,
        study_close_record_id=study_close_id,
        evidence_state=EvidenceState.ENGINEERING_GAP,
        confidence=DiagnosisConfidence.HIGH,
        rationale="the exact pre-Job implementation rejection is engineering only",
        counterfactual="an accepted replacement would permit a fresh bounded replay",
        reopen_condition="resume only after the exact replacement family is accepted",
    )
    diagnosed = case.fixture.writer.record_study_diagnosis(
        diagnosis=diagnosis,
        operation_id=f"partial-terminal-{tag}-diagnose-study",
    )
    assert diagnosed.result["study_diagnosis_id"] == diagnosis.identity
    return _DiagnosedPartialReplay(
        case=case,
        preflight_id=rejected.result["preflight_id"],
        study_close_id=study_close_id,
        diagnosis_id=diagnosis.identity,
        trial_delta=trial_delta,
    )


def _deferral(
    state: _DiagnosedPartialReplay,
    *,
    reason_codes: tuple[str, ...] = (_REJECTION_REASON,),
    subject_id: str = recert.STUDY_ID,
    historical_reference_ids: tuple[str, ...] | None = None,
) -> tuple[ReplayDeferral, ReplayResumeCondition]:
    case = state.case
    condition = ReplayResumeCondition(
        kind=ReplayResumeConditionKind.REPLACEMENT_PROSPECTIVE_IMPLEMENTATION,
        protocol_id=recert.PROTOCOL_ID,
        original_executable_ids=(
            case.historical_reference_ids
            if historical_reference_ids is None
            else historical_reference_ids
        ),
        criterion_ids=case.obligation.criterion_ids,
    )
    execution = (
        None
        if _head(case).status == "pending"
        else ReplayDeferralExecutionBinding(
            portfolio_decision_id="decision:" + "2" * 64,
            replay_study_id=recert.STUDY_ID,
            replay_executable_id=case.target_member.identity,
            replay_study_close_record_id=state.study_close_id,
            study_diagnosis_id=state.diagnosis_id,
        )
    )
    return (
        ReplayDeferral(
            obligation_id=case.obligation.identity,
            basis=ReplayDeferralBasis(
                kind=ReplayDeferralBasisKind.STUDY_DIAGNOSIS,
                record_id=state.diagnosis_id,
                subject_id=subject_id,
            ),
            reason_codes=reason_codes,
            resume_conditions=(condition,),
            execution_binding=execution,
        ),
        condition,
    )


def _replacement_request(
    state: _DiagnosedPartialReplay,
    *,
    cross_family: bool = False,
    replacement_for_preflight_id: str | None = None,
) -> ReplayJobImplementationPreflightRequest:
    case = state.case
    members = tuple(
        _replacement_member(member, ordinal)
        for ordinal, member in enumerate(case.fixture.members, start=1)
    )
    if cross_family:
        attacked = members[-1]
        owner = attacked.components[-1]
        changed_owner = ComponentSpec(
            display_name=owner.display_name,
            protocol=owner.protocol,
            implementation=owner.implementation,
            spec=owner.specification(),
            semantic_dependencies=owner.semantic_dependencies,
        )
        members = (
            *members[:-1],
            ExecutableSpec(
                display_name=attacked.display_name,
                components=(*attacked.components[:-1], changed_owner),
                parameters={
                    **attacked.parameter_values(),
                    "historical_reference_executable_id": (
                        "executable:" + "9" * 64
                    ),
                },
                data_contract=attacked.data_contract,
                split_contract=attacked.split_contract,
                clock_contract=attacked.clock_contract,
                cost_contract=attacked.cost_contract,
                engine_contract=attacked.engine_contract,
                source_contracts=attacked.source_contracts,
            ),
        )
    return _request(
        case,
        executables=members,
        implementation_identity="9" * 64,
        protocol_id="python.tests.partial_replay_replacement.v2",
        callable_identity="python:tests.partial_replay_replacement",
        replacement_for_preflight_id=(
            state.preflight_id
            if replacement_for_preflight_id is None
            else replacement_for_preflight_id
        ),
    )


@pytest.mark.parametrize(
    ("target_ordinal", "prefix_count", "expected_prior_status"),
    (
        (3, 2, "pending"),
        (0, 2, "in_progress"),
    ),
)
def test_partial_replay_terminal_replacement_resume_is_exact_and_idempotent(
    tmp_path: Path,
    target_ordinal: int,
    prefix_count: int,
    expected_prior_status: str,
) -> None:
    case = _build_case(tmp_path, target_ordinal=target_ordinal)
    tag = expected_prior_status.replace("_", "-")
    with _compact_scientific_surface_boundary():
        state = _advance_to_diagnosis(
            case,
            prefix_count=prefix_count,
            tag=tag,
        )
        assert _head(case).status == expected_prior_status

        # A generic reason, a cross-Study basis, or a truncated historical
        # family must not manufacture a resumable engineering terminal.
        wrong_reason, _ = _deferral(
            state,
            reason_codes=("implementation_invalid",),
        )
        with pytest.raises(TransitionError):
            case.fixture.writer.defer_historical_replay_obligations(
                deferrals=(wrong_reason,),
                operation_id=f"partial-terminal-{tag}-wrong-reason",
            )
        cross_study, _ = _deferral(
            state,
            subject_id="STU-ANOTHER-PARTIAL-REPLAY",
        )
        with pytest.raises(TransitionError):
            case.fixture.writer.defer_historical_replay_obligations(
                deferrals=(cross_study,),
                operation_id=f"partial-terminal-{tag}-cross-study",
            )
        omitted_reference = next(
            value
            for value in case.historical_reference_ids
            if value != case.obligation.original_executable_id
        )
        truncated_family, _ = _deferral(
            state,
            historical_reference_ids=tuple(
                value
                for value in case.historical_reference_ids
                if value != omitted_reference
            ),
        )
        with pytest.raises(TransitionError):
            case.fixture.writer.defer_historical_replay_obligations(
                deferrals=(truncated_family,),
                operation_id=f"partial-terminal-{tag}-truncated-family",
            )

        deferral, condition = _deferral(state)
        deferred = case.fixture.writer.defer_historical_replay_obligations(
            deferrals=(deferral,),
            operation_id=f"partial-terminal-{tag}-defer",
        )
        assert deferred.result["deferred_replay_obligation_ids"] == [
            case.obligation.identity
        ]
        assert _head(case).status == "deferred"
        assert _trial_delta(case.fixture.writer) == state.trial_delta
        with LocalIndex(case.fixture.writer.index_path) as index:
            stored_deferral = index.get(
                "historical-replay-obligation-resolution",
                deferral.identity,
            )
        assert stored_deferral is not None
        stored_resolution = stored_deferral.payload["resolution"]
        assert stored_resolution["reason_codes"] == [_REJECTION_REASON]
        assert stored_resolution["resume_conditions"][0][
            "original_executable_ids"
        ] == sorted(case.historical_reference_ids)
        assert set(case.historical_reference_ids).isdisjoint(
            case.request.executable_ids
        )

        # Replacement authority must name this exact rejection and preserve
        # the historical-reference family even though all prospective
        # Executable identities are genuinely new.
        stale_request = _replacement_request(
            state,
            replacement_for_preflight_id=(
                "job-implementation-preflight:" + "0" * 64
            ),
        )
        with pytest.raises(TransitionError):
            _record_preflight(
                case,
                request=stale_request,
                accepted=True,
                operation_id=f"partial-terminal-{tag}-stale-replacement",
            )
        cross_family_request = _replacement_request(state, cross_family=True)
        with pytest.raises(TransitionError):
            _record_preflight(
                case,
                request=cross_family_request,
                accepted=True,
                operation_id=f"partial-terminal-{tag}-cross-family",
            )

        replacement_request = _replacement_request(state)
        accepted = _record_preflight(
            case,
            request=replacement_request,
            accepted=True,
            operation_id=f"partial-terminal-{tag}-accept-replacement",
        )
        trigger_id = accepted.result["preflight_id"]
        assert accepted.result["status"] == "accepted"
        assert set(replacement_request.executable_ids).isdisjoint(
            case.request.executable_ids
        )
        assert replay_executable_reference_map(
            replacement_request.executables
        ).keys() == replay_executable_reference_map(case.request.executables).keys()

        with pytest.raises(TransitionError):
            _record_preflight(
                case,
                request=replacement_request,
                accepted=True,
                operation_id=f"partial-terminal-{tag}-duplicate-replacement",
            )

        stale_resume = ReplayResumeEvidence(
            obligation_id=case.obligation.identity,
            deferral_id=deferral.identity,
            resume_condition_id=condition.identity,
            trigger_record_id="job-implementation-preflight:" + "8" * 64,
        )
        with pytest.raises(TransitionError):
            case.fixture.writer.resume_historical_replay_obligations(
                resumes=(stale_resume,),
                operation_id=f"partial-terminal-{tag}-stale-resume",
            )

        resume = ReplayResumeEvidence(
            obligation_id=case.obligation.identity,
            deferral_id=deferral.identity,
            resume_condition_id=condition.identity,
            trigger_record_id=trigger_id,
        )
        operation_id = f"partial-terminal-{tag}-resume"
        resumed = case.fixture.writer.resume_historical_replay_obligations(
            resumes=(resume,),
            operation_id=operation_id,
        )
        assert resumed.reused is False
        assert resumed.result["scientific_claim_delta"] == 0
        assert resumed.result["scientific_satisfaction_delta"] == 0
        assert resumed.result["scientific_trial_delta"] == 0
        assert _head(case).status == "pending"
        assert _trial_delta(case.fixture.writer) == state.trial_delta

        restarted = StateWriter(
            case.fixture.writer.root,
            permit_authority=PermitAuthority(b"r" * 32),
            clock=lambda: FIXED_NOW,
            engineering_fixture=False,
            foundation_root=REPO_ROOT,
            study_close_guard_capability=FIXTURE_DELIVERY_CAPABILITY,
        )
        replayed = restarted.resume_historical_replay_obligations(
            resumes=(resume,),
            operation_id=operation_id,
        )
        assert replayed.reused is True
        assert replayed.revision == resumed.revision


def test_pending_partial_terminal_rejects_a_registration_gap_at_close(
    tmp_path: Path,
) -> None:
    case = _build_case(tmp_path, target_ordinal=3)
    with _compact_scientific_surface_boundary():
        _register_legacy_member(case, 0)
        _register_legacy_member(case, 1)
        recert._activate_protocol(case.fixture)
        rejected = _record_preflight(
            case,
            request=case.request,
            accepted=False,
            operation_id="partial-terminal-gap-reject-preflight",
        )
        case.fixture.writer.dispose_batch(
            outcome="not_evaluable",
            operation_id="partial-terminal-gap-dispose-batch",
        )
        original_event_record = LocalIndex.event_record

        def event_record(index: LocalIndex, stream: str, sequence: int):
            if (
                stream == f"batch-trials:{case.fixture.batch.identity}"
                and sequence == 1
            ):
                return None
            return original_event_record(index, stream, sequence)

        control_before = case.fixture.writer.read_control()
        journal_before = case.fixture.writer.journal.tail()[0]
        with patch.object(LocalIndex, "event_record", new=event_record):
            with pytest.raises(
                RecoveryRequired,
                match="exact frozen family prefix",
            ):
                case.fixture.writer.close_study(
                    outcome="not_evaluable",
                    operation_id="partial-terminal-gap-reject-close",
                )
        assert case.fixture.writer.read_control() == control_before
        assert case.fixture.writer.journal.tail()[0] == journal_before
        assert rejected.result["status"] == "rejected"
