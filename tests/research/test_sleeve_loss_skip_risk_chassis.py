from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from axiom_rift.research.chassis import validate_controlled_executable
from axiom_rift.research.positive_direction_sleeve_chassis import (
    PositiveDirectionSleeveConfiguration,
    positive_direction_sleeve_executable,
)
from axiom_rift.research.sleeve_loss_skip_risk_chassis import (
    INTENT_CALENDAR_POLICY,
    SKIP_NEXT_AFTER_LOSS,
    UNRESTRICTED_CONTROL,
    SleeveLossSkipRiskConfiguration,
    simulate_sleeve_loss_skip_risk,
    sleeve_loss_skip_risk_controlled_chassis,
    sleeve_loss_skip_risk_executable,
)
from axiom_rift.research.sleeve_loss_skip_risk_trace import (
    preregistered_eligible_intent_rows,
)


def test_corrected_control_preserves_prior_components_under_new_calendar() -> None:
    prior = positive_direction_sleeve_executable(
        PositiveDirectionSleeveConfiguration("dual_positive_direction_slots")
    )
    control = sleeve_loss_skip_risk_executable(
        SleeveLossSkipRiskConfiguration(UNRESTRICTED_CONTROL)
    )
    assert control.identity != prior.identity
    assert control.component_identities == prior.component_identities
    assert control.parameter_values()["intent_calendar_policy"] == (
        INTENT_CALENDAR_POLICY
    )
    assert control.engine_contract.endswith(
        "+preregistered-eligible-intent-calendar-v2"
    )


def test_subject_changes_only_risk_and_portfolio_layers() -> None:
    baseline = sleeve_loss_skip_risk_executable(
        SleeveLossSkipRiskConfiguration(UNRESTRICTED_CONTROL)
    )
    subject = sleeve_loss_skip_risk_executable(
        SleeveLossSkipRiskConfiguration(SKIP_NEXT_AFTER_LOSS)
    )
    chassis = sleeve_loss_skip_risk_controlled_chassis()
    assert chassis.baseline_executable.identity == baseline.identity
    validate_controlled_executable(chassis.to_identity_payload(), subject)


def test_loss_skip_frees_slot_without_reading_skipped_outcome() -> None:
    count = 60
    time = pd.date_range("2026-01-01", periods=count, freq="5min")
    opens = np.full(count, 100.0)
    opens[11] = 101.0
    opens[23] = 100.0
    opens[25] = 100.0
    opens[37] = 102.0
    frame = pd.DataFrame(
        {
            "time": time,
            "open": opens,
            "spread": np.zeros(count),
        }
    )
    score = np.full((count, 2), np.nan)
    score[[10, 23, 24], 0] = 2.0
    volatility = np.ones(count)
    run = np.arange(1, count + 1)
    result = simulate_sleeve_loss_skip_risk(
        frame=frame,
        score=score,
        volatility=volatility,
        run=run,
        threshold=1.0,
        configuration=SleeveLossSkipRiskConfiguration(SKIP_NEXT_AFTER_LOSS),
        test_start=time[0],
        test_end=time[-1],
        fold_id="rw_001",
        regime_cutoffs=(0.5, 1.5),
        effective_spread=np.zeros(count),
    )
    assert list(result.trades["decision_time"]) == [time[10] + pd.Timedelta(minutes=5), time[24] + pd.Timedelta(minutes=5)]
    assert result.trades.iloc[0]["pnl"] < 0
    statuses = [row[-1] for row in result.intent_rows]
    assert statuses == ["executed", "risk_policy_skipped", "executed"]
    assert result.intent_rows[1][1] == time[23] + pd.Timedelta(minutes=5)
    assert result.intent_rows[2][1] == time[24] + pd.Timedelta(minutes=5)


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
