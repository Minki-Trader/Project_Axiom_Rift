from __future__ import annotations

from contextlib import ExitStack, contextmanager, nullcontext
from dataclasses import dataclass, replace
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator
from unittest.mock import patch

import pytest

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.permits import (
    PermitAuthority,
    SubjectKind,
)
from axiom_rift.operations.replay_job_implementation_preflight import (
    REPLACEMENT_REQUIRED,
    ReplayJobImplementationPreflightRequest,
    ReplayJobImplementationPreflightResult,
)
from axiom_rift.operations.writer import (
    RecoveryRequired,
    StateWriter,
    TransitionError,
    _record,
)
from axiom_rift.operations.validation import EvidenceValidatorRegistry
from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.protocol import ResearchProtocol, ResearchProtocolActivation
from axiom_rift.research.semantic_question import SemanticQuestionCore
from axiom_rift.research.trials import MaterialReference, TrialAccountant
from axiom_rift.research.validation_v2 import ScientificAdjudicationValidatorV2
from axiom_rift.research.portfolio import (
    BatchSpec,
    ConcurrentFamilyEvaluationMode,
    ConcurrentFamilyManifest,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex
from tests.operations.test_writer import (
    FIXED_NOW,
    FIXTURE_DELIVERY_CAPABILITY,
    OBSERVED_MATERIAL_ID,
    REPO_ROOT,
    initiative_objective,
    mission_goal,
    record_fixture_research_intake,
    scientific_executable_spec,
    study_question,
)
from tests.operations.fixture_validators import ScientificFixtureValidator


MISSION_ID = "MIS-PARTIAL-REPLAY-RECERT"
INITIATIVE_ID = "INI-PARTIAL-REPLAY-RECERT"
STUDY_ID = "STU-PARTIAL-REPLAY-RECERT"
OBLIGATION_ID = "historical-replay-obligation:" + "a" * 64
PROTOCOL_ID = "python.tests.partial_replay_recertification.v1"
CALLABLE_IDENTITY = "python:tests.partial_replay_recertification.execute.v1"


@dataclass(frozen=True, slots=True)
class _TrialSnapshot:
    trial_ids: tuple[str, ...]
    accounting_payloads: tuple[tuple[str, str], ...]
    trial_delta: int


@dataclass(slots=True)
class _LegacyReplay:
    writer: StateWriter
    members: tuple[object, ...]
    batch: BatchSpec
    chassis: ControlledStudyChassis

    @property
    def request(self) -> ReplayJobImplementationPreflightRequest:
        return ReplayJobImplementationPreflightRequest(
            mission_id=MISSION_ID,
            protocol_id=PROTOCOL_ID,
            callable_identity=CALLABLE_IDENTITY,
            implementation_identity="f" * 64,
            executables=self.members,  # type: ignore[arg-type]
            scientific_bindings=tuple(
                {
                    "validation_plan_hash": f"{ordinal:064x}",
                    "validator_id": ScientificAdjudicationValidatorV2.validator_id,
                }
                for ordinal in range(1, len(self.members) + 1)
            ),
            replay_obligation_ids=(OBLIGATION_ID,),
        )


def _surface(request: ReplayJobImplementationPreflightRequest) -> dict[str, object]:
    return {
        "callable_identity": request.callable_identity,
        "mission_id": request.mission_id,
        "protocol_id": request.protocol_id,
        "replay_obligation_ids": list(request.replay_obligation_ids),
        "schema": "partial_replay_recertification_surface.v1",
    }


def _surface_hash(surface: object) -> str:
    return canonical_digest(
        domain="partial-replay-recertification-surface",
        payload=surface,
    )


def _accepted_result(
    request: ReplayJobImplementationPreflightRequest,
) -> ReplayJobImplementationPreflightResult:
    return ReplayJobImplementationPreflightResult(
        request=request,
        accepted=True,
        artifact_hashes=("e" * 64,),
        source_closure_authority={
            "callable_module_path": (
                "axiom_rift/research/partial_replay_recertification.py"
            ),
            "dependency_count": 1,
            "path_inventory_hash": "d" * 64,
            "schema": "job_implementation_source_authority.v1",
            "source_closure_hash": "c" * 64,
        },
    )


def _build_legacy_replay(tmp_path: Path) -> _LegacyReplay:
    writer = StateWriter(
        tmp_path / "writer",
        permit_authority=PermitAuthority(b"r" * 32),
        clock=lambda: FIXED_NOW,
        engineering_fixture=False,
        foundation_root=REPO_ROOT,
        study_close_guard_capability=FIXTURE_DELIVERY_CAPABILITY,
    )
    writer.initialize_ready()
    writer.open_mission(
        mission_id=MISSION_ID,
        goal=mission_goal("partial replay recertification"),
        operation_id="partial-recert-open-mission",
    )
    record_fixture_research_intake(
        writer,
        mission_id=MISSION_ID,
        operation_id="partial-recert-record-intake",
    )
    writer.open_initiative(
        initiative_id=INITIATIVE_ID,
        objective=initiative_objective("partial replay recertification"),
        operation_id="partial-recert-open-initiative",
    )
    members = tuple(
        scientific_executable_spec(f"partial-recert-member-{ordinal}")
        for ordinal in range(1, 5)
    )
    changed_domains = (
        ResearchLayer.CALIBRATION,
        ResearchLayer.EXECUTION,
        ResearchLayer.FEATURE,
        ResearchLayer.LABEL,
        ResearchLayer.LIFECYCLE,
        ResearchLayer.MODEL,
        ResearchLayer.RISK,
        ResearchLayer.SELECTOR,
        ResearchLayer.TRADE,
    )
    chassis = ControlledStudyChassis(
        baseline_executable=members[0],
        changed_domains=changed_domains,
        controlled_domains=(ResearchLayer.SYNTHESIS,),
        architecture=ArchitectureChassisSpec.from_executable(members[0]),
    )
    question = study_question("partial replay recertification")
    proposal = {"mechanism": "legacy replay exact prefix recertification"}
    study_hash = writer.study_input_hash(
        question=question,
        material_identity=OBSERVED_MATERIAL_ID,
        semantic_proposal=proposal,
        controlled_chassis=chassis,
    )
    family = ConcurrentFamilyManifest(
        evaluation_mode=ConcurrentFamilyEvaluationMode.VECTORIZED,
        executable_ids=tuple(member.identity for member in members),
    )
    batch = BatchSpec(
        batch_id="BAT-PARTIAL-REPLAY-RECERT",
        study_id=STUDY_ID,
        study_hash=study_hash,
        display_name="legacy partial replay concurrent family",
        max_trials=len(members),
        max_compute_seconds=60,
        max_wall_seconds=90,
        stop_rule="stop after the exact registered family",
        concurrent_family=family,
        acceptance_profile={
            "causality": "required",
            "unknown_cost": "reject",
        },
        adaptive_basis={
            "causal_complexity": "bounded fixture",
            "compute_cost": "bounded",
            "expected_information_value": "positive",
            "portfolio_opportunity_cost": "one exact recertification",
            "surface_curvature": "unknown",
            "uncertainty": "legacy partial prefix",
        },
    )
    trial_context = TrialAccountant.from_foundation(REPO_ROOT).open_study(
        material=MaterialReference(
            identity=OBSERVED_MATERIAL_ID,
            display_name="foundation observed development material",
        ),
        semantic_proposal=proposal,
    )
    question_payload = dict(question)
    semantic_core = SemanticQuestionCore.from_question_manifest(question_payload)
    portfolio_axis_id = "partial-recert-axis"
    portfolio_axis_identity = "axis:" + "1" * 64
    portfolio_decision_id = "decision:" + "2" * 64
    portfolio_snapshot_id = "portfolio:" + "3" * 64
    architecture_family = "architecture-family:" + "4" * 64
    changed_domain_values = [domain.value for domain in changed_domains]
    controlled_domain_values = [ResearchLayer.SYNTHESIS.value]

    # There is intentionally no public API that can create a new replay Study
    # without an admission.  Seed the exact historical shape through one real
    # Writer commit: it is a pre-activation legacy state, while every tested
    # rebind, recertification, trial, accounting, and rejection uses the current
    # public Writer against the durable Journal and SQLite projection.
    def prepare_legacy(current: dict[str, object] | None, _index: LocalIndex):
        assert current is not None
        body = writer._body(current)  # type: ignore[arg-type]
        science = body["scientific"]
        science["active_study"] = STUDY_ID
        science["active_batch"] = {
            "hash": batch.identity.removeprefix("batch:"),
            "id": batch.identity,
            "status": "open",
        }
        body["next_action"] = {"kind": "declare_job", "batch_id": batch.identity}
        writer._bind_authorization(
            body,
            writer._authorization(
                kind=SubjectKind.STUDY,
                subject_id=STUDY_ID,
                semantic_hash=study_hash,
            ),
        )
        study_record = _record(
            kind="study-open",
            record_id=STUDY_ID,
            subject=f"Study:{STUDY_ID}",
            status="open",
            fingerprint=study_hash,
            payload={
                "changed_domains": changed_domain_values,
                "commitment_batches": 1,
                "controlled_chassis": chassis.to_identity_payload(),
                "controlled_chassis_identity": chassis.controlled_chassis_identity,
                "controlled_domains": controlled_domain_values,
                "material_identity": trial_context.material_identity,
                "mechanism_family": "legacy replay exact prefix recertification",
                "mission_id": MISSION_ID,
                "portfolio_action": "synthesize",
                "portfolio_architecture_family": architecture_family,
                "portfolio_axis_id": portfolio_axis_id,
                "portfolio_axis_identity": portfolio_axis_identity,
                "portfolio_decision_id": portfolio_decision_id,
                "portfolio_snapshot_id": portfolio_snapshot_id,
                "primary_research_layer": ResearchLayer.SYNTHESIS.value,
                "prior_global_multiplicity": trial_context.prior_global_multiplicity,
                "prior_material_trial_count": 0,
                "question": question_payload,
                "question_hash": canonical_digest(
                    domain="study-question", payload=question_payload
                ),
                "replay_obligation_ids": [OBLIGATION_ID],
                "semantic_proposal": proposal,
                "semantic_question_core_id": semantic_core.identity,
                "semantic_question_equivalence": None,
                "semantic_question_equivalence_id": None,
                "semantic_question_lineage": None,
                "semantic_question_lineage_id": None,
                "semantic_warning_ids": [
                    warning.warning_id for warning in trial_context.semantic_warnings
                ],
                "system_architecture_family": architecture_family,
                "warning_scheduler_weight": trial_context.warning_scheduler_weight,
            },
        )
        batch_record = _record(
            kind="batch-open",
            record_id=batch.identity,
            subject=f"Study:{STUDY_ID}",
            status="open",
            fingerprint=batch.identity.removeprefix("batch:"),
            payload={
                "batch_hash": batch.identity.removeprefix("batch:"),
                "display_id": batch.batch_id,
                "display_name": batch.display_name,
                "source_permit_ids": [],
                "spec": batch.to_identity_payload(),
            },
            event_stream=f"study-batches:{STUDY_ID}",
            event_sequence=1,
        )
        return body, [study_record, batch_record], {
            "batch_id": batch.identity,
            "legacy_replay": True,
            "study_id": STUDY_ID,
            "trial_delta": 0,
        }

    writer._commit(
        event_kind="legacy_partial_replay_fixture_seeded",
        operation_id="partial-recert-seed-legacy-study",
        subject=f"Study:{STUDY_ID}",
        payload={"batch_id": batch.identity, "study_id": STUDY_ID},
        prepare=prepare_legacy,
    )
    return _LegacyReplay(
        writer=writer,
        members=members,
        batch=batch,
        chassis=chassis,
    )


@contextmanager
def _legacy_replay_surface(
    fixture: _LegacyReplay,
    *,
    accepted: bool,
) -> Iterator[None]:
    request = fixture.request

    def evaluate(
        active_request: ReplayJobImplementationPreflightRequest,
        **_kwargs: object,
    ) -> ReplayJobImplementationPreflightResult:
        assert active_request == request
        assert accepted is True
        return _accepted_result(active_request)

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "axiom_rift.operations.replay_projection.obligation_heads",
                return_value=(
                    (
                        SimpleNamespace(identity=OBLIGATION_ID),
                        SimpleNamespace(
                            status="pending",
                            event_stream=None,
                            event_sequence=1,
                        ),
                    ),
                ),
            )
        )
        stack.enter_context(
            patch(
                "axiom_rift.operations.replay_projection.prepare_execution_progress",
                return_value=((OBLIGATION_ID,), []),
            )
        )
        stack.enter_context(
            patch(
                "axiom_rift.operations.replay_job_implementation_preflight."
                "derive_replay_job_scientific_surface",
                side_effect=lambda active_request, **_kwargs: _surface(
                    active_request
                ),
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
                "evaluate_replay_job_implementation_preflight",
                side_effect=evaluate,
            )
        )
        stack.enter_context(
            patch.object(
                fixture.writer,
                "_preflight_scientific_binding",
                return_value=None,
            )
        )
        stack.enter_context(
            patch.object(
                fixture.writer,
                "_require_replay_registration_source_authority",
                return_value=None,
            )
        )
        yield


def _activate_protocol(
    fixture: _LegacyReplay,
    *,
    historical_validator: bool = False,
):
    audit = fixture.writer.evidence.finalize(
        (
            b"historical partial replay protocol activation"
            if historical_validator
            else b"current partial replay protocol activation"
        )
    )
    validators = (
        ScientificAdjudicationValidatorV2(),
        ScientificFixtureValidator(),
    )
    fixture.writer.validation_registry = EvidenceValidatorRegistry(validators)
    control = fixture.writer.read_control()
    assert control is not None
    validator_id = (
        ScientificFixtureValidator.validator_id
        if historical_validator
        else ScientificAdjudicationValidatorV2.validator_id
    )
    activation = ResearchProtocolActivation(
        protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
        validator_id=validator_id,
        authority_manifest_digest=control["authority"]["manifest_digest"],
        audit_artifact_hash=audit.sha256,
    )
    context = (
        patch(
            "axiom_rift.research.validation_v2."
            "SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID",
            ScientificFixtureValidator.validator_id,
        )
        if historical_validator
        else nullcontext()
    )
    with context:
        return fixture.writer.activate_research_protocol(
            activation=activation,
            operation_id=(
                "partial-recert-activate-historical-protocol"
                if historical_validator
                else "partial-recert-activate-current-protocol"
            ),
            allow_active_unexecuted_study_boundary=True,
        )


def _register(
    fixture: _LegacyReplay,
    ordinal: int,
    *,
    replay: bool,
) -> object:
    contexts = ExitStack()
    if replay:
        contexts.enter_context(
            _legacy_replay_surface(fixture, accepted=True)
        )
    else:
        legacy_admission = SimpleNamespace(
            payload={
                "request": {
                    "executable_manifests": [
                        member.to_identity_payload() for member in fixture.members
                    ]
                }
            }
        )
        contexts.enter_context(
            patch.object(
                fixture.writer,
                "_study_replay_implementation_admission",
                return_value=legacy_admission,
            )
        )
        contexts.enter_context(
            patch.object(
                fixture.writer,
                "_require_replay_registration_source_authority",
                return_value=None,
            )
        )
        contexts.enter_context(
            patch(
                "axiom_rift.operations.replay_projection.prepare_execution_progress",
                return_value=((OBLIGATION_ID,), []),
            )
        )
    contexts.enter_context(
        patch(
            "axiom_rift.research.chassis.validate_controlled_executable",
            return_value=None,
        )
    )
    with contexts:
        return fixture.writer.register_trial(
            executable=fixture.members[ordinal],
            operation_id=f"partial-recert-register-{ordinal + 1}",
        )


def _trial_snapshot(writer: StateWriter) -> _TrialSnapshot:
    with LocalIndex(writer.index_path) as index:
        trials = sorted(
            index.records_by_kind("trial"),
            key=lambda record: record.event_sequence or 0,
        )
        accounting = index.records_by_kind("trial-accounting")
        operations = index.records_by_kind("operation")
    return _TrialSnapshot(
        trial_ids=tuple(record.record_id for record in trials),
        accounting_payloads=tuple(
            sorted(
                (
                    record.record_id,
                    json.dumps(
                        record.payload,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
                for record in accounting
            )
        ),
        trial_delta=sum(
            int(record.payload.get("result", {}).get("trial_delta", 0))
            for record in operations
        ),
    )


def _record_accepted_preflight(fixture: _LegacyReplay, tag: str):
    with _legacy_replay_surface(fixture, accepted=True):
        return fixture.writer.record_replay_job_implementation_preflight(
            request=fixture.request,
            operation_id=f"partial-recert-{tag}-preflight",
        )


@pytest.mark.parametrize("prefix_count", (0, 1, 2, 3))
def test_accepted_recertification_counts_only_missing_trials(
    tmp_path: Path,
    prefix_count: int,
) -> None:
    fixture = _build_legacy_replay(tmp_path)
    prefix_results = tuple(
        _register(fixture, ordinal, replay=False)
        for ordinal in range(prefix_count)
    )
    before = _trial_snapshot(fixture.writer)
    activated = _activate_protocol(fixture)

    preflight = _record_accepted_preflight(fixture, f"prefix-{prefix_count}")
    after_preflight = _trial_snapshot(fixture.writer)

    assert preflight.result["status"] == "accepted"
    assert preflight.result["admission_id"].startswith(
        "replay-implementation-admission:"
    )
    assert after_preflight == before
    with LocalIndex(fixture.writer.index_path) as index:
        admission = index.get(
            "replay-implementation-admission",
            preflight.result["admission_id"],
        )
        preflight_record = index.get(
            "job-implementation-preflight",
            preflight.result["preflight_id"],
        )
        study_before_activation = index.get("study-open", STUDY_ID)
        activation_record = index.get(
            "research-protocol-activation",
            activated.result["activation_record_id"],
        )
    assert admission is not None
    assert preflight_record is not None
    assert study_before_activation is not None
    assert activation_record is not None
    assert (
        study_before_activation.authority_sequence
        < activation_record.authority_sequence
        < admission.authority_sequence
    )
    assert admission.payload["schema"] == "replay_implementation_admission.v2"
    assert admission.payload["research_protocol_activation_id"] == (
        activated.result["activation_record_id"]
    )
    control = fixture.writer.read_control()
    assert control is not None
    assert admission.payload["authority_manifest_digest"] == (
        control["authority"]["manifest_digest"]
    )
    assert admission.payload["registered_prefix_executable_ids"] == [
        fixture.members[ordinal].identity
        for ordinal in range(prefix_count)
    ]
    assert preflight_record.authority_sequence == admission.authority_sequence
    if prefix_results:
        assert prefix_results[-1].revision < preflight.revision

    remaining_results = tuple(
        _register(fixture, ordinal, replay=True)
        for ordinal in range(prefix_count, len(fixture.members))
    )
    final = _trial_snapshot(fixture.writer)
    assert final.trial_ids == tuple(member.identity for member in fixture.members)
    assert final.trial_delta - before.trial_delta == len(
        fixture.members
    ) - prefix_count
    assert set(before.accounting_payloads).issubset(
        set(final.accounting_payloads)
    )
    if remaining_results:
        assert preflight.revision < remaining_results[0].revision

    with LocalIndex(fixture.writer.index_path) as index:
        study = index.get("study-open", STUDY_ID)
        accounting = {
            record.payload["executable_id"]: record
            for record in index.records_by_kind("trial-accounting")
        }
    assert study is not None
    expected_global = [
        study.payload["prior_global_multiplicity"]
        + ordinal
        - study.payload["prior_material_trial_count"]
        for ordinal in range(1, len(fixture.members) + 1)
    ]
    assert [
        accounting[member.identity].payload["global_multiplicity"]
        for member in fixture.members
    ] == expected_global
    assert len(accounting) == len(fixture.members)


@pytest.mark.parametrize("attack", ("missing", "malformed"))
def test_recertification_fails_closed_on_invalid_trial_accounting(
    tmp_path: Path,
    attack: str,
) -> None:
    fixture = _build_legacy_replay(tmp_path)
    _register(fixture, 0, replay=False)
    _activate_protocol(fixture)
    with LocalIndex(fixture.writer.index_path) as index:
        accounting = index.records_by_kind("trial-accounting")
    assert len(accounting) == 1
    target = accounting[0]
    original_get = LocalIndex.get

    def get(index: LocalIndex, kind: str, record_id: str):
        record = original_get(index, kind, record_id)
        if kind == "trial-accounting" and record_id == target.record_id:
            if attack == "missing":
                return None
            assert record is not None
            return replace(
                record,
                payload={**record.payload, "global_multiplicity": 0},
            )
        return record

    control_before = fixture.writer.read_control()
    journal_before = fixture.writer.journal.tail()[0]

    with (
        _legacy_replay_surface(fixture, accepted=True),
        patch.object(LocalIndex, "get", new=get),
    ):
        with pytest.raises(
            RecoveryRequired,
            match="replay trial stream is not the exact frozen family prefix",
        ):
            fixture.writer.record_replay_job_implementation_preflight(
                request=fixture.request,
                operation_id=f"reject-partial-recert-{attack}-accounting",
            )

    assert fixture.writer.read_control() == control_before
    assert fixture.writer.journal.tail()[0] == journal_before


@pytest.mark.parametrize(
    "attack",
    ("gap", "out_of_order", "tamper", "canonical", "lineage"),
)
def test_recertification_rejects_prefix_order_and_integrity_attacks(
    tmp_path: Path,
    attack: str,
) -> None:
    fixture = _build_legacy_replay(tmp_path)
    attack_context = nullcontext()
    if attack == "out_of_order":
        _activate_protocol(fixture)
        _register(fixture, 1, replay=False)
    else:
        _register(fixture, 0, replay=False)
        original_event_record = LocalIndex.event_record
        if attack == "gap":
            _register(fixture, 1, replay=False)
            _activate_protocol(fixture)

            def event_record(index: LocalIndex, stream: str, sequence: int):
                if stream == f"batch-trials:{fixture.batch.identity}" and sequence == 1:
                    return None
                return original_event_record(index, stream, sequence)

            attack_context = patch.object(
                LocalIndex,
                "event_record",
                new=event_record,
            )
        else:
            _activate_protocol(fixture)

            def event_record(index: LocalIndex, stream: str, sequence: int):
                record = original_event_record(index, stream, sequence)
                if stream == f"batch-trials:{fixture.batch.identity}" and sequence == 1:
                    assert record is not None
                    payload = dict(record.payload)
                    if attack == "canonical":
                        executable = dict(payload["executable"])
                        executable["parameters"] = {
                            **executable["parameters"],
                            "forged_parameter": True,
                        }
                        payload["executable"] = executable
                    elif attack == "lineage":
                        payload["portfolio_axis_identity"] = "axis:" + "0" * 64
                    else:
                        payload["trial_delta"] = 0
                    return replace(
                        record,
                        payload=payload,
                    )
                return record

            attack_context = patch.object(
                LocalIndex,
                "event_record",
                new=event_record,
            )

    with _legacy_replay_surface(fixture, accepted=True), attack_context:
        with pytest.raises(
            RecoveryRequired,
            match="replay trial stream is not the exact frozen family prefix",
        ):
            fixture.writer.record_replay_job_implementation_preflight(
                request=fixture.request,
                operation_id=f"reject-partial-recert-{attack}",
            )


def test_missing_protocol_requires_additive_rebind_without_terminal_disposal(
    tmp_path: Path,
) -> None:
    fixture = _build_legacy_replay(tmp_path)
    before = _trial_snapshot(fixture.writer)
    control_before = fixture.writer.read_control()
    journal_before = fixture.writer.journal.tail()[0]

    with _legacy_replay_surface(fixture, accepted=True):
        with pytest.raises(
            TransitionError,
            match="prospective protocol rebind before recertification",
        ):
            fixture.writer.record_replay_job_implementation_preflight(
                request=fixture.request,
                operation_id="partial-recert-missing-protocol-preflight",
            )

    assert _trial_snapshot(fixture.writer) == before
    assert fixture.writer.read_control() == control_before
    assert fixture.writer.journal.tail()[0] == journal_before

    rebound = _activate_protocol(fixture)
    accepted = _record_accepted_preflight(fixture, "after-missing-protocol-rebind")
    assert accepted.result["status"] == "accepted"
    assert _trial_snapshot(fixture.writer) == before
    with LocalIndex(fixture.writer.index_path) as index:
        admission = index.get(
            "replay-implementation-admission",
            accepted.result["admission_id"],
        )
    assert admission is not None
    assert admission.payload["research_protocol_activation_id"] == (
        rebound.result["activation_record_id"]
    )


def test_stale_validator_rebind_supersedes_without_refund_or_disposal(
    tmp_path: Path,
) -> None:
    fixture = _build_legacy_replay(tmp_path)
    _register(fixture, 0, replay=False)
    before = _trial_snapshot(fixture.writer)
    historical = _activate_protocol(fixture, historical_validator=True)
    control_before = fixture.writer.read_control()
    assert control_before is not None

    with _legacy_replay_surface(fixture, accepted=True):
        with pytest.raises(
            TransitionError,
            match="prospective protocol rebind before recertification",
        ):
            fixture.writer.record_replay_job_implementation_preflight(
                request=fixture.request,
                operation_id="partial-recert-stale-validator-preflight",
            )
    assert fixture.writer.read_control() == control_before
    assert _trial_snapshot(fixture.writer) == before

    rebound = _activate_protocol(fixture)
    assert rebound.result["ordinal"] == historical.result["ordinal"] + 1
    assert rebound.result["trial_delta"] == 0
    after_rebind = _trial_snapshot(fixture.writer)
    assert after_rebind == before
    accepted = _record_accepted_preflight(fixture, "after-stale-validator-rebind")
    assert accepted.result["status"] == "accepted"
    assert _trial_snapshot(fixture.writer) == before


@pytest.mark.parametrize("attack", ("payload", "cross_event"))
def test_recertified_admission_tamper_blocks_the_next_trial(
    tmp_path: Path,
    attack: str,
) -> None:
    fixture = _build_legacy_replay(tmp_path)
    _activate_protocol(fixture)
    preflight = _record_accepted_preflight(fixture, "tamper-admission")
    admission_id = preflight.result["admission_id"]
    original_get = LocalIndex.get

    def get(index: LocalIndex, kind: str, record_id: str):
        record = original_get(index, kind, record_id)
        if kind == "replay-implementation-admission" and record_id == admission_id:
            assert record is not None
            if attack == "cross_event":
                return replace(record, authority_event_id="0" * 64)
            return replace(
                record,
                payload={
                    **record.payload,
                    "registered_prefix_executable_ids": [
                        fixture.members[1].identity
                    ],
                },
            )
        return record

    before = _trial_snapshot(fixture.writer)
    with (
        _legacy_replay_surface(fixture, accepted=True),
        patch.object(LocalIndex, "get", new=get),
    ):
        with pytest.raises(
            RecoveryRequired,
            match="Study replay implementation admission is malformed",
        ):
            fixture.writer.register_trial(
                executable=fixture.members[0],
                operation_id="reject-tampered-recertified-admission",
            )
    assert _trial_snapshot(fixture.writer) == before


@pytest.mark.parametrize(
    "attack",
    ("missing_operation", "tampered_result", "missing_journal"),
)
def test_recertification_rejects_trial_operation_witness_attacks(
    tmp_path: Path,
    attack: str,
) -> None:
    fixture = _build_legacy_replay(tmp_path)
    _register(fixture, 0, replay=False)
    _activate_protocol(fixture)
    with LocalIndex(fixture.writer.index_path) as index:
        trial = index.get("trial", fixture.members[0].identity)
    assert trial is not None
    assert isinstance(trial.authority_sequence, int)
    assert isinstance(trial.authority_event_id, str)
    original_at_sequence = LocalIndex.records_by_kind_at_authority_sequence
    original_get = LocalIndex.get

    def records_at_sequence(
        index: LocalIndex,
        kind: str,
        authority_sequence: int,
    ):
        records = original_at_sequence(index, kind, authority_sequence)
        if kind != "operation" or authority_sequence != trial.authority_sequence:
            return records
        if attack == "missing_operation":
            return ()
        if attack == "tampered_result":
            assert len(records) == 1
            operation = records[0]
            result = dict(operation.payload["result"])
            result["global_multiplicity"] += 1
            return (
                replace(
                    operation,
                    payload={**operation.payload, "result": result},
                ),
            )
        return records

    def get(index: LocalIndex, kind: str, record_id: str):
        if (
            attack == "missing_journal"
            and kind == "journal-event"
            and record_id == trial.authority_event_id
        ):
            return None
        return original_get(index, kind, record_id)

    with (
        _legacy_replay_surface(fixture, accepted=True),
        patch.object(
            LocalIndex,
            "records_by_kind_at_authority_sequence",
            new=records_at_sequence,
        ),
        patch.object(LocalIndex, "get", new=get),
    ):
        with pytest.raises(
            RecoveryRequired,
            match="replay trial stream is not the exact frozen family prefix",
        ):
            fixture.writer.record_replay_job_implementation_preflight(
                request=fixture.request,
                operation_id=f"reject-partial-recert-{attack}",
            )


def test_post_activation_study_cannot_claim_legacy_recertification(
    tmp_path: Path,
) -> None:
    fixture = _build_legacy_replay(tmp_path)
    activated = _activate_protocol(fixture)
    with LocalIndex(fixture.writer.index_path) as index:
        activation = index.get(
            "research-protocol-activation",
            activated.result["activation_record_id"],
        )
    assert activation is not None
    assert isinstance(activation.authority_sequence, int)
    original_get = LocalIndex.get

    def get(index: LocalIndex, kind: str, record_id: str):
        record = original_get(index, kind, record_id)
        if kind == "study-open" and record_id == STUDY_ID:
            assert record is not None
            return replace(
                record,
                authority_sequence=activation.authority_sequence + 1,
            )
        return record

    before = fixture.writer.journal.tail()[0]
    with (
        _legacy_replay_surface(fixture, accepted=True),
        patch.object(LocalIndex, "get", new=get),
    ):
        with pytest.raises(
            RecoveryRequired,
            match="legacy pre-activation recertification boundary",
        ):
            fixture.writer.record_replay_job_implementation_preflight(
                request=fixture.request,
                operation_id="reject-post-activation-missing-admission",
            )
    assert fixture.writer.journal.tail()[0] == before


def test_active_preflight_cannot_cross_a_job_operation_gap(
    tmp_path: Path,
) -> None:
    fixture = _build_legacy_replay(tmp_path)
    _activate_protocol(fixture)
    # A declaration after an unadmitted legacy Batch is an operation gap: the
    # durable preflight can no longer be inserted retroactively.  The test
    # patches only the declaration lookup, while the rejection itself crosses
    # the real Writer transaction boundary and must leave no preflight record.
    fake_declaration = IndexRecord(
        kind="job-declared",
        record_id="JOB-PARTIAL-RECERT-GAP",
        subject=f"Batch:{fixture.batch.identity}",
        status="declared",
        fingerprint="b" * 64,
        payload={"batch_id": fixture.batch.identity},
    )
    original_lookup = LocalIndex.records_by_payload_text

    def lookup(index: LocalIndex, kind: str, name: str, value: str):
        if (
            kind == "job-declared"
            and name == "batch_id"
            and value == fixture.batch.identity
        ):
            return (fake_declaration,)
        return original_lookup(index, kind, name, value)

    before = fixture.writer.journal.tail()[0]
    with (
        _legacy_replay_surface(fixture, accepted=True),
        patch.object(LocalIndex, "records_by_payload_text", new=lookup),
    ):
        with pytest.raises(
            TransitionError,
            match="preflight differs from the active family",
        ):
            fixture.writer.record_replay_job_implementation_preflight(
                request=fixture.request,
                operation_id="reject-partial-recert-operation-gap",
            )
    assert fixture.writer.journal.tail()[0] == before
