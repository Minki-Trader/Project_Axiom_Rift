from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.executable_axis_lineage import (
    ExecutableAxisLineageError,
    completion_executable_axis_lineage,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


class ExecutableAxisLineageTests(unittest.TestCase):
    def _records(
        self,
        *,
        job_id: str | None = None,
        registered_payload: dict[str, object] | None = None,
    ) -> tuple[tuple[IndexRecord, ...], str]:
        executable = {
            "schema": "executable_axis_lineage_fixture.v1",
            "source_contracts": [],
        }
        executable_id = "executable:" + canonical_digest(
            domain="executable", payload=executable
        )
        typed_job_id = (
            "job:" + canonical_digest(domain="fixture-job", payload={"n": 1})
            if job_id is None
            else job_id
        )
        registration_study = "STU-LINEAGE-REGISTRATION"
        completion_study = "STU-LINEAGE-COMPLETION"
        registration_axis = "axis:" + "a" * 64
        completion_axis = "axis:" + "b" * 64
        return (
            (
                IndexRecord(
                    kind="study-open",
                    record_id=registration_study,
                    subject=f"Study:{registration_study}",
                    status="closed",
                    fingerprint="1" * 64,
                    payload={
                        "mission_id": "MIS-LINEAGE",
                        "portfolio_axis_id": "axis-registration",
                        "portfolio_axis_identity": registration_axis,
                    },
                ),
                IndexRecord(
                    kind="study-open",
                    record_id=completion_study,
                    subject=f"Study:{completion_study}",
                    status="closed",
                    fingerprint="2" * 64,
                    payload={
                        "mission_id": "MIS-LINEAGE",
                        "portfolio_axis_id": "axis-completion",
                        "portfolio_axis_identity": completion_axis,
                    },
                ),
                IndexRecord(
                    kind="trial",
                    record_id=executable_id,
                    subject="Batch:BAT-LINEAGE",
                    status="evaluated",
                    fingerprint=executable_id.removeprefix("executable:"),
                    payload={
                        "executable": (
                            executable
                            if registered_payload is None
                            else registered_payload
                        ),
                        "mission_id": "MIS-LINEAGE",
                        "portfolio_axis_id": "axis-registration",
                        "portfolio_axis_identity": registration_axis,
                        "study_id": registration_study,
                    },
                ),
                IndexRecord(
                    kind="job-declared",
                    record_id=typed_job_id,
                    subject=f"Job:{typed_job_id}",
                    status="declared",
                    fingerprint="3" * 64,
                    payload={
                        "mission_id": "MIS-LINEAGE",
                        "study_id": completion_study,
                        "spec": {
                            "evidence_subject": {
                                "id": executable_id,
                                "kind": "Executable",
                            }
                        },
                    },
                ),
                IndexRecord(
                    kind="job-completed",
                    record_id="4" * 64,
                    subject=f"Job:{typed_job_id}",
                    status="success",
                    fingerprint="4" * 64,
                    payload={
                        "job_id": typed_job_id,
                        "scientific": {"executable_id": executable_id},
                    },
                ),
            ),
            executable_id,
        )

    def test_completion_axis_is_owned_by_declared_study(self) -> None:
        records, executable_id = self._records()
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                index.put_many(records)
                lineage = completion_executable_axis_lineage(index, records[-1])
        self.assertEqual(lineage.executable_id, executable_id)
        self.assertEqual(lineage.study_id, "STU-LINEAGE-COMPLETION")
        self.assertEqual(lineage.axis_id, "axis-completion")
        self.assertEqual(
            lineage.registration.study_id, "STU-LINEAGE-REGISTRATION"
        )
        self.assertEqual(lineage.registration.axis_id, "axis-registration")

    def test_forged_trial_payload_fails_closed(self) -> None:
        records, _ = self._records(
            registered_payload={
                "schema": "forged_executable_axis_lineage_fixture.v1",
                "source_contracts": [],
            }
        )
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                index.put_many(records)
                with self.assertRaisesRegex(
                    ExecutableAxisLineageError,
                    "registration axis lineage",
                ):
                    completion_executable_axis_lineage(index, records[-1])

    def test_non_identity_job_id_fails_closed(self) -> None:
        records, _ = self._records(job_id="job:not-a-sha256")
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                index.put_many(records)
                with self.assertRaisesRegex(
                    ExecutableAxisLineageError,
                    "Job id",
                ):
                    completion_executable_axis_lineage(index, records[-1])


if __name__ == "__main__":
    unittest.main()
