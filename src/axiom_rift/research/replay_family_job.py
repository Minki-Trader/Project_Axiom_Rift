"""Protocol-neutral in-memory boundary for replay-family Jobs.

Durable Job specifications remain data-only.  These protocols describe the
repository-owned adapters used by the Mission workflow so operational
ceremony is not coupled to one scientific family shape or validator.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from axiom_rift.research.historical_family_binding import HistoricalFamilyLike


@runtime_checkable
class ReplayFamilyDefinition(Protocol):
    family: HistoricalFamilyLike
    prospective_executable_ids: tuple[str, ...]
    identity: str


@runtime_checkable
class ReplayFamilyJobPlan(Protocol):
    mission_id: str
    study_id: str
    executable_id: str
    definition: ReplayFamilyDefinition

    @property
    def plan_hash(self) -> str: ...

    @property
    def produces_family_cache(self) -> bool: ...

    @property
    def cache_output_name(self) -> str: ...

    @property
    def cache_provenance_output_name(self) -> str: ...

    @property
    def plan(self) -> Mapping[str, object]: ...

    def expected_outputs(self) -> tuple[str, ...]: ...

    def expected_output_classes(self) -> dict[str, str]: ...

    def job_input_hashes(
        self,
        *,
        cache_sha256: str | None = None,
        cache_provenance_sha256: str | None = None,
        producer_trace_sha256: str | None = None,
    ) -> tuple[str, ...]: ...

    def scientific_binding(self) -> dict[str, object]: ...

    def validated_recomputed_criterion_ids(
        self,
        scientific_facts: Mapping[str, object],
    ) -> tuple[str, ...]: ...


@runtime_checkable
class ReplayFamilyJobPacket(Protocol):
    adjudication_state: str

    def outputs(self) -> dict[str, str]: ...


def replay_family_evidence_modes(
    plans: tuple[ReplayFamilyJobPlan, ...],
) -> tuple[str, ...]:
    """Return one exact evidence-mode inventory shared by all family Jobs."""

    if not plans:
        raise ValueError("replay family Job plans are absent")
    values: list[tuple[str, ...]] = []
    for plan in plans:
        binding = plan.scientific_binding()
        raw = binding.get("evidence_modes")
        if (
            not isinstance(raw, list)
            or not raw
            or any(type(item) is not str or not item.isascii() for item in raw)
        ):
            raise ValueError("replay family evidence modes are malformed")
        modes = tuple(raw)
        if modes != tuple(sorted(set(modes))):
            raise ValueError("replay family evidence modes are not canonical")
        values.append(modes)
    if any(value != values[0] for value in values[1:]):
        raise ValueError("replay family evidence modes differ by member")
    return values[0]


__all__ = [
    "ReplayFamilyDefinition",
    "ReplayFamilyJobPacket",
    "ReplayFamilyJobPlan",
    "replay_family_evidence_modes",
]
