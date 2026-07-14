"""Operational raw-parity catalog for the frozen STU-0051 adapter.

This module is Job implementation evidence, not Executable semantics.  Keeping
historical artifact addresses here allows a catalog Repair without changing
the registered scientific family identity.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.research.historical_family_replay import (
    STU0051_HISTORICAL_FAMILY,
)
from axiom_rift.research.volatility_duration_replay import (
    volatility_duration_replay_configurations,
)
from axiom_rift.storage.evidence import EvidenceStore


STU0051_REPAIRED_HISTORICAL_EVALUATION_HASHES = {
    "mature_state_age_24_47-follow-h24": (
        "8e9a0c5dbeb1e66f9a714bec6479405b4ec68f03e9c803dccd96f7a68938f0c2"
    ),
    "mature_state_age_24_47-reverse-h24": (
        "1dd88cc08c88e4e4334ff16b88f3787317c7265ba0382cd82a82aeab1b12b25a"
    ),
    "persistent_state_age_72_143-follow-h24": (
        "b9da6c1e52b4a76fa6f525d7d59dcebeb5f74127c8797085d0ceeda4a95f4700"
    ),
    "persistent_state_age_72_143-reverse-h24": (
        "a678c8b9bbf3f6757eb292cd30ce2d23122da7adb53ce665925972a54ad43853"
    ),
}

_LEGACY_INFERENCE_METRICS = frozenset(
    {
        "feature_control_worst_pvalue_upper_ppm",
        "opposite_sign_pvalue_upper_ppm",
        "selection_aware_pvalue_ppm",
    }
)


def _load_historical_evaluations(
    repository_root: Path,
) -> dict[str, dict[str, Any]]:
    store = EvidenceStore(repository_root / "local" / "evidence")
    evaluations: dict[str, dict[str, Any]] = {}
    for configuration_id, identity in (
        STU0051_REPAIRED_HISTORICAL_EVALUATION_HASHES.items()
    ):
        value = parse_canonical(store.read_verified(identity))
        if (
            not isinstance(value, dict)
            or value.get("schema") != "volatility_duration_evaluation.v2"
            or value.get("subject_configuration_id") != configuration_id
        ):
            raise RuntimeError("historical STU-0051 evaluation binding drifted")
        evaluations[configuration_id] = value
    return evaluations


def assert_repaired_volatility_duration_historical_raw_parity(
    repository_root: Path,
    results: Mapping[str, Any],
) -> None:
    """Require exact raw equality while excluding obsolete inference values."""

    historical = _load_historical_evaluations(repository_root)
    configurations = volatility_duration_replay_configurations()
    by_reference = {
        configuration.historical_reference_executable_id: results[
            configuration.configuration_id
        ]
        for configuration in configurations
    }
    for configuration in configurations:
        result = results[configuration.configuration_id]
        control = STU0051_HISTORICAL_FAMILY.control_for_historical_executable(
            configuration.historical_reference_executable_id
        )
        opposite = by_reference[control.opposite_historical_executable_id]
        features = tuple(
            by_reference[value]
            for value in control.feature_historical_executable_ids
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
                "prospective STU-0051 raw results differ from historical "
                f"evidence for {configuration.configuration_id}: {mismatches}"
            )


__all__ = [
    "STU0051_REPAIRED_HISTORICAL_EVALUATION_HASHES",
    "assert_repaired_volatility_duration_historical_raw_parity",
]
