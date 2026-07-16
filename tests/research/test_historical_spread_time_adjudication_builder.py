from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from axiom_rift.research.historical_adjudication import (
    HistoricalDisposition,
    HistoricalValidityOverride,
    HistoricalValidityReason,
    ReplayPriority,
)
import axiom_rift.research.historical_spread_time_adjudication_builder as builder
from axiom_rift.research.historical_scientific_validity import (
    DecisionPredicateActivationState,
    HistoricalScientificValidityInvalidation,
    JobBindingKind,
)
from axiom_rift.research.historical_spread_time_invalidation_builder import (
    EXPECTED_STUDY_CONTEXTS,
    HistoricalSpreadTimeInvalidationInventory,
)
from axiom_rift.research.source_authority import (
    SourceAuthorityAuditManifest,
    SourceAuthorityInvalidation,
    SourceAuthorityLatch,
    SourceAuthorityReason,
    SourceAuthoritySurface,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


def _digest(label: str) -> str:
    return sha256(label.encode("ascii")).hexdigest()


def _legacy_rows() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for study_id in (
        "STU-0046",
        "STU-0047",
        "STU-0048",
        "STU-0049",
        "STU-0050",
        "STU-0051",
    ):
        for ordinal in range(4):
            completion_id = _digest(f"{study_id}-completion-{ordinal}")
            if study_id == "STU-0048" and ordinal == 3:
                completion_id = next(
                    item
                    for item in builder.P0_REPLAY_COMPLETION_IDS
                    if item.startswith("9765")
                )
            if study_id == "STU-0051" and ordinal == 0:
                completion_id = next(
                    item
                    for item in builder.P0_REPLAY_COMPLETION_IDS
                    if item.startswith("731e")
                )
            rows.append((study_id, completion_id))
    rows.extend(
        (
            ("STU-0071", _digest("STU-0071-completion")),
            ("STU-0101", builder.NOT_EVALUABLE_COMPLETION_ID),
        )
    )
    return rows


def _rich_rows() -> list[tuple[str, str]]:
    return [
        (study_id, _digest(f"{study_id}-completion-{ordinal}"))
        for study_id in ("STU-0107", "STU-0108")
        for ordinal in range(4)
    ]


@contextmanager
def _fixture(*, forged_timing_override: bool = False):
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        audit_hash = _digest("spread-time-audit")
        prior_audit_hash = _digest("prior-adjudication-audit")
        mission_id = "MIS-TEST"
        implementation_hash = _digest("implementation")
        source_id = "source:" + _digest("source")
        source_manifest = SourceAuthorityAuditManifest(
            report_artifact_hash=_digest("source-report"),
            report_finding_id="AX-SOURCE-TEST",
            source_contract_id=source_id,
            source_state_record_id=_digest("source-state"),
            surface=SourceAuthoritySurface.AVAILABILITY,
            reason_code=SourceAuthorityReason.POINT_IN_TIME_AUTHORITY_UNPROVEN,
            observed_defect="fixture_point_in_time_authority_unproven",
            observed_at_utc="2026-07-16T00:00:00Z",
        )
        source_invalidation = SourceAuthorityInvalidation(
            source_contract_id=source_id,
            source_state_record_id=source_manifest.source_state_record_id,
            audit_artifact_hash=_digest("source-audit-manifest"),
            surface=source_manifest.surface,
            reason_code=source_manifest.reason_code,
            observed_defect=source_manifest.observed_defect,
            observed_at_utc=source_manifest.observed_at_utc,
        )
        source_latch = SourceAuthorityLatch.bind(
            invalidation=source_invalidation,
            manifest=source_manifest,
        )
        source_override = HistoricalValidityOverride(
            reason=HistoricalValidityReason.SOURCE_AUTHORITY_INVALIDATED,
            subject_id=source_id,
            evidence_record_id=source_invalidation.identity,
        )

        records: list[IndexRecord] = []
        closes: dict[str, str] = {}
        for study_id in sorted(
            {study_id for study_id, _completion in _legacy_rows() + _rich_rows()}
        ):
            close_id = _digest(f"close-{study_id}")
            closes[study_id] = close_id
            records.extend(
                (
                    IndexRecord(
                        kind="study-open",
                        record_id=study_id,
                        subject=f"Study:{study_id}",
                        status="open",
                        fingerprint=_digest(f"open-{study_id}"),
                        payload={"mission_id": mission_id},
                    ),
                    IndexRecord(
                        kind="study-close",
                        record_id=close_id,
                        subject=f"Study:{study_id}",
                        status="preserved",
                        fingerprint=_digest(f"close-fingerprint-{study_id}"),
                        payload={"outcome": "preserved"},
                    ),
                )
            )
        records.append(
            IndexRecord(
                kind="source-authority-invalidation",
                record_id=source_invalidation.identity,
                subject=f"Source:{source_id}",
                status="confirmed_and_suspended",
                fingerprint=source_invalidation.identity.removeprefix(
                    "source-authority-invalidation:"
                ),
                payload={
                    "audit_manifest": source_manifest.to_identity_payload(),
                    "invalidation": source_invalidation.to_identity_payload(),
                    "latch": source_latch.to_identity_payload(),
                },
                event_stream=f"source-authority:{source_id}",
                event_sequence=1,
            )
        )

        invalidations: list[HistoricalScientificValidityInvalidation] = []
        prior_head_ids: list[str] = []
        head_entries: list[dict[str, object]] = []
        memory_entries: list[dict[str, str]] = []
        for ordinal, (study_id, completion_id) in enumerate(
            _legacy_rows() + _rich_rows()
        ):
            rich = study_id in {"STU-0107", "STU-0108"}
            executable_id = "executable:" + _digest(f"executable-{ordinal}")
            job_id = "job:" + _digest(f"job-{ordinal}")
            plan_hash = _digest(f"plan-{ordinal}")
            measurement_hash = _digest(f"measurement-{ordinal}")
            result_hash = _digest(f"result-{ordinal}")
            claims = ("claim",)
            modes = ("cost_and_execution",)
            criteria = ("C03-decision-time-causality",)
            source_contracts = [source_id] if study_id == "STU-0101" else []
            invalidation = HistoricalScientificValidityInvalidation(
                study_id=study_id,
                study_close_record_id=closes[study_id],
                job_id=job_id,
                job_binding_kind=JobBindingKind.DECLARATION,
                job_binding_record_id=job_id,
                completion_record_id=completion_id,
                executable_id=executable_id,
                validation_plan_hash=plan_hash,
                measurement_artifact_hash=measurement_hash,
                result_manifest_hash=result_hash,
                component_implementation_hashes=(implementation_hash,),
                clock_contract="clock:test",
                cost_contract="cost:test",
                predicate_evaluated=True,
                activation_state=(
                    DecisionPredicateActivationState.EVALUATED_NOT_ACTIVATED
                    if rich
                    else DecisionPredicateActivationState.LEGACY_AGGREGATE_NOT_SERIALIZED
                ),
                predicate_activation_count=0 if rich else None,
                affected_claim_ids=claims,
                affected_evidence_modes=modes,
                affected_criterion_ids=criteria,
                audit_finding_id="AX-SPREAD-TIME-001",
                audit_artifact_hash=audit_hash,
            )
            invalidations.append(invalidation)
            scientific: dict[str, object] = {
                "claims": list(claims),
                "executed_evidence_modes": list(modes),
                "executable_id": executable_id,
                "measurement_artifact_hashes": [measurement_hash],
                "result_manifest_hash": result_hash,
                "scientific_eligible": True,
                "validation_plan_hash": plan_hash,
                "verdict": "failed",
            }
            if rich:
                scientific["adjudication"] = {
                    "candidate_eligible": False,
                    "claims": [{"claim_id": "claim"}],
                    "criteria": [
                        {
                            "claim_id": "claim",
                            "criterion_id": "C03-decision-time-causality",
                        }
                    ],
                }
            records.extend(
                (
                    IndexRecord(
                        kind="trial",
                        record_id=executable_id,
                        subject=f"Batch:BAT-{ordinal}",
                        status="evaluated",
                        fingerprint=executable_id.removeprefix("executable:"),
                        payload={
                            "engineering_fixture": False,
                            "executable": {
                                "clock_contract": "clock:test",
                                "component_manifests": [
                                    {
                                        "implementation": (
                                            "fixture.component@sha256:"
                                            + implementation_hash
                                        )
                                    }
                                ],
                                "cost_contract": "cost:test",
                                "source_contracts": source_contracts,
                            },
                            "mission_id": mission_id,
                            "scientific_eligible": True,
                            "study_id": study_id,
                        },
                    ),
                    IndexRecord(
                        kind="job-declared",
                        record_id=job_id,
                        subject=f"Job:{job_id}",
                        status="declared",
                        fingerprint=_digest(f"declaration-{ordinal}"),
                        payload={
                            "mission_id": mission_id,
                            "spec": {
                                "evidence_subject": {
                                    "id": executable_id,
                                    "kind": "Executable",
                                }
                            },
                            "study_id": study_id,
                        },
                    ),
                    IndexRecord(
                        kind="job-completed",
                        record_id=completion_id,
                        subject=f"Job:{job_id}",
                        status="success",
                        fingerprint=_digest(f"completion-{ordinal}"),
                        payload={
                            "job_id": job_id,
                            "outputs": {
                                "measurement": measurement_hash,
                                "plan": plan_hash,
                                "result": result_hash,
                            },
                            "scientific": scientific,
                        },
                    ),
                )
            )
            if rich:
                continue

            memory_id = "negative-memory:" + _digest(f"memory-{ordinal}")
            head_id = "historical-adjudication:" + _digest(f"head-{ordinal}")
            prior_head_ids.append(head_id)
            prior_overrides: list[dict[str, str]] = []
            if study_id == "STU-0101":
                prior_overrides.append(source_override.manifest())
            if forged_timing_override and ordinal == 0:
                prior_overrides.append(
                    HistoricalValidityOverride(
                        reason=(
                            HistoricalValidityReason
                            .DECISION_INPUT_POINT_IN_TIME_UNPROVEN
                        ),
                        subject_id=completion_id,
                        evidence_record_id=(
                            "historical-scientific-validity-invalidation:"
                            + _digest("forged-timing")
                        ),
                    ).manifest()
                )
            status = "claim_scoped_qualification"
            if completion_id in builder.P0_REPLAY_COMPLETION_IDS:
                status = "replay_required"
            elif study_id == "STU-0071":
                status = "inventory_partial_positive"
            elif study_id == "STU-0101":
                status = "not_evaluable_qualification"
            records.extend(
                (
                    IndexRecord(
                        kind="negative-memory",
                        record_id=memory_id,
                        subject=f"Executable:{executable_id}",
                        status="durable",
                        fingerprint=executable_id,
                        payload={
                            "evidence_references": [completion_id],
                            "holdout_id": None,
                            "study_id": study_id,
                        },
                    ),
                    IndexRecord(
                        kind="historical-scientific-adjudication",
                        record_id=head_id,
                        subject=f"Study:{study_id}",
                        status=status,
                        fingerprint=head_id.removeprefix(
                            "historical-adjudication:"
                        ),
                        payload={
                            "adjudication": {"candidate_eligible": False},
                            "audit_artifact_hash": prior_audit_hash,
                            "candidate_delta": 0,
                            "claim_authority": "additive_qualification_only",
                            "completion_record_id": completion_id,
                            "disposition": status,
                            "executable_id": executable_id,
                            "holdout_delta": 0,
                            "measurement_artifact_hash": measurement_hash,
                            "negative_memory_ids": [memory_id],
                            "schema": "historical_scientific_adjudication.v2",
                            "study_close_record_id": closes[study_id],
                            "study_id": study_id,
                            "supersedes_record_id": None,
                            "trial_delta": 0,
                            "validation_plan_hash": plan_hash,
                            "validity_overrides": prior_overrides,
                        },
                        event_stream=f"historical-adjudication:{completion_id}",
                        event_sequence=1,
                    ),
                )
            )
            head_entries.append(
                {
                    "completion_record_id": completion_id,
                    "head_record_id": head_id,
                    "head_sequence": 1,
                }
            )
            memory_entries.append(
                {
                    "completion_record_id": completion_id,
                    "negative_memory_id": memory_id,
                }
            )
            if completion_id in builder.P0_REPLAY_COMPLETION_IDS:
                obligation_id, satisfaction_id = builder._P0_REPLAY_AUTHORITY[
                    completion_id
                ]
                stream = f"historical-replay-obligation:{obligation_id}"
                obligation = {
                    "historical_adjudication_id": head_id,
                    "original_completion_record_id": completion_id,
                    "original_executable_id": executable_id,
                    "original_study_close_record_id": closes[study_id],
                    "original_study_id": study_id,
                    "replay_priority": "p1",
                    "schema": "historical_replay_obligation.v1",
                }
                records.extend(
                    (
                        IndexRecord(
                            kind="historical-replay-obligation",
                            record_id=obligation_id,
                            subject=f"Mission:{mission_id}",
                            status="pending",
                            fingerprint=obligation_id.removeprefix(
                                "historical-replay-obligation:"
                            ),
                            payload={"obligation": obligation},
                            event_stream=stream,
                            event_sequence=1,
                        ),
                        IndexRecord(
                            kind="historical-replay-obligation-transition",
                            record_id=_digest(f"in-progress-{completion_id}"),
                            subject=f"Mission:{mission_id}",
                            status="in_progress",
                            fingerprint=_digest(f"in-progress-fp-{completion_id}"),
                            payload={
                                "obligation_id": obligation_id,
                                "prior_status": "pending",
                            },
                            event_stream=stream,
                            event_sequence=2,
                        ),
                        IndexRecord(
                            kind="historical-replay-obligation-resolution",
                            record_id=satisfaction_id,
                            subject=f"Mission:{mission_id}",
                            status="satisfied",
                            fingerprint=satisfaction_id.removeprefix(
                                "historical-replay-satisfaction:"
                            ),
                            payload={
                                "obligation_id": obligation_id,
                                "prior_status": "in_progress",
                                "resolution": {
                                    "obligation_id": obligation_id,
                                    "schema": "historical_replay_satisfaction.v1",
                                },
                            },
                            event_stream=stream,
                            event_sequence=3,
                        ),
                    )
                )

        inventory = HistoricalSpreadTimeInvalidationInventory(
            audit_artifact_hash=audit_hash,
            study_contexts=EXPECTED_STUDY_CONTEXTS,
            invalidations=tuple(
                sorted(
                    invalidations,
                    key=lambda item: item.completion_record_id,
                )
            ),
        )
        legacy = tuple(
            item
            for item in inventory.invalidations
            if item.study_id not in {"STU-0107", "STU-0108"}
        )
        rich = tuple(
            item
            for item in inventory.invalidations
            if item.study_id in {"STU-0107", "STU-0108"}
        )
        expected = {
            "_EXPECTED_ALL_INVALIDATION_INVENTORY_DIGEST": (
                builder._semantic_inventory_digest(
                    "all_typed_invalidations",
                    inventory.invalidations,
                )
            ),
            "_EXPECTED_LEGACY_INVALIDATION_INVENTORY_DIGEST": (
                builder._semantic_inventory_digest(
                    "legacy_v1_supersession",
                    legacy,
                )
            ),
            "_EXPECTED_RICH_V2_INVALIDATION_INVENTORY_DIGEST": (
                builder._semantic_inventory_digest("rich_v2_excluded", rich)
            ),
            "_EXPECTED_PRIOR_HEAD_INVENTORY_DIGEST": (
                builder._head_inventory_digest(
                    sorted(
                        head_entries,
                        key=lambda item: item["completion_record_id"],
                    )
                )
            ),
            "_EXPECTED_NEGATIVE_MEMORY_INVENTORY_DIGEST": (
                builder._negative_memory_inventory_digest(
                    sorted(
                        memory_entries,
                        key=lambda item: item["completion_record_id"],
                    )
                )
            ),
        }
        with LocalIndex(root / "index.sqlite") as index:
            index.put_many(records)
            yield index, inventory, expected, tuple(prior_head_ids), prior_audit_hash


@contextmanager
def _builder_patches(expected: dict[str, str], head_ids: tuple[str, ...], audit: str):
    def same_event(*_args, **_kwargs):
        return (
            "historical_scientific_adjudications_recorded",
            {
                "adjudication_record_ids": list(head_ids),
                "audit_artifact_hash": audit,
                "candidate_delta": 0,
                "holdout_delta": 0,
                "trial_delta": 0,
            },
        )

    with ExitStack() as stack:
        for name, value in expected.items():
            stack.enter_context(patch.object(builder, name, value))
        binding = stack.enter_context(
            patch.object(
                builder,
                "validate_completion_validity_invalidation_binding",
                return_value=None,
            )
        )
        stack.enter_context(
            patch.object(
                builder,
                "require_same_event_operation_result",
                side_effect=same_event,
            )
        )
        stack.enter_context(
            patch.object(
                builder,
                "_require_recorded_satisfaction_authority",
                return_value=None,
            )
        )
        yield binding


def test_builds_exact_policy_families_and_canonical_manifest() -> None:
    with _fixture() as (index, inventory, expected, head_ids, audit):
        with _builder_patches(expected, head_ids, audit) as binding:
            plan = builder.build_historical_spread_time_adjudication_plan(
                index,
                inventory,
            )

        assert binding.call_count == 34
        assert len(plan.requests) == 26
        assert len(plan.excluded_rich_v2_completion_ids) == 8
        assert len(plan.family(builder.P0_REPLAY_FAMILY_ID).members) == 2
        assert len(plan.family(builder.P1_REPLAY_FAMILY_ID).members) == 23
        assert len(plan.family(builder.NOT_EVALUABLE_FAMILY_ID).members) == 1
        assert {
            item.request.replay_priority
            for item in plan.family(builder.P0_REPLAY_FAMILY_ID).members
        } == {ReplayPriority.P0}
        assert {
            item.request.replay_priority
            for item in plan.family(builder.P1_REPLAY_FAMILY_ID).members
        } == {ReplayPriority.P1}

        not_evaluable = plan.family(builder.NOT_EVALUABLE_FAMILY_ID).members[0]
        assert not_evaluable.completion_record_id == builder.NOT_EVALUABLE_COMPLETION_ID
        assert (
            not_evaluable.request.disposition
            is HistoricalDisposition.NOT_EVALUABLE_QUALIFICATION
        )
        assert not_evaluable.request.replay_priority is ReplayPriority.NONE
        assert [item.reason for item in not_evaluable.request.validity_overrides] == [
            HistoricalValidityReason.DECISION_INPUT_POINT_IN_TIME_UNPROVEN,
            HistoricalValidityReason.SOURCE_AUTHORITY_INVALIDATED,
        ]
        assert all(len(item.negative_memory_ids) == 1 for item in plan.members)
        assert all(
            len(item.request.validity_overrides) == 1
            for item in plan.members
            if item.completion_record_id != builder.NOT_EVALUABLE_COMPLETION_ID
        )
        assert all(
            item.replay_obligation_id is not None
            and item.accepted_satisfaction_record_id is not None
            and item.prior_replay_obligation_priority is ReplayPriority.P1
            for item in plan.family(builder.P0_REPLAY_FAMILY_ID).members
        )
        assert len(
            plan.family(builder.P0_REPLAY_FAMILY_ID)
            .to_manifest_payload()["priority_transitions"]
        ) == 2

        manifest = plan.to_request_manifest_payload()
        assert manifest["request_count"] == 26
        assert manifest["negative_memory_count"] == 26
        assert manifest["negative_memory_role"] == "diagnostic_only"
        assert plan.request_manifest_digest == builder.canonical_digest(
            domain=(
                "historical-spread-time-adjudication-supersession-manifest"
            ),
            payload=manifest,
        )


def test_fails_closed_on_typed_inventory_or_current_head_drift() -> None:
    with _fixture() as (index, inventory, expected, head_ids, audit):
        changed = replace(
            inventory.invalidations[0],
            affected_claim_ids=("changed_claim",),
            audit_slice_digest=None,
        )
        drifted = HistoricalSpreadTimeInvalidationInventory(
            audit_artifact_hash=inventory.audit_artifact_hash,
            study_contexts=inventory.study_contexts,
            invalidations=(changed, *inventory.invalidations[1:]),
        )
        with _builder_patches(expected, head_ids, audit):
            with pytest.raises(
                builder.HistoricalSpreadTimeAdjudicationBuilderError,
                match="inventory drifted",
            ):
                builder.build_historical_spread_time_adjudication_plan(
                    index,
                    drifted,
                )

        first = next(
            item
            for item in inventory.invalidations
            if item.study_id not in {"STU-0107", "STU-0108"}
        )
        prior_head = index.event_head(
            f"historical-adjudication:{first.completion_record_id}"
        )
        assert prior_head is not None
        prior = index.get(prior_head.record_kind, prior_head.record_id)
        assert prior is not None
        index.put_many(
            (
                IndexRecord(
                    kind=prior.kind,
                    record_id="historical-adjudication:" + _digest("drifted-head"),
                    subject=prior.subject,
                    status=prior.status,
                    fingerprint=_digest("drifted-head"),
                    payload={
                        **prior.payload,
                        "supersedes_record_id": prior.record_id,
                    },
                    event_stream=prior.event_stream,
                    event_sequence=2,
                ),
            )
        )
        with _builder_patches(expected, head_ids, audit):
            with pytest.raises(
                builder.HistoricalSpreadTimeAdjudicationBuilderError,
                match="stale or malformed",
            ):
                builder.build_historical_spread_time_adjudication_plan(
                    index,
                    inventory,
                )


def test_fails_closed_on_forged_prior_timing_override() -> None:
    with _fixture(forged_timing_override=True) as (
        index,
        inventory,
        expected,
        head_ids,
        audit,
    ):
        with _builder_patches(expected, head_ids, audit):
            with pytest.raises(
                builder.HistoricalSpreadTimeAdjudicationBuilderError,
                match="prior timing override",
            ):
                builder.build_historical_spread_time_adjudication_plan(
                    index,
                    inventory,
                )
