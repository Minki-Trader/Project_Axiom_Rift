"""Canonical V2 research and empty-epoch autonomy surfaces.

Operational execution is the hash-registered causal scout backed by
``axiom_rift.v2.features``. The older pure-Python core is fixture-only and is
available under explicit fixture names solely to preserve causal unit tests.
"""

from __future__ import annotations

import warnings
from typing import Any

from axiom_rift.v2.research.core import (
    ResearchResult as FixtureResearchResult,
    run_research as run_fixture_research,
)
from axiom_rift.v2.research.execution import (
    Signal as _FixtureSignal,
    SimulationResult as _FixtureSimulationResult,
    Trade as _FixtureTrade,
    UnknownCostError as _FixtureUnknownCostError,
    select_sequential as _fixture_select_sequential,
    simulate_fixed_horizon as _fixture_simulate_fixed_horizon,
    trade_crosses_end as _fixture_trade_crosses_end,
)
from axiom_rift.v2.research.features import (
    FeatureRow as _FixtureFeatureRow,
    build_feature_rows as _fixture_build_feature_rows,
    feature_crosses_start as _fixture_feature_crosses_start,
    required_lookback as _fixture_required_lookback,
)
from axiom_rift.v2.research.modeling import (
    FittedRidge as _FixtureFittedRidge,
    ValidationBand as _FixtureValidationBand,
    fit_ridge as _fixture_fit_ridge,
)
from axiom_rift.v2.research.programs import (
    CANONICAL_ENGINE,
    DEFAULT_PROGRAM_REGISTRY_PATH,
    ProgramDefinition,
    ProgramRegistry,
    ProgramRegistryError,
    load_program_registry,
)
from axiom_rift.v2.research.autonomy import (
    HypothesisBatch,
    ResearchMap,
    ScopedNegativeMemory,
    choose_next_hypothesis,
)
from axiom_rift.v2.research.dispatch import (
    CallableProgramRegistry,
    GenericProgramRunner,
    ProgramBundle,
    ProgramDefinition as AutonomousProgramDefinition,
)
from axiom_rift.v2.research.runtime_data import (
    RuntimeDataEligibilityRegistry,
    validate_sizing_gate,
)
from axiom_rift.v2.research.samples import (
    SupervisedSample as _FixtureSupervisedSample,
    build_supervised_samples as _fixture_build_supervised_samples,
    label_crosses_end as _fixture_label_crosses_end,
)
from axiom_rift.v2.research.scout import (
    FoldWindow,
    ModelBundle,
    ScoutResult,
    ScoutSpec,
    ScoutSpecError,
    ScoutTrade,
    load_fold_windows,
    load_scout_spec,
    run_causal_scout,
)
from axiom_rift.v2.research.specs import (
    Bar as _FixtureBar,
    BoundaryPurge as _FixtureBoundaryPurge,
    FeatureSpec as _FixtureFeatureSpec,
    IndexBoundary as _FixtureIndexBoundary,
    LabelSpec as _FixtureLabelSpec,
    ModelSpec as _FixtureModelSpec,
    ResearchSpec as _FixtureResearchSpec,
    ResearchSpecError as _FixtureResearchSpecError,
    SelectorSpec as _FixtureSelectorSpec,
    TradeSpec as _FixtureTradeSpec,
)


_FIXTURE_COMPATIBILITY = {
    "Bar": _FixtureBar,
    "BoundaryPurge": _FixtureBoundaryPurge,
    "FeatureRow": _FixtureFeatureRow,
    "FeatureSpec": _FixtureFeatureSpec,
    "FittedRidge": _FixtureFittedRidge,
    "IndexBoundary": _FixtureIndexBoundary,
    "LabelSpec": _FixtureLabelSpec,
    "ModelSpec": _FixtureModelSpec,
    "ResearchResult": FixtureResearchResult,
    "ResearchSpec": _FixtureResearchSpec,
    "ResearchSpecError": _FixtureResearchSpecError,
    "SelectorSpec": _FixtureSelectorSpec,
    "Signal": _FixtureSignal,
    "SimulationResult": _FixtureSimulationResult,
    "SupervisedSample": _FixtureSupervisedSample,
    "Trade": _FixtureTrade,
    "TradeSpec": _FixtureTradeSpec,
    "UnknownCostError": _FixtureUnknownCostError,
    "ValidationBand": _FixtureValidationBand,
    "build_feature_rows": _fixture_build_feature_rows,
    "build_supervised_samples": _fixture_build_supervised_samples,
    "feature_crosses_start": _fixture_feature_crosses_start,
    "fit_ridge": _fixture_fit_ridge,
    "label_crosses_end": _fixture_label_crosses_end,
    "required_lookback": _fixture_required_lookback,
    "run_research": run_fixture_research,
    "select_sequential": _fixture_select_sequential,
    "simulate_fixed_horizon": _fixture_simulate_fixed_horizon,
    "trade_crosses_end": _fixture_trade_crosses_end,
}


def __getattr__(name: str) -> Any:
    fixture = _FIXTURE_COMPATIBILITY.get(name)
    if fixture is None:
        raise AttributeError(name)
    warnings.warn(
        f"axiom_rift.v2.research.{name} is fixture-only; use the canonical scout surface",
        DeprecationWarning,
        stacklevel=2,
    )
    return fixture


__all__ = [
    "CANONICAL_ENGINE",
    "AutonomousProgramDefinition",
    "CallableProgramRegistry",
    "DEFAULT_PROGRAM_REGISTRY_PATH",
    "FixtureResearchResult",
    "FoldWindow",
    "GenericProgramRunner",
    "HypothesisBatch",
    "ModelBundle",
    "ProgramDefinition",
    "ProgramBundle",
    "ProgramRegistry",
    "ProgramRegistryError",
    "ScoutResult",
    "ScoutSpec",
    "ScoutSpecError",
    "ScoutTrade",
    "ResearchMap",
    "RuntimeDataEligibilityRegistry",
    "ScopedNegativeMemory",
    "choose_next_hypothesis",
    "load_fold_windows",
    "load_program_registry",
    "load_scout_spec",
    "run_causal_scout",
    "run_fixture_research",
    "validate_sizing_gate",
]
