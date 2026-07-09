"""Bounded, pure research execution surface for Project Axiom Rift V2."""

from axiom_rift.v2.research.core import ResearchResult, run_research
from axiom_rift.v2.research.execution import (
    Signal,
    SimulationResult,
    Trade,
    UnknownCostError,
    select_sequential,
    simulate_fixed_horizon,
    trade_crosses_end,
)
from axiom_rift.v2.research.features import (
    FeatureRow,
    build_feature_rows,
    feature_crosses_start,
    required_lookback,
)
from axiom_rift.v2.research.modeling import FittedRidge, ValidationBand, fit_ridge
from axiom_rift.v2.research.samples import (
    SupervisedSample,
    build_supervised_samples,
    label_crosses_end,
)
from axiom_rift.v2.research.specs import (
    Bar,
    BoundaryPurge,
    FeatureSpec,
    IndexBoundary,
    LabelSpec,
    ModelSpec,
    ResearchSpec,
    ResearchSpecError,
    SelectorSpec,
    TradeSpec,
)

__all__ = [
    "Bar",
    "BoundaryPurge",
    "FeatureRow",
    "FeatureSpec",
    "FittedRidge",
    "IndexBoundary",
    "LabelSpec",
    "ModelSpec",
    "ResearchResult",
    "ResearchSpec",
    "ResearchSpecError",
    "SelectorSpec",
    "Signal",
    "SimulationResult",
    "SupervisedSample",
    "Trade",
    "TradeSpec",
    "UnknownCostError",
    "ValidationBand",
    "build_feature_rows",
    "build_supervised_samples",
    "feature_crosses_start",
    "fit_ridge",
    "label_crosses_end",
    "required_lookback",
    "run_research",
    "select_sequential",
    "simulate_fixed_horizon",
    "trade_crosses_end",
]
