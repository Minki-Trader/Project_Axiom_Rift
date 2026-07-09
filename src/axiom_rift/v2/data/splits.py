"""Adapt legacy boundaries into V2 development roles without inheriting claims."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
SCOUT_ANCHORS = {"V2D002", "V2D005", "V2D008"}
ALL_DEVELOPMENT = {f"V2D{index:03d}" for index in range(1, 10)}
SCOUT_ANCHOR_METHOD = "preregistered_time_and_calendar_phase_diversity"
SCOUT_ANCHOR_RATIONALE = (
    "cover_early_middle_late_development_with_distinct_"
    "may_july_february_april_and_november_january_phases"
)


class SplitAccessError(RuntimeError):
    """Raised when a stage attempts to inspect an unauthorized split."""


def adapt_split_set(path: Path, expected_sha256: str, dataset_object_id: str, dataset_sha256: str) -> dict[str, Any]:
    from axiom_rift.v2.data.datasets import sha256_file

    if sha256_file(path) != expected_sha256:
        raise ValueError("rolling-window source hash differs from the V2 split contract")
    source = json.loads(path.read_text(encoding="ascii"))
    source_folds = source.get("folds")
    if not isinstance(source_folds, list) or len(source_folds) != 9:
        raise ValueError("V2SP0001 requires exactly nine source development folds")
    expected_ids = [f"rw_{index:03d}" for index in range(1, 10)]
    if [fold.get("fold_id") for fold in source_folds] != expected_ids:
        raise ValueError("source fold identity or order differs from V2SP0001")
    folds = []
    previous_development_end: datetime | None = None
    for index, fold in enumerate(source_folds, start=1):
        train_end = datetime.strptime(fold["train_is"]["end"], TIME_FORMAT)
        validation_start = datetime.strptime(fold["validation_oos"]["start"], TIME_FORMAT)
        validation_end = datetime.strptime(fold["validation_oos"]["end"], TIME_FORMAT)
        development_start = datetime.strptime(fold["test_oos"]["start"], TIME_FORMAT)
        development_end = datetime.strptime(fold["test_oos"]["end"], TIME_FORMAT)
        if not (train_end < validation_start <= validation_end < development_start <= development_end):
            raise ValueError(f"source fold time roles overlap or are unordered: {fold['fold_id']}")
        if previous_development_end is not None and not previous_development_end < development_start:
            raise ValueError("development windows overlap or are unordered")
        previous_development_end = development_end
        folds.append(
            {
                "development_id": f"V2D{index:03d}",
                "source_fold_id": fold["fold_id"],
                "train_is": fold["train_is"],
                "validation_oos": fold["validation_oos"],
                "development_cv": fold["test_oos"],
            }
        )
    tail = source.get("tail_holdout_partial")
    if not isinstance(tail, dict):
        raise ValueError("V2SP0001 requires an explicit quarantined tail")
    tail_start = datetime.strptime(tail["start"], TIME_FORMAT)
    tail_end = datetime.strptime(tail["end"], TIME_FORMAT)
    if previous_development_end is None or not previous_development_end < tail_start <= tail_end:
        raise ValueError("tail must begin after all development windows")
    observed_last = str(source.get("observed", {}).get("last_time"))
    if tail["end"] != observed_last:
        raise ValueError("tail end must equal the observed dataset end")
    return {
        "schema": "axiom_rift_v2_split_set_v1",
        "split_set_id": "V2SP0001",
        "dataset_object_id": dataset_object_id,
        "dataset_sha256": dataset_sha256,
        "source_path": path.as_posix(),
        "source_sha256": expected_sha256,
        "folds": folds,
        "scout_anchor_ids": sorted(SCOUT_ANCHORS),
        "scout_anchor_selection": {
            "method": SCOUT_ANCHOR_METHOD,
            "rationale": SCOUT_ANCHOR_RATIONALE,
            "performance_inputs_used": False,
            "source_split_sha256": expected_sha256,
            "dataset_sha256": dataset_sha256,
        },
        "legacy_test_role": "development_cv",
        "tail": {
            **tail,
            "status": "quarantine_pending_access_audit",
            "claim_use_allowed": False,
            "raw_access_allowed": False,
        },
        "forward_holdout": {
            "start_after": observed_last,
            "status": "awaiting_future_data",
            "reveal_count": 0,
            "max_reveals": 1,
        },
        "claim_ceiling": "none",
    }


def sample_lifecycle_within_role(
    *,
    feature_context_start: datetime,
    decision_bar_open: datetime,
    label_end_bar_open: datetime | None,
    trade_end_bar_open: datetime | None,
    role_start: datetime,
    role_end: datetime,
) -> bool:
    """Check role containment while allowing causal feature warmup before it."""

    if role_end < role_start:
        raise ValueError("role end precedes role start")
    if feature_context_start > decision_bar_open:
        raise ValueError("feature context starts after the decision bar")
    if not role_start <= decision_bar_open <= role_end:
        return False
    for terminal_time in (label_end_bar_open, trade_end_bar_open):
        if terminal_time is None:
            continue
        if terminal_time < decision_bar_open:
            raise ValueError("label or trade lifecycle ends before the decision bar")
        if terminal_time > role_end:
            return False
    return True


def assert_split_access(
    stage: str,
    development_id: str,
    role: str,
    *,
    reveal_permit: bool = False,
    frozen_identity_bundle_sha256: str | None = None,
) -> None:
    if stage == "H":
        raise SplitAccessError("H stage may inspect metadata only")
    if role == "tail":
        raise SplitAccessError("quarantined tail raw access is disabled")
    if stage == "S" and (development_id not in SCOUT_ANCHORS or role not in {"train_is", "validation_oos", "development_cv"}):
        raise SplitAccessError("S stage is restricted to preregistered anchor development folds")
    if stage == "R" and (development_id not in ALL_DEVELOPMENT or role not in {"train_is", "validation_oos", "development_cv"}):
        raise SplitAccessError("R stage is restricted to all development folds")
    if stage == "P":
        if role == "development_cv" and development_id in ALL_DEVELOPMENT:
            return
        if role in {"limited_test_oos", "forward_holdout"} and reveal_permit and frozen_identity_bundle_sha256:
            return
        raise SplitAccessError("P holdout access requires a reveal permit and frozen identity bundle")
    if stage == "M":
        if role == "sealed_holdout_receipt" and development_id == "sealed":
            return
        raise SplitAccessError("M may read only a sealed holdout receipt")
    if stage not in {"S", "R"}:
        raise SplitAccessError(f"unknown stage: {stage}")
