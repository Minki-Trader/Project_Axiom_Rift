from __future__ import annotations

import ast
from collections import Counter
import inspect
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from axiom_rift.core.component_surface import (
    COMPONENT_SURFACE_PROTOCOL_NEUTRAL,
    component_manifest_surfaces,
)
from axiom_rift.core.identity import ComponentSpec, ExecutableSpec
from axiom_rift.operations.writer import StateWriter


class WriterHistoryQueryTests(unittest.TestCase):
    @staticmethod
    def _executable() -> ExecutableSpec:
        component = ComponentSpec(
            display_name="bounded model component",
            protocol="model.bounded_history.v1",
            implementation="fixture.bounded_history.model",
            spec={"window": 5},
        )
        return ExecutableSpec(
            display_name="bounded history executable",
            components=(component,),
            parameters={"threshold_bp": 5000},
            data_contract="data:" + "a" * 64,
            split_contract="split:" + "b" * 64,
            clock_contract="clock:" + "c" * 64,
            cost_contract="cost:" + "d" * 64,
            engine_contract="engine:" + "e" * 64,
        )

    def test_component_projection_uses_canonical_indexed_surface(self) -> None:
        executable = self._executable()
        manifest = executable.components[0].to_identity_payload()
        expected_surface = component_manifest_surfaces(manifest).protocol_neutral

        class ExactIndex:
            def __init__(self) -> None:
                self.surface_query: tuple[str, str] | None = None

            def get(self, kind: str, record_id: str):
                self.exact_record = (kind, record_id)
                return None

            def records_by_fingerprint(self, fingerprint: str):
                self.domain_surface = fingerprint
                return ()

            def component_manifests_by_surface(
                self,
                surface_kind: str,
                surface_identity: str,
            ):
                self.surface_query = (surface_kind, surface_identity)
                return ()

            def records_by_kind(self, _kind: str):
                raise AssertionError("Component projection scanned global history")

        writer = object.__new__(StateWriter)
        index = ExactIndex()
        records = writer._project_executable_components(index, executable)

        self.assertEqual(len(records), 1)
        self.assertEqual(
            writer._component_protocol_neutral_surface(manifest),
            expected_surface,
        )
        self.assertEqual(
            index.surface_query,
            (COMPONENT_SURFACE_PROTOCOL_NEUTRAL, expected_surface),
        )

    def test_empty_parity_seed_has_no_global_history_fallback(self) -> None:
        class NoScanIndex:
            def records_by_kind(self, _kind: str):
                raise AssertionError("Parity resolution scanned global history")

            def records_by_fingerprint(self, _fingerprint: str):
                raise AssertionError("Empty parity seed performed a lookup")

            def records_by_subject_status(self, _subject: str, _status: str):
                raise AssertionError("Empty parity seed performed a lookup")

        writer = object.__new__(StateWriter)
        self.assertEqual(
            writer._verified_component_parity_edges(NoScanIndex()),
            (),
        )

    def test_cross_contract_controlled_history_uses_one_global_presence_rule(
        self,
    ) -> None:
        executable = self._executable()
        axis_identity = "axis:" + "f" * 64
        provenance = {
            "data_contract": executable.data_contract,
            "kind": "first_axis_controlled_chassis_bootstrap",
            "portfolio_axis_identity": axis_identity,
        }
        decision = SimpleNamespace(
            payload={
                "baseline_executable": executable.to_identity_payload(),
                "baseline_executable_id": executable.identity,
                "baseline_provenance": provenance,
                "target_axis_identity": axis_identity,
            }
        )
        writer = object.__new__(StateWriter)
        component_record = writer._component_manifest_record(
            component_id=executable.component_identities[0],
            manifest=executable.components[0].to_identity_payload(),
        )

        class ExactIndex:
            def __init__(self) -> None:
                self.lookups: list[tuple[str, str, str]] = []
                self.global_presence_reads = 0

            def records_by_payload_text(
                self,
                kind: str,
                lookup_name: str,
                value: str,
            ):
                self.lookups.append((kind, lookup_name, value))
                if kind == "trial" and lookup_name == "trial_data_contract":
                    return (SimpleNamespace(payload={"executable": {}}),)
                if kind == "study-open" and lookup_name == "portfolio_axis_identity":
                    return ()
                raise AssertionError("Unexpected baseline history lookup")

            def has_controlled_chassis_study(self) -> bool:
                self.global_presence_reads += 1
                return True

            def get(self, kind: str, record_id: str):
                if (kind, record_id) == (
                    "component-manifest",
                    component_record.record_id,
                ):
                    return component_record
                return None

        index = ExactIndex()
        with patch.object(
            StateWriter,
            "_prior_scientific_baseline",
            return_value=None,
        ):
            writer._require_registered_chassis_baseline(
                index=index,
                controlled_chassis=SimpleNamespace(
                    baseline_executable=executable,
                ),
                decision=decision,
            )
        self.assertEqual(index.global_presence_reads, 1)
        self.assertIn(
            ("study-open", "portfolio_axis_identity", axis_identity),
            index.lookups,
        )
        self.assertNotIn(
            (
                "study-open",
                "study_open_baseline_data_contract",
                executable.data_contract,
            ),
            index.lookups,
        )

    def test_full_history_reads_are_restricted_to_explicit_boundaries(self) -> None:
        source_path = Path(inspect.getsourcefile(StateWriter) or "")
        tree = ast.parse(source_path.read_text(encoding="ascii"))
        writer_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "StateWriter"
        )
        observed: Counter[tuple[str, str]] = Counter()
        methods: dict[str, ast.FunctionDef] = {}
        for method in writer_class.body:
            if not isinstance(method, ast.FunctionDef):
                continue
            methods[method.name] = method
            for node in ast.walk(method):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "records_by_kind"
                ):
                    kind = (
                        node.args[0].value
                        if node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)
                        else "<dynamic>"
                    )
                    observed[(method.name, kind)] += 1

        expected = Counter(
            {
                ("activate_project_goal_continuation", "mission-close"): 1,
                ("_derive_research_history_summary", "study-open"): 1,
                ("_derive_research_history_summary", "study-close"): 1,
                ("_derive_research_history_summary", "trial"): 1,
                ("_derive_research_history_summary", "study-diagnosis"): 1,
                ("_derive_research_history_summary", "mission-close"): 1,
                ("backfill_historical_study_kpis", "study-close"): 1,
                ("backfill_historical_study_kpis", "study-open"): 1,
                ("rebuild_study_kpi_projection", "study-kpi"): 1,
                ("backfill_component_manifests", "trial"): 1,
                ("backfill_semantic_question_registry", "study-open"): 1,
                ("backfill_executable_semantic_surfaces", "trial"): 1,
                (
                    "record_historical_scientific_adjudications",
                    "negative-memory",
                ): 1,
                ("accept_exhaustion_audit", "job-completed"): 1,
            }
        )
        self.assertEqual(observed, expected)

        decision_method = methods["record_portfolio_decision"]
        decision_payload_lookups = {
            node.args[1].value
            for node in ast.walk(decision_method)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "records_by_payload_text"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        }
        self.assertTrue(
            {
                "portfolio_axis_identity",
                "target_axis_identity",
                "trial_data_contract",
            }.issubset(decision_payload_lookups)
        )
        self.assertTrue(
            any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "has_controlled_chassis_study"
                for node in ast.walk(decision_method)
            )
        )


if __name__ == "__main__":
    unittest.main()
