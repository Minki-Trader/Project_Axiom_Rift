from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import yaml

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.writer import StateWriter, TransitionError
from axiom_rift.storage.index import IndexRecord, LocalIndex
from axiom_rift.storage.study_kpi import (
    LEDGER_RELATIVE_PATH,
    render_study_kpi,
    validate_study_id,
)


REPO_ROOT = Path(__file__).resolve().parents[2]


def digest(domain: str, payload: object) -> str:
    return canonical_digest(domain=domain, payload=payload)


class StudyKpiWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.writer = StateWriter(self.root, foundation_root=REPO_ROOT)
        self.study_id = "STU-KPI"
        self.batch_id = "batch:" + "0" * 64
        self.job_id = "job:" + "1" * 64
        self.job_hash = "2" * 64
        self.executable_id = "executable:" + "3" * 64
        measurement = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "executable_id": self.executable_id,
                    "job_hash": self.job_hash,
                    "job_id": self.job_id,
                    "metrics": {
                        "activity": {"trade_count": 124},
                        "economics": {
                            "median_fold_profit_factor_milli": 1_780,
                            "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": 72_000,
                            "net_profit_micropoints": 1_248_300,
                        },
                    },
                    "schema": "scientific_measurement.test.v1",
                }
            )
        )
        self.completion_id = digest("completion", {"study": self.study_id})
        with LocalIndex(self.writer.index_path) as index:
            index.put(
                IndexRecord(
                    kind="batch-open",
                    record_id=self.batch_id,
                    subject=f"Study:{self.study_id}",
                    status="open",
                    fingerprint="0" * 64,
                    payload={},
                    event_stream=f"study-batches:{self.study_id}",
                    event_sequence=1,
                )
            )
            index.put(
                IndexRecord(
                    kind="job-declared",
                    record_id=self.job_id,
                    subject=f"Job:{self.job_id}",
                    status="declared",
                    fingerprint=self.job_hash,
                    payload={
                        "batch_id": self.batch_id,
                        "study_id": self.study_id,
                    },
                )
            )
            index.put(
                IndexRecord(
                    kind="batch-budget-reservation",
                    record_id=digest("batch-budget", {"job": self.job_id}),
                    subject=f"Batch:{self.batch_id}",
                    status="reserved",
                    fingerprint=self.job_hash,
                    payload={
                        "compute_seconds": 30,
                        "job_id": self.job_id,
                        "wall_seconds": 30,
                    },
                    event_stream=f"batch-budget:{self.batch_id}",
                    event_sequence=1,
                )
            )
            index.put(
                IndexRecord(
                    kind="job-completed",
                    record_id=self.completion_id,
                    subject=f"Job:{self.job_id}",
                    status="success",
                    fingerprint=self.job_hash,
                    payload={
                        "job_id": self.job_id,
                        "scientific": {
                            "executable_id": self.executable_id,
                            "measurement_artifact_hashes": [measurement.sha256],
                            "scientific_eligible": True,
                            "verdict": "failed",
                        },
                    },
                )
            )

    def _put_decision(self, disposition: str) -> None:
        with LocalIndex(self.writer.index_path) as index:
            index.put(
                IndexRecord(
                    kind="job-evidence-decision",
                    record_id=digest(
                        "decision",
                        {
                            "completion": self.completion_id,
                            "disposition": disposition,
                        },
                    ),
                    subject=f"Job:{self.job_id}",
                    status=disposition,
                    fingerprint=self.job_hash,
                    payload={"completion_record_id": self.completion_id},
                )
            )

    def _put_historical_close(
        self,
        *,
        outcome: str,
        batch_outcome: str,
        revision: int = 10,
    ) -> IndexRecord:
        event_id = digest(
            "historical-close-event",
            {"study_id": self.study_id, "revision": revision},
        )
        close_id = digest(
            "historical-study-close",
            {"study_id": self.study_id, "outcome": outcome},
        )
        close = IndexRecord(
            kind="study-close",
            record_id=close_id,
            subject=f"Study:{self.study_id}",
            status=outcome,
            fingerprint=close_id,
            payload={"outcome": outcome},
            authority_sequence=revision,
            authority_event_id=event_id,
            authority_offset=revision,
        )
        with LocalIndex(self.writer.index_path) as index:
            index.put(
                IndexRecord(
                    kind="study-open",
                    record_id=self.study_id,
                    subject=f"Study:{self.study_id}",
                    status="open",
                    fingerprint="f" * 64,
                    payload={},
                )
            )
            index.put(
                IndexRecord(
                    kind="batch-close",
                    record_id=digest(
                        "historical-batch-close",
                        {"batch_id": self.batch_id, "outcome": batch_outcome},
                    ),
                    subject=f"Batch:{self.batch_id}",
                    status=batch_outcome,
                    fingerprint="e" * 64,
                    payload={"outcome": batch_outcome},
                )
            )
            index.put(
                IndexRecord(
                    kind="journal-event",
                    record_id=event_id,
                    subject="Study:active",
                    status="study_closed",
                    fingerprint=event_id,
                    payload={
                        "occurred_at_utc": "2026-07-11T12:34:56Z",
                        "operation_id": "historical-study-close",
                    },
                    event_stream="control",
                    event_sequence=revision,
                    authority_sequence=revision,
                    authority_event_id=event_id,
                    authority_offset=revision,
                )
            )
            index.put(close)
        return close

    def test_writer_derives_metrics_from_bound_measurement(self) -> None:
        self._put_decision("stop_batch")
        with LocalIndex(self.writer.index_path) as index:
            value = self.writer._study_kpi_from_completion(
                index=index,
                study_id=self.study_id,
                completion_record_id=self.completion_id,
            )
        self.assertEqual(value["executable_id"], self.executable_id)
        self.assertEqual(
            value["metrics"],
            {
                "net_profit_micropoints": 1_248_300,
                "median_fold_profit_factor_milli": 1_780,
                "trade_count": 124,
                "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": 72_000,
            },
        )

    def test_batch_decision_inventory_is_batch_keyed_and_query_bounded(
        self,
    ) -> None:
        self._put_decision("stop_batch")
        unrelated_job_id = "job:" + "8" * 64
        with LocalIndex(self.writer.index_path) as index:
            index.put(
                IndexRecord(
                    kind="job-evidence-decision",
                    record_id=digest("decision", {"unrelated": True}),
                    subject=f"Job:{unrelated_job_id}",
                    status="stop_batch",
                    fingerprint="8" * 64,
                    payload={"completion_record_id": None},
                )
            )
            payload_calls: list[tuple[str, str, str, int]] = []
            subject_calls: list[tuple[str, str, int]] = []
            payload_lookup = index.records_by_payload_text
            subject_lookup = index.records_by_subject_status

            def counted_payload(kind: str, lookup_name: str, value: str):
                records = payload_lookup(kind, lookup_name, value)
                payload_calls.append((kind, lookup_name, value, len(records)))
                return records

            def counted_subject(subject: str, status: str):
                records = subject_lookup(subject, status)
                subject_calls.append((subject, status, len(records)))
                return records

            with patch.object(
                index,
                "records_by_payload_text",
                side_effect=counted_payload,
            ), patch.object(
                index,
                "records_by_subject_status",
                side_effect=counted_subject,
            ), patch.object(
                index,
                "records_by_kind",
                side_effect=AssertionError(
                    "Batch decision inventory decoded project-wide history"
                ),
            ):
                completion_ids = self.writer._batch_stop_completion_ids(
                    index,
                    self.batch_id,
                )
        self.assertEqual(completion_ids, (self.completion_id,))
        self.assertEqual(
            payload_calls,
            [
                (
                    "job-declared",
                    "batch_id",
                    self.batch_id,
                    1,
                )
            ],
        )
        self.assertEqual(
            subject_calls,
            [
                (f"Job:{self.job_id}", "continue_batch", 0),
                (f"Job:{self.job_id}", "stop_batch", 1),
            ],
        )

    def test_study_kpi_display_allocation_decodes_only_identity_and_collisions(
        self,
    ) -> None:
        collision_identity = "executable:" + "4" * 64
        with LocalIndex(self.writer.index_path) as index:
            index.put_many(
                (
                    IndexRecord(
                        kind="study-kpi",
                        record_id="STU-KPI-COLLISION",
                        subject="Study:STU-KPI-COLLISION",
                        status="not_supported",
                        fingerprint="4" * 64,
                        payload={
                            "executable_display_id": "EXE-" + "3" * 12,
                            "executable_id": collision_identity,
                        },
                    ),
                    IndexRecord(
                        kind="study-kpi",
                        record_id="STU-KPI-UNRELATED-MALFORMED",
                        subject="Study:STU-KPI-UNRELATED-MALFORMED",
                        status="not_evaluable",
                        fingerprint="5" * 64,
                        payload={
                            "executable_display_id": None,
                            "executable_id": "executable:" + "5" * 64,
                        },
                    ),
                )
            )
            decoded: list[tuple[str, str, int]] = []
            payload_lookup = index.records_by_payload_text

            def counted_payload(kind: str, lookup_name: str, value: str):
                records = payload_lookup(kind, lookup_name, value)
                decoded.append((lookup_name, value, len(records)))
                return records

            with patch.object(
                index,
                "records_by_payload_text",
                side_effect=counted_payload,
            ), patch.object(
                index,
                "records_by_kind",
                side_effect=AssertionError(
                    "Study KPI display allocation decoded the full ledger"
                ),
            ):
                display_id = self.writer._study_kpi_display_id(
                    index,
                    self.executable_id,
                )
        self.assertEqual(display_id, "EXE-" + "3" * 16)
        self.assertEqual(
            decoded,
            [
                (
                    "study_kpi_executable_id",
                    self.executable_id,
                    0,
                ),
                (
                    "study_kpi_executable_display_id",
                    "EXE-" + "3" * 12,
                    1,
                ),
                (
                    "study_kpi_executable_display_id",
                    "EXE-" + "3" * 16,
                    0,
                ),
            ],
        )

    def test_historical_payload_uses_final_completion_and_original_close(self) -> None:
        self._put_decision("stop_batch")
        close = self._put_historical_close(
            outcome="not_supported",
            batch_outcome="completed",
        )
        with LocalIndex(self.writer.index_path) as index:
            payload = self.writer._historical_study_kpi_payload(
                index=index,
                close_record=close,
                sequence=1,
                reserved_display_owners={},
            )
        self.assertEqual(payload["provenance"], "historical_backfill")
        self.assertEqual(payload["historical_study_close_revision"], 10)
        self.assertEqual(payload["executable_id"], self.executable_id)
        self.assertEqual(payload["executable_display_id"], "EXE-" + "3" * 12)
        self.assertEqual(payload["metrics"]["net_profit_micropoints"], 1_248_300)

    def test_historical_engineering_failure_keeps_executable_and_dash_metrics(
        self,
    ) -> None:
        job_id = "job:" + "9" * 64
        job_hash = "a" * 64
        executable_id = "executable:" + "b" * 64
        completion_id = digest("completion", {"engineering": True})
        with LocalIndex(self.writer.index_path) as index:
            index.put(
                IndexRecord(
                    kind="job-declared",
                    record_id=job_id,
                    subject=f"Job:{job_id}",
                    status="declared",
                    fingerprint=job_hash,
                    payload={
                        "batch_id": self.batch_id,
                        "spec": {
                            "evidence_subject": {
                                "id": executable_id,
                                "kind": "Executable",
                            }
                        },
                        "study_id": self.study_id,
                    },
                )
            )
            index.put(
                IndexRecord(
                    kind="job-completed",
                    record_id=completion_id,
                    subject=f"Job:{job_id}",
                    status="failed",
                    fingerprint=job_hash,
                    payload={
                        "failure": {"failure_kind": "engineering"},
                        "job_id": job_id,
                    },
                )
            )
            index.put(
                IndexRecord(
                    kind="job-evidence-decision",
                    record_id=digest("decision", {"engineering": True}),
                    subject=f"Job:{job_id}",
                    status="stop_batch",
                    fingerprint=job_hash,
                    payload={"completion_record_id": completion_id},
                )
            )
        close = self._put_historical_close(
            outcome="evidence_gap",
            batch_outcome="engineering_failure",
        )
        with LocalIndex(self.writer.index_path) as index:
            payload = self.writer._historical_study_kpi_payload(
                index=index,
                close_record=close,
                sequence=1,
                reserved_display_owners={},
            )
        self.assertEqual(
            payload["source"],
            "historical_writer_verified_unavailable",
        )
        self.assertEqual(payload["executable_id"], executable_id)
        self.assertTrue(
            all(value is None for value in payload["metrics"].values())
        )

    def test_prospective_sequence_continues_after_historical_backfill(self) -> None:
        self._put_decision("stop_batch")
        with LocalIndex(self.writer.index_path) as index:
            index.put(
                IndexRecord(
                    kind="study-kpi",
                    record_id="STU-HISTORICAL",
                    subject="Study:STU-HISTORICAL",
                    status="not_supported",
                    fingerprint="c" * 64,
                    payload={
                        "executable_display_id": None,
                        "executable_id": None,
                    },
                    event_stream="study-kpi",
                    event_sequence=21,
                )
            )
            payload = self.writer._study_kpi_payload(
                index=index,
                study_id=self.study_id,
                outcome="not_supported",
                completion_record_id=self.completion_id,
                closed_at_utc="2026-07-12T00:00:00Z",
            )
        assert payload is not None
        self.assertEqual(payload["sequence"], 22)
        self.assertEqual(payload["provenance"], "prospective_close")
        self.assertIsNone(payload["historical_study_close_event_id"])

    def test_not_evaluable_science_cannot_be_closed_as_not_supported(self) -> None:
        job_id = "job:" + "4" * 64
        job_hash = "5" * 64
        completion_id = digest("completion", {"not_evaluable": True})
        measurement = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "executable_id": self.executable_id,
                    "job_hash": job_hash,
                    "job_id": job_id,
                    "metrics": {},
                    "schema": "scientific_measurement.test.v1",
                }
            )
        )
        with LocalIndex(self.writer.index_path) as index:
            existing = index.get("job-completed", self.completion_id)
            assert existing is not None
            scientific = dict(existing.payload["scientific"])
            scientific["measurement_artifact_hashes"] = [measurement.sha256]
            scientific["verdict"] = "not_evaluable"
            index.put(
                IndexRecord(
                    kind="job-declared",
                    record_id=job_id,
                    subject=f"Job:{job_id}",
                    status="declared",
                    fingerprint=job_hash,
                    payload={
                        "batch_id": self.batch_id,
                        "study_id": self.study_id,
                    },
                )
            )
            index.put(
                IndexRecord(
                    kind="job-completed",
                    record_id=completion_id,
                    subject=f"Job:{job_id}",
                    status="success",
                    fingerprint=job_hash,
                    payload={"job_id": job_id, "scientific": scientific},
                )
            )
            index.put(
                IndexRecord(
                    kind="job-evidence-decision",
                    record_id=digest("decision", {"not_evaluable": True}),
                    subject=f"Job:{job_id}",
                    status="stop_batch",
                    fingerprint=job_hash,
                    payload={"completion_record_id": completion_id},
                )
            )
            for rejected_outcome in ("not_supported", "pruned"):
                with self.subTest(outcome=rejected_outcome), self.assertRaisesRegex(
                    TransitionError,
                    "disposition-driving scientific adjudication",
                ):
                    self.writer._study_kpi_payload(
                        index=index,
                        study_id=self.study_id,
                        outcome=rejected_outcome,
                        completion_record_id=completion_id,
                        closed_at_utc="2026-07-12T00:00:00Z",
                    )
            payload = self.writer._study_kpi_payload(
                index=index,
                study_id=self.study_id,
                outcome="not_evaluable",
                completion_record_id=completion_id,
                closed_at_utc="2026-07-12T00:00:00Z",
            )
        assert payload is not None
        self.assertEqual(payload["outcome"], "not_evaluable")

    def test_engineering_completion_cannot_become_a_scientific_outcome(self) -> None:
        job_id = "job:" + "6" * 64
        job_hash = "7" * 64
        executable_id = "executable:" + "8" * 64
        completion_id = digest("completion", {"prospective_engineering": True})
        with LocalIndex(self.writer.index_path) as index:
            index.put(
                IndexRecord(
                    kind="job-declared",
                    record_id=job_id,
                    subject=f"Job:{job_id}",
                    status="declared",
                    fingerprint=job_hash,
                    payload={
                        "batch_id": self.batch_id,
                        "spec": {
                            "evidence_subject": {
                                "id": executable_id,
                                "kind": "Executable",
                            }
                        },
                        "study_id": self.study_id,
                    },
                )
            )
            index.put(
                IndexRecord(
                    kind="job-completed",
                    record_id=completion_id,
                    subject=f"Job:{job_id}",
                    status="failed",
                    fingerprint=job_hash,
                    payload={
                        "engineering_disposition": {
                            "job_id": job_id,
                            "schema": "engineering_failure_disposition.v1",
                        },
                        "failure": {"failure_kind": "engineering"},
                        "job_id": job_id,
                    },
                )
            )
            index.put(
                IndexRecord(
                    kind="job-evidence-decision",
                    record_id=digest(
                        "decision",
                        {"prospective_engineering": True},
                    ),
                    subject=f"Job:{job_id}",
                    status="stop_batch",
                    fingerprint=job_hash,
                    payload={"completion_record_id": completion_id},
                )
            )
            for rejected_outcome in ("not_supported", "pruned", "supported"):
                with self.subTest(outcome=rejected_outcome), self.assertRaisesRegex(
                    TransitionError,
                    "cannot become a scientific outcome",
                ):
                    self.writer._study_kpi_payload(
                        index=index,
                        study_id=self.study_id,
                        outcome=rejected_outcome,
                        completion_record_id=completion_id,
                        closed_at_utc="2026-07-12T00:00:00Z",
                    )
            payload = self.writer._study_kpi_payload(
                index=index,
                study_id=self.study_id,
                outcome="evidence_gap",
                completion_record_id=completion_id,
                closed_at_utc="2026-07-12T00:00:00Z",
            )
        assert payload is not None
        self.assertEqual(payload["source"], "typed_engineering_failure_completion")
        self.assertEqual(payload["outcome"], "evidence_gap")

    def test_writer_derived_unavailable_study_cannot_be_pruned(self) -> None:
        with LocalIndex(self.writer.index_path) as index:
            index.put(
                IndexRecord(
                    kind="batch-close",
                    record_id=digest("batch-close", {"stopped_early": True}),
                    subject=f"Batch:{self.batch_id}",
                    status="stopped_early",
                    fingerprint=self.job_hash,
                    payload={"outcome": "stopped_early"},
                )
            )
            with self.assertRaisesRegex(
                TransitionError,
                "unavailable state is not writer-derived",
            ):
                self.writer._study_kpi_payload(
                    index=index,
                    study_id=self.study_id,
                    outcome="pruned",
                    completion_record_id=None,
                    closed_at_utc="2026-07-12T00:00:00Z",
                )
            payload = self.writer._study_kpi_payload(
                index=index,
                study_id=self.study_id,
                outcome="not_evaluable",
                completion_record_id=None,
                closed_at_utc="2026-07-12T00:00:00Z",
            )
        assert payload is not None
        self.assertEqual(payload["source"], "writer_derived_unavailable")
        self.assertEqual(payload["outcome"], "not_evaluable")

    def test_rich_partial_positive_remains_a_positive_study_close(self) -> None:
        completion = IndexRecord(
            kind="job-completed",
            record_id=digest("completion", {"partial_positive": True}),
            subject=f"Job:{self.job_id}",
            status="success",
            fingerprint=self.job_hash,
            payload={
                "scientific": {
                    "adjudication": {"state": "partial_positive"},
                    "scientific_eligible": True,
                    "verdict": "not_evaluable",
                }
            },
        )
        self.writer._require_scientific_study_outcome(
            completion=completion,
            outcome="preserved",
        )
        with self.assertRaisesRegex(
            TransitionError,
            "disposition-driving scientific adjudication",
        ):
            self.writer._require_scientific_study_outcome(
                completion=completion,
                outcome="not_supported",
            )

    def test_intermediate_continue_batch_completion_is_rejected(self) -> None:
        self._put_decision("continue_batch")
        with LocalIndex(self.writer.index_path) as index:
            with self.assertRaisesRegex(TransitionError, "stop_batch"):
                self.writer._study_kpi_from_completion(
                    index=index,
                    study_id=self.study_id,
                    completion_record_id=self.completion_id,
                )

    def test_completion_must_belong_to_the_final_batch(self) -> None:
        self._put_decision("stop_batch")
        later_batch_id = "batch:" + "4" * 64
        with LocalIndex(self.writer.index_path) as index:
            index.put(
                IndexRecord(
                    kind="batch-open",
                    record_id=later_batch_id,
                    subject=f"Study:{self.study_id}",
                    status="open",
                    fingerprint="4" * 64,
                    payload={},
                    event_stream=f"study-batches:{self.study_id}",
                    event_sequence=2,
                )
            )
            with self.assertRaisesRegex(TransitionError, "final Study Batch"):
                self.writer._study_kpi_from_completion(
                    index=index,
                    study_id=self.study_id,
                    completion_record_id=self.completion_id,
                )

    def test_metric_bearing_measurement_requires_exact_identity_fields(self) -> None:
        measurement = self.writer.evidence.finalize(
            canonical_bytes(
                {
                    "metrics": {"economics": {"net_profit_micropoints": 1}},
                    "schema": "unbound_measurement.test.v1",
                }
            )
        )
        job_id = "job:" + "5" * 64
        job_hash = "6" * 64
        completion_id = digest("completion", {"unbound": True})
        with LocalIndex(self.writer.index_path) as index:
            index.put(
                IndexRecord(
                    kind="job-declared",
                    record_id=job_id,
                    subject=f"Job:{job_id}",
                    status="declared",
                    fingerprint=job_hash,
                    payload={
                        "batch_id": self.batch_id,
                        "study_id": self.study_id,
                    },
                )
            )
            index.put(
                IndexRecord(
                    kind="job-completed",
                    record_id=completion_id,
                    subject=f"Job:{job_id}",
                    status="success",
                    fingerprint=job_hash,
                    payload={
                        "job_id": job_id,
                        "scientific": {
                            "executable_id": self.executable_id,
                            "measurement_artifact_hashes": [measurement.sha256],
                            "scientific_eligible": True,
                        },
                    },
                )
            )
            index.put(
                IndexRecord(
                    kind="job-evidence-decision",
                    record_id=digest("decision", {"unbound": True}),
                    subject=f"Job:{job_id}",
                    status="stop_batch",
                    fingerprint=job_hash,
                    payload={"completion_record_id": completion_id},
                )
            )
            with self.assertRaisesRegex(TransitionError, "another Job"):
                self.writer._study_kpi_from_completion(
                    index=index,
                    study_id=self.study_id,
                    completion_record_id=completion_id,
                )

    def test_conflicting_validator_metric_values_fail_closed(self) -> None:
        with self.assertRaisesRegex(TransitionError, "ambiguous"):
            self.writer._collect_study_kpi_metric(
                (
                    {
                        "metrics": {
                            "economics": {"net_profit_micropoints": 10}
                        }
                    },
                    {
                        "metrics": {
                            "economics": {"net_profit_micropoints": 11}
                        }
                    },
                ),
                "net_profit_micropoints",
            )

    def test_validator_derived_source_completion_creates_dash_kpi(self) -> None:
        job_id = "job:" + "7" * 64
        job_hash = "8" * 64
        completion_id = digest("completion", {"source": True})
        result_hash = digest("source-result", {"valid": True})
        with LocalIndex(self.writer.index_path) as index:
            index.put(
                IndexRecord(
                    kind="job-declared",
                    record_id=job_id,
                    subject=f"Job:{job_id}",
                    status="declared",
                    fingerprint=job_hash,
                    payload={
                        "batch_id": self.batch_id,
                        "spec": {
                            "evidence_subject": {
                                "id": self.study_id,
                                "kind": "Study",
                            }
                        },
                        "study_id": self.study_id,
                    },
                )
            )
            index.put(
                IndexRecord(
                    kind="job-completed",
                    record_id=completion_id,
                    subject=f"Job:{job_id}",
                    status="success",
                    fingerprint=job_hash,
                    payload={
                        "job_id": job_id,
                        "scientific": None,
                        "source": {
                            "result_manifest_hash": result_hash,
                            "validation_trace": {"opened_artifact_count": 1},
                            "validator_id": "validator:test-source",
                        },
                    },
                )
            )
            index.put(
                IndexRecord(
                    kind="job-evidence-decision",
                    record_id=digest("decision", {"source": True}),
                    subject=f"Job:{job_id}",
                    status="stop_batch",
                    fingerprint=job_hash,
                    payload={"completion_record_id": completion_id},
                )
            )
            value = self.writer._study_kpi_from_completion(
                index=index,
                study_id=self.study_id,
                completion_record_id=completion_id,
            )
        self.assertEqual(value["source"], "validator_derived_source_completion")
        self.assertIsNone(value["executable_id"])
        self.assertTrue(all(metric is None for metric in value["metrics"].values()))

    def test_wrong_study_and_missing_completion_fail_closed(self) -> None:
        self._put_decision("stop_batch")
        with LocalIndex(self.writer.index_path) as index:
            with self.assertRaisesRegex(TransitionError, "another Study"):
                self.writer._study_kpi_from_completion(
                    index=index,
                    study_id="STU-OTHER",
                    completion_record_id=self.completion_id,
                )
            with self.assertRaisesRegex(TransitionError, "validator completion"):
                self.writer._study_kpi_payload(
                    index=index,
                    study_id=self.study_id,
                    outcome="evidence_gap",
                    completion_record_id=None,
                    closed_at_utc="2026-07-12T00:00:00Z",
                )

    def test_close_api_does_not_accept_caller_kpi_numbers(self) -> None:
        with self.assertRaises(TypeError):
            self.writer.close_study(
                outcome="supported",
                operation_id="forged-kpi",
                kpi_metrics={"net_profit_micropoints": 9_999_999},
            )

    def test_unrenderable_row_is_rejected_and_only_explicit_maintenance_repairs_navigation(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid Study id"):
            validate_study_id("STU-BAD|ROW")
        with TemporaryDirectory() as temporary:
            writer = StateWriter(
                temporary,
                clock=lambda: "bad-clock",
                foundation_root=REPO_ROOT,
            )
            with self.assertRaisesRegex(TransitionError, "occurred_at_utc"):
                writer.initialize_ready()
            journal = Path(temporary) / "records" / "journal.jsonl"
            self.assertFalse(journal.exists() and journal.stat().st_size)
        with TemporaryDirectory() as temporary:
            writer = StateWriter(
                temporary,
                engineering_fixture=True,
                foundation_root=REPO_ROOT,
            )
            writer.initialize_ready()
            ledger = Path(temporary) / LEDGER_RELATIVE_PATH
            ledger.parent.mkdir(parents=True, exist_ok=True)
            ledger.write_bytes(b"corrupt\n")
            report = writer.recover()
            self.assertFalse(report["study_kpi_projection_changed"])
            self.assertEqual(ledger.read_bytes(), b"corrupt\n")
            self.assertTrue(writer.rebuild_study_kpi_projection())
            self.assertEqual(ledger.read_bytes(), render_study_kpi(()))
            self.assertFalse(writer.rebuild_study_kpi_projection())

    def test_idempotent_retry_does_not_read_a_new_clock_value(self) -> None:
        with TemporaryDirectory() as temporary:
            writer = StateWriter(
                temporary,
                clock=lambda: "2026-07-12T00:00:00Z",
                engineering_fixture=True,
                foundation_root=REPO_ROOT,
            )
            first = writer.initialize_ready()
            writer.clock = lambda: "bad-retry-clock"
            retried = writer.initialize_ready()
            self.assertTrue(retried.reused)
            self.assertEqual(retried.event_id, first.event_id)

    def test_active_contract_routes_the_same_projection_and_delivery(self) -> None:
        science = yaml.safe_load(
            (REPO_ROOT / "contracts" / "science.yaml").read_text(encoding="ascii")
        )
        operations = yaml.safe_load(
            (REPO_ROOT / "contracts" / "operations.yaml").read_text(
                encoding="ascii"
            )
        )
        self.assertEqual(science["study_kpi_projection"]["path"], LEDGER_RELATIVE_PATH)
        self.assertEqual(
            science["study_kpi_projection"]["materialization"],
            "explicit_stable_boundary_maintenance",
        )
        self.assertTrue(science["study_kpi_projection"]["may_lag_journal_authority"])
        self.assertFalse(science["study_kpi_projection"]["freshness_blocks_research"])
        durable = operations["authority"]["durable_journal"]
        segmented_contract = isinstance(durable, dict)
        if segmented_contract:
            self.assertEqual(durable["legacy_path"], "records/journal.jsonl")
            self.assertEqual(
                durable["segmented_manifest"],
                "records/journal/manifest.json",
            )
            self.assertEqual(durable["offset_mode"], "global_virtual")
            self.assertTrue(durable["dual_read_compatibility"])
            journal_storage = operations["journal_storage"]
            self.assertTrue(journal_storage["sealed_segments_immutable"])
            self.assertTrue(journal_storage["existing_global_offsets_preserved"])
            self.assertTrue(journal_storage["existing_event_ids_preserved"])
            self.assertEqual(journal_storage["segment_byte_limit"], 33_554_432)
            self.assertEqual(journal_storage["segment_event_limit"], 5_000)
        else:
            self.assertEqual(durable, "records/journal.jsonl")
            self.assertNotIn("journal_storage", operations)
        historical = science["study_kpi_projection"]["historical_backfill"]
        self.assertTrue(historical["sponsor_authorized_once"])
        self.assertFalse(historical["retrospective_best_selection_allowed"])
        self.assertEqual(
            historical["single_writer_event"],
            "study_kpi_backfilled",
        )
        checkpoint = operations["git"]["study_close_checkpoint"]
        self.assertEqual(checkpoint["trigger_event"], "study_closed")
        self.assertEqual(checkpoint["local_ref"], "main")
        self.assertEqual(checkpoint["remote_ref"], "origin/main")
        self.assertTrue(
            checkpoint[
                "local_commit_and_initial_push_attempt_required_before_later_scientific_work"
            ]
        )
        self.assertFalse(
            checkpoint["remote_equality_required_before_later_scientific_work"]
        )
        self.assertEqual(
            operations["study_close_delivery_checkpoint"]["validator_version"],
            "study_close_delivery_checkpoint.v3",
        )
        self.assertIn(
            "records/STUDY_CLOSE_DELIVERY_CHECKPOINT.json",
            checkpoint["required_same_commit_paths"],
        )
        self.assertNotIn(
            "records/STUDY_KPI.md",
            checkpoint["required_same_commit_paths"],
        )
        if segmented_contract:
            self.assertEqual(
                checkpoint["required_journal_path"]["segmented"],
                "manifest_active_segment",
            )
        self.assertTrue(
            checkpoint["boot_delivery_audit"][
                "local_commit_absence_requires_resume_before_state_or_science_action"
            ]
        )
        self.assertTrue(
            checkpoint["boot_delivery_audit"][
                "exact_unique_trailer_commit_reachable_from_local_ref"
            ]
        )
        self.assertTrue(
            checkpoint["boot_delivery_audit"][
                "commit_snapshot_journal_tail_matches_event"
            ]
        )
        self.assertTrue(
            checkpoint["boot_delivery_audit"][
                "commit_snapshot_new_kpi_record_and_checkpoint_transition_valid"
            ]
        )
        self.assertFalse(
            checkpoint["boot_delivery_audit"][
                "complete_kpi_projection_scan_required"
            ]
        )
        self.assertEqual(
            checkpoint["boot_delivery_audit"]["remote_relation"],
            "closeout_commit_ancestor_of_remote_ref",
        )
        self.assertTrue(
            checkpoint["push_failure"][
                "retry_at_next_stable_delivery_opportunity"
            ]
        )
        enforcement = checkpoint["automated_enforcement"]
        self.assertEqual(
            enforcement["tracked_commit_msg_hook"], ".githooks/commit-msg"
        )
        self.assertEqual(enforcement["required_core_hooks_path"], ".githooks")
        self.assertTrue(
            enforcement["exact_contiguous_final_trailer_block_required"]
        )
        self.assertTrue(enforcement["routine_kpi_markdown_change_forbidden"])
        self.assertEqual(
            enforcement["complete_kpi_rerender"],
            "explicit_maintenance_only",
        )
        self.assertFalse(enforcement["hook_bypass_allowed"])
        self.assertTrue(
            enforcement["next_portfolio_decision_writer_guard_required"]
        )
        repair = operations["git"][
            "study_close_delivery_repair_checkpoint"
        ]
        self.assertTrue(repair["sponsor_authorization_required"])
        self.assertTrue(
            repair["boot_delivery_audit_accepts_valid_attested_original"]
        )
        self.assertFalse(repair["history_rewrite_allowed"])
        self.assertFalse(repair["duplicate_study_close_snapshot_allowed"])
        self.assertEqual(
            repair["attestation_manifest"],
            "records/STUDY_CLOSE_DELIVERY_REPAIR.json",
        )
        backfill = operations["git"][
            "study_kpi_historical_backfill_checkpoint"
        ]
        self.assertTrue(backfill["one_commit_for_complete_history"])
        self.assertFalse(backfill["per_historical_study_commit_allowed"])
        self.assertEqual(
            backfill["commit_trailers"],
            ["Axiom-Study-KPI-Backfill", "Axiom-State-Revision"],
        )
        (REPO_ROOT / LEDGER_RELATIVE_PATH).read_text(encoding="ascii")


if __name__ == "__main__":
    unittest.main()
