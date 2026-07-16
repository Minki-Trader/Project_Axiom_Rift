from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.operations.historical_cost_semantics_projection import (
    HistoricalCostSemanticsProjectionError,
    HistoricalSpreadSemanticsProjection,
    current_historical_cost_semantics_latch,
    derive_historical_spread_semantics_audit_slice,
    historical_cost_semantics_latch_record,
)
from axiom_rift.research.historical_cost_semantics import (
    CAUSAL_INVALID_COMPLETION_IDS,
    CAUSAL_INVALID_STUDY_CONTEXT_IDS,
    EXCEPTIONAL_STUDY_CLASSES,
    GOLDEN_CLASS_COMPLETION_SEALS,
    GOLDEN_INVENTORY_SEALS,
    HistoricalAuthorityCursor,
    HistoricalCostInterpretation,
    HistoricalCostQualificationState,
    HistoricalCostSemanticCriterion,
    HistoricalCostSemanticsLatch,
    HistoricalSpreadSemanticClass,
    HistoricalSpreadSemanticsAuditManifest,
    PRODUCTION_UPPER_CURSOR,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


BOUNDARY_EVENT_ID = "f" * 64
UPPER_CURSOR = HistoricalAuthorityCursor(
    sequence=100,
    event_id=BOUNDARY_EVENT_ID,
    offset=1_000,
)
EXECUTABLE_73 = "executable:" + "7" * 64
EXECUTABLE_103 = "executable:" + "8" * 64
FUTURE_EXECUTABLE = "executable:" + "9" * 64
JOB_83 = "job:" + "a" * 64
JOB_103 = "job:" + "b" * 64
JOB_104 = "job:" + "c" * 64
FUTURE_JOB = "job:" + "d" * 64
COMPLETION_83 = "1" * 64
COMPLETION_103 = "2" * 64
COMPLETION_104 = "3" * 64
FUTURE_COMPLETION = "4" * 64


def _record(
    *,
    kind: str,
    record_id: str,
    sequence: int,
    payload: dict[str, object],
    subject: str = "Mission:MIS-FIXTURE",
    status: str = "recorded",
    event_id: str | None = None,
    offset: int | None = None,
    event_stream: str | None = None,
    event_sequence: int | None = None,
) -> IndexRecord:
    authority_event_id = event_id or f"{sequence:064x}"
    return IndexRecord(
        kind=kind,
        record_id=record_id,
        subject=subject,
        status=status,
        fingerprint=f"{sequence + 2_000:064x}",
        payload=payload,
        event_stream=event_stream,
        event_sequence=event_sequence,
        authority_sequence=sequence,
        authority_event_id=authority_event_id,
        authority_offset=sequence * 10 if offset is None else offset,
    )


def _study_open(study_id: str, sequence: int) -> tuple[IndexRecord, IndexRecord]:
    event_id = f"{sequence:064x}"
    return (
        _record(
            kind="study-open",
            record_id=study_id,
            sequence=sequence,
            event_id=event_id,
            payload={"mission_id": "MIS-FIXTURE"},
            subject=f"Study:{study_id}",
            status="open",
        ),
        _record(
            kind="operation",
            record_id=f"operation-open-{study_id}",
            sequence=sequence,
            event_id=event_id,
            payload={
                "event_kind": "study_opened",
                "result": {"study_id": study_id},
            },
        ),
    )


def _trial(executable_id: str, study_id: str, sequence: int) -> IndexRecord:
    return _record(
        kind="trial",
        record_id=executable_id,
        sequence=sequence,
        payload={
            "study_id": study_id,
            "executable": {
                "cost_contract": "cost:completed_bar_spread_proxy_v1",
            },
        },
        subject="Batch:BAT-FIXTURE",
        status="evaluated",
    )


def _job_declaration(
    job_id: str,
    executable_id: str,
    study_id: str,
    sequence: int,
) -> IndexRecord:
    return _record(
        kind="job-declared",
        record_id=job_id,
        sequence=sequence,
        payload={
            "study_id": study_id,
            "spec": {
                "evidence_subject": {
                    "kind": "Executable",
                    "id": executable_id,
                },
            },
        },
        subject=f"Job:{job_id}",
        status="declared",
    )


def _completion(
    completion_id: str,
    job_id: str,
    executable_id: str,
    sequence: int,
    *,
    scientific: bool,
) -> IndexRecord:
    payload: dict[str, object] = {"job_id": job_id}
    if scientific:
        payload["scientific"] = {
            "claims": ["after_cost_fixed_lot_economics"],
            "executable_id": executable_id,
        }
    return _record(
        kind="job-completed",
        record_id=completion_id,
        sequence=sequence,
        payload=payload,
        subject=f"Job:{job_id}",
        status="success",
    )


def _fixture_records() -> tuple[IndexRecord, ...]:
    studies: list[IndexRecord] = []
    for sequence, study_id in enumerate(
        ("STU-0073", "STU-0083", "STU-0103", "STU-0104"),
        start=10,
    ):
        studies.extend(_study_open(study_id, sequence))
    boundary = _record(
        kind="journal-event",
        record_id=BOUNDARY_EVENT_ID,
        sequence=UPPER_CURSOR.sequence,
        event_id=UPPER_CURSOR.event_id,
        offset=UPPER_CURSOR.offset,
        payload={"operation_id": "fixture-boundary"},
        event_stream="control",
        event_sequence=UPPER_CURSOR.sequence,
        status="fixture_boundary",
    )
    return (
        *studies,
        _trial(EXECUTABLE_73, "STU-0073", 20),
        _trial(EXECUTABLE_103, "STU-0103", 21),
        _job_declaration(JOB_83, EXECUTABLE_73, "STU-0083", 30),
        _completion(
            COMPLETION_83,
            JOB_83,
            EXECUTABLE_73,
            31,
            scientific=True,
        ),
        _job_declaration(JOB_103, EXECUTABLE_103, "STU-0103", 32),
        _completion(
            COMPLETION_103,
            JOB_103,
            EXECUTABLE_103,
            33,
            scientific=False,
        ),
        _job_declaration(JOB_104, EXECUTABLE_103, "STU-0104", 34),
        _completion(
            COMPLETION_104,
            JOB_104,
            EXECUTABLE_103,
            35,
            scientific=True,
        ),
        boundary,
        _trial(FUTURE_EXECUTABLE, "STU-0200", 101),
        _job_declaration(FUTURE_JOB, FUTURE_EXECUTABLE, "STU-0200", 101),
        _completion(
            FUTURE_COMPLETION,
            FUTURE_JOB,
            FUTURE_EXECUTABLE,
            101,
            scientific=True,
        ),
    )


def _derive(index: LocalIndex):
    return derive_historical_spread_semantics_audit_slice(
        index,
        upper_authority_cursor=UPPER_CURSOR,
        causal_invalid_completion_ids=(),
        causal_invalid_study_context_ids=(),
        exceptional_study_classes={
            HistoricalSpreadSemanticClass.CAUSAL_POLICY_COST_STATE_DEPENDENT: (
                "STU-0083",
            ),
            HistoricalSpreadSemanticClass.NATIVE_COST_OUTCOME_LABEL_ONLY: (
                "STU-0104",
            ),
        },
    )


def _production_manifest() -> HistoricalSpreadSemanticsAuditManifest:
    return HistoricalSpreadSemanticsAuditManifest(
        audit_artifact_hash="a" * 64,
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


class HistoricalCostSemanticsProjectionTests(unittest.TestCase):
    def test_cross_study_membership_uses_completion_declaration_and_is_bounded(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                index.put_many(_fixture_records())
                audit_slice = _derive(index)

        members = {
            item.completion_record_id: item for item in audit_slice.members
        }
        self.assertEqual(set(members), {COMPLETION_83, COMPLETION_103, COMPLETION_104})
        self.assertEqual(members[COMPLETION_83].registration_study_id, "STU-0073")
        self.assertEqual(members[COMPLETION_83].completion_study_id, "STU-0083")
        self.assertEqual(
            members[COMPLETION_83].semantic_class,
            HistoricalSpreadSemanticClass.CAUSAL_POLICY_COST_STATE_DEPENDENT,
        )
        self.assertEqual(members[COMPLETION_104].registration_study_id, "STU-0103")
        self.assertEqual(members[COMPLETION_104].completion_study_id, "STU-0104")
        self.assertEqual(
            members[COMPLETION_104].semantic_class,
            HistoricalSpreadSemanticClass.NATIVE_COST_OUTCOME_LABEL_ONLY,
        )
        self.assertEqual(
            members[COMPLETION_103].semantic_class,
            HistoricalSpreadSemanticClass.ENGINEERING,
        )
        self.assertNotIn(FUTURE_COMPLETION, members)
        self.assertEqual(
            audit_slice.study_operation_record_ids,
            ("STU-0073", "STU-0083", "STU-0103", "STU-0104"),
        )

    def test_reader_qualifies_proxy_actual_criterion_claim_and_engineering(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                index.put_many(_fixture_records())
                audit_slice = _derive(index)
        projection = HistoricalSpreadSemanticsProjection(
            audit_manifest=None,  # type: ignore[arg-type]
            latch=None,  # type: ignore[arg-type]
            members=audit_slice.members,
            study_operation_record_ids=audit_slice.study_operation_record_ids,
            adjudication_record_ids=(),
            negative_memory_ids=(),
        )

        completion = projection.completion_qualification(COMPLETION_83)
        self.assertEqual(
            completion.preserved_proxy_criteria,
            (
                HistoricalCostSemanticCriterion.C01_POSITIVE_REPORTED_COST,
                HistoricalCostSemanticCriterion.C02_STRESS_RESILIENCE,
                HistoricalCostSemanticCriterion.C05_FIXED_LOT_PROFIT_FACTOR,
            ),
        )
        proxy = projection.qualify_criterion(
            COMPLETION_83,
            HistoricalCostSemanticCriterion.C01_POSITIVE_REPORTED_COST,
            interpretation=HistoricalCostInterpretation.COMPLETED_PERIOD_PROXY,
        )
        self.assertEqual(
            proxy.state,
            HistoricalCostQualificationState.PRESERVED_EXACT_PROXY_ONLY,
        )
        self.assertTrue(proxy.proxy_only)
        actual = projection.qualify_criterion(
            COMPLETION_83,
            HistoricalCostSemanticCriterion.C01_POSITIVE_REPORTED_COST,
            interpretation=(
                HistoricalCostInterpretation.ACTUAL_POINT_IN_TIME_NATIVE_QUOTE
            ),
        )
        self.assertEqual(actual.state, HistoricalCostQualificationState.UNRESOLVED)
        diagnostic = projection.qualify_criterion(
            COMPLETION_83,
            HistoricalCostSemanticCriterion.C04_UNKNOWN_COST_RESOLUTION,
            interpretation=HistoricalCostInterpretation.COMPLETED_PERIOD_PROXY,
        )
        self.assertEqual(
            diagnostic.state,
            HistoricalCostQualificationState.DIAGNOSTIC_ONLY,
        )
        bound_claim = projection.qualify_claim(
            COMPLETION_83,
            "after_cost_fixed_lot_economics",
            interpretation=HistoricalCostInterpretation.COMPLETED_PERIOD_PROXY,
        )
        self.assertEqual(
            bound_claim.state,
            HistoricalCostQualificationState.UNRESOLVED,
        )
        independent = projection.qualify_claim(
            COMPLETION_104,
            "gross_mechanism",
            interpretation=(
                HistoricalCostInterpretation.ACTUAL_POINT_IN_TIME_NATIVE_QUOTE
            ),
        )
        self.assertEqual(
            independent.state,
            HistoricalCostQualificationState.PRESERVED_INDEPENDENT,
        )
        engineering = projection.qualify_criterion(
            COMPLETION_103,
            HistoricalCostSemanticCriterion.C01_POSITIVE_REPORTED_COST,
            interpretation=HistoricalCostInterpretation.COMPLETED_PERIOD_PROXY,
        )
        self.assertEqual(
            engineering.state,
            HistoricalCostQualificationState.ENGINEERING_NOT_APPLICABLE,
        )

    def test_caller_created_latch_head_lacks_writer_authority(self) -> None:
        manifest = _production_manifest()
        latch = HistoricalCostSemanticsLatch.from_audit_manifest(manifest)
        fake = replace(
            historical_cost_semantics_latch_record(latch),
            authority_sequence=PRODUCTION_UPPER_CURSOR.sequence + 1,
            authority_event_id="e" * 64,
            authority_offset=PRODUCTION_UPPER_CURSOR.offset + 1,
        )
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                index.put(fake)
                with self.assertRaisesRegex(
                    HistoricalCostSemanticsProjectionError,
                    "same-event Writer authority",
                ):
                    current_historical_cost_semantics_latch(index, manifest)


if __name__ == "__main__":
    unittest.main()
