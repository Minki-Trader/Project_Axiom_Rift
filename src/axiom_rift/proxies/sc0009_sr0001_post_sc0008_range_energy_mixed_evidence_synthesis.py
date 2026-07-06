"""SC0009 SR0001 proxy for post-SC0008 mixed evidence synthesis."""

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


WORK_UNIT_ID = "SC0009"
RUN_ID = "SR0001"
WORK_UNIT_REL = "campaigns/SC0009_post_sc0008_c0046_c0048_mixed_evidence_synthesis"
RUN_REL = f"{WORK_UNIT_REL}/runs/{RUN_ID}"
WORK_UNIT_DIR = PROJECT_ROOT / WORK_UNIT_REL
RUN_DIR = WORK_UNIT_DIR / "runs" / RUN_ID
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "sc0009_sr0001_proxy_trades.csv"
SUMMARY_ARTIFACT_PATH = RUN_DIR / "artifacts" / "sc0009_sr0001_summary.json"
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

MODEL_FAMILY = "fold_local_post_sc0008_range_energy_mixed_evidence_synthesis"
LABEL_SHAPE = "candidate_source_agreement_cost_survival_under_c0046_c0048_negative_memory"
SELECTION_RULE = (
    "top_pooled_c0046_c0047_c0048_candidate_schedule_entries_reweighted_by_source_agreement_"
    "negative_memory_collision_fold_loss_density_and_execution_divergence_context"
)

CANDIDATE_SOURCE_INGREDIENTS = (
    (
        "C0046_R0001",
        "c0046_ig001_intraday_flow_convexity_release_candidate_evidence",
        "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0001/artifacts/c0046_r0001_proxy_trades.csv",
        "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0001/kpi/mt5_tick_by_fold.json",
        "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0001/kpi/execution_divergence_by_fold.json",
    ),
    (
        "C0047_R0001",
        "c0047_ig001_intraday_liquidity_void_reversion_candidate_evidence",
        "campaigns/C0047_intraday_liquidity_void_reversion_discovery/runs/R0001/artifacts/c0047_r0001_proxy_trades.csv",
        "campaigns/C0047_intraday_liquidity_void_reversion_discovery/runs/R0001/kpi/mt5_tick_by_fold.json",
        "campaigns/C0047_intraday_liquidity_void_reversion_discovery/runs/R0001/kpi/execution_divergence_by_fold.json",
    ),
    (
        "C0048_R0002",
        "c0048_ig001_intraday_range_energy_absorption_reversal_candidate_evidence",
        "campaigns/C0048_intraday_range_energy_absorption_discovery/runs/R0002/artifacts/c0048_r0002_proxy_trades.csv",
        "campaigns/C0048_intraday_range_energy_absorption_discovery/runs/R0002/kpi/mt5_tick_by_fold.json",
        "campaigns/C0048_intraday_range_energy_absorption_discovery/runs/R0002/kpi/execution_divergence_by_fold.json",
    ),
)

NEGATIVE_SOURCE_INGREDIENTS = (
    (
        "C0046_R0002",
        "c0046_ig002_cost_fragility_survival_negative_memory",
        "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0002/artifacts/c0046_r0002_proxy_trades.csv",
        "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0002/kpi/mt5_tick_by_fold.json",
        "campaigns/C0046_intraday_flow_convexity_release_discovery/runs/R0002/kpi/execution_divergence_by_fold.json",
    ),
    (
        "C0047_R0002",
        "c0047_ig002_rejection_continuation_negative_memory",
        "campaigns/C0047_intraday_liquidity_void_reversion_discovery/runs/R0002/artifacts/c0047_r0002_proxy_trades.csv",
        "campaigns/C0047_intraday_liquidity_void_reversion_discovery/runs/R0002/kpi/mt5_tick_by_fold.json",
        "campaigns/C0047_intraday_liquidity_void_reversion_discovery/runs/R0002/kpi/execution_divergence_by_fold.json",
    ),
    (
        "C0048_R0001",
        "c0048_ig002_intraday_range_energy_follow_through_negative_memory",
        "campaigns/C0048_intraday_range_energy_absorption_discovery/runs/R0001/artifacts/c0048_r0001_proxy_trades.csv",
        "campaigns/C0048_intraday_range_energy_absorption_discovery/runs/R0001/kpi/mt5_tick_by_fold.json",
        "campaigns/C0048_intraday_range_energy_absorption_discovery/runs/R0001/kpi/execution_divergence_by_fold.json",
    ),
)

SOURCE_INGREDIENT_IDS = tuple(row[1] for row in CANDIDATE_SOURCE_INGREDIENTS + NEGATIVE_SOURCE_INGREDIENTS) + (
    "c0046_ig003_execution_divergence_contrast",
    "c0047_ig003_execution_divergence_contrast",
    "c0048_ig003_execution_divergence_contrast",
)

CLUSTER_SPACING_BARS = 3
BASE_SCORE_WEIGHT = 0.64
SOURCE_AGREEMENT_CREDIT = 0.18
SOURCE_DIVERSITY_CREDIT = 0.04
SAME_NEGATIVE_COLLISION_PENALTY = 0.22
OPPOSITE_NEGATIVE_CONFLICT_CREDIT = 0.07
NEGATIVE_FOLD_LOSS_DENSITY_PENALTY = 0.12
CANDIDATE_FOLD_WEAKNESS_PENALTY = 0.08
EXECUTION_DIVERGENCE_PRESSURE_PENALTY = 0.08
SPREAD_PRESSURE_PENALTY = 0.07
SAME_NEGATIVE_CONTEXT_VETO_COUNT = 3
CANDIDATE_FOLD_WEAKNESS_VETO_LEVEL = 0.90

SCORE_COMPONENT_NAMES = (
    "candidate_source_score_z",
    "same_direction_candidate_source_agreement",
    "candidate_source_diversity",
    "same_direction_negative_memory_collision",
    "opposite_direction_negative_memory_conflict",
    "negative_fold_loss_density",
    "candidate_fold_weakness",
    "execution_divergence_pressure",
    "spread_pressure",
)


@dataclass(frozen=True)
class GeneratorCandidate:
    source_id: str
    ingredient_id: str
    fold_id: str
    signal_index: int
    entry_time: datetime
    direction: int
    source_score: float
    source_score_z: float
    spread_points: float


@dataclass(frozen=True)
class MemoryEvent:
    source_id: str
    ingredient_id: str
    fold_id: str
    signal_index: int
    entry_time: datetime
    direction: int


@dataclass(frozen=True)
class SourceEvidenceProfile:
    source_id: str
    ingredient_id: str
    fold_loss_density: float
    losing_fold_ids: tuple[str, ...]
    weakest_fold_ids: tuple[str, ...]
    tick_worse_fold_ids: tuple[str, ...]


def run_sc0009_sr0001_proxy(write: bool = True) -> dict[str, object]:
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
    generators = load_generator_candidates()
    negative_events = load_negative_memory_events()
    candidate_profiles = load_source_profiles(CANDIDATE_SOURCE_INGREDIENTS)
    negative_profiles = load_source_profiles(NEGATIVE_SOURCE_INGREDIENTS)
    generator_by_fold = group_generators_by_fold(generators)
    negative_by_fold = group_memory_events_by_fold(negative_events)
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
            candidate_profiles,
            negative_profiles,
        )
        selected = base.select_daily_candidates(synthesized)
        fold_trades = base.simulate_trades(bars, range_average, selected, split["test_oos"])
        trades.extend(fold_trades)
        fold_models.append(fold_model_summary(fold_id, fold_generators, fold_negative, synthesized, selected))
        state_distributions[fold_id] = synthesis_distribution(synthesized, selected)
        candidates_by_fold[fold_id] = {
            "generator_candidate_count": len(fold_generators),
            "negative_memory_event_count": len(fold_negative),
            "synthesized_candidate_count": len(synthesized),
            "selected_candidate_count": len(selected),
            "eligible_candidate_count": sum(1 for candidate in synthesized if candidate.score is not None),
            "candidate_source_count": len({candidate.source_id for candidate in fold_generators}),
            "negative_source_count": len({event.source_id for event in fold_negative}),
            "selection_uses_source_oos_pnl": 0,
            "selection_uses_source_proxy_pnl": 0,
        }

    return base.ProxyRunResult(
        trades=sorted(trades, key=lambda trade: (trade.entry_time, trade.fold_id, trade.signal_index)),
        windows=windows,
        fold_models=fold_models,
        state_distributions=state_distributions,
        candidates_by_fold=candidates_by_fold,
    )


def load_generator_candidates() -> list[GeneratorCandidate]:
    raw_rows: list[dict[str, object]] = []
    scores_by_key: dict[tuple[str, str], list[float]] = defaultdict(list)
    for source_id, ingredient_id, rel_path, _tick_path, _divergence_path in CANDIDATE_SOURCE_INGREDIENTS:
        with (PROJECT_ROOT / rel_path).open("r", encoding="ascii", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                fold_id = row["fold_id"]
                score = float(row["score"])
                scores_by_key[(source_id, fold_id)].append(score)
                raw_rows.append(
                    {
                        "source_id": source_id,
                        "ingredient_id": ingredient_id,
                        "fold_id": fold_id,
                        "signal_index": int(row["signal_index"]),
                        "entry_time": datetime.strptime(row["entry_time"], TIME_FORMAT),
                        "direction": int(row["direction"]),
                        "source_score": score,
                        "spread_points": float(row["spread_points"]),
                    }
                )
    stats: dict[tuple[str, str], tuple[float, float]] = {}
    for key, values in scores_by_key.items():
        mean_value = sum(values) / len(values) if values else 0.0
        variance = sum((value - mean_value) ** 2 for value in values) / len(values) if values else 0.0
        std_value = math.sqrt(variance)
        stats[key] = (mean_value, std_value if std_value > 1e-12 else 1.0)

    candidates: list[GeneratorCandidate] = []
    for row in raw_rows:
        source_id = str(row["source_id"])
        fold_id = str(row["fold_id"])
        mean_value, std_value = stats[(source_id, fold_id)]
        source_score = float(row["source_score"])
        candidates.append(
            GeneratorCandidate(
                source_id=source_id,
                ingredient_id=str(row["ingredient_id"]),
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


def load_negative_memory_events() -> list[MemoryEvent]:
    events: list[MemoryEvent] = []
    for source_id, ingredient_id, rel_path, _tick_path, _divergence_path in NEGATIVE_SOURCE_INGREDIENTS:
        with (PROJECT_ROOT / rel_path).open("r", encoding="ascii", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                events.append(
                    MemoryEvent(
                        source_id=source_id,
                        ingredient_id=ingredient_id,
                        fold_id=row["fold_id"],
                        signal_index=int(row["signal_index"]),
                        entry_time=datetime.strptime(row["entry_time"], TIME_FORMAT),
                        direction=int(row["direction"]),
                    )
                )
    return events


def load_source_profiles(source_rows: tuple[tuple[str, str, str, str, str], ...]) -> dict[str, SourceEvidenceProfile]:
    profiles: dict[str, SourceEvidenceProfile] = {}
    for source_id, ingredient_id, _trade_path, tick_path, divergence_path in source_rows:
        tick_data = json.loads((PROJECT_ROOT / tick_path).read_text(encoding="ascii"))
        tick_folds = tick_data["conditional_profiles"]["fold_profile"]["fields"]["folds"]
        fold_net = [
            (str(fold["fold_id"]), float(fold.get("required_kpis", {}).get("mt5_net_pnl", 0.0)))
            for fold in tick_folds
        ]
        losing_fold_ids = tuple(fold_id for fold_id, net_pnl in fold_net if net_pnl <= 0.0)
        weakest_fold_ids = tuple(fold_id for fold_id, _net_pnl in sorted(fold_net, key=lambda row: row[1])[:2])
        divergence_data = json.loads((PROJECT_ROOT / divergence_path).read_text(encoding="ascii"))
        divergence_folds = divergence_data["conditional_profiles"]["fold_divergence_profile"]["fields"]["folds"]
        tick_worse_fold_ids = tuple(
            str(fold["fold_id"])
            for fold in divergence_folds
            if fold.get("required_kpis", {}).get("economics_shift_status") == "tick_worse_than_logic"
        )
        profiles[source_id] = SourceEvidenceProfile(
            source_id=source_id,
            ingredient_id=ingredient_id,
            fold_loss_density=len(losing_fold_ids) / len(fold_net) if fold_net else 0.0,
            losing_fold_ids=losing_fold_ids,
            weakest_fold_ids=weakest_fold_ids,
            tick_worse_fold_ids=tick_worse_fold_ids,
        )
    return profiles


def group_generators_by_fold(candidates: list[GeneratorCandidate]) -> dict[str, list[GeneratorCandidate]]:
    grouped: dict[str, list[GeneratorCandidate]] = defaultdict(list)
    for candidate in candidates:
        grouped[candidate.fold_id].append(candidate)
    return dict(grouped)


def group_memory_events_by_fold(events: list[MemoryEvent]) -> dict[str, list[MemoryEvent]]:
    grouped: dict[str, list[MemoryEvent]] = defaultdict(list)
    for event in events:
        grouped[event.fold_id].append(event)
    return dict(grouped)


def synthesize_fold_candidates(
    generator_candidates: list[GeneratorCandidate],
    negative_events: list[MemoryEvent],
    candidate_profiles: dict[str, SourceEvidenceProfile],
    negative_profiles: dict[str, SourceEvidenceProfile],
) -> list[base.Candidate]:
    candidate_index: dict[tuple[int, int], list[GeneratorCandidate]] = defaultdict(list)
    for candidate in generator_candidates:
        candidate_index[(candidate.signal_index, candidate.direction)].append(candidate)

    negative_index: dict[tuple[int, int], list[MemoryEvent]] = defaultdict(list)
    for event in negative_events:
        negative_index[(event.signal_index, event.direction)].append(event)

    synthesized: list[base.Candidate] = []
    for candidate in generator_candidates:
        same_candidate_sources: set[str] = set()
        opposite_candidate_sources: set[str] = set()
        same_negative_sources: set[str] = set()
        opposite_negative_sources: set[str] = set()
        for offset in range(-CLUSTER_SPACING_BARS, CLUSTER_SPACING_BARS + 1):
            index = candidate.signal_index + offset
            same_candidate_sources.update(
                item.source_id for item in candidate_index.get((index, candidate.direction), [])
            )
            opposite_candidate_sources.update(
                item.source_id for item in candidate_index.get((index, -candidate.direction), [])
            )
            same_negative_sources.update(event.source_id for event in negative_index.get((index, candidate.direction), []))
            opposite_negative_sources.update(
                event.source_id for event in negative_index.get((index, -candidate.direction), [])
            )

        same_candidate_count = len(same_candidate_sources)
        source_diversity = len(same_candidate_sources | opposite_candidate_sources)
        same_negative_count = len(same_negative_sources)
        opposite_negative_count = len(opposite_negative_sources)
        negative_fold_loss_density = average_profile_value(
            negative_profiles,
            same_negative_sources,
            "fold_loss_density",
        )
        candidate_fold_weakness = candidate_weakness_pressure(
            candidate_profiles.get(candidate.source_id),
            candidate.fold_id,
        )
        execution_pressure = execution_divergence_pressure(
            candidate_profiles,
            same_candidate_sources,
            candidate.fold_id,
        )
        spread_pressure = max(candidate.spread_points, 0.0)
        score = (
            BASE_SCORE_WEIGHT * candidate.source_score_z
            + SOURCE_AGREEMENT_CREDIT * max(same_candidate_count - 1, 0)
            + SOURCE_DIVERSITY_CREDIT * min(source_diversity, 4)
            - SAME_NEGATIVE_COLLISION_PENALTY * same_negative_count
            + OPPOSITE_NEGATIVE_CONFLICT_CREDIT * opposite_negative_count
            - NEGATIVE_FOLD_LOSS_DENSITY_PENALTY * negative_fold_loss_density
            - CANDIDATE_FOLD_WEAKNESS_PENALTY * candidate_fold_weakness
            - EXECUTION_DIVERGENCE_PRESSURE_PENALTY * execution_pressure
            - SPREAD_PRESSURE_PENALTY * spread_pressure
        )
        context_veto = (
            same_negative_count >= SAME_NEGATIVE_CONTEXT_VETO_COUNT
            or candidate_fold_weakness >= CANDIDATE_FOLD_WEAKNESS_VETO_LEVEL
        )
        side = "long" if candidate.direction > 0 else "short"
        synthesized.append(
            base.Candidate(
                fold_id=candidate.fold_id,
                index=candidate.signal_index,
                direction=candidate.direction,
                day=candidate.entry_time.strftime("%Y-%m-%d"),
                state_key=(
                    f"{side}|post_sc0008_range_energy_mixed_evidence|src_{candidate.source_id}|"
                    f"agree_{same_candidate_count}|neg_{same_negative_count}|oppneg_{opposite_negative_count}|"
                    f"loss_{int(round(100.0 * negative_fold_loss_density))}|"
                    f"weak_{int(round(100.0 * candidate_fold_weakness))}|"
                    f"div_{int(round(100.0 * execution_pressure))}"
                ),
                features=(
                    candidate.source_score_z,
                    float(same_candidate_count),
                    float(source_diversity),
                    float(same_negative_count),
                    float(opposite_negative_count),
                    negative_fold_loss_density,
                    candidate_fold_weakness,
                    execution_pressure,
                    spread_pressure,
                    float(context_veto),
                ),
                label=None,
                score=None if context_veto else float(score),
            )
        )
    return synthesized


def average_profile_value(
    profiles: dict[str, SourceEvidenceProfile],
    source_ids: set[str],
    field: str,
) -> float:
    if not source_ids:
        return 0.0
    values = [float(getattr(profiles[source_id], field)) for source_id in source_ids if source_id in profiles]
    return sum(values) / len(values) if values else 0.0


def candidate_weakness_pressure(profile: SourceEvidenceProfile | None, fold_id: str) -> float:
    if profile is None:
        return 0.0
    pressure = 0.0
    if fold_id in profile.losing_fold_ids:
        pressure += 0.65
    if fold_id in profile.weakest_fold_ids:
        pressure += 0.25
    return min(pressure, 1.0)


def execution_divergence_pressure(
    profiles: dict[str, SourceEvidenceProfile],
    source_ids: set[str],
    fold_id: str,
) -> float:
    if not source_ids:
        return 0.0
    values = [
        1.0 if fold_id in profiles[source_id].tick_worse_fold_ids else 0.0
        for source_id in source_ids
        if source_id in profiles
    ]
    return sum(values) / len(values) if values else 0.0


def fold_model_summary(
    fold_id: str,
    generator_candidates: list[GeneratorCandidate],
    negative_events: list[MemoryEvent],
    synthesized: list[base.Candidate],
    selected: list[base.Candidate],
) -> dict[str, object]:
    generator_counts: dict[str, int] = defaultdict(int)
    negative_counts: dict[str, int] = defaultdict(int)
    for candidate in generator_candidates:
        generator_counts[candidate.source_id] += 1
    for event in negative_events:
        negative_counts[event.source_id] += 1
    return {
        "fold_id": fold_id,
        "model_family": MODEL_FAMILY,
        "label_shape": LABEL_SHAPE,
        "score_component_names": list(SCORE_COMPONENT_NAMES),
        "source_ingredient_ids": list(SOURCE_INGREDIENT_IDS),
        "candidate_source_event_counts": dict(sorted(generator_counts.items())),
        "negative_memory_event_counts": dict(sorted(negative_counts.items())),
        "synthesized_candidate_count": len(synthesized),
        "selected_candidate_count": len(selected),
        "selection_uses_source_oos_pnl": False,
        "selection_uses_source_proxy_pnl": False,
        "model_selected": False,
    }


def synthesis_distribution(
    synthesized: list[base.Candidate],
    selected: list[base.Candidate],
) -> dict[str, float | int | None]:
    scores = [candidate.score or 0.0 for candidate in synthesized if candidate.score is not None]
    selected_scores = [candidate.score or 0.0 for candidate in selected]
    agreement = [candidate.features[1] for candidate in synthesized]
    same_negative = [candidate.features[3] for candidate in synthesized]
    negative_loss_density = [candidate.features[5] for candidate in synthesized]
    candidate_weakness = [candidate.features[6] for candidate in synthesized]
    divergence_pressure = [candidate.features[7] for candidate in synthesized]
    veto_values = [candidate.features[9] for candidate in synthesized]
    return {
        "synthesized_candidate_count": len(synthesized),
        "selected_count": len(selected),
        "synthesis_score_p10": base.rounded(base.percentile(scores, 0.10)),
        "synthesis_score_p50": base.rounded(base.percentile(scores, 0.50)),
        "synthesis_score_p90": base.rounded(base.percentile(scores, 0.90)),
        "selected_score_min": base.rounded(min(selected_scores)) if selected_scores else None,
        "selected_score_max": base.rounded(max(selected_scores)) if selected_scores else None,
        "same_candidate_source_agreement_p50": base.rounded(base.percentile(agreement, 0.50)),
        "same_negative_collision_p50": base.rounded(base.percentile(same_negative, 0.50)),
        "negative_fold_loss_density_p50": base.rounded(base.percentile(negative_loss_density, 0.50)),
        "candidate_fold_weakness_p50": base.rounded(base.percentile(candidate_weakness, 0.50)),
        "execution_divergence_pressure_p50": base.rounded(base.percentile(divergence_pressure, 0.50)),
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
    payload["proxy_id"] = "PX-SC0009-SR0001"
    payload["proxy_engine"] = "axiom_rift.proxies.sc0009_sr0001_post_sc0008_range_energy_mixed_evidence_synthesis"
    payload["proxy_config_path"] = f"{RUN_REL}/run_manifest.json"
    payload["split_policy"] = "rolling_window_test_oos_only_with_c0046_c0047_c0048_schedule_mixed_evidence_rerank"
    payload["proxy_artifact_paths"] = [
        f"{RUN_REL}/kpi/proxy.json",
        f"{RUN_REL}/artifacts/sc0009_sr0001_proxy_trades.csv",
        f"{RUN_REL}/artifacts/sc0009_sr0001_summary.json",
    ]
    payload["proxy_config"] = proxy_config()
    payload["claim_boundary"] = claim_boundary()
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    profiles.pop("state_archetype_profile", None)  # type: ignore[union-attr]
    profiles["range_energy_mixed_evidence_synthesis_profile"] = {  # type: ignore[index]
        "applies": True,
        "fields": {
            "model_family": MODEL_FAMILY,
            "state_model": MODEL_FAMILY,
            "label_shape": LABEL_SHAPE,
            "source_ingredient_ids": list(SOURCE_INGREDIENT_IDS),
            "candidate_sources": [
                {
                    "source_id": item[0],
                    "ingredient_id": item[1],
                    "trade_artifact": item[2],
                    "tick_by_fold": item[3],
                    "execution_divergence_by_fold": item[4],
                }
                for item in CANDIDATE_SOURCE_INGREDIENTS
            ],
            "negative_memory_sources": [
                {
                    "source_id": item[0],
                    "ingredient_id": item[1],
                    "trade_artifact": item[2],
                    "tick_by_fold": item[3],
                    "execution_divergence_by_fold": item[4],
                }
                for item in NEGATIVE_SOURCE_INGREDIENTS
            ],
            "score_component_names": list(SCORE_COMPONENT_NAMES),
            "selection_rule": SELECTION_RULE,
            "cluster_spacing_bars": CLUSTER_SPACING_BARS,
            "same_negative_context_veto_count": SAME_NEGATIVE_CONTEXT_VETO_COUNT,
            "candidate_fold_weakness_veto_level": CANDIDATE_FOLD_WEAKNESS_VETO_LEVEL,
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
            "next_action": "produce_sc0009_sr0001_mt5_logic_parity_evidence",
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
            "candidate_trade_artifacts": [item[2] for item in CANDIDATE_SOURCE_INGREDIENTS],
            "candidate_tick_by_fold_artifacts": [item[3] for item in CANDIDATE_SOURCE_INGREDIENTS],
            "candidate_execution_divergence_artifacts": [item[4] for item in CANDIDATE_SOURCE_INGREDIENTS],
            "negative_memory_trade_artifacts": [item[2] for item in NEGATIVE_SOURCE_INGREDIENTS],
            "negative_memory_tick_by_fold_artifacts": [item[3] for item in NEGATIVE_SOURCE_INGREDIENTS],
            "negative_memory_execution_divergence_artifacts": [item[4] for item in NEGATIVE_SOURCE_INGREDIENTS],
            "cluster_spacing_bars": CLUSTER_SPACING_BARS,
            "same_negative_context_veto_count": SAME_NEGATIVE_CONTEXT_VETO_COUNT,
            "candidate_fold_weakness_veto_level": CANDIDATE_FOLD_WEAKNESS_VETO_LEVEL,
            "weights": score_weights(),
            "source_oos_pnl_used_for_selection": False,
            "source_proxy_pnl_used_for_selection": False,
            "variant_boundary": (
                "post_sc0008_range_energy_mixed_evidence_synthesis_not_threshold_score_cost_buffer_stop_target_hold_"
                "session_activity_spread_capital_monthly_filter_materialization_onnx_or_retry_nudge"
            ),
            "fixed_lot_policy": "early_discovery_fixed_lot_no_equity_percent_sizing_rescue",
        }
    )
    return config


def score_weights() -> dict[str, float]:
    return {
        "base_score": BASE_SCORE_WEIGHT,
        "source_agreement_credit": SOURCE_AGREEMENT_CREDIT,
        "source_diversity_credit": SOURCE_DIVERSITY_CREDIT,
        "same_negative_collision_penalty": SAME_NEGATIVE_COLLISION_PENALTY,
        "opposite_negative_conflict_credit": OPPOSITE_NEGATIVE_CONFLICT_CREDIT,
        "negative_fold_loss_density_penalty": NEGATIVE_FOLD_LOSS_DENSITY_PENALTY,
        "candidate_fold_weakness_penalty": CANDIDATE_FOLD_WEAKNESS_PENALTY,
        "execution_divergence_pressure_penalty": EXECUTION_DIVERGENCE_PRESSURE_PENALTY,
        "spread_pressure_penalty": SPREAD_PRESSURE_PENALTY,
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
        "schema": "axiom_rift_sc0009_range_energy_mixed_evidence_synthesis_summary_v1",
        "template": False,
        "work_unit_id": WORK_UNIT_ID,
        "synthesis_id": WORK_UNIT_ID,
        "run_id": RUN_ID,
        "created_at_utc": payload["created_at_utc"],
        "source_ingredient_ids": list(SOURCE_INGREDIENT_IDS),
        "proxy_config": payload["proxy_config"],
        "range_energy_mixed_evidence_synthesis_profile": profiles["range_energy_mixed_evidence_synthesis_profile"][
            "fields"
        ],
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
        "range_energy_mixed_evidence_summary_artifact",
    }
    records = [record for record in data.get("artifact_records", []) if record.get("artifact_role") not in filtered_roles]
    records.extend(
        [
            artifact_record(
                "A-SC0009-SR0001-RUN-MANIFEST",
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
                "A-SC0009-SR0001-GATE-REPORT",
                "gate_report",
                "json",
                f"{RUN_REL}/gate_report.json",
                gate_report_hash,
                [f"{RUN_REL}/run_manifest.json", f"{RUN_REL}/kpi/proxy.json"],
                "run_state",
            ),
            artifact_record(
                "A-SC0009-SR0001-PROXY-KPI",
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
                "A-SC0009-SR0001-PROXY-TRADES",
                "proxy_trade_artifact",
                "csv",
                f"{RUN_REL}/artifacts/sc0009_sr0001_proxy_trades.csv",
                trade_hash,
                [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    f"{RUN_REL}/kpi/proxy.json",
                ],
                "proxy",
            ),
            artifact_record(
                "A-SC0009-SR0001-RANGE-ENERGY-MIXED-EVIDENCE-SUMMARY",
                "range_energy_mixed_evidence_summary_artifact",
                "json",
                f"{RUN_REL}/artifacts/sc0009_sr0001_summary.json",
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
            "next_action": "produce_sc0009_sr0001_mt5_logic_parity_evidence",
        }
    ]
    data["created_at_utc"] = data.get("created_at_utc") or utc_now()
    data["lineage_id"] = data.get("lineage_id") or "L-SC0009-SR0001"
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
        "produced_by": "axiom_rift.proxies.sc0009_sr0001_post_sc0008_range_energy_mixed_evidence_synthesis",
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
    evidence["proxy_trade_artifact"] = "artifacts/sc0009_sr0001_proxy_trades.csv"
    evidence["mixed_evidence_summary"] = "artifacts/sc0009_sr0001_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["evidence_gate"]["checks"]["proxy_kpi_path_recorded"] = True
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["mt5_gate"]["status"] = "mt5_logic_parity_required_next"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_sc0009_sr0001_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/sc0009_sr0001_proxy_trades.csv",
        "artifacts/sc0009_sr0001_summary.json",
        "kpi/proxy.json",
    ):
        if path not in evidence_paths:
            evidence_paths.append(path)
    data["evidence_paths"] = evidence_paths
    data["deferred_with_reason"] = [
        {
            "field": "decision",
            "reason": "proxy evidence is recorded but MT5 and proxy-vs-MT5 evidence are still missing",
            "blocking_condition": (
                "SR0001 cannot close until mandatory MT5 logic parity, MT5 tick, execution divergence, "
                "and fold-isolated evidence are recorded"
            ),
            "revisit_when": "produce_sc0009_sr0001_mt5_logic_parity_evidence",
        }
    ]
    GATE_REPORT_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_synthesis_status() -> None:
    data = yaml.safe_load(SYNTHESIS_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_attempts"
    open_state = data.setdefault("open_state", {})
    open_state["status"] = "mt5_probe_attempts"
    open_state["next_required_action"] = "produce_sc0009_sr0001_mt5_logic_parity_evidence"
    run_index = data.setdefault("run_index", {})
    run_index["active_run"] = "runs/SR0001"
    opened = list(run_index.get("opened_runs") or [])
    if "runs/SR0001" not in opened:
        opened.append("runs/SR0001")
    run_index["opened_runs"] = opened
    next_candidate = run_index.setdefault("next_run_candidate", {})
    next_candidate["run_id"] = RUN_ID
    next_candidate["direction"] = "produce_sc0009_sr0001_mt5_logic_parity_evidence"
    next_candidate["reason"] = "SR0001 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    SYNTHESIS_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_synthesis_queue_after_proxy() -> None:
    data = yaml.safe_load(SYNTHESIS_QUEUE_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_attempts"
    for item in data.get("queue", []):
        if item.get("synthesis_run_id") == RUN_ID:
            item["status"] = "proxy_done"
            item["last_completed_step"] = "produce_sc0009_sr0001_proxy_evidence"
            item["next_action"] = "produce_sc0009_sr0001_mt5_logic_parity_evidence"
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
    latest["next_required_action"] = "produce_sc0009_sr0001_mt5_logic_parity_evidence"
    SELECTED_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_reentry_after_proxy() -> None:
    data = yaml.safe_load(REENTRY_PATH.read_text(encoding="ascii"))
    data["updated_local_date"] = datetime.now().date().isoformat()
    conditional = data.setdefault("read_budget", {}).setdefault("conditional_files", {})
    conditional["active_campaign"] = None
    conditional["active_synthesis"] = WORK_UNIT_REL
    data.setdefault("project", {})["active_campaign"] = None
    data.setdefault("project", {})["active_synthesis"] = WORK_UNIT_REL
    data.setdefault("project", {})["active_run"] = RUN_REL
    next_work = data.setdefault("next_work", {})
    next_work["campaign"] = None
    next_work["synthesis"] = WORK_UNIT_REL
    completed = list(next_work.get("completed") or [])
    if "produce_sc0009_sr0001_proxy_evidence" not in completed:
        completed.append("produce_sc0009_sr0001_proxy_evidence")
    next_action = "produce_sc0009_sr0001_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    next_work["active_campaign"] = None
    next_work["active_run"] = RUN_REL
    next_work["run"] = RUN_REL
    next_work["active_synthesis"] = WORK_UNIT_REL
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
        "id": "produce_sc0009_sr0001_proxy_evidence",
        "status": "completed",
        "recorded_at_source": f"{RUN_REL}/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "active_synthesis": WORK_UNIT_REL,
        "active_run": RUN_REL,
        "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
        "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
        "next_required_action": "produce_sc0009_sr0001_mt5_logic_parity_evidence",
        "claim_boundary": claim_boundary(),
    }
    data["claim_boundary"] = claim_boundary()
    CLAIM_STATE_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def update_decision_cursor_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(DECISION_CURSOR_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["updated_local_date"] = datetime.now().date().isoformat()
    data["canonical_source"] = f"{RUN_REL}/kpi/proxy.json"
    data["canonical_status"] = "proxy_recorded_pending_mt5"
    data["current_decision"] = "produce_sc0009_sr0001_mt5_logic_parity_evidence"
    data["active_campaign"] = None
    data["active_synthesis"] = WORK_UNIT_REL
    data["active_run"] = RUN_REL
    data["next_required_action"] = "produce_sc0009_sr0001_mt5_logic_parity_evidence"
    current = data.setdefault("current_evidence_summary", {})
    current.update(
        {
            "source_campaign": None,
            "source_synthesis": WORK_UNIT_REL,
            "current_task": "produce_sc0009_sr0001_mt5_logic_parity_evidence",
            "active_run": RUN_REL,
            "active_run_status": "proxy_recorded_pending_mt5",
            "evidence_status": "proxy_recorded_pending_mt5",
            "hypothesis_family": MODEL_FAMILY,
            "label_surface": LABEL_SHAPE,
            "feature_surface": "c0046_c0047_c0048_candidate_schedule_agreement_negative_memory_fold_loss_and_execution_divergence_context",
            "trade_logic_surface": "fixed_lot_pooled_candidate_schedule_reweighted_by_post_sc0008_mixed_evidence_context",
            "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
            "proxy_net_pnl_points": required.get("proxy_net_pnl_points") if isinstance(required, dict) else None,
            "proxy_profit_factor": required.get("proxy_profit_factor") if isinstance(required, dict) else None,
            "proxy_trade_count": required.get("proxy_trade_count") if isinstance(required, dict) else None,
            "note": "SC0009 SR0001 proxy is recorded; MT5 paired validation is mandatory before judgment.",
        }
    )
    data["next_decision_basis"] = [
        {
            "path": f"{RUN_REL}/kpi/proxy.json",
            "role": "active_synthesis_run_proxy_kpi",
            "summary": "SC0009 SR0001 proxy evidence is recorded; MT5 logic parity is next and proxy is not a go/no-go gate.",
        },
        {
            "path": f"{RUN_REL}/run_manifest.json",
            "role": "active_synthesis_run_manifest",
            "summary": "SR0001 remains open with mandatory MT5 paired validation before judgment.",
        },
        {
            "path": f"{WORK_UNIT_REL}/ingredient_refs.yaml",
            "role": "active_synthesis_ingredient_index",
            "summary": "Ingredient refs preserve C0046/C0047/C0048 candidate, negative-memory, and divergence evidence context.",
        },
    ]
    data["claim_boundary_snapshot"] = claim_boundary()
    DECISION_CURSOR_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False, width=88), encoding="ascii")


def append_decision_registry_after_proxy(payload: dict[str, object]) -> None:
    decision_id = "dec_20260706_produce_sc0009_sr0001_proxy_evidence"
    text = DECISION_REGISTRY_PATH.read_text(encoding="ascii")
    if decision_id in text:
        return
    required = payload.get("required_kpis", {})
    summary = payload.get("proxy_summary", {})
    block = f"""
- decision_id: {decision_id}
  created_local_date: '2026-07-06'
  status: active
  decision: produce_sc0009_sr0001_proxy_evidence
  refines:
  - dec_20260706_open_sc0009_sr0001_post_sc0008_range_energy_mixed_evidence_synthesis_run
  - dec_20260701_mandatory_mt5_paired_run_validation
  rationale:
  - sc0009_sr0001_proxy_pools_c0046_r0001_c0047_r0001_and_c0048_r0002_candidate_schedule_entries_with_c0046_r0002_c0047_r0002_and_c0048_r0001_negative_memory_context
  - source_oos_pnl_and_source_proxy_pnl_are_not_used_for_entry_selection
  - proxy_trade_count_{required.get("proxy_trade_count") if isinstance(required, dict) else "unknown"}_and_entries_per_active_day_{summary.get("entries_per_active_day") if isinstance(summary, dict) else "unknown"}_are_reference_proxy_evidence_only
  - proxy_net_pnl_points_{required.get("proxy_net_pnl_points") if isinstance(required, dict) else "unknown"}_and_profit_factor_{required.get("proxy_profit_factor") if isinstance(required, dict) else "unknown"}_do_not_create_selection_or_economics_claims
  - weak_or_strong_proxy_must_continue_to_mt5_logic_parity_proxy_vs_mt5_parity_mt5_tick_execution_divergence_and_fold_isolated_closeout_evidence
  - next_work_is_produce_sc0009_sr0001_mt5_logic_parity_evidence
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
            "C0004 R0001": "SC0009 SR0001",
            "C0004": "SC0009",
            "R0001": "SR0001",
            "c0004_r0001_fold_local_state_archetype": "sc0009_sr0001_post_sc0008_range_energy_mixed_evidence_synthesis",
            "c0004_r0001": "sc0009_sr0001",
            "fold_local_state_archetype_discovery": "post_sc0008_range_energy_mixed_evidence_synthesis",
            "fold_local_state_archetype_membership": MODEL_FAMILY,
            "directional_target_before_stop_plus_path_quality": LABEL_SHAPE,
            "state_archetype_summary": "range_energy_mixed_evidence_summary",
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
    print(json.dumps(run_sc0009_sr0001_proxy(write=True), indent=2, sort_keys=True))
