"""C0004 R0002 proxy evidence for path-quality-aware state archetypes."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from axiom_rift.paths import PROJECT_ROOT
from axiom_rift.proxies import c0004_r0001_fold_local_state_archetype as base


RUN_DIR = PROJECT_ROOT / "campaigns" / "C0004_fold_local_state_archetype_discovery" / "runs" / "R0002"
CAMPAIGN_PATH = PROJECT_ROOT / "campaigns" / "C0004_fold_local_state_archetype_discovery" / "campaign.yaml"
PROXY_PATH = RUN_DIR / "kpi" / "proxy.json"
TRADE_ARTIFACT_PATH = RUN_DIR / "artifacts" / "c0004_r0002_proxy_trades.csv"
PATH_QUALITY_SUMMARY_PATH = RUN_DIR / "artifacts" / "c0004_r0002_path_quality_archetype_summary.json"
RUN_MANIFEST_PATH = RUN_DIR / "run_manifest.json"
GATE_REPORT_PATH = RUN_DIR / "gate_report.json"
ARTIFACT_LINEAGE_PATH = RUN_DIR / "artifact_lineage.json"
CLAIM_STATE_PATH = PROJECT_ROOT / "registries" / "claim_state.yaml"
BASE_FRAME = base.BASE_FRAME
ROLLING_WINDOWS = base.ROLLING_WINDOWS
SplitWindow = base.SplitWindow
Trade = base.Trade
load_bars = base.load_bars
load_windows = base.load_windows

PRIOR_PATH_BARS = 12
EARLY_ADVERSE_BARS = 3
FEATURE_NAMES = base.FEATURE_NAMES + (
    "prior_adverse_pressure",
    "prior_against_close_ratio",
    "prior_directional_follow_through",
)
STATE_DIMENSIONS = base.STATE_DIMENSIONS + (
    "prior_adverse_state",
    "prior_path_stability_state",
    "prior_follow_through_state",
)


def run_c0004_r0002_proxy(write: bool = True) -> dict[str, object]:
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
    return build_proxy_run_result().trades


def build_proxy_run_result() -> base.ProxyRunResult:
    bars = base.load_bars(base.BASE_FRAME)
    windows = base.load_windows(base.ROLLING_WINDOWS)
    ranges = [bar.high - bar.low for bar in bars]
    range_average = base.previous_rolling_average(ranges, base.LOOKBACK_RANGE_BARS)
    short_range_average = base.previous_rolling_average(ranges, base.SHORT_RANGE_BARS)
    trades: list[base.Trade] = []
    fold_models: list[dict[str, object]] = []
    state_distributions: dict[str, dict[str, float | int | None]] = {}
    candidates_by_fold: dict[str, dict[str, int]] = {}
    for fold_id in sorted(fold_id for fold_id, split in windows.items() if {"train_is", "test_oos"} <= set(split)):
        split = windows[fold_id]
        train_candidates = build_path_quality_candidates(
            bars,
            range_average,
            short_range_average,
            split["train_is"],
            fold_id,
            include_labels=True,
        )
        model = fit_path_quality_model(train_candidates, fold_id)
        test_candidates = build_path_quality_candidates(
            bars,
            range_average,
            short_range_average,
            split["test_oos"],
            fold_id,
            include_labels=False,
        )
        scored_candidates = [score_candidate(candidate, model) for candidate in test_candidates]
        selected = base.select_daily_candidates(scored_candidates)
        trades.extend(base.simulate_trades(bars, range_average, selected, split["test_oos"]))
        fold_models.append(archetype_model_summary(model))
        state_distributions[fold_id] = base.state_distribution(scored_candidates, selected, model)
        candidates_by_fold[fold_id] = {
            "train_candidate_count": len(train_candidates),
            "test_candidate_count": len(test_candidates),
            "selected_candidate_count": len(selected),
            "eligible_archetype_count": len(model.eligible_archetypes),
            "observed_archetype_count": model.observed_archetype_count,
        }
    return base.ProxyRunResult(
        trades=trades,
        windows=windows,
        fold_models=fold_models,
        state_distributions=state_distributions,
        candidates_by_fold=candidates_by_fold,
    )


def build_path_quality_candidates(
    bars: list[base.Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
    window: base.SplitWindow,
    fold_id: str,
    include_labels: bool,
) -> list[base.Candidate]:
    start_index = max(
        base.first_index_at_or_after(bars, window.start),
        base.LOOKBACK_RANGE_BARS,
        base.SHORT_RANGE_BARS,
        base.TREND_BARS,
        base.POSITION_BARS,
        base.MOMENTUM_BARS,
        PRIOR_PATH_BARS + 1,
    )
    end_index = min(base.last_index_at_or_before(bars, window.end), len(bars) - base.LABEL_HORIZON_BARS - 2)
    candidates: list[base.Candidate] = []
    for index in range(start_index, end_index + 1):
        if not base.in_core_session(bars[index].time):
            continue
        average_range = range_average[index]
        short_average_range = short_range_average[index]
        if average_range is None or average_range <= 0 or short_average_range is None or short_average_range <= 0:
            continue
        for direction in (1, -1):
            state_key, features = path_quality_state_and_features(
                bars,
                range_average,
                short_range_average,
                index,
                direction,
            )
            if state_key is None or features is None:
                continue
            label = path_quality_label(bars, range_average, index, direction) if include_labels else None
            candidates.append(
                base.Candidate(
                    fold_id=fold_id,
                    index=index,
                    direction=direction,
                    day=bars[index].time.strftime("%Y-%m-%d"),
                    state_key=state_key,
                    features=features,
                    label=label,
                )
            )
    return candidates


def path_quality_state_and_features(
    bars: list[base.Bar],
    range_average: list[float | None],
    short_range_average: list[float | None],
    index: int,
    direction: int,
) -> tuple[str | None, tuple[float, ...] | None]:
    state_key, features = base.candidate_state_and_features(
        bars,
        range_average,
        short_range_average,
        index,
        direction,
    )
    metrics = prior_path_metrics(bars, range_average, index, direction)
    if state_key is None or features is None or metrics is None:
        return None, None
    adverse_pressure, against_ratio, follow_through = metrics
    dimensions = (
        adverse_pressure_bucket(adverse_pressure),
        path_stability_bucket(against_ratio),
        follow_through_bucket(follow_through),
    )
    return state_key + "|" + "|".join(dimensions), features + metrics


def prior_path_metrics(
    bars: list[base.Bar],
    range_average: list[float | None],
    index: int,
    direction: int,
) -> tuple[float, float, float] | None:
    average_range = range_average[index]
    if average_range is None or average_range <= 0 or index <= PRIOR_PATH_BARS:
        return None
    start = index - PRIOR_PATH_BARS
    anchor = bars[start].close
    window = bars[start + 1 : index + 1]
    if not window:
        return None
    if direction > 0:
        adverse = max(anchor - bar.low for bar in window)
    else:
        adverse = max(bar.high - anchor for bar in window)
    against_moves = [
        direction * (bars[row].close - bars[row - 1].close)
        for row in range(start + 1, index + 1)
    ]
    against_ratio = sum(1 for move in against_moves if move < 0.0) / len(against_moves)
    follow_through = direction * (bars[index].close - anchor) / average_range
    return adverse / average_range, against_ratio, follow_through


def path_quality_label(
    bars: list[base.Bar],
    range_average: list[float | None],
    index: int,
    direction: int,
) -> float | None:
    entry_index = index + 1
    exit_index = min(index + base.LABEL_HORIZON_BARS, len(bars) - 1)
    average_range = range_average[index]
    if average_range is None or average_range <= 0 or entry_index >= exit_index:
        return None
    entry = bars[entry_index].open
    path = bars[entry_index : exit_index + 1]
    stop_distance = base.STOP_RANGE_MULTIPLE * average_range
    target_distance = base.TARGET_RANGE_MULTIPLE * average_range
    stop_price = entry - direction * stop_distance
    target_price = entry + direction * target_distance
    first_hit = 0.0
    for bar in path:
        if direction > 0:
            hit_stop = bar.low <= stop_price
            hit_target = bar.high >= target_price
        else:
            hit_stop = bar.high >= stop_price
            hit_target = bar.low <= target_price
        if hit_stop:
            first_hit = -1.0
            break
        if hit_target:
            first_hit = 1.0
            break
    if direction > 0:
        mfe = max(bar.high - entry for bar in path)
        mae = max(entry - bar.low for bar in path)
        terminal = path[-1].close - entry
        early_mae = max(entry - bar.low for bar in path[:EARLY_ADVERSE_BARS])
    else:
        mfe = max(entry - bar.low for bar in path)
        mae = max(bar.high - entry for bar in path)
        terminal = entry - path[-1].close
        early_mae = max(bar.high - entry for bar in path[:EARLY_ADVERSE_BARS])
    closes = [direction * (path[row].close - path[row - 1].close) for row in range(1, len(path))]
    clean_ratio = sum(1 for move in closes if move >= 0.0) / len(closes) if closes else 0.0
    normalized = {
        "terminal": terminal / average_range,
        "mfe": mfe / average_range,
        "mae": mae / average_range,
        "early_mae": early_mae / average_range,
        "spread": bars[entry_index].spread_points / average_range,
    }
    return (
        0.35 * first_hit
        + 0.40 * normalized["terminal"]
        + 0.35 * normalized["mfe"]
        - 0.95 * normalized["mae"]
        - 0.35 * normalized["early_mae"]
        + 0.20 * clean_ratio
        - normalized["spread"]
    )


def fit_path_quality_model(candidates: list[base.Candidate], fold_id: str) -> base.ArchetypeModel:
    grouped: dict[str, list[float]] = defaultdict(list)
    labels: list[float] = []
    for candidate in candidates:
        if candidate.label is None:
            continue
        grouped[candidate.state_key].append(candidate.label)
        labels.append(candidate.label)
    if not labels:
        return base.ArchetypeModel(fold_id, 0.0, None, 0, {}, 0)
    global_mean = base.mean(labels) or 0.0
    global_positive_rate = sum(1 for label in labels if label > 0.0) / len(labels)
    stats: list[base.ArchetypeStats] = []
    for archetype_id, bucket in grouped.items():
        if len(bucket) < base.MIN_TRAIN_ARCHETYPE_COUNT:
            continue
        mean_label = base.mean(bucket) or 0.0
        positive_rate = sum(1 for label in bucket if label > 0.0) / len(bucket)
        edge_lift = mean_label - global_mean
        positive_lift = positive_rate - global_positive_rate
        downside_tail = min(bucket)
        activity_weight = math.log(1.0 + len(bucket) / base.MIN_TRAIN_ARCHETYPE_COUNT)
        score = mean_label + 0.25 * positive_lift + 0.02 * activity_weight + 0.06 * max(downside_tail, -1.5)
        if edge_lift <= 0.0 or positive_lift < 0.0:
            continue
        stats.append(
            base.ArchetypeStats(
                archetype_id=archetype_id,
                count=len(bucket),
                mean_label=mean_label,
                positive_rate=positive_rate,
                score=score,
            )
        )
    ordered = sorted(stats, key=lambda row: (row.score, row.count), reverse=True)
    eligible = {row.archetype_id: row for row in ordered[: base.TOP_ARCHETYPES_PER_FOLD]}
    return base.ArchetypeModel(
        fold_id=fold_id,
        global_mean=global_mean,
        global_positive_rate=global_positive_rate,
        train_candidate_count=len(labels),
        eligible_archetypes=eligible,
        observed_archetype_count=len(grouped),
    )


def score_candidate(candidate: base.Candidate, model: base.ArchetypeModel) -> base.Candidate:
    stat = model.eligible_archetypes.get(candidate.state_key)
    return base.Candidate(
        fold_id=candidate.fold_id,
        index=candidate.index,
        direction=candidate.direction,
        day=candidate.day,
        state_key=candidate.state_key,
        features=candidate.features,
        label=candidate.label,
        score=None if stat is None else stat.score,
    )


def build_proxy_payload(
    trades: list[base.Trade],
    windows: dict[str, dict[str, base.SplitWindow]],
    fold_models: list[dict[str, object]],
    state_distributions: dict[str, dict[str, float | int | None]],
    candidates_by_fold: dict[str, dict[str, int]],
) -> dict[str, object]:
    payload = replace_run_markers(base.build_proxy_payload(trades, windows, fold_models, state_distributions, candidates_by_fold))
    payload["run_id"] = "R0002"
    payload["proxy_id"] = "PX-C0004-R0002"
    payload["proxy_engine"] = "axiom_rift.proxies.c0004_r0002_path_quality_archetype"
    payload["proxy_artifact_paths"] = [
        "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0002/kpi/proxy.json",
        "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0002/artifacts/c0004_r0002_proxy_trades.csv",
        "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0002/artifacts/c0004_r0002_path_quality_archetype_summary.json",
    ]
    payload["proxy_config"] = proxy_config()
    profile = payload["conditional_profiles"]["state_archetype_profile"]["fields"]  # type: ignore[index]
    profile["feature_count"] = len(FEATURE_NAMES)
    profile["feature_names"] = list(FEATURE_NAMES)
    profile["state_dimensions"] = list(STATE_DIMENSIONS)
    profile["label_shape"] = "directional_forward_path_quality_with_early_adverse_excursion_penalty"
    profile["selection_rule"] = "top_fold_local_path_quality_archetypes_per_active_day"
    profile["model_family"] = "fold_local_path_quality_state_archetype_membership"
    payload["conditional_profiles"]["path_quality_profile"] = {  # type: ignore[index]
        "applies": True,
        "fields": {
            "prior_path_bars": PRIOR_PATH_BARS,
            "early_adverse_bars": EARLY_ADVERSE_BARS,
            "prior_adverse_pressure_state": True,
            "prior_path_stability_state": True,
            "prior_directional_follow_through_state": True,
            "model_selected": False,
            "feature_set_selected": False,
            "label_selected": False,
        },
    }
    return payload


def proxy_config() -> dict[str, object]:
    config = dict(base.proxy_config())
    config.update(
        {
            "state_model": "fold_local_path_quality_state_archetype_membership",
            "label_shape": "directional_forward_path_quality_with_early_adverse_excursion_penalty",
            "prior_path_bars": PRIOR_PATH_BARS,
            "early_adverse_bars": EARLY_ADVERSE_BARS,
            "feature_names": list(FEATURE_NAMES),
            "state_dimensions": list(STATE_DIMENSIONS),
            "variant_boundary": "path_quality_and_adverse_path_state_archetype_filter_not_adjacent_r0001_nudge",
        }
    )
    return config


def archetype_model_summary(model: base.ArchetypeModel) -> dict[str, object]:
    summary = base.archetype_model_summary(model)
    summary["feature_names"] = list(FEATURE_NAMES)
    summary["state_dimensions"] = list(STATE_DIMENSIONS)
    summary["model_family"] = "fold_local_path_quality_state_archetype_membership"
    return summary


def write_proxy_evidence(payload: dict[str, object], trades: list[base.Trade]) -> None:
    RUN_DIR.joinpath("artifacts").mkdir(parents=True, exist_ok=True)
    RUN_DIR.joinpath("kpi").mkdir(parents=True, exist_ok=True)
    base.write_trade_artifact(trades, TRADE_ARTIFACT_PATH)
    write_path_quality_summary_artifact(payload, PATH_QUALITY_SUMMARY_PATH)
    PROXY_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="ascii")
    trade_hash = base.sha256_file(TRADE_ARTIFACT_PATH)
    summary_hash = base.sha256_file(PATH_QUALITY_SUMMARY_PATH)
    update_proxy_hashes(trade_hash, summary_hash)
    proxy_hash = base.sha256_file(PROXY_PATH)
    update_artifact_lineage(proxy_hash, trade_hash, summary_hash)
    update_run_manifest_status()
    update_gate_report()
    update_campaign_status()
    update_reentry_after_proxy()
    update_claim_state_after_proxy(payload)


def write_path_quality_summary_artifact(payload: dict[str, object], path: Path) -> None:
    profiles = payload["conditional_profiles"]  # type: ignore[index]
    summary = {
        "schema": "axiom_rift_path_quality_archetype_summary_v1",
        "template": False,
        "work_unit_id": "C0004",
        "run_id": "R0002",
        "created_at_utc": payload["created_at_utc"],
        "proxy_config": payload["proxy_config"],
        "state_archetype_profile": profiles["state_archetype_profile"]["fields"],  # type: ignore[index]
        "path_quality_profile": profiles["path_quality_profile"]["fields"],  # type: ignore[index]
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
        if record.get("artifact_role") not in {"proxy_kpi", "proxy_trade_artifact", "path_quality_archetype_summary_artifact"}
    ]
    records.extend(
        [
            {
                "artifact_id": "A-C0004-R0002-PROXY-KPI",
                "artifact_role": "proxy_kpi",
                "artifact_type": "json",
                "repo_relative_path": "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0002/kpi/proxy.json",
                "sha256": proxy_hash,
                "produced_by": "axiom_rift.proxies.c0004_r0002_path_quality_archetype",
                "source_inputs": [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0002/run_manifest.json",
                ],
                "linked_kpi_family": "proxy",
                "mutable": False,
                "claim_authority": False,
            },
            {
                "artifact_id": "A-C0004-R0002-PROXY-TRADES",
                "artifact_role": "proxy_trade_artifact",
                "artifact_type": "csv",
                "repo_relative_path": "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0002/artifacts/c0004_r0002_proxy_trades.csv",
                "sha256": trade_hash,
                "produced_by": "axiom_rift.proxies.c0004_r0002_path_quality_archetype",
                "source_inputs": [
                    "data/processed/datasets/us100_m5_base_frame.csv",
                    "data/processed/coverage_audits/us100_m5_rolling_windows.csv",
                    "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0002/kpi/proxy.json",
                ],
                "linked_kpi_family": "proxy",
                "mutable": False,
                "claim_authority": False,
            },
            {
                "artifact_id": "A-C0004-R0002-PATH-QUALITY-ARCHETYPE-SUMMARY",
                "artifact_role": "path_quality_archetype_summary_artifact",
                "artifact_type": "json",
                "repo_relative_path": "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0002/artifacts/c0004_r0002_path_quality_archetype_summary.json",
                "sha256": summary_hash,
                "produced_by": "axiom_rift.proxies.c0004_r0002_path_quality_archetype",
                "source_inputs": [
                    "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0002/kpi/proxy.json",
                ],
                "linked_kpi_family": "proxy",
                "mutable": False,
                "claim_authority": False,
            },
        ]
    )
    data["artifact_records"] = records
    data["deferred_with_reason"] = [
        {
            "field": "mt5_artifact_hashes",
            "reason": "MT5 artifacts are produced after proxy evidence in the mandatory paired validation sequence",
            "next_action": "produce_c0004_r0002_mt5_logic_parity_evidence",
        }
    ]
    ARTIFACT_LINEAGE_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_run_manifest_status() -> None:
    data = json.loads(RUN_MANIFEST_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_ready"
    data["gate_status"] = "proxy_recorded_pending_mt5"
    evidence = data.setdefault("evidence_paths", {})
    evidence["proxy_trade_artifact"] = "artifacts/c0004_r0002_proxy_trades.csv"
    evidence["path_quality_archetype_summary"] = "artifacts/c0004_r0002_path_quality_archetype_summary.json"
    RUN_MANIFEST_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_gate_report() -> None:
    data = json.loads(GATE_REPORT_PATH.read_text(encoding="ascii"))
    data["evidence_gate"]["status"] = "proxy_recorded_pending_mt5"
    data["parity_gate"]["status"] = "blocked_until_mt5"
    data["decision"] = "defer_with_reason"
    data["next_action"] = "produce_c0004_r0002_mt5_logic_parity_evidence"
    evidence_paths = list(data.get("evidence_paths") or [])
    for path in (
        "artifacts/c0004_r0002_proxy_trades.csv",
        "artifacts/c0004_r0002_path_quality_archetype_summary.json",
        "kpi/proxy.json",
    ):
        if path not in evidence_paths:
            evidence_paths.append(path)
    data["evidence_paths"] = evidence_paths
    data["deferred_with_reason"] = [
        {
            "field": "decision",
            "reason": "proxy evidence is recorded but MT5 and proxy-vs-MT5 evidence are still missing",
            "blocking_condition": "R0002 cannot close until mandatory MT5 logic parity, MT5 tick, execution divergence, and fold-isolated evidence are recorded",
            "revisit_when": "after C0004 R0002 MT5 evidence files contain measured results",
        }
    ]
    GATE_REPORT_PATH.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="ascii")


def update_campaign_status() -> None:
    data = yaml.safe_load(CAMPAIGN_PATH.read_text(encoding="ascii"))
    data["status"] = "mt5_probe_attempts"
    run_index = data.setdefault("run_index", {})
    run_index["active_run"] = "runs/R0002"
    next_candidate = run_index.setdefault("next_run_candidate", {})
    next_candidate["run_id"] = "R0002"
    next_candidate["direction"] = "active_r0002_mt5_logic_parity"
    next_candidate["reason"] = "R0002 proxy evidence is recorded; next work is mandatory MT5 logic parity before any hypothesis judgment."
    next_candidate["status"] = "active_run_open"
    closeout = data.setdefault("closeout", {})
    closeout["remaining_question"] = "produce_c0004_r0002_mt5_logic_parity_evidence"
    CAMPAIGN_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_reentry_after_proxy() -> None:
    path = PROJECT_ROOT / "registries" / "reentry.yaml"
    data = yaml.safe_load(path.read_text(encoding="ascii"))
    next_work = data.setdefault("next_work", {})
    completed = list(next_work.get("completed") or [])
    if "produce_c0004_r0002_proxy_evidence" not in completed:
        completed.append("produce_c0004_r0002_proxy_evidence")
    next_action = "produce_c0004_r0002_mt5_logic_parity_evidence"
    completed = [item for item in completed if item != next_action]
    next_work["completed"] = completed
    next_work["tasks"] = [next_action]
    data["active_run"] = "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0002"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def update_claim_state_after_proxy(payload: dict[str, object]) -> None:
    data = yaml.safe_load(CLAIM_STATE_PATH.read_text(encoding="ascii"))
    summary = payload.get("proxy_summary", {})
    required = payload.get("required_kpis", {})
    data["active_campaign"] = "campaigns/C0004_fold_local_state_archetype_discovery"
    data["active_run"] = "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0002"
    data["latest_operation"] = {
        "id": "produce_c0004_r0002_proxy_evidence",
        "status": "completed",
        "recorded_at_source": "campaigns/C0004_fold_local_state_archetype_discovery/runs/R0002/kpi/proxy.json",
        "evidence_status": "proxy_recorded_pending_mt5",
        "proxy_trade_count": required.get("proxy_trade_count"),
        "entries_per_active_day": summary.get("entries_per_active_day") if isinstance(summary, dict) else None,
        "proxy_net_pnl_points": required.get("proxy_net_pnl_points"),
        "proxy_profit_factor": required.get("proxy_profit_factor"),
        "next_required_action": "produce_c0004_r0002_mt5_logic_parity_evidence",
        "claim_boundary": {
            "claim_authority": False,
            "selected": False,
            "label_selected": False,
            "feature_set_selected": False,
            "model_selected": False,
            "runtime_authority": False,
            "onnx_ready": False,
            "promotion_ready": False,
            "live_ready": False,
        },
    }
    CLAIM_STATE_PATH.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=False), encoding="ascii")


def replace_run_markers(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: replace_run_markers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_run_markers(item) for item in value]
    if isinstance(value, str):
        replacements = {
            "c0004_r0001_fold_local_state_archetype": "c0004_r0002_path_quality_archetype",
            "c0004_r0001": "c0004_r0002",
            "C0004_R0001": "C0004_R0002",
            "R0001": "R0002",
            "r0001": "r0002",
        }
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value
    return value


def adverse_pressure_bucket(value: float) -> str:
    if value < 0.45:
        return "prior_adverse_low"
    if value < 0.90:
        return "prior_adverse_mid"
    return "prior_adverse_high"


def path_stability_bucket(value: float) -> str:
    if value < 0.35:
        return "prior_path_smooth"
    if value < 0.58:
        return "prior_path_mixed"
    return "prior_path_unstable"


def follow_through_bucket(value: float) -> str:
    if value < -0.35:
        return "prior_follow_against"
    if value < 0.35:
        return "prior_follow_flat"
    return "prior_follow_with"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
