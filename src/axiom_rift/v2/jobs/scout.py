"""Artifact writer for one bounded declarative V2 causal scout."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.v2.research.scout import ScoutTrade, load_scout_spec, run_causal_scout


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT).as_posix()


def _project_path(path: Path, *, must_exist: bool) -> Path:
    candidate = path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()
    root = PROJECT_ROOT.resolve()
    if root not in candidate.parents:
        raise ValueError(f"scout path escapes project root: {path}")
    if must_exist and not candidate.is_file():
        raise ValueError(f"scout input is missing: {rel(candidate)}")
    return candidate


def _validate_stage_identity(value: str, prefix: str) -> None:
    if re.fullmatch(rf"V2{prefix}[0-9]{{4}}", value) is None:
        raise ValueError(f"invalid V2 {prefix} identity: {value}")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="ascii")


def _write_trades(path: Path, trades: tuple[ScoutTrade, ...]) -> None:
    fields = [
        "fold_id",
        "signal_time",
        "entry_time",
        "exit_time",
        "direction",
        "score",
        "residual_band",
        "causal_cost_edge",
        "gross_broker_points",
        "spread_cost_broker_points",
        "net_broker_points",
        "evaluable_after_cost",
        "exclusion_reason",
        "market_day",
        "market_hour",
    ]
    with path.open("w", encoding="ascii", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for trade in trades:
            writer.writerow(trade.to_payload())


def run_scout_job(
    goal_id: str,
    hypothesis_id: str,
    stage_id: str,
    spec_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Run one preregistered scout without assuming a campaign or namespace id."""

    _validate_stage_identity(goal_id, "G")
    _validate_stage_identity(hypothesis_id, "H")
    _validate_stage_identity(stage_id, "S")
    hypothesis_path = _project_path(Path(spec_path), must_exist=True)
    work_unit_dir = _project_path(Path(output_dir), must_exist=False)
    work_unit_dir.mkdir(parents=True, exist_ok=True)
    data_config_path = PROJECT_ROOT / "configs" / "v2" / "data.yaml"
    split_config_path = PROJECT_ROOT / "configs" / "v2" / "splits.yaml"
    data_config = yaml.safe_load(data_config_path.read_text(encoding="ascii"))
    split_config = yaml.safe_load(split_config_path.read_text(encoding="ascii"))
    spec = load_scout_spec(hypothesis_path, PROJECT_ROOT)
    if spec.goal_id != goal_id:
        raise ValueError(f"goal id differs from preregistered spec: {goal_id} != {spec.goal_id}")
    if spec.hypothesis_id != hypothesis_id:
        raise ValueError(
            f"hypothesis id differs from preregistered spec: {hypothesis_id} != {spec.hypothesis_id}"
        )
    base_frame = PROJECT_ROOT / data_config["processed"]["path"]
    split_source = PROJECT_ROOT / split_config["source"]["path"]
    boundary_source = PROJECT_ROOT / data_config["boundary_source"]["path"]
    for path, expected in (
        (base_frame, data_config["processed"]["sha256"]),
        (split_source, split_config["source"]["sha256"]),
        (boundary_source, data_config["boundary_source"]["sha256"]),
    ):
        if sha256_file(path) != expected:
            raise ValueError(f"preregistered input hash mismatch: {rel(path)}")
    started_at = utc_now()
    started = time.monotonic()
    result = run_causal_scout(
        spec,
        base_frame_path=base_frame,
        split_source_path=split_source,
        boundary_source_path=boundary_source,
    )
    metrics_path = work_unit_dir / "metrics.json"
    models_path = work_unit_dir / "model_bundles.json"
    trades_path = work_unit_dir / "trades.csv"
    causal_path = work_unit_dir / "causal_checks.json"
    _write_json(metrics_path, result.metrics)
    _write_json(
        models_path,
        {
            "schema": "axiom_rift_v2_scout_model_bundles_v1",
            "models": [model.to_payload() for model in result.models],
            "claim_ceiling": "diagnostic_observation",
        },
    )
    _write_trades(trades_path, result.trades)
    _write_json(causal_path, result.causal_checks)
    receipt = {
        "schema": "axiom_rift_v2_scout_receipt_v1",
        "status": "completed",
        "goal_id": goal_id,
        "hypothesis_id": spec.hypothesis_id,
        "stage": "S",
        "stage_id": stage_id,
        "started_at_utc": started_at,
        "completed_at_utc": utc_now(),
        "duration_seconds": time.monotonic() - started,
        "outcome": result.outcome,
        "gate_passed": result.gate_passed,
        "claim_ceiling": result.claim_ceiling,
        "economics_claim_allowed": False,
        "mt5_executed": False,
        "isolated_nine_fold_executed": False,
        "spec_path": rel(hypothesis_path),
        "spec_sha256": sha256_file(hypothesis_path),
        "spec_payload_sha256": spec.spec_sha256,
        "program_registry_path": spec.program_registry_path,
        "program_registry_sha256": spec.program_registry_sha256,
        "programs": spec.program_identities,
        "dataset_path": rel(base_frame),
        "dataset_sha256": sha256_file(base_frame),
        "split_source_path": rel(split_source),
        "split_source_sha256": sha256_file(split_source),
        "boundary_source_path": rel(boundary_source),
        "boundary_source_sha256": sha256_file(boundary_source),
        "result_sha256": result.result_sha256,
        "artifacts": {
            "metrics": {"path": rel(metrics_path), "sha256": sha256_file(metrics_path)},
            "models": {"path": rel(models_path), "sha256": sha256_file(models_path)},
            "trades": {"path": rel(trades_path), "sha256": sha256_file(trades_path)},
            "causal_checks": {"path": rel(causal_path), "sha256": sha256_file(causal_path)},
        },
    }
    receipt_path = work_unit_dir / "receipt.json"
    _write_json(receipt_path, receipt)
    return receipt


def run_v2s0001_job(work_unit_dir: Path) -> dict[str, Any]:
    """Bootstrap-legacy compatibility wrapper; new work calls run_scout_job."""

    return run_scout_job(
        "V2G0001",
        "V2H0001",
        "V2S0001",
        Path("campaigns/v2/V2G0001_v2_activation/hypotheses/V2H0001.yaml"),
        work_unit_dir,
    )
