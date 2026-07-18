from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256

import pytest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.running_job import RunningJobExecution
from axiom_rift.research.cost_aware_execution_pair import (
    cost_aware_execution_pair_historical_context,
    cost_aware_execution_pair_producer_implementation_identities,
    cost_aware_execution_pair_protocol_definition,
)
from axiom_rift.research.cost_aware_execution_pair_engine import (
    COST_AWARE_EXECUTION_PAIR_PRODUCER_MANIFEST_SCHEMA,
)
from axiom_rift.research.cost_aware_execution_pair_job import (
    CostAwareExecutionPairJobPlan,
    build_cost_aware_execution_pair_cache_provenance,
    build_cost_aware_execution_pair_job_plan,
    cost_aware_execution_pair_cache,
    materialize_cost_aware_execution_pair_evidence,
    verify_cost_aware_execution_pair_cache_producer,
)
from axiom_rift.research.cost_aware_execution_protocol import (
    COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT,
)
from axiom_rift.research.cost_aware_execution_trace import (
    compute_cost_aware_execution_pair_trace,
)
from axiom_rift.research.discovery import (
    DATASET_SHA256,
    OBSERVED_MATERIAL_ID,
    ROLLING_SPLIT_SHA256,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyReplayContext,
)
from axiom_rift.research.historical_family_stu0070 import (
    STU0070_HISTORICAL_FAMILY,
)
from axiom_rift.research.replay_family_job import ReplayFamilyJobPlan


_START = datetime(2026, 1, 1)


def _index(value: datetime) -> int:
    return int((value - _START).total_seconds() // 300)


def _time(index: int) -> datetime:
    return _START + timedelta(minutes=5 * index)


def _replay_context() -> HistoricalFamilyReplayContext:
    return HistoricalFamilyReplayContext(
        family_authority_id=(
            "historical-family-authority:" + "a" * 64
        ),
        replay_obligation_id=(
            "historical-replay-obligation:" + "b" * 64
        ),
        family=STU0070_HISTORICAL_FAMILY,
        prior_global_exposure_count=700,
        original_family_end_global_exposure_count=(
            COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
        ),
    )


def _plans() -> tuple[CostAwareExecutionPairJobPlan, ...]:
    context = _replay_context()
    definition = cost_aware_execution_pair_protocol_definition(context)
    return tuple(
        build_cost_aware_execution_pair_job_plan(
            mission_id="MIS-SYNTHETIC",
            study_id="STU-SYNTHETIC",
            executable_id=executable_id,
            historical_context_prior_global_exposure_count=(
                context.prior_global_exposure_count
            ),
            original_family_end_global_exposure_count=(
                context.original_family_end_global_exposure_count
            ),
            historical_family=context.family,
            historical_family_authority_id=context.family_authority_id,
            replay_obligation_id=context.replay_obligation_id,
        )
        for executable_id in definition.prospective_executable_ids
    )


def _trace(plan: CostAwareExecutionPairJobPlan) -> dict[str, object]:
    decisions = [
        _index(datetime(2026, 1, 4, 12)),
        _index(datetime(2026, 1, 31, 22)),
    ]
    required: set[int] = set()
    for decision in decisions:
        start = max(0, decision - 576)
        required.update(range(max(0, start - 1), decision + 50))
    sources = [
        {
            "bar_index": index,
            "bar_open_time": _time(index).isoformat(timespec="seconds"),
            "open_micropoints": 100_000_000 + index * 1_000,
            "raw_spread_millipoints": (
                2_000 if index == decisions[0] else 1_000
            ),
        }
        for index in sorted(required)
    ]
    candidates = [
        {
            "decision_bar_index": decision,
            "decision_time": (_time(decision) + timedelta(minutes=5)).isoformat(
                timespec="seconds"
            ),
            "direction": 1,
            "fold_id": "fold-01",
            "ordinal": ordinal,
            "regime": ("middle", "high")[ordinal - 1],
            "scope": scope,
        }
        for scope in ("full", "prefix")
        for ordinal, decision in enumerate(decisions, start=1)
    ]
    eligible = [
        (datetime(2026, 1, 2) + timedelta(days=offset)).date().isoformat()
        for offset in range(30)
    ]
    return compute_cost_aware_execution_pair_trace(
        definition=plan.definition,
        dataset_sha256=DATASET_SHA256,
        split_artifact_sha256=ROLLING_SPLIT_SHA256,
        material_identity=OBSERVED_MATERIAL_ID,
        windows=[
            {
                "eligible_dates": eligible,
                "fold_id": "fold-01",
                "test_end": datetime(2026, 2, 2).isoformat(timespec="seconds"),
                "test_start": datetime(2026, 1, 2).isoformat(timespec="seconds"),
            }
        ],
        source_observations=sources,
        candidate_observations=candidates,
        historical_context=plan.historical_context,
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
        self.verified = False

    def verify_reproducible_cache_producer(
        self,
        producer: RunningJobExecution,
        **kwargs: object,
    ) -> None:
        assert producer.job_id.startswith("job:")
        assert kwargs["cache_hash"] in self.evidence.values
        self.verified = True


def _execution(character: str) -> RunningJobExecution:
    return RunningJobExecution(
        job_id="job:" + character * 64,
        job_hash=character * 64,
        start_record_id=("a" if character != "a" else "b") * 64,
        job_permit_id=("c" if character != "c" else "d") * 64,
    )


def _producer_manifest(
    plan: CostAwareExecutionPairJobPlan,
    cache_hash: str,
) -> dict[str, object]:
    return {
        "dataset_sha256": DATASET_SHA256,
        "historical_context": {
            "current": plan.historical_context.manifest(),
        },
        "implementation_identities": dict(
            sorted(
                cost_aware_execution_pair_producer_implementation_identities().items()
            )
        ),
        "material_identity": OBSERVED_MATERIAL_ID,
        "prospective_family_id": plan.definition.prospective_family_id,
        "protocol_definition_id": plan.definition.identity,
        "protocol_id": plan.definition.protocol_id,
        "schema": COST_AWARE_EXECUTION_PAIR_PRODUCER_MANIFEST_SCHEMA,
        "split_artifact_sha256": ROLLING_SPLIT_SHA256,
        "trace_sha256": cache_hash,
    }


def test_job_plans_are_exact_two_member_protocol_neutral_ports() -> None:
    producer, consumer = _plans()
    assert isinstance(producer, ReplayFamilyJobPlan)
    assert isinstance(consumer, ReplayFamilyJobPlan)
    assert producer.produces_family_cache is True
    assert consumer.produces_family_cache is False
    assert len(producer.plan["criteria"]) == 18
    multiplicity = {
        row["criterion_id"]: row
        for row in producer.plan["adjudication_profile"]["multiplicity"]
    }
    assert multiplicity["D04-primary-control-uncertainty"]["family_size"] == 1
    assert multiplicity["E01-familywise-selection"]["family_size"] == 2
    assert producer.job_input_hashes() != consumer.job_input_hashes()
    with pytest.raises(ValueError, match="inseparable"):
        consumer.job_input_hashes(cache_sha256="a" * 64)


def test_neutral_cache_subject_evidence_and_consumer_provenance_roundtrip(
    tmp_path,
) -> None:
    producer, consumer = _plans()
    trace = _trace(producer)
    cache = cost_aware_execution_pair_cache(
        scoped_plan=producer,
        neutral_trace=trace,
        produced=True,
    )
    writer = _Writer()
    cache_artifact = writer.evidence.finalize(cache.content)
    producer_execution = _execution("1")
    outputs, state = materialize_cost_aware_execution_pair_evidence(
        writer=writer,
        scoped_plan=producer,
        execution=producer_execution,
        neutral_trace=trace,
    )
    assert state in {
        "not_evaluable",
        "contradicted",
        "unresolved",
        "partial_positive",
        "frontier",
        "confirmed",
    }
    producer_trace_hash = outputs[producer.output_names["trace"]]
    provenance = build_cost_aware_execution_pair_cache_provenance(
        scoped_plan=producer,
        execution=producer_execution,
        cache_sha256=cache_artifact.sha256,
        producer_trace_sha256=producer_trace_hash,
        producer_manifest=_producer_manifest(producer, cache_artifact.sha256),
    )
    provenance_hash = writer.evidence.finalize(
        canonical_bytes(provenance)
    ).sha256
    inputs = consumer.job_input_hashes(
        cache_sha256=cache_artifact.sha256,
        cache_provenance_sha256=provenance_hash,
        producer_trace_sha256=producer_trace_hash,
    )
    opened, opened_provenance, opened_trace, _ = (
        verify_cost_aware_execution_pair_cache_producer(
            writer,
            scoped_plan=consumer,
            repository_root=tmp_path,
            input_hashes=inputs,
            expected_callable_identity=(
                "axiom_rift.research.synthetic.execute_cost_aware.v1"
            ),
        )
    )
    assert opened.content == cache.content
    assert opened_provenance == provenance_hash
    assert opened_trace == producer_trace_hash
    assert writer.verified is True
    consumer_outputs, consumer_state = (
        materialize_cost_aware_execution_pair_evidence(
            writer=writer,
            scoped_plan=consumer,
            execution=_execution("2"),
            neutral_trace=opened.trace(consumer.definition),
        )
    )
    assert set(consumer_outputs) == set(consumer.expected_outputs())
    assert consumer_state in {
        "not_evaluable",
        "contradicted",
        "unresolved",
        "partial_positive",
        "frontier",
        "confirmed",
    }


def test_cache_rejects_registered_input_drift() -> None:
    producer, _ = _plans()
    trace = _trace(producer)
    trace["dataset_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        cost_aware_execution_pair_cache(
            scoped_plan=producer,
            neutral_trace=trace,
            produced=True,
        )
