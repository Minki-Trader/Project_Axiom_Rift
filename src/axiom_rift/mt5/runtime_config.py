"""Runtime configuration helpers for MT5 runners."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from axiom_rift.paths import CONFIG_DIR, PROJECT_ROOT


RUNTIME_CONFIG_PATH = CONFIG_DIR / "runtime.yaml"
LOGIC_PARITY_MODE = "logic_parity"
TICK_EXECUTION_MODE = "tick_execution"


class RuntimeConfigError(ValueError):
    """Raised when the active runtime config is incomplete or unsafe."""


@dataclass(frozen=True)
class RuntimeConfig:
    path: Path
    data: dict[str, Any]
    sha256: str

    @property
    def mt5(self) -> dict[str, Any]:
        return _mapping(self.data, "mt5")

    @property
    def execution(self) -> dict[str, Any]:
        return _mapping(self.data, "execution")

    @property
    def claim_boundary(self) -> dict[str, Any]:
        return _mapping(self.data, "claim_boundary")

    @property
    def terminal_exe(self) -> Path:
        return Path(_required(self.mt5, "terminal_exe"))

    @property
    def metaeditor_exe(self) -> Path:
        return Path(_required(self.mt5, "metaeditor_exe"))

    @property
    def terminal_data_dir(self) -> Path:
        return Path(_required(self.mt5, "terminal_data_dir"))

    @property
    def symbol(self) -> str:
        return str(_required(self.mt5, "symbol"))

    @property
    def timeframe(self) -> str:
        return str(_required(self.mt5, "timeframe"))

    @property
    def deposit(self) -> float:
        return float(_required(self.mt5, "deposit"))

    @property
    def deposit_currency(self) -> str:
        return str(_required(self.mt5, "deposit_currency"))

    @property
    def leverage(self) -> int:
        return int(_required(self.mt5, "leverage"))

    @property
    def execution_mode(self) -> int:
        return int(_required(self.mt5, "execution_mode"))

    @property
    def default_lot(self) -> float:
        return float(_required(self.execution, "default_lot"))

    def tester_model_for_mode(self, mode: str) -> int:
        if mode == LOGIC_PARITY_MODE:
            return int(_required(self.mt5, "logic_parity_model"))
        if mode == TICK_EXECUTION_MODE:
            return int(_required(self.mt5, "tick_execution_model"))
        raise RuntimeConfigError(f"Unsupported MT5 mode for tester model: {mode}")

    def tester_account_lines(self) -> list[str]:
        return [
            f"Deposit={format_runtime_number(self.deposit)}",
            f"Currency={self.deposit_currency}",
            f"Leverage={self.leverage}",
            f"ExecutionMode={self.execution_mode}",
        ]

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema": self.data.get("schema"),
            "status": self.data.get("status"),
            "mt5": _snapshot_section(self.mt5),
            "execution": _snapshot_section(self.execution),
            "claim_boundary": _snapshot_section(self.claim_boundary),
        }

    def payload_fields(self) -> dict[str, Any]:
        return {
            "runtime_config_path": rel(self.path),
            "runtime_config_sha256": self.sha256,
            "runtime_config_snapshot": self.snapshot(),
        }


def load_runtime_config(path: Path = RUNTIME_CONFIG_PATH) -> RuntimeConfig:
    path = path.resolve()
    if not path.exists():
        raise RuntimeConfigError(f"Runtime config not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    if not isinstance(data, dict):
        raise RuntimeConfigError(f"Runtime config must be a mapping: {path}")
    cfg = RuntimeConfig(path=path, data=data, sha256=sha256_file(path))
    validate_runtime_config(cfg)
    return cfg


def validate_runtime_config(cfg: RuntimeConfig) -> None:
    for key in (
        "terminal_exe",
        "metaeditor_exe",
        "terminal_data_dir",
        "broker_server",
        "symbol",
        "timeframe",
        "tester_model",
        "logic_parity_model",
        "tick_execution_model",
        "deposit",
        "deposit_currency",
        "leverage",
        "terminal_mode",
        "execution_mode",
    ):
        _required(cfg.mt5, key)
    for key in ("signal_timing", "position_management", "default_lot", "cost_behavior"):
        _required(cfg.execution, key)
    if cfg.claim_boundary.get("active_runtime_config_complete") is not True:
        raise RuntimeConfigError("Runtime config must set active_runtime_config_complete: true")
    if cfg.claim_boundary.get("runtime_authority") is not False:
        raise RuntimeConfigError("Runtime config must not claim runtime_authority")
    if cfg.claim_boundary.get("live_ready") is not False:
        raise RuntimeConfigError("Runtime config must not claim live_ready")
    if str(_required(cfg.mt5, "terminal_mode")) != "headless":
        raise RuntimeConfigError("Only terminal_mode: headless is supported")


def terminal_exe() -> Path:
    return load_runtime_config().terminal_exe


def metaeditor_exe() -> Path:
    return load_runtime_config().metaeditor_exe


def terminal_data_dir() -> Path:
    return load_runtime_config().terminal_data_dir


def runtime_symbol() -> str:
    return load_runtime_config().symbol


def runtime_timeframe() -> str:
    return load_runtime_config().timeframe


def starting_balance_usd() -> float:
    return load_runtime_config().deposit


def default_lot() -> float:
    return load_runtime_config().default_lot


def lot_input_line() -> str:
    return f"InpLot={format_runtime_number(default_lot())}"


def tester_model_for_mode(mode: str) -> int:
    return load_runtime_config().tester_model_for_mode(mode)


def tester_model_label_for_mode(mode: str) -> str:
    return tester_model_label_for_code(tester_model_for_mode(mode))


def tester_model_label_for_code(model_code: int | str) -> str:
    labels = {
        "1": "ohlc_model_1",
        "2": "open_prices_model_2",
        "4": "real_ticks_model_4",
    }
    value = str(model_code)
    return labels.get(value, f"mt5_model_{value}" if value else "unknown")


def tester_account_lines() -> list[str]:
    return load_runtime_config().tester_account_lines()


def runtime_payload_fields() -> dict[str, Any]:
    return load_runtime_config().payload_fields()


def format_runtime_number(value: float | int) -> str:
    numeric = float(value)
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:g}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise RuntimeConfigError(f"Runtime config section must be a mapping: {key}")
    return value


def _required(data: dict[str, Any], key: str) -> Any:
    value = data.get(key)
    if value is None or value == "":
        raise RuntimeConfigError(f"Runtime config required field is missing or null: {key}")
    return value


def _snapshot_section(section: dict[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in section.items()}
