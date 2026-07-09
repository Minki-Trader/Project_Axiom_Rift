"""One-shot hash-keyed validation job for the unchanged V2 base dataset."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.v2.data.blackouts import load_non_allow_gaps, summarize_non_allow_boundaries
from axiom_rift.v2.data.datasets import compare_raw_to_base, inspect_base_frame, sha256_file
from axiom_rift.v2.data.splits import adapt_split_set
from axiom_rift.v2.identity import sha256_payload
from axiom_rift.v2.operations import MaterialRecord


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rel(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT).as_posix()


def predicted_material_object_id(material_id: str, kind: str, payload: dict[str, Any]) -> str:
    material_payload = {"material_id": material_id, "kind": kind, **payload}
    return sha256_payload(
        {
            "schema": "axiom_rift_v2_object_v1",
            "kind": "material",
            "payload": material_payload,
        }
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="ascii")


def run_corrected_data_identity_job(work_dir: Path) -> tuple[tuple[MaterialRecord, ...], dict[str, Any]]:
    work_dir = work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    started_at = utc_now()
    started = time.monotonic()
    data_config_path = PROJECT_ROOT / "configs" / "v2" / "data.yaml"
    split_config_path = PROJECT_ROOT / "configs" / "v2" / "splits.yaml"
    data_config = yaml.safe_load(data_config_path.read_text(encoding="ascii"))
    split_config = yaml.safe_load(split_config_path.read_text(encoding="ascii"))
    raw_path = PROJECT_ROOT / data_config["raw"]["path"]
    base_path = PROJECT_ROOT / data_config["processed"]["path"]
    boundary_path = PROJECT_ROOT / data_config["boundary_source"]["path"]
    split_source = PROJECT_ROOT / split_config["source"]["path"]
    dataset_receipt = inspect_base_frame(base_path, data_config["processed"]["sha256"])
    raw_comparison = compare_raw_to_base(raw_path, base_path)
    gaps = load_non_allow_gaps(boundary_path)
    boundary_summary = summarize_non_allow_boundaries(gaps)
    if raw_comparison["mismatch_count"] != 0:
        raise ValueError("raw and processed base frame differ")
    if boundary_summary["non_allow_boundary_count"] != data_config["boundary_source"]["non_allow_boundary_count"]:
        raise ValueError("non-ALLOW boundary count differs from the V2 config")
    observed = data_config["cost_quality"]["observed_counts"]
    if dataset_receipt["zero_spread_count"] != observed["full_dataset_zero_spread"]:
        raise ValueError("zero-spread count differs from the V2 config")
    dataset_payload = {
        "canonical_path": rel(base_path),
        "content_sha256": sha256_file(base_path),
        "schema_version": dataset_receipt["schema"],
        "producer_code_path": "src/axiom_rift/v2/data/datasets.py",
        "producer_code_sha256": sha256_file(PROJECT_ROOT / "src" / "axiom_rift" / "v2" / "data" / "datasets.py"),
        "input_material_ids": ["V2MAT000006", "V2MAT000007", "V2MAT000008"],
        "availability_semantics": "broker_server_bar_open_closed_at_plus_5_minutes",
        "portability": "python_mql_rates_schema",
        "legacy_origin": {
            "origin": "v1_reuse",
            "source_path": rel(base_path),
            "decision": "adapt",
            "deficiency": "zero_spread_and_real_volume_semantics_were_not_bound_in_prior_receipt",
            "parity_boundary": "raw_to_processed_rows_exact",
            "rollback_boundary": "V2MAT000009",
        },
        "dataset_receipt": dataset_receipt,
        "raw_comparison": raw_comparison,
        "boundary_summary": boundary_summary,
        "claim_ceiling": "none",
    }
    dataset_object_id = predicted_material_object_id("V2MAT000011", "dataset", dataset_payload)
    split_payload_body = adapt_split_set(
        split_source,
        split_config["source"]["sha256"],
        dataset_object_id,
        data_config["processed"]["sha256"],
    )
    split_payload = {
        "canonical_path": rel(split_config_path),
        "content_sha256": sha256_payload(split_payload_body),
        "schema_version": split_payload_body["schema"],
        "producer_code_path": "src/axiom_rift/v2/data/splits.py",
        "producer_code_sha256": sha256_file(PROJECT_ROOT / "src" / "axiom_rift" / "v2" / "data" / "splits.py"),
        "input_material_ids": ["V2MAT000011", "V2MAT000007"],
        "availability_semantics": "role_gated_development_only",
        "portability": "v2_stage_access_contract",
        "legacy_origin": {
            "origin": "v1_reuse",
            "source_path": rel(split_source),
            "decision": "adapt",
            "deficiency": "legacy_test_role_was_repeatedly_observed_and_anchors_were_seasonally_aliased",
            "parity_boundary": "time_boundaries_only_no_claims",
            "rollback_boundary": "V2MAT000010",
        },
        "split_set": split_payload_body,
        "claim_ceiling": "none",
    }
    records = (
        MaterialRecord("V2MAT000011", "dataset", dataset_payload),
        MaterialRecord("V2MAT000012", "split_set", split_payload),
    )
    dataset_path = work_dir / "dataset_receipt.json"
    split_path = work_dir / "split_set.json"
    _write_json(dataset_path, dataset_receipt)
    _write_json(split_path, split_payload_body)
    receipt = {
        "schema": "axiom_rift_v2_data_identity_evidence_v1",
        "status": "passed",
        "goal_id": "V2G0001",
        "stage": "bootstrap",
        "stage_id": "V2B0001",
        "started_at_utc": started_at,
        "completed_at_utc": utc_now(),
        "duration_seconds": time.monotonic() - started,
        "dataset_material_id": "V2MAT000011",
        "dataset_material_object_id": dataset_object_id,
        "split_set_material_id": "V2MAT000012",
        "dataset_sha256": dataset_receipt["sha256"],
        "row_count": dataset_receipt["row_count"],
        "zero_spread_count": dataset_receipt["zero_spread_count"],
        "zero_spread_semantics": "unknown_cost",
        "real_volume_eligible": False,
        "non_allow_boundary_count": boundary_summary["non_allow_boundary_count"],
        "raw_base_mismatch_count": raw_comparison["mismatch_count"],
        "scout_anchor_ids": split_payload_body["scout_anchor_ids"],
        "feature_context_before_role_allowed": True,
        "label_and_trade_end_must_stay_inside_role": True,
        "artifacts": {
            "dataset_receipt": {"path": rel(dataset_path), "sha256": sha256_file(dataset_path)},
            "split_set": {"path": rel(split_path), "sha256": sha256_file(split_path)},
        },
        "supersedes": {
            "materials": ["V2MAT000009", "V2MAT000010"],
            "evidence": "V2E000003",
            "validation_receipt": "V2VR000004",
        },
        "outcome": "data_identity_corrected",
        "claim_ceiling": "none",
    }
    _write_json(work_dir / "receipt.json", receipt)
    return records, receipt
