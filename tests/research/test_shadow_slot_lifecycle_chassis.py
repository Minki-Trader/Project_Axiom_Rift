from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ControlledStudyChassis,
    validate_controlled_executable,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.shadow_slot_lifecycle_chassis import (
    ShadowSlotLifecycleConfiguration,
    shadow_slot_lifecycle_baseline,
    shadow_slot_lifecycle_configurations,
    shadow_slot_lifecycle_executable,
    simulate_shadow_slot_lifecycle,
)


class ShadowSlotLifecycleChassisTests(unittest.TestCase):
    def test_subject_changes_only_the_lifecycle_parameter(self) -> None:
        baseline = shadow_slot_lifecycle_baseline()
        subject = shadow_slot_lifecycle_executable(
            next(
                value for value in shadow_slot_lifecycle_configurations()
                if value.lifecycle_policy == "shadow_reserve_original_expiry"
            )
        )
        chassis = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(ResearchLayer.LIFECYCLE,),
            controlled_domains=(
                ResearchLayer.FEATURE, ResearchLayer.LABEL, ResearchLayer.MODEL,
                ResearchLayer.SELECTOR, ResearchLayer.TRADE, ResearchLayer.RISK,
                ResearchLayer.EXECUTION,
            ),
            architecture=ArchitectureChassisSpec.from_executable(baseline),
        )
        validate_controlled_executable(chassis.to_identity_payload(), subject)

    def test_shadow_reservation_suppresses_post_stop_reentry(self) -> None:
        times = pd.date_range("2025-01-01", periods=70, freq="5min", tz="UTC")
        opens = np.full(70, 100.0)
        opens[2:] = 98.0
        frame = pd.DataFrame({"time": times, "open": opens, "spread": np.ones(70)})
        score = np.ones(70)
        volatility = np.full(70, 0.001)
        run = np.arange(1, 71)
        kwargs = {
            "frame": frame, "score": score, "volatility": volatility,
            "run": run, "threshold": 0.5, "test_start": times[0],
            "test_end": times[-1], "fold_id": "fold-01",
            "regime_cutoffs": (0.0005, 0.002),
            "effective_spread": np.ones(70),
        }
        immediate = simulate_shadow_slot_lifecycle(
            configuration=ShadowSlotLifecycleConfiguration("immediate_reuse_control"),
            **kwargs,
        )
        shadow = simulate_shadow_slot_lifecycle(
            configuration=ShadowSlotLifecycleConfiguration("shadow_reserve_original_expiry"),
            **kwargs,
        )
        self.assertGreater(len(immediate.trades), len(shadow.trades))
        self.assertEqual(len(shadow.trades), 1)


if __name__ == "__main__":
    unittest.main()
