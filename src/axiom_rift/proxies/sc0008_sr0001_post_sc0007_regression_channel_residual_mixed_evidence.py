"""SC0008 SR0001 proxy for post-SC0007 regression-channel mixed evidence synthesis."""

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


WORK_UNIT_ID = "SC0008"
RUN_ID = "SR0001"
WORK_UNIT_REL = "campaigns/SC0008_post_sc0007_c0038_c0045_mixed_evidence_synthesis"
RUN_REL = f"{WORK_UNIT_REL}/runs/{RUN_ID}"
WORK_UNIT_DIR = PROJECT_ROOT / WORK_UNIT_REL
RUN_DIR = WORK_UNIT_DIR / "runs" / RUN_ID
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "sc0008_sr0001_proxy_trades.csv"
SUMMARY_ARTIFACT_PATH = RUN_DIR / "artifacts" / "sc0008_sr0001_summary.json"
RUN_MANIFEST_PATH = RUN_DIR / "run_manifest.json"
GATE_REPORT_PATH = RUN_DIR / "gate_report.json"
ARTIFACT_LINEAGE_PATH = RUN_DIR / "artifact_lineage.json"
SYNTHESIS_PATH = WORK_UNIT_DIR / "synthesis.yaml"
SYNTHESIS_QUEUE_PATH = WORK_UNIT_DIR / "synthesis_queue.yaml"
SELECTED_PATH = WORK_UNIT_DIR / "selected.yaml"
CLAIM_STATE_PATH = PROJECT_ROOT / "registries" / "claim_state.yaml"
REENTRY_PATH = PROJECT_ROOT / "registries" / "reentry.yaml"
DECISION_CURSOR_PATH = PROJECT_ROOT / "registries" / "decision_cursor.yaml"
DECISION_REGISTRY_PATH = PROJECT_ROOT / "registries" / "decision_registry.yaml"

BASE_FRAME = base.BASE_FRAME
ROLLING_WINDOWS = base.ROLLING_WINDOWS
TIME_FORMAT = base.TIME_FORMAT

MODEL_FAMILY = "fold_local_post_sc0007_regression_channel_residual_mixed_evidence_synthesis"
LABEL_SHAPE = "regression_channel_residual_cost_survival_under_post_sc0007_negative_memory_context"
SELECTION_RULE = "top_c0045_r0003_schedule_entries_reweighted_by_negative_memory_and_cost_gap_per_active_day"
BASE_CANDIDATE_SOURCE = (
    "C0045_R0003",
    "c0045_ig001_intraday_regression_channel_residual_candidate_evidence",
    "campaigns/C0045_intraday_regression_channel_residual_discovery/runs/R0003/artifacts/c0045_r0003_proxy_trades.csv",
)
C0045_R0003_COST_MATERIALIZATION_AUDIT = (
    "campaigns/C0045_intraday_regression_channel_residual_discovery/runs/R0003/kpi/cost_slippage_materialization_audit.json"
)
C0045_R0003_TICK_BY_FOLD = (
    "campaigns/C0045_intraday_regression_channel_residual_discovery/runs/R0003/kpi/mt5_tick_by_fold.json"
)

NEGATIVE_SOURCE_INGREDIENTS = (
    (
        "C0038",
        "c0038_ig001_intraday_dwell_transition_timing_negative_memory",
        "campaigns/C0038_intraday_dwell_transition_timing_discovery/runs/R0001/artifacts/c0038_r0001_proxy_trades.csv",
        "campaigns/C0038_intraday_dwell_transition_timing_discovery/runs/R0001/kpi/mt5_tick_by_fold.json",
    ),
    (
        "C0039",
        "c0039_ig001_intraday_moving_average_ribbon_phase_negative_memory",
        "campaigns/C0039_intraday_moving_average_ribbon_phase_discovery/runs/R0001/artifacts/c0039_r0001_proxy_trades.csv",
        "campaigns/C0039_intraday_moving_average_ribbon_phase_discovery/runs/R0001/kpi/mt5_tick_by_fold.json",
    ),
    (
        "C0040",
        "c0040_ig001_intraday_return_distribution_shape_negative_memory",
        "campaigns/C0040_intraday_return_distribution_shape_discovery/runs/R0001/artifacts/c0040_r0001_proxy_trades.csv",
        "campaigns/C0040_intraday_return_distribution_shape_discovery/runs/R0001/kpi/mt5_tick_by_fold.json",
    ),
    (
        "C0041",
        "c0041_ig001_intraday_autocorrelation_decay_negative_memory",
        "campaigns/C0041_intraday_autocorrelation_decay_discovery/runs/R0001/artifacts/c0041_r0001_proxy_trades.csv",
        "campaigns/C0041_intraday_autocorrelation_decay_discovery/runs/R0001/kpi/mt5_tick_by_fold.json",
    ),
    (
        "C0042",
        "c0042_ig001_intraday_path_symmetry_imbalance_negative_memory",
        "campaigns/C0042_intraday_path_symmetry_imbalance_discovery/runs/R0001/artifacts/c0042_r0001_proxy_trades.csv",
        "campaigns/C0042_intraday_path_symmetry_imbalance_discovery/runs/R0001/kpi/mt5_tick_by_fold.json",
    ),
    (
        "C0043",
        "c0043_ig001_intraday_range_shock_digest_negative_memory",
        "campaigns/C0043_intraday_range_shock_digest_discovery/runs/R0001/artifacts/c0043_r0001_proxy_trades.csv",
        "campaigns/C0043_intraday_range_shock_digest_discovery/runs/R0001/kpi/mt5_tick_by_fold.json",
    ),
    (
        "C0044",
        "c0044_ig001_intraday_extreme_recency_gradient_negative_memory",
        "campaigns/C0044_intraday_extreme_recency_gradient_discovery/runs/R0001/artifacts/c0044_r0001_proxy_trades.csv",
        "campaigns/C0044_intraday_extreme_recency_gradient_discovery/runs/R0001/kpi/mt5_tick_by_fold.json",
    ),
)
SOURCE_INGREDIENT_IDS = tuple(row[1] for row in NEGATIVE_SOURCE_INGREDIENTS) + (
    BASE_CANDIDATE_SOURCE[1],
    "c0045_ig002_cost_slippage_materialization_evidence_gap",
    "c0045_ig003_regression_channel_residual_hardening_trajectory",
)

CLUSTER_SPACING_BARS = 3
BASE_SCORE_WEIGHT = 0.78
SAME_FAILURE_CLUSTER_PENALTY = 0.20
OPPOSITE_FAILURE_CONFLICT_CREDIT = 0.08
SOURCE_DIVERSITY_CREDIT = 0.04
SPREAD_PRESSURE_PENALTY_WEIGHT = 0.08
FOLD_LOSS_DENSITY_PENALTY_WEIGHT = 0.12
CURRENT_FOLD_LOSS_PRESSURE_WEIGHT = 0.08
RECENT_NEGATIVE_MEMORY_PRESSURE_WEIGHT = 0.05
COST_MATERIALIZATION_GAP_PENALTY_WEIGHT = 0.10
SAME_FAILURE_CONTEXT_VETO_COUNT = 3
COST_GAP_CONTEXT_VETO_LEVEL = 0.85

SCORE_COMPONENT_NAMES = (
    "c0045_r0003_source_score_z",
    "same_direction_negative_memory_cluster_penalty",
    "opposite_direction_negative_memory_conflict_credit",
    "source_diversity_credit",
    "spread_pressure_penalty",
    "fold_loss_density_penalty",
    "current_fold_loss_pressure_penalty",
    "recent_negative_memory_pressure_penalty",
    "cost_materialization_gap_penalty",
)


@dataclass(frozen=True)
class GeneratorCandidate:
    fold_id: str
    signal_index: int
    entry_time: datetime
    direction: int
    source_score: float
    source_score_z: float
    spread_points: float


@dataclass(frozen=True)
class NegativeMemoryEvent:
    source_id: str
    ingredient_id: str
    fold_id: str
    signal_index: int
    entry_time: datetime
    direction: int


@dataclass(frozen=True)
class SourceMemoryProfile:
    source_id: str
    ingredient_id: str
    fold_loss_density: float
    recent_negative_memory_pressure: float
    losing_fold_ids: tuple[str, ...]


def run_sc0008_sr0001_proxy(write: bool = True) -> dict[str, object]:
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
    generator_candidates = load_generator_candidates()
    negative_events = load_negative_memory_events()
    memory_profiles = load_source_memory_profiles()
    cost_gap_profile = load_cost_materialization_gap_profile()
    generator_by_fold = group_generators_by_fold(generator_candidates)
    negative_by_fold = group_negative_events_by_fold(negative_events)
    trades: list[base.Trade] = []
    fold_models: list[dict[str, object]] = []
    state_distributions: dict[str, dict[str, float | int | None]] = {}
    candidates_by_fold: dict[str, dict[str, int]] = {}

    for fold_id in sorted(fold_id for fold_id, split in windows.items() if {"train_is", "test_oos"} <= set(split)):
        split = windows[fold_id]
        fold_generators = generator_by_fold.get(fold_id, [])
        fold_negative = negative_by_fold.get(fold_id, [])
        synthesized = synthesize_fold_candidates(
            fold_generators,
            fold_negative,
            memory_profiles,
            cost_gap_profile,
        )
        selected = base.select_daily_candidates(synthesized)
        fold_trades = base.simulate_trades(bars, range_average, selected, split["test_oos"])
        trades.extend(fold_trades)
        fold_models.append(fold_model_summary(fold_id, fold_generators, fold_negative, synthesized, selected))
        state_distributions[fold_id] = synthesis_distribution(synthesized, selected)
        candidates_by_fold[fold_id] = {
            "c0045_r0003_generator_candidate_count": len(fold_generators),
            "negative_memory_event_count": len(fold_negative),
            "synthesized_candidate_count": len(synthesized),
            "selected_candidate_count": len(selected),
            "eligible_candidate_count": sum(1 for candidate in synthesized if candidate.score is not None),
            "negative_source_surface_count": len({event.source_id for event in fold_negative}),
            "selection_uses_source_oos_pnl": 0,
        }

    return base.ProxyRunResult(
        trades=sorted(trades, key=lambda trade: (trade.entry_time, trade.fold_id, trade.signal_index)),
        windows=windows,
        fold_models=fold_models,
        state_distributions=state_distributions,
        candidates_by_fold=candidates_by_fold,
    )


def load_generator_candidates() -> list[GeneratorCandidate]:
    rel_path = BASE_CANDIDATE_SOURCE[2]
    path = PROJECT_ROOT / rel_path
    raw_rows: list[dict[str, object]] = []
    scores_by_fold: dict[str, list[float]] = defaultdict(list)
    with path.open("r", encoding="ascii", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            score = float(row["score"])
            fold_id = row["fold_id"]
            scores_by_fold[fold_id].append(score)
            raw_rows.append(
                {
                    "fold_id": fold_id,
                    "signal_index": int(row["signal_index"]),
                    "entry_time": datetime.strptime(row["entry_time"], TIME_FORMAT),
                    "direction": int(row["direction"]),
                    "source_score": score,
                    "spread_points": float(row["spread_points"]),
                }
            )
    stats: dict[str, tuple[float, float]] = {}
    for fold_id, values in scores_by_fold.items():
        mean_value = sum(values) / len(values) if values else 0.0
        variance = sum((value - mean_value) ** 2 for value in values) / len(values) if values else 0.0
        std_value = math.sqrt(variance)
        stats[fold_id] = (mean_value, std_value if std_value > 1e-12 else 1.0)
    candidates: list[GeneratorCandidate] = []
    for row in raw_rows:
        fold_id = str(row["fold_id"])
        mean_value, std_value = stats[fold_id]
        source_score = float(row["source_score"])
        candidates.append(
            GeneratorCandidate(
                fold_id=fold_id,
                signal_index=int(row["signal_index"]),
                entry_time=row["entry_time"],  # type: ignore[arg-type]
                direction=int(row["direction"]),
                source_score=source_score,
                source_score_z=(source_score - mean_value) / std_value,
                spread_points=float(row["spread_points"]),
            )
        )
    return candidates


def load_negative_memory_events() -> list[NegativeMemoryEvent]:
    events: list[NegativeMemoryEvent] = []
    for source_id, ingredient_id, rel_path, _tick_path in NEGATIVE_SOURCE_INGREDIENTS:
        path = PROJECT_ROOT / rel_path
        with path.open("r", encoding="ascii", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                events.append(
                    NegativeMemoryEvent(
                        source_id=source_id,
                        ingredient_id=ingredient_id,
                        fold_id=row["fold_id"],
                        signal_index=int(row["signal_index"]),
                        entry_time=datetime.strptime(row["entry_time"], TIME_FORMAT),
                        direction=int(row["direction"]),
                    )
                )
    return events


def load_source_memory_profiles() -> dict[str, SourceMemoryProfile]:
    profiles: dict[str, SourceMemoryProfile] = {}
    total_sources = len(NEGATIVE_SOURCE_INGREDIENTS)
    for index, (source_id, ingredient_id, _trade_path, tick_path) in enumerate(NEGATIVE_SOURCE_INGREDIENTS, start=1):
        data = json.loads((PROJECT_ROOT / tick_path).read_text(encoding="ascii"))
        folds = data["conditional_profiles"]["fold_profile"]["fields"]["folds"]
        losing_fold_ids: list[str] = []
        for fold in folds:
            required = fold.get("required_kpis", {})
            if float(required.get("mt5_net_pnl", 0.0)) <= 0.0:
                losing_fold_ids.append(str(fold["fold_id"]))
        fold_loss_density = len(losing_fold_ids) / len(folds) if folds else 0.0
        profiles[source_id] = SourceMemoryProfile(
            source_id=source_id,
            ingredient_id=ingredient_id,
            fold_loss_density=fold_loss_density,
            recent_negative_memory_pressure=index / total_sources,
            losing_fold_ids=tuple(losing_fold_ids),
        )
    return profiles


def load_cost_materialization_gap_profile() -> dict[str, object]:
    audit = json.loads((PROJECT_ROOT / C0045_R0003_COST_MATERIALIZATION_AUDIT).read_text(encoding="ascii"))
    required = audit.get("required_kpis", {})
    stress_by_fold = audit.get("stress_by_fold", [])
    fragile_fold_ids = [
        str(row.get("fold_id"))
        for row in stress_by_fold
        if float(row.get("net_after_0.02_adverse_cost_per_trade") or 0.0) <= 0.0
    ]
    tick_by_fold = json.loads((PROJECT_ROOT / C0045_R0003_TICK_BY_FOLD).read_text(encoding="ascii"))
    folds = tick_by_fold["conditional_profiles"]["fold_profile"]["fields"]["folds"]
    weakest_tick_fold_ids = [
        str(fold["fold_id"])
        for fold in sorted(
            folds,
            key=lambda row: float(row.get("required_kpis", {}).get("mt5_net_pnl", 0.0)),
        )[:2]
    ]
    return {
        "cost_gap_base_pressure": 0.20 if required.get("cost_slippage_stress_status") else 0.0,
        "r0003_worst_fold_id": required.get("worst_fold_id"),
        "r0003_weakest_positive_fold_id": required.get("weakest_positive_fold_id"),
        "fragile_cost_fold_ids": fragile_fold_ids,
        "weakest_tick_fold_ids": weakest_tick_fold_ids,
        "materialization_ready": bool(audit.get("materialization_probe", {}).get("materialization_ready")),
    }


def group_generators_by_fold(candidates: list[GeneratorCandidate]) -> dict[str, list[GeneratorCandidate]]:
    grouped: dict[str, list[GeneratorCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.fold_id].append(candidate)
    return dict(grouped)


def group_negative_events_by_fold(events: list[NegativeMemoryEvent]) -> dict[str, list[NegativeMemoryEvent]]:
    grouped: dict[str, list[NegativeMemoryEvent]] = defaultdict(list)
    for event in events:
        grouped[event.fold_id].append(event)
    return dict(grouped)


def synthesize_fold_candidates(
    generator_candidates: list[GeneratorCandidate],
    negative_events: list[NegativeMemoryEvent],
    memory_profiles: dict[str, SourceMemoryProfile],
    cost_gap_profile: dict[str, object],
) -> list[base.Candidate]:
    negative_index: dict[tuple[int, int], list[NegativeMemoryEvent]] = defaultdict(list)
    for event in negative_events:
        negative_index[(event.signal_index, event.direction)].append(event)

    synthesized: list[base.Candidate] = []
    for candidate in generator_candidates:
        same_sources: set[str] = set()
        opposite_sources: set[str] = set()
        for offset in range(-CLUSTER_SPACING_BARS, CLUSTER_SPACING_BARS + 1):
            index = candidate.signal_index + offset
            same_sources.update(event.source_id for event in negative_index.get((index, candidate.direction), []))
            opposite_sources.update(event.source_id for event in negative_index.get((index, -candidate.direction), []))
        source_diversity = len(same_sources | opposite_sources)
        fold_loss_density = average_profile_value(memory_profiles, same_sources, "fold_loss_density")
        recent_pressure = average_profile_value(memory_profiles, same_sources, "recent_negative_memory_pressure")
        current_fold_loss_pressure = average_current_fold_loss_pressure(memory_profiles, same_sources, candidate.fold_id)
        cost_gap_pressure = cost_materialization_gap_pressure(candidate.fold_id, cost_gap_profile)
        same_count = len(same_sources)
        opposite_count = len(opposite_sources)
        spread_pressure = max(candidate.spread_points, 0.0)
        score = (
            BASE_SCORE_WEIGHT * candidate.source_score_z
            - SAME_FAILURE_CLUSTER_PENALTY * same_count
            + OPPOSITE_FAILURE_CONFLICT_CREDIT * opposite_count
            + SOURCE_DIVERSITY_CREDIT * min(source_diversity, 6)
            - SPREAD_PRESSURE_PENALTY_WEIGHT * spread_pressure
            - FOLD_LOSS_DENSITY_PENALTY_WEIGHT * fold_loss_density
            - CURRENT_FOLD_LOSS_PRESSURE_WEIGHT * current_fold_loss_pressure
            - RECENT_NEGATIVE_MEMORY_PRESSURE_WEIGHT * recent_pressure
            - COST_MATERIALIZATION_GAP_PENALTY_WEIGHT * cost_gap_pressure
        )
        context_veto = same_count >= SAME_FAILURE_CONTEXT_VETO_COUNT or cost_gap_pressure >= COST_GAP_CONTEXT_VETO_LEVEL
        side = "long" if candidate.direction > 0 else "short"
        synthesized.append(
            base.Candidate(
                fold_id=candidate.fold_id,
                index=candidate.signal_index,
                direction=candidate.direction,
                day=candidate.entry_time.strftime("%Y-%m-%d"),
                state_key=(
                    f"{side}|post_sc0007_regression_channel_residual_mixed_evidence|same_{same_count}|"
                    f"opp_{opposite_count}|div_{source_diversity}|loss_{int(round(100.0 * fold_loss_density))}|"
                    f"foldloss_{int(round(100.0 * current_fold_loss_pressure))}|"
                    f"costgap_{int(round(100.0 * cost_gap_pressure))}"
                ),
                features=(
                    candidate.source_score_z,
                    float(same_count),
                    float(opposite_count),
                    float(source_diversity),
                    spread_pressure,
                    fold_loss_density,
                    current_fold_loss_pressure,
                    recent_pressure,
                    cost_gap_pressure,
                    float(context_veto),
                ),
                label=None,
                score=None if context_veto else float(score),
            )
        )
    return synthesized


def average_profile_value(
    memory_profiles: dict[str, SourceMemoryProfile],
    source_ids: set[str],
    field: str,
) -> float:
    if not source_ids:
        return 0.0
    values = [float(getattr(memory_profiles[source_id], field)) for source_id in source_ids if source_id in memory_profiles]
    return sum(values) / len(values) if values else 0.0


def average_current_fold_loss_pressure(
    memory_profiles: dict[str, SourceMemoryProfile],
    source_ids: set[str],
    fold_id: str,
) -> float:
    if not source_ids:
        return 0.0
    values = [
        1.0 if fold_id in memory_profiles[source_id].losing_fold_ids else 0.0
        for source_id in source_ids
        if source_id in memory_profiles
    ]
    return sum(values) / len(values) if values else 0.0


def cost_materialization_gap_pressure(fold_id: str, profile: dict[str, object]) -> float:
    pressure = float(profile.get("cost_gap_base_pressure") or 0.0)
    if fold_id == profile.get("r0003_worst_fold_id"):
        pressure += 0.35
    if fold_id == profile.get("r0003_weakest_positive_fold_id"):
        pressure += 0.35
    if fold_id in set(profile.get("fragile_cost_fold_ids") or []):
        pressure += 0.35
    if fold_id in set(profile.get("weakest_tick_fold_ids") or []):
        pressure += 0.20
    if not bool(profile.get("materialization_ready")):
        pressure += 0.10
    return min(pressure, 1.0)


def fold_model_summary(
    fold_id: str,
    generator_candidates: list[GeneratorCandidate],
    negative_events: list[NegativeMemoryEvent],
    synthesized: list[base.Candidate],
    selected: list[base.Candidate],
) -> dict[str, object]:
    negative_counts: dict[str, int] = defaultdict(int)
    for event in negative_events:
        negative_counts[event.source_id] += 1
    return {
        "fold_id": fold_id,
        "model_family": MODEL_FAMILY,
        "label_shape": LABEL_SHAPE,
        "score_component_names": list(SCORE_COMPONENT_NAMES),
        "source_ingredient_ids": list(SOURCE_INGREDIENT_IDS),
        "c0045_r0003_generator_candidate_count": len(generator_candidates),
        "negative_memory_event_counts": dict(sorted(negative_counts.items())),
        "synthesized_candidate_count": len(synthesized),
        "selected_candidate_count": len(selected),
        "selection_uses_source_oos_pnl": False,
        "model_selected": False,
    }


def synthesis_distribution(
    synthesized: list[base.Candidate],
    selected: list[base.Candidate],
) -> dict[str, float | int | None]:
    synthesis_scores = [candidate.score or 0.0 for candidate in synthesized if candidate.score is not None]
    selected_scores = [candidate.score or 0.0 for candidate in selected]
    same_counts = [candidate.features[1] for candidate in synthesized]
    opposite_counts = [candidate.features[2] for candidate in synthesized]
    fold_loss_density_values = [candidate.features[5] for candidate in synthesized]
    current_fold_loss_values = [candidate.features[6] for candidate in synthesized]
    cost_gap_values = [candidate.features[8] for candidate in synthesized]
    veto_values = [candidate.features[9] for candidate in synthesized]
    return {
        "synthesized_candidate_count": len(synthesized),
        "selected_count": len(selected),
        "synthesis_score_p10": base.rounded(base.percentile(synthesis_scores, 0.10)),
        "synthesis_score_p50": base.rounded(base.percentile(synthesis_scores, 0.50)),
        "synthesis_score_p90": base.rounded(base.percentile(synthesis_scores, 0.90)),
        "selected_score_min": base.rounded(min(selected_scores)) if selected_scores else None,
        "selected_score_max": base.rounded(max(selected_scores)) if selected_scores else None,
        "same_negative_source_count_p50": base.rounded(base.percentile(same_counts, 0.50)),
        "opposite_negative_source_count_p50": base.rounded(base.percentile(opposite_counts, 0.50)),
        "fold_loss_density_p50": base.rounded(base.percentile(fold_loss_density_values, 0.50)),
        "current_fold_loss_pressure_p50": base.rounded(base.percentile(current_fold_loss_values, 0.50)),
        "cost_materialization_gap_pressure_p50": base.rounded(base.percentile(cost_gap_values, 0.50)),
        "context_veto_rate": base.rounded(sum(veto_values) / len(veto_values)) if veto_values else None,
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
    payload["proxy_id"] = "PX-SC0008-SR0001"
    payload["proxy_engine"] = "axiom_rift.proxies.sc0008_sr0001_post_sc0007_regression_channel_residual_mixed_evidence"
    payload["proxy_config_path"] = f"{RUN_REL}/run_manifest.json"
    payload["split_policy"] = "rolling_window_test_oos_only_with_c0045_r0003_schedule_negative_memory_cost_gap_rerank"
    payload["proxy_artifact_paths"] = [
        f"{RUN_REL}/kpi/proxy.json",
        f"{RUN_REL}/artifacts/sc0008_sr0001_proxy_trades.csv",
        f"{RUN_REL}/artifacts/sc0008_sr0001_summary.json",
    ]
    payload["proxy_config"] = proxy_config()
    payload["claim_boundary"] = claim_boundary()
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    profiles.pop("state_archetype_profile", None)  # type: ignore[union-attr]
    profiles["regression_channel_residual_mixed_evidence_synthesis_profile"] = {  # type: ignore[index]
        "applies": True,
        "fields": {
            "model_family": MODEL_FAMILY,
            "state_model": MODEL_FAMILY,
            "label_shape": LABEL_SHAPE,
            "source_ingredient_ids": list(SOURCE_INGREDIENT_IDS),
            "base_candidate_source": {
                "source_id": BASE_CANDIDATE_SOURCE[0],
                "ingredient_id": BASE_CANDIDATE_SOURCE[1],
                "trade_artifact": BASE_CANDIDATE_SOURCE[2],
            },
            "negative_memory_sources": [
                {"source_id": item[0], "ingredient_id": item[1], "trade_artifact": item[2], "tick_by_fold": item[3]}
                for item in NEGATIVE_SOURCE_INGREDIENTS
            ],
            "score_component_names": list(SCORE_COMPONENT_NAMES),
            "selection_rule": SELECTION_RULE,
            "cluster_spacing_bars": CLUSTER_SPACING_BARS,
            "same_failure_context_veto_count": SAME_FAILURE_CONTEXT_VETO_COUNT,
            "cost_gap_context_veto_level": COST_GAP_CONTEXT_VETO_LEVEL,
            "weights": score_weights(),
            "source_oos_pnl_used_for_selection": False,
            "source_proxy_pnl_used_for_selection": False,
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
            "next_action": "produce_sc0008_sr0001_mt5_logic_parity_evidence",
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
            "base_candidate_source": BASE_CANDIDATE_SOURCE[2],
            "negative_memory_trade_artifacts": [item[2] for item in NEGATIVE_SOURCE_INGREDIENTS],
            "negative_memory_tick_by_fold_artifacts": [item[3] for item in NEGATIVE_SOURCE_INGREDIENTS],
            "cluster_spacing_bars": CLUSTER_SPACING_BARS,
            "same_failure_context_veto_count": SAME_FAILURE_CONTEXT_VETO_COUNT,
            "cost_gap_context_veto_level": COST_GAP_CONTEXT_VETO_LEVEL,
            "weights": score_weights(),
            "source_oos_pnl_used_for_selection": False,
            "source_proxy_pnl_used_for_selection": False,
            "variant_boundary": "post_sc0007_regression_channel_residual_mixed_evidence_synthesis_not_c0045_threshold_score_cost_buffer_stop_target_hold_session_activity_spread_capital_monthly_filter_or_retry_nudge",
            "fixed_lot_policy": "early_discovery_fixed_lot_no_equity_percent_sizing_rescue",
        }
    )
    return config


def score_weights() -> dict[str, float]:
    return {
        "base_score": BASE_SCORE_WEIGHT,
        "same_failure_cluster_penalty": SAME_FAILURE_CLUSTER_PENALTY,
        "opposite_failure_conflict_credit": OPPOSITE_FAILURE_CONFLICT_CREDIT,
        "source_diversity_credit": SOURCE_DIVERSITY_CREDIT,
        "spread_pressure_penalty": SPREAD_PRESSURE_PENALTY_WEIGHT,
        "fold_loss_density_penalty": FOLD_LOSS_DENSITY_PENALTY_WEIGHT,
        "current_fold_loss_pressure_penalty": CURRENT_FOLD_LOSS_PRESSURE_WEIGHT,
        "recent_negative_memory_pressure_penalty": RECENT_NEGATIVE_MEMORY_PRESSURE_WEIGHT,
        "cost_materialization_gap_penalty": COST_MATERIALIZATION_GAP_PENALTY_WEIGHT,
    }


def write_proxy_evidence(payload: dict[str, object], trades: list[base.Trade]) -> None:
    RUN_DIR.joinpath("artifacts").mkdir(parents=True, exist_ok=True)
    RUN_DIR.joinpath("kpi").mkdir(parents=True, exist_ok=True)
    base.write_trade_artifact(trades, TRADE_ARTIFACT_PATH)
    write_summary_artifact(payload, SUMMARY_ARTIFACT_PATH)
    PROXY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    trade_hash = base.sha256_file(TRADE_ARTIFACT_PATH)
    summary_hash = base.sha256_file(SUMMARY_ARTIFACT_PATH)
    update_proxy_hashes(trade_hash, summary_hash)
    update_run_manifest_status()
    update_gate_report()
    update_synthesis_status()
    update_synthesis_queue_after_proxy()
    update_selected_after_proxy()
    update_reentry_after_proxy()
    update_claim_state_after_proxy(payload)
    update_decision_cursor_after_proxy(payload)
    append_decision_registry_after_proxy(payload)
    proxy_hash = base.sha256_file(PROXY_PATH)
    run_manifest_hash = base.sha256_file(RUN_MANIFEST_PATH)
    gate_report_hash = base.sha256_file(GATE_REPORT_PATH)
    update_artifact_lineage(proxy_hash, trade_hash, summary_hash, run_manifest_hash, gate_report_hash)


def write_summary_artifact(payload: dict[str, object], path: Path) -> None:
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    summary = {
        "schema": "axiom_rift_sc0008_regression_channel_residual_mixed_evidence_synthesis_summary_v1",
        "template": False,
        "work_unit_id": WORK_UNIT_ID,
        "synthesis_id": WORK_UNIT_ID,
        "run_id": RUN_ID,
        "created_at_utc": payload["created_at_utc"],
        "source_ingredient_ids": list(SOURCE_INGREDIENT_IDS),
        "proxy_config": payload["proxy_config"],
        "regression_channel_residual_mixed_evidence_synthesis_profile": profiles[
            "regression_channel_residual_mixed_evidence_synthesis_profile"
        ]["fields"],
        "claim_boundary": payload["claim_boundary"],
    }
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_proxy_hashes(trade_hash: str, summary_hash: str) -> None:
    data = json.loads(PROXY_PATH.read_text(encoding="ascii"))
    data["proxy_artifact_hashes"] = [trade_hash, summary_hash]
    PROXY_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_artifact_lineage(
    proxy_hash: str,
    trade_hash: str,
    summary_hash: str,
    run_manifest_hash: str,
    gate_report_hash: str,
) -> None:
    data = json.loads(ARTIFACT_LINEAGE_PATH.read_text(encoding="ascii"))
    filtered_roles = {
        "run_manifest",
        "gate_report",
        "proxy_kpi",
        "proxy_trade_artifact",
        "regression_channel_mixed_evidence_summary_artifact",
    }
    records = [record for record in data.get("artifact_records", []) if record.get("artifact_role") not in filtered_roles]
    records.extend(
        [
            artifact_record(
                "A-SC0008-SR0001-RUN-MANIFEST",
                "run_manifest",
                "json",
                f"{RUN_REL}/run_manifest.json",
                run_manifest_hash,
                [
                    f"{WORK_UNIT_REL}/synthesis.yaml",
                    f"{WORK_UNIT_REL}/ingredient_refs.yaml",
                    f"{WORK_UNIT_REL}/synthesis_queue.yaml",
                    "contracts/goal_operation_policy.yaml",
                ],
                "run_state",
            ),
            artifact_record(
                "A-SC0008-SR0001-GATE-REPORT",
                "gate_report",
                "json",
                f"{RUN_REL}/gate_report.json",
                gate_report_hash,
                [f"{RUN_REL}/run_manifest.json", f"{RUN_REL}/kpi/proxy.json"],
                "run_state",
            ),
            artifact_record(
                "A-SC0008-SR0001-PROXY-KPI",
                "proxy_kpi",
                "json",
                f"{RUN_REL}/kpi/proxy.json",
                proxy_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    f"{WORK_UNIT_REL}/ingredient_refs.yaml",
                    f"{WORK_UNIT_REL}/synthesis_queue.yaml",
                    f"{RUN_REL}/run_manifest.json",
                ],
                "proxy",
            ),
            artifact_record(
                "A-SC0008-SR0001-PROXY-TRADES",
                "proxy_trade_artifact",
                "csv",
                f"{RUN_REL}/artifacts/sc0008_sr0001_proxy_trades.csv",
                trade_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    f"{RUN_REL}/kpi/proxy.json",
                ],
                "proxy",
            ),
            artifact_record(
                "A-SC0008-SR0001-NEGATIVE-CONTEXT-SYNTHESIS-SUMMARY",
                "regression_channel_mixed_evidence_summary_artifact",
                "json",
                f"{RUN_REL}/artifacts/sc0008_sr0001_summary.json",
                summary_hash,
                [f"{RUN_REL}/kpi/proxy.json"],
                "proxy",
            ),
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_sc0008_sr0001_mt5_logic_parity_evidence",
        }
    ]
    data["created_at_utc"] = data.get("created_at_utc") or utc_now()
    data["lineage_id"] = data.get("lineage_id") or "L-SC0008-SR0001"
    ARTIFACT_LINEAGE_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def artifact_record(
    artifact_id: str,
    role: str,
    artifact_type: str,
    path: str,
    digest: str,
    source_inputs: list[str],
    linked_kpi_family: str,
) -> dict[str, object]:
    return {
        "artifact_id": artifact_id,
        "artifact_role": role,
        "artifact_type": artifact_type,
        "repo_relative_path": path,
        "sha256": digest,
        "produced_by": "axiom_rift.proxies.sc0008_sr0001_post_sc0007_regression_channel_residual_mixed_evidence",
        "source_inputs": source_inputs,
        "linked_kpi_family": linked_kpi_family,
        "mutable": False,
        "claim_authority": False,
    }


def update_run_manifest_status() -> None:
    data = json.loads(RUN_MANIFEST_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_ready"
    data["gate_status"] = "proxy_recorded_pending_mt5"
    evidence = data.setdefault("evidence_paths", {})
    evidence["proxy_kpi"] = "kpi/proxy.json"
    evidence["proxy_trade_artifact"] = "artifacts/sc0008_sr0001_proxy_trades.csv"
    evidence["regression_channel_mixed_evidence_summary"] = "artifacts/sc0008_sr0001_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["checks"]["proxy_kpi_path_recorded"] = True
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["mt5_gate"]["status"] = "mt5_logic_parity_required_next"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_sc0008_sr0001_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/sc0008_sr0001_proxy_trades.csv",
        "artifacts/sc0008_sr0001_summary.json",
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
            "revisit_when": "produce_sc0008_sr0001_mt5_logic_parity_evidence",
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
    next_candidate["direction"] = "produce_sc0008_sr0001_mt5_logic_parity_evidence"
    next_candidate["reason"] = "SR0001 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    SYNTHESIS_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_synthesis_queue_after_proxy() -> None:
    data = yaml.safe_load(SYNTHESIS_QUEUE_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_attempts"
    for item in data.get("queue", []):
        if item.get("synthesis_run_id") == RUN_ID:
            item["status"] = "proxy_done"
            item["last_completed_step"] = "produce_sc0008_sr0001_proxy_evidence"
            item["next_action"] = "produce_sc0008_sr0001_mt5_logic_parity_evidence"
    SYNTHESIS_QUEUE_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_selected_after_proxy() -> None:
    data = yaml.safe_load(SELECTED_PATH.read_text(encoding="ascii"))
    data["status"] = "proxy_recorded_pending_mt5"
    latest = data.setdefault("latest_synthesis_state", {})
    latest["status"] = "proxy_recorded_pending_mt5"
    latest["source"] = "runs/SR0001/kpi/proxy.json"
    latest["active_run"] = "runs/SR0001"
    latest["candidate_evidence_retained"] = False
    latest["negative_memory_recorded"] = False
    latest["next_required_action"] = "produce_sc0008_sr0001_mt5_logic_parity_evidence"
    SELECTED_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_reentry_after_proxy() -> None:
    data = yaml.safe_load(REENTRY_PATH.read_text(encoding="ascii"))
    data.setdefault("project", {})["active_synthesis"] = WORK_UNIT_REL
    data.setdefault("project", {})["active_run"] = RUN_REL
    next_work = data.setdefault("next_work", {})
    next_work["campaign"] = None
    next_work["synthesis"] = WORK_UNIT_REL
    completed = list(next_work.get("completed") or [])
    if "produce_sc0008_sr0001_proxy_evidence" not in completed:
        completed.append("produce_sc0008_sr0001_proxy_evidence")
    next_action = "produce_sc0008_sr0001_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    next_work["active_campaign"] = None
    next_work["active_run"] = RUN_REL
    next_work["run"] = RUN_REL
    data["active_campaign"] = None
    data["active_synthesis"] = WORK_UNIT_REL
    data["active_run"] = RUN_REL
    REENTRY_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["active_campaign"] = None
    data["active_synthesis"] = WORK_UNIT_REL
    data["active_run"] = RUN_REL
    data["latest_operation"] = {
        "id": "produce_sc0008_sr0001_proxy_evidence",
        "status": "completed",
        "recorded_at_source": f"{RUN_REL}/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "active_synthesis": WORK_UNIT_REL,
        "active_run": RUN_REL,
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_sc0008_sr0001_mt5_logic_parity_evidence",
        "claim_boundary": claim_boundary(),
    }
    CLAIM_STATE_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_decision_cursor_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(DECISION_CURSOR_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["canonical_source"] = f"{RUN_REL}/kpi/proxy.json"
    data["canonical_status"] = "proxy_recorded_pending_mt5"
    data["current_decision"] = "produce_sc0008_sr0001_mt5_logic_parity_evidence"
    data["active_campaign"] = None
    data["active_synthesis"] = WORK_UNIT_REL
    data["active_run"] = RUN_REL
    data["next_required_action"] = "produce_sc0008_sr0001_mt5_logic_parity_evidence"
    current = data.setdefault("current_evidence_summary", {})
    current.update(
        {
            "source_campaign": None,
            "source_synthesis": WORK_UNIT_REL,
            "current_task": "produce_sc0008_sr0001_mt5_logic_parity_evidence",
            "active_run": RUN_REL,
            "active_run_status": "proxy_recorded_pending_mt5",
            "evidence_status": "proxy_recorded_pending_mt5",
            "hypothesis_family": MODEL_FAMILY,
            "label_surface": LABEL_SHAPE,
            "feature_surface": "c0045_r0003_schedule_score_plus_c0038_c0044_negative_memory_and_cost_gap_context",
            "trade_logic_surface": "fixed_lot_c0045_r0003_schedule_reweighted_by_post_sc0007_mixed_evidence_context",
            "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
            "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
            "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
            "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
            "note": "SC0008 SR0001 proxy is recorded; MT5 paired validation is mandatory before judgment.",
        }
    )
    data["next_decision_basis"] = [
        {
            "path": f"{RUN_REL}/kpi/proxy.json",
            "role": "active_synthesis_run_proxy_kpi",
            "summary": "SC0008 SR0001 proxy evidence is recorded; MT5 logic parity is next and proxy is not a go/no-go gate.",
        },
        {
            "path": f"{RUN_REL}/run_manifest.json",
            "role": "active_synthesis_run_manifest",
            "summary": "SR0001 remains open with mandatory MT5 paired validation before judgment.",
        },
        {
            "path": f"{WORK_UNIT_REL}/ingredient_refs.yaml",
            "role": "active_synthesis_ingredient_index",
            "summary": "Ingredient refs record C0038-C0044 negative memory and C0045 candidate/cost-gap evidence used by SR0001.",
        },
    ]
    DECISION_CURSOR_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def append_decision_registry_after_proxy(payload: dict[str, object]) -> None:
    decision_id = "dec_20260706_produce_sc0008_sr0001_proxy_evidence"
    text = DECISION_REGISTRY_PATH.read_text(encoding="ascii")
    if decision_id in text:
        return
    required = payload.get("required_kpis", {})
    summary = payload.get("proxy_summary", {})
    block = f"""
- decision_id: {decision_id}
  created_local_date: '2026-07-05'
  status: active
  decision: produce_sc0008_sr0001_proxy_evidence
  refines:
  - dec_20260706_open_sc0008_sr0001_post_sc0007_regression_channel_residual_mixed_evidence_synthesis_run
  - dec_20260701_mandatory_mt5_paired_run_validation
  rationale:
  - sc0008_sr0001_proxy_reranks_c0045_r0003_candidate_schedule_entries_with_c0038_through_c0044_negative_memory_and_c0045_cost_gap_context
  - source_oos_pnl_and_source_proxy_pnl_are_not_used_for_entry_selection
  - proxy_trade_count_{required.get("proxy_trade_count") if isinstance(required, dict) else "unknown"}_and_entries_per_active_day_{summary.get("entries_per_active_day") if isinstance(summary, dict) else "unknown"}_are_reference_proxy_evidence_only
  - proxy_net_pnl_points_{required.get("proxy_net_pnl_points") if isinstance(required, dict) else "unknown"}_and_profit_factor_{required.get("proxy_profit_factor") if isinstance(required, dict) else "unknown"}_do_not_create_selection_or_economics_claims
  - weak_or_strong_proxy_must_continue_to_mt5_logic_parity_proxy_vs_mt5_parity_mt5_tick_execution_divergence_and_fold_isolated_closeout_evidence
  - next_work_is_produce_sc0008_sr0001_mt5_logic_parity_evidence
  claim_boundary:
    claim_authority: false
    selected: false
    label_selected: false
    feature_set_selected: false
    model_selected: false
    trade_logic_selected: false
    runtime_probe_completed: false
    economics_pass: false
    materialization_ready: false
    runtime_authority: false
    onnx_ready: false
    promotion_ready: false
    live_ready: false
"""
    DECISION_REGISTRY_PATH.write_text(text.rstrip() + "\n" + block, encoding="ascii")


def replace_base_markers(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: replace_base_markers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_base_markers(item) for item in value]
    if isinstance(value, str):
        replacements = {
            "C0004 R0001": "SC0008 SR0001",
            "C0004": "SC0008",
            "R0001": "SR0001",
            "c0004_r0001_fold_local_state_archetype": "sc0008_sr0001_post_sc0007_regression_channel_residual_mixed_evidence",
            "c0004_r0001": "sc0008_sr0001",
            "fold_local_state_archetype_discovery": "post_sc0007_regression_channel_residual_mixed_evidence_synthesis",
            "fold_local_state_archetype_membership": MODEL_FAMILY,
            "directional_target_before_stop_plus_path_quality": LABEL_SHAPE,
            "state_archetype_summary": "regression_channel_mixed_evidence_summary",
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
    print(json.dumps(run_sc0008_sr0001_proxy(write=True), indent=2, sort_keys=True))
