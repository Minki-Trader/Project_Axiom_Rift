from __future__ import annotations

import dataclasses
from hashlib import sha256
import unittest

from axiom_rift.core.canonical import (
    CanonicalJSONError,
    canonical_bytes,
    canonical_text,
    parse_canonical,
)
from axiom_rift.core.identity import (
    ComponentSpec,
    ExecutableSpec,
    canonical_digest,
    canonical_identity_bytes,
    parse_canonical_identity_bytes,
)


CANONICAL_FIXTURE = {"z": [3, True, None], "a": {"x": "ASCII", "n": -7}}
CANONICAL_GOLDEN = b'{"a":{"n":-7,"x":"ASCII"},"z":[3,true,null]}'
CANONICAL_DIGEST_GOLDEN = (
    "0acba82228afca10aa3450c965948e27797b85f93ffd1d6ccb4fcf2aeab228e8"
)
COMPONENT_GOLDEN = (
    "component:30db77bab49db90033264ac70d271db9dbfddf9390cd4bc843eeb00428fd1b0e"
)
SELECTOR_GOLDEN = (
    "component:035aeee702a48008dc429b96b90b1f592ef2f2fbe731438fab094461062d35ca"
)
EXECUTABLE_GOLDEN = (
    "executable:c1f0c8c87d6d625240932bda0bec58cfa29559721c38fe1c372c3531a0e51503"
)
SOURCE_A = "source:" + "a" * 64
SOURCE_B = "source:" + "b" * 64


def component(
    *,
    display_name: str = "Momentum",
    source_contracts: tuple[str, ...] = (SOURCE_A,),
) -> ComponentSpec:
    return ComponentSpec(
        display_name=display_name,
        protocol="feature.completed_bar.v1",
        implementation="impl:fixture-v1",
        spec={"lookback": 12, "inputs": ["close", "high", "low"]},
        semantic_dependencies=(*source_contracts, "clock:completed_m5"),
    )


def selector() -> ComponentSpec:
    return ComponentSpec(
        display_name="Threshold selector",
        protocol="selector.threshold.v1",
        implementation="impl:selector-v1",
        spec={"side": "both"},
    )


def executable(
    *,
    display_name: str = "Fixture executable",
    components: tuple[ComponentSpec, ...] | None = None,
    parameters: object | None = None,
    data_contract: str = "data:us100-m5-fixture-v1",
    split_contract: str = "split:walk-forward-fixture-v1",
    clock_contract: str = "clock:completed-m5-v1",
    cost_contract: str = "cost:native-spread-v1",
    engine_contract: str = "engine:python-sequential-v1",
    source_contracts: tuple[str, ...] = (SOURCE_A,),
) -> ExecutableSpec:
    return ExecutableSpec(
        display_name=display_name,
        components=components
        if components is not None
        else (component(source_contracts=source_contracts), selector()),
        parameters=parameters
        if parameters is not None
        else {"threshold_bps": 25, "directions": ["long", "short"]},
        data_contract=data_contract,
        split_contract=split_contract,
        clock_contract=clock_contract,
        cost_contract=cost_contract,
        engine_contract=engine_contract,
        source_contracts=source_contracts,
    )


class CanonicalJSONTests(unittest.TestCase):
    def test_golden_encoding_and_parse(self) -> None:
        self.assertEqual(canonical_bytes(CANONICAL_FIXTURE), CANONICAL_GOLDEN)
        self.assertEqual(canonical_text(CANONICAL_FIXTURE), CANONICAL_GOLDEN.decode())
        self.assertEqual(parse_canonical(CANONICAL_GOLDEN), CANONICAL_FIXTURE)
        self.assertEqual(parse_canonical(CANONICAL_GOLDEN.decode()), CANONICAL_FIXTURE)

    def test_domain_separated_digest_golden(self) -> None:
        self.assertEqual(
            canonical_digest(domain="fixture", payload=CANONICAL_FIXTURE),
            CANONICAL_DIGEST_GOLDEN,
        )
        self.assertNotEqual(
            canonical_digest(domain="fixture", payload=CANONICAL_FIXTURE),
            canonical_digest(domain="other", payload=CANONICAL_FIXTURE),
        )

    def test_canonical_identity_bytes_are_the_exact_digest_preimage(self) -> None:
        framed = canonical_identity_bytes(
            domain="fixture", payload=CANONICAL_FIXTURE
        )
        self.assertEqual(sha256(framed).hexdigest(), CANONICAL_DIGEST_GOLDEN)
        self.assertTrue(framed.endswith(CANONICAL_GOLDEN))

    def test_canonical_identity_bytes_round_trip_strictly(self) -> None:
        framed = canonical_identity_bytes(
            domain="fixture", payload=CANONICAL_FIXTURE
        )
        self.assertEqual(
            parse_canonical_identity_bytes(framed),
            ("fixture", CANONICAL_FIXTURE),
        )
        noncanonical = (
            framed[: -len(CANONICAL_GOLDEN)]
            + b'{ "a":{"n":-7,"x":"ASCII"},"z":[3,true,null]}'
        )
        for label, malformed in (
            ("prefix", b"X" + framed[1:]),
            ("truncated", framed[:12]),
            ("noncanonical", noncanonical),
        ):
            with self.subTest(label=label):
                with self.assertRaises(ValueError):
                    parse_canonical_identity_bytes(malformed)
        with self.assertRaises(TypeError):
            parse_canonical_identity_bytes(framed.decode("latin-1"))  # type: ignore[arg-type]

    def test_python_values_outside_profile_are_rejected(self) -> None:
        rejected = (
            1.0,
            float("nan"),
            float("inf"),
            "non-ascii-\u00e9",
            {"\u00e9": 1},
            {1: "value"},
            ("tuple",),
        )
        for value in rejected:
            with self.subTest(value=repr(value)):
                with self.assertRaises(CanonicalJSONError):
                    canonical_bytes(value)

    def test_noncanonical_or_unsafe_documents_are_rejected(self) -> None:
        rejected = (
            b'{"x":1,"x":2}',
            b'{"x":1.0}',
            b'{"x":NaN}',
            b'{"x":Infinity}',
            b'{"z":1,"a":2}',
            b'{"a": 2}',
            b'{"a":2}\n',
            b'{"x":"\\u00e9"}',
            '{"x":"\u00e9"}',
        )
        for document in rejected:
            with self.subTest(document=repr(document)):
                with self.assertRaises(CanonicalJSONError):
                    parse_canonical(document)

    def test_cycles_are_rejected(self) -> None:
        value: list[object] = []
        value.append(value)
        with self.assertRaises(CanonicalJSONError):
            canonical_bytes(value)


class ComponentIdentityTests(unittest.TestCase):
    def test_component_golden_and_display_rename_stability(self) -> None:
        original = component()
        self.assertEqual(original.identity, COMPONENT_GOLDEN)
        self.assertEqual(selector().identity, SELECTOR_GOLDEN)
        self.assertEqual(original.renamed("Renamed display").identity, original.identity)
        self.assertEqual(component(display_name="Another label"), original)

    def test_component_identity_is_detached_from_mutable_input(self) -> None:
        semantic_spec = {"window": [5, 10]}
        value = ComponentSpec(
            display_name="Detached",
            protocol="feature.detached.v1",
            implementation="impl:detached-v1",
            spec=semantic_spec,
        )
        identity_before = value.identity
        semantic_spec["window"].append(20)
        detached = value.specification()
        detached["window"].append(30)
        self.assertEqual(value.identity, identity_before)
        self.assertEqual(value.specification(), {"window": [5, 10]})

    def test_each_component_semantic_surface_changes_identity(self) -> None:
        original = component()
        variants = (
            ComponentSpec(
                display_name="Momentum",
                protocol="feature.completed_bar.v2",
                implementation="impl:fixture-v1",
                spec={"lookback": 12, "inputs": ["close", "high", "low"]},
                semantic_dependencies=(SOURCE_A, "clock:completed_m5"),
            ),
            ComponentSpec(
                display_name="Momentum",
                protocol="feature.completed_bar.v1",
                implementation="impl:fixture-v2",
                spec={"lookback": 12, "inputs": ["close", "high", "low"]},
                semantic_dependencies=(SOURCE_A, "clock:completed_m5"),
            ),
            ComponentSpec(
                display_name="Momentum",
                protocol="feature.completed_bar.v1",
                implementation="impl:fixture-v1",
                spec={"lookback": 13, "inputs": ["close", "high", "low"]},
                semantic_dependencies=(SOURCE_A, "clock:completed_m5"),
            ),
            ComponentSpec(
                display_name="Momentum",
                protocol="feature.completed_bar.v1",
                implementation="impl:fixture-v1",
                spec={"lookback": 12, "inputs": ["close", "high", "low"]},
                semantic_dependencies=(SOURCE_B, "clock:completed_m5"),
            ),
        )
        for variant in variants:
            with self.subTest(identity=variant.identity):
                self.assertNotEqual(variant.identity, original.identity)

    def test_dependency_order_is_not_semantic_but_duplicates_are_invalid(self) -> None:
        ordered = component()
        reversed_dependencies = ComponentSpec(
            display_name="Momentum",
            protocol="feature.completed_bar.v1",
            implementation="impl:fixture-v1",
            spec={"inputs": ["close", "high", "low"], "lookback": 12},
            semantic_dependencies=("clock:completed_m5", SOURCE_A),
        )
        self.assertEqual(reversed_dependencies.identity, ordered.identity)
        with self.assertRaises(ValueError):
            ComponentSpec(
                display_name="Invalid",
                protocol="feature.invalid.v1",
                implementation="impl:invalid-v1",
                spec={},
                semantic_dependencies=("same", "same"),
            )

    def test_unrelated_registry_addition_does_not_rehash_component(self) -> None:
        original = component()
        registry = {original.identity: original}
        identity_before = original.identity
        unrelated = selector()
        registry[unrelated.identity] = unrelated
        self.assertEqual(original.identity, identity_before)
        self.assertEqual(registry[identity_before], original)

    def test_component_is_frozen_and_ascii_only(self) -> None:
        value = component()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            value.display_name = "Mutation"  # type: ignore[misc]
        with self.assertRaises(ValueError):
            ComponentSpec(
                display_name="non-ascii-\u00e9",
                protocol="feature.fixture.v1",
                implementation="impl:fixture-v1",
                spec={},
            )


class ExecutableIdentityTests(unittest.TestCase):
    def test_executable_golden_and_display_rename_stability(self) -> None:
        original = executable()
        self.assertEqual(original.identity, EXECUTABLE_GOLDEN)
        self.assertEqual(original.renamed("Renamed executable").identity, original.identity)

    def test_ordered_composition_is_bound(self) -> None:
        original = executable()
        reversed_composition = executable(
            components=(selector(), component())
        )
        self.assertNotEqual(reversed_composition.identity, original.identity)

    def test_parameters_are_canonical_and_detached(self) -> None:
        parameters = {"threshold_bps": 25, "directions": ["long", "short"]}
        original = executable(parameters=parameters)
        reordered = executable(
            parameters={"directions": ["long", "short"], "threshold_bps": 25}
        )
        self.assertEqual(reordered.identity, original.identity)
        parameters["directions"].append("flat")
        detached = original.parameter_values()
        detached["directions"].append("detached")
        self.assertEqual(original.identity, EXECUTABLE_GOLDEN)
        self.assertEqual(
            original.parameter_values(),
            {"directions": ["long", "short"], "threshold_bps": 25},
        )

    def test_each_bound_contract_changes_executable_identity(self) -> None:
        original = executable()
        variants = (
            executable(data_contract="data:changed"),
            executable(split_contract="split:changed"),
            executable(clock_contract="clock:changed"),
            executable(cost_contract="cost:changed"),
            executable(engine_contract="engine:changed"),
            executable(source_contracts=(SOURCE_B,)),
            executable(parameters={"threshold_bps": 26}),
        )
        for variant in variants:
            with self.subTest(identity=variant.identity):
                self.assertNotEqual(variant.identity, original.identity)

    def test_source_contract_order_is_not_semantic(self) -> None:
        first = executable(source_contracts=(SOURCE_B, SOURCE_A))
        second = executable(source_contracts=(SOURCE_A, SOURCE_B))
        self.assertEqual(first.identity, second.identity)

    def test_component_source_dependency_cannot_be_omitted_or_added_out_of_band(self) -> None:
        with self.assertRaises(ValueError):
            executable(components=(component(), selector()), source_contracts=())
        with self.assertRaises(ValueError):
            executable(
                components=(component(source_contracts=(SOURCE_A,)), selector()),
                source_contracts=(SOURCE_A, SOURCE_B),
            )

    def test_unrelated_registry_addition_does_not_rehash_executable(self) -> None:
        original = executable()
        registry = {original.identity: original}
        identity_before = original.identity
        unrelated = executable(parameters={"unrelated": 1})
        registry[unrelated.identity] = unrelated
        self.assertEqual(original.identity, identity_before)
        self.assertEqual(registry[identity_before], original)

    def test_invalid_component_identity_and_float_parameter_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            executable(components=("not-a-component",))  # type: ignore[arg-type]
        with self.assertRaises(CanonicalJSONError):
            executable(parameters={"threshold": 0.5})


if __name__ == "__main__":
    unittest.main()
