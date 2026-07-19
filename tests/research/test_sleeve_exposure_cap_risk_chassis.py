from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from axiom_rift.research.chassis import validate_controlled_executable
from axiom_rift.research.sleeve_exposure_cap_risk_chassis import (
    CAP_ONE_GROSS_POSITION,
    UNRESTRICTED_CONTROL,
    SleeveExposureCapRiskConfiguration,
    simulate_sleeve_exposure_cap_risk,
    sleeve_exposure_cap_risk_controlled_chassis,
    sleeve_exposure_cap_risk_executable,
)
from axiom_rift.research.sleeve_loss_skip_risk_chassis import (
    sleeve_loss_skip_risk_baseline,
)
from axiom_rift.research.sleeve_exposure_cap_risk_trace import (
    preregistered_eligible_intent_rows,
)


def test_control_is_exact_stu0123_unrestricted_executable() -> None:
    prior = sleeve_loss_skip_risk_baseline()
    control = sleeve_exposure_cap_risk_executable(
        SleeveExposureCapRiskConfiguration(UNRESTRICTED_CONTROL)
    )
    assert control.identity == prior.identity
    assert control.to_identity_payload() == prior.to_identity_payload()


def test_subject_changes_only_the_risk_layer() -> None:
    baseline = sleeve_exposure_cap_risk_executable(
        SleeveExposureCapRiskConfiguration(UNRESTRICTED_CONTROL)
    )
    subject = sleeve_exposure_cap_risk_executable(
        SleeveExposureCapRiskConfiguration(CAP_ONE_GROSS_POSITION)
    )
    chassis = sleeve_exposure_cap_risk_controlled_chassis()
    assert chassis.baseline_executable.identity == baseline.identity
    validate_controlled_executable(chassis.to_identity_payload(), subject)


def test_cap_blocks_overlap_without_consuming_the_blocked_sleeve() -> None:
    count = 40
    time = pd.date_range("2026-01-01", periods=count, freq="5min")
    opens = np.full(count, 100.0)
    frame = pd.DataFrame(
        {
            "time": time,
            "open": opens,
            "spread": np.zeros(count),
        }
    )
    score = np.full((count, 2), np.nan)
    score[2, 0] = 2.0
    score[[3, 15], 1] = 2.0
    volatility = np.ones(count)
    run = np.arange(1, count + 1)
    result = simulate_sleeve_exposure_cap_risk(
        frame=frame,
        score=score,
        volatility=volatility,
        run=run,
        threshold=1.0,
        configuration=SleeveExposureCapRiskConfiguration(CAP_ONE_GROSS_POSITION),
        test_start=time[0],
        test_end=time[-1],
        fold_id="rw_001",
        regime_cutoffs=(0.5, 1.5),
        effective_spread=np.zeros(count),
    )
    assert list(result.trades["decision_time"]) == [
        time[2] + pd.Timedelta(minutes=5),
        time[15] + pd.Timedelta(minutes=5),
    ]
    assert list(result.trades["slot"]) == ["regime_router", "target_direction"]
    statuses = [row[-1] for row in result.intent_rows]
    assert statuses == ["executed", "gross_exposure_cap_blocked", "executed"]
    assert result.intent_rows[1][1] == time[3] + pd.Timedelta(minutes=5)
    assert result.intent_rows[2][1] == time[15] + pd.Timedelta(minutes=5)


def test_trace_drops_only_noneligible_gap_diagnostics() -> None:
    eligible = ("2026-01-05",)
    weekend_gap = (
        "regime_router",
        pd.Timestamp("2026-01-03T00:00:00"),
        pd.Timestamp("2026-01-05T00:00:00"),
        pd.Timestamp("2026-01-05T01:00:00"),
        1,
        "gap_excluded",
    )
    eligible_gap = (
        "regime_router",
        pd.Timestamp("2026-01-05T00:05:00"),
        pd.Timestamp("2026-01-05T00:10:00"),
        pd.Timestamp("2026-01-05T01:10:00"),
        1,
        "gap_excluded",
    )
    assert preregistered_eligible_intent_rows(
        (weekend_gap, eligible_gap),
        eligible_dates=eligible,
    ) == (eligible_gap,)
    invalid_executed = (*weekend_gap[:-1], "executed")
    with pytest.raises(ValueError, match="non-gap intent"):
        preregistered_eligible_intent_rows(
            (invalid_executed,),
            eligible_dates=eligible,
        )
