"""Pure, deterministic orchestration for one bounded V2 research evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from axiom_rift.v2.identity import sha256_payload
from axiom_rift.v2.research.execution import (
    Signal,
    SimulationResult,
    assert_known_spreads,
    select_sequential,
    simulate_fixed_horizon,
)
from axiom_rift.v2.research.features import build_feature_rows
from axiom_rift.v2.research.modeling import FittedRidge, fit_ridge
from axiom_rift.v2.research.samples import build_supervised_samples
from axiom_rift.v2.research.specs import Bar, IndexBoundary, ResearchSpec, ResearchSpecError


@dataclass(frozen=True)
class ResearchResult:
    spec_hash: str
    data_hash: str
    train_sample_count: int
    validation_sample_count: int
    evaluation_row_count: int
    model: FittedRidge
    signals: tuple[Signal, ...]
    simulation: SimulationResult
    result_hash: str
    claim_ceiling: str = "diagnostic_observation"
    economic_claim_allowed: bool = False

    def _body_payload(self) -> dict[str, Any]:
        return {
            "schema": "axiom_rift_v2_research_result_v1",
            "spec_hash": self.spec_hash,
            "data_hash": self.data_hash,
            "train_sample_count": self.train_sample_count,
            "validation_sample_count": self.validation_sample_count,
            "evaluation_row_count": self.evaluation_row_count,
            "model": self.model.to_payload(),
            "signals": [signal.to_payload() for signal in self.signals],
            "simulation": self.simulation.to_payload(),
            "claim_ceiling": self.claim_ceiling,
            "economic_claim_allowed": self.economic_claim_allowed,
        }

    def to_payload(self) -> dict[str, Any]:
        return {**self._body_payload(), "result_hash": self.result_hash}


def _validate_boundaries(
    bar_count: int,
    train: IndexBoundary,
    validation: IndexBoundary,
    evaluation: IndexBoundary,
) -> None:
    for boundary in (train, validation, evaluation):
        boundary.validate(bar_count)
    if train.end > validation.start or validation.end > evaluation.start:
        raise ResearchSpecError("train, validation, and evaluation boundaries must be ordered and disjoint")


def run_research(
    bars: Iterable[Bar],
    spec: ResearchSpec,
    *,
    train: IndexBoundary,
    validation: IndexBoundary,
    evaluation: IndexBoundary,
) -> ResearchResult:
    """Run without filesystem, registry, ledger, campaign, or control-state mutation."""

    frozen_bars = tuple(bars)
    if not frozen_bars:
        raise ResearchSpecError("research requires at least one bar")
    if len({bar.timestamp for bar in frozen_bars}) != len(frozen_bars):
        raise ResearchSpecError("bar timestamps must be unique")
    if any(left.timestamp >= right.timestamp for left, right in zip(frozen_bars, frozen_bars[1:])):
        raise ResearchSpecError("bar timestamps must be strictly chronological")
    _validate_boundaries(len(frozen_bars), train, validation, evaluation)
    assert_known_spreads(frozen_bars)

    train_samples = build_supervised_samples(
        frozen_bars, spec.features, spec.label, train, spec.purge
    )
    validation_samples = build_supervised_samples(
        frozen_bars, spec.features, spec.label, validation, spec.purge
    )
    fitted = fit_ridge(train_samples, validation_samples, spec.features, spec.model)
    evaluation_rows = build_feature_rows(frozen_bars, spec.features, evaluation, spec.purge)
    scored_rows = tuple((row, fitted.predict(row.values)) for row in evaluation_rows)
    signals = select_sequential(
        scored_rows,
        fitted.validation_band,
        spec.selector,
        spec.trade,
        evaluation,
        spec.purge,
    )
    simulation = simulate_fixed_horizon(frozen_bars, signals, spec.trade)
    spec_hash = sha256_payload(spec.to_payload())
    data_hash = sha256_payload(
        {
            "schema": "axiom_rift_v2_research_input_v1",
            "bars": [bar.to_payload() for bar in frozen_bars],
            "boundaries": {
                "train": train.to_payload(),
                "validation": validation.to_payload(),
                "evaluation": evaluation.to_payload(),
            },
        }
    )
    provisional = ResearchResult(
        spec_hash=spec_hash,
        data_hash=data_hash,
        train_sample_count=len(train_samples),
        validation_sample_count=len(validation_samples),
        evaluation_row_count=len(evaluation_rows),
        model=fitted,
        signals=signals,
        simulation=simulation,
        result_hash="",
    )
    result_hash = sha256_payload(provisional._body_payload())
    return ResearchResult(
        spec_hash=spec_hash,
        data_hash=data_hash,
        train_sample_count=len(train_samples),
        validation_sample_count=len(validation_samples),
        evaluation_row_count=len(evaluation_rows),
        model=fitted,
        signals=signals,
        simulation=simulation,
        result_hash=result_hash,
    )
