from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
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

    def test_unrenderable_row_is_rejected_before_authority_and_api_recovery_repairs(self) -> None:
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
            self.assertTrue(report["study_kpi_projection_changed"])
            self.assertEqual(ledger.read_bytes(), render_study_kpi(()))

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
                "commit_snapshot_kpi_projection_equals_deterministic_journal_render"
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
        (REPO_ROOT / LEDGER_RELATIVE_PATH).read_text(encoding="ascii")


if __name__ == "__main__":
    unittest.main()
