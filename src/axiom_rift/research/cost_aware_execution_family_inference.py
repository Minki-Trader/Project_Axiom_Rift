"""One immutable inference bundle for both cost-aware family members."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.research.cost_aware_execution_protocol import (
    CostAwareExecutionProtocolDefinition,
)
from axiom_rift.research.cost_aware_execution_trace_snapshot import (
    CostAwareExecutionPairTraceSnapshot,
    _cost_aware_pair_snapshot_value,
)
from axiom_rift.research.scientific_trace import ScientificTraceError
from axiom_rift.research.selection_inference import (
    selection_inference_implementation_sha256,
)


_THIS_FILE = Path(__file__).resolve()
_FAMILY_INFERENCE_SNAPSHOT_AUTHORITY = object()


def cost_aware_execution_family_inference_implementation_sha256() -> str:
    return sha256(_THIS_FILE.read_bytes()).hexdigest()


def _family_inference_identity() -> str:
    return sha256(
        bytes.fromhex(selection_inference_implementation_sha256())
        + bytes.fromhex(
            cost_aware_execution_family_inference_implementation_sha256()
        )
    ).hexdigest()


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


def _family_inference_snapshot_bindings(
    *,
    pair_sha256: str,
    definition_identity: str,
    parameters_sha256: str,
    inference_identity: str,
) -> tuple[tuple[str, str], ...]:
    return (
        (
            "definition_identity",
            _ascii("family inference definition", definition_identity),
        ),
        (
            "inference_identity",
            _digest("family inference implementation", inference_identity),
        ),
        ("pair_sha256", _digest("family inference pair hash", pair_sha256)),
        (
            "parameters_sha256",
            _digest("family inference parameter hash", parameters_sha256),
        ),
    )


class _SealedCostAwareFamilyInferencePayload:
    __slots__ = ("__bindings", "__subjects")

    def __init__(
        self,
        *,
        authority: object,
        bindings: tuple[tuple[str, str], ...],
        subjects: dict[str, dict[str, object]],
    ) -> None:
        if authority is not _FAMILY_INFERENCE_SNAPSHOT_AUTHORITY:
            raise ScientificTraceError(
                "cost-aware family inference lacks derivation authority"
            )
        object.__setattr__(
            self,
            "_SealedCostAwareFamilyInferencePayload__bindings",
            bindings,
        )
        object.__setattr__(
            self,
            "_SealedCostAwareFamilyInferencePayload__subjects",
            _freeze(subjects),
        )

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(
            "validated cost-aware family inference payloads are immutable"
        )

    def require(
        self,
        bindings: tuple[tuple[str, str], ...],
    ) -> _SealedCostAwareFamilyInferencePayload:
        if self.__bindings != bindings:
            raise ScientificTraceError(
                "cost-aware family inference binding drifted"
            )
        return self

    def subject(self, executable_id: str) -> dict[str, object]:
        try:
            value = _detach(self.__subjects[executable_id])
        except KeyError as exc:
            raise ScientificTraceError(
                "cost-aware family inference subject is absent"
            ) from exc
        if not isinstance(value, dict):
            raise RuntimeError("cost-aware family inference payload drifted")
        return value


@dataclass(frozen=True, slots=True)
class CostAwareExecutionFamilyInferenceSnapshot:
    """Both subject projections from one exact family inference run."""

    pair_sha256: str
    definition_identity: str
    parameters_sha256: str
    inference_identity: str
    _payload: _SealedCostAwareFamilyInferencePayload = field(
        repr=False,
        compare=False,
    )
    _authority: object = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            self._authority is not _FAMILY_INFERENCE_SNAPSHOT_AUTHORITY
            or not isinstance(
                self._payload, _SealedCostAwareFamilyInferencePayload
            )
        ):
            raise ScientificTraceError(
                "cost-aware family inference snapshot is invalid"
            )
        self._payload.require(
            _family_inference_snapshot_bindings(
                pair_sha256=self.pair_sha256,
                definition_identity=self.definition_identity,
                parameters_sha256=self.parameters_sha256,
                inference_identity=self.inference_identity,
            )
        )

    def require(
        self,
        *,
        pair: CostAwareExecutionPairTraceSnapshot,
        definition: CostAwareExecutionProtocolDefinition,
        parameters: Mapping[str, Any],
    ) -> CostAwareExecutionFamilyInferenceSnapshot:
        pair.require(definition=definition)
        expected_parameters = sha256(
            canonical_bytes(dict(parameters))
        ).hexdigest()
        expected_inference = _family_inference_identity()
        if (
            self.pair_sha256 != pair.sha256
            or self.definition_identity != definition.identity
            or self.parameters_sha256 != expected_parameters
            or self.inference_identity != expected_inference
        ):
            raise ScientificTraceError(
                "cost-aware family inference snapshot authority drifted"
            )
        self._payload.require(
            _family_inference_snapshot_bindings(
                pair_sha256=pair.sha256,
                definition_identity=definition.identity,
                parameters_sha256=expected_parameters,
                inference_identity=expected_inference,
            )
        )
        return self

    def subject(
        self,
        executable_id: str,
    ) -> tuple[dict[str, dict[str, int | None]], dict[str, object]]:
        payload = self._payload.subject(executable_id)
        metrics = payload.get("metrics")
        statistics = payload.get("statistics")
        if not isinstance(metrics, dict) or not isinstance(statistics, dict):
            raise RuntimeError("cost-aware family inference payload drifted")
        return metrics, statistics


def build_cost_aware_execution_family_inference_snapshot(
    *,
    pair_trace: Mapping[str, Any] | CostAwareExecutionPairTraceSnapshot,
    definition: CostAwareExecutionProtocolDefinition,
    parameters: Mapping[str, Any] | None = None,
) -> CostAwareExecutionFamilyInferenceSnapshot:
    """Run exact selection/control inference once for both pair members."""

    from axiom_rift.research.cost_aware_execution_trace import (
        _cost_aware_family_inference_parts,
        _derive_subject_metrics_and_statistics,
        cost_aware_execution_calculation_parameters,
        validate_cost_aware_execution_pair_trace_snapshot,
    )

    pair = validate_cost_aware_execution_pair_trace_snapshot(
        pair_trace,
        definition=definition,
    )
    actual_parameters = (
        cost_aware_execution_calculation_parameters(definition)
        if parameters is None
        else dict(parameters)
    )
    pair_value = _cost_aware_pair_snapshot_value(pair, definition=definition)
    family = _cost_aware_family_inference_parts(
        pair=pair_value,
        definition=definition,
        parameters=actual_parameters,
    )
    subjects: dict[str, dict[str, object]] = {}
    for subject_id in definition.prospective_executable_ids:
        metrics, statistics = _derive_subject_metrics_and_statistics(
            subject_id=subject_id,
            pair=pair_value,
            definition=definition,
            parameters=actual_parameters,
            family=family,
        )
        subjects[subject_id] = {
            "metrics": metrics,
            "statistics": statistics,
        }
    canonical_bytes(subjects)
    parameters_sha256 = sha256(canonical_bytes(actual_parameters)).hexdigest()
    inference_identity = _family_inference_identity()
    bindings = _family_inference_snapshot_bindings(
        pair_sha256=pair.sha256,
        definition_identity=definition.identity,
        parameters_sha256=parameters_sha256,
        inference_identity=inference_identity,
    )
    payload = _SealedCostAwareFamilyInferencePayload(
        authority=_FAMILY_INFERENCE_SNAPSHOT_AUTHORITY,
        bindings=bindings,
        subjects=subjects,
    )
    return CostAwareExecutionFamilyInferenceSnapshot(
        pair_sha256=pair.sha256,
        definition_identity=definition.identity,
        parameters_sha256=parameters_sha256,
        inference_identity=inference_identity,
        _payload=payload,
        _authority=_FAMILY_INFERENCE_SNAPSHOT_AUTHORITY,
    )


__all__ = [
    "CostAwareExecutionFamilyInferenceSnapshot",
    "build_cost_aware_execution_family_inference_snapshot",
    "cost_aware_execution_family_inference_implementation_sha256",
]
