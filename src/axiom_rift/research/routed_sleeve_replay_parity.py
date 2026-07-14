"""Shared raw-parity proof for historical routed-sleeve replay adapters."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.research.historical_family_replay import HistoricalFamilySpec
from axiom_rift.research.routed_sleeve_replay import RoutedReplayConfiguration
from axiom_rift.storage.evidence import EvidenceStore


_LEGACY_INFERENCE_METRICS = frozenset(
    {
        "feature_control_worst_pvalue_upper_ppm",
        "opposite_sign_pvalue_upper_ppm",
        "selection_aware_pvalue_ppm",
    }
)


def assert_routed_sleeve_historical_raw_parity(
    repository_root: Path,
    results: Mapping[str, Any],
    *,
    family: HistoricalFamilySpec,
    configurations: tuple[RoutedReplayConfiguration, ...],
    evaluation_hashes: Mapping[str, str],
    evaluation_schema: str,
) -> None:
    """Require exact raw equality while excluding obsolete inference values."""

    expected_configuration_ids = {
        configuration.configuration_id for configuration in configurations
    }
    if set(evaluation_hashes) != expected_configuration_ids:
        raise RuntimeError("historical routed evaluation catalog is incomplete")
    if set(results) != expected_configuration_ids:
        raise RuntimeError("prospective routed result family is incomplete")

    store = EvidenceStore(repository_root / "local" / "evidence")
    historical: dict[str, dict[str, Any]] = {}
    by_configuration = {
        configuration.configuration_id: configuration
        for configuration in configurations
    }
    for configuration_id, identity in evaluation_hashes.items():
        value = parse_canonical(store.read_verified(identity))
        configuration = by_configuration[configuration_id]
        if (
            not isinstance(value, dict)
            or value.get("schema") != evaluation_schema
            or value.get("subject_configuration_id") != configuration_id
            or value.get("subject_executable_id")
            != configuration.historical_reference_executable_id
        ):
            raise RuntimeError("historical routed evaluation binding drifted")
        historical[configuration_id] = value

    by_reference = {
        configuration.historical_reference_executable_id: results[
            configuration.configuration_id
        ]
        for configuration in configurations
    }
    for configuration in configurations:
        result = results[configuration.configuration_id]
        control = family.control_for_historical_executable(
            configuration.historical_reference_executable_id
        )
        opposite = by_reference[control.opposite_historical_executable_id]
        features = tuple(
            by_reference[identity]
            for identity in control.feature_historical_executable_ids
        )
        observed_metrics = {
            **{
                name: value
                for name, value in result.metrics.items()
                if name not in _LEGACY_INFERENCE_METRICS
            },
            "feature_control_worst_delta_net_profit_micropoints": min(
                result.metrics["net_profit_micropoints"]
                - value.metrics["net_profit_micropoints"]
                for value in features
            ),
            "opposite_sign_worst_delta_net_profit_micropoints": (
                result.metrics["net_profit_micropoints"]
                - opposite.metrics["net_profit_micropoints"]
            ),
        }
        expected = historical[configuration.configuration_id]
        expected_metrics = {
            name: value
            for name, value in expected["metrics"].items()
            if name not in _LEGACY_INFERENCE_METRICS
        }
        surfaces = {
            "metrics": (observed_metrics, expected_metrics),
            "fold_metrics": (result.fold_metrics, expected["fold_metrics"]),
            "regime_metrics": (
                result.regime_metrics,
                expected["regime_metrics"],
            ),
            "session_metrics": (
                result.session_metrics,
                expected["session_metrics"],
            ),
            "direction_metrics": (
                result.direction_metrics,
                expected["direction_metrics"],
            ),
        }
        mismatches = {
            name: {"expected": expected_value, "observed": observed_value}
            for name, (observed_value, expected_value) in surfaces.items()
            if observed_value != expected_value
        }
        if mismatches:
            raise RuntimeError(
                "prospective routed raw results differ from historical "
                f"evidence for {configuration.configuration_id}: {mismatches}"
            )


__all__ = ["assert_routed_sleeve_historical_raw_parity"]
