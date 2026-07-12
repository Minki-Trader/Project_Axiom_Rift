from __future__ import annotations

import unittest

import numpy as np

from axiom_rift.research.complementary_sleeve_discovery import (
    _combine_sleeves,
    complementary_sleeve_configurations,
    complementary_sleeve_executable,
    executable_configuration_map,
)


class ComplementarySleeveDiscoveryTests(unittest.TestCase):
    def test_four_portfolio_and_direction_executables_are_unique(self) -> None:
        configurations = complementary_sleeve_configurations()
        executables = [
            complementary_sleeve_executable(value) for value in configurations
        ]
        self.assertEqual(len(configurations), 4)
        self.assertEqual(len({value.identity for value in executables}), 4)
        self.assertEqual(
            set(executable_configuration_map()),
            {value.identity for value in executables},
        )

    def test_dual_sleeve_agreement_adds_and_opposition_cancels(self) -> None:
        first = np.array([2.0, 2.0, 0.2, -2.0])
        terminal = np.array([-2.0, 2.0, -2.0, 2.0])
        dual = _combine_sleeves(first, terminal, 1.0, 1.0, "dual_label_net_exposure")
        single = _combine_sleeves(
            first, terminal, 1.0, 1.0, "single_event_label_control"
        )
        np.testing.assert_array_equal(dual, np.array([4.0, 0.0, 2.0, -4.0]))
        np.testing.assert_array_equal(single, np.array([2.0, 2.0, 0.0, -2.0]))

    def test_portfolio_and_risk_protocols_are_explicit(self) -> None:
        executable = complementary_sleeve_executable(
            complementary_sleeve_configurations()[0]
        )
        protocols = {component.protocol for component in executable.components}
        self.assertIn("portfolio.dual_label_sleeve_netting.v1", protocols)
        self.assertIn("risk.net_exposure_cap_one_lot.v1", protocols)


if __name__ == "__main__":
    unittest.main()
