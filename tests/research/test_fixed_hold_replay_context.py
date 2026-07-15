from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.running_job_context import (
    RunningJobFixedHoldReplayContext,
)
from axiom_rift.operations.scientific_history import (
    project_frozen_family_exposure_context,
)
from axiom_rift.research.analog_fixed_hold_replay import (
    analog_fixed_hold_replay_configurations,
    analog_fixed_hold_replay_executable,
)
from axiom_rift.research.analog_fixed_hold_replay_job import RUNTIME_ADAPTER
from axiom_rift.research.historical_family_stu0061 import (
    STU0061_HISTORICAL_FAMILY,
)
from axiom_rift.research.historical_family_binding import (
    historical_family_from_manifest,
)
from axiom_rift.research.fixed_hold_replay_runtime import (
    registered_fixed_hold_replay_context,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex


STUDY_ID = "STU-CONTEXT"
CONTEXT = 622
STUDY_HASH = "4" * 64
BATCH_SPEC = {"study_hash": STUDY_HASH, "study_id": STUDY_ID}
BATCH_DIGEST = canonical_digest(domain="batch-spec", payload=BATCH_SPEC)
BATCH_ID = f"batch:{BATCH_DIGEST}"
WRITER_BOUND_STU0061_FAMILY = historical_family_from_manifest(
    STU0061_HISTORICAL_FAMILY.manifest()
)


class _RuntimeContext:
    prior_global_multiplicity_floor = 18

    def __init__(
        self,
        index_path: Path,
        subject_id: str,
        family_ids: tuple[str, ...],
    ) -> None:
        self.index_path = index_path
        self.subject_id = subject_id
        self.family_ids = family_ids

    def project_bound_fixed_hold_replay_context(
        self,
        *,
        study_id: str,
        batch_id: str,
        subject_executable_id: str,
        expected_family_size: int,
        parameter_name: str | None,
    ):
        assert study_id == STUDY_ID
        assert batch_id == BATCH_ID
        assert subject_executable_id == self.subject_id
        with LocalIndex(self.index_path) as index:
            with patch.object(
                index,
                "records_by_kind",
                side_effect=AssertionError("global trial scan"),
            ):
                exposure = project_frozen_family_exposure_context(
                    index.read_only(),
                    prior_global_exposure_floor=(
                        self.prior_global_multiplicity_floor
                    ),
                    study_id=study_id,
                    batch_id=batch_id,
                    expected_family_size=expected_family_size,
                    parameter_name=parameter_name,
                    allow_unregistered=False,
                )
        return RunningJobFixedHoldReplayContext(
            family_authority_id="historical-family-authority:" + "1" * 64,
            replay_obligation_id=(
                "historical-replay-obligation:" + "2" * 64
            ),
            family=WRITER_BOUND_STU0061_FAMILY,
            exposure=exposure,
            batch_family_executable_ids=tuple(sorted(self.family_ids)),
            registered_member_bindings=tuple(
                (
                    prospective_id,
                    member.historical_reference_executable_id,
                )
                for prospective_id, member in zip(
                    self.family_ids,
                    WRITER_BOUND_STU0061_FAMILY.members,
                    strict=True,
                )
            ),
            execution_prefix_executable_ids=(self.subject_id,),
            completed_member_executable_ids=(),
            target_prospective_executable_id=self.family_ids[-1],
        )


def _trial(
    *,
    executable_id: str,
    payload: dict[str, object],
    authority_sequence: int,
    stream: str | None = None,
    ordinal: int | None = None,
) -> IndexRecord:
    return IndexRecord(
        kind="trial",
        record_id=executable_id,
        subject=(f"Batch:{BATCH_ID}" if stream is not None else "Batch:prior"),
        status="evaluated",
        fingerprint=executable_id.removeprefix("executable:"),
        payload=payload,
        event_stream=stream,
        event_sequence=ordinal,
        authority_sequence=authority_sequence,
        authority_event_id=f"{authority_sequence:064x}",
        authority_offset=authority_sequence,
    )


def test_registered_context_reads_only_exact_batch_family(tmp_path: Path) -> None:
    index_path = tmp_path / "index.sqlite"
    executables = tuple(
        analog_fixed_hold_replay_executable(
            configuration,
            historical_family=WRITER_BOUND_STU0061_FAMILY,
            historical_context_prior_global_exposure_count=CONTEXT,
        )
        for configuration in analog_fixed_hold_replay_configurations(
            WRITER_BOUND_STU0061_FAMILY
        )
    )
    prior = tuple(
        _trial(
            executable_id=f"executable:{ordinal:064x}",
            payload={"study_id": "STU-PRIOR"},
            authority_sequence=ordinal,
        )
        for ordinal in range(1, CONTEXT - 18 + 1)
    )
    family = tuple(
        _trial(
            executable_id=executable.identity,
            payload={
                "executable": executable.to_identity_payload(),
                "study_id": STUDY_ID,
            },
            authority_sequence=999 + ordinal,
            stream=f"batch-trials:{BATCH_ID}",
            ordinal=ordinal,
        )
        for ordinal, executable in enumerate(executables, start=1)
    )
    study = IndexRecord(
        kind="study-open",
        record_id=STUDY_ID,
        subject=f"Study:{STUDY_ID}",
        status="open",
        fingerprint=STUDY_HASH,
        payload={"spec": {"study_id": STUDY_ID}},
    )
    batch = IndexRecord(
        kind="batch-open",
        record_id=BATCH_ID,
        subject=f"Study:{STUDY_ID}",
        status="open",
        fingerprint=BATCH_DIGEST,
        payload={"batch_hash": BATCH_DIGEST, "spec": BATCH_SPEC},
        event_stream=f"study-batches:{STUDY_ID}",
        event_sequence=1,
    )
    with LocalIndex(index_path) as index:
        index.rebuild((study, batch, *prior, *family))

    binding = {
        "batch_id": BATCH_ID,
        "execution": {
            "job_hash": "2" * 64,
            "job_id": "job:" + "1" * 64,
            "job_permit_id": "5" * 64,
            "start_record_id": "3" * 64,
        },
        "study_id": STUDY_ID,
    }
    context = registered_fixed_hold_replay_context(
        _RuntimeContext(
            index_path,
            executables[0].identity,
            tuple(item.identity for item in executables),
        ),
        adapter=RUNTIME_ADAPTER,
        binding=binding,
        subject_executable_id=executables[0].identity,
    )
    assert context.exposure.prior_global_exposure_count == CONTEXT
    assert context.family == WRITER_BOUND_STU0061_FAMILY
    assert context.exposure.family_executable_ids == tuple(
        item.identity for item in executables
    )


def test_file_is_ascii() -> None:
    Path(__file__).read_text(encoding="ascii")
