from __future__ import annotations

from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.permits import (
    PermitAuthority,
    PermitKind,
    SubjectKind,
    SubjectRef,
)
from axiom_rift.operations.writer import (
    RunningJobExecution,
    StateWriter,
    TransitionError,
)
from axiom_rift.storage.index import EventHead, IndexRecord


class _Index:
    def __init__(
        self,
        *,
        records: list[IndexRecord],
        events: list[IndexRecord],
        retry_head: EventHead,
    ) -> None:
        self._records = {
            (record.kind, record.record_id): record for record in records
        }
        self._events = {
            (record.event_stream, record.event_sequence): record
            for record in events
        }
        self._retry_head = retry_head
        self.event_head_calls: list[str] = []
        self.fingerprint_calls: list[str] = []

    def __enter__(self) -> _Index:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def get(self, kind: str, record_id: str) -> IndexRecord | None:
        return self._records.get((kind, record_id))

    def event_record(self, stream: str, sequence: int) -> IndexRecord | None:
        return self._events.get((stream, sequence))

    def event_head(self, stream: str) -> EventHead:
        self.event_head_calls.append(stream)
        return self._retry_head

    def records_by_fingerprint(self, fingerprint: str) -> tuple[IndexRecord, ...]:
        self.fingerprint_calls.append(fingerprint)
        return tuple(
            record
            for record in self._records.values()
            if record.fingerprint == fingerprint
        )

    def replace(self, record: IndexRecord) -> None:
        self._records[(record.kind, record.record_id)] = record


class CacheProducerProvenanceTests(unittest.TestCase):
    def _fixture(
        self,
    ) -> tuple[
        StateWriter,
        _Index,
        RunningJobExecution,
        dict[str, object],
        IndexRecord,
    ]:
        mission_id = "MIS-CACHE-PRODUCER"
        study_id = "STU-CACHE-PRODUCER"
        job_hash = "1" * 64
        job_id = f"job:{job_hash}"
        permit = PermitAuthority(b"p" * 32).issue(
            kind=PermitKind.JOB,
            subject=SubjectRef(
                kind=SubjectKind.JOB,
                subject_id=job_id,
                authorization_epoch=1,
                authorization_hash="2" * 64,
            ),
            input_hash=job_hash,
            actions=("start_job",),
            scope=("job",),
            issued_at_utc="2026-07-14T00:00:00Z",
            expires_at_utc="2026-07-15T00:00:00Z",
            one_shot=True,
            audit_revision=7,
        )
        start_id = canonical_digest(
            domain="job-start",
            payload={
                "job_id": job_id,
                "job_permit": permit.permit_id,
                "runtime_permit": None,
            },
        )
        execution = RunningJobExecution(
            job_id=job_id,
            job_hash=job_hash,
            job_permit_id=permit.permit_id,
            start_record_id=start_id,
        )
        cache_name = "local/cache/producer.bin"
        manifest_name = "evidence/producer-trace"
        cache_hash = "3" * 64
        manifest_hash = "4" * 64
        output_classes = {
            cache_name: "reproducible_cache",
            manifest_name: "durable_evidence",
        }
        expected_outputs = [cache_name, manifest_name]
        callable_identity = "fixture.cache.producer"
        spec = {
            "callable_identity": callable_identity,
            "evidence_subject": {
                "kind": "Executable",
                "id": "executable:" + "5" * 64,
            },
            "expected_outputs": expected_outputs,
            "output_classes": output_classes,
        }
        work_fingerprint = "6" * 64
        success_fingerprint = "7" * 64
        completion_id = "8" * 64
        start_event_id = "9" * 64
        completion_event_id = "a" * 64
        declaration = IndexRecord(
            kind="job-declared",
            record_id=job_id,
            subject=f"Job:{job_id}",
            status="declared",
            fingerprint=job_hash,
            payload={
                "batch_id": "BAT-CACHE-PRODUCER",
                "initiative_id": "INI-CACHE-PRODUCER",
                "mission_id": mission_id,
                "spec": spec,
                "study_id": study_id,
                "success_fingerprint": success_fingerprint,
                "work_fingerprint": work_fingerprint,
            },
            event_stream=f"job-attempt:{work_fingerprint}",
            event_sequence=1,
        )
        start = IndexRecord(
            kind="job-started",
            record_id=start_id,
            subject=f"Job:{job_id}",
            status="running",
            fingerprint=job_hash,
            payload={"job_permit_id": permit.permit_id, "runtime": None},
            authority_event_id=start_event_id,
            authority_sequence=10,
        )
        issued = IndexRecord(
            kind="permit-issued",
            record_id=permit.permit_id,
            subject=f"Permit:{permit.permit_id}",
            status="issued",
            fingerprint=permit.permit_id,
            payload=permit.payload(),
            event_stream=f"permit:{permit.permit_id}",
            event_sequence=1,
            authority_event_id="b" * 64,
            authority_sequence=9,
        )
        consumed_id = "c" * 64
        consumed = IndexRecord(
            kind="permit-consumed",
            record_id=consumed_id,
            subject=f"Permit:{permit.permit_id}",
            status="consumed",
            fingerprint=permit.permit_id,
            payload={"one_shot": True, "permit_id": permit.permit_id},
            event_stream=f"permit:{permit.permit_id}",
            event_sequence=2,
            authority_event_id=start_event_id,
            authority_sequence=10,
        )
        engine_entry_id = canonical_digest(
            domain="job-engine-entry",
            payload=execution.payload(),
        )
        engine_entry = IndexRecord(
            kind="job-engine-entry",
            record_id=engine_entry_id,
            subject=f"Job:{job_id}",
            status="validated",
            fingerprint=job_hash,
            payload={
                "execution": execution.payload(),
                "permit_consumption_record_id": consumed_id,
            },
            authority_event_id=start_event_id,
            authority_sequence=10,
        )
        completion = IndexRecord(
            kind="job-completed",
            record_id=completion_id,
            subject=f"Job:{job_id}",
            status="success",
            fingerprint=job_hash,
            payload={
                "failure": None,
                "job_id": job_id,
                "output_classes": output_classes,
                "outputs": {
                    cache_name: cache_hash,
                    manifest_name: manifest_hash,
                },
                "scientific": {"verdict": "passed"},
                "start_record_id": start_id,
            },
            event_stream=f"job-attempt:{work_fingerprint}",
            event_sequence=3,
            authority_event_id=completion_event_id,
            authority_sequence=11,
        )
        retry_completion = IndexRecord(
            kind="job-completed",
            record_id="d" * 64,
            subject="Job:job:" + "e" * 64,
            status="failed",
            fingerprint="e" * 64,
            payload={
                "failure": {"failure_kind": "engineering"},
                "job_id": "job:" + "e" * 64,
                "output_classes": {},
                "outputs": {},
                "scientific": None,
                "start_record_id": "f" * 64,
            },
            event_stream=f"job-attempt:{work_fingerprint}",
            event_sequence=6,
            authority_event_id="f" * 64,
            authority_sequence=14,
        )
        index = _Index(
            records=[
                declaration,
                start,
                engine_entry,
                completion,
                retry_completion,
            ],
            events=[issued, consumed],
            retry_head=EventHead(
                stream=f"job-attempt:{work_fingerprint}",
                sequence=6,
                record_kind=retry_completion.kind,
                record_id=retry_completion.record_id,
                fingerprint=retry_completion.fingerprint,
            ),
        )
        writer = object.__new__(StateWriter)
        writer.lock_path = Path("unused-cache-producer-lock")
        writer._open_authoritative_index = lambda: index  # type: ignore[method-assign]
        writer._require_stable_locked = lambda _: {  # type: ignore[method-assign]
            "scientific": {"active_mission": mission_id}
        }
        arguments: dict[str, object] = {
            "cache_output_name": cache_name,
            "cache_hash": cache_hash,
            "expected_callable_identity": callable_identity,
            "expected_evidence_subject": spec["evidence_subject"],
            "expected_output_classes": output_classes,
            "expected_study_id": study_id,
            "manifest_output_name": manifest_name,
            "manifest_hash": manifest_hash,
        }
        return writer, index, execution, arguments, completion

    def _verify(
        self,
        writer: StateWriter,
        execution: RunningJobExecution,
        arguments: dict[str, object],
    ) -> None:
        with (
            patch(
                "axiom_rift.operations.writer.WriterLock",
                side_effect=lambda _: nullcontext(),
            ),
            patch(
                "axiom_rift.operations.writer._effective_completion_scope",
                return_value=SimpleNamespace(scientific_eligible=True),
            ),
        ):
            writer.verify_reproducible_cache_producer(
                execution,
                **arguments,  # type: ignore[arg-type]
            )

    def test_exact_execution_survives_later_retry_without_success_cache(self) -> None:
        writer, index, execution, arguments, _ = self._fixture()

        self._verify(writer, execution, arguments)

        self.assertEqual(index.event_head_calls, [])
        self.assertEqual(index.fingerprint_calls, [execution.job_hash])

    def test_forged_start_or_mismatched_completion_binding_fails_closed(self) -> None:
        writer, index, execution, arguments, completion = self._fixture()
        forged_execution = RunningJobExecution(
            job_id=execution.job_id,
            job_hash=execution.job_hash,
            job_permit_id="f" * 64,
            start_record_id=execution.start_record_id,
        )
        with self.assertRaisesRegex(TransitionError, "start provenance"):
            self._verify(writer, forged_execution, arguments)

        index.replace(
            replace(
                completion,
                payload={
                    **completion.payload,
                    "start_record_id": "0" * 64,
                },
            )
        )
        with self.assertRaisesRegex(TransitionError, "completion"):
            self._verify(writer, execution, arguments)


if __name__ == "__main__":
    unittest.main()
