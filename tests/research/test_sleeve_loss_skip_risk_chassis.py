from __future__ import annotations

import numpy as np
import pandas as pd

from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
    ResearchLayer,
    validate_controlled_executable,
)
from axiom_rift.research.positive_direction_sleeve_chassis import (
    PositiveDirectionSleeveConfiguration,
    positive_direction_sleeve_executable,
)
from axiom_rift.research.sleeve_loss_skip_risk_chassis import (
    SKIP_NEXT_AFTER_LOSS,
    UNRESTRICTED_CONTROL,
    SleeveLossSkipRiskConfiguration,
    simulate_sleeve_loss_skip_risk,
    sleeve_loss_skip_risk_executable,
)


def test_control_is_exact_prior_dual_positive_executable() -> None:
    prior = positive_direction_sleeve_executable(
        PositiveDirectionSleeveConfiguration("dual_positive_direction_slots")
    )
    control = sleeve_loss_skip_risk_executable(
        SleeveLossSkipRiskConfiguration(UNRESTRICTED_CONTROL)
    )
    assert control.identity == prior.identity


def test_subject_changes_only_risk_and_portfolio_layers() -> None:
    baseline = sleeve_loss_skip_risk_executable(
        SleeveLossSkipRiskConfiguration(UNRESTRICTED_CONTROL)
    )
    subject = sleeve_loss_skip_risk_executable(
        SleeveLossSkipRiskConfiguration(SKIP_NEXT_AFTER_LOSS)
    )
    chassis = ControlledStudyChassis(
        baseline_executable=baseline,
        changed_domains=(ResearchLayer.PORTFOLIO, ResearchLayer.RISK),
        controlled_domains=(
            ResearchLayer.CALIBRATION,
            ResearchLayer.EXECUTION,
            ResearchLayer.FEATURE,
            ResearchLayer.LABEL,
            ResearchLayer.LIFECYCLE,
            ResearchLayer.MODEL,
            ResearchLayer.REGIME,
            ResearchLayer.SELECTOR,
            ResearchLayer.SYNTHESIS,
            ResearchLayer.TRADE,
        ),
        architecture=ArchitectureChassisSpec.from_executable(baseline),
    )
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
