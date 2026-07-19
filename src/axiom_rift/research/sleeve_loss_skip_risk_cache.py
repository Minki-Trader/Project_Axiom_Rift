"""Durable producer-bound family cache for the sleeve loss-skip pair."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.operations.running_job import RunningJobExecution
from axiom_rift.research.prospective_pair_trace import (
    ProspectivePairProtocolDefinition,
)
from axiom_rift.research.reproducible_cache import (
    publish_reproducible_cache,
    reproducible_cache_implementation_sha256,
)
from axiom_rift.research.sleeve_loss_skip_risk_trace import (
    extract_sleeve_loss_skip_risk_family_trace,
    validate_sleeve_loss_skip_risk_family_trace,
)


SLEEVE_LOSS_SKIP_RISK_CACHE_PROVENANCE_SCHEMA = (
    "sleeve_loss_skip_risk_cache_provenance.v1"
)
SLEEVE_LOSS_SKIP_RISK_CACHE_NAMESPACE = "sleeve-loss-skip-risk-v1"
_THIS_FILE = Path(__file__).resolve()
_MAX_PROVENANCE_BYTES = 1_000_000
_PRODUCER_EXECUTION_FIELDS = {
    "identity",
    "job_hash",
    "job_id",
    "job_permit_id",
    "start_record_id",
}
_PROVENANCE_FIELDS = {
    "cache_output_name",
    "cache_sha256",
    "definition_identity",
    "family_id",
    "mission_id",
    "producer_executable_id",
    "producer_execution",
    "producer_trace_output_name",
    "producer_trace_sha256",
    "protocol_id",
    "schema",
    "study_id",
}


class SleeveLossSkipRiskCacheAuthority(Protocol):
    evidence: Any

    def verify_reproducible_cache_producer(
        self,
        producer: RunningJobExecution,
        **kwargs: Any,
    ) -> None: ...


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ValueError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return text


def sleeve_loss_skip_risk_cache_implementation_sha256() -> str:
    return sha256(
        _THIS_FILE.read_bytes()
        + bytes.fromhex(reproducible_cache_implementation_sha256())
    ).hexdigest()


def sleeve_loss_skip_risk_cache_output_name(
    definition: ProspectivePairProtocolDefinition,
) -> str:
    suffix = definition.identity.removeprefix(
        "prospective-pair-definition:"
    )[:16]
    return (
        "local/cache/prospective-pair/"
        f"{SLEEVE_LOSS_SKIP_RISK_CACHE_NAMESPACE}-{suffix}.json"
    )


def sleeve_loss_skip_risk_cache_provenance_output_name(
    study_id: str,
) -> str:
    return (
        f"scientific/{_ascii('sleeve loss-skip study_id', study_id)}/"
        f"{SLEEVE_LOSS_SKIP_RISK_CACHE_NAMESPACE}-family-cache-provenance.json"
    )


@dataclass(frozen=True, slots=True)
class SleeveLossSkipRiskFamilyCache:
    content: bytes
    produced: bool
    sha256: str
    _trace: dict[str, object] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if type(self.content) is not bytes or type(self.produced) is not bool:
            raise ValueError("sleeve loss-skip cache value is invalid")
        if _digest("sleeve loss-skip cache hash", self.sha256) != sha256(
            self.content
        ).hexdigest():
            raise ValueError("sleeve loss-skip cache content hash drifted")

    def trace(
        self,
        definition: ProspectivePairProtocolDefinition,
    ) -> dict[str, object]:
        trace = self._trace
        if trace is None:
            trace = validate_sleeve_loss_skip_risk_family_trace(
                self.content,
                definition=definition,
            )
        else:
            trace = validate_sleeve_loss_skip_risk_family_trace(
                trace,
                definition=definition,
            )
        if canonical_bytes(trace) != self.content:
            raise ValueError("sleeve loss-skip cache trace differs from its bytes")
        return trace


def sleeve_loss_skip_risk_family_cache(
    *,
    definition: ProspectivePairProtocolDefinition,
    family_trace: bytes | Mapping[str, Any],
    produced: bool,
) -> SleeveLossSkipRiskFamilyCache:
    trace = validate_sleeve_loss_skip_risk_family_trace(
        family_trace,
        definition=definition,
    )
    content = canonical_bytes(trace)
    return SleeveLossSkipRiskFamilyCache(
        content=content,
        produced=produced,
        sha256=sha256(content).hexdigest(),
        _trace=trace,
    )


def materialize_sleeve_loss_skip_risk_cache(
    repository_root: str | Path,
    *,
    definition: ProspectivePairProtocolDefinition,
    content: bytes,
) -> None:
    observed = publish_reproducible_cache(
        repository_root=Path(repository_root).resolve(),
        relative_path=sleeve_loss_skip_risk_cache_output_name(definition),
        content=content,
    )
    if observed != sha256(content).hexdigest():
        raise ValueError("sleeve loss-skip cache publication drifted")


def build_sleeve_loss_skip_risk_cache_provenance(
    *,
    definition: ProspectivePairProtocolDefinition,
    mission_id: str,
    study_id: str,
    producer_executable_id: str,
    producer_trace_output_name: str,
    execution: RunningJobExecution,
    cache_sha256: str,
    producer_trace_sha256: str,
) -> dict[str, object]:
    if producer_executable_id != definition.prospective_executable_ids[0]:
        raise ValueError("sleeve loss-skip cache producer is not the first member")
    value = {
        "cache_output_name": sleeve_loss_skip_risk_cache_output_name(definition),
        "cache_sha256": _digest(
            "sleeve loss-skip cache hash",
            cache_sha256,
        ),
        "definition_identity": definition.identity,
        "family_id": definition.family_id,
        "mission_id": _ascii("sleeve loss-skip mission_id", mission_id),
        "producer_executable_id": producer_executable_id,
        "producer_execution": {
            **execution.payload(),
            "identity": execution.identity,
        },
        "producer_trace_output_name": _ascii(
            "sleeve loss-skip producer trace output",
            producer_trace_output_name,
        ),
        "producer_trace_sha256": _digest(
            "sleeve loss-skip producer trace hash",
            producer_trace_sha256,
        ),
        "protocol_id": definition.protocol_id,
        "schema": SLEEVE_LOSS_SKIP_RISK_CACHE_PROVENANCE_SCHEMA,
        "study_id": _ascii("sleeve loss-skip study_id", study_id),
    }
    return validate_sleeve_loss_skip_risk_cache_provenance(
        value,
        definition=definition,
        mission_id=mission_id,
        study_id=study_id,
        producer_trace_output_name=producer_trace_output_name,
    )


def validate_sleeve_loss_skip_risk_cache_provenance(
    value: Mapping[str, Any],
    *,
    definition: ProspectivePairProtocolDefinition,
    mission_id: str,
    study_id: str,
    producer_trace_output_name: str,
) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != _PROVENANCE_FIELDS:
        raise ValueError("sleeve loss-skip cache provenance schema is invalid")
    content = canonical_bytes(value)
    if len(content) > _MAX_PROVENANCE_BYTES:
        raise ValueError("sleeve loss-skip cache provenance exceeds its bound")
    normalized = parse_canonical(content)
    if not isinstance(normalized, dict):
        raise ValueError("sleeve loss-skip cache provenance is not an object")
    producer_id = definition.prospective_executable_ids[0]
    if (
        normalized.get("schema")
        != SLEEVE_LOSS_SKIP_RISK_CACHE_PROVENANCE_SCHEMA
        or normalized.get("cache_output_name")
        != sleeve_loss_skip_risk_cache_output_name(definition)
        or normalized.get("definition_identity") != definition.identity
        or normalized.get("family_id") != definition.family_id
        or normalized.get("mission_id") != mission_id
        or normalized.get("producer_executable_id") != producer_id
        or normalized.get("producer_trace_output_name")
        != producer_trace_output_name
        or normalized.get("protocol_id") != definition.protocol_id
        or normalized.get("study_id") != study_id
    ):
        raise ValueError("sleeve loss-skip cache provenance is out of scope")
    _digest(
        "sleeve loss-skip cache hash",
        normalized.get("cache_sha256"),
    )
    _digest(
        "sleeve loss-skip producer trace hash",
        normalized.get("producer_trace_sha256"),
    )
    producer = normalized.get("producer_execution")
    if not isinstance(producer, dict) or set(producer) != (
        _PRODUCER_EXECUTION_FIELDS
    ):
        raise ValueError("sleeve loss-skip cache producer execution is invalid")
    execution = RunningJobExecution.from_mapping(
        {
            name: producer[name]
            for name in (
                "job_hash",
                "job_id",
                "job_permit_id",
                "start_record_id",
            )
        }
    )
    if producer.get("identity") != execution.identity:
        raise ValueError("sleeve loss-skip cache producer identity drifted")
    return normalized


def verify_sleeve_loss_skip_risk_cache_producer(
    writer: SleeveLossSkipRiskCacheAuthority,
    *,
    repository_root: str | Path,
    input_hashes: Sequence[str],
    definition: ProspectivePairProtocolDefinition,
    mission_id: str,
    study_id: str,
    producer_executable_id: str,
    producer_trace_output_name: str,
    producer_expected_output_classes: Mapping[str, str],
    expected_callable_identity: str,
    materialize_missing: bool = True,
) -> tuple[SleeveLossSkipRiskFamilyCache, str, str, dict[str, object]]:
    if producer_executable_id != definition.prospective_executable_ids[0]:
        raise ValueError("sleeve loss-skip cache producer identity is invalid")
    inputs = tuple(input_hashes)
    opened: dict[str, bytes] = {}
    parsed: dict[str, object] = {}
    matches: list[tuple[str, dict[str, object]]] = []
    for input_hash in dict.fromkeys(inputs):
        try:
            content = writer.evidence.read_verified(input_hash)
        except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError):
            continue
        opened[input_hash] = content
        if len(content) > _MAX_PROVENANCE_BYTES:
            continue
        try:
            value = parse_canonical(content)
        except (TypeError, ValueError):
            continue
        parsed[input_hash] = value
        if (
            isinstance(value, dict)
            and value.get("schema")
            == SLEEVE_LOSS_SKIP_RISK_CACHE_PROVENANCE_SCHEMA
        ):
            matches.append(
                (
                    input_hash,
                    validate_sleeve_loss_skip_risk_cache_provenance(
                        value,
                        definition=definition,
                        mission_id=mission_id,
                        study_id=study_id,
                        producer_trace_output_name=producer_trace_output_name,
                    ),
                )
            )
    if len(matches) != 1:
        raise ValueError(
            "sleeve loss-skip consumer requires one cache provenance input"
        )
    provenance_hash, provenance = matches[0]
    cache_hash = str(provenance["cache_sha256"])
    producer_trace_hash = str(provenance["producer_trace_sha256"])
    for name, value in (
        ("cache", cache_hash),
        ("cache provenance", provenance_hash),
        ("producer trace", producer_trace_hash),
    ):
        if inputs.count(value) != 1:
            raise ValueError(
                f"sleeve loss-skip {name} must be exactly one Job input"
            )
    cache_content = opened.get(cache_hash)
    producer_trace_content = opened.get(producer_trace_hash)
    if cache_content is None or producer_trace_content is None:
        raise ValueError("sleeve loss-skip producer evidence is unavailable")
    cache = sleeve_loss_skip_risk_family_cache(
        definition=definition,
        family_trace=cache_content,
        produced=False,
    )
    if cache.sha256 != cache_hash:
        raise ValueError("sleeve loss-skip cache hash differs from its bytes")
    producer_trace = parsed.get(producer_trace_hash)
    if not isinstance(producer_trace, Mapping):
        try:
            producer_trace = parse_canonical(producer_trace_content)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "sleeve loss-skip producer trace is not canonical"
            ) from exc
    if not isinstance(producer_trace, Mapping):
        raise ValueError("sleeve loss-skip producer trace is not an object")
    family = extract_sleeve_loss_skip_risk_family_trace(
        producer_trace,
        definition=definition,
    )
    if canonical_bytes(family) != cache.content:
        raise ValueError("sleeve loss-skip producer trace differs from its cache")
    producer_payload = provenance["producer_execution"]
    execution = RunningJobExecution.from_mapping(
        {
            name: producer_payload[name]
            for name in (
                "job_hash",
                "job_id",
                "job_permit_id",
                "start_record_id",
            )
        }
    )
    if (
        producer_trace.get("mission_id") != mission_id
        or producer_trace.get("subject_executable_id")
        != producer_executable_id
        or producer_trace.get("job_id") != execution.job_id
        or producer_trace.get("job_hash") != execution.job_hash
    ):
        raise ValueError("sleeve loss-skip producer trace execution drifted")
    writer.verify_reproducible_cache_producer(
        execution,
        cache_output_name=sleeve_loss_skip_risk_cache_output_name(definition),
        cache_hash=cache.sha256,
        expected_callable_identity=_ascii(
            "sleeve loss-skip callable identity",
            expected_callable_identity,
        ),
        expected_evidence_subject={
            "kind": "Executable",
            "id": producer_executable_id,
        },
        expected_output_classes=dict(producer_expected_output_classes),
        expected_study_id=study_id,
        manifest_output_name=(
            sleeve_loss_skip_risk_cache_provenance_output_name(study_id)
        ),
        manifest_hash=provenance_hash,
    )
    target = (
        Path(repository_root).resolve()
        / sleeve_loss_skip_risk_cache_output_name(definition)
    )
    if target.exists() or materialize_missing:
        materialize_sleeve_loss_skip_risk_cache(
            repository_root,
            definition=definition,
            content=cache.content,
        )
    return cache, provenance_hash, producer_trace_hash, provenance


__all__ = [
    "SLEEVE_LOSS_SKIP_RISK_CACHE_NAMESPACE",
    "SLEEVE_LOSS_SKIP_RISK_CACHE_PROVENANCE_SCHEMA",
    "SleeveLossSkipRiskFamilyCache",
    "build_sleeve_loss_skip_risk_cache_provenance",
    "materialize_sleeve_loss_skip_risk_cache",
    "sleeve_loss_skip_risk_cache_implementation_sha256",
    "sleeve_loss_skip_risk_cache_output_name",
    "sleeve_loss_skip_risk_cache_provenance_output_name",
    "sleeve_loss_skip_risk_family_cache",
    "validate_sleeve_loss_skip_risk_cache_provenance",
    "verify_sleeve_loss_skip_risk_cache_producer",
]
