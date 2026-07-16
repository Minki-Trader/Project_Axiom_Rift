from __future__ import annotations

import ast
from pathlib import Path
import subprocess
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
MAINTENANCE_SCRIPT = REPO_ROOT / "scripts" / "audit_live_canonical_test_boundaries.py"


def tracked_source(relative: str) -> str:
    completed = subprocess.run(
        ("git", "ls-files", "--error-unmatch", "--", relative),
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout.strip() == relative
    return (REPO_ROOT / relative).read_text(encoding="ascii")


def tracked_test_sources() -> tuple[tuple[str, str], ...]:
    completed = subprocess.run(
        ("git", "ls-files", "-z", "--", "tests"),
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    paths = tuple(
        item.decode("ascii")
        for item in completed.stdout.split(b"\0")
        if item.endswith(b".py")
    )
    return tuple(
        (relative, (REPO_ROOT / relative).read_text(encoding="ascii"))
        for relative in paths
    )


def defined_functions(source: str) -> frozenset[str]:
    return frozenset(
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _repository_path_parts(node: ast.AST) -> tuple[str, ...] | None:
    if isinstance(node, ast.Name) and node.id in {
        "REPO_ROOT",
        "REPOSITORY_ROOT",
        "ROOT",
    }:
        return (node.id,)
    if (
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Div)
        and isinstance(node.right, ast.Constant)
        and type(node.right.value) is str
    ):
        prefix = _repository_path_parts(node.left)
        if prefix is not None:
            return (*prefix, node.right.value)
    return None


def live_authority_violations(relative: str, source: str) -> tuple[str, ...]:
    tree = ast.parse(source, filename=relative)
    violations: set[str] = set()
    authority_paths = {
        ("state", "control.json"),
        ("local", "index.sqlite"),
        ("records", "journal.jsonl"),
    }
    platform_skip_terms = (
        "hard link",
        "link fixture",
        "reparse-point",
        "symbolic link",
        "symlink",
    )
    for node in ast.walk(tree):
        parts = _repository_path_parts(node)
        if parts is not None and (
            tuple(parts[1:]) in authority_paths
            or tuple(parts[1:2]) == ("records",)
            and tuple(parts[2:3]) == ("journal",)
        ):
            violations.add(f"repository authority path at line {node.lineno}")
        if not isinstance(node, ast.Call) or not node.args:
            continue
        function = node.func
        call_name = (
            function.id
            if isinstance(function, ast.Name)
            else function.attr
            if isinstance(function, ast.Attribute)
            else None
        )
        if call_name in {"skip", "skipIf", "skipUnless", "skipTest"}:
            skip_text = " ".join(
                child.value
                for child in ast.walk(node)
                if isinstance(child, ast.Constant)
                and type(child.value) is str
            ).lower()
            if not any(term in skip_text for term in platform_skip_terms):
                violations.add(f"non-platform skip at line {node.lineno}")
        if not (
            isinstance(function, ast.Name)
            and function.id == "StateWriter"
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id in {"REPO_ROOT", "REPOSITORY_ROOT", "ROOT"}
        ):
            continue
        engineering_fixture = next(
            (
                keyword.value
                for keyword in node.keywords
                if keyword.arg == "engineering_fixture"
            ),
            None,
        )
        if not (
            isinstance(engineering_fixture, ast.Constant)
            and engineering_fixture.value is True
        ):
            violations.add(f"live StateWriter at line {node.lineno}")
    return tuple(sorted(violations))


class DefaultTestAuthorityBoundaryTests(unittest.TestCase):
    def test_implementation_inventory_has_no_filename_bypass(self) -> None:
        source = tracked_source("tests/research/test_implementation_identity.py")
        tree = ast.parse(source)
        constants = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and type(node.value) is str
        }
        self.assertIn("ls-files", constants)
        self.assertIn("src/axiom_rift/research/*.py", constants)
        self.assertNotIn("tlt_source", constants)

    def test_default_tests_do_not_read_live_authority_or_skip_by_phase(self) -> None:
        for relative, source in tracked_test_sources():
            with self.subTest(path=relative):
                self.assertEqual(live_authority_violations(relative, source), ())

    def test_live_checks_exist_only_at_explicit_maintenance_boundary(self) -> None:
        self.assertTrue(MAINTENANCE_SCRIPT.is_file())
        self.assertFalse(MAINTENANCE_SCRIPT.name.startswith("test_"))
        source = MAINTENANCE_SCRIPT.read_text(encoding="ascii")
        functions = defined_functions(source)
        for test_name in (
            "test_frozen_report_and_pure_authority_transforms_are_exact",
            "test_read_only_plan_binds_exact_replay_family_without_state_change",
            "test_completed_validation_does_not_require_reproducible_cache_presence",
            "test_read_only_design_retains_every_axis_and_binds_frozen_report",
            "test_job_spec_closes_the_exact_component_implementation_bundle",
            "test_spread_time_read_only_plan_rederives_all_seven_events_without_mutation",
        ):
            with self.subTest(test_name=test_name):
                self.assertIn(test_name, functions)
        calls = {
            node.func.attr
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn("skip", calls)
        self.assertNotIn("skipUnless", calls)

    def test_exhaustive_live_plan_invariants_use_synthetic_authority(self) -> None:
        source = tracked_source(
            "tests/operations/test_exhaustive_audit_replay_correction.py"
        )
        self.assertIn(
            "test_read_only_plan_does_not_mutate_control_journal_or_index",
            defined_functions(source),
        )
        self.assertIn('len(plan["authority_replacement_sha256"]), 4', source)
        self.assertIn("SUBJECT.REVIEWED_INVALIDATION_MANIFEST_SHA256", source)

    def test_historical_stu0061_checks_are_deterministic(self) -> None:
        source = tracked_source("tests/operations/test_stu0061_replay_runner.py")
        functions = defined_functions(source)
        for test_name in (
            "test_runner_recovers_predecessor_from_first_operation",
            "test_runner_contains_no_frozen_future_state_boundary",
            "test_frozen_family_separates_recorded_and_current_trace_lineage",
            "test_runner_recovers_one_to_three_registered_family_members",
        ):
            with self.subTest(test_name=test_name):
                self.assertIn(test_name, functions)
        self.assertNotIn(
            "test_root_no_argument_runner_fails_closed_at_pre_activation_drift",
            functions,
        )
        self.assertNotIn(
            "test_typed_correction_sandbox_builds_exact_current_family_read_only",
            functions,
        )


if __name__ == "__main__":
    unittest.main()
