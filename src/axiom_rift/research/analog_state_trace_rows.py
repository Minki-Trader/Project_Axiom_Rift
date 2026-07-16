"""ID-free causal row helpers shared by analog replay implementations."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.analog_state_family import AnalogFamilyConfiguration
from axiom_rift.research.completed_period_atomic_trace import (
    AtomicFixedHoldMember,
    completed_period_atomic_trace_implementation_sha256,
    materialize_fixed_hold_intent_rows,
    materialize_fixed_hold_trade_rows,
)


MICROPOINTS_PER_POINT = 1_000_000
_THIS_FILE = Path(__file__).resolve()


def analog_trace_rows_implementation_sha256() -> str:
    """Bind the ID-free row materialization implementation into replay identity."""

    return sha256(
        _THIS_FILE.read_bytes()
        + bytes.fromhex(
            completed_period_atomic_trace_implementation_sha256()
        )
    ).hexdigest()


def digest_causal_surfaces(
    surfaces: tuple[tuple[str, np.ndarray], ...],
) -> str:
    """Hash every causal input surface consumed by an analog simulation."""

    if type(surfaces) is not tuple or not surfaces:
        raise ValueError("analog causal replay surfaces are absent")
    digest = sha256()
    digest.update(b"analog-causal-input-surfaces.v1\0")
    digest.update(len(surfaces).to_bytes(4, "big"))
    names: set[str] = set()
    for name, values in surfaces:
        if (
            type(name) is not str
            or not name
            or not name.isascii()
            or name in names
        ):
            raise ValueError("analog causal replay surface name is invalid")
        names.add(name)
        encoded_name = name.encode("ascii")
        array = np.asarray(values, dtype="<f8").copy(order="C")
        if array.ndim == 0:
            raise ValueError("analog causal replay surface is not an array")
        array[np.isnan(array)] = np.nan
        digest.update(len(encoded_name).to_bytes(4, "big"))
        digest.update(encoded_name)
        digest.update(array.ndim.to_bytes(4, "big"))
        for size in array.shape:
            digest.update(int(size).to_bytes(8, "big"))
        digest.update(array.nbytes.to_bytes(8, "big"))
        digest.update(memoryview(array).cast("B"))
    return digest.hexdigest()


def iso_timestamp(value: object) -> str:
    return pd.Timestamp(value).isoformat()


def _observation_id(kind: str, value: Mapping[str, Any]) -> str:
    payload = {
        key: item for key, item in value.items() if key != "observation_id"
    }
    return "observation:" + canonical_digest(
        domain=f"analog-{kind}-observation",
        payload=payload,
    )


def trade_rows(
    *,
    configuration: AnalogFamilyConfiguration,
    executable_id: str,
    simulations: Mapping[tuple[str, str], Any],
    frame: pd.DataFrame,
    effective_spread: np.ndarray,
) -> list[dict[str, object]]:
    return materialize_fixed_hold_trade_rows(
        member=AtomicFixedHoldMember(
            configuration_id=configuration.configuration_id,
            executable_id=executable_id,
            historical_reference_executable_id=(
                configuration.historical_reference_executable_id
            ),
            holding_bars=configuration.holding_bars,
        ),
        simulations=simulations,
        frame=frame,
        effective_spread=effective_spread,
        observation_id=_observation_id,
    )


def intent_rows(
    *,
    configuration: AnalogFamilyConfiguration,
    executable_id: str,
    simulations: Mapping[tuple[str, str], Any],
    frame: pd.DataFrame,
    effective_spread: np.ndarray,
) -> list[dict[str, object]]:
    return materialize_fixed_hold_intent_rows(
        member=AtomicFixedHoldMember(
            configuration_id=configuration.configuration_id,
            executable_id=executable_id,
            historical_reference_executable_id=(
                configuration.historical_reference_executable_id
            ),
            holding_bars=configuration.holding_bars,
        ),
        simulations=simulations,
        frame=frame,
        effective_spread=effective_spread,
        observation_id=_observation_id,
    )


__all__ = [
    "MICROPOINTS_PER_POINT",
    "analog_trace_rows_implementation_sha256",
    "digest_causal_surfaces",
    "intent_rows",
    "iso_timestamp",
    "trade_rows",
]
