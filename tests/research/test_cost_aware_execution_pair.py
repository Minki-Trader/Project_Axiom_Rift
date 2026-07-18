from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest

from axiom_rift.research.cost_aware_execution_pair import (
    COST_AWARE_EXECUTION_PAIR_CONTEXT_PARAMETER,
    COST_AWARE_EXECUTION_PAIR_ORIGINAL_END_PARAMETER,
    CostAwareExecutionPairError,
    cost_aware_execution_pair_components,
    cost_aware_execution_pair_configurations,
    cost_aware_execution_pair_controlled_chassis,
    cost_aware_execution_pair_executable,
    cost_aware_execution_pair_executable_map,
    cost_aware_execution_pair_historical_context,
    cost_aware_execution_pair_protocol_definition,
)
from axiom_rift.research.cost_aware_execution_protocol import (
    COST_AWARE_EXECUTION_CONTROL_HISTORICAL_EXECUTABLE_ID,
    COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT,
    COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyReplayContext,
    HistoricalFamilySpec,
    HistoricalMemberSpec,
)
from axiom_rift.research.historical_family_stu0070 import (
    STU0070_HISTORICAL_FAMILY,
)
from axiom_rift.research.governance import ResearchLayer


_FAMILY_AUTHORITY_ID = (
    "historical-family-authority:"
    "3ddff77adc305d07d2ee536994527f8bd40dc12e9ea8ef9615797e95fd256e29"
)
_OBLIGATION_ID = (
    "historical-replay-obligation:"
    "ab4d0fcd6d5f88756fbed17f32dbf2831217a7c158d043b7f85f3c69b149b63e"
)


def _context() -> HistoricalFamilyReplayContext:
    return HistoricalFamilyReplayContext(
        family_authority_id=_FAMILY_AUTHORITY_ID,
        replay_obligation_id=_OBLIGATION_ID,
        family=STU0070_HISTORICAL_FAMILY,
        prior_global_exposure_count=581,
        original_family_end_global_exposure_count=(
            COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
        ),
    )


class CostAwareExecutionPairTests(unittest.TestCase):
    def test_exact_writer_family_builds_new_ordered_pair(self) -> None:
        configurations = cost_aware_execution_pair_configurations(
            STU0070_HISTORICAL_FAMILY
        )
        self.assertEqual(
            tuple(value.execution_policy for value in configurations),
            ("unconditional_next_open", "causal_spread_abstention"),
        )
        self.assertEqual(
            tuple(
                value.historical_reference_executable_id
                for value in configurations
            ),
            (
                COST_AWARE_EXECUTION_CONTROL_HISTORICAL_EXECUTABLE_ID,
                COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID,
            ),
        )
        executables = cost_aware_execution_pair_executable_map(
            historical_family=STU0070_HISTORICAL_FAMILY,
            historical_context_prior_global_exposure_count=581,
            original_family_end_global_exposure_count=(
                COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
            ),
        )
        self.assertEqual(len(executables), 2)
        self.assertTrue(all(value.startswith("executable:") for value in executables))
        for executable_id, configuration in executables.items():
            # Rebuilding is deterministic and is not another trial.
            executable = cost_aware_execution_pair_executable(
                configuration,
                historical_family=STU0070_HISTORICAL_FAMILY,
                historical_context_prior_global_exposure_count=581,
                original_family_end_global_exposure_count=(
                    COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
                ),
            )
            self.assertEqual(executable.identity, executable_id)
            self.assertNotIn("bonferroni_530", executable.engine_contract)
            self.assertIn("d04_family_1:e01_family_2", executable.engine_contract)
            self.assertEqual(
                executable.parameter_values()[
                    COST_AWARE_EXECUTION_PAIR_CONTEXT_PARAMETER
                ],
                581,
            )
            self.assertEqual(
                executable.parameter_values()[
                    COST_AWARE_EXECUTION_PAIR_ORIGINAL_END_PARAMETER
                ],
                COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT,
            )

    def test_protocol_definition_uses_new_pair_in_historical_order(self) -> None:
        definition = cost_aware_execution_pair_protocol_definition(_context())
        by_id = cost_aware_execution_pair_executable_map(
            historical_family=STU0070_HISTORICAL_FAMILY,
            historical_context_prior_global_exposure_count=581,
            original_family_end_global_exposure_count=(
                COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
            ),
        )
        expected = tuple(
            executable_id
            for executable_id, configuration in by_id.items()
            if configuration.execution_policy == "unconditional_next_open"
        ) + tuple(
            executable_id
            for executable_id, configuration in by_id.items()
            if configuration.execution_policy == "causal_spread_abstention"
        )
        self.assertEqual(definition.prospective_executable_ids, expected)
        self.assertEqual(
            tuple(item.role for item in definition.member_bindings),
            ("control", "target"),
        )

    def test_historical_context_is_explicitly_non_adjusting(self) -> None:
        value = cost_aware_execution_pair_historical_context(
            _context()
        ).manifest()
        self.assertEqual(
            value["prior_global_exposure_count"],
            581,
        )
        self.assertEqual(value["context_id"], _FAMILY_AUTHORITY_ID)
        self.assertEqual(
            value["adjustment_authority"],
            "context_only_never_adjustment_factor",
        )
        self.assertEqual(
            set(value),
            {
                "adjustment_authority",
                "context_id",
                "prior_global_exposure_count",
            },
        )

    def test_execution_component_seals_no_read_and_strict_prior_semantics(self) -> None:
        execution = next(
            item
            for item in cost_aware_execution_pair_components(
                STU0070_HISTORICAL_FAMILY
            )
            if item.protocol.startswith("execution.causal_")
        )
        specification = execution.specification()
        self.assertEqual(
            specification["read_mask"],
            "null_not_read_false_read_but_unavailable",
        )
        self.assertIn("strict_prior", specification["spread_gate_reference"])
        self.assertTrue(
            specification["spread_zero_repair"].endswith("min_24")
        )
        self.assertEqual(
            specification["cost_proxy_sources"],
            {"entry": "entry_index_minus_1", "exit": "exit_index_minus_1"},
        )

    def test_controlled_chassis_changes_execution_inside_replay_synthesis(self) -> None:
        chassis = cost_aware_execution_pair_controlled_chassis(
            historical_family=STU0070_HISTORICAL_FAMILY,
            historical_context_prior_global_exposure_count=581,
            original_family_end_global_exposure_count=(
                COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
            ),
        )
        self.assertEqual(
            chassis.changed_domains,
            (ResearchLayer.EXECUTION, ResearchLayer.SYNTHESIS),
        )

    def test_mutated_historical_parameter_is_rejected(self) -> None:
        first = STU0070_HISTORICAL_FAMILY.members[0]
        parameters = first.parameter_values()
        parameters["spread_reference_bars"] = 144
        mutated = HistoricalFamilySpec(
            original_study_id=STU0070_HISTORICAL_FAMILY.original_study_id,
            original_batch_id=STU0070_HISTORICAL_FAMILY.original_batch_id,
            target_historical_executable_id=(
                STU0070_HISTORICAL_FAMILY.target_historical_executable_id
            ),
            members=(
                HistoricalMemberSpec(
                    ordinal=first.ordinal,
                    configuration_id=first.configuration_id,
                    historical_reference_executable_id=(
                        first.historical_reference_executable_id
                    ),
                    parameters=parameters,
                ),
                STU0070_HISTORICAL_FAMILY.members[1],
            ),
            controls=STU0070_HISTORICAL_FAMILY.controls,
        )
        with self.assertRaises(CostAwareExecutionPairError):
            cost_aware_execution_pair_configurations(mutated)

    def test_context_must_bind_historical_family_end_526(self) -> None:
        with self.assertRaises(CostAwareExecutionPairError):
            cost_aware_execution_pair_protocol_definition(
                replace(
                    _context(),
                    original_family_end_global_exposure_count=(
                        COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
                        - 1
                    ),
                )
            )

    def test_current_prior_exposure_is_bound_into_executable_identity(self) -> None:
        first = cost_aware_execution_pair_configurations(
            STU0070_HISTORICAL_FAMILY
        )[0]
        common = {
            "configuration": first,
            "historical_family": STU0070_HISTORICAL_FAMILY,
            "original_family_end_global_exposure_count": (
                COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
            ),
        }
        earlier = cost_aware_execution_pair_executable(
            historical_context_prior_global_exposure_count=581,
            **common,
        )
        later = cost_aware_execution_pair_executable(
            historical_context_prior_global_exposure_count=582,
            **common,
        )
        self.assertNotEqual(earlier.identity, later.identity)

    def test_builder_does_not_import_legacy_discovery_runner(self) -> None:
        source = Path(
            "src/axiom_rift/research/cost_aware_execution_pair.py"
        ).read_text(encoding="ascii")
        self.assertNotIn("cost_aware_execution_discovery import", source)
        self.assertNotIn("SELECTION_TOTAL_EXPOSURES", source)


if __name__ == "__main__":
    unittest.main()
