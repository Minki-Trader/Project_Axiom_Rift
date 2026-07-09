"""Build the durable material batch for V2 research and reference runtime seams."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.v2.identity import sha256_payload
from axiom_rift.v2.jobs.scout import sha256_file
from axiom_rift.v2.operations import MaterialRecord


def rel(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT).as_posix()


def _new_origin(parity_boundary: str, rollback_boundary: str) -> dict[str, Any]:
    return {
        "origin": "v2_new",
        "source_path": None,
        "decision": "new",
        "deficiency": None,
        "parity_boundary": parity_boundary,
        "rollback_boundary": rollback_boundary,
    }


def _program_payload(
    *,
    canonical_path: str,
    content: dict[str, Any],
    producer_code_path: str,
    input_material_ids: list[str],
    availability_semantics: str,
    portability: str,
    parity_boundary: str,
) -> dict[str, Any]:
    producer = PROJECT_ROOT / producer_code_path
    return {
        "canonical_path": canonical_path,
        "content_sha256": sha256_payload(content),
        "schema_version": "axiom_rift_v2_executable_program_v1",
        "producer_code_path": producer_code_path,
        "producer_code_sha256": sha256_file(producer),
        "input_material_ids": input_material_ids,
        "availability_semantics": availability_semantics,
        "portability": portability,
        "legacy_origin": _new_origin(parity_boundary, "remove_material_and_repoint_hypothesis_before_execution"),
        "program": content,
        "claim_ceiling": "none",
    }


def build_bootstrap_material_records() -> tuple[MaterialRecord, ...]:
    hypothesis_path = PROJECT_ROOT / "campaigns/v2/V2G0001_v2_activation/hypotheses/V2H0001.yaml"
    feature_path = PROJECT_ROOT / "configs/v2/feature_programs/causal_bar_v1.yaml"
    fixture_receipt_path = PROJECT_ROOT / "campaigns/v2/V2G0001_v2_activation/evidence/V2FIX0001/receipt.json"
    hypothesis = yaml.safe_load(hypothesis_path.read_text(encoding="ascii"))
    feature_contract = yaml.safe_load(feature_path.read_text(encoding="ascii"))
    programs = hypothesis["executable_programs"]
    fixture_receipt = json.loads(fixture_receipt_path.read_text(encoding="ascii"))
    feature_payload = _program_payload(
        canonical_path=rel(feature_path),
        content=feature_contract,
        producer_code_path="src/axiom_rift/v2/features.py",
        input_material_ids=["V2MAT000011", "V2MAT000006", "V2MAT000007"],
        availability_semantics="completed_bar_at_decision_time",
        portability="python_float32_onnx_input_mql5",
        parity_boundary="feature_order_hash_and_fixture_numeric_tolerance",
    )
    feature_payload["python_implementation_sha256"] = sha256_file(PROJECT_ROOT / "src/axiom_rift/v2/features.py")
    feature_payload["mql5_implementation_sha256"] = sha256_file(
        PROJECT_ROOT / "src/axiom_rift/v2/mt5/include/AxiomV2Features.mqh"
    )
    label_payload = _program_payload(
        canonical_path=rel(hypothesis_path),
        content=dict(programs["label_program"]),
        producer_code_path="src/axiom_rift/v2/research/scout.py",
        input_material_ids=["V2MAT000011", "V2MAT000013"],
        availability_semantics="training_label_only_never_live_feature",
        portability="python_research_only",
        parity_boundary="entry_open_t_plus_1_exit_open_t_plus_7",
    )
    model_payload = _program_payload(
        canonical_path=rel(hypothesis_path),
        content={**dict(programs["model_program"]), **dict(programs["calibration_program"])},
        producer_code_path="src/axiom_rift/v2/research/scout.py",
        input_material_ids=["V2MAT000013", "V2MAT000014"],
        availability_semantics="train_fit_validation_calibration_only",
        portability="sklearn_ridge_to_linear_onnx",
        parity_boundary="float32_feature_vector_to_scalar_score",
    )
    selector_payload = _program_payload(
        canonical_path=rel(hypothesis_path),
        content=dict(programs["selector_program"]),
        producer_code_path="src/axiom_rift/v2/research/scout.py",
        input_material_ids=["V2MAT000015", "V2MAT000008"],
        availability_semantics="chronological_decision_time_only",
        portability="python_and_native_ea_decision_layer",
        parity_boundary="exact_direction_and_timestamp",
    )
    trade_payload = _program_payload(
        canonical_path=rel(hypothesis_path),
        content=dict(programs["trade_program"]),
        producer_code_path="src/axiom_rift/v2/research/scout.py",
        input_material_ids=["V2MAT000011", "V2MAT000008", "V2MAT000016"],
        availability_semantics="next_open_entry_fixed_six_bar_exit",
        portability="python_bid_ohlc_and_native_mt5",
        parity_boundary="entry_exit_direction_lifecycle",
    )
    model_path = PROJECT_ROOT / fixture_receipt["paths"]["model"]
    ea_source_path = PROJECT_ROOT / fixture_receipt["paths"]["ea_source"]
    ea_binary_path = PROJECT_ROOT / fixture_receipt["paths"]["ea_binary"]
    onnx_payload = {
        "canonical_path": rel(model_path),
        "content_sha256": sha256_file(model_path),
        "schema_version": "onnx_linear_reference_fixture_v1",
        "producer_code_path": "src/axiom_rift/v2/materialization/linear_onnx.py",
        "producer_code_sha256": sha256_file(PROJECT_ROOT / "src/axiom_rift/v2/materialization/linear_onnx.py"),
        "input_material_ids": ["V2MAT000013", "V2MAT000015"],
        "availability_semantics": "non_economic_fixture_only",
        "portability": "onnxruntime_and_mql5_native_onnx",
        "legacy_origin": _new_origin("fixture_score_tolerance_2e_5", "regenerate_reference_model"),
        "fixture_receipt_sha256": sha256_file(fixture_receipt_path),
        "claim_ceiling": "none",
    }
    ea_source_payload = {
        "canonical_path": rel(ea_source_path),
        "content_sha256": sha256_file(ea_source_path),
        "schema_version": "mql5_reference_ea_v2",
        "producer_code_path": rel(ea_source_path),
        "producer_code_sha256": sha256_file(ea_source_path),
        "input_material_ids": ["V2MAT000013", "V2MAT000016", "V2MAT000017", "V2MAT000018"],
        "availability_semantics": "closed_bar_then_next_open",
        "portability": "fpmarkets_us100_m5_mt5",
        "legacy_origin": _new_origin("native_online_signal_and_fixture_mode", "remove_AxiomV2ReferenceEA"),
        "thin_ea": True,
        "claim_ceiling": "none",
    }
    ea_binary_payload = {
        "canonical_path": rel(ea_binary_path),
        "content_sha256": sha256_file(ea_binary_path),
        "schema_version": "mql5_ex5_build_5833_reference_v1",
        "producer_code_path": "src/axiom_rift/v2/mt5/runner.py",
        "producer_code_sha256": sha256_file(PROJECT_ROOT / "src/axiom_rift/v2/mt5/runner.py"),
        "input_material_ids": ["V2MAT000018", "V2MAT000019"],
        "availability_semantics": "local_mt5_reference_fixture",
        "portability": "same_mt5_build_requires_recompile_elsewhere",
        "legacy_origin": _new_origin("compile_receipt_and_fixture_execution", "recompile_from_source"),
        "terminal_build": 5833,
        "claim_ceiling": "none",
    }
    return (
        MaterialRecord("V2MAT000013", "feature_dag", feature_payload),
        MaterialRecord("V2MAT000014", "label_program", label_payload),
        MaterialRecord("V2MAT000015", "model_program", model_payload),
        MaterialRecord("V2MAT000016", "selector", selector_payload),
        MaterialRecord("V2MAT000017", "trade_program", trade_payload),
        MaterialRecord("V2MAT000018", "onnx_model", onnx_payload),
        MaterialRecord("V2MAT000019", "ea_source", ea_source_payload),
        MaterialRecord("V2MAT000020", "ea_binary", ea_binary_payload),
    )
