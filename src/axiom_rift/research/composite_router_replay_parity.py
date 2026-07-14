"""Historical raw-parity catalog for the STU-0016 replay adapter."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from axiom_rift.research.composite_router_replay import (
    composite_router_replay_configurations,
)
from axiom_rift.research.historical_family_replay import (
    STU0016_HISTORICAL_FAMILY,
)
from axiom_rift.research.routed_sleeve_replay_parity import (
    assert_routed_sleeve_historical_raw_parity,
)


STU0016_HISTORICAL_EVALUATION_HASHES = {
    "three_sleeve_router-inverted-h12": (
        "a353c2005b26ccec53d1fa5c2fe62744e04608d8d6a5fc2d13fb83e02f84832c"
    ),
    "three_sleeve_router-inverted-h48": (
        "5c0123f93b14ca853890e8573387d4473ae8d07c45e313a26b5f52c3f72aa741"
    ),
    "three_sleeve_router-routed-h12": (
        "56a5497d072a30bc96667d4ddbb19bf83615493a1f8624321f8afd7ec704d106"
    ),
    "three_sleeve_router-routed-h48": (
        "0064ca9cf96e26dcca30f989ee345b1428e34604bfcec3541d8730b8e14cc0ba"
    ),
    "volume_reversion_ablation-inverted-h12": (
        "8ce5c33ad4e27bb185c06644f32975e24e0d5106f59df452e76ef95393057bbf"
    ),
    "volume_reversion_ablation-inverted-h48": (
        "01030e9bf56faee17c22d7a6779ad6669bc225a5a5b2758ffe53d847b2e9c505"
    ),
    "volume_reversion_ablation-routed-h12": (
        "a10c3b5be0ba2fe268fea896aba428047e8ca6f282494b726b5cea3ee6e75888"
    ),
    "volume_reversion_ablation-routed-h48": (
        "a07986518fc0f8c36725b222d152437c9d8aff8af063f530fef1895efe5815c1"
    ),
    "volume_volatility_ablation-inverted-h12": (
        "d61795eef4b75247d69549a3b0434927f91fb3500e83dc33c0637a6478a9b46b"
    ),
    "volume_volatility_ablation-inverted-h48": (
        "246cd357e751f25d022df77882b871932027000a6247a056485adbef98cac9d7"
    ),
    "volume_volatility_ablation-routed-h12": (
        "b239420846378bf0f00ecbbcebe5616c3ccfda35d954f1e79b2c44a1e9432a51"
    ),
    "volume_volatility_ablation-routed-h48": (
        "59bf3f0c22ca4ec21b074d2faafc50a61120cb5e7c5eb8129d08105507eb05d0"
    ),
}


def assert_composite_router_historical_raw_parity(
    repository_root: Path,
    results: Mapping[str, Any],
) -> None:
    assert_routed_sleeve_historical_raw_parity(
        repository_root,
        results,
        family=STU0016_HISTORICAL_FAMILY,
        configurations=composite_router_replay_configurations(),
        evaluation_hashes=STU0016_HISTORICAL_EVALUATION_HASHES,
        evaluation_schema="composite_router_evaluation.v1",
    )


__all__ = [
    "STU0016_HISTORICAL_EVALUATION_HASHES",
    "assert_composite_router_historical_raw_parity",
]
