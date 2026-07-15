"""ID-free causal row helpers shared by analog replay implementations."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from axiom_rift.core.identity import canonical_digest
from axiom_rift.research.analog_state_family import AnalogFamilyConfiguration


MICROPOINTS_PER_POINT = 1_000_000
_THIS_FILE = Path(__file__).resolve()


def analog_trace_rows_implementation_sha256() -> str:
    """Bind the ID-free row materialization implementation into replay identity."""

    return sha256(_THIS_FILE.read_bytes()).hexdigest()


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


def _micropoints(value: object) -> int:
    return int(round(float(value) * MICROPOINTS_PER_POINT))


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
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for (fold_id, scope), simulation in simulations.items():
        if scope != "full":
            continue
        for raw in simulation.trades.to_dict(orient="records"):
            gross = _micropoints(raw["gross_pnl"])
            native_cost = _micropoints(raw["native_cost"])
            stress_cost = _micropoints(raw["stress_cost"])
            row: dict[str, object] = {
                "availability_time": iso_timestamp(raw["decision_time"]),
                "configuration_id": configuration.configuration_id,
                "decision_bar_open_time": iso_timestamp(
                    raw["decision_bar_open_time"]
                ),
                "decision_time": iso_timestamp(raw["decision_time"]),
                "direction": int(raw["direction"]),
                "entry_time": iso_timestamp(raw["entry_time"]),
                "executable_id": executable_id,
                "exit_time": iso_timestamp(raw["exit_time"]),
                "fold_id": fold_id,
                "gross_pnl_micropoints": gross,
                "historical_reference_executable_id": (
                    configuration.historical_reference_executable_id
                ),
                "native_cost_micropoints": native_cost,
                "native_net_pnl_micropoints": gross - native_cost,
                "observation_id": "pending",
                "regime": str(raw["regime"]),
                "stress_cost_micropoints": stress_cost,
                "stress_net_pnl_micropoints": gross - stress_cost,
            }
            row["observation_id"] = _observation_id("trade", row)
            rows.append(row)
    return rows


def intent_rows(
    *,
    configuration: AnalogFamilyConfiguration,
    executable_id: str,
    simulations: Mapping[tuple[str, str], Any],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for (fold_id, scope), simulation in simulations.items():
        for ordinal, raw in enumerate(simulation.intent_rows, start=1):
            decision, entry, exit_time, direction, status = raw
            row: dict[str, object] = {
                "availability_time": iso_timestamp(decision),
                "configuration_id": configuration.configuration_id,
                "decision_time": iso_timestamp(decision),
                "direction": int(direction),
                "entry_time": iso_timestamp(entry),
                "executable_id": executable_id,
                "exit_time": iso_timestamp(exit_time),
                "fold_id": fold_id,
                "observation_id": "pending",
                "ordinal": ordinal,
                "scope": scope,
                "status": str(status),
            }
            row["observation_id"] = _observation_id("intent", row)
            rows.append(row)
    return rows


__all__ = [
    "MICROPOINTS_PER_POINT",
    "analog_trace_rows_implementation_sha256",
    "digest_causal_surfaces",
    "intent_rows",
    "iso_timestamp",
    "trade_rows",
]
