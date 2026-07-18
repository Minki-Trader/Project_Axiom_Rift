from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from typing import Any

import pytest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations import repair_validation
from axiom_rift.operations import registered_repair_episode_authority as authority
from axiom_rift.operations.repair_candidate import (
    RepairCandidate,
    build_repair_candidate,
    build_repair_evaluation,
    parse_repair_candidate,
)
from axiom_rift.operations.repair_observation_authority import (
    REPAIR_VALIDATION_OBSERVATION_SCHEMA,
)
from axiom_rift.operations.registered_repair_episode_authority import (
    RegisteredRepairEpisodeAuthorityError,
    require_registered_repair_episode,
)
from axiom_rift.operations.replay_repair_operational_authority import (
    ReplayRepairOperationalAuthorityError,
    require_repair_chain,
)
from axiom_rift.operations.running_job import RunningJobAuthorityIntegrityError
from axiom_rift.operations.running_job_repair_projection import (
    effective_repair_head_implementation,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex
from replay_repair_fixture_factory import _repair_fixture
from replay_repair_fixture_mutations import _add_second_implementation_repair
from replay_repair_fixture_records import (
    NEW_IMPLEMENTATION,
    REGISTERED,
    THIRD_IMPLEMENTATION,
    _repair_attempt_fingerprint_record,
)


def _engine_projection(fixture: Any) -> tuple[str, str | None]:
    return effective_repair_head_implementation(
        fixture.index,
        job_id=fixture.declaration.record_id,
        declared_implementation_identity=fixture.declaration.payload["spec"][
            "implementation_identity"
        ],
    )


def _replay_projection(fixture: Any) -> tuple[IndexRecord, ...]:
    return require_repair_chain(
        fixture.index,
        job_id=fixture.declaration.record_id,
        declared_implementation_identity=fixture.declaration.payload["spec"][
            "implementation_identity"
        ],
        expected_implementation_identity=NEW_IMPLEMENTATION,
        trigger_repair_close_record_id=fixture.repair_close.record_id,
        declaration=fixture.declaration,
        executable_id=REGISTERED[0],
    )


def test_fixture_only_registered_trace_remains_projection_compatible(
    tmp_path: Any,
) -> None:
    fixture = _repair_fixture(tmp_path, registered_repair_authority=True)

    assert _engine_projection(fixture)[0] == NEW_IMPLEMENTATION
    assert _replay_projection(fixture) == (fixture.repair_close,)


def test_candidate_stripped_production_episode_fails_both_projections(
    tmp_path: Any,
) -> None:
    fixture = _repair_fixture(tmp_path, registered_repair_authority=True)
    production_open = replace(
        fixture.repair_open,
        payload={
            **fixture.repair_open.payload,
            "repair_validation_scope": "production",
        },
    )
    fixture.replace_records(((fixture.repair_open, production_open),))

    with pytest.raises(RunningJobAuthorityIntegrityError):
        _engine_projection(fixture)
    with pytest.raises(ReplayRepairOperationalAuthorityError):
        _replay_projection(fixture)


@pytest.mark.parametrize(
    "attack",
    ("open_not_after_declaration", "terminal_event_differs_from_close"),
)
def test_registered_episode_chronology_fails_both_projections(
    tmp_path: Any,
    attack: str,
) -> None:
    fixture = _repair_fixture(tmp_path, registered_repair_authority=True)
    if attack == "open_not_after_declaration":
        forged = replace(
            fixture.repair_open,
            authority_sequence=fixture.declaration.authority_sequence,
            authority_event_id=fixture.declaration.authority_event_id,
        )
        fixture.replace_records(((fixture.repair_open, forged),))
    else:
        forged = replace(
            fixture.attempt,
            authority_event_id="f" * 64,
        )
        fingerprint = next(
            record
            for record in fixture.records
            if record.kind == "repair-attempt-fingerprint"
        )
        forged_fingerprint = replace(
            fingerprint,
            authority_event_id=forged.authority_event_id,
        )
        fixture.replace_records(((fixture.attempt, forged),))
        fixture.replace_records(((fingerprint, forged_fingerprint),))

    with pytest.raises(RunningJobAuthorityIntegrityError):
        _engine_projection(fixture)
    with pytest.raises(ReplayRepairOperationalAuthorityError):
        _replay_projection(fixture)


def test_later_registered_episode_must_follow_predecessor_resume(
    tmp_path: Any,
) -> None:
    fixture = _repair_fixture(tmp_path, registered_repair_authority=True)
    _add_second_implementation_repair(fixture, continuous=True)
    second_open = next(
        record
        for record in fixture.records
        if record.kind == "repair-open" and record.payload.get("episode") == 2
    )
    first_resume = fixture.index.event_record(
        f"job-resume:{fixture.declaration.record_id}", 1
    )
    assert first_resume is not None
    forged_open = replace(
        second_open,
        authority_sequence=first_resume.authority_sequence,
        authority_event_id=first_resume.authority_event_id,
    )
    fixture.replace_records(((second_open, forged_open),))

    with pytest.raises(RunningJobAuthorityIntegrityError):
        _engine_projection(fixture)
    head = fixture.index.event_head(
        f"job-repair:{fixture.declaration.record_id}"
    )
    assert head is not None
    with pytest.raises(ReplayRepairOperationalAuthorityError):
        require_repair_chain(
            fixture.index,
            job_id=fixture.declaration.record_id,
            declared_implementation_identity=fixture.declaration.payload["spec"][
                "implementation_identity"
            ],
            expected_implementation_identity=THIRD_IMPLEMENTATION,
            trigger_repair_close_record_id=head.record_id,
            declaration=fixture.declaration,
            executable_id=REGISTERED[0],
        )


def test_successful_episode_projection_consumes_observation_stream(
    tmp_path: Any,
) -> None:
    fixture = _repair_fixture(tmp_path, registered_repair_authority=True)
    malformed = IndexRecord(
        kind="repair-validation-observation",
        record_id="d" * 64,
        subject=f"Repair:{fixture.repair_open.record_id}",
        status="not_evaluable",
        fingerprint="e" * 64,
        payload={},
        event_stream=(
            f"repair-validation-observation:{fixture.repair_open.record_id}"
        ),
        event_sequence=1,
        authority_sequence=19,
        authority_event_id="1" * 64,
        authority_offset=0,
    )
    fixture.add_records((malformed,))

    with pytest.raises(RunningJobAuthorityIntegrityError):
        _engine_projection(fixture)
    with pytest.raises(ReplayRepairOperationalAuthorityError):
        _replay_projection(fixture)


_CAPABILITIES = (("fixture.registered.repair.v1", "validator:" + "9" * 64),)


def _attempt_fingerprint(payload: dict[str, Any]) -> str:
    return canonical_digest(
        domain="repair-attempt-intervention",
        payload={
            "changed_dimension": payload["changed_dimension"],
            "implementation_proof_hash": payload["implementation_proof_hash"],
            "new_basis_hash": payload["new_basis_hash"],
            "new_evidence_hashes": payload["new_evidence_hashes"],
            "outcome": payload["outcome"],
            "verification_capabilities": [
                {"protocol": protocol, "validator_id": validator_id}
                for protocol, validator_id in _CAPABILITIES
            ],
        },
    )


def _attempt_record(
    fixture: Any,
    *,
    payload: dict[str, Any],
    sequence: int,
    authority_sequence: int,
    authority_event_id: str,
) -> IndexRecord:
    payload = {**payload, "attempt_fingerprint": _attempt_fingerprint(payload)}
    identity = dict(payload)
    identity.pop("scientific_failure_delta")
    identity.pop("scientific_trial_delta")
    return IndexRecord(
        kind="repair-attempt",
        record_id=canonical_digest(domain="repair-attempt", payload=identity),
        subject=f"Repair:{fixture.repair_open.record_id}",
        status=str(payload["outcome"]),
        fingerprint=str(payload["attempt_proof_hash"]),
        payload=payload,
        event_stream=f"repair-attempt:{fixture.repair_open.record_id}",
        event_sequence=sequence,
        authority_sequence=authority_sequence,
        authority_event_id=authority_event_id,
        authority_offset=0,
    )


def _two_attempt_cause_episode(
    fixture: Any,
    *,
    terminal_basis: str,
) -> tuple[IndexRecord, IndexRecord, IndexRecord, IndexRecord, IndexRecord]:
    opened = fixture.repair_open
    original = fixture.attempt.payload
    failed_basis = "b" * 64
    failed_payload = {
        **original,
        "attempt_proof_hash": "e" * 64,
        "changed_dimension": "cause",
        "explanation": "a new cause basis still reproduced the defect",
        "failure_observation": "the original engineering defect reproduced",
        "implementation_proof_hash": None,
        "new_basis_hash": failed_basis,
        "new_evidence_hashes": [failed_basis],
        "outcome": "failed",
        "previous_basis_hash": opened.fingerprint,
        "prior_attempt_record_id": None,
    }
    failed_payload.pop("semantic_equivalence_validation")
    failed = _attempt_record(
        fixture,
        payload=failed_payload,
        sequence=1,
        authority_sequence=19,
        authority_event_id="1" * 64,
    )
    terminal_payload = {
        **original,
        "attempt_proof_hash": "d" * 64,
        "changed_dimension": "cause",
        "explanation": "a second cause basis repaired the engineering defect",
        "failure_observation": None,
        "implementation_proof_hash": None,
        "new_basis_hash": terminal_basis,
        "new_evidence_hashes": [terminal_basis],
        "outcome": "repaired",
        "previous_basis_hash": failed_basis,
        "prior_attempt_record_id": failed.record_id,
    }
    terminal_payload.pop("semantic_equivalence_validation")
    terminal = _attempt_record(
        fixture,
        payload=terminal_payload,
        sequence=2,
        authority_sequence=20,
        authority_event_id="2" * 64,
    )
    failed_fingerprint = _repair_attempt_fingerprint_record(failed)
    terminal_fingerprint = _repair_attempt_fingerprint_record(terminal)
    assert failed_fingerprint is not None and terminal_fingerprint is not None
    close_payload = {
        **fixture.repair_close.payload,
        "attempt_record_id": terminal.record_id,
        "changed_cause_proof_hash": terminal.fingerprint,
        "changed_dimension": "cause",
        "effective_implementation_identity": fixture.repair_close.payload[
            "previous_effective_implementation_identity"
        ],
        "implementation_changed": False,
        "prior_attempt_record_id": failed.record_id,
        "repair_validation": terminal.payload["repair_validation"],
        "verification_evidence_hashes": terminal.payload[
            "verification_evidence_hashes"
        ],
    }
    close_payload.pop("semantic_equivalence_validation")
    close_identity = {
        "proof": close_payload["changed_cause_proof_hash"],
        "repair_id": close_payload["repair_id"],
        "repair_authority_schema": close_payload["repair_authority_schema"],
        "repair_validation": close_payload["repair_validation"],
    }
    close = replace(
        fixture.repair_close,
        record_id=canonical_digest(domain="repair-close", payload=close_identity),
        fingerprint=terminal.fingerprint,
        payload=close_payload,
        authority_sequence=20,
        authority_event_id=terminal.authority_event_id,
    )
    return failed, failed_fingerprint, terminal, terminal_fingerprint, close


def test_registered_episode_rejects_a_b_a_basis_reuse(
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _repair_fixture(tmp_path, registered_repair_authority=True)
    monkeypatch.setattr(
        authority,
        "_require_registered_validation",
        lambda *args, **kwargs: (None, _CAPABILITIES),
    )
    old_fingerprint = next(
        record
        for record in fixture.records
        if record.kind == "repair-attempt-fingerprint"
    )
    retained = [
        record
        for record in fixture.records
        if record not in (fixture.attempt, fixture.repair_close, old_fingerprint)
    ]

    unique = _two_attempt_cause_episode(fixture, terminal_basis="c" * 64)
    fixture.index.rebuild((*retained, *unique))
    accepted = require_registered_repair_episode(
        fixture.index,
        opened=fixture.repair_open,
        close=unique[-1],
        declaration=fixture.declaration,
        job_id=fixture.declaration.record_id,
        episode=1,
        predecessor_repair_close_record_id=None,
        prior_authority_sequence=fixture.declaration.authority_sequence,
    )
    assert accepted.terminal_attempt.record_id == unique[2].record_id

    cycled = _two_attempt_cause_episode(
        fixture,
        terminal_basis=fixture.repair_open.fingerprint,
    )
    fixture.index.rebuild((*retained, *cycled))
    with pytest.raises(
        RegisteredRepairEpisodeAuthorityError,
        match="attempt chain is malformed",
    ):
        require_registered_repair_episode(
            fixture.index,
            opened=fixture.repair_open,
            close=cycled[-1],
            declaration=fixture.declaration,
            job_id=fixture.declaration.record_id,
            episode=1,
            predecessor_repair_close_record_id=None,
            prior_authority_sequence=fixture.declaration.authority_sequence,
        )


_CANDIDATE_FLAT_FIELDS = {
    "cause_hash",
    "changed_dimension",
    "explanation",
    "implementation_proof_hash",
    "job_hash",
    "job_id",
    "new_basis_hash",
    "new_evidence_hashes",
    "previous_basis_hash",
    "prior_attempt_record_id",
    "repair_id",
    "reproduction_evidence_hashes",
    "resume_action",
    "scientific_semantics_changed",
    "verification_evidence_hashes",
}


def _fixture_digest(label: str) -> str:
    return sha256(label.encode("ascii")).hexdigest()


def _candidate_validation(
    fixture: Any,
    *,
    mode: str,
    tag: str,
    prior_observation_head: dict[str, Any] | None = None,
    bound_observations: tuple[dict[str, Any], ...] = (),
    additional_new_evidence: tuple[str, ...] = (),
    final_attempt: bool,
) -> tuple[dict[str, Any], RepairCandidate, dict[str, Any], dict[str, Any]]:
    base = fixture.attempt.payload
    if final_attempt:
        changed_dimension = str(base["changed_dimension"])
        implementation_proof = str(base["implementation_proof_hash"])
        new_basis = str(base["new_basis_hash"])
        new_evidence = tuple(
            sorted({*base["new_evidence_hashes"], *additional_new_evidence})
        )
        explanation = str(base["explanation"])
    else:
        changed_dimension = "information"
        implementation_proof = None
        new_basis = _fixture_digest(f"{tag}-basis")
        new_evidence = (new_basis,)
        explanation = "measure a distinct zero-credit information basis"

    receipt_hash = _fixture_digest(f"{tag}-receipt")
    validator_id = "validator:" + _fixture_digest(f"{tag}-validator")
    validation_plan_hash = _fixture_digest(f"{tag}-plan")
    result_hash = _fixture_digest(f"{tag}-result")
    protocol = "fixture.registered.repair.candidate.v3"
    candidate_payload = build_repair_candidate(
        repair_id=base["repair_id"],
        job_id=base["job_id"],
        job_hash=base["job_hash"],
        cause_hash=base["cause_hash"],
        repair_axis_id=f"{changed_dimension}-registered-v3-fixture",
        changed_dimension=changed_dimension,
        previous_basis_hash=base["previous_basis_hash"],
        new_basis_hash=new_basis,
        prior_attempt_record_id=None,
        prior_validation_observation_head=prior_observation_head,
        bound_validation_observations=bound_observations,
        reproduction_evidence_hashes=base["reproduction_evidence_hashes"],
        new_evidence_hashes=new_evidence,
        verification_evidence_hashes=(receipt_hash,),
        implementation_proof_hash=implementation_proof,
        explanation=explanation,
        resume_action=base["resume_action"],
    )
    candidate = parse_repair_candidate(
        canonical_bytes(candidate_payload),
        repair_id=base["repair_id"],
        job_id=base["job_id"],
        job_hash=base["job_hash"],
        cause_hash=base["cause_hash"],
        previous_basis_hash=base["previous_basis_hash"],
        prior_attempt_record_id=None,
        reproduction_evidence_hashes=base["reproduction_evidence_hashes"],
        resume_action=base["resume_action"],
    )
    if mode == "repaired":
        cause_resolved = True
        failure_reproduced = False
        material_change = True
        reason_code = None
        verdict = "passed"
    elif mode == "not_evaluable":
        cause_resolved = None
        failure_reproduced = None
        material_change = None
        reason_code = "fixture_measurement_inconclusive"
        verdict = "not_evaluable"
    else:
        raise AssertionError("synthetic candidate mode is unsupported")

    mission_id = str(fixture.declaration.payload["mission_id"])
    binding = repair_validation.repair_validation_binding(
        verification_kind="candidate",
        mission_id=mission_id,
        protocol=protocol,
        context=repair_validation.repair_candidate_validation_context(candidate),
        artifact_roles=(("validation_result", result_hash),),
    )
    facts = {
        "binding": binding,
        "cause_resolved": cause_resolved,
        "failure_reproduced": failure_reproduced,
        "material_change": material_change,
        "mode": mode,
        "new_failure_manifest_hash": None,
        "reason_code": reason_code,
    }
    registered_trace = {
        "authority_scope": "fixture_only",
        "evidence_subject": {
            "kind": "Repair",
            "id": candidate.repair_id,
        },
        "facts": facts,
        "protocol": protocol,
        "registry_trace": {
            "declared_artifact_count": 2,
            "opened_artifact_count": 2,
            "validator_id": validator_id,
        },
        "result_artifact_hashes": [result_hash],
        "schema": repair_validation.TRACE_SCHEMA,
        "validation_plan_hash": validation_plan_hash,
        "verification_kind": "candidate",
        "verdict": verdict,
    }
    registered_trace_hash = sha256(
        canonical_bytes(registered_trace)
    ).hexdigest()
    evaluation = build_repair_evaluation(
        candidate_hash=candidate.sha256,
        validator_id=validator_id,
        validation_plan_hash=validation_plan_hash,
        registry_trace_hash=registered_trace_hash,
        mode=mode,
        cause_resolved=cause_resolved,
        failure_reproduced=failure_reproduced,
        material_change=material_change,
        new_failure_manifest_hash=None,
        reason_code=reason_code,
    )
    body = {
        "evaluation": evaluation,
        "receipt_hash": receipt_hash,
        "registered_trace": registered_trace,
        "registered_trace_hash": registered_trace_hash,
        "schema": repair_validation.CANDIDATE_TRACE_SCHEMA,
    }
    wrapper = {
        **body,
        "trace_sha256": sha256(canonical_bytes(body)).hexdigest(),
    }
    return candidate_payload, candidate, wrapper, evaluation


def _candidate_observation(
    fixture: Any,
    *,
    tag: str,
) -> tuple[IndexRecord, tuple[dict[str, Any], ...], dict[str, Any]]:
    candidate_payload, candidate, wrapper, evaluation = _candidate_validation(
        fixture,
        mode="not_evaluable",
        tag=tag,
        final_attempt=False,
    )
    identity = {
        "candidate_hash": candidate.sha256,
        "evaluation": evaluation,
        "registered_candidate_validation": wrapper,
        "repair_id": candidate.repair_id,
        "schema": REPAIR_VALIDATION_OBSERVATION_SCHEMA,
    }
    record_id = canonical_digest(
        domain="repair-validation-observation",
        payload=identity,
    )
    payload = {
        "basis_advance": False,
        "candidate": candidate_payload,
        "candidate_delta": 0,
        "candidate_hash": candidate.sha256,
        "evaluation": evaluation,
        "holdout_reveal_delta": 0,
        "registered_candidate_validation": wrapper,
        "release_delta": 0,
        "repair_attempt_delta": 0,
        "repair_authority_schema": (
            repair_validation.REGISTERED_REPAIR_AUTHORITY_SCHEMA
        ),
        "repair_id": candidate.repair_id,
        "schema": REPAIR_VALIDATION_OBSERVATION_SCHEMA,
        "scientific_failure_delta": 0,
        "scientific_trial_delta": 0,
    }
    record = IndexRecord(
        kind="repair-validation-observation",
        record_id=record_id,
        subject=f"Repair:{candidate.repair_id}",
        status="not_evaluable",
        fingerprint=candidate.sha256,
        payload=payload,
        event_stream=(
            f"repair-validation-observation:{candidate.repair_id}"
        ),
        event_sequence=1,
        authority_sequence=19,
        authority_event_id=_fixture_digest(f"{tag}-event"),
        authority_offset=0,
    )
    information = tuple(
        sorted(
            {
                candidate.sha256,
                str(evaluation["validation_plan_hash"]),
            }
        )
    )
    bound = (
        {
            "new_information_evidence_hashes": list(information),
            "observation_record_id": record.record_id,
        },
    )
    head = {
        "fingerprint": record.fingerprint,
        "record_id": record.record_id,
        "sequence": 1,
    }
    return record, bound, head


def _candidate_episode(
    fixture: Any,
    *,
    bound_observations: tuple[dict[str, Any], ...] = (),
    prior_observation_head: dict[str, Any] | None = None,
) -> dict[str, IndexRecord]:
    information = tuple(
        identity
        for observation in bound_observations
        for identity in observation["new_information_evidence_hashes"]
    )
    candidate_payload, candidate, wrapper, evaluation = _candidate_validation(
        fixture,
        mode="repaired",
        tag="terminal-repaired",
        prior_observation_head=prior_observation_head,
        bound_observations=bound_observations,
        additional_new_evidence=information,
        final_attempt=True,
    )
    attempt_payload = dict(fixture.attempt.payload)
    for key in _CANDIDATE_FLAT_FIELDS:
        attempt_payload[key] = candidate_payload[key]
    attempt_payload.update(
        {
            "attempt_proof_hash": candidate.sha256,
            "repair_candidate": candidate_payload,
            "repair_candidate_hash": candidate.sha256,
            "repair_evaluation": evaluation,
            "repair_validation": wrapper,
        }
    )
    registered = wrapper["registered_trace"]
    attempt_payload["attempt_fingerprint"] = canonical_digest(
        domain="repair-attempt-intervention",
        payload={
            "changed_dimension": attempt_payload["changed_dimension"],
            "implementation_proof_hash": attempt_payload[
                "implementation_proof_hash"
            ],
            "new_basis_hash": attempt_payload["new_basis_hash"],
            "new_evidence_hashes": attempt_payload["new_evidence_hashes"],
            "outcome": attempt_payload["outcome"],
            "verification_capabilities": [
                {
                    "protocol": registered["protocol"],
                    "validator_id": registered["registry_trace"][
                        "validator_id"
                    ],
                }
            ],
        },
    )
    attempt_identity = dict(attempt_payload)
    attempt_identity.pop("scientific_failure_delta")
    attempt_identity.pop("scientific_trial_delta")
    authority_event_id = _fixture_digest("terminal-repaired-event")
    attempt = replace(
        fixture.attempt,
        record_id=canonical_digest(
            domain="repair-attempt",
            payload=attempt_identity,
        ),
        fingerprint=candidate.sha256,
        payload=attempt_payload,
        authority_sequence=20,
        authority_event_id=authority_event_id,
    )
    fingerprint = _repair_attempt_fingerprint_record(attempt)
    assert fingerprint is not None

    close_payload = {
        **fixture.repair_close.payload,
        "attempt_record_id": attempt.record_id,
        "changed_cause_proof_hash": candidate.sha256,
        "repair_candidate": candidate_payload,
        "repair_candidate_hash": candidate.sha256,
        "repair_evaluation": evaluation,
        "repair_validation": wrapper,
        "verification_evidence_hashes": list(
            candidate.verification_evidence_hashes
        ),
    }
    close_identity = {
        "proof": close_payload["changed_cause_proof_hash"],
        "repair_id": close_payload["repair_id"],
        "repair_authority_schema": close_payload["repair_authority_schema"],
        "repair_validation": close_payload["repair_validation"],
        "semantic_equivalence_validation": close_payload[
            "semantic_equivalence_validation"
        ],
        "repair_candidate": close_payload["repair_candidate"],
        "repair_candidate_hash": close_payload["repair_candidate_hash"],
        "repair_evaluation": close_payload["repair_evaluation"],
    }
    close = replace(
        fixture.repair_close,
        record_id=canonical_digest(
            domain="repair-close",
            payload=close_identity,
        ),
        fingerprint=candidate.sha256,
        payload=close_payload,
        authority_sequence=20,
        authority_event_id=authority_event_id,
    )
    return {
        "attempt": attempt,
        "close": close,
        "fingerprint": fingerprint,
    }


def _authenticate_candidate_episode(
    tmp_path: Any,
    fixture: Any,
    episode: dict[str, IndexRecord],
    *,
    observation: IndexRecord | None,
) -> None:
    records = [
        fixture.declaration,
        fixture.repair_open,
        episode["fingerprint"],
        episode["attempt"],
        episode["close"],
    ]
    if observation is not None:
        records.append(observation)
    index = LocalIndex(tmp_path / "candidate-episode.sqlite")
    index.rebuild(records)
    require_registered_repair_episode(
        index,
        opened=fixture.repair_open,
        close=episode["close"],
        declaration=fixture.declaration,
        job_id=fixture.declaration.record_id,
        episode=1,
        predecessor_repair_close_record_id=None,
        prior_authority_sequence=fixture.declaration.authority_sequence,
    )


def test_genuine_v3_candidate_rebinds_exact_prior_observation_prefix(
    tmp_path: Any,
) -> None:
    fixture = _repair_fixture(tmp_path, registered_repair_authority=True)
    observation, bound, head = _candidate_observation(
        fixture,
        tag="genuine-observation",
    )
    episode = _candidate_episode(
        fixture,
        bound_observations=bound,
        prior_observation_head=head,
    )

    _authenticate_candidate_episode(
        tmp_path,
        fixture,
        episode,
        observation=observation,
    )


def test_v3_candidate_cannot_omit_prior_observation_binding(
    tmp_path: Any,
) -> None:
    fixture = _repair_fixture(tmp_path, registered_repair_authority=True)
    observation, _bound, _head = _candidate_observation(
        fixture,
        tag="omitted-observation",
    )
    episode = _candidate_episode(fixture)

    with pytest.raises(
        RegisteredRepairEpisodeAuthorityError,
        match="does not bind its exact prior observation stream",
    ):
        _authenticate_candidate_episode(
            tmp_path,
            fixture,
            episode,
            observation=observation,
        )


def test_v3_candidate_cannot_bind_a_different_observation_prefix(
    tmp_path: Any,
) -> None:
    fixture = _repair_fixture(tmp_path, registered_repair_authority=True)
    expected_observation, bound, head = _candidate_observation(
        fixture,
        tag="expected-observation",
    )
    different_observation, _different_bound, _different_head = (
        _candidate_observation(
            fixture,
            tag="different-observation",
        )
    )
    assert expected_observation.record_id != different_observation.record_id
    episode = _candidate_episode(
        fixture,
        bound_observations=bound,
        prior_observation_head=head,
    )

    with pytest.raises(
        RegisteredRepairEpisodeAuthorityError,
        match="does not bind its exact prior observation stream",
    ):
        _authenticate_candidate_episode(
            tmp_path,
            fixture,
            episode,
            observation=different_observation,
        )
