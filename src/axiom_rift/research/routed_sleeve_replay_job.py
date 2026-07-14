"""Shared runtime-adapter factory for routed-sleeve replay families."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import axiom_rift.core.identity as identity_module
import axiom_rift.research.chassis as chassis_module
import axiom_rift.research.data as data_module
import axiom_rift.research.discovery as discovery_module
import axiom_rift.research.fixed_hold_family_trace as fixed_hold_trace_module
import axiom_rift.research.governance as governance_module
import axiom_rift.research.historical_family_replay as historical_family_module
import axiom_rift.research.reversion_discovery as reversion_module
import axiom_rift.research.routed_sleeve_replay as routed_replay_module
import axiom_rift.research.routed_sleeve_replay_parity as shared_parity_module
import axiom_rift.research.routed_sleeve_trace_engine as trace_engine_module
import axiom_rift.research.scientific_trace as scientific_trace_module
import axiom_rift.research.selection_inference as selection_inference_module
import axiom_rift.research.volatility_discovery as volatility_module
import axiom_rift.research.volume_price_discovery as volume_price_module
import axiom_rift.storage.evidence as evidence_module
from axiom_rift.research.fixed_hold_family_trace import (
    FixedHoldProtocolDefinition,
)
from axiom_rift.research.fixed_hold_replay_runtime import (
    FixedHoldReplayRuntimeAdapter,
)
from axiom_rift.research.routed_sleeve_trace_engine import (
    FeatureBuilder,
    RawParityValidator,
    RouterCalibrator,
    ScoreRouter,
    SpreadBuilder,
    compute_routed_sleeve_family_trace,
)


ConfigurationBuilder = Callable[[], tuple[object, ...]]
DefinitionBuilder = Callable[..., FixedHoldProtocolDefinition]
_THIS_FILE = Path(__file__).resolve()


def build_routed_sleeve_runtime_adapter(
    *,
    callable_identity: str,
    job_implementation_protocol: str,
    artifact_namespace: str,
    adapter_source_path: Path,
    job_source_path: Path,
    source_module_path: Path,
    parity_module_path: Path,
    configurations: ConfigurationBuilder,
    protocol_definition: DefinitionBuilder,
    feature_builder: FeatureBuilder,
    router_calibrator: RouterCalibrator,
    score_router: ScoreRouter,
    spread_builder: SpreadBuilder,
    raw_parity_validator: RawParityValidator,
) -> FixedHoldReplayRuntimeAdapter:
    """Bind one thin family adapter into the proven fixed-hold runtime."""

    def definition(prior_global_exposure_count: int) -> FixedHoldProtocolDefinition:
        return protocol_definition(
            historical_context_prior_global_exposure_count=(
                prior_global_exposure_count
            )
        )

    def trace(
        repository_root: Path,
        prior_global_exposure_count: int,
    ) -> tuple[dict[str, object], dict[str, dict[str, int]]]:
        return compute_routed_sleeve_family_trace(
            repository_root,
            definition=definition(prior_global_exposure_count),
            configurations=configurations(),
            feature_builder=feature_builder,
            router_calibrator=router_calibrator,
            score_router=score_router,
            spread_builder=spread_builder,
            raw_parity_validator=raw_parity_validator,
        )

    dependency_paths = {
        _THIS_FILE,
        Path(identity_module.__file__).resolve(),
        Path(chassis_module.__file__).resolve(),
        Path(data_module.__file__).resolve(),
        Path(discovery_module.__file__).resolve(),
        Path(evidence_module.__file__).resolve(),
        Path(fixed_hold_trace_module.__file__).resolve(),
        Path(governance_module.__file__).resolve(),
        Path(historical_family_module.__file__).resolve(),
        Path(reversion_module.__file__).resolve(),
        Path(routed_replay_module.__file__).resolve(),
        Path(scientific_trace_module.__file__).resolve(),
        Path(selection_inference_module.__file__).resolve(),
        Path(shared_parity_module.__file__).resolve(),
        Path(trace_engine_module.__file__).resolve(),
        Path(volatility_module.__file__).resolve(),
        Path(volume_price_module.__file__).resolve(),
        Path(adapter_source_path).resolve(),
        Path(job_source_path).resolve(),
        Path(source_module_path).resolve(),
        Path(parity_module_path).resolve(),
    }
    component_source_paths = {
        Path(adapter_source_path).resolve(),
        Path(data_module.__file__).resolve(),
        Path(discovery_module.__file__).resolve(),
        Path(fixed_hold_trace_module.__file__).resolve(),
        Path(historical_family_module.__file__).resolve(),
        Path(reversion_module.__file__).resolve(),
        Path(routed_replay_module.__file__).resolve(),
        Path(source_module_path).resolve(),
        Path(trace_engine_module.__file__).resolve(),
        Path(volatility_module.__file__).resolve(),
        Path(volume_price_module.__file__).resolve(),
    }
    return FixedHoldReplayRuntimeAdapter(
        callable_identity=callable_identity,
        job_implementation_protocol=job_implementation_protocol,
        artifact_namespace=artifact_namespace,
        adapter_source_path=Path(adapter_source_path).resolve(),
        dependency_paths=tuple(
            sorted(dependency_paths, key=lambda value: value.as_posix())
        ),
        component_source_paths=tuple(
            sorted(component_source_paths, key=lambda value: value.as_posix())
        ),
        expected_family_size=12,
        context_parameter_name=(
            "historical_context_prior_global_exposure_count"
        ),
        definition_builder=definition,
        trace_builder=trace,
    )


__all__ = [
    "ConfigurationBuilder",
    "DefinitionBuilder",
    "build_routed_sleeve_runtime_adapter",
]
