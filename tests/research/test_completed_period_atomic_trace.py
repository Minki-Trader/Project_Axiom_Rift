from __future__ import annotations

import unittest

from axiom_rift.research.completed_period_atomic_trace import (
    completed_period_proxy_execution_spec,
)
from axiom_rift.research.composite_router_replay import (
    composite_router_replay_components,
)
from axiom_rift.research.distribution_asymmetry_replay import (
    distribution_asymmetry_replay_components,
)
from axiom_rift.research.drawdown_state_discovery import drawdown_components
from axiom_rift.research.drawdown_state_replay import (
    drawdown_replay_components,
)
from axiom_rift.research.gap_recovery_discovery import gap_components
from axiom_rift.research.volatility_duration_discovery import (
    volatility_duration_components,
)
from axiom_rift.research.historical_family_binding import (
    historical_family_from_manifest,
)
from axiom_rift.research.historical_family_replay import (
    STU0051_HISTORICAL_FAMILY,
)
from axiom_rift.research.volatility_duration_fixed_hold import (
    volatility_duration_fixed_hold_components,
)


def current_volatility_duration_components():
    return volatility_duration_fixed_hold_components(
        historical_family_from_manifest(STU0051_HISTORICAL_FAMILY.manifest())
    )


class CompletedPeriodAtomicTraceTests(unittest.TestCase):
    def test_every_repaired_execution_component_names_the_actual_sources(
        self,
    ) -> None:
        factories = (
            drawdown_components,
            gap_components,
            volatility_duration_components,
            drawdown_replay_components,
            current_volatility_duration_components,
            distribution_asymmetry_replay_components,
            composite_router_replay_components,
        )
        for factory in factories:
            with self.subTest(factory=factory.__name__):
                execution = next(
                    component
                    for component in factory()
                    if component.protocol.startswith("execution.")
                )
                spec = execution.specification()
                self.assertIsInstance(spec, dict)
                assert isinstance(spec, dict)
                self.assertEqual(
                    execution.protocol,
                    "execution.fpmarkets_completed_period_spread_proxy.v2",
                )
                self.assertIn("completed-period", execution.display_name)
                self.assertNotIn("lagged-spread", execution.display_name)
                self.assertEqual(
                    spec["decision_spread_source"],
                    "decision_bar_index",
                )
                self.assertEqual(
                    spec["entry_cost_source"],
                    "entry_bar_index_minus_1_equals_decision_bar_index",
                )
                self.assertEqual(
                    spec["exit_cost_source"],
                    "exit_bar_index_minus_1",
                )
                self.assertEqual(
                    spec["information_completion"],
                    "source_bar_open_plus_5m",
                )
                self.assertIn("strict_prior", spec["zero_spread_repair"])
                self.assertEqual(
                    spec["unknown_entry_action"], "cancel_before_open"
                )

    def test_execution_spec_is_fresh_and_rejects_non_ascii_policy(self) -> None:
        first = completed_period_proxy_execution_spec(
            repair_policy="strict_prior_positive_else_unknown"
        )
        second = completed_period_proxy_execution_spec(
            repair_policy="strict_prior_positive_else_unknown"
        )
        first["point"] = "forged"
        self.assertEqual(second["point"], "0.01")
        with self.assertRaisesRegex(ValueError, "non-empty ASCII"):
            completed_period_proxy_execution_spec(repair_policy="invalid-\u2603")


if __name__ == "__main__":
    unittest.main()
