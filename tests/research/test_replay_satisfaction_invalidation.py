from __future__ import annotations

import pytest

from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.replay_satisfaction_invalidation import (
    ReplayCompletionValidityDefect,
    ReplayCompletionValidityDefectCode,
    ReplayCompletionValidityObservation,
    ReplayMultiplicityBindingDefect,
    ReplayMultiplicityDefectCode,
    ReplaySatisfactionInvalidationAuditManifest,
    ReplaySatisfactionInvalidationAuditManifestV2,
    ReplaySelectionFamilyObservation,
    SELECTION_CRITERION_ID,
    replay_satisfaction_invalidation_manifest_from_mapping,
)


EXPECTED_MEMBER_IDS = (
    "executable:" + "3" * 64,
    "executable:" + "1" * 64,
    "executable:" + "2" * 64,
)


def _registration_hash(ordered_member_ids: tuple[str, ...]) -> str:
    return canonical_digest(
        domain="scientific-v2-multiplicity-family",
        payload={
            "alpha_ppm": 100_000,
            "family_id": "family:test",
            "family_size": len(ordered_member_ids),
            "method": "holm",
            "ordered_member_ids": list(ordered_member_ids),
            "schema": "scientific_multiplicity_family_registration.v1",
        },
    )


def _observation(
    executable_id: str,
    *,
    ordered_member_ids: tuple[str, ...],
) -> ReplaySelectionFamilyObservation:
    token = int(executable_id[-1], 16)
    return ReplaySelectionFamilyObservation(
        executable_id=executable_id,
        completion_record_id=f"{token + 4:064x}",
        family_id="family:test",
        family_size=len(ordered_member_ids),
        method="holm",
        alpha_ppm=100_000,
        registered_member_id=executable_id,
        ordered_member_ids=ordered_member_ids,
        family_registration_hash=_registration_hash(ordered_member_ids),
    )


def _defect(
    observed_order: tuple[str, ...],
    *,
    actual_member_set_mismatch: bool = False,
) -> ReplayMultiplicityBindingDefect:
    def member_ids(executable_id: str) -> tuple[str, ...]:
        if not actual_member_set_mismatch:
            return observed_order
        peer = next(item for item in EXPECTED_MEMBER_IDS if item != executable_id)
        return (executable_id, peer, "executable:" + "9" * 64)

    return ReplayMultiplicityBindingDefect(
        code=(
            ReplayMultiplicityDefectCode.SELECTION_FAMILY_MEMBERSHIP_MISMATCH
        ),
        criterion_id=SELECTION_CRITERION_ID,
        batch_open_record_id="batch:" + "a" * 64,
        batch_close_record_id="b" * 64,
        expected_executable_ids=EXPECTED_MEMBER_IDS,
        expected_family_size=len(EXPECTED_MEMBER_IDS),
        observations=tuple(
            _observation(
                executable_id,
                ordered_member_ids=member_ids(executable_id),
            )
            for executable_id in sorted(EXPECTED_MEMBER_IDS)
        ),
    )


def test_same_set_reversed_registration_is_not_a_revocation_defect() -> None:
    reversed_order = tuple(reversed(EXPECTED_MEMBER_IDS))
    with pytest.raises(ValueError, match="membership mismatch is not present"):
        _defect(reversed_order)


def test_actual_member_set_substitution_remains_a_membership_defect() -> None:
    defect = _defect(
        EXPECTED_MEMBER_IDS,
        actual_member_set_mismatch=True,
    )
    assert defect.expected_executable_ids == EXPECTED_MEMBER_IDS
    assert all(
        set(observation.ordered_member_ids) != set(EXPECTED_MEMBER_IDS)
        for observation in defect.observations
    )


def test_exact_batch_order_cannot_be_mislabeled_as_a_membership_defect() -> None:
    with pytest.raises(ValueError, match="membership mismatch is not present"):
        _defect(EXPECTED_MEMBER_IDS)


def test_membership_defect_round_trip_preserves_exact_batch_order() -> None:
    defect = _defect(
        EXPECTED_MEMBER_IDS,
        actual_member_set_mismatch=True,
    )
    rebuilt = ReplayMultiplicityBindingDefect.from_mapping(
        defect.to_identity_payload()
    )
    assert rebuilt == defect
    assert rebuilt.expected_executable_ids == EXPECTED_MEMBER_IDS


def test_registration_hash_binds_member_order() -> None:
    reversed_order = tuple(reversed(EXPECTED_MEMBER_IDS))
    with pytest.raises(ValueError, match="registration hash is invalid"):
        ReplaySelectionFamilyObservation(
            executable_id=EXPECTED_MEMBER_IDS[0],
            completion_record_id="c" * 64,
            family_id="family:test",
            family_size=len(EXPECTED_MEMBER_IDS),
            method="holm",
            alpha_ppm=100_000,
            registered_member_id=EXPECTED_MEMBER_IDS[0],
            ordered_member_ids=reversed_order,
            family_registration_hash=_registration_hash(EXPECTED_MEMBER_IDS),
        )


def _multiplicity_manifest() -> ReplaySatisfactionInvalidationAuditManifest:
    defect = _defect(
        EXPECTED_MEMBER_IDS,
        actual_member_set_mismatch=True,
    )
    return ReplaySatisfactionInvalidationAuditManifest(
        governing_mission_id="MIS-0001",
        obligation_id="historical-replay-obligation:" + "5" * 64,
        satisfaction_record_id="historical-replay-satisfaction:" + "6" * 64,
        satisfaction_event_sequence=2,
        portfolio_decision_id="decision:" + "7" * 64,
        replay_study_id="STU-0001",
        replay_executable_id=EXPECTED_MEMBER_IDS[0],
        replay_study_close_record_id="8" * 64,
        study_diagnosis_id="diagnosis:" + "9" * 64,
        completion_record_ids=tuple(
            item.completion_record_id for item in defect.observations
        ),
        defect=defect,
    )


def test_v1_manifest_rejects_domain_noncanonical_inventory_order() -> None:
    payload = _multiplicity_manifest().to_identity_payload()
    payload["completion_record_ids"] = list(
        reversed(payload["completion_record_ids"])
    )

    with pytest.raises(ValueError, match="changed on rebuild"):
        replay_satisfaction_invalidation_manifest_from_mapping(payload)


def _validity_observation(
    completion_record_id: str = "4" * 64,
) -> ReplayCompletionValidityObservation:
    return ReplayCompletionValidityObservation(
        completion_record_id=completion_record_id,
        executable_id=EXPECTED_MEMBER_IDS[0],
        invalidation_record_id=(
            "historical-scientific-validity-invalidation:" + "d" * 64
        ),
        reason="decision_input_point_in_time_unproven",
        affected_criterion_ids=("C03-decision-time-causality", "A01-alpha"),
        validity_stream_sequence=1,
        authority_event_id="e" * 64,
        authority_sequence=42,
        authority_offset=420,
    )


def _validity_manifest() -> ReplaySatisfactionInvalidationAuditManifestV2:
    defect = ReplayCompletionValidityDefect(
        code=(
            ReplayCompletionValidityDefectCode.EVIDENCE_COMPLETION_VALIDITY_INVALID
        ),
        observations=(_validity_observation(),),
    )
    return ReplaySatisfactionInvalidationAuditManifestV2(
        governing_mission_id="MIS-0001",
        obligation_id="historical-replay-obligation:" + "5" * 64,
        satisfaction_record_id="historical-replay-satisfaction:" + "6" * 64,
        satisfaction_event_sequence=2,
        portfolio_decision_id="decision:" + "7" * 64,
        replay_study_id="STU-0001",
        replay_executable_id=EXPECTED_MEMBER_IDS[0],
        replay_study_close_record_id="8" * 64,
        study_diagnosis_id="diagnosis:" + "9" * 64,
        completion_record_ids=("4" * 64, "a" * 64),
        defects=(defect,),
    )


def test_completion_validity_v2_round_trip_is_sorted_and_generic() -> None:
    manifest = _validity_manifest()
    rebuilt = replay_satisfaction_invalidation_manifest_from_mapping(
        manifest.to_identity_payload()
    )
    assert rebuilt == manifest
    observation = manifest.defects[0].observations[0]
    assert observation.affected_criterion_ids == (
        "A01-alpha",
        "C03-decision-time-causality",
    )
    assert manifest.completion_record_ids == ("4" * 64, "a" * 64)


def test_v2_manifest_rejects_domain_noncanonical_inventory_order() -> None:
    payload = _validity_manifest().to_identity_payload()
    payload["completion_record_ids"] = list(
        reversed(payload["completion_record_ids"])
    )

    with pytest.raises(ValueError, match="changed on rebuild"):
        replay_satisfaction_invalidation_manifest_from_mapping(payload)


def test_v2_manifest_requires_completion_validity_at_construction() -> None:
    manifest = _multiplicity_manifest()

    with pytest.raises(ValueError, match="requires completion validity"):
        ReplaySatisfactionInvalidationAuditManifestV2(
            governing_mission_id=manifest.governing_mission_id,
            obligation_id=manifest.obligation_id,
            satisfaction_record_id=manifest.satisfaction_record_id,
            satisfaction_event_sequence=manifest.satisfaction_event_sequence,
            portfolio_decision_id=manifest.portfolio_decision_id,
            replay_study_id=manifest.replay_study_id,
            replay_executable_id=manifest.replay_executable_id,
            replay_study_close_record_id=manifest.replay_study_close_record_id,
            study_diagnosis_id=manifest.study_diagnosis_id,
            completion_record_ids=manifest.completion_record_ids,
            defects=(manifest.defect,),
        )


def test_completion_validity_defect_must_belong_to_satisfaction_evidence() -> None:
    manifest = _validity_manifest()
    with pytest.raises(ValueError, match="outside satisfaction evidence"):
        ReplaySatisfactionInvalidationAuditManifestV2(
            governing_mission_id=manifest.governing_mission_id,
            obligation_id=manifest.obligation_id,
            satisfaction_record_id=manifest.satisfaction_record_id,
            satisfaction_event_sequence=manifest.satisfaction_event_sequence,
            portfolio_decision_id=manifest.portfolio_decision_id,
            replay_study_id=manifest.replay_study_id,
            replay_executable_id=manifest.replay_executable_id,
            replay_study_close_record_id=manifest.replay_study_close_record_id,
            study_diagnosis_id=manifest.study_diagnosis_id,
            completion_record_ids=manifest.completion_record_ids,
            defects=(
                ReplayCompletionValidityDefect(
                    code=(
                        ReplayCompletionValidityDefectCode.EVIDENCE_COMPLETION_VALIDITY_INVALID
                    ),
                    observations=(_validity_observation("b" * 64),),
                ),
            ),
        )
