from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

import pytest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.running_job import RunningJobExecution
from axiom_rift.research.sleeve_loss_skip_risk_cache import (
    build_sleeve_loss_skip_risk_cache_provenance,
    sleeve_loss_skip_risk_family_cache,
    validate_sleeve_loss_skip_risk_cache_provenance,
    verify_sleeve_loss_skip_risk_cache_producer,
)
from axiom_rift.research.sleeve_loss_skip_risk_study import (
    build_sleeve_loss_skip_risk_job_plan,
)
from axiom_rift.research.sleeve_loss_skip_risk_trace import (
    bind_sleeve_loss_skip_risk_family_trace,
    extract_sleeve_loss_skip_risk_family_trace,
)
from tests.research.test_prospective_pair_trace import (
    MISSION_ID,
    _definition,
    _trace,
)


@dataclass(frozen=True)
class _Artifact:
    sha256: str


class _Evidence:
    def __init__(self) -> None:
        self.values: dict[str, bytes] = {}

    def finalize(self, content: bytes) -> _Artifact:
        digest = sha256(content).hexdigest()
        self.values[digest] = content
        return _Artifact(digest)

    def read_verified(self, digest: str) -> bytes:
        try:
            return self.values[digest]
        except KeyError as exc:
            raise FileNotFoundError(digest) from exc


class _Writer:
    def __init__(self) -> None:
        self.evidence = _Evidence()
        self.verification: tuple[RunningJobExecution, dict[str, object]] | None = None

    def verify_reproducible_cache_producer(
        self,
        producer: RunningJobExecution,
        **kwargs: object,
    ) -> None:
        self.verification = producer, kwargs


def _execution(character: str) -> RunningJobExecution:
    return RunningJobExecution(
        job_id="job:" + character * 64,
        job_hash=character * 64,
        start_record_id=("a" if character != "a" else "b") * 64,
        job_permit_id=("c" if character != "c" else "d") * 64,
    )


def test_family_trace_cache_roundtrip_is_producer_bound(tmp_path) -> None:
    definition = _definition()
    producer_id, consumer_id = definition.prospective_executable_ids
    producer = build_sleeve_loss_skip_risk_job_plan(
        repository_root=tmp_path,
        mission_id=MISSION_ID,
        study_id="STU-PAIR-CACHE",
        executable_id=producer_id,
        definition=definition,
    )
    consumer = build_sleeve_loss_skip_risk_job_plan(
        repository_root=tmp_path,
        mission_id=MISSION_ID,
        study_id="STU-PAIR-CACHE",
        executable_id=consumer_id,
        definition=definition,
    )
    family = extract_sleeve_loss_skip_risk_family_trace(
        _trace(definition),
        definition=definition,
    )
    rebound = bind_sleeve_loss_skip_risk_family_trace(
        family,
        definition=definition,
        mission_id=MISSION_ID,
        subject_executable_id=consumer_id,
        job_id="job:" + "3" * 64,
        job_hash="4" * 64,
    )
    assert rebound == _trace(definition)
    cache = sleeve_loss_skip_risk_family_cache(
        definition=definition,
        family_trace=family,
        produced=True,
    )
    writer = _Writer()
    cache_hash = writer.evidence.finalize(cache.content).sha256
    execution = _execution("1")
    producer_trace = bind_sleeve_loss_skip_risk_family_trace(
        family,
        definition=definition,
        mission_id=MISSION_ID,
        subject_executable_id=producer_id,
        job_id=execution.job_id,
        job_hash=execution.job_hash,
    )
    producer_trace_hash = writer.evidence.finalize(
        canonical_bytes(producer_trace)
    ).sha256
    provenance = build_sleeve_loss_skip_risk_cache_provenance(
        definition=definition,
        mission_id=MISSION_ID,
        study_id=producer.study_id,
        producer_executable_id=producer_id,
        producer_trace_output_name=producer.output_names["trace"],
        execution=execution,
        cache_sha256=cache_hash,
        producer_trace_sha256=producer_trace_hash,
    )
    provenance_hash = writer.evidence.finalize(
        canonical_bytes(provenance)
    ).sha256
    inputs = consumer.job_input_hashes(
        cache_sha256=cache_hash,
        cache_provenance_sha256=provenance_hash,
        producer_trace_sha256=producer_trace_hash,
    )
    opened, opened_provenance, opened_trace, _ = (
        verify_sleeve_loss_skip_risk_cache_producer(
            writer,
            repository_root=tmp_path,
            input_hashes=inputs,
            definition=definition,
            mission_id=MISSION_ID,
            study_id=producer.study_id,
            producer_executable_id=producer_id,
            producer_trace_output_name=producer.output_names["trace"],
            producer_expected_output_classes=(
                producer.expected_output_classes()
            ),
            expected_callable_identity="synthetic.sleeve_loss_skip.v1",
        )
    )

    assert opened.content == cache.content
    assert opened_provenance == provenance_hash
    assert opened_trace == producer_trace_hash
    assert writer.verification is not None
    assert producer.produces_family_cache is True
    assert consumer.produces_family_cache is False
    assert producer.cache_output_name in producer.expected_outputs()
    assert producer.expected_output_classes()[producer.cache_output_name] == (
        "reproducible_cache"
    )


def test_cache_provenance_rejects_cross_study_reuse() -> None:
    definition = _definition()
    producer_id = definition.prospective_executable_ids[0]
    execution = _execution("1")
    provenance = build_sleeve_loss_skip_risk_cache_provenance(
        definition=definition,
        mission_id=MISSION_ID,
        study_id="STU-PAIR-CACHE",
        producer_executable_id=producer_id,
        producer_trace_output_name="scientific/STU-PAIR-CACHE/trace.json",
        execution=execution,
        cache_sha256="5" * 64,
        producer_trace_sha256="6" * 64,
    )

    with pytest.raises(ValueError, match="out of scope"):
        validate_sleeve_loss_skip_risk_cache_provenance(
            provenance,
            definition=definition,
            mission_id=MISSION_ID,
            study_id="STU-OTHER",
            producer_trace_output_name="scientific/STU-PAIR-CACHE/trace.json",
        )
