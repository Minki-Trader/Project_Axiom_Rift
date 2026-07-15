from __future__ import annotations

import unittest

from axiom_rift.core.component_surface import (
    ARCHITECTURE_ROLE_DOMAINS,
    COMPONENT_SURFACE_ARCHITECTURE_ROLE,
    COMPONENT_SURFACE_DOMAIN_AWARE,
    COMPONENT_SURFACE_PROTOCOL_NEUTRAL,
    ComponentManifestError,
    component_manifest_surfaces,
    component_spec_from_manifest,
)
from axiom_rift.core.identity import ComponentSpec, canonical_digest
from axiom_rift.research.chassis import (
    ChassisIdentityError,
    architecture_component_semantic_surface_identity,
    component_semantic_surface_identity,
)
from axiom_rift.research.governance import ResearchLayer


class ComponentSurfaceTests(unittest.TestCase):
    def test_every_research_domain_preserves_the_legacy_surface_formula(self) -> None:
        role_by_domain = {
            domain: role
            for role, domains in ARCHITECTURE_ROLE_DOMAINS.items()
            for domain in domains
        }
        protocols = tuple(layer.value for layer in ResearchLayer) + (
            "external_source",
        )
        for ordinal, protocol in enumerate(protocols):
            with self.subTest(protocol=protocol):
                component = ComponentSpec(
                    display_name=f"component {ordinal}",
                    protocol=protocol + ".v1",
                    implementation=f"implementation-{ordinal:02d}",
                    spec={"ordinal": ordinal},
                    semantic_dependencies=(f"dependency-{ordinal:02d}",),
                )
                manifest = component.to_identity_payload()
                normalized_domain = (
                    "data_source" if protocol == "external_source" else protocol
                )
                expected_domain_aware = "component-surface:" + canonical_digest(
                    domain="component-semantic-surface",
                    payload={
                        "domain": normalized_domain,
                        "implementation": manifest["implementation"],
                        "schema": "component_semantic_surface.v1",
                        "semantic_dependencies": manifest[
                            "semantic_dependencies"
                        ],
                        "spec": manifest["spec"],
                    },
                )
                expected_protocol_neutral = (
                    "component-protocol-neutral:"
                    + canonical_digest(
                        domain="component-protocol-neutral-surface",
                        payload={
                            "implementation": manifest["implementation"],
                            "schema": "component_protocol_neutral_surface.v1",
                            "semantic_dependencies": manifest[
                                "semantic_dependencies"
                            ],
                            "spec": manifest["spec"],
                        },
                    )
                )
                role = role_by_domain.get(normalized_domain)
                expected_architecture = (
                    None
                    if role is None
                    else "architecture-component-surface:"
                    + canonical_digest(
                        domain="architecture-component-semantic-surface",
                        payload={
                            "implementation": manifest["implementation"],
                            "role": role,
                            "schema": (
                                "architecture_component_semantic_surface.v1"
                            ),
                            "semantic_dependencies": manifest[
                                "semantic_dependencies"
                            ],
                            "spec": manifest["spec"],
                        },
                    )
                )

                surfaces = component_manifest_surfaces(manifest)

                self.assertEqual(surfaces.component_id, component.identity)
                self.assertEqual(surfaces.domain, normalized_domain)
                self.assertEqual(surfaces.domain_aware, expected_domain_aware)
                self.assertEqual(
                    surfaces.protocol_neutral,
                    expected_protocol_neutral,
                )
                self.assertEqual(surfaces.architecture_role, role)
                self.assertEqual(
                    surfaces.architecture_role_surface,
                    expected_architecture,
                )
                self.assertEqual(
                    component_semantic_surface_identity(component),
                    expected_domain_aware,
                )
                if expected_architecture is None:
                    with self.assertRaisesRegex(
                        ChassisIdentityError,
                        "outside the prediction-to-position",
                    ):
                        architecture_component_semantic_surface_identity(component)
                else:
                    self.assertEqual(
                        architecture_component_semantic_surface_identity(component),
                        expected_architecture,
                    )
                expected_bindings = {
                    (
                        COMPONENT_SURFACE_DOMAIN_AWARE,
                        expected_domain_aware,
                    ),
                    (
                        COMPONENT_SURFACE_PROTOCOL_NEUTRAL,
                        expected_protocol_neutral,
                    ),
                }
                if expected_architecture is not None:
                    expected_bindings.add(
                        (
                            COMPONENT_SURFACE_ARCHITECTURE_ROLE,
                            expected_architecture,
                        )
                    )
                self.assertEqual(set(surfaces.bindings()), expected_bindings)

    def test_role_and_protocol_collapsing_is_exact(self) -> None:
        def component(protocol: str) -> ComponentSpec:
            return ComponentSpec(
                display_name=protocol,
                protocol=protocol + ".v1",
                implementation="shared-implementation",
                spec={"shared": True},
            )

        decision = tuple(
            component_manifest_surfaces(component(protocol))
            for protocol in ("model", "calibration", "selector")
        )
        self.assertEqual(
            len({item.architecture_role_surface for item in decision}),
            1,
        )
        self.assertEqual(len({item.domain_aware for item in decision}), 3)
        self.assertEqual(len({item.protocol_neutral for item in decision}), 1)
        source = component_manifest_surfaces(component("data_source"))
        alias = component_manifest_surfaces(component("external_source"))
        self.assertEqual(source.domain_aware, alias.domain_aware)
        self.assertEqual(source.protocol_neutral, alias.protocol_neutral)

    def test_manifest_validator_rejects_noncanonical_or_unknown_domains(self) -> None:
        component = ComponentSpec(
            display_name="fixture",
            protocol="model.v1",
            implementation="fixture-implementation",
            spec={"fixture": True},
            semantic_dependencies=("a", "b"),
        )
        unsorted = component.to_identity_payload()
        unsorted["semantic_dependencies"] = ["b", "a"]
        with self.assertRaisesRegex(ComponentManifestError, "not canonical"):
            component_spec_from_manifest(unsorted)

        unknown = component.to_identity_payload()
        unknown["protocol"] = "unknown.v1"
        with self.assertRaisesRegex(ComponentManifestError, "ResearchLayer"):
            component_manifest_surfaces(unknown)


if __name__ == "__main__":
    unittest.main()
