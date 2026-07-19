from __future__ import annotations

import unittest

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ChassisIdentityError,
    prospective_architecture_family_identity,
    prospective_architecture_family_identity_from_chassis,
    prospective_architecture_payload,
    prospective_architecture_payload_from_chassis,
)
from axiom_rift.research.positive_direction_sleeve_chassis import (
    PositiveDirectionSleeveConfiguration,
    positive_direction_sleeve_executable,
)
from axiom_rift.research.sleeve_loss_skip_risk_chassis import (
    UNRESTRICTED_CONTROL,
    SleeveLossSkipRiskConfiguration,
    sleeve_loss_skip_risk_executable,
)


def _stu_0122_executable() -> ExecutableSpec:
    return positive_direction_sleeve_executable(
        PositiveDirectionSleeveConfiguration("dual_positive_direction_slots")
    )


def _clone(
    baseline: ExecutableSpec,
    *,
    components: tuple[ComponentSpec, ...] | None = None,
    parameters: object | None = None,
    clock_contract: str | None = None,
    cost_contract: str | None = None,
    engine_contract: str | None = None,
) -> ExecutableSpec:
    return ExecutableSpec(
        display_name="semantic architecture variant",
        components=baseline.components if components is None else components,
        parameters=(
            baseline.parameter_values() if parameters is None else parameters
        ),
        data_contract=baseline.data_contract,
        split_contract=baseline.split_contract,
        clock_contract=baseline.clock_contract if clock_contract is None else clock_contract,
        cost_contract=baseline.cost_contract if cost_contract is None else cost_contract,
        engine_contract=(
            baseline.engine_contract if engine_contract is None else engine_contract
        ),
        source_contracts=baseline.source_contracts,
    )


class ProspectiveSemanticArchitectureFamilyTests(unittest.TestCase):
    def test_stu_0122_0123_engine_suffix_keeps_one_semantic_family(self) -> None:
        stu_0122 = _stu_0122_executable()
        stu_0123 = sleeve_loss_skip_risk_executable(
            SleeveLossSkipRiskConfiguration(UNRESTRICTED_CONTROL)
        )

        legacy_0122 = ArchitectureChassisSpec.from_executable(stu_0122)
        legacy_0123 = ArchitectureChassisSpec.from_executable(stu_0123)
        self.assertEqual(stu_0122.component_identities, stu_0123.component_identities)
        self.assertNotEqual(legacy_0122.identity, legacy_0123.identity)
        self.assertEqual(
            legacy_0122.to_identity_payload()["schema"],
            "architecture_chassis.v2",
        )
        self.assertEqual(
            prospective_architecture_family_identity(stu_0122),
            prospective_architecture_family_identity(stu_0123),
        )
        self.assertEqual(
            prospective_architecture_payload(stu_0122),
            prospective_architecture_payload_from_chassis(legacy_0122),
        )
        self.assertEqual(
            prospective_architecture_family_identity(stu_0122),
            prospective_architecture_family_identity_from_chassis(legacy_0122),
        )

        v2_only = ArchitectureChassisSpec(
            label=legacy_0122.label,
            decision=legacy_0122.decision,
            entry=legacy_0122.entry,
            lifecycle=legacy_0122.lifecycle,
            execution=legacy_0122.execution,
            portfolio=legacy_0122.portfolio,
        )
        self.assertEqual(v2_only.identity, legacy_0122.identity)
        self.assertEqual(
            v2_only.to_identity_payload(),
            legacy_0122.to_identity_payload(),
        )
        with self.assertRaisesRegex(
            ChassisIdentityError,
            "stored v2 architecture lacks prospective Component manifests",
        ):
            prospective_architecture_payload_from_chassis(v2_only)

    def test_bookkeeping_drift_does_not_split_semantic_family(self) -> None:
        baseline = _stu_0122_executable()
        old_portfolio = next(
            component
            for component in baseline.components
            if component.protocol.startswith("portfolio.")
        )
        new_spec = old_portfolio.specification()
        assert isinstance(new_spec, dict)
        new_spec.update({"artifact_hash": "f" * 64, "random_seed": 991})
        new_portfolio = ComponentSpec(
            display_name="portfolio release refactor",
            protocol=old_portfolio.protocol.rsplit(".v", 1)[0] + ".v99",
            implementation="fixture.portfolio@sha256:" + "e" * 64,
            spec=new_spec,
            semantic_dependencies=old_portfolio.semantic_dependencies,
        )
        parameters = baseline.parameter_values()
        assert isinstance(parameters, dict)
        parameters["selector_quantile_bp"] = 8500
        variant = _clone(
            baseline,
            components=tuple(
                new_portfolio if component is old_portfolio else component
                for component in baseline.components
            ),
            parameters=parameters,
            clock_contract=baseline.clock_contract.rsplit("_v", 1)[0] + "_v99",
            cost_contract=baseline.cost_contract.rsplit("_v", 1)[0] + "_v99",
            engine_contract=(
                baseline.engine_contract
                .replace("positive_direction_sleeves_v1", "positive_direction_sleeves_v99")
                .rsplit(":seed_", 1)[0]
                + ":seed_991"
            ),
        )

        self.assertNotEqual(
            ArchitectureChassisSpec.from_executable(baseline).identity,
            ArchitectureChassisSpec.from_executable(variant).identity,
        )
        self.assertEqual(
            prospective_architecture_family_identity(baseline),
            prospective_architecture_family_identity(variant),
        )

    def test_role_topology_causal_and_runtime_category_stay_distinct(self) -> None:
        baseline = _stu_0122_executable()
        model = next(
            component
            for component in baseline.components
            if component.protocol.startswith("model.")
        )
        extra_calibration = ComponentSpec(
            display_name="second decision node",
            protocol="calibration.isotonic_probability.v1",
            implementation="fixture.calibration@sha256:" + "d" * 64,
            spec={"fit_role": "train_only"},
            semantic_dependencies=(model.identity,),
        )
        variants = (
            _clone(baseline, components=(*baseline.components, extra_calibration)),
            _clone(
                baseline,
                clock_contract="clock:fpmarkets_m5_bar_close_completed_plus_5m_v5",
            ),
            _clone(
                baseline,
                engine_contract="engine:positive_direction_sleeves_v9:mt5build5833",
            ),
        )
        family = prospective_architecture_family_identity(baseline)
        self.assertTrue(
            all(
                prospective_architecture_family_identity(variant) != family
                for variant in variants
            )
        )
        payload = prospective_architecture_payload(baseline)
        execution = payload["roles"]["execution"]
        self.assertEqual(
            execution["boundary_categories"]["engine_contract"][
                "runtime_categories"
            ],
            ["python"],
        )


if __name__ == "__main__":
    unittest.main()
