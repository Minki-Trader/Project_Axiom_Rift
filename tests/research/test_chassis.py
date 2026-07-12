from __future__ import annotations

import unittest

from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ChassisIdentityError,
    ComponentParityDimension,
    ComponentParityEvidence,
    ControlledStudyChassis,
    combine_control_payloads,
    component_semantic_surface_identity,
    executable_semantic_surface_identity,
    require_combinable_chassis,
    validate_controlled_executable,
)
from axiom_rift.research.governance import ResearchLayer


DOMAINS = (
    "feature",
    "label",
    "model",
    "calibration",
    "selector",
    "trade",
    "lifecycle",
    "risk",
    "execution",
)
PARITY_DIMENSIONS = tuple(ComponentParityDimension)


def component(
    domain: str,
    *,
    implementation_tag: str = "baseline",
    protocol_tag: str = "v1",
    semantic_dependencies: tuple[str, ...] = (),
) -> ComponentSpec:
    return ComponentSpec(
        display_name=f"{domain} fixture",
        protocol=f"{domain}.fixture.{protocol_tag}",
        implementation=f"fixture.{domain}.{implementation_tag}",
        spec={
            "parameter_fields": [f"{domain}_profile"],
            "semantic_role": domain,
        },
        semantic_dependencies=semantic_dependencies,
    )


def executable(
    components: tuple[ComponentSpec, ...],
    *,
    parameter_overrides: dict[str, int] | None = None,
) -> ExecutableSpec:
    parameters = {f"{domain}_profile": 0 for domain in DOMAINS}
    parameters.update(parameter_overrides or {})
    return ExecutableSpec(
        display_name="controlled chassis fixture",
        components=components,
        parameters=parameters,
        data_contract="data:fixture",
        split_contract="split:fixture",
        clock_contract="clock:fixture",
        cost_contract="cost:fixture",
        engine_contract="engine:fixture",
    )


def baseline_executable(*, model_tag: str = "baseline") -> ExecutableSpec:
    feature = component("feature")
    label = component("label")
    model = component(
        "model",
        implementation_tag=model_tag,
        semantic_dependencies=(feature.identity, label.identity),
    )
    calibration = component("calibration", semantic_dependencies=("role:model",))
    selector = component(
        "selector", semantic_dependencies=("role:calibration",)
    )
    trade = component("trade", semantic_dependencies=("role:selector",))
    lifecycle = component("lifecycle", semantic_dependencies=("role:trade",))
    risk = component("risk", semantic_dependencies=("role:lifecycle",))
    execution_component = component(
        "execution", semantic_dependencies=("role:risk",)
    )
    return executable(
        (
            feature,
            label,
            model,
            calibration,
            selector,
            trade,
            lifecycle,
            risk,
            execution_component,
        )
    )


def architecture(value: ExecutableSpec) -> ArchitectureChassisSpec:
    return ArchitectureChassisSpec.from_executable(value)


def controlled_domains() -> tuple[ResearchLayer, ...]:
    return tuple(
        ResearchLayer(domain)
        for domain in DOMAINS
        if domain != ResearchLayer.CALIBRATION.value
    )


class ControlledStudyChassisTests(unittest.TestCase):
    def test_changed_component_must_be_consumed_by_current_composition(self) -> None:
        baseline = baseline_executable()
        old_calibration = next(
            item
            for item in baseline.components
            if item.protocol.startswith("calibration.")
        )
        old_selector = next(
            item
            for item in baseline.components
            if item.protocol.startswith("selector.")
        )
        exact_selector = component(
            "selector",
            semantic_dependencies=(old_calibration.identity,),
        )
        baseline = executable(
            tuple(
                exact_selector if item is old_selector else item
                for item in baseline.components
            )
        )
        new_calibration = component(
            "calibration",
            implementation_tag="unused-addition",
            semantic_dependencies=old_calibration.semantic_dependencies,
        )
        candidate = executable((*baseline.components, new_calibration))
        chassis = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(ResearchLayer.CALIBRATION,),
            controlled_domains=controlled_domains(),
            architecture=architecture(baseline),
        )

        with self.assertRaisesRegex(
            ChassisIdentityError, "requires one explicit final terminal"
        ):
            validate_controlled_executable(chassis.to_identity_payload(), candidate)

    def test_changed_domain_cannot_claim_parity_or_many_to_one_control(self) -> None:
        baseline = baseline_executable()
        old_calibration = next(
            item
            for item in baseline.components
            if item.protocol.startswith("calibration.")
        )
        refactor = component(
            "calibration",
            implementation_tag="equivalent-refactor",
            semantic_dependencies=old_calibration.semantic_dependencies,
        )
        parity = ComponentParityEvidence(
            canonical_component=old_calibration,
            equivalent_component=refactor,
            dimensions=PARITY_DIMENSIONS,
            parity_manifest_hash="d" * 64,
            completion_record_id="4" * 64,
        )
        with self.assertRaisesRegex(ChassisIdentityError, "controlled domain"):
            ControlledStudyChassis(
                baseline_executable=baseline,
                changed_domains=(ResearchLayer.CALIBRATION,),
                controlled_domains=controlled_domains(),
                architecture=architecture(baseline),
                equivalences=(parity,),
            )

        old_execution = next(
            item
            for item in baseline.components
            if item.protocol.startswith("execution.")
        )
        first = component(
            "execution",
            implementation_tag="equivalent-first",
            semantic_dependencies=old_execution.semantic_dependencies,
        )
        second = component(
            "execution",
            implementation_tag="equivalent-second",
            semantic_dependencies=old_execution.semantic_dependencies,
        )
        first_parity = ComponentParityEvidence(
            canonical_component=old_execution,
            equivalent_component=first,
            dimensions=PARITY_DIMENSIONS,
            parity_manifest_hash="e" * 64,
            completion_record_id="5" * 64,
        )
        second_parity = ComponentParityEvidence(
            canonical_component=old_execution,
            equivalent_component=second,
            dimensions=PARITY_DIMENSIONS,
            parity_manifest_hash="f" * 64,
            completion_record_id="6" * 64,
        )
        with self.assertRaisesRegex(ChassisIdentityError, "multiple equivalent"):
            ControlledStudyChassis(
                baseline_executable=baseline,
                changed_domains=(ResearchLayer.CALIBRATION,),
                controlled_domains=controlled_domains(),
                architecture=architecture(baseline),
                equivalences=(first_parity, second_parity),
            )

    def test_architecture_role_and_executable_surfaces_ignore_protocol_labels(self) -> None:
        baseline = baseline_executable()
        model = next(
            item for item in baseline.components if item.protocol.startswith("model.")
        )
        decision_relabel = ComponentSpec(
            display_name="decision role relabel",
            protocol="selector.fixture.v9",
            implementation=model.implementation,
            spec=model.specification(),
            semantic_dependencies=model.semantic_dependencies,
        )
        relabeled = executable(
            tuple(decision_relabel if item is model else item for item in baseline.components)
        )
        self.assertEqual(architecture(baseline).identity, architecture(relabeled).identity)

        trade = next(
            item for item in baseline.components if item.protocol.startswith("trade.")
        )
        cross_role_alias = ComponentSpec(
            display_name="trade semantics relabeled as risk",
            protocol="risk.fixture.v8",
            implementation=trade.implementation,
            spec=trade.specification(),
            semantic_dependencies=trade.semantic_dependencies,
        )
        cross_role_candidate = executable(
            (*baseline.components, cross_role_alias)
        )
        cross_role_chassis = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(ResearchLayer.RISK,),
            controlled_domains=tuple(
                ResearchLayer(domain) for domain in DOMAINS if domain != "risk"
            ),
            architecture=architecture(baseline),
        )
        with self.assertRaisesRegex(ChassisIdentityError, "protocol-domain-only"):
            validate_controlled_executable(
                cross_role_chassis.to_identity_payload(), cross_role_candidate
            )
        protocol_alias = ComponentSpec(
            display_name="trade protocol alias",
            protocol="trade.fixture.v99",
            implementation=trade.implementation,
            spec=trade.specification(),
            semantic_dependencies=trade.semantic_dependencies,
        )
        aliased = executable(
            tuple(protocol_alias if item is trade else item for item in baseline.components)
        )
        self.assertNotEqual(baseline.identity, aliased.identity)
        self.assertEqual(
            executable_semantic_surface_identity(baseline),
            executable_semantic_surface_identity(aliased),
        )
        feature = next(
            item
            for item in baseline.components
            if item.protocol.startswith("feature.")
        )
        label = next(
            item
            for item in baseline.components
            if item.protocol.startswith("label.")
        )
        model = next(
            item
            for item in baseline.components
            if item.protocol.startswith("model.")
        )
        feature_alias = ComponentSpec(
            display_name="feature protocol alias",
            protocol="feature.fixture.v77",
            implementation=feature.implementation,
            spec=feature.specification(),
            semantic_dependencies=feature.semantic_dependencies,
        )
        rebound_model = ComponentSpec(
            display_name="model rebound to alias",
            protocol=model.protocol,
            implementation=model.implementation,
            spec=model.specification(),
            semantic_dependencies=(feature_alias.identity, label.identity),
        )
        recursively_aliased = executable(
            tuple(
                feature_alias
                if item is feature
                else rebound_model
                if item is model
                else item
                for item in baseline.components
            )
        )
        self.assertNotEqual(baseline.identity, recursively_aliased.identity)
        self.assertEqual(
            executable_semantic_surface_identity(baseline),
            executable_semantic_surface_identity(recursively_aliased),
        )
        changed_trade = component(
            "trade",
            implementation_tag="actual-meaning-change",
            semantic_dependencies=trade.semantic_dependencies,
        )
        changed = executable(
            tuple(changed_trade if item is trade else item for item in baseline.components)
        )
        self.assertNotEqual(
            executable_semantic_surface_identity(baseline),
            executable_semantic_surface_identity(changed),
        )

    def test_cross_study_typed_parity_is_direction_independent(self) -> None:
        left_baseline = baseline_executable()
        right_baseline = baseline_executable(model_tag="right-refactor")
        left_model = next(
            item
            for item in left_baseline.components
            if item.protocol.startswith("model.")
        )
        right_model = next(
            item
            for item in right_baseline.components
            if item.protocol.startswith("model.")
        )
        left = ControlledStudyChassis(
            baseline_executable=left_baseline,
            changed_domains=tuple(
                ResearchLayer(domain) for domain in DOMAINS if domain != "model"
            ),
            controlled_domains=(ResearchLayer.MODEL,),
            architecture=architecture(left_baseline),
        )
        right = ControlledStudyChassis(
            baseline_executable=right_baseline,
            changed_domains=tuple(
                ResearchLayer(domain) for domain in DOMAINS if domain != "model"
            ),
            controlled_domains=(ResearchLayer.MODEL,),
            architecture=architecture(right_baseline),
        )
        forward = ComponentParityEvidence(
            canonical_component=left_model,
            equivalent_component=right_model,
            dimensions=PARITY_DIMENSIONS,
            parity_manifest_hash="1" * 64,
            completion_record_id="7" * 64,
        )
        reverse = ComponentParityEvidence(
            canonical_component=right_model,
            equivalent_component=left_model,
            dimensions=PARITY_DIMENSIONS,
            parity_manifest_hash="2" * 64,
            completion_record_id="8" * 64,
        )
        forward_identity = combine_control_payloads(
            left.to_identity_payload(),
            right.to_identity_payload(),
            shared_domains=(ResearchLayer.MODEL,),
            verified_equivalences=(forward.to_identity_payload(),),
        )
        reverse_identity = combine_control_payloads(
            left.to_identity_payload(),
            right.to_identity_payload(),
            shared_domains=(ResearchLayer.MODEL,),
            verified_equivalences=(reverse.to_identity_payload(),),
        )
        self.assertEqual(forward_identity, reverse_identity)

    def test_frozen_controlled_parameters_survive_equivalent_refactor(self) -> None:
        baseline = baseline_executable()
        old_execution = next(
            item
            for item in baseline.components
            if item.protocol.startswith("execution.")
        )
        equivalent_execution = ComponentSpec(
            display_name="execution refactor without parameter declaration",
            protocol=old_execution.protocol,
            implementation="fixture.execution.equivalent-refactor",
            spec={"semantic_role": "execution"},
            semantic_dependencies=old_execution.semantic_dependencies,
        )
        parity = ComponentParityEvidence(
            canonical_component=old_execution,
            equivalent_component=equivalent_execution,
            dimensions=PARITY_DIMENSIONS,
            parity_manifest_hash="3" * 64,
            completion_record_id="9" * 64,
        )
        old_calibration = next(
            item
            for item in baseline.components
            if item.protocol.startswith("calibration.")
        )
        changed_calibration = component(
            "calibration",
            implementation_tag="declared-change",
            semantic_dependencies=old_calibration.semantic_dependencies,
        )
        candidate = executable(
            tuple(
                equivalent_execution
                if item is old_execution
                else changed_calibration
                if item is old_calibration
                else item
                for item in baseline.components
            ),
            parameter_overrides={"execution_profile": 99},
        )
        chassis = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(ResearchLayer.CALIBRATION,),
            controlled_domains=controlled_domains(),
            architecture=architecture(baseline),
            equivalences=(parity,),
        )
        with self.assertRaisesRegex(ChassisIdentityError, "frozen controlled parameter"):
            validate_controlled_executable(chassis.to_identity_payload(), candidate)

    def test_only_changed_domain_gets_a_new_identity(self) -> None:
        baseline = baseline_executable()
        baseline_calibration = next(
            item
            for item in baseline.components
            if item.protocol.startswith("calibration.")
        )
        changed_calibration = component(
            "calibration",
            implementation_tag="meaningfully-changed",
            semantic_dependencies=baseline_calibration.semantic_dependencies,
        )
        candidate = executable(
            tuple(
                changed_calibration if item.protocol.startswith("calibration.") else item
                for item in baseline.components
            ),
            parameter_overrides={"calibration_profile": 1},
        )
        chassis = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(ResearchLayer.CALIBRATION,),
            controlled_domains=controlled_domains(),
            architecture=architecture(baseline),
        )

        with self.assertRaisesRegex(ChassisIdentityError, "does not semantically change"):
            validate_controlled_executable(chassis.to_identity_payload(), baseline)
        validate_controlled_executable(chassis.to_identity_payload(), candidate)
        baseline_ids = {
            item.protocol.split(".", 1)[0]: item.identity for item in baseline.components
        }
        candidate_ids = {
            item.protocol.split(".", 1)[0]: item.identity for item in candidate.components
        }
        self.assertNotEqual(
            baseline_ids["calibration"], candidate_ids["calibration"]
        )
        for domain in set(DOMAINS) - {"calibration"}:
            self.assertEqual(baseline_ids[domain], candidate_ids[domain])

    def test_protocol_only_controlled_component_bump_is_rejected(self) -> None:
        baseline = baseline_executable()
        old_model = next(
            item for item in baseline.components if item.protocol.startswith("model.")
        )
        bumped_model = ComponentSpec(
            display_name="renamed model fixture",
            protocol="model.fixture.v2",
            implementation=old_model.implementation,
            spec=old_model.specification(),
            semantic_dependencies=old_model.semantic_dependencies,
        )
        candidate = executable(
            tuple(
                bumped_model
                if item is old_model
                else component(
                    "calibration",
                    implementation_tag="declared-change",
                    semantic_dependencies=item.semantic_dependencies,
                )
                if item.protocol.startswith("calibration.")
                else item
                for item in baseline.components
            )
        )
        chassis = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(ResearchLayer.CALIBRATION,),
            controlled_domains=controlled_domains(),
            architecture=architecture(baseline),
        )

        with self.assertRaisesRegex(ChassisIdentityError, "protocol-only"):
            validate_controlled_executable(chassis.to_identity_payload(), candidate)
        with self.assertRaisesRegex(ChassisIdentityError, "protocol-only"):
            ComponentParityEvidence(
                canonical_component=old_model,
                equivalent_component=bumped_model,
                dimensions=PARITY_DIMENSIONS,
                parity_manifest_hash="a" * 64,
                completion_record_id="1" * 64,
            )
        old_calibration = next(
            item
            for item in baseline.components
            if item.protocol.startswith("calibration.")
        )
        calibration_alias = ComponentSpec(
            display_name="protocol-only changed calibration",
            protocol="calibration.fixture.v2",
            implementation=old_calibration.implementation,
            spec=old_calibration.specification(),
            semantic_dependencies=old_calibration.semantic_dependencies,
        )
        alias_candidate = executable(
            tuple(
                calibration_alias if item is old_calibration else item
                for item in baseline.components
            )
        )
        with self.assertRaisesRegex(ChassisIdentityError, "does not semantically change"):
            validate_controlled_executable(
                chassis.to_identity_payload(), alias_candidate
            )

    def test_fixed_score_requires_feature_label_model_dependencies(self) -> None:
        baseline = baseline_executable()
        by_domain = {
            item.protocol.split(".", 1)[0]: item for item in baseline.components
        }
        hidden_model = component(
            "model",
            implementation_tag="fixed-score-with-hidden-feature-label",
        )
        def compose(model_component: ComponentSpec) -> ExecutableSpec:
            calibration = component(
                "calibration", semantic_dependencies=(model_component.identity,)
            )
            selector = component(
                "selector", semantic_dependencies=(calibration.identity,)
            )
            trade = component("trade", semantic_dependencies=(selector.identity,))
            lifecycle = component(
                "lifecycle", semantic_dependencies=(trade.identity,)
            )
            risk = component("risk", semantic_dependencies=(lifecycle.identity,))
            execution_component = component(
                "execution", semantic_dependencies=(risk.identity,)
            )
            return executable(
                (
                    by_domain["feature"],
                    by_domain["label"],
                    model_component,
                    calibration,
                    selector,
                    trade,
                    lifecycle,
                    risk,
                    execution_component,
                )
            )

        missing_dependencies = compose(hidden_model)
        chassis = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=tuple(
                ResearchLayer(domain)
                for domain in DOMAINS
                if domain not in {"feature", "label"}
            ),
            controlled_domains=(ResearchLayer.FEATURE, ResearchLayer.LABEL),
            architecture=architecture(baseline),
        )
        with self.assertRaisesRegex(ChassisIdentityError, "feature and label"):
            validate_controlled_executable(
                chassis.to_identity_payload(), missing_dependencies
            )

        explicit_model = component(
            "model",
            implementation_tag="fixed-score-explicit",
            semantic_dependencies=(
                by_domain["feature"].identity,
                by_domain["label"].identity,
            ),
        )
        validate_controlled_executable(
            chassis.to_identity_payload(), compose(explicit_model)
        )

    def test_typed_parity_can_anchor_a_changed_implementation(self) -> None:
        baseline = baseline_executable()
        old_model = next(
            item for item in baseline.components if item.protocol.startswith("model.")
        )
        equivalent_model = component(
            "model",
            implementation_tag="refactored-equivalent",
            semantic_dependencies=old_model.semantic_dependencies,
        )
        parity = ComponentParityEvidence(
            canonical_component=old_model,
            equivalent_component=equivalent_model,
            dimensions=PARITY_DIMENSIONS,
            parity_manifest_hash="b" * 64,
            completion_record_id="2" * 64,
        )
        candidate = executable(
            tuple(
                equivalent_model if item is old_model else item
                if not item.protocol.startswith("calibration.")
                else component(
                    "calibration",
                    implementation_tag="declared-change",
                    semantic_dependencies=item.semantic_dependencies,
                )
                for item in baseline.components
            )
        )
        chassis = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(ResearchLayer.CALIBRATION,),
            controlled_domains=controlled_domains(),
            architecture=architecture(baseline),
            equivalences=(parity,),
        )
        validate_controlled_executable(chassis.to_identity_payload(), candidate)

    def test_cross_study_combination_requires_exact_or_typed_parity(self) -> None:
        left_baseline = baseline_executable()
        left_model = next(
            item
            for item in left_baseline.components
            if item.protocol.startswith("model.")
        )
        right_baseline = baseline_executable(model_tag="equivalent-right")
        right_model = next(
            item
            for item in right_baseline.components
            if item.protocol.startswith("model.")
        )
        left = ControlledStudyChassis(
            baseline_executable=left_baseline,
            changed_domains=tuple(
                ResearchLayer(domain) for domain in DOMAINS if domain != "model"
            ),
            controlled_domains=(ResearchLayer.MODEL,),
            architecture=architecture(left_baseline),
        )
        exact_successor = ControlledStudyChassis(
            baseline_executable=left_baseline.renamed("next Study exact chassis"),
            changed_domains=tuple(
                ResearchLayer(domain) for domain in DOMAINS if domain != "model"
            ),
            controlled_domains=(ResearchLayer.MODEL,),
            architecture=architecture(left_baseline),
        )
        exact_combination = require_combinable_chassis(
            left,
            exact_successor,
            shared_domains=(ResearchLayer.MODEL,),
        )
        self.assertTrue(exact_combination.startswith("chassis-combination:"))
        right = ControlledStudyChassis(
            baseline_executable=right_baseline,
            changed_domains=tuple(
                ResearchLayer(domain) for domain in DOMAINS if domain != "model"
            ),
            controlled_domains=(ResearchLayer.MODEL,),
            architecture=architecture(right_baseline),
        )
        with self.assertRaisesRegex(ChassisIdentityError, "architecture boundary"):
            require_combinable_chassis(
                left,
                right,
                shared_domains=(ResearchLayer.MODEL,),
            )
        parity = ComponentParityEvidence(
            canonical_component=left_model,
            equivalent_component=right_model,
            dimensions=PARITY_DIMENSIONS,
            parity_manifest_hash="c" * 64,
            completion_record_id="3" * 64,
        )
        self.assertTrue(parity.identity.startswith("component-parity:"))
        with self.assertRaisesRegex(ChassisIdentityError, "architecture boundary"):
            require_combinable_chassis(
                left,
                right,
                shared_domains=(ResearchLayer.MODEL,),
            )

    def test_semantic_change_and_architecture_meaning_change_get_new_identities(self) -> None:
        original = component("model")
        protocol_only = ComponentSpec(
            display_name="model renamed",
            protocol="model.fixture.v2",
            implementation=original.implementation,
            spec=original.specification(),
        )
        meaning_change = ComponentSpec(
            display_name="model changed",
            protocol=original.protocol,
            implementation=original.implementation,
            spec={"parameter_fields": ["model_profile"], "semantic_role": "nonlinear"},
        )
        self.assertNotEqual(original.identity, protocol_only.identity)
        self.assertEqual(
            component_semantic_surface_identity(original),
            component_semantic_surface_identity(protocol_only),
        )
        self.assertNotEqual(
            component_semantic_surface_identity(original),
            component_semantic_surface_identity(meaning_change),
        )

        baseline = baseline_executable()
        first = architecture(baseline)
        renamed_construction = architecture(baseline.renamed("same chassis"))
        trade = next(
            item
            for item in baseline.components
            if item.protocol.startswith("trade.")
        )
        trade_alias = ComponentSpec(
            display_name="protocol-only trade alias",
            protocol="trade.fixture.v2",
            implementation=trade.implementation,
            spec=trade.specification(),
            semantic_dependencies=trade.semantic_dependencies,
        )
        alias_baseline = executable(
            tuple(trade_alias if item is trade else item for item in baseline.components)
        )
        self.assertEqual(first.identity, architecture(alias_baseline).identity)
        lifecycle = next(
            item
            for item in baseline.components
            if item.protocol.startswith("lifecycle.")
        )
        changed_lifecycle = component(
            "lifecycle",
            implementation_tag="meaningfully-different-exit",
            semantic_dependencies=lifecycle.semantic_dependencies,
        )
        changed_baseline = executable(
            tuple(
                changed_lifecycle if item is lifecycle else item
                for item in baseline.components
            )
        )
        changed = architecture(changed_baseline)
        self.assertEqual(first.identity, renamed_construction.identity)
        self.assertNotEqual(first.identity, changed.identity)

    def test_execution_boundaries_and_controlled_parameters_block_combination(self) -> None:
        baseline = baseline_executable()
        calibration = next(
            item
            for item in baseline.components
            if item.protocol.startswith("calibration.")
        )
        changed_calibration = component(
            "calibration",
            implementation_tag="actual-change",
            semantic_dependencies=calibration.semantic_dependencies,
        )
        candidate = ExecutableSpec(
            display_name="changed engine candidate",
            components=tuple(
                changed_calibration if item is calibration else item
                for item in baseline.components
            ),
            parameters=baseline.parameter_values(),
            data_contract=baseline.data_contract,
            split_contract=baseline.split_contract,
            clock_contract=baseline.clock_contract,
            cost_contract=baseline.cost_contract,
            engine_contract="engine:changed",
        )
        chassis = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=(ResearchLayer.CALIBRATION,),
            controlled_domains=controlled_domains(),
            architecture=architecture(baseline),
        )
        with self.assertRaisesRegex(ChassisIdentityError, "engine contract"):
            validate_controlled_executable(chassis.to_identity_payload(), candidate)

        different_engine = ExecutableSpec(
            display_name="different engine baseline",
            components=baseline.components,
            parameters=baseline.parameter_values(),
            data_contract=baseline.data_contract,
            split_contract=baseline.split_contract,
            clock_contract=baseline.clock_contract,
            cost_contract=baseline.cost_contract,
            engine_contract="engine:changed",
        )
        engine_chassis = ControlledStudyChassis(
            baseline_executable=different_engine,
            changed_domains=(ResearchLayer.CALIBRATION,),
            controlled_domains=controlled_domains(),
            architecture=architecture(different_engine),
        )
        with self.assertRaisesRegex(ChassisIdentityError, "architecture boundary"):
            require_combinable_chassis(
                chassis,
                engine_chassis,
                shared_domains=(ResearchLayer.EXECUTION,),
            )

        different_parameter = executable(
            baseline.components,
            parameter_overrides={"model_profile": 1},
        )
        parameter_chassis = ControlledStudyChassis(
            baseline_executable=different_parameter,
            changed_domains=tuple(
                ResearchLayer(domain) for domain in DOMAINS if domain != "model"
            ),
            controlled_domains=(ResearchLayer.MODEL,),
            architecture=architecture(different_parameter),
        )
        model_chassis = ControlledStudyChassis(
            baseline_executable=baseline,
            changed_domains=tuple(
                ResearchLayer(domain) for domain in DOMAINS if domain != "model"
            ),
            controlled_domains=(ResearchLayer.MODEL,),
            architecture=architecture(baseline),
        )
        with self.assertRaisesRegex(ChassisIdentityError, "architecture boundary"):
            require_combinable_chassis(
                model_chassis,
                parameter_chassis,
                shared_domains=(ResearchLayer.MODEL,),
            )


if __name__ == "__main__":
    unittest.main()
