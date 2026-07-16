from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.scientific_history import (
    HistoricalFamilyMemberExpectation,
    ScientificHistoryProjectionError,
    project_frozen_family_exposure_context,
    project_historical_batch_family_observation,
    project_historical_family_end_global_exposure_count,
    project_study_job_evidence,
)
from axiom_rift.operations.writer import StateWriter
from axiom_rift.research.historical_family_binding import (
    ControlBinding,
    HistoricalFamilySpec,
    HistoricalMemberSpec,
)
from axiom_rift.research.replay_exposure import (
    derive_frozen_family_exposure_context,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


STUDY_ID = "STU-TEST"
BATCH_ID = "batch:test"
JOB_ONE = "job:one"
JOB_TWO = "job:two"
COMPLETION_ONE = "completion-one"
COMPLETION_TWO = "completion-two"
MEMORY_ONE = "negative-memory:one"


def record(
    *,
    kind: str,
    record_id: str,
    subject: str,
    status: str,
    fingerprint: str,
    payload: dict[str, object],
    stream: str | None = None,
    sequence: int | None = None,
) -> IndexRecord:
    return IndexRecord(
        kind=kind,
        record_id=record_id,
        subject=subject,
        status=status,
        fingerprint=fingerprint,
        payload=payload,
        event_stream=stream,
        event_sequence=sequence,
    )


class _NoGlobalKindScan:
    def __init__(self, index: LocalIndex) -> None:
        self.index = index
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def __getattr__(self, name: str):
        value = getattr(self.index, name)

        def call(*args: object, **kwargs: object):
            if name == "records_by_kind":
                raise AssertionError("Study projection performed a global kind scan")
            self.calls.append((name, args))
            return value(*args, **kwargs)

        return call


class ScientificHistoryProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "index.sqlite"

    @staticmethod
    def _populate(index: LocalIndex) -> IndexRecord:
        close = record(
            kind="study-close",
            record_id="study-close:test",
            subject=f"Study:{STUDY_ID}",
            status="not_supported",
            fingerprint="close-fingerprint",
            payload={"study_kpi_record_id": "study-kpi:test"},
        )
        records = (
            close,
            record(
                kind="study-kpi",
                record_id="study-kpi:test",
                subject=f"Study:{STUDY_ID}",
                status="failed",
                fingerprint="kpi-fingerprint",
                payload={"completion_record_id": COMPLETION_ONE},
            ),
            record(
                kind="batch-open",
                record_id=BATCH_ID,
                subject=f"Study:{STUDY_ID}",
                status="open",
                fingerprint="batch-fingerprint",
                payload={},
                stream=f"study-batches:{STUDY_ID}",
                sequence=1,
            ),
            record(
                kind="batch-close",
                record_id="batch-close:test",
                subject=f"Batch:{BATCH_ID}",
                status="completed",
                fingerprint="batch-close-fingerprint",
                payload={},
            ),
            record(
                kind="batch-budget-reservation",
                record_id="reservation-one",
                subject=f"Batch:{BATCH_ID}",
                status="reserved",
                fingerprint="reservation-one-fingerprint",
                payload={"job_id": JOB_ONE},
                stream=f"batch-budget:{BATCH_ID}",
                sequence=1,
            ),
            record(
                kind="batch-budget-reservation",
                record_id="reservation-two",
                subject=f"Batch:{BATCH_ID}",
                status="reserved",
                fingerprint="reservation-two-fingerprint",
                payload={"job_id": JOB_TWO},
                stream=f"batch-budget:{BATCH_ID}",
                sequence=2,
            ),
            record(
                kind="batch-budget-repair",
                record_id="budget-repair:test",
                subject=f"Batch:{BATCH_ID}",
                status="repaired",
                fingerprint="budget-repair-fingerprint",
                payload={},
                stream=f"batch-budget:{BATCH_ID}",
                sequence=3,
            ),
            record(
                kind="job-declared",
                record_id=JOB_ONE,
                subject=f"Batch:{BATCH_ID}",
                status="declared",
                fingerprint="job-one-fingerprint",
                payload={"batch_id": BATCH_ID, "study_id": STUDY_ID},
                stream="job-attempt:one",
                sequence=1,
            ),
            record(
                kind="job-completed",
                record_id=COMPLETION_ONE,
                subject=f"Job:{JOB_ONE}",
                status="failed",
                fingerprint="completion-one-fingerprint",
                payload={"job_id": JOB_ONE},
                stream="job-attempt:one",
                sequence=2,
            ),
            record(
                kind="job-evidence-decision",
                record_id="decision-one",
                subject=f"Job:{JOB_ONE}",
                status="continue_batch",
                fingerprint="completion-one-fingerprint",
                payload={
                    "completion_record_id": COMPLETION_ONE,
                    "negative_memory_id": MEMORY_ONE,
                },
            ),
            record(
                kind="negative-memory",
                record_id=MEMORY_ONE,
                subject="Executable:one",
                status="recorded",
                fingerprint="memory-one-fingerprint",
                payload={
                    "evidence_references": [COMPLETION_ONE],
                    "study_id": STUDY_ID,
                },
            ),
            record(
                kind="job-declared",
                record_id=JOB_TWO,
                subject=f"Batch:{BATCH_ID}",
                status="declared",
                fingerprint="job-two-fingerprint",
                payload={"batch_id": BATCH_ID, "study_id": STUDY_ID},
                stream="job-attempt:two",
                sequence=1,
            ),
            record(
                kind="job-completed",
                record_id=COMPLETION_TWO,
                subject=f"Job:{JOB_TWO}",
                status="success",
                fingerprint="completion-two-fingerprint",
                payload={"job_id": JOB_TWO},
                stream="job-attempt:two",
                sequence=2,
            ),
            record(
                kind="job-evidence-decision",
                record_id="decision-two",
                subject=f"Job:{JOB_TWO}",
                status="stop_batch",
                fingerprint="completion-two-fingerprint",
                payload={
                    "completion_record_id": COMPLETION_TWO,
                    "negative_memory_id": None,
                },
            ),
            record(
                kind="job-declared",
                record_id="job:decoy",
                subject="Batch:decoy",
                status="declared",
                fingerprint="decoy-job-fingerprint",
                payload={"batch_id": "batch:decoy", "study_id": "STU-DECOY"},
            ),
            record(
                kind="job-completed",
                record_id="completion-decoy",
                subject="Job:job:decoy",
                status="failed",
                fingerprint="decoy-completion-fingerprint",
                payload={"job_id": "job:decoy"},
            ),
            record(
                kind="negative-memory",
                record_id="negative-memory:decoy",
                subject="Executable:decoy",
                status="recorded",
                fingerprint="decoy-memory-fingerprint",
                payload={"study_id": "STU-DECOY"},
            ),
        )
        index.rebuild(records)
        return close

    @staticmethod
    def _legacy_basis(
        index: LocalIndex,
        close: IndexRecord,
    ) -> list[dict[str, str]]:
        references = {
            ("study-close", close.record_id),
            ("study-kpi", "study-kpi:test"),
            ("job-completed", COMPLETION_ONE),
            ("batch-open", BATCH_ID),
            ("batch-close", "batch-close:test"),
        }
        for completion in index.records_by_kind("job-completed"):
            declaration = index.get(
                "job-declared", completion.payload.get("job_id", "")
            )
            if declaration is not None and declaration.payload.get(
                "study_id"
            ) == STUDY_ID:
                references.add(("job-completed", completion.record_id))
        for memory in index.records_by_kind("negative-memory"):
            if memory.payload.get("study_id") == STUDY_ID:
                references.add(("negative-memory", memory.record_id))
        return [
            {"kind": kind, "record_id": record_id}
            for kind, record_id in sorted(references)
        ]

    def test_writer_basis_is_legacy_equivalent_without_global_scan(self) -> None:
        with LocalIndex(self.path) as index:
            close = self._populate(index)
            expected = self._legacy_basis(index, close)
            bounded = _NoGlobalKindScan(index)
            actual = StateWriter._study_diagnosis_evidence_basis(
                bounded,
                study_id=STUDY_ID,
                close_record=close,
            )
            self.assertEqual(actual, expected)
            names = [name for name, _args in bounded.calls]
            self.assertEqual(names.count("records_by_fingerprint"), 2)
            self.assertNotIn("records_by_kind", names)
            self.assertTrue(
                all(
                    any(part == "SEARCH:records" for part in shape)
                    for shape in (
                        index.hot_query_access_shape(
                            "event_record_by_position",
                            (f"batch-budget:{BATCH_ID}", 1),
                        ),
                        index.hot_query_access_shape(
                            "records_by_fingerprint",
                            ("completion-one-fingerprint",),
                        ),
                        index.hot_query_access_shape(
                            "records_by_subject_status",
                            (f"Batch:{BATCH_ID}", "completed"),
                        ),
                    )
                )
            )

    def test_projection_rejects_a_reservation_without_declaration(self) -> None:
        with LocalIndex(self.path) as index:
            index.rebuild(
                (
                    record(
                        kind="batch-open",
                        record_id=BATCH_ID,
                        subject=f"Study:{STUDY_ID}",
                        status="open",
                        fingerprint="batch-fingerprint",
                        payload={},
                        stream=f"study-batches:{STUDY_ID}",
                        sequence=1,
                    ),
                    record(
                        kind="batch-budget-reservation",
                        record_id="reservation-missing",
                        subject=f"Batch:{BATCH_ID}",
                        status="reserved",
                        fingerprint="reservation-missing-fingerprint",
                        payload={"job_id": "job:missing"},
                        stream=f"batch-budget:{BATCH_ID}",
                        sequence=1,
                    ),
                )
            )
            with self.assertRaisesRegex(
                ScientificHistoryProjectionError,
                "exact declaration",
            ):
                project_study_job_evidence(index, study_id=STUDY_ID)

    def test_continuation_rejects_two_jobs_for_one_batch_member(self) -> None:
        executable_id = "executable:" + "a" * 64
        batch_id = "batch:" + "b" * 64
        job_one = "job:" + "c" * 64
        job_two = "job:" + "d" * 64
        completion_one = "1" * 64
        completion_two = "2" * 64
        job_records = []
        for sequence, job_id, completion_id, fingerprint in (
            (1, job_one, completion_one, "e" * 64),
            (2, job_two, completion_two, "f" * 64),
        ):
            job_records.extend(
                (
                    record(
                        kind="batch-budget-reservation",
                        record_id=f"reservation-{sequence}",
                        subject=f"Batch:{batch_id}",
                        status="reserved",
                        fingerprint=fingerprint,
                        payload={"job_id": job_id},
                        stream=f"batch-budget:{batch_id}",
                        sequence=sequence,
                    ),
                    record(
                        kind="job-declared",
                        record_id=job_id,
                        subject=f"Job:{job_id}",
                        status="declared",
                        fingerprint=fingerprint,
                        payload={
                            "batch_id": batch_id,
                            "spec": {
                                "evidence_subject": {
                                    "kind": "Executable",
                                    "id": executable_id,
                                }
                            },
                        },
                        stream=f"job-attempt:{sequence}",
                        sequence=1,
                    ),
                    record(
                        kind="job-completed",
                        record_id=completion_id,
                        subject=f"Job:{job_id}",
                        status="success",
                        fingerprint=fingerprint,
                        payload={
                            "job_id": job_id,
                            "output_classes": {},
                            "outputs": {},
                        },
                        stream=f"job-attempt:{sequence}",
                        sequence=2,
                    ),
                    record(
                        kind="job-evidence-decision",
                        record_id=f"decision-{sequence}",
                        subject=f"Job:{job_id}",
                        status="continue_batch",
                        fingerprint=fingerprint,
                        payload={"completion_record_id": completion_id},
                    ),
                )
            )
        with LocalIndex(self.path) as index:
            index.rebuild(
                (
                    record(
                        kind="batch-open",
                        record_id=batch_id,
                        subject=f"Study:{STUDY_ID}",
                        status="open",
                        fingerprint="b" * 64,
                        payload={
                            "spec": {
                                "acceptance_profile": {},
                                "study_hash": "9" * 64,
                            }
                        },
                    ),
                    record(
                        kind="trial",
                        record_id=executable_id,
                        subject=f"Batch:{batch_id}",
                        status="evaluated",
                        fingerprint="a" * 64,
                        payload={},
                        stream=f"batch-trials:{batch_id}",
                        sequence=1,
                    ),
                    *job_records,
                )
            )
            bounded = _NoGlobalKindScan(index)
            with self.assertRaisesRegex(
                RuntimeError,
                "exactly one completed Job per Batch member",
            ):
                StateWriter._batch_continuation_bindings(
                    bounded,
                    batch_id,
                )
            self.assertNotIn(
                "records_by_kind",
                [name for name, _args in bounded.calls],
            )

    @staticmethod
    def _populate_fixed_hold_family(
        index: LocalIndex,
        *,
        prior_trial_count: int,
        later_trial_count: int,
    ) -> tuple[int, str, tuple[str, ...]]:
        parameter_name = "historical_context_prior_global_exposure_count"
        floor = 18
        frozen_count = floor + prior_trial_count
        family_ids = tuple(
            f"executable:{10_000 + ordinal:064x}" for ordinal in range(1, 5)
        )
        study_hash = "9" * 64
        batch_spec = {
            "acceptance_profile": {
                "concurrent_family": {
                    "evaluation_mode": "vectorized",
                    "executable_ids": list(family_ids),
                    "family_size": len(family_ids),
                    "schema": "concurrent_family_manifest.v1",
                }
            },
            "adaptive_basis": {
                "causal_complexity": "fixture",
                "compute_cost": "fixture",
                "expected_information_value": "fixture",
                "portfolio_opportunity_cost": "fixture",
                "surface_curvature": "fixture",
                "uncertainty": "fixture",
            },
            "max_compute_seconds": 4,
            "max_trials": len(family_ids),
            "max_wall_seconds": 4,
            "schema": "batch_spec.v1",
            "source_contract_ids": [],
            "stop_rule": "fixed hold fixture",
            "study_hash": study_hash,
        }
        batch_digest = canonical_digest(domain="batch-spec", payload=batch_spec)
        batch_id = f"batch:{batch_digest}"
        study = record(
            kind="study-open",
            record_id=STUDY_ID,
            subject=f"Study:{STUDY_ID}",
            status="open",
            fingerprint=study_hash,
            payload={},
        )
        batch = record(
            kind="batch-open",
            record_id=batch_id,
            subject=f"Study:{STUDY_ID}",
            status="open",
            fingerprint=batch_digest,
            payload={"batch_hash": batch_digest, "spec": batch_spec},
            stream=f"study-batches:{STUDY_ID}",
            sequence=1,
        )
        prior = tuple(
            IndexRecord(
                kind="trial",
                record_id=f"executable:{ordinal:064x}",
                subject="Batch:prior",
                status="evaluated",
                fingerprint=f"{ordinal:064x}",
                payload={"study_id": "STU-PRIOR"},
                authority_sequence=ordinal,
                authority_event_id=f"{ordinal:064x}",
                authority_offset=ordinal,
            )
            for ordinal in range(1, prior_trial_count + 1)
        )
        first_family_sequence = prior_trial_count + 100
        family = tuple(
            IndexRecord(
                kind="trial",
                record_id=executable_id,
                subject=f"Batch:{batch_id}",
                status="evaluated",
                fingerprint=executable_id.removeprefix("executable:"),
                payload={
                    "executable": {
                        "parameters": {parameter_name: frozen_count}
                    },
                    "study_id": STUDY_ID,
                },
                event_stream=f"batch-trials:{batch_id}",
                event_sequence=ordinal,
                authority_sequence=first_family_sequence + ordinal - 1,
                authority_event_id=f"{first_family_sequence + ordinal - 1:064x}",
                authority_offset=first_family_sequence + ordinal - 1,
            )
            for ordinal, executable_id in enumerate(family_ids, start=1)
        )
        later = tuple(
            IndexRecord(
                kind="trial",
                record_id=f"executable:{20_000 + ordinal:064x}",
                subject="Batch:later",
                status="evaluated",
                fingerprint=f"{20_000 + ordinal:064x}",
                payload={"study_id": "STU-LATER"},
                authority_sequence=first_family_sequence + 100 + ordinal,
                authority_event_id=(
                    f"{first_family_sequence + 100 + ordinal:064x}"
                ),
                authority_offset=first_family_sequence + 100 + ordinal,
            )
            for ordinal in range(1, later_trial_count + 1)
        )
        index.rebuild((study, batch, *prior, *family, *later))
        return frozen_count, batch_id, family_ids

    def test_fixed_hold_family_projection_matches_legacy_without_global_scan(
        self,
    ) -> None:
        parameter_name = "historical_context_prior_global_exposure_count"
        with LocalIndex(self.path) as index:
            frozen_count, batch_id, family_ids = (
                self._populate_fixed_hold_family(
                    index,
                    prior_trial_count=37,
                    later_trial_count=211,
                )
            )
            legacy = derive_frozen_family_exposure_context(
                trials=index.records_by_kind("trial"),
                prior_global_exposure_floor=18,
                study_id=STUDY_ID,
                expected_family_size=4,
                parameter_name=parameter_name,
                allow_unregistered=False,
            )
            with patch.object(
                index,
                "records_by_kind",
                side_effect=AssertionError("global trial scan"),
            ):
                projected = project_frozen_family_exposure_context(
                    index.read_only(),
                    prior_global_exposure_floor=18,
                    study_id=STUDY_ID,
                    batch_id=batch_id,
                    expected_family_size=4,
                    parameter_name=parameter_name,
                    allow_unregistered=False,
                )

            self.assertEqual(projected, legacy)
            self.assertEqual(projected.prior_global_exposure_count, frozen_count)
            self.assertEqual(projected.family_executable_ids, family_ids)
            details = index.count_by_kind_before_authority_sequence_access_shape(
                "trial",
                projected.first_family_authority_sequence,
            )
            self.assertTrue(
                any("ix_records_kind_authority_sequence" in item for item in details)
            )

    def test_fixed_hold_projection_decodes_constant_rows_as_history_grows(self) -> None:
        parameter_name = "historical_context_prior_global_exposure_count"

        def project(prior_trial_count: int) -> tuple[int, int]:
            path = Path(self.temporary.name) / f"scale-{prior_trial_count}.sqlite"
            validated: list[str] = []
            with LocalIndex(
                path,
                authority_validator=lambda item: validated.append(item.record_id),
            ) as index:
                frozen_count, batch_id, _family_ids = (
                    self._populate_fixed_hold_family(
                        index,
                        prior_trial_count=prior_trial_count,
                        later_trial_count=0,
                    )
                )
                validated.clear()
                context = project_frozen_family_exposure_context(
                    index,
                    prior_global_exposure_floor=18,
                    study_id=STUDY_ID,
                    batch_id=batch_id,
                    expected_family_size=4,
                    parameter_name=parameter_name,
                    allow_unregistered=False,
                )
                self.assertEqual(
                    context.prior_global_exposure_count,
                    frozen_count,
                )
                return len(validated), index.count_by_kind("trial")

        small_decodes, small_history = project(8)
        large_decodes, large_history = project(5_000)
        self.assertEqual(small_decodes, large_decodes)
        self.assertLessEqual(large_decodes, 8)
        self.assertEqual((small_history, large_history), (12, 5_004))

    def test_unregistered_family_uses_kind_count_without_trial_payload_reads(
        self,
    ) -> None:
        with LocalIndex(self.path) as index:
            self._populate_fixed_hold_family(
                index,
                prior_trial_count=125,
                later_trial_count=0,
            )
            index.rebuild(
                tuple(
                    value
                    for value in index.records_by_kind("trial")
                    if value.payload.get("study_id") != STUDY_ID
                )
            )
            with patch.object(
                index,
                "records_by_kind",
                side_effect=AssertionError("global trial scan"),
            ):
                context = project_frozen_family_exposure_context(
                    index,
                    prior_global_exposure_floor=18,
                    study_id="STU-FUTURE",
                    batch_id=None,
                    expected_family_size=4,
                    parameter_name=(
                        "historical_context_prior_global_exposure_count"
                    ),
                    allow_unregistered=True,
                )
            self.assertEqual(context.prior_global_exposure_count, 143)
            self.assertEqual(context.family_executable_ids, ())
            self.assertIsNone(context.first_family_authority_sequence)

    @staticmethod
    def _populate_historical_observation_family(
        index: LocalIndex,
        *,
        exposure_count: int,
        drift_ordinal: int | None = None,
    ) -> tuple[
        tuple[HistoricalFamilyMemberExpectation, ...],
        tuple[str, ...],
    ]:
        floor = 18
        prior_count = exposure_count - floor
        expectations = tuple(
            HistoricalFamilyMemberExpectation(
                configuration_id=f"configuration-{ordinal}",
                historical_reference_executable_id=(
                    f"executable:{10_000 + ordinal:064x}"
                ),
            )
            for ordinal in range(1, 5)
        )
        executable_payloads = tuple(
            {
                "clock_contract": "clock:historical",
                "component_identities": [
                    f"component:{20_000 + ordinal:064x}"
                ],
                "component_manifests": [],
                "cost_contract": "cost:historical",
                "data_contract": "data:historical",
                "engine_contract": f"engine:historical:{ordinal}",
                "parameters": {
                    "configuration_id": expectation.configuration_id,
                    "fixed_exposure_count": (
                        exposure_count + 1
                        if drift_ordinal == ordinal
                        else exposure_count
                    ),
                    "historical_reference_executable_id": (
                        expectation.historical_reference_executable_id
                    ),
                },
                "schema": "executable_spec.v1",
                "source_contracts": [],
                "split_contract": "split:historical",
            }
            for ordinal, expectation in enumerate(expectations, start=1)
        )
        executable_ids = tuple(
            "executable:"
            + canonical_digest(domain="executable", payload=payload)
            for payload in executable_payloads
        )
        batch_spec = {
            "acceptance_profile": {
                "concurrent_family": {
                    "evaluation_mode": "vectorized",
                    "executable_ids": list(executable_ids),
                    "family_size": 4,
                    "schema": "concurrent_family_manifest.v1",
                }
            },
            "adaptive_basis": {
                "causal_complexity": "fixture",
                "compute_cost": "fixture",
                "expected_information_value": "fixture",
                "portfolio_opportunity_cost": "fixture",
                "surface_curvature": "fixture",
                "uncertainty": "fixture",
            },
            "max_compute_seconds": 4,
            "max_trials": 4,
            "max_wall_seconds": 4,
            "schema": "batch_spec.v1",
            "source_contract_ids": [],
            "stop_rule": "exact historical family",
            "study_hash": "9" * 64,
        }
        batch_id = "batch:" + canonical_digest(
            domain="batch-spec", payload=batch_spec
        )
        prior = tuple(
            IndexRecord(
                kind="trial",
                record_id=f"executable:{ordinal:064x}",
                subject="Batch:prior",
                status="evaluated",
                fingerprint=f"{ordinal:064x}",
                payload={"study_id": "STU-PRIOR"},
                authority_sequence=ordinal,
                authority_event_id=f"{ordinal:064x}",
                authority_offset=ordinal,
            )
            for ordinal in range(1, prior_count + 1)
        )
        first_sequence = prior_count + 100
        family = tuple(
            IndexRecord(
                kind="trial",
                record_id=executable_id,
                subject=f"Batch:{batch_id}",
                status="evaluated",
                fingerprint=executable_id.removeprefix("executable:"),
                payload={
                    "executable": payload,
                    "study_id": STUDY_ID,
                },
                event_stream=f"batch-trials:{batch_id}",
                event_sequence=ordinal,
                authority_sequence=first_sequence + ordinal - 1,
                authority_event_id=f"{first_sequence + ordinal - 1:064x}",
                authority_offset=first_sequence + ordinal - 1,
            )
            for ordinal, (executable_id, payload) in enumerate(
                zip(executable_ids, executable_payloads, strict=True),
                start=1,
            )
        )
        batch = IndexRecord(
            kind="batch-open",
            record_id=batch_id,
            subject=f"Study:{STUDY_ID}",
            status="open",
            fingerprint=batch_id.removeprefix("batch:"),
            payload={"spec": batch_spec},
            event_stream=f"study-batches:{STUDY_ID}",
            event_sequence=1,
            authority_sequence=first_sequence - 1,
            authority_event_id=f"{first_sequence - 1:064x}",
            authority_offset=first_sequence - 1,
        )
        index.rebuild((batch, *prior, *family))
        return expectations, executable_ids

    def test_historical_family_projection_is_bounded_and_immutable(self) -> None:
        with LocalIndex(self.path) as index:
            expectations, executable_ids = (
                self._populate_historical_observation_family(
                    index,
                    exposure_count=574,
                )
            )
            with patch.object(
                index,
                "records_by_kind",
                side_effect=AssertionError("global trial scan"),
            ):
                observation = project_historical_batch_family_observation(
                    index.read_only(),
                    prior_global_exposure_floor=18,
                    study_id=STUDY_ID,
                    batch_id=None,
                    expected_members=expectations,
                    expected_prior_global_exposure_count=574,
                    exposure_parameter_name="fixed_exposure_count",
                )
            self.assertEqual(observation.family_executable_ids, executable_ids)
            self.assertEqual(observation.prior_global_exposure_count, 574)
            self.assertEqual(
                tuple(member.ordinal for member in observation.members),
                (1, 2, 3, 4),
            )
            detached = observation.members[0].to_identity_payload()
            detached["engine_contract"] = "engine:forged"
            self.assertNotEqual(
                observation.members[0].to_identity_payload()["engine_contract"],
                "engine:forged",
            )

    def test_historical_family_projection_rejects_slot_or_exposure_drift(
        self,
    ) -> None:
        with LocalIndex(self.path) as index:
            expectations, _ids = self._populate_historical_observation_family(
                index,
                exposure_count=574,
                drift_ordinal=3,
            )
            with self.assertRaisesRegex(
                ScientificHistoryProjectionError,
                "exposure parameter drifted",
            ):
                project_historical_batch_family_observation(
                    index,
                    prior_global_exposure_floor=18,
                    study_id=STUDY_ID,
                    batch_id=None,
                    expected_members=expectations,
                    expected_prior_global_exposure_count=574,
                    exposure_parameter_name="fixed_exposure_count",
                )
            reordered = (expectations[1], expectations[0], *expectations[2:])
            with self.assertRaisesRegex(
                ScientificHistoryProjectionError,
                "semantic slot",
            ):
                project_historical_batch_family_observation(
                    index,
                    prior_global_exposure_floor=18,
                    study_id=STUDY_ID,
                    batch_id=None,
                    expected_members=reordered,
                    expected_prior_global_exposure_count=574,
                    exposure_parameter_name=None,
                )

    @staticmethod
    def _populate_original_family_end_projection(
        index: LocalIndex,
        *,
        interleaved: bool = False,
        mismatched_member: bool = False,
    ) -> tuple[HistoricalFamilySpec, int]:
        study_id = "STU-7001"
        floor = 18
        prior_count = 7
        executable_payloads = tuple(
            {
                "clock_contract": "clock:historical",
                "component_identities": [],
                "component_manifests": [],
                "cost_contract": "cost:historical",
                "data_contract": "data:historical",
                "engine_contract": f"engine:historical:{ordinal}",
                "parameters": {
                    "configuration_id": f"configuration-{ordinal}",
                    "fixture_slot": ordinal,
                },
                "schema": "executable_spec.v1",
                "source_contracts": [],
                "split_contract": "split:historical",
            }
            for ordinal in range(1, 5)
        )
        executable_ids = tuple(
            "executable:"
            + canonical_digest(domain="executable", payload=payload)
            for payload in executable_payloads
        )
        batch_spec = {
            "acceptance_profile": {},
            "adaptive_basis": {
                "causal_complexity": "fixture",
                "compute_cost": "fixture",
                "expected_information_value": "fixture",
                "portfolio_opportunity_cost": "fixture",
                "surface_curvature": "fixture",
                "uncertainty": "fixture",
            },
            "max_compute_seconds": 4,
            "max_trials": 4,
            "max_wall_seconds": 4,
            "schema": "batch_spec.v1",
            "source_contract_ids": [],
            "stop_rule": "exact original family",
            "study_hash": "9" * 64,
        }
        batch_digest = canonical_digest(domain="batch-spec", payload=batch_spec)
        batch_id = f"batch:{batch_digest}"
        members = tuple(
            HistoricalMemberSpec(
                ordinal=ordinal,
                configuration_id=f"configuration-{ordinal}",
                historical_reference_executable_id=executable_ids[ordinal - 1],
                parameters=executable_payloads[ordinal - 1]["parameters"],
            )
            for ordinal in range(1, 5)
        )
        opposite_indices = (1, 0, 3, 2)
        feature_indices = (2, 2, 0, 0)
        family = HistoricalFamilySpec(
            original_study_id=study_id,
            original_batch_id=batch_id,
            target_historical_executable_id=executable_ids[-1],
            members=members,
            controls=tuple(
                ControlBinding(
                    subject_historical_executable_id=executable_id,
                    opposite_historical_executable_id=(
                        executable_ids[opposite_indices[index]]
                    ),
                    feature_historical_executable_ids=(
                        executable_ids[feature_indices[index]],
                    ),
                )
                for index, executable_id in enumerate(executable_ids)
            ),
        )
        batch = IndexRecord(
            kind="batch-open",
            record_id=batch_id,
            subject=f"Study:{study_id}",
            status="open",
            fingerprint=batch_digest,
            payload={"spec": batch_spec},
            event_stream=f"study-batches:{study_id}",
            event_sequence=1,
            authority_sequence=90,
            authority_event_id=f"{90:064x}",
            authority_offset=90,
        )
        prior = tuple(
            IndexRecord(
                kind="trial",
                record_id=f"executable:{ordinal:064x}",
                subject="Batch:prior",
                status="evaluated",
                fingerprint=f"{ordinal:064x}",
                payload={"study_id": "STU-PRIOR"},
                authority_sequence=ordinal,
                authority_event_id=f"{ordinal:064x}",
                authority_offset=ordinal,
            )
            for ordinal in range(1, prior_count + 1)
        )
        family_sequences = (100, 102, 103, 104) if interleaved else (
            100,
            101,
            102,
            103,
        )
        family_trials = []
        for ordinal, (executable_id, payload, sequence) in enumerate(
            zip(
                executable_ids,
                executable_payloads,
                family_sequences,
                strict=True,
            ),
            start=1,
        ):
            if mismatched_member and ordinal == 3:
                payload = {**payload, "engine_contract": "engine:attacked"}
                executable_id = "executable:" + canonical_digest(
                    domain="executable", payload=payload
                )
            family_trials.append(
                IndexRecord(
                    kind="trial",
                    record_id=executable_id,
                    subject=f"Batch:{batch_id}",
                    status="evaluated",
                    fingerprint=executable_id.removeprefix("executable:"),
                    payload={"executable": payload, "study_id": study_id},
                    event_stream=f"batch-trials:{batch_id}",
                    event_sequence=ordinal,
                    authority_sequence=sequence,
                    authority_event_id=f"{sequence:064x}",
                    authority_offset=sequence,
                )
            )
        interleaved_trial = (
            IndexRecord(
                kind="trial",
                record_id="executable:" + "f" * 64,
                subject="Batch:interleaved",
                status="evaluated",
                fingerprint="f" * 64,
                payload={"study_id": "STU-INTERLEAVED"},
                authority_sequence=101,
                authority_event_id=f"{101:064x}",
                authority_offset=101,
            ),
        ) if interleaved else ()
        index.rebuild((batch, *prior, *family_trials, *interleaved_trial))
        return family, floor + prior_count + family.family_size

    def test_original_family_end_is_derived_from_exact_global_trial_order(
        self,
    ) -> None:
        with LocalIndex(self.path) as index:
            family, expected = self._populate_original_family_end_projection(
                index
            )
            with patch.object(
                index,
                "records_by_kind",
                side_effect=AssertionError("global trial scan"),
            ):
                actual = project_historical_family_end_global_exposure_count(
                    index.read_only(),
                    prior_global_exposure_floor=18,
                    family=family,
                )
            self.assertEqual(actual, expected)

    def test_original_family_end_rejects_interleaving_and_member_mismatch(
        self,
    ) -> None:
        for attack, message in (
            ("interleaved", "interleaved global trial"),
            ("mismatched", "member is malformed"),
            ("wrong-batch", "original Batch authority"),
        ):
            with self.subTest(attack=attack):
                path = Path(self.temporary.name) / f"{attack}.sqlite"
                with LocalIndex(path) as index:
                    family, _expected = (
                        self._populate_original_family_end_projection(
                            index,
                            interleaved=attack == "interleaved",
                            mismatched_member=attack == "mismatched",
                        )
                    )
                    if attack == "wrong-batch":
                        family = HistoricalFamilySpec(
                            original_study_id=family.original_study_id,
                            original_batch_id="batch:" + "0" * 64,
                            target_historical_executable_id=(
                                family.target_historical_executable_id
                            ),
                            members=family.members,
                            controls=family.controls,
                        )
                    with self.assertRaisesRegex(
                        ScientificHistoryProjectionError,
                        message,
                    ):
                        project_historical_family_end_global_exposure_count(
                            index.read_only(),
                            prior_global_exposure_floor=18,
                            family=family,
                        )


if __name__ == "__main__":
    unittest.main()
