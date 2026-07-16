from __future__ import annotations

from dataclasses import replace
import inspect
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import axiom_rift.operations.historical_cost_semantics_reader as cost_reader_module

from axiom_rift.operations.axis_disposition import (
    aggregate_axis_evidence_state,
    derive_axis_evidence_binding,
)
from axiom_rift.operations.effective_axis_projection import (
    effective_axis_resolution,
)
from axiom_rift.operations.evidence_scope_projection import (
    EvidenceScopeProjectionError,
    effective_completion_evidence_scope,
)
from axiom_rift.operations.historical_cost_semantics_common import (
    COMPLETION_SCOPE_RECORD_KIND,
    HistoricalCostSemanticsProjectionError,
)
from axiom_rift.operations.historical_cost_semantics_projection import (
    HistoricalSpreadCompletionMember,
    historical_cost_semantics_completion_record,
    historical_cost_semantics_latch_record,
)
from axiom_rift.operations.historical_cost_semantics_reader import (
    current_historical_cost_semantics_activation,
    effective_historical_completion_cost_authority,
    effective_historical_negative_memory_cost_authority,
    qualify_historical_cost_claim,
    qualify_historical_cost_criterion,
)
from axiom_rift.operations.study_close_delivery import StudyCloseGuardCapability
from axiom_rift.operations.writer import StateWriter, TransitionError
from axiom_rift.research.axis_disposition import (
    AxisDisposition,
    AxisDispositionAction,
    AxisEvidenceKind,
    AxisEvidenceReference,
    AxisEvidenceState,
)
from axiom_rift.research.effective_axis import (
    AxisReopenAuthority,
    EffectiveAxisStatus,
    axis_reopen_evidence,
)
from axiom_rift.research.historical_cost_semantics import (
    AUTHORITY_DELTA_ZERO,
    CAUSAL_INVALID_COMPLETION_IDS,
    CAUSAL_INVALID_STUDY_CONTEXT_IDS,
    EXCEPTIONAL_STUDY_CLASSES,
    GOLDEN_CLASS_COMPLETION_SEALS,
    GOLDEN_INVENTORY_SEALS,
    HistoricalCostInterpretation,
    HistoricalCostQualificationState,
    HistoricalCostSemanticCriterion,
    HistoricalCostSemanticsLatch,
    HistoricalSpreadSemanticClass,
    HistoricalSpreadSemanticsAuditManifest,
    PRODUCTION_UPPER_CURSOR,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


MISSION_ID = "MIS-COST-CONSUMPTION"
AXIS_ID = "AX-COST-CONSUMPTION"
AXIS_IDENTITY = "axis:" + "6" * 64
STUDY_ID = "STU-COST-CONSUMPTION"
EXECUTABLE_ID = "executable:" + "7" * 64
JOB_ID = "job:" + "8" * 64
COMPLETION_ID = "9" * 64
NEGATIVE_MEMORY_ID = "negative-memory:" + "a" * 64
LATCH_EVENT_ID = "e" * 64
LATCH_SEQUENCE = PRODUCTION_UPPER_CURSOR.sequence + 1
LATCH_OFFSET = PRODUCTION_UPPER_CURSOR.offset + 1_000
PORTFOLIO_ID = "portfolio:" + "d" * 64


def _record(
    *,
    kind: str,
    record_id: str,
    payload: dict[str, object],
    sequence: int,
    subject: str,
    status: str,
    fingerprint: str,
    event_id: str | None = None,
    offset: int | None = None,
    event_stream: str | None = None,
    event_sequence: int | None = None,
) -> IndexRecord:
    return IndexRecord(
        kind=kind,
        record_id=record_id,
        subject=subject,
        status=status,
        fingerprint=fingerprint,
        payload=payload,
        event_stream=event_stream,
        event_sequence=event_sequence,
        authority_sequence=sequence,
        authority_event_id=event_id or f"{sequence:064x}",
        authority_offset=sequence * 100 if offset is None else offset,
    )


def _manifest() -> HistoricalSpreadSemanticsAuditManifest:
    return HistoricalSpreadSemanticsAuditManifest(
        audit_artifact_hash="b" * 64,
        upper_authority_cursor=PRODUCTION_UPPER_CURSOR,
        causal_invalid_completion_ids=CAUSAL_INVALID_COMPLETION_IDS,
        causal_invalid_study_context_ids=CAUSAL_INVALID_STUDY_CONTEXT_IDS,
        audited_cost_contracts=("cost:completed_bar_spread_proxy_v1",),
        exceptional_study_classes=tuple(
            sorted(
                EXCEPTIONAL_STUDY_CLASSES.items(),
                key=lambda item: item[0].value,
            )
        ),
        inventory_seals=GOLDEN_INVENTORY_SEALS,
        class_completion_seals=GOLDEN_CLASS_COMPLETION_SEALS,
    )


def _base_records() -> tuple[IndexRecord, ...]:
    modes = ["cost_and_execution", "gross_mechanism"]
    study = _record(
        kind="study-open",
        record_id=STUDY_ID,
        payload={
            "mission_id": MISSION_ID,
            "portfolio_axis_id": AXIS_ID,
            "portfolio_axis_identity": AXIS_IDENTITY,
        },
        sequence=10,
        subject=f"Study:{STUDY_ID}",
        status="open",
        fingerprint="1" * 64,
    )
    trial = _record(
        kind="trial",
        record_id=EXECUTABLE_ID,
        payload={
            "executable": {
                "cost_contract": "cost:completed_bar_spread_proxy_v1",
                "source_contracts": [],
            },
            "mission_id": MISSION_ID,
            "portfolio_axis_id": AXIS_ID,
            "portfolio_axis_identity": AXIS_IDENTITY,
            "study_id": STUDY_ID,
        },
        sequence=11,
        subject="Batch:BAT-COST-CONSUMPTION",
        status="evaluated",
        fingerprint=EXECUTABLE_ID.removeprefix("executable:"),
    )
    declaration = _record(
        kind="job-declared",
        record_id=JOB_ID,
        payload={
            "mission_id": MISSION_ID,
            "spec": {
                "evidence_subject": {
                    "id": EXECUTABLE_ID,
                    "kind": "Executable",
                }
            },
            "study_id": STUDY_ID,
        },
        sequence=12,
        subject=f"Job:{JOB_ID}",
        status="declared",
        fingerprint="2" * 64,
    )
    completion = _record(
        kind="job-completed",
        record_id=COMPLETION_ID,
        payload={
            "job_id": JOB_ID,
            "scientific": {
                "adjudication": {
                    "candidate_eligible": False,
                    "invalid_metrics": [],
                    "schema": "scientific_adjudication.v1",
                    "state": "contradicted",
                },
                "candidate_eligible": False,
                "claims": [
                    "after_cost_fixed_lot_economics",
                    "causal_feature_and_execution_validity",
                ],
                "executed_evidence_modes": modes,
                "executable_id": EXECUTABLE_ID,
                "scientific_eligible": True,
                "verdict": "failed",
            },
        },
        sequence=13,
        subject=f"Job:{JOB_ID}",
        status="success",
        fingerprint="3" * 64,
    )
    memory = _record(
        kind="negative-memory",
        record_id=NEGATIVE_MEMORY_ID,
        payload={
            "evidence_references": [COMPLETION_ID],
            "executed_evidence_modes": modes,
            "mission_id": MISSION_ID,
            "portfolio_axis_id": AXIS_ID,
            "portfolio_axis_identity": AXIS_IDENTITY,
            "study_id": STUDY_ID,
        },
        sequence=14,
        subject=f"Executable:{EXECUTABLE_ID}",
        status="durable",
        fingerprint="4" * 64,
    )
    return study, trial, declaration, completion, memory


def _activation_records(
    *,
    omit_scope: bool = False,
    malformed_scope: bool = False,
    malformed_latch: bool = False,
) -> tuple[IndexRecord, ...]:
    manifest = _manifest()
    latch = HistoricalCostSemanticsLatch.from_audit_manifest(manifest)
    member = HistoricalSpreadCompletionMember(
        completion_record_id=COMPLETION_ID,
        job_id=JOB_ID,
        job_declaration_record_id=JOB_ID,
        executable_id=EXECUTABLE_ID,
        trial_record_id=EXECUTABLE_ID,
        completion_study_id=STUDY_ID,
        registration_study_id=STUDY_ID,
        cost_contract="cost:completed_bar_spread_proxy_v1",
        semantic_class=(
            HistoricalSpreadSemanticClass.EXECUTION_COST_MEASUREMENT_ONLY
        ),
        scientific=True,
        claim_ids=("after_cost_fixed_lot_economics",),
        criterion_bindings=(),
        adjudication_record_ids=(),
        negative_memory_ids=(NEGATIVE_MEMORY_ID,),
        authority_sequence=13,
        authority_event_id=f"{13:064x}",
        authority_offset=1_300,
    )
    latch_record = replace(
        historical_cost_semantics_latch_record(latch),
        authority_sequence=LATCH_SEQUENCE,
        authority_event_id=LATCH_EVENT_ID,
        authority_offset=LATCH_OFFSET,
    )
    if malformed_latch:
        latch_record = replace(
            latch_record,
            payload={"schema": "malformed"},
        )
    scope_record = replace(
        historical_cost_semantics_completion_record(latch, member),
        authority_sequence=LATCH_SEQUENCE,
        authority_event_id=LATCH_EVENT_ID,
        authority_offset=LATCH_OFFSET,
    )
    if malformed_scope:
        scope_record = replace(
            scope_record,
            payload={**scope_record.payload, "study_id": "STU-WRONG"},
        )
    result = {
        "audit_manifest_hash": latch.audit_manifest_hash,
        "authority_delta": dict(AUTHORITY_DELTA_ZERO),
        "latch_record_id": latch.identity,
    }
    operation = _record(
        kind="operation",
        record_id="record-historical-cost-semantics-fixture",
        payload={
            "event_kind": "historical_cost_semantics_latch_recorded",
            "result": result,
        },
        sequence=LATCH_SEQUENCE,
        event_id=LATCH_EVENT_ID,
        offset=LATCH_OFFSET,
        subject="ProjectGoal:OPERATING_DIRECTION.md",
        status="success",
        fingerprint="5" * 64,
    )
    journal = _record(
        kind="journal-event",
        record_id=LATCH_EVENT_ID,
        payload={"operation_id": operation.record_id},
        sequence=LATCH_SEQUENCE,
        event_id=LATCH_EVENT_ID,
        offset=LATCH_OFFSET,
        event_stream="control",
        event_sequence=LATCH_SEQUENCE,
        subject="ProjectGoal:OPERATING_DIRECTION.md",
        status="historical_cost_semantics_latch_recorded",
        fingerprint="6" * 64,
    )
    projected = () if omit_scope else (scope_record,)
    return latch_record, *projected, operation, journal


def _noise_records(count: int) -> tuple[IndexRecord, ...]:
    records = []
    for ordinal in range(count):
        token = ordinal + 1_000
        records.append(
            _record(
                kind="job-completed",
                record_id=f"{token:064x}",
                payload={
                    "scientific": {
                        "executable_id": "executable:" + f"{token:064x}"
                    }
                },
                sequence=LATCH_SEQUENCE + 1 + ordinal,
                subject=f"Job:noise-{ordinal}",
                status="success",
                fingerprint=f"{token + 10_000:064x}",
            )
        )
    return tuple(records)


def _portfolio_record() -> IndexRecord:
    return _record(
        kind="portfolio-snapshot",
        record_id=PORTFOLIO_ID,
        payload={
            "axes": [
                {
                    "axis_id": AXIS_ID,
                    "axis_identity": AXIS_IDENTITY,
                    "mechanism_family": "cost-consumption",
                    "primary_research_layer": "execution",
                    "status": "pruned",
                    "system_architecture_family": "architecture-family:cost",
                },
                {
                    "axis_id": "AX-UNRELATED",
                    "axis_identity": "axis:" + "5" * 64,
                    "mechanism_family": "unrelated-control",
                    "primary_research_layer": "feature",
                    "status": "open",
                    "system_architecture_family": "architecture-family:control",
                },
            ],
            "exhaustion_standard": {},
            "mission_id": MISSION_ID,
            "schema": "portfolio_snapshot.v3",
        },
        sequence=15,
        subject=f"Mission:{MISSION_ID}",
        status="current",
        fingerprint=PORTFOLIO_ID.removeprefix("portfolio:"),
        event_stream=f"portfolio:{MISSION_ID}",
        event_sequence=1,
    )


class HistoricalCostSemanticsConsumptionTests(unittest.TestCase):
    def test_preactivation_absence_is_compatible(self) -> None:
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                index.put_many(_base_records())
                completion = index.get("job-completed", COMPLETION_ID)
                assert completion is not None
                self.assertIsNone(
                    current_historical_cost_semantics_activation(index)
                )
                self.assertIsNone(
                    effective_historical_completion_cost_authority(
                        index,
                        completion,
                    )
                )
                scope = effective_completion_evidence_scope(index, completion)
                self.assertEqual(scope.economic_credit, 1)
                self.assertEqual(scope.terminal_credit, 1)
                self.assertTrue(scope.negative_memory_authoritative)

    def test_cost_negative_is_unresolved_for_architecture_and_blocks_exhaustion_terminal(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                index.put_many((*_base_records(), *_activation_records()))
                completion = index.get("job-completed", COMPLETION_ID)
                assert completion is not None
                authority = effective_historical_completion_cost_authority(
                    index,
                    completion,
                )
                assert authority is not None
                self.assertEqual(authority.candidate_credit, 0)
                self.assertEqual(authority.economic_credit, 0)
                self.assertFalse(authority.negative_memory_authoritative)

                scope = effective_completion_evidence_scope(index, completion)
                self.assertEqual(
                    scope.evidence_modes,
                    ("completed_period_proxy_cost", "gross_mechanism"),
                )
                self.assertEqual(scope.scientific_credit, 1)
                self.assertEqual(scope.economic_credit, 0)
                self.assertEqual(scope.candidate_credit, 0)
                self.assertEqual(scope.terminal_credit, 0)
                self.assertFalse(scope.negative_memory_authoritative)
                self.assertEqual(scope.negative_memory_role, "diagnostic_only")
                self.assertIn(
                    "gross_mechanism",
                    scope.preserved_independent_scopes,
                )

                actual = qualify_historical_cost_claim(
                    index,
                    completion_record_id=COMPLETION_ID,
                    claim_id="after_cost_fixed_lot_economics",
                    interpretation=(
                        HistoricalCostInterpretation.
                        ACTUAL_POINT_IN_TIME_NATIVE_QUOTE
                    ),
                )
                assert actual is not None
                self.assertIs(
                    actual.state,
                    HistoricalCostQualificationState.UNRESOLVED,
                )
                independent = qualify_historical_cost_claim(
                    index,
                    completion_record_id=COMPLETION_ID,
                    claim_id="gross_mechanism",
                    interpretation=(
                        HistoricalCostInterpretation.
                        ACTUAL_POINT_IN_TIME_NATIVE_QUOTE
                    ),
                )
                assert independent is not None
                self.assertIs(
                    independent.state,
                    HistoricalCostQualificationState.PRESERVED_INDEPENDENT,
                )
                proxy = qualify_historical_cost_criterion(
                    index,
                    completion_record_id=COMPLETION_ID,
                    criterion=(
                        HistoricalCostSemanticCriterion.
                        C01_POSITIVE_REPORTED_COST
                    ),
                    interpretation=(
                        HistoricalCostInterpretation.COMPLETED_PERIOD_PROXY
                    ),
                )
                assert proxy is not None
                self.assertIs(
                    proxy.state,
                    HistoricalCostQualificationState.
                    PRESERVED_EXACT_PROXY_ONLY,
                )

                memory = effective_historical_negative_memory_cost_authority(
                    index,
                    NEGATIVE_MEMORY_ID,
                )
                assert memory is not None
                self.assertEqual(memory.prune_credit, 0)
                self.assertEqual(memory.exhaustion_credit, 0)
                self.assertEqual(memory.terminal_credit, 0)
                binding = derive_axis_evidence_binding(
                    index,
                    reference=AxisEvidenceReference(
                        kind=AxisEvidenceKind.NEGATIVE_MEMORY,
                        record_id=NEGATIVE_MEMORY_ID,
                    ),
                    mission_id=MISSION_ID,
                    axis_id=AXIS_ID,
                    axis_identity=AXIS_IDENTITY,
                )
                self.assertIs(binding.state, AxisEvidenceState.UNRESOLVED)
                self.assertIs(
                    aggregate_axis_evidence_state((binding,)),
                    AxisEvidenceState.UNRESOLVED,
                )
                self.assertEqual(
                    binding.evidence_modes,
                    ("completed_period_proxy_cost", "gross_mechanism"),
                )

                axis = {
                    "axis_id": AXIS_ID,
                    "axis_identity": AXIS_IDENTITY,
                    "status": "pruned",
                }
                resolution = effective_axis_resolution(index, axis)
                self.assertIs(
                    resolution.effective_status,
                    EffectiveAxisStatus.DEFERRED_REQUIRES_REOPEN,
                )
                self.assertFalse(resolution.selectable)
                self.assertTrue(resolution.requires_reopen)
                self.assertFalse(resolution.terminal_eligible)
                self.assertTrue(resolution.decision_option_eligible)
                writer_resolution = StateWriter._effective_axis_resolutions(
                    index,
                    (axis,),
                )[0]
                self.assertEqual(writer_resolution, resolution)
                self.assertFalse(writer_resolution.terminal_eligible)
                reopen = axis_reopen_evidence(resolution)
                self.assertEqual(
                    reopen.historical_cost_completion_ids,
                    (COMPLETION_ID,),
                )
                self.assertEqual(
                    reopen.historical_cost_negative_memory_ids,
                    (NEGATIVE_MEMORY_ID,),
                )
                self.assertEqual(reopen.replay_resolution_record_ids, ())
                authority_record = AxisReopenAuthority(
                    mission_id=MISSION_ID,
                    portfolio_snapshot_id="portfolio:" + "b" * 64,
                    portfolio_decision_id="decision:" + "c" * 64,
                    axis_id=AXIS_ID,
                    axis_identity=AXIS_IDENTITY,
                    replay_resolution_record_ids=(
                        reopen.replay_resolution_record_ids
                    ),
                    evidence_scope_overlay_ids=(
                        reopen.evidence_scope_overlay_ids
                    ),
                    historical_cost_completion_ids=(
                        reopen.historical_cost_completion_ids
                    ),
                    historical_cost_latch_ids=(
                        reopen.historical_cost_latch_ids
                    ),
                    historical_cost_negative_memory_ids=(
                        reopen.historical_cost_negative_memory_ids
                    ),
                )
                self.assertEqual(
                    authority_record.to_identity_payload()[
                        "historical_cost_completion_ids"
                    ],
                    [COMPLETION_ID],
                )

    def test_cost_only_negative_cannot_cross_writer_terminal_boundaries(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            writer = StateWriter(
                Path(temporary) / "writer",
                clock=lambda: "2026-07-16T00:00:00Z",
                study_close_guard_capability=(
                    StudyCloseGuardCapability.ISOLATED_ENGINEERING_FIXTURE
                ),
                foundation_root=Path(__file__).resolve().parents[2],
            )
            writer.initialize_ready()
            writer.open_mission(
                mission_id=MISSION_ID,
                goal={
                    "objective": "prove historical cost terminal containment",
                    "scope": ["isolated", "writer-boundary"],
                    "terminal_contract": "no_scientific_terminal",
                },
                operation_id="cost-terminal-open-mission",
            )

            def seed_research_boundary(current, _index):
                assert current is not None
                body = writer._body(current)
                body["next_action"] = {
                    "kind": "choose_next_initiative_or_terminal",
                    "mission_id": MISSION_ID,
                }
                return body, [*_base_records(), _portfolio_record()], {
                    "trial_delta": 0
                }

            writer._commit(
                event_kind="research_intake_recorded",
                operation_id="cost-terminal-seed-research-boundary",
                subject=f"Mission:{MISSION_ID}",
                payload={"trial_delta": 0},
                prepare=seed_research_boundary,
            )
            latch_record, scope_record, *_ = _activation_records()
            latch = HistoricalCostSemanticsLatch.from_audit_manifest(_manifest())
            latch_result = {
                "audit_manifest_hash": latch.audit_manifest_hash,
                "authority_delta": dict(AUTHORITY_DELTA_ZERO),
                "latch_record_id": latch.identity,
            }

            def seed_cost_activation(current, _index):
                assert current is not None
                return writer._body(current), [latch_record, scope_record], latch_result

            writer._commit(
                event_kind="historical_cost_semantics_latch_recorded",
                operation_id="cost-terminal-seed-activation",
                subject="ProjectGoal:OPERATING_DIRECTION.md",
                payload={"trial_delta": 0},
                prepare=seed_cost_activation,
            )
            disposition = AxisDisposition(
                mission_id=MISSION_ID,
                portfolio_snapshot_id=PORTFOLIO_ID,
                axis_id=AXIS_ID,
                axis_identity=AXIS_IDENTITY,
                evidence_state=AxisEvidenceState.UNRESOLVED,
                action=AxisDispositionAction.DEFER,
                evidence_references=(
                    AxisEvidenceReference(
                        kind=AxisEvidenceKind.NEGATIVE_MEMORY,
                        record_id=NEGATIVE_MEMORY_ID,
                    ),
                ),
                reason_codes=("historical_cost_semantics_unresolved",),
                rationale="actual point-in-time native cost was not measured",
                continuation_or_reopen_condition=(
                    "reopen with timestamped quote or execution evidence"
                ),
            )
            lower_test_cursor = replace(PRODUCTION_UPPER_CURSOR, sequence=1)
            with patch.object(
                cost_reader_module,
                "PRODUCTION_UPPER_CURSOR",
                lower_test_cursor,
            ):
                with self.assertRaisesRegex(
                    TransitionError,
                    "axis disposition cannot interpret",
                ):
                    writer.record_axis_dispositions(
                        dispositions=(disposition,),
                        operation_id="reject-cost-only-axis-disposition",
                    )
                with self.assertRaisesRegex(
                    TransitionError,
                    "exhaustion cannot bypass unresolved",
                ):
                    writer.accept_exhaustion_audit(
                        frontiers={
                            AXIS_ID: (
                                {
                                    "kind": "negative-memory",
                                    "record_id": NEGATIVE_MEMORY_ID,
                                },
                            )
                        },
                        diversity_basis="cost-only negatives are diagnostic",
                        opportunity_cost_audit="the branch must be reopened",
                        operation_id="reject-cost-only-exhaustion",
                    )

                exhaustion_id = "f" * 64

                def seed_pending_terminal(current, _index):
                    assert current is not None
                    body = writer._body(current)
                    body["next_action"] = {
                        "basis_record_id": exhaustion_id,
                        "kind": "close_mission",
                        "outcome": "closed_no_candidate",
                    }
                    basis = _record(
                        kind="exhaustion-audit",
                        record_id=exhaustion_id,
                        payload={"portfolio_snapshot_id": PORTFOLIO_ID},
                        sequence=16,
                        subject=f"Mission:{MISSION_ID}",
                        status="accepted",
                        fingerprint=exhaustion_id,
                    )
                    return body, [basis], {"basis_record_id": exhaustion_id}

                writer._commit(
                    event_kind="exhaustion_audit_accepted",
                    operation_id="cost-terminal-seed-pending-close",
                    subject=f"Mission:{MISSION_ID}",
                    payload={"trial_delta": 0},
                    prepare=seed_pending_terminal,
                )
                with self.assertRaisesRegex(
                    TransitionError,
                    "Mission terminal cannot bypass unresolved Portfolio axis",
                ):
                    writer.close_mission(
                        outcome="closed_no_candidate",
                        basis_record_id=exhaustion_id,
                        operation_id="reject-cost-only-mission-terminal",
                    )

    def test_malformed_or_incomplete_activated_projection_fails_closed(self) -> None:
        for option, message in (
            ({"omit_scope": True}, "lacks a required keyed completion"),
            ({"malformed_scope": True}, "not same-event canonical"),
            ({"malformed_latch": True}, "head payload is malformed"),
        ):
            with self.subTest(option=option):
                with TemporaryDirectory() as temporary:
                    with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                        index.put_many(
                            (*_base_records(), *_activation_records(**option))
                        )
                        completion = index.get("job-completed", COMPLETION_ID)
                        assert completion is not None
                        with self.assertRaisesRegex(
                            HistoricalCostSemanticsProjectionError,
                            message,
                        ):
                            effective_historical_completion_cost_authority(
                                index,
                                completion,
                            )
                        with self.assertRaises(EvidenceScopeProjectionError):
                            effective_completion_evidence_scope(
                                index,
                                completion,
                            )

    def test_large_history_routine_consumers_use_only_keyed_queries(self) -> None:
        reader_source = inspect.getsource(cost_reader_module)
        self.assertNotIn(
            "historical_cost_semantics_projection",
            reader_source,
        )
        self.assertNotIn(".records_by_kind(", reader_source)
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                index.put_many(
                    (
                        *_base_records(),
                        *_activation_records(),
                        *_noise_records(1_000),
                    )
                )
                completion = index.get("job-completed", COMPLETION_ID)
                assert completion is not None
                axis = {
                    "axis_id": AXIS_ID,
                    "axis_identity": AXIS_IDENTITY,
                    "status": "pruned",
                }
                with patch.object(
                    index,
                    "records_by_kind",
                    side_effect=AssertionError("routine full-history scan"),
                ):
                    effective_historical_completion_cost_authority(
                        index,
                        completion,
                    )
                    effective_historical_negative_memory_cost_authority(
                        index,
                        NEGATIVE_MEMORY_ID,
                    )
                    effective_completion_evidence_scope(index, completion)
                    effective_axis_resolution(index, axis)
                record_shape = index.hot_query_access_shape(
                    "record_by_key",
                    (COMPLETION_SCOPE_RECORD_KIND, COMPLETION_ID),
                )
                head_shape = index.hot_query_access_shape(
                    "event_head_by_stream",
                    ("historical-cost-semantics:completed-period-spread",),
                )
                operation_shape = (
                    index.records_by_kind_at_authority_sequence_access_shape(
                        "operation",
                        LATCH_SEQUENCE,
                    )
                )
                completion_shape = (
                    index.records_by_payload_text_values_access_shape(
                        "job-completed",
                        "scientific_executable_id",
                        (EXECUTABLE_ID,),
                    )
                )
                for shape in (
                    record_shape,
                    head_shape,
                    operation_shape,
                    completion_shape,
                ):
                    self.assertTrue(any("SEARCH" in detail for detail in shape))
                    self.assertFalse(
                        any(detail.startswith("SCAN records") for detail in shape)
                    )


if __name__ == "__main__":
    unittest.main()
