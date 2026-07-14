"""Operational raw-parity catalog for the STU-0032 replay adapter.

Historical artifact addresses are Job implementation evidence, not Executable
semantics.  A catalog correction can therefore use typed implementation Repair
without changing the registered scientific family.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from axiom_rift.core.canonical import parse_canonical
from axiom_rift.research.distribution_asymmetry_replay import (
    distribution_asymmetry_replay_configurations,
)
from axiom_rift.research.historical_family_replay import (
    STU0032_HISTORICAL_FAMILY,
)
from axiom_rift.storage.evidence import EvidenceStore


STU0032_HISTORICAL_EVALUATION_HASHES = {
    "skew_96-aligned-h48": (
        "ea85bfaacc9b36fb911033da3d0970000521efafc50881d4316360951f0585ca"
    ),
    "skew_96-aligned-h96": (
        "bf3f314a0de43d57fefcf928b463dd1e3e0ae4df30981a5c6fec9dbbc3d4d654"
    ),
    "skew_96-inverse-h48": (
        "86964b60e2b68a0abf9534499377333e4177cd13457bb4100c91215c8ecaac03"
    ),
    "skew_96-inverse-h96": (
        "50ac6949c304b4fe1c72d9978b30b5b878e6f6275e4d0b913883712de81da237"
    ),
    "skew_192-aligned-h48": (
        "3dee236523c1239eb04027f05d461e25225760618453be523919adabd0348eb5"
    ),
    "skew_192-aligned-h96": (
        "02fb11a8f31916123b38b7962fb16f4019342838aee77c0a8711a7d66f852c6f"
    ),
    "skew_192-inverse-h48": (
        "489be0ba3d2187c0a10d8c61f1edc99553e3cc6ef425ac5bc6745e6adef0c846"
    ),
    "skew_192-inverse-h96": (
        "2828560166ffa55ec010bb4383d3460d0d32778de8859b1a35a097f2992fc984"
    ),
    "semivariance_96-aligned-h48": (
        "136d5b449cc62facc7df0b873e9a0002aa49108230e7f2e8eb10b08fdeed087b"
    ),
    "semivariance_96-aligned-h96": (
        "e3c0f6d264434671b6c3d2d5b289885f70fa6c6234ad8974fccb96fd43df73b5"
    ),
    "semivariance_96-inverse-h48": (
        "9e240cdcea92fca020bc66832c9359d52faad9f8bafb6060967a5cf2c8cb642c"
    ),
    "semivariance_96-inverse-h96": (
        "cf5b8a2fc54476e2f0266e4bcd716c61c99a9469010d9f6c7fbbe82591a83078"
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
    for configuration_id, identity in STU0032_HISTORICAL_EVALUATION_HASHES.items():
        value = parse_canonical(store.read_verified(identity))
        if (
            not isinstance(value, dict)
            or value.get("schema") != "distribution_asymmetry_evaluation.v1"
            or value.get("subject_configuration_id") != configuration_id
        ):
            raise RuntimeError("historical STU-0032 evaluation binding drifted")
        evaluations[configuration_id] = value
    expected = {
        value.configuration_id
        for value in distribution_asymmetry_replay_configurations()
    }
    if set(evaluations) != expected:
        raise RuntimeError("historical STU-0032 evaluation catalog is incomplete")
    return evaluations


def assert_distribution_asymmetry_historical_raw_parity(
    repository_root: Path,
    results: Mapping[str, Any],
) -> None:
    """Require exact raw equality while excluding obsolete inference values."""

    historical = _load_historical_evaluations(repository_root)
    configurations = distribution_asymmetry_replay_configurations()
    by_reference = {
        configuration.historical_reference_executable_id: results[
            configuration.configuration_id
        ]
        for configuration in configurations
    }
    for configuration in configurations:
        result = results[configuration.configuration_id]
        control = STU0032_HISTORICAL_FAMILY.control_for_historical_executable(
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
                "prospective STU-0032 raw results differ from historical "
                f"evidence for {configuration.configuration_id}: {mismatches}"
            )


__all__ = [
    "STU0032_HISTORICAL_EVALUATION_HASHES",
    "assert_distribution_asymmetry_historical_raw_parity",
]
