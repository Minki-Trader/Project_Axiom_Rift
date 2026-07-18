"""Immutable validation snapshots for one cost-aware family trace."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any

from axiom_rift.research.cost_aware_execution_protocol import (
    CostAwareExecutionProtocolDefinition,
)
from axiom_rift.research.scientific_trace import ScientificTraceError


_THIS_FILE = Path(__file__).resolve()
_PAIR_TRACE_SNAPSHOT_AUTHORITY = object()


def cost_aware_execution_trace_snapshot_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ScientificTraceError(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        raise ScientificTraceError(f"{name} must be a lowercase SHA-256 digest")
    return text


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _detach(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _detach(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_detach(item) for item in value]
    return value


def _pair_snapshot_bindings(
    *,
    content_sha256: str,
    definition_identity: str,
    validator_identity: str,
) -> tuple[tuple[str, str], ...]:
    return (
        ("content_sha256", _digest("cost-aware pair snapshot hash", content_sha256)),
        (
            "definition_identity",
            _ascii(
                "cost-aware pair snapshot definition identity",
                definition_identity,
            ),
        ),
        (
            "validator_identity",
            _ascii(
                "cost-aware pair snapshot validator identity",
                validator_identity,
            ),
        ),
    )


class _SealedCostAwarePairPayload:
    """Private normalized rows retained after one complete boundary scan."""

    __slots__ = ("__bindings", "__normalized")

    def __init__(
        self,
        *,
        authority: object,
        bindings: tuple[tuple[str, str], ...],
        normalized: dict[str, object],
    ) -> None:
        if authority is not _PAIR_TRACE_SNAPSHOT_AUTHORITY:
            raise ScientificTraceError(
                "cost-aware pair snapshot payload lacks validation authority"
            )
        object.__setattr__(
            self,
            "_SealedCostAwarePairPayload__bindings",
            bindings,
        )
        object.__setattr__(
            self,
            "_SealedCostAwarePairPayload__normalized",
            _freeze(normalized),
        )

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("validated cost-aware pair payloads are immutable")

    def require(
        self,
        bindings: tuple[tuple[str, str], ...],
    ) -> _SealedCostAwarePairPayload:
        if self.__bindings != bindings:
            raise ScientificTraceError(
                "cost-aware pair snapshot payload binding drifted"
            )
        return self

    def detached(self) -> dict[str, object]:
        value = _detach(self.__normalized)
        if not isinstance(value, dict):
            raise RuntimeError("cost-aware pair snapshot projection drifted")
        return value

    def normalized(self, authority: object) -> Mapping[str, Any]:
        if authority is not _PAIR_TRACE_SNAPSHOT_AUTHORITY:
            raise ScientificTraceError(
                "cost-aware pair snapshot projection lacks authority"
            )
        return self.__normalized


@dataclass(frozen=True, slots=True)
class CostAwareExecutionPairTraceSnapshot:
    """One immutable, fully scanned neutral pair at one trust boundary."""

    content: bytes
    sha256: str
    definition_identity: str
    validator_identity: str
    _payload: _SealedCostAwarePairPayload = field(repr=False, compare=False)
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if self._authority is not _PAIR_TRACE_SNAPSHOT_AUTHORITY:
            raise ScientificTraceError(
                "cost-aware pair snapshot lacks validation authority"
            )
        if type(self.content) is not bytes or not isinstance(
            self._payload, _SealedCostAwarePairPayload
        ):
            raise ScientificTraceError("cost-aware pair snapshot is invalid")
        observed = sha256(self.content).hexdigest()
        if _digest("cost-aware pair snapshot hash", self.sha256) != observed:
            raise ScientificTraceError(
                "cost-aware pair snapshot content hash drifted"
            )
        object.__setattr__(self, "sha256", observed)
        self._payload.require(
            _pair_snapshot_bindings(
                content_sha256=observed,
                definition_identity=self.definition_identity,
                validator_identity=self.validator_identity,
            )
        )

    def require(
        self,
        *,
        definition: CostAwareExecutionProtocolDefinition,
    ) -> CostAwareExecutionPairTraceSnapshot:
        if not isinstance(definition, CostAwareExecutionProtocolDefinition):
            raise ScientificTraceError("cost-aware trace definition is not typed")
        from axiom_rift.research.cost_aware_execution_trace import (
            cost_aware_execution_trace_implementation_sha256,
        )

        expected_validator = cost_aware_execution_trace_implementation_sha256()
        if (
            self.definition_identity != definition.identity
            or self.validator_identity != expected_validator
            or sha256(self.content).hexdigest() != self.sha256
        ):
            raise ScientificTraceError(
                "cost-aware pair snapshot authority drifted"
            )
        self._payload.require(
            _pair_snapshot_bindings(
                content_sha256=self.sha256,
                definition_identity=definition.identity,
                validator_identity=expected_validator,
            )
        )
        return self

    def to_dict(self) -> dict[str, object]:
        self._payload.require(
            _pair_snapshot_bindings(
                content_sha256=self.sha256,
                definition_identity=self.definition_identity,
                validator_identity=self.validator_identity,
            )
        )
        return self._payload.detached()

    def registered_inputs(
        self,
        *,
        definition: CostAwareExecutionProtocolDefinition,
    ) -> dict[str, object]:
        self.require(definition=definition)
        value = self._payload.normalized(_PAIR_TRACE_SNAPSHOT_AUTHORITY)
        detached = _detach(
            {
                "dataset_sha256": value["dataset_sha256"],
                "historical_context": value["historical_context"],
                "material_identity": value["material_identity"],
                "protocol_definition": value["protocol_definition"],
                "protocol_id": value["protocol_id"],
                "split_artifact_sha256": value["split_artifact_sha256"],
            }
        )
        if not isinstance(detached, dict):
            raise RuntimeError("cost-aware registered input projection drifted")
        return detached


def _cost_aware_pair_snapshot_value(
    snapshot: CostAwareExecutionPairTraceSnapshot,
    *,
    definition: CostAwareExecutionProtocolDefinition,
) -> Mapping[str, Any]:
    snapshot.require(definition=definition)
    return snapshot._payload.normalized(_PAIR_TRACE_SNAPSHOT_AUTHORITY)


def _seal_cost_aware_execution_pair_trace_snapshot(
    *,
    content: bytes,
    normalized: dict[str, object],
    definition_identity: str,
    validator_identity: str,
) -> CostAwareExecutionPairTraceSnapshot:
    """Seal bytes already opened by the complete trace validator."""

    if type(content) is not bytes or not isinstance(normalized, dict):
        raise ScientificTraceError("cost-aware pair snapshot material is invalid")
    content_sha256 = sha256(content).hexdigest()
    bindings = _pair_snapshot_bindings(
        content_sha256=content_sha256,
        definition_identity=definition_identity,
        validator_identity=validator_identity,
    )
    payload = _SealedCostAwarePairPayload(
        authority=_PAIR_TRACE_SNAPSHOT_AUTHORITY,
        bindings=bindings,
        normalized=normalized,
    )
    return CostAwareExecutionPairTraceSnapshot(
        content=content,
        sha256=content_sha256,
        definition_identity=definition_identity,
        validator_identity=validator_identity,
        _payload=payload,
        _authority=_PAIR_TRACE_SNAPSHOT_AUTHORITY,
    )


__all__ = [
    "CostAwareExecutionPairTraceSnapshot",
    "cost_aware_execution_trace_snapshot_implementation_sha256",
]
