"""SC0005 SR0001 proxy for post-C0022 negative-memory synthesis."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.proxies.common import base


WORK_UNIT_ID = "SC0005"
RUN_ID = "SR0001"
WORK_UNIT_DIR = PROJECT_ROOT / "campaigns" / "SC0005_post_c0022_negative_memory_synthesis"
RUN_DIR = WORK_UNIT_DIR / "runs" / RUN_ID
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "sc0005_sr0001_proxy_trades.csv"
SUMMARY_ARTIFACT_PATH = RUN_DIR / "artifacts" / "sc0005_sr0001_negative_memory_synthesis_summary.json"
RUN_MANIFEST_PATH = RUN_DIR / "run_manifest.json"
GATE_REPORT_PATH = RUN_DIR / "gate_report.json"
ARTIFACT_LINEAGE_PATH = RUN_DIR / "artifact_lineage.json"
SYNTHESIS_PATH = WORK_UNIT_DIR / "synthesis.yaml"
SYNTHESIS_QUEUE_PATH = WORK_UNIT_DIR / "synthesis_queue.yaml"
CLAIM_STATE_PATH = PROJECT_ROOT / "registries" / "claim_state.yaml"
REENTRY_PATH = PROJECT_ROOT / "registries" / "reentry.yaml"
DECISION_CURSOR_PATH = PROJECT_ROOT / "registries" / "decision_cursor.yaml"

BASE_FRAME = base.BASE_FRAME
ROLLING_WINDOWS = base.ROLLING_WINDOWS
TIME_FORMAT = base.TIME_FORMAT
SplitWindow = base.SplitWindow
Trade = base.Trade
load_bars = base.load_bars
load_windows = base.load_windows

MODEL_FAMILY = "fold_local_post_c0022_negative_memory_conflict_synthesis"
LABEL_SHAPE = "source_schedule_score_conflict_without_source_pnl_selection"
SELECTION_RULE = "top_fold_local_negative_memory_conflict_candidates_per_active_day"
CLUSTER_SPACING_BARS = 3
BASE_SCORE_WEIGHT = 0.72
SAME_FAILURE_CLUSTER_PENALTY = 0.22
OPPOSITE_FAILURE_CONFLICT_CREDIT = 0.10
SOURCE_DIVERSITY_CREDIT = 0.04
SPREAD_PRESSURE_PENALTY_WEIGHT = 0.10

SOURCE_INGREDIENTS = (
    (
        "C0013",
        "c0013_ig001_path_resilience_recovery_negative_memory",
        "campaigns/C0013_path_resilience_recovery_discovery/runs/R0001/artifacts/c0013_r0001_proxy_trades.csv",
    ),
    (
        "C0014",
        "c0014_ig001_interday_range_handoff_negative_memory",
        "campaigns/C0014_interday_range_handoff_discovery/runs/R0001/artifacts/c0014_r0001_proxy_trades.csv",
    ),
    (
        "C0015",
        "c0015_ig001_liquidity_vacuum_rebound_negative_memory",
        "campaigns/C0015_liquidity_vacuum_rebound_discovery/runs/R0001/artifacts/c0015_r0001_proxy_trades.csv",
    ),
    (
        "C0016",
        "c0016_ig001_intraday_directional_imbalance_negative_memory",
        "campaigns/C0016_intraday_directional_imbalance_discovery/runs/R0001/artifacts/c0016_r0001_proxy_trades.csv",
    ),
    (
        "C0017",
        "c0017_ig001_round_level_magnet_rejection_negative_memory",
        "campaigns/C0017_round_level_magnet_rejection_discovery/runs/R0001/artifacts/c0017_r0001_proxy_trades.csv",
    ),
    (
        "C0018",
        "c0018_ig001_micro_gap_absorption_negative_memory",
        "campaigns/C0018_micro_gap_absorption_discovery/runs/R0001/artifacts/c0018_r0001_proxy_trades.csv",
    ),
    (
        "C0019",
        "c0019_ig001_bar_quality_asymmetry_negative_memory",
        "campaigns/C0019_bar_quality_asymmetry_discovery/runs/R0001/artifacts/c0019_r0001_proxy_trades.csv",
    ),
    (
        "C0020",
        "c0020_ig001_excursion_decay_memory_negative_memory",
        "campaigns/C0020_excursion_decay_memory_discovery/runs/R0001/artifacts/c0020_r0001_proxy_trades.csv",
    ),
    (
        "C0021",
        "c0021_ig001_daily_profile_energy_balance_negative_memory",
        "campaigns/C0021_daily_profile_energy_balance_discovery/runs/R0001/artifacts/c0021_r0001_proxy_trades.csv",
    ),
    (
        "C0022",
        "c0022_ig001_volatility_term_structure_negative_memory",
        "campaigns/C0022_volatility_term_structure_discovery/runs/R0001/artifacts/c0022_r0001_proxy_trades.csv",
    ),
)
SOURCE_INGREDIENT_IDS = tuple(row[1] for row in SOURCE_INGREDIENTS)
SCORE_COMPONENT_NAMES = (
    "source_schedule_score_z",
    "same_direction_failed_source_cluster_penalty",
    "opposite_direction_failed_source_conflict_credit",
    "source_diversity_credit",
    "spread_pressure_penalty",
)


@dataclass(frozen=True)
class SourceCandidate:
    source_id: str
    ingredient_id: str
    artifact_path: str
    fold_id: str
    signal_index: int
    entry_time: datetime
    direction: int
    source_score: float
    source_score_z: float
    spread_points: float


def run_sc0005_sr0001_proxy(write: bool = True) -> dict[str, object]:
    result = build_proxy_run_result()
    payload = build_proxy_payload(
        result.trades,
        result.windows,
        result.fold_models,
        result.state_distributions,
        result.candidates_by_fold,
    )
    if write:
        write_proxy_evidence(payload, result.trades)
    return payload


def load_proxy_trades() -> list[base.Trade]:
    if TRADE_ARTIFACT_PATH.exists():
        return read_trade_artifact(TRADE_ARTIFACT_PATH)
    return build_proxy_run_result().trades


def read_trade_artifact(path: Path) -> list[base.Trade]:
    trades: list[base.Trade] = []
    with path.open("r", encoding="ascii", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            trades.append(
                base.Trade(
                    fold_id=row["fold_id"],
                    signal_index=int(row["signal_index"]),
                    entry_time=datetime.strptime(row["entry_time"], TIME_FORMAT),
                    exit_time=datetime.strptime(row["exit_time"], TIME_FORMAT),
                    direction=int(row["direction"]),
                    score=float(row["score"]),
                    state_key=row["state_key"],
                    entry_price=float(row["entry_price"]),
                    exit_price=float(row["exit_price"]),
                    stop_price=float(row["stop_price"]),
                    target_price=float(row["target_price"]),
                    pnl_points=float(row["pnl_points"]),
                    bars_held=int(row["bars_held"]),
                    exit_reason=row["exit_reason"],
                    mfe_points=float(row["mfe_points"]),
                    mae_points=float(row["mae_points"]),
                    spread_points=float(row["spread_points"]),
                )
            )
    return trades


def build_proxy_run_result() -> base.ProxyRunResult:
    bars = base.load_bars(BASE_FRAME)
    windows = base.load_windows(ROLLING_WINDOWS)
    ranges = [bar.high - bar.low for bar in bars]
    range_average = base.previous_rolling_average(ranges, base.LOOKBACK_RANGE_BARS)
    source_candidates = load_source_candidates()
    grouped = group_by_fold(source_candidates)
    trades: list[base.Trade] = []
    fold_models: list[dict[str, object]] = []
    state_distributions: dict[str, dict[str, float | int | None]] = {}
    candidates_by_fold: dict[str, dict[str, int]] = {}

    for fold_id in sorted(fold_id for fold_id, split in windows.items() if {"train_is", "test_oos"} <= set(split)):
        split = windows[fold_id]
        fold_sources = grouped.get(fold_id, [])
        synthesis_candidates = synthesize_fold_candidates(fold_sources)
        selected = base.select_daily_candidates(synthesis_candidates)
        fold_trades = base.simulate_trades(bars, range_average, selected, split["test_oos"])
        trades.extend(fold_trades)
        fold_models.append(fold_model_summary(fold_id, fold_sources, synthesis_candidates, selected))
        state_distributions[fold_id] = synthesis_distribution(fold_sources, synthesis_candidates, selected)
        candidates_by_fold[fold_id] = {
            "source_candidate_count": len(fold_sources),
            "synthesized_candidate_count": len(synthesis_candidates),
            "selected_candidate_count": len(selected),
            "eligible_candidate_count": sum(1 for candidate in synthesis_candidates if candidate.score is not None),
            "source_surface_count": len({candidate.source_id for candidate in fold_sources}),
            "selection_uses_source_pnl": 0,
        }

    return base.ProxyRunResult(
        trades=sorted(trades, key=lambda trade: (trade.entry_time, trade.fold_id, trade.signal_index)),
        windows=windows,
        fold_models=fold_models,
        state_distributions=state_distributions,
        candidates_by_fold=candidates_by_fold,
    )


def load_source_candidates() -> list[SourceCandidate]:
    raw_rows: list[dict[str, object]] = []
    scores_by_source_fold: dict[tuple[str, str], list[float]] = defaultdict(list)
    for source_id, ingredient_id, rel_path in SOURCE_INGREDIENTS:
        path = PROJECT_ROOT / rel_path
        with path.open("r", encoding="ascii", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                score = float(row["score"])
                fold_id = row["fold_id"]
                scores_by_source_fold[(source_id, fold_id)].append(score)
                raw_rows.append(
                    {
                        "source_id": source_id,
                        "ingredient_id": ingredient_id,
                        "artifact_path": rel_path,
                        "fold_id": fold_id,
                        "signal_index": int(row["signal_index"]),
                        "entry_time": datetime.strptime(row["entry_time"], TIME_FORMAT),
                        "direction": int(row["direction"]),
                        "source_score": score,
                        "spread_points": float(row["spread_points"]),
                    }
                )
    stats: dict[tuple[str, str], tuple[float, float]] = {}
    for key, values in scores_by_source_fold.items():
        mean_value = sum(values) / len(values) if values else 0.0
        variance = sum((value - mean_value) ** 2 for value in values) / len(values) if values else 0.0
        std_value = math.sqrt(variance)
        stats[key] = (mean_value, std_value if std_value > 1e-12 else 1.0)
    candidates: list[SourceCandidate] = []
    for row in raw_rows:
        key = (str(row["source_id"]), str(row["fold_id"]))
        mean_value, std_value = stats[key]
        source_score = float(row["source_score"])
        candidates.append(
            SourceCandidate(
                source_id=str(row["source_id"]),
                ingredient_id=str(row["ingredient_id"]),
                artifact_path=str(row["artifact_path"]),
                fold_id=str(row["fold_id"]),
                signal_index=int(row["signal_index"]),
                entry_time=row["entry_time"],  # type: ignore[arg-type]
                direction=int(row["direction"]),
                source_score=source_score,
                source_score_z=(source_score - mean_value) / std_value,
                spread_points=float(row["spread_points"]),
            )
        )
    return candidates


def group_by_fold(candidates: list[SourceCandidate]) -> dict[str, list[SourceCandidate]]:
    grouped: dict[str, list[SourceCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.fold_id].append(candidate)
    return dict(grouped)


def synthesize_fold_candidates(source_candidates: list[SourceCandidate]) -> list[base.Candidate]:
    source_sets: dict[tuple[int, int], set[str]] = defaultdict(set)
    for candidate in source_candidates:
        source_sets[(candidate.signal_index, candidate.direction)].add(candidate.source_id)

    synthesized: list[base.Candidate] = []
    for candidate in source_candidates:
        same_sources: set[str] = set()
        opposite_sources: set[str] = set()
        for offset in range(-CLUSTER_SPACING_BARS, CLUSTER_SPACING_BARS + 1):
            index = candidate.signal_index + offset
            same_sources.update(source_sets.get((index, candidate.direction), set()))
            opposite_sources.update(source_sets.get((index, -candidate.direction), set()))
        same_count = len(same_sources)
        opposite_count = len(opposite_sources)
        source_diversity = len(same_sources | opposite_sources)
        spread_pressure = max(candidate.spread_points, 0.0)
        score = (
            BASE_SCORE_WEIGHT * candidate.source_score_z
            - SAME_FAILURE_CLUSTER_PENALTY * max(same_count - 1, 0)
            + OPPOSITE_FAILURE_CONFLICT_CREDIT * opposite_count
            + SOURCE_DIVERSITY_CREDIT * min(source_diversity, 4)
            - SPREAD_PRESSURE_PENALTY_WEIGHT * spread_pressure
        )
        side = "long" if candidate.direction > 0 else "short"
        synthesized.append(
            base.Candidate(
                fold_id=candidate.fold_id,
                index=candidate.signal_index,
                direction=candidate.direction,
                day=candidate.entry_time.strftime("%Y-%m-%d"),
                state_key=f"{side}|post_c0022_negative_memory|{candidate.source_id.lower()}|same_{same_count}|opp_{opposite_count}",
                features=(
                    candidate.source_score_z,
                    float(same_count),
                    float(opposite_count),
                    float(source_diversity),
                    spread_pressure,
                ),
                label=None,
                score=float(score),
            )
        )
    return synthesized


def fold_model_summary(
    fold_id: str,
    source_candidates: list[SourceCandidate],
    synthesized: list[base.Candidate],
    selected: list[base.Candidate],
) -> dict[str, object]:
    source_counts: dict[str, int] = defaultdict(int)
    selected_source_counts: dict[str, int] = defaultdict(int)
    for candidate in source_candidates:
        source_counts[candidate.source_id] += 1
    for candidate in selected:
        parts = candidate.state_key.split("|")
        if len(parts) >= 3:
            selected_source_counts[parts[2].upper()] += 1
    return {
        "fold_id": fold_id,
        "model_family": MODEL_FAMILY,
        "label_shape": LABEL_SHAPE,
        "score_component_names": list(SCORE_COMPONENT_NAMES),
        "source_ingredient_ids": list(SOURCE_INGREDIENT_IDS),
        "source_candidate_counts": dict(sorted(source_counts.items())),
        "selected_source_counts": dict(sorted(selected_source_counts.items())),
        "synthesized_candidate_count": len(synthesized),
        "selected_candidate_count": len(selected),
        "selection_uses_source_pnl": False,
        "model_selected": False,
    }


def synthesis_distribution(
    source_candidates: list[SourceCandidate],
    synthesized: list[base.Candidate],
    selected: list[base.Candidate],
) -> dict[str, float | int | None]:
    source_scores = [candidate.source_score_z for candidate in source_candidates]
    synthesis_scores = [candidate.score or 0.0 for candidate in synthesized if candidate.score is not None]
    selected_scores = [candidate.score or 0.0 for candidate in selected]
    same_counts = [candidate.features[1] for candidate in synthesized]
    opposite_counts = [candidate.features[2] for candidate in synthesized]
    return {
        "source_candidate_count": len(source_candidates),
        "synthesized_candidate_count": len(synthesized),
        "selected_count": len(selected),
        "source_score_z_p50": base.rounded(base.percentile(source_scores, 0.50)),
        "synthesis_score_p10": base.rounded(base.percentile(synthesis_scores, 0.10)),
        "synthesis_score_p50": base.rounded(base.percentile(synthesis_scores, 0.50)),
        "synthesis_score_p90": base.rounded(base.percentile(synthesis_scores, 0.90)),
        "selected_score_min": base.rounded(min(selected_scores)) if selected_scores else None,
        "selected_score_max": base.rounded(max(selected_scores)) if selected_scores else None,
        "same_failed_source_count_p50": base.rounded(base.percentile(same_counts, 0.50)),
        "opposite_failed_source_count_p50": base.rounded(base.percentile(opposite_counts, 0.50)),
    }


def build_proxy_payload(
    trades: list[base.Trade],
    windows: dict[str, dict[str, base.SplitWindow]],
    fold_models: list[dict[str, object]],
    state_distributions: dict[str, dict[str, float | int | None]],
    candidates_by_fold: dict[str, dict[str, int]],
) -> dict[str, object]:
    payload = replace_base_markers(
        base.build_proxy_payload(trades, windows, fold_models, state_distributions, candidates_by_fold)
    )
    payload["campaign_id"] = None
    payload["work_unit_id"] = WORK_UNIT_ID
    payload["synthesis_id_when_applicable"] = WORK_UNIT_ID
    payload["run_id"] = RUN_ID
    payload["proxy_id"] = "PX-SC0005-SR0001"
    payload["proxy_engine"] = "axiom_rift.proxies.sc0005_sr0001_post_c0022_negative_memory_synthesis"
    payload["proxy_config_path"] = "campaigns/SC0005_post_c0022_negative_memory_synthesis/runs/SR0001/run_manifest.json"
    payload["split_policy"] = "rolling_window_test_oos_only_with_source_schedule_score_conflict_synthesis"
    payload["proxy_artifact_paths"] = [
        "campaigns/SC0005_post_c0022_negative_memory_synthesis/runs/SR0001/kpi/proxy.json",
        "campaigns/SC0005_post_c0022_negative_memory_synthesis/runs/SR0001/artifacts/sc0005_sr0001_proxy_trades.csv",
        "campaigns/SC0005_post_c0022_negative_memory_synthesis/runs/SR0001/artifacts/sc0005_sr0001_negative_memory_synthesis_summary.json",
    ]
    payload["proxy_config"] = proxy_config()
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    profiles.pop("state_archetype_profile", None)  # type: ignore[union-attr]
    profiles["negative_memory_synthesis_profile"] = {  # type: ignore[index]
        "applies": True,
        "fields": {
            "model_family": MODEL_FAMILY,
            "state_model": MODEL_FAMILY,
            "label_shape": LABEL_SHAPE,
            "source_ingredient_ids": list(SOURCE_INGREDIENT_IDS),
            "source_trade_artifacts": [item[2] for item in SOURCE_INGREDIENTS],
            "score_component_names": list(SCORE_COMPONENT_NAMES),
            "selection_rule": SELECTION_RULE,
            "cluster_spacing_bars": CLUSTER_SPACING_BARS,
            "base_score_weight": BASE_SCORE_WEIGHT,
            "same_failure_cluster_penalty": SAME_FAILURE_CLUSTER_PENALTY,
            "opposite_failure_conflict_credit": OPPOSITE_FAILURE_CONFLICT_CREDIT,
            "source_diversity_credit": SOURCE_DIVERSITY_CREDIT,
            "spread_pressure_penalty_weight": SPREAD_PRESSURE_PENALTY_WEIGHT,
            "source_pnl_used_for_selection": False,
            "fold_models": fold_models,
            "state_distributions": state_distributions,
            "candidates_by_fold": candidates_by_fold,
            "model_selected": False,
            "feature_set_selected": False,
            "label_selected": False,
            "trade_logic_selected": False,
        },
    }
    profiles["mt5_pairing_profile"] = {  # type: ignore[index]
        "applies": True,
        "fields": {
            "mt5_logic_parity_required_next": True,
            "mt5_tick_required_after_logic_parity": True,
            "fold_isolated_mt5_closeout_required": True,
            "proxy_result_may_close_run": False,
            "proxy_is_screening_gate_for_mt5": False,
            "weak_proxy_may_skip_mt5": False,
            "next_action": "produce_sc0005_sr0001_mt5_logic_parity_evidence",
        },
    }
    return payload


def proxy_config() -> dict[str, object]:
    config = dict(base.proxy_config())
    config.update(
        {
            "model_family": MODEL_FAMILY,
            "label_shape": LABEL_SHAPE,
            "selection_rule": SELECTION_RULE,
            "score_component_names": list(SCORE_COMPONENT_NAMES),
            "source_ingredient_ids": list(SOURCE_INGREDIENT_IDS),
            "source_trade_artifacts": [item[2] for item in SOURCE_INGREDIENTS],
            "source_pnl_used_for_selection": False,
            "weights": {
                "base_score": BASE_SCORE_WEIGHT,
                "same_failure_cluster_penalty": SAME_FAILURE_CLUSTER_PENALTY,
                "opposite_failure_conflict_credit": OPPOSITE_FAILURE_CONFLICT_CREDIT,
                "source_diversity_credit": SOURCE_DIVERSITY_CREDIT,
                "spread_pressure_penalty": SPREAD_PRESSURE_PENALTY_WEIGHT,
            },
            "variant_boundary": "post_c0022_negative_memory_conflict_synthesis_not_c0022_threshold_score_stop_target_hold_activity_spread_session_or_retry_nudge",
            "fixed_lot_policy": "early_discovery_fixed_lot_no_equity_percent_sizing_rescue",
        }
    )
    return config


def write_proxy_evidence(payload: dict[str, object], trades: list[base.Trade]) -> None:
    RUN_DIR.joinpath("artifacts").mkdir(parents=True, exist_ok=True)
    RUN_DIR.joinpath("kpi").mkdir(parents=True, exist_ok=True)
    base.write_trade_artifact(trades, TRADE_ARTIFACT_PATH)
    write_summary_artifact(payload, SUMMARY_ARTIFACT_PATH)
    PROXY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    trade_hash = base.sha256_file(TRADE_ARTIFACT_PATH)
    summary_hash = base.sha256_file(SUMMARY_ARTIFACT_PATH)
    update_proxy_hashes(trade_hash, summary_hash)
    proxy_hash = base.sha256_file(PROXY_PATH)
    update_artifact_lineage(proxy_hash, trade_hash, summary_hash)
    update_run_manifest_status()
    update_gate_report()
    update_synthesis_status()
    update_synthesis_queue_after_proxy()
    update_reentry_after_proxy()
    update_claim_state_after_proxy(payload)
    update_decision_cursor_after_proxy(payload)


def write_summary_artifact(payload: dict[str, object], path: Path) -> None:
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    summary = {
        "schema": "axiom_rift_post_c0022_negative_memory_synthesis_summary_v1",
        "template": False,
        "work_unit_id": WORK_UNIT_ID,
        "synthesis_id": WORK_UNIT_ID,
        "run_id": RUN_ID,
        "created_at_utc": payload["created_at_utc"],
        "source_ingredient_ids": list(SOURCE_INGREDIENT_IDS),
        "proxy_config": payload["proxy_config"],
        "negative_memory_synthesis_profile": profiles["negative_memory_synthesis_profile"]["fields"],  # type: ignore[index]
        "claim_boundary": payload["claim_boundary"],
    }
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_proxy_hashes(trade_hash: str, summary_hash: str) -> None:
    data = json.loads(PROXY_PATH.read_text(encoding="ascii"))
    data["proxy_artifact_hashes"] = [trade_hash, summary_hash]
    PROXY_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_artifact_lineage(proxy_hash: str, trade_hash: str, summary_hash: str) -> None:
    data = json.loads(ARTIFACT_LINEAGE_PATH.read_text(encoding="ascii"))
    records = [
        record
        for record in data.get("artifact_records", [])
        if record.get("artifact_role")
        not in {"proxy_kpi", "proxy_trade_artifact", "negative_memory_synthesis_summary_artifact"}
    ]
    records.extend(
        [
            artifact_record(
                "A-SC0005-SR0001-PROXY-KPI",
                "proxy_kpi",
                "json",
                "campaigns/SC0005_post_c0022_negative_memory_synthesis/runs/SR0001/kpi/proxy.json",
                proxy_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/SC0005_post_c0022_negative_memory_synthesis/ingredient_refs.yaml",
                    "campaigns/SC0005_post_c0022_negative_memory_synthesis/synthesis_queue.yaml",
                    "campaigns/SC0005_post_c0022_negative_memory_synthesis/runs/SR0001/run_manifest.json",
                ],
            ),
            artifact_record(
                "A-SC0005-SR0001-PROXY-TRADES",
                "proxy_trade_artifact",
                "csv",
                "campaigns/SC0005_post_c0022_negative_memory_synthesis/runs/SR0001/artifacts/sc0005_sr0001_proxy_trades.csv",
                trade_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/SC0005_post_c0022_negative_memory_synthesis/runs/SR0001/kpi/proxy.json",
                ],
            ),
            artifact_record(
                "A-SC0005-SR0001-NEGATIVE-MEMORY-SYNTHESIS-SUMMARY",
                "negative_memory_synthesis_summary_artifact",
                "json",
                "campaigns/SC0005_post_c0022_negative_memory_synthesis/runs/SR0001/artifacts/sc0005_sr0001_negative_memory_synthesis_summary.json",
                summary_hash,
                ["campaigns/SC0005_post_c0022_negative_memory_synthesis/runs/SR0001/kpi/proxy.json"],
            ),
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_sc0005_sr0001_mt5_logic_parity_evidence",
        }
    ]
    ARTIFACT_LINEAGE_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def artifact_record(
    artifact_id: str,
    role: str,
    artifact_type: str,
    path: str,
    digest: str,
    source_inputs: list[str],
) -> dict[str, object]:
    return {
        "artifact_id": artifact_id,
        "artifact_role": role,
        "artifact_type": artifact_type,
        "repo_relative_path": path,
        "sha256": digest,
        "produced_by": "axiom_rift.proxies.sc0005_sr0001_post_c0022_negative_memory_synthesis",
        "source_inputs": source_inputs,
        "linked_kpi_family": "proxy",
        "mutable": False,
        "claim_authority": False,
    }


def update_run_manifest_status() -> None:
    data = json.loads(RUN_MANIFEST_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_ready"
    data["gate_status"] = "proxy_recorded_pending_mt5"
    evidence = data.setdefault("evidence_paths", {})
    evidence["proxy_trade_artifact"] = "artifacts/sc0005_sr0001_proxy_trades.csv"
    evidence["negative_memory_synthesis_summary"] = "artifacts/sc0005_sr0001_negative_memory_synthesis_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["checks"]["proxy_kpi_path_recorded"] = True
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_sc0005_sr0001_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/sc0005_sr0001_proxy_trades.csv",
        "artifacts/sc0005_sr0001_negative_memory_synthesis_summary.json",
        "kpi/proxy.json",
    ):
        if path not in evidence_paths:
            evidence_paths.append(path)
    data["evidence_paths"] = evidence_paths
    data["deferred_with_reason"] = [
        {
            "field": "decision",
            "reason": "proxy evidence is recorded but MT5 and proxy-vs-MT5 evidence are still missing",
            "blocking_condition": "SR0001 cannot close until mandatory MT5 logic parity, MT5 tick, execution divergence, and fold-isolated evidence are recorded",
            "revisit_when": "produce_sc0005_sr0001_mt5_logic_parity_evidence",
        }
    ]
    GATE_REPORT_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_synthesis_status() -> None:
    data = yaml.safe_load(SYNTHESIS_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_attempts"
    run_index = data.setdefault("run_index", {})
    run_index["active_run"] = "runs/SR0001"
    opened = list(run_index.get("opened_runs") or [])
    if "runs/SR0001" not in opened:
        opened.append("runs/SR0001")
    run_index["opened_runs"] = opened
    next_candidate = run_index.setdefault("next_run_candidate", {})
    next_candidate["run_id"] = RUN_ID
    next_candidate["direction"] = "active_sc0005_sr0001_mt5_logic_parity"
    next_candidate["reason"] = "SR0001 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    SYNTHESIS_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_synthesis_queue_after_proxy() -> None:
    data = yaml.safe_load(SYNTHESIS_QUEUE_PATH.read_text(encoding="ascii"))
    for item in data.get("queue", []):
        if item.get("synthesis_run_id") == RUN_ID:
            item["status"] = "proxy_done"
            item["opened_at_utc"] = item.get("opened_at_utc") or utc_now()
            item["last_completed_step"] = "produce_sc0005_sr0001_proxy_evidence"
            item["next_action"] = "produce_sc0005_sr0001_mt5_logic_parity_evidence"
    SYNTHESIS_QUEUE_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_reentry_after_proxy() -> None:
    data = yaml.safe_load(REENTRY_PATH.read_text(encoding="ascii"))
    data.setdefault("project", {})["active_synthesis"] = "campaigns/SC0005_post_c0022_negative_memory_synthesis"
    next_work = data.setdefault("next_work", {})
    next_work["synthesis"] = "campaigns/SC0005_post_c0022_negative_memory_synthesis"
    completed = list(next_work.get("completed") or [])
    for item in (
        "open_sc0005_post_c0022_negative_memory_synthesis",
        "open_sc0005_sr0001_negative_memory_synthesis_run",
        "produce_sc0005_sr0001_proxy_evidence",
    ):
        if item not in completed:
            completed.append(item)
    next_action = "produce_sc0005_sr0001_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    data["active_synthesis"] = "campaigns/SC0005_post_c0022_negative_memory_synthesis"
    data["active_run"] = "campaigns/SC0005_post_c0022_negative_memory_synthesis/runs/SR0001"
    REENTRY_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["active_synthesis"] = "campaigns/SC0005_post_c0022_negative_memory_synthesis"
    data["active_run"] = "campaigns/SC0005_post_c0022_negative_memory_synthesis/runs/SR0001"
    data["latest_operation"] = {
        "id": "produce_sc0005_sr0001_proxy_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/SC0005_post_c0022_negative_memory_synthesis/runs/SR0001/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "active_synthesis": "campaigns/SC0005_post_c0022_negative_memory_synthesis",
        "active_run": "campaigns/SC0005_post_c0022_negative_memory_synthesis/runs/SR0001",
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_sc0005_sr0001_mt5_logic_parity_evidence",
        "claim_boundary": claim_boundary(),
    }
    CLAIM_STATE_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_decision_cursor_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(DECISION_CURSOR_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["canonical_source"] = "campaigns/SC0005_post_c0022_negative_memory_synthesis/runs/SR0001/kpi/proxy.json"
    data["canonical_status"] = "proxy_recorded_pending_mt5"
    data["current_decision"] = "produce_sc0005_sr0001_mt5_logic_parity_evidence"
    data["active_synthesis"] = "campaigns/SC0005_post_c0022_negative_memory_synthesis"
    data["active_run"] = "campaigns/SC0005_post_c0022_negative_memory_synthesis/runs/SR0001"
    data["next_required_action"] = "produce_sc0005_sr0001_mt5_logic_parity_evidence"
    current = data.setdefault("current_evidence_summary", {})
    current.update(
        {
            "source_campaign": None,
            "source_synthesis": "campaigns/SC0005_post_c0022_negative_memory_synthesis",
            "current_task": "produce_sc0005_sr0001_mt5_logic_parity_evidence",
            "active_run": "campaigns/SC0005_post_c0022_negative_memory_synthesis/runs/SR0001",
            "active_run_status": "proxy_recorded_pending_mt5",
            "evidence_status": "proxy_recorded_pending_mt5",
            "hypothesis_family": MODEL_FAMILY,
            "label_surface": LABEL_SHAPE,
            "feature_surface": "source_schedule_score_cluster_conflict_without_source_pnl_selection",
            "trade_logic_surface": "fixed_lot_dual_direction_post_c0022_negative_memory_conflict_schedule",
            "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
            "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
            "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
            "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
            "note": "SC0005 SR0001 proxy is recorded; MT5 paired validation is mandatory before judgment.",
        }
    )
    DECISION_CURSOR_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def replace_base_markers(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: replace_base_markers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_base_markers(item) for item in value]
    if isinstance(value, str):
        replacements = {
            "C0004 R0001": "SC0005 SR0001",
            "C0004": "SC0005",
            "R0001": "SR0001",
            "c0004_r0001_fold_local_state_archetype": "sc0005_sr0001_post_c0022_negative_memory_synthesis",
            "c0004_r0001": "sc0005_sr0001",
            "fold_local_state_archetype_discovery": "post_c0022_negative_memory_synthesis",
            "fold_local_state_archetype_membership": MODEL_FAMILY,
            "directional_target_before_stop_plus_path_quality": LABEL_SHAPE,
            "state_archetype_summary": "negative_memory_synthesis_summary",
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value
    return value


def claim_boundary() -> dict[str, bool]:
    return {
        "claim_authority": False,
        "selected": False,
        "label_selected": False,
        "feature_set_selected": False,
        "model_selected": False,
        "trade_logic_selected": False,
        "runtime_probe_completed": False,
        "economics_pass": False,
        "materialization_ready": False,
        "runtime_authority": False,
        "onnx_ready": False,
        "promotion_ready": False,
        "live_ready": False,
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    print(json.dumps(run_sc0005_sr0001_proxy(write=True), indent=2, sort_keys=True))
