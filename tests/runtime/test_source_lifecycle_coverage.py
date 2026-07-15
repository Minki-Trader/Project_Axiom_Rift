from __future__ import annotations

import unittest

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.runtime.source_lifecycle_coverage import (
    SourceLifecycleCoverageError,
    derive_source_lifecycle_coverage,
    require_source_lifecycle_coverage_ids,
)


def executable(*, two_dependents: bool = True) -> ExecutableSpec:
    source_a = "source:" + "a" * 64
    source_b = "source:" + "b" * 64
    components = [
        ComponentSpec(
            display_name="source-a sleeve",
            protocol="feature.source_sleeve.v1",
            implementation="fixture.source_a",
            spec={"sleeve": "a"},
            semantic_dependencies=(source_a,),
        ),
        ComponentSpec(
            display_name="source-b sleeve",
            protocol="feature.source_sleeve.v1",
            implementation="fixture.source_b",
            spec={"sleeve": "b"},
            semantic_dependencies=(source_b,),
        ),
    ]
    if two_dependents:
        components.append(
            ComponentSpec(
                display_name="second source-a sleeve",
                protocol="selector.source_sleeve.v1",
                implementation="fixture.source_a_selector",
                spec={"sleeve": "a-secondary"},
                semantic_dependencies=(source_a,),
            )
        )
    components.append(
        ComponentSpec(
            display_name="shared lifecycle",
            protocol="lifecycle.position.v1",
            implementation="fixture.lifecycle",
            spec={"missing": "safe_exit"},
        )
    )
    return ExecutableSpec(
        display_name="multi-source fixture",
        components=tuple(components),
        parameters={"fixture": True},
        data_contract="data:fixture",
        split_contract="split:fixture",
        clock_contract="clock:fixture",
        cost_contract="cost:fixture",
        engine_contract="engine:fixture",
        source_contracts=(source_a, source_b),
    )


class SourceLifecycleCoverageTests(unittest.TestCase):
    def test_matrix_covers_every_source_dependent_component_and_case(self) -> None:
        rows = derive_source_lifecycle_coverage(executable().to_identity_payload())
        self.assertEqual(len(rows), 6)
        self.assertEqual(
            {row["materialization_case"] for row in rows},
            {"source_interruption", "stale_or_missing_input"},
        )
        self.assertEqual(
            {row["source_contract_id"] for row in rows},
            {"source:" + "a" * 64, "source:" + "b" * 64},
        )
        self.assertEqual(len({row["coverage_id"] for row in rows}), 6)
        self.assertEqual(len({row["lifecycle_surface_id"] for row in rows}), 1)
        for row in rows:
            self.assertEqual(row["independent_control_outcome"], "unchanged")
            self.assertEqual(row["unrelated_sleeve_outcome"], "unchanged")
            self.assertFalse(row["retain_baseline_pnl_for_missing_subject"])

    def test_planned_subset_is_canonical_and_case_bound(self) -> None:
        rows = derive_source_lifecycle_coverage(executable().to_identity_payload())
        selected = sorted(
            row["coverage_id"]
            for row in rows
            if row["source_contract_id"] == "source:" + "b" * 64
        )
        self.assertEqual(
            require_source_lifecycle_coverage_ids(
                selected,
                allowed_rows=rows,
                planned_materialization_cases=(
                    "source_interruption",
                    "stale_or_missing_input",
                ),
            ),
            tuple(selected),
        )
        with self.assertRaises(SourceLifecycleCoverageError):
            require_source_lifecycle_coverage_ids(
                selected[:1],
                allowed_rows=rows,
                planned_materialization_cases=(
                    "source_interruption",
                    "stale_or_missing_input",
                ),
            )

    def test_manifest_identity_tampering_is_rejected(self) -> None:
        manifest = executable().to_identity_payload()
        manifest["component_identities"][0] = "component:" + "f" * 64
        with self.assertRaises(SourceLifecycleCoverageError):
            derive_source_lifecycle_coverage(manifest)

    def test_forged_identity_and_source_free_credit_are_rejected(self) -> None:
        rows = derive_source_lifecycle_coverage(
            executable().to_identity_payload()
        )
        with self.assertRaises(SourceLifecycleCoverageError):
            require_source_lifecycle_coverage_ids(
                ["source-lifecycle-coverage:" + "f" * 64],
                allowed_rows=rows,
                planned_materialization_cases=("source_interruption",),
            )

        source_free = ExecutableSpec(
            display_name="source-free fixture",
            components=(
                ComponentSpec(
                    display_name="source-free component",
                    protocol="feature.source_free.v1",
                    implementation="fixture.source_free",
                    spec={"fixture": True},
                ),
            ),
            parameters={"fixture": True},
            data_contract="data:fixture",
            split_contract="split:fixture",
            clock_contract="clock:fixture",
            cost_contract="cost:fixture",
            engine_contract="engine:fixture",
        )
        source_free_rows = derive_source_lifecycle_coverage(
            source_free.to_identity_payload()
        )
        self.assertEqual(source_free_rows, ())
        self.assertEqual(
            require_source_lifecycle_coverage_ids(
                [],
                allowed_rows=source_free_rows,
                planned_materialization_cases=("source_interruption",),
            ),
            (),
        )
        with self.assertRaises(SourceLifecycleCoverageError):
            require_source_lifecycle_coverage_ids(
                ["source-lifecycle-coverage:" + "f" * 64],
                allowed_rows=source_free_rows,
                planned_materialization_cases=("source_interruption",),
            )


if __name__ == "__main__":
    unittest.main()
