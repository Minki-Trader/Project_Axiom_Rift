"""Historical raw-parity catalog for the STU-0017 replay adapter."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from axiom_rift.research.composite_consensus_replay import (
    composite_consensus_replay_configurations,
)
from axiom_rift.research.historical_family_replay import (
    STU0017_HISTORICAL_FAMILY,
)
from axiom_rift.research.routed_sleeve_replay_parity import (
    assert_routed_sleeve_historical_raw_parity,
)


STU0017_HISTORICAL_EVALUATION_HASHES = {
    "full_regime_consensus-inverted-h24": (
        "9770e418a32d8d25ebead1f4e1c2e4b8a57e82ecafe036614c58d89ed4116aa4"
    ),
    "full_regime_consensus-inverted-h48": (
        "9f45ebe72a2f1e7b731d3b5b31372117095dade5087fed8392847fc8e16e15ad"
    ),
    "full_regime_consensus-routed-h24": (
        "c1a9451e2e6d8ddde956d9694fcb3dc59e0060c10b8a645fcf981bbc867ecefc"
    ),
    "full_regime_consensus-routed-h48": (
        "94c2b39da3de3f7bf17ee515e6b76a37ef35951bac6d06efd6feb84cf08ca383"
    ),
    "volume_primary_all_regimes-inverted-h24": (
        "b7fe6fb3793acd6cbfd347844afc38d7beb57351f347a21970a170c842f6a299"
    ),
    "volume_primary_all_regimes-inverted-h48": (
        "4e3eca2af1d6186bf2f046d06bd345886c3d90ee14e0ed54ff7e26dc895b89c2"
    ),
    "volume_primary_all_regimes-routed-h24": (
        "3cab4a8dfbb20a664796dc3364812bfdc1ceb0406a2779ac231e4fe1c716476d"
    ),
    "volume_primary_all_regimes-routed-h48": (
        "dfd4ac9244fdd203c2bd94e1f7394e7fa590ccf91fe9957dba39461652c5316d"
    ),
    "middle_consensus_no_high-inverted-h24": (
        "e8c243f7e3cbf12aa85492c3d0389fd12ca13c350a8db3655cc905b619f11afd"
    ),
    "middle_consensus_no_high-inverted-h48": (
        "3c4cab5d61454cf17a8b06db06f95af2e173fe25899b65c93c7efb205f383f61"
    ),
    "middle_consensus_no_high-routed-h24": (
        "d9ee603122462ce5dd2134d7424afe2184d1b9d8b29442a67cc22ca21c7f4118"
    ),
    "middle_consensus_no_high-routed-h48": (
        "1bf8f6ff98216317d8a5e419c715618fbee08a01886360d9ca42b3455b50ecc5"
    ),
}


def assert_composite_consensus_historical_raw_parity(
    repository_root: Path,
    results: Mapping[str, Any],
) -> None:
    assert_routed_sleeve_historical_raw_parity(
        repository_root,
        results,
        family=STU0017_HISTORICAL_FAMILY,
        configurations=composite_consensus_replay_configurations(),
        evaluation_hashes=STU0017_HISTORICAL_EVALUATION_HASHES,
        evaluation_schema="composite_consensus_evaluation.v1",
    )


__all__ = [
    "STU0017_HISTORICAL_EVALUATION_HASHES",
    "assert_composite_consensus_historical_raw_parity",
]
