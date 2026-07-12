from __future__ import annotations

import unittest

from axiom_rift.research.cost_utility_objective_discovery import (
    cost_utility_objective_configurations,
    cost_utility_objective_executable,
)


class CostUtilityObjectiveDiscoveryTests(unittest.TestCase):
    def test_four_objective_and_direction_executables_are_unique(self) -> None:
        configurations = cost_utility_objective_configurations()
        identities = {cost_utility_objective_executable(value).identity for value in configurations}
        self.assertEqual(len(configurations), 4)
        self.assertEqual(len(identities), 4)

    def test_objective_is_only_varying_fitted_domain(self) -> None:
        configurations = cost_utility_objective_configurations()
        self.assertEqual({value.profile for value in configurations}, {"native_utility_weighted_loss", "unweighted_directional_loss_control"})
        self.assertEqual({value.signal_sign for value in configurations}, {-1, 1})
        protocols = {component.protocol for component in cost_utility_objective_executable(configurations[0]).components}
        self.assertIn("objective.native_utility_weighted_vs_unweighted.v1", protocols)
        self.assertIn("model.fixed_ridge_linear_capacity.v1", protocols)
        self.assertIn("label.fixed_first_passage_with_multiscale_features.v1", protocols)


if __name__ == "__main__":
    unittest.main()
