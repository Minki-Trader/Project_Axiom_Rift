from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest

import yaml

from axiom_rift.v2.identity import sha256_payload
from axiom_rift.v2.research.dispatch import PROGRAM_KINDS
from axiom_rift.v2.research.scientific_programs import (
    DIRECTIONAL_BUNDLE_ROLES,
    SCIENTIFIC_BUNDLE_ROLES,
    SCIENTIFIC_RUNTIME_PATHS,
    ScientificProgramRegistryError,
    bind_compression_release_runtime,
    bind_directional_reversal_runtime,
    build_scientific_bundle_batch,
    load_scientific_program_registry,
)


PROGRAM_IDS = {
    "feature": "V2FP0001",
    "label": "V2LP0001",
    "model": "V2MP0001",
    "calibration": "V2CP0001",
    "selector": "V2SEL0001",
    "trade": "V2TP0001",
    "sizing": "V2SZ0001",
    "portfolio_risk": "V2PR0001",
}


def _rehash(program_id: str, body: dict[str, object]) -> None:
    identity = {key: value for key, value in body.items() if key != "program_sha256"}
    identity = {"program_id": program_id, **identity}
    body["program_sha256"] = sha256_payload(identity)


def _write_payload(path: Path, payload: dict[str, object]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="ascii")


def _valid_tree(root: Path) -> tuple[Path, dict[str, object], dict[str, dict[str, str]]]:
    runtime_files: list[dict[str, str]] = []
    for relative_path in (
        "src/axiom_rift/v2/research/compression_release.py",
        "src/axiom_rift/v2/research/directional_reversal.py",
        "src/axiom_rift/v2/research/evaluation.py",
        "src/axiom_rift/v2/research/scientific_scout.py",
    ):
        runtime_path = root / relative_path
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        content = f'"""Fixture runtime for {relative_path}."""\n'
        runtime_path.write_bytes(content.encode("ascii"))
        runtime_files.append(
            {
                "path": relative_path,
                "sha256": hashlib.sha256(runtime_path.read_bytes()).hexdigest(),
            }
        )
    runtime_identity = {
        "schema": "axiom_rift_v2_scientific_runtime_manifest_v1",
        "files": runtime_files,
    }
    runtime_sha256 = sha256_payload(runtime_identity)
    contract_path = root / "contracts/v2/scientific/compression_release_v1.yaml"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_payload = {
        "schema": "axiom_rift_v2_scientific_program_contract_v1",
        "market": "FPMarkets_US100_M5",
        "causal": True,
    }
    _write_payload(contract_path, contract_payload)
    contract_sha256 = sha256_payload(contract_payload)

    shared_parameters: dict[str, dict[str, object]] = {
        "feature": {"atr_bars": 24, "box_bars": 12},
        "label": {"horizon_bars_after_entry": 6},
        "model": {
            "family": "deterministic_event_score",
            "train_fit": "hashed_no_op",
        },
        "calibration": {"family": "identity_event_calibration"},
        "selector": {
            "role": "continuation_low",
            "event_kind": "continuation",
            "compression_ratio_max": 2.0,
            "daily_entry_safety_cap": 10,
        },
        "trade": {
            "hold_bars": 6,
            "spread": "observed_broker_points",
            "zero_spread": "unknown_cost_observation",
        },
        "sizing": {"mode": "fixed_lot", "lots": 1.0},
        "portfolio_risk": {
            "one_position_per_role": True,
            "overlap": "forbidden",
        },
    }
    programs: dict[str, dict[str, object]] = {}
    implementation_keys = {
        "feature": "compression_release_features_v1",
        "label": "forward_open_return_6bar_v1",
        "model": "deterministic_event_score_v1",
        "calibration": "identity_event_calibration_v1",
        "selector": "chronological_compression_selector_v1",
        "trade": "fixed_6bar_observed_spread_v1",
        "sizing": "fixed_lot_v1",
        "portfolio_risk": "one_position_safety_v1",
    }
    for kind in PROGRAM_KINDS:
        program_id = PROGRAM_IDS[kind]
        body: dict[str, object] = {
            "kind": kind,
            "version": 1,
            "contract_path": "contracts/v2/scientific/compression_release_v1.yaml",
            "contract_sha256": contract_sha256,
            "implementation_key": implementation_keys[kind],
            "runtime_sha256": runtime_sha256,
            "parameters": shared_parameters[kind],
            "fixture_only": False,
            "reuse_decision": (
                "engine_primitive_reuse_without_evidence"
                if kind in {"trade", "sizing", "portfolio_risk"}
                else "new_scientific_component"
            ),
        }
        _rehash(program_id, body)
        programs[program_id] = body

    selector_ids = ["V2SEL0001", "V2SEL0002", "V2SEL0003", "V2SEL0004", "V2SEL0005"]
    template = deepcopy(programs["V2SEL0001"])
    selector_kinds = (
        ("continuation", 2.0),
        ("continuation", 2.5),
        ("continuation", 3.0),
        ("failed_break_reversal", 2.5),
        ("unconditioned_breakout", None),
    )
    for role, program_id, (event_kind, ratio) in zip(
        SCIENTIFIC_BUNDLE_ROLES,
        selector_ids,
        selector_kinds,
        strict=True,
    ):
        body = deepcopy(template)
        body["parameters"] = {
            "role": role,
            "event_kind": event_kind,
            "compression_ratio_max": ratio,
            "daily_entry_safety_cap": 10,
        }
        _rehash(program_id, body)
        programs[program_id] = body

    registry_payload: dict[str, object] = {
        "schema": "axiom_rift_v2_scientific_program_registry_v1",
        "status": "active",
        "encoding": "ascii_only",
        "hash_semantics": "compact_sorted_ascii_json_sha256",
        "scientific_origin": "v2_current",
        "arbitrary_import_allowed": False,
        "runtime": {**runtime_identity, "runtime_sha256": runtime_sha256},
        "programs": programs,
    }
    registry_path = root / "registries/v2/scientific/program_registry.yaml"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    _write_payload(registry_path, registry_payload)

    roles: dict[str, dict[str, str]] = {}
    for role, selector_id in zip(SCIENTIFIC_BUNDLE_ROLES, selector_ids, strict=True):
        roles[role] = {**PROGRAM_IDS, "selector": selector_id}
    return registry_path, registry_payload, roles


class ScientificProgramRegistryTests(unittest.TestCase):
    def test_active_causal_registry_binds_new_disjoint_five_role_batch(self) -> None:
        root = Path(__file__).resolve().parents[2]
        registry = load_scientific_program_registry(root)
        self.assertEqual(
            tuple(row["path"] for row in registry.runtime_files),
            SCIENTIFIC_RUNTIME_PATHS,
        )
        self.assertIn(
            "src/axiom_rift/v2/research/evaluation.py",
            SCIENTIFIC_RUNTIME_PATHS,
        )
        selectors = dict(
            zip(
                SCIENTIFIC_BUNDLE_ROLES,
                (
                    "V2SEL2001",
                    "V2SEL2002",
                    "V2SEL2003",
                    "V2SEL2004",
                    "V2SEL2005",
                ),
                strict=True,
            )
        )
        shared = {
            "feature": "V2FP1001",
            "label": "V2LP1001",
            "model": "V2MP1001",
            "calibration": "V2CP1001",
            "trade": "V2TP1002",
            "sizing": "V2SZ1001",
            "portfolio_risk": "V2PR1001",
        }
        batch = build_scientific_bundle_batch(
            registry,
            {
                role: {**shared, "selector": selectors[role]}
                for role in SCIENTIFIC_BUNDLE_ROLES
            },
        )
        bind_compression_release_runtime(registry, batch)
        prior = {
            "027be0975647858cae1d71d319a20ccaeda85d2c5feda1deebd78de7ea6d04c0",
            "1b0d2674b6d1e43143540f1b7cf12302d322078f296097810d41382aa0fb319e",
            "2a111689327a43ce46a784287017196ad25b1ac4f8446b913e78e25ad841df06",
            "604cf897b7a0541513bb873fc3ae487ca83919da88bdbe873da55b15cf1ea5d9",
            "cdd8cb3132a04aaa747fafe7214759276ef14f9ff4df1480d6f071e780fcdce0",
        }
        self.assertEqual(5, len(set(batch.bundle_role_hashes.values())))
        self.assertTrue(set(batch.bundle_role_hashes.values()).isdisjoint(prior))
        self.assertEqual(
            {"fixed_6bar_causal_spread_floor_v1"},
            {
                bundle.programs["trade"].implementation_key
                for bundle in batch.bundles.values()
            },
        )

    def test_active_registry_binds_directional_reversal_layout(self) -> None:
        root = Path(__file__).resolve().parents[2]
        registry = load_scientific_program_registry(root)
        selectors = dict(
            zip(
                DIRECTIONAL_BUNDLE_ROLES,
                (
                    "V2SEL3001",
                    "V2SEL3002",
                    "V2SEL3003",
                    "V2SEL3004",
                    "V2SEL3005",
                ),
                strict=True,
            )
        )
        shared = {
            "feature": "V2FP1001",
            "label": "V2LP1001",
            "model": "V2MP1001",
            "calibration": "V2CP1001",
            "trade": "V2TP1002",
            "sizing": "V2SZ1001",
            "portfolio_risk": "V2PR1001",
        }
        batch = build_scientific_bundle_batch(
            registry,
            {
                role: {**shared, "selector": selectors[role]}
                for role in DIRECTIONAL_BUNDLE_ROLES
            },
        )
        hashes = bind_directional_reversal_runtime(registry, batch)
        self.assertEqual(set(DIRECTIONAL_BUNDLE_ROLES), set(hashes))
        self.assertEqual(5, len(set(batch.bundle_role_hashes.values())))

        data = yaml.safe_load(
            (root / "configs/v2/data.yaml").read_text(encoding="ascii")
        )
        policy = yaml.safe_load(
            (
                root
                / "configs/v2/scientific/programs/causal_spread_floor_v1.yaml"
            ).read_text(encoding="ascii")
        )
        consumers = sorted(
            program_id
            for program_id, definition in registry.programs.items()
            if definition.kind == "selector"
            and definition.parameters.get("admission_cost_policy_id")
            == "V2CF0001"
        )
        self.assertEqual(
            consumers,
            sorted(
                data["cost_quality"]["active_causal_fallback"][
                    "selector_program_ids"
                ]
            ),
        )
        self.assertEqual(
            consumers,
            sorted(policy["program_ids"]["selectors"]),
        )

    def test_hypothesis_routing_contract_preserves_all_scientific_routes(self) -> None:
        root = Path(__file__).resolve().parents[2]
        contract = yaml.safe_load(
            (root / "contracts/v2/hypothesis_contract.yaml").read_text(
                encoding="ascii"
            )
        )
        routing = contract["routing"]
        self.assertEqual("repair_same_scope", routing["broken_execution"])
        self.assertEqual(
            "record_negative_memory_then_rotate",
            routing["scientific_reject"],
        )
        self.assertEqual("advance_by_stage_gate", routing["scientific_survive"])
        self.assertEqual(
            "close_without_negative_memory_then_preregister_distinct_H",
            routing["scientific_evidence_gap"],
        )
        self.assertFalse(routing["identical_executable_retry_allowed"])
        state_machine = yaml.safe_load(
            (root / "contracts/v2/state_machine.yaml").read_text(
                encoding="ascii"
            )
        )
        self.assertIn(
            "evidence_gap_to_distinct_H",
            state_machine["stage_internal_routes"]["S"],
        )

    def test_contract_and_program_hashes_are_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry_path, payload, _roles = _valid_tree(root)
            programs = payload["programs"]
            assert isinstance(programs, dict)
            feature = programs["V2FP0001"]
            assert isinstance(feature, dict)
            feature["contract_sha256"] = "0" * 64
            _rehash("V2FP0001", feature)
            _write_payload(registry_path, payload)
            with self.assertRaisesRegex(ScientificProgramRegistryError, "contract hash mismatch"):
                load_scientific_program_registry(root, registry_path)

            registry_path, payload, _roles = _valid_tree(root)
            programs = payload["programs"]
            assert isinstance(programs, dict)
            feature = programs["V2FP0001"]
            assert isinstance(feature, dict)
            feature["program_sha256"] = "0" * 64
            _write_payload(registry_path, payload)
            with self.assertRaisesRegex(ScientificProgramRegistryError, "identity hash mismatch"):
                load_scientific_program_registry(root, registry_path)

            registry_path, _payload, _roles = _valid_tree(root)
            runtime_path = (
                root / "src/axiom_rift/v2/research/compression_release.py"
            )
            runtime_path.write_bytes(runtime_path.read_bytes() + b"# drift\n")
            with self.assertRaisesRegex(
                ScientificProgramRegistryError, "runtime file hash mismatch"
            ):
                load_scientific_program_registry(root, registry_path)

    def test_fixture_and_unsafe_implementation_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry_path, payload, _roles = _valid_tree(root)
            programs = payload["programs"]
            assert isinstance(programs, dict)
            feature = programs["V2FP0001"]
            assert isinstance(feature, dict)
            feature["fixture_only"] = True
            _rehash("V2FP0001", feature)
            _write_payload(registry_path, payload)
            with self.assertRaisesRegex(ScientificProgramRegistryError, "fixture_only=false"):
                load_scientific_program_registry(root, registry_path)

            registry_path, payload, _roles = _valid_tree(root)
            programs = payload["programs"]
            assert isinstance(programs, dict)
            feature = programs["V2FP0001"]
            assert isinstance(feature, dict)
            feature["implementation_key"] = "arbitrary_import"
            _rehash("V2FP0001", feature)
            _write_payload(registry_path, payload)
            with self.assertRaisesRegex(ScientificProgramRegistryError, "allowlist"):
                load_scientific_program_registry(root, registry_path)

    def test_missing_kind_and_renamed_executable_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry_path, payload, _roles = _valid_tree(root)
            programs = payload["programs"]
            assert isinstance(programs, dict)
            del programs["V2SZ0001"]
            _write_payload(registry_path, payload)
            with self.assertRaisesRegex(ScientificProgramRegistryError, "all eight"):
                load_scientific_program_registry(root, registry_path)

            registry_path, payload, _roles = _valid_tree(root)
            programs = payload["programs"]
            assert isinstance(programs, dict)
            duplicate = deepcopy(programs["V2FP0001"])
            assert isinstance(duplicate, dict)
            _rehash("V2FP0002", duplicate)
            programs["V2FP0002"] = duplicate
            _write_payload(registry_path, payload)
            with self.assertRaisesRegex(ScientificProgramRegistryError, "renamed duplicate"):
                load_scientific_program_registry(root, registry_path)

    def test_bundle_missing_kind_duplicate_roles_and_external_sources_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry_path, _payload, roles = _valid_tree(root)
            registry = load_scientific_program_registry(root, registry_path)

            missing = deepcopy(roles)
            del missing[SCIENTIFIC_BUNDLE_ROLES[0]]["sizing"]
            with self.assertRaisesRegex(ScientificProgramRegistryError, "all eight"):
                build_scientific_bundle_batch(registry, missing)

            duplicate = deepcopy(roles)
            duplicate[SCIENTIFIC_BUNDLE_ROLES[1]] = deepcopy(
                duplicate[SCIENTIFIC_BUNDLE_ROLES[0]]
            )
            with self.assertRaisesRegex(ScientificProgramRegistryError, "materially distinct"):
                build_scientific_bundle_batch(registry, duplicate)

            with self.assertRaisesRegex(ScientificProgramRegistryError, "external sources"):
                build_scientific_bundle_batch(
                    registry,
                    {"bundle_roles": roles, "external_source_ids": ["macro_feed"]},
                )

    def test_valid_five_role_batch_is_pure_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry_path, _payload, roles = _valid_tree(root)
            before = registry_path.read_bytes()
            first_registry = load_scientific_program_registry(root, registry_path)
            first = build_scientific_bundle_batch(first_registry, roles)

            reversed_roles = {
                role: dict(reversed(list(roles[role].items())))
                for role in reversed(SCIENTIFIC_BUNDLE_ROLES)
            }
            second_registry = load_scientific_program_registry(root, registry_path)
            second = build_scientific_bundle_batch(second_registry, reversed_roles)

            self.assertEqual(before, registry_path.read_bytes())
            self.assertEqual(first_registry.registry_sha256, second_registry.registry_sha256)
            self.assertEqual(first.batch_sha256, second.batch_sha256)
            self.assertEqual(dict(first.bundle_role_hashes), dict(second.bundle_roles))
            self.assertEqual(set(first.bundle_role_hashes), set(SCIENTIFIC_BUNDLE_ROLES))
            self.assertEqual(5, len(set(first.bundle_role_hashes.values())))
            self.assertEqual(first.batch_sha256, sha256_payload(first.to_payload()))
            for bundle in first.bundles.values():
                self.assertEqual(set(bundle.programs), set(PROGRAM_KINDS))
                self.assertEqual((), bundle.external_source_ids)
            release_hashes = bind_compression_release_runtime(first_registry, first)
            self.assertEqual(set(release_hashes), set(SCIENTIFIC_BUNDLE_ROLES))

            swapped = deepcopy(roles)
            swapped["continuation_low"]["selector"] = roles["continuation_high"][
                "selector"
            ]
            swapped["continuation_high"]["selector"] = roles["continuation_low"][
                "selector"
            ]
            swapped_batch = build_scientific_bundle_batch(first_registry, swapped)
            with self.assertRaisesRegex(
                ScientificProgramRegistryError, "selector differs from runtime"
            ):
                bind_compression_release_runtime(first_registry, swapped_batch)

    def test_causal_spread_floor_bundle_is_uniform_and_rejects_mixed_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry_path, payload, roles = _valid_tree(root)
            programs = payload["programs"]
            assert isinstance(programs, dict)
            legacy_trade = programs["V2TP0001"]
            assert isinstance(legacy_trade, dict)
            causal_trade = deepcopy(legacy_trade)
            causal_trade.update(
                {
                    "implementation_key": "fixed_6bar_causal_spread_floor_v1",
                    "parameters": {
                        "hold_bars": 6,
                        "policy_id": "V2CF0001",
                        "decision_zero_action": "reject_signal_admission",
                        "positive_execution_rule": (
                            "max_decision_and_execution_spread"
                        ),
                        "execution_zero_action": (
                            "positive_decision_spread_floor"
                        ),
                        "policy_parameter_count": 0,
                    },
                }
            )
            _rehash("V2TP0002", causal_trade)
            programs["V2TP0002"] = causal_trade
            causal_roles = deepcopy(roles)
            for index, role in enumerate(SCIENTIFIC_BUNDLE_ROLES, start=1):
                legacy_selector_id = roles[role]["selector"]
                selector = deepcopy(programs[legacy_selector_id])
                assert isinstance(selector, dict)
                selector["implementation_key"] = (
                    "chronological_compression_cost_gated_selector_v1"
                )
                selector["parameters"] = {
                    **dict(selector["parameters"]),
                    "admission_cost_policy_id": "V2CF0001",
                }
                selector_id = f"V2SEL01{index:02d}"
                _rehash(selector_id, selector)
                programs[selector_id] = selector
                causal_roles[role]["selector"] = selector_id
                causal_roles[role]["trade"] = "V2TP0002"
            _write_payload(registry_path, payload)
            registry = load_scientific_program_registry(root, registry_path)
            batch = build_scientific_bundle_batch(registry, causal_roles)
            release_hashes = bind_compression_release_runtime(registry, batch)
            self.assertEqual(set(SCIENTIFIC_BUNDLE_ROLES), set(release_hashes))

            mixed = deepcopy(causal_roles)
            mixed["continuation_low"]["trade"] = "V2TP0001"
            mixed_batch = build_scientific_bundle_batch(registry, mixed)
            with self.assertRaisesRegex(
                ScientificProgramRegistryError, "mix trade cost policies"
            ):
                bind_compression_release_runtime(registry, mixed_batch)


if __name__ == "__main__":
    unittest.main()
