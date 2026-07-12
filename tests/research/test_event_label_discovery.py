from __future__ import annotations

import unittest

from axiom_rift.research.event_label_discovery import (
    BARRIER_MULTIPLE_MILLI,
    event_label_configurations,
    event_label_executable,
    executable_configuration_map,
)


class EventLabelDiscoveryTests(unittest.TestCase):
    def test_four_exact_label_and_direction_executables_are_unique(self) -> None:
        configurations = event_label_configurations()
        executables = [event_label_executable(value) for value in configurations]
        self.assertEqual(len(configurations), 4)
        self.assertEqual(len({value.identity for value in executables}), 4)
        self.assertEqual(set(executable_configuration_map()), {x.identity for x in executables})

    def test_only_label_profile_and_direction_vary_on_fixed_chassis(self) -> None:
        configurations = event_label_configurations()
        profiles = {value.profile for value in configurations}
        self.assertEqual(
            profiles,
            {"first_passage_label_48", "terminal_return_label_control_48"},
        )
        self.assertEqual({value.signal_sign for value in configurations}, {-1, 1})
        self.assertEqual({value.holding_bars for value in configurations}, {48})
        self.assertEqual(BARRIER_MULTIPLE_MILLI, 750)
        protocols = {
            component.protocol
            for component in event_label_executable(configurations[0]).components
        }
        self.assertIn("label.path_event_vs_terminal_return.v1", protocols)
        self.assertIn("model.fold_train_ridge_linear.v1", protocols)
        self.assertIn("lifecycle.fixed_hold_no_overlap.v3", protocols)


if __name__ == "__main__":
    unittest.main()
