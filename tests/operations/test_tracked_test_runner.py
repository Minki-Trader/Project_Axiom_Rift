from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPOSITORY_ROOT / "scripts" / "run_tracked_tests.py"


def run(root: Path, *arguments: str) -> None:
    subprocess.run(arguments, cwd=root, check=True, capture_output=True)


def load_runner_module() -> object:
    spec = importlib.util.spec_from_file_location("tracked_test_runner_subject", RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load tracked-test runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TrackedTestRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        run(self.root, "git", "init", "-b", "main")
        run(self.root, "git", "config", "user.email", "test@example.invalid")
        run(self.root, "git", "config", "user.name", "Axiom Test")
        tests = self.root / "tests"
        tests.mkdir()
        (tests / "test_tracked.py").write_text(
            "def test_tracked():\n    assert True\n", encoding="ascii"
        )
        run(self.root, "git", "add", "tests/test_tracked.py")
        run(self.root, "git", "commit", "-m", "Track canonical test")
        (tests / "test_untracked.py").write_text(
            "def test_untracked():\n    assert False\n", encoding="ascii"
        )

    def invoke(
        self, *arguments: str, environment: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        if environment:
            env.update(environment)
        return subprocess.run(
            (
                sys.executable,
                str(RUNNER),
                "--repository-root",
                str(self.root),
                *arguments,
            ),
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )

    def configure_protected_development_inputs(
        self,
        *,
        observed_path: str = "data/processed/datasets/observed.csv",
        observed: bytes = b"development-prefix-fixture\n",
        split: bytes = b'{"schema":"split-fixture"}\n',
        declared_observed_sha256: str | None = None,
        include_observed_block: bool = True,
    ) -> tuple[Path, Path]:
        observed_file = (
            self.root / Path(observed_path)
            if ".." not in observed_path and ":" not in observed_path
            else self.root / "data" / "processed" / "datasets" / "observed.csv"
        )
        processed_file = (
            self.root / "data" / "processed" / "datasets" / "base.csv"
        )
        split_file = (
            self.root
            / "data"
            / "processed"
            / "coverage_audits"
            / "rolling.json"
        )
        observed_file.parent.mkdir(parents=True)
        split_file.parent.mkdir(parents=True)
        observed_file.write_bytes(observed)
        forbidden_tail = b"FORBIDDEN_QUARANTINE_TAIL\n"
        processed_file.write_bytes(observed + forbidden_tail)
        split_file.write_bytes(split)
        foundation = self.root / "foundation"
        foundation.mkdir()
        (self.root / ".gitignore").write_text("data/\n", encoding="ascii")
        observed_block = (
            "observed_development:\n"
            f"  path: {observed_path}\n"
            "  sha256: "
            f"{declared_observed_sha256 or sha256(observed).hexdigest()}\n"
            f"  byte_count: {len(observed)}\n"
            "  row_count: 1\n"
            '  first_time: "2026-01-01 00:00:00"\n'
            '  last_time: "2026-01-01 00:00:00"\n'
            f"  parent_dataset_sha256: {sha256(observed + forbidden_tail).hexdigest()}\n"
            f"  split_artifact_sha256: {sha256(split).hexdigest()}\n"
            "  derivation: exact_prefix_before_quarantined_tail\n"
            if include_observed_block
            else ""
        )
        (foundation / "data.yaml").write_text(
            "schema: data_foundation\n"
            "processed:\n"
            "  path: data/processed/datasets/base.csv\n"
            f"  sha256: {sha256(observed + forbidden_tail).hexdigest()}\n"
            + observed_block
            + (
                "split_artifact:\n"
                "  path: data/processed/coverage_audits/rolling.json\n"
                f"  sha256: {sha256(split).hexdigest()}\n"
                "protection:\n"
                "  ignored_by_git: true\n"
            ),
            encoding="ascii",
        )
        run(
            self.root,
            "git",
            "add",
            ".gitignore",
            "foundation/data.yaml",
        )
        return observed_file, split_file

    def configure_test_evidence(
        self,
        content: bytes = b'{"schema":"test-evidence"}\n',
        *,
        declared_identity: str | None = None,
        materialize: bool = True,
    ) -> tuple[str, Path]:
        identity = declared_identity or sha256(content).hexdigest()
        evidence = (
            self.root
            / "local"
            / "evidence"
            / "sha256"
            / identity[:2]
            / identity
        )
        if materialize:
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_bytes(content)
        (self.root / "tests" / "evidence_inputs.txt").write_text(
            identity + "\n", encoding="ascii"
        )
        run(self.root, "git", "add", "tests/evidence_inputs.txt")
        return identity, evidence

    def test_manifest_excludes_and_reports_untracked_tests(self) -> None:
        result = self.invoke("--manifest-only", "--no-manifest-file")
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        manifest = json.loads(result.stdout)
        self.assertEqual(manifest["tracked_test_count"], 1)
        self.assertEqual(manifest["excluded_untracked_test_count"], 1)
        self.assertEqual(
            manifest["excluded_untracked_tests"],
            ["tests/test_untracked.py"],
        )
        repeated = json.loads(
            self.invoke("--manifest-only", "--no-manifest-file").stdout
        )
        self.assertEqual(
            repeated["manifest_sha256"], manifest["manifest_sha256"]
        )

    def test_runner_passes_exact_tracked_paths_only(self) -> None:
        result = self.invoke("--no-manifest-file", "--", "-q")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1 passed", result.stdout)
        manifest = json.loads(result.stdout.splitlines()[0])
        self.assertEqual(
            manifest["excluded_untracked_tests"], ["tests/test_untracked.py"]
        )

    def test_runner_materializes_only_exact_foundation_development_inputs(self) -> None:
        observed = b"approved-development-prefix-fixture\n"
        split = b'{"schema":"approved-split-fixture"}\n'
        self.configure_protected_development_inputs(
            observed=observed,
            split=split,
        )
        (self.root / "tests" / "test_tracked.py").write_text(
            "from pathlib import Path\n\n"
            "def test_tracked():\n"
            "    prefix = Path('data/processed/datasets/observed.csv').read_bytes()\n"
            f"    assert prefix == {observed!r}\n"
            "    assert b'FORBIDDEN_QUARANTINE_TAIL' not in prefix\n"
            "    assert not Path('data/processed/datasets/base.csv').exists()\n"
            "    assert not Path('.git/objects/info/alternates').exists()\n"
            "    for parent in (Path.cwd(), *Path.cwd().parents):\n"
            "        assert not (parent / 'data/processed/datasets/base.csv').exists()\n"
            "    assert Path('data/processed/coverage_audits/rolling.json')"
            f".read_bytes() == {split!r}\n",
            encoding="ascii",
        )
        run(self.root, "git", "add", "tests/test_tracked.py")

        result = self.invoke("--no-manifest-file", "--", "-q")

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("1 passed", result.stdout)
        manifest = json.loads(result.stdout.splitlines()[0])
        plan = manifest["protected_development_inputs"]
        self.assertEqual(
            plan["authority"], "foundation_declared_protected_input"
        )
        self.assertEqual(plan["input_count"], 2)
        self.assertFalse(plan["scientific_or_claim_authority"])
        self.assertTrue(plan["test_execution_prerequisite_only"])
        self.assertEqual(
            [(item["role"], item["path"]) for item in plan["inputs"]],
            [
                (
                    "observed_development",
                    "data/processed/datasets/observed.csv",
                ),
                (
                    "split_artifact",
                    "data/processed/coverage_audits/rolling.json",
                ),
            ],
        )
        self.assertEqual(
            (self.root / "data/processed/datasets/observed.csv").read_bytes(),
            observed,
        )

    def test_runner_materializes_only_exact_allowlisted_test_evidence(self) -> None:
        content = b'{"schema":"approved-test-evidence"}\n'
        identity, evidence = self.configure_test_evidence(content)
        unlisted_content = b'{"schema":"unlisted-test-evidence"}\n'
        unlisted_identity = sha256(unlisted_content).hexdigest()
        unlisted = (
            evidence.parents[1]
            / unlisted_identity[:2]
            / unlisted_identity
        )
        unlisted.parent.mkdir(parents=True)
        unlisted.write_bytes(unlisted_content)
        (self.root / "tests" / "test_tracked.py").write_text(
            "from pathlib import Path\n\n"
            "def test_tracked():\n"
            f"    approved = Path('local/evidence/sha256/{identity[:2]}/{identity}')\n"
            f"    assert approved.read_bytes() == {content!r}\n"
            f"    assert not Path('local/evidence/sha256/{unlisted_identity[:2]}/"
            f"{unlisted_identity}').exists()\n",
            encoding="ascii",
        )
        run(self.root, "git", "add", "tests/test_tracked.py")

        result = self.invoke("--no-manifest-file", "--", "-q")

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("1 passed", result.stdout)
        plan = json.loads(result.stdout.splitlines()[0])["test_evidence_inputs"]
        self.assertEqual(plan["authority"], "tracked_exact_content_allowlist")
        self.assertEqual(plan["input_count"], 1)
        self.assertEqual(plan["total_size"], len(content))
        self.assertFalse(plan["scientific_or_claim_authority"])
        self.assertTrue(plan["test_execution_prerequisite_only"])
        self.assertEqual(
            [(item["role"], item["path"]) for item in plan["inputs"]],
            [
                (
                    "test_evidence",
                    f"local/evidence/sha256/{identity[:2]}/{identity}",
                )
            ],
        )
        self.assertEqual(evidence.read_bytes(), content)

    def test_test_evidence_missing_or_identity_mismatch_fails_closed(self) -> None:
        missing_identity = "1" * 64
        self.configure_test_evidence(
            declared_identity=missing_identity,
            materialize=False,
        )

        missing = self.invoke("--manifest-only", "--no-manifest-file")

        self.assertEqual(missing.returncode, 1)
        self.assertIn("unavailable", json.loads(missing.stderr)["error"])

        wrong = (
            self.root
            / "local"
            / "evidence"
            / "sha256"
            / missing_identity[:2]
            / missing_identity
        )
        wrong.parent.mkdir(parents=True)
        wrong.write_bytes(b"wrong-content\n")

        mismatch = self.invoke("--manifest-only", "--no-manifest-file")

        self.assertEqual(mismatch.returncode, 1)
        self.assertIn(
            "content identity differs",
            json.loads(mismatch.stderr)["error"],
        )

    def test_mutated_test_evidence_copy_rejects_passing_suite(self) -> None:
        content = b'{"schema":"immutable-test-evidence"}\n'
        identity, evidence = self.configure_test_evidence(content)
        relative = f"local/evidence/sha256/{identity[:2]}/{identity}"
        (self.root / "tests" / "test_tracked.py").write_text(
            "from pathlib import Path\n\n"
            "def test_tracked():\n"
            f"    target = Path({relative!r})\n"
            "    target.chmod(0o666)\n"
            "    target.write_bytes(b'mutated-in-sandbox\\n')\n"
            "    assert True\n",
            encoding="ascii",
        )
        run(self.root, "git", "add", "tests/test_tracked.py")

        result = self.invoke("--no-manifest-file", "--", "-q")

        self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
        self.assertIn("postcondition failed", result.stderr)
        self.assertEqual(evidence.read_bytes(), content)

    def test_protected_input_missing_or_hash_mismatch_fails_closed(self) -> None:
        observed_file, split_file = self.configure_protected_development_inputs()
        split_file.unlink()
        missing = self.invoke("--manifest-only", "--no-manifest-file")
        self.assertEqual(missing.returncode, 1)
        self.assertIn("unavailable", json.loads(missing.stderr)["error"])

        split_file.parent.mkdir(parents=True, exist_ok=True)
        split_file.write_bytes(b'{"schema":"split-fixture"}\n')
        observed_file.write_bytes(b"changed-after-foundation-binding\n")
        mismatch = self.invoke("--manifest-only", "--no-manifest-file")
        self.assertEqual(mismatch.returncode, 1)
        self.assertIn("SHA256 differs", json.loads(mismatch.stderr)["error"])

    def test_protected_input_path_escape_fails_before_materialization(self) -> None:
        self.configure_protected_development_inputs(
            observed_path="data/processed/datasets/../escape.csv"
        )

        result = self.invoke("--manifest-only", "--no-manifest-file")

        self.assertEqual(result.returncode, 1)
        self.assertIn("approved data lane", json.loads(result.stderr)["error"])

    def test_foundation_without_observed_development_fails_closed(self) -> None:
        self.configure_protected_development_inputs(include_observed_block=False)

        result = self.invoke("--manifest-only", "--no-manifest-file")

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "observed development block",
            json.loads(result.stderr)["error"],
        )

    def test_foundation_binding_uses_the_frozen_index_tree(self) -> None:
        observed_file, _ = self.configure_protected_development_inputs()
        old_tree = subprocess.run(
            ("git", "write-tree"),
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        next_file = observed_file.with_name("observed_next.csv")
        next_file.write_bytes(observed_file.read_bytes())
        foundation = self.root / "foundation" / "data.yaml"
        foundation.write_text(
            foundation.read_text(encoding="ascii").replace(
                "data/processed/datasets/observed.csv",
                "data/processed/datasets/observed_next.csv",
            ),
            encoding="ascii",
        )
        run(self.root, "git", "add", "foundation/data.yaml")

        subject = load_runner_module()
        tracked_paths = set(subject._tree_paths(self.root, old_tree))
        plan = subject._protected_development_input_plan(
            self.root,
            index_tree=old_tree,
            tracked_paths=tracked_paths,
        )

        self.assertEqual(
            plan["inputs"][0]["path"],
            "data/processed/datasets/observed.csv",
        )
        self.assertNotEqual(
            old_tree,
            subprocess.run(
                ("git", "write-tree"),
                cwd=self.root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip(),
        )

    def test_foundation_worktree_drift_does_not_replace_index_authority(self) -> None:
        self.configure_protected_development_inputs()
        foundation = self.root / "foundation" / "data.yaml"
        foundation.write_text("schema: poisoned_worktree\n", encoding="ascii")

        result = self.invoke("--manifest-only", "--no-manifest-file")

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        plan = json.loads(result.stdout)["protected_development_inputs"]
        self.assertEqual(plan["input_count"], 2)

    def test_manifest_rejects_index_change_during_construction(self) -> None:
        self.configure_protected_development_inputs()
        foundation = self.root / "foundation" / "data.yaml"
        subject = load_runner_module()

        def mutate_index() -> tuple[dict[str, object], tuple[str, ...]]:
            foundation.write_text(
                foundation.read_text(encoding="ascii") + "# concurrent stage\n",
                encoding="ascii",
            )
            run(self.root, "git", "add", "foundation/data.yaml")
            return ({"runtime_sha256": "0" * 64}, ())

        with patch.object(subject, "_python_runtime", side_effect=mutate_index):
            with self.assertRaisesRegex(RuntimeError, "changed during"):
                subject._manifest(self.root.resolve(), pytest_args=())

    def test_nested_snapshot_reuses_only_parent_bound_runtime_roots(self) -> None:
        subject = load_runner_module()
        runtime_roots = subject._distribution_search_paths()
        (self.root / "src").mkdir()
        run(
            self.root,
            "git",
            "commit",
            "--allow-empty",
            "-m",
            "Isolated tracked-test snapshot",
        )
        inherited_pythonpath = os.pathsep.join(
            (
                str((self.root / "src").resolve()),
                str(self.root.resolve()),
                *runtime_roots,
            )
        )
        with patch.object(
            subject,
            "PROJECT_ROOT",
            self.root.resolve(),
        ), patch.dict(
            os.environ,
            {
                "AXIOM_TRACKED_TEST_PARENT_RUNTIME": "1",
                "PYTHONPATH": inherited_pythonpath,
                "PYTHONSAFEPATH": "1",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            },
        ):
            inherited = subject._inherited_isolated_runtime_paths()
        self.assertEqual(inherited, runtime_roots)

    def test_independent_git_metadata_contains_no_source_repository_path(self) -> None:
        self.configure_protected_development_inputs()
        tree = subprocess.run(
            ("git", "write-tree"),
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        subject = load_runner_module()
        with TemporaryDirectory(prefix="independent-git-test-") as temporary:
            sandbox = Path(temporary).resolve()
            subject._checkout_independent_index_tree(
                self.root.resolve(), sandbox, index_tree=tree
            )
            source_needles = {
                str(self.root.resolve()).encode("utf-8").lower(),
                self.root.resolve().as_posix().encode("utf-8").lower(),
            }
            self.assertFalse(
                (sandbox / ".git" / "objects" / "info" / "alternates").exists()
            )
            for candidate in (sandbox / ".git").rglob("*"):
                if candidate.is_file():
                    content = candidate.read_bytes().lower()
                    self.assertFalse(
                        any(needle in content for needle in source_needles)
                    )

    def test_independent_snapshot_preserves_executable_index_modes(self) -> None:
        hooks = self.root / ".githooks"
        hooks.mkdir()
        hook = hooks / "commit-msg"
        hook.write_bytes(b"#!/bin/sh\nexit 0\n")
        run(self.root, "git", "add", ".githooks/commit-msg")
        run(
            self.root,
            "git",
            "update-index",
            "--chmod=+x",
            "--",
            ".githooks/commit-msg",
        )
        tree = subprocess.run(
            ("git", "write-tree"),
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        subject = load_runner_module()
        with TemporaryDirectory(prefix="independent-mode-test-") as temporary:
            sandbox = Path(temporary).resolve()
            subject._checkout_independent_index_tree(
                self.root.resolve(), sandbox, index_tree=tree
            )
            entry = subprocess.run(
                (
                    "git",
                    "ls-files",
                    "--stage",
                    "--",
                    ".githooks/commit-msg",
                ),
                cwd=sandbox,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        self.assertTrue(entry.startswith("100755 "), entry)

    def test_mutated_sandbox_copy_rejects_otherwise_passing_suite(self) -> None:
        observed = b"immutable-development-prefix\n"
        observed_file, _ = self.configure_protected_development_inputs(
            observed=observed
        )
        (self.root / "tests" / "test_tracked.py").write_text(
            "from pathlib import Path\n\n"
            "def test_tracked():\n"
            "    target = Path('data/processed/datasets/observed.csv')\n"
            "    target.chmod(0o666)\n"
            "    target.write_bytes(b'mutated-in-sandbox\\n')\n"
            "    assert True\n",
            encoding="ascii",
        )
        run(self.root, "git", "add", "tests/test_tracked.py")

        result = self.invoke("--no-manifest-file", "--", "-q")

        self.assertEqual(result.returncode, 1, result.stderr or result.stdout)
        self.assertIn("postcondition failed", result.stderr)
        self.assertEqual(observed_file.read_bytes(), observed)

    def test_link_like_protected_source_fails_closed(self) -> None:
        observed_file, _ = self.configure_protected_development_inputs()
        content = observed_file.read_bytes()
        target = self.root / "outside-observed.csv"
        target.write_bytes(content)
        observed_file.unlink()
        try:
            observed_file.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"file symlinks unavailable: {exc}")

        result = self.invoke("--manifest-only", "--no-manifest-file")

        self.assertEqual(result.returncode, 1)
        self.assertIn("link-like", json.loads(result.stderr)["error"])

    def test_runner_requires_worktree_bytes_to_match_the_git_index(self) -> None:
        tracked = self.root / "tests" / "test_tracked.py"
        tracked.write_text(
            "def test_tracked():\n    assert 1 + 1 == 2\n", encoding="ascii"
        )
        rejected = self.invoke("--manifest-only", "--no-manifest-file")
        self.assertEqual(rejected.returncode, 1)
        error = json.loads(rejected.stderr)
        self.assertIn("differ from the Git index blob", error["error"])
        run(self.root, "git", "add", "tests/test_tracked.py")
        accepted = self.invoke("--manifest-only", "--no-manifest-file")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

    def test_manifest_batches_git_blob_work_by_bounded_file_groups(self) -> None:
        tests = self.root / "tests"
        (tests / "test_untracked.py").unlink()
        for ordinal in range(130):
            (tests / f"test_batch_{ordinal:03d}.py").write_text(
                f"def test_batch_{ordinal:03d}():\n    assert True\n",
                encoding="ascii",
            )
        run(self.root, "git", "add", "tests")
        subject = load_runner_module()
        original_git = subject._git
        calls: list[tuple[str, ...]] = []

        def observed_git(root: Path, *arguments: str) -> bytes:
            calls.append(tuple(arguments))
            return original_git(root, *arguments)

        with patch.object(
            subject,
            "_git",
            side_effect=observed_git,
        ), patch.object(
            subject,
            "_python_runtime",
            return_value=({"runtime_sha256": "0" * 64}, ()),
        ):
            manifest, tracked, _runtime = subject._manifest(
                self.root.resolve(), pytest_args=()
            )

        self.assertEqual(manifest["tracked_test_count"], 131)
        self.assertEqual(len(tracked), 131)
        hash_calls = [call for call in calls if call[:1] == ("hash-object",)]
        self.assertEqual(len(hash_calls), 3)
        self.assertFalse(any(call[:1] == ("show",) for call in calls))
        self.assertFalse(
            any(
                call[:1] == ("rev-parse",)
                and len(call) == 2
                and ":tests/" in call[1]
                for call in calls
            )
        )

    def test_skip_worktree_cannot_hide_index_blob_mismatch(self) -> None:
        tracked = self.root / "tests" / "test_tracked.py"
        run(
            self.root,
            "git",
            "update-index",
            "--skip-worktree",
            "tests/test_tracked.py",
        )
        tracked.write_text(
            "def test_tracked():\n    assert False\n", encoding="ascii"
        )
        rejected = self.invoke("--manifest-only", "--no-manifest-file")
        self.assertEqual(rejected.returncode, 1)
        error = json.loads(rejected.stderr)
        self.assertIn("index blob", error["error"])

    def test_untracked_conftest_and_pytest_environment_cannot_inject(self) -> None:
        (self.root / "tests" / "test_tracked.py").write_text(
            "import os, site, tempfile\n"
            "from pathlib import Path\n\n"
            "def test_tracked():\n"
            "    assert site.ENABLE_USER_SITE is not True\n"
            "    for key in ('PYTHONUSERBASE', 'PYTHONWARNINGS', "
            "'COVERAGE_PROCESS_START', 'COV_CORE_SOURCE', "
            "'AXIOM_TEST_SECRET_SENTINEL', 'AXIOM_TEST_HOST_PATH'):\n"
            "        assert key not in os.environ\n"
            "    root = Path.cwd().resolve()\n"
            "    for key in ('HOME', 'USERPROFILE', 'TEMP', 'TMP'):\n"
            "        value = Path(os.environ[key]).resolve()\n"
            "        assert root not in value.parents\n"
            "        assert value not in root.parents\n"
            "        assert root.parent in value.parents\n"
            "    fixture = Path(tempfile.mkdtemp()).resolve()\n"
            "    assert root not in fixture.parents\n"
            "    assert root.parent in fixture.parents\n"
            "    assert not any((parent / '.git').exists() "
            "for parent in (fixture, *fixture.parents))\n",
            encoding="ascii",
        )
        run(self.root, "git", "add", "tests/test_tracked.py")
        (self.root / "tests" / "conftest.py").write_text(
            "raise RuntimeError('untracked conftest executed')\n", encoding="ascii"
        )
        result = self.invoke(
            "--no-manifest-file",
            "--",
            "-q",
            environment={
                "PYTEST_ADDOPTS": "tests/test_untracked.py",
                "PYTEST_PLUGINS": "tests.test_untracked",
                "PYTHONUSERBASE": str(self.root / "poison-user-base"),
                "PYTHONWARNINGS": "error",
                "COVERAGE_PROCESS_START": str(self.root / "poison.coveragerc"),
                "COV_CORE_SOURCE": "poison",
                "AXIOM_TEST_SECRET_SENTINEL": "must-not-reach-child",
                "AXIOM_TEST_HOST_PATH": str(self.root),
            },
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("1 passed", result.stdout)

    def test_pytest_path_or_plugin_arguments_are_rejected(self) -> None:
        for injected in ("tests/test_untracked.py", "-p", "--collect-only"):
            with self.subTest(injected=injected):
                result = self.invoke(
                    "--no-manifest-file", "--", "-q", injected
                )
                self.assertEqual(result.returncode, 1)
                error = json.loads(result.stderr)
                self.assertIn("collection or plugin", error["error"])

    def test_runtime_projection_is_rebuilt_and_clone_origin_is_detached(self) -> None:
        (self.root / "OPERATING_DIRECTION.md").write_text(
            "fixture\n", encoding="ascii"
        )
        (self.root / ".gitignore").write_text("local/\n", encoding="ascii")
        (self.root / "state").mkdir()
        (self.root / "state" / "control.json").write_text(
            "{}\n", encoding="ascii"
        )
        (self.root / "records").mkdir()
        (self.root / "records" / "journal.jsonl").write_text(
            "{}\n", encoding="ascii"
        )
        package = self.root / "src" / "axiom_rift"
        (package / "operations").mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="ascii")
        (package / "operations" / "__init__.py").write_text(
            "", encoding="ascii"
        )
        (package / "operations" / "writer.py").write_text(
            "# rebuild trigger fixture\n", encoding="ascii"
        )
        (package / "cli.py").write_text(
            "from pathlib import Path\n"
            "import json, os, site, subprocess\n"
            "root = Path.cwd()\n"
            "assert site.ENABLE_USER_SITE is not True\n"
            "assert 'PYTHONUSERBASE' not in os.environ\n"
            "assert 'COVERAGE_PROCESS_START' not in os.environ\n"
            "assert subprocess.run(('git', 'remote'), capture_output=True, "
            "check=True).stdout == b''\n"
            "(root / 'local').mkdir(exist_ok=True)\n"
            "(root / 'local' / 'index.sqlite').write_bytes(b'rebuilt')\n"
            "print(json.dumps({'schema': 'axiom_recovery', "
            "'index_rebuilt': True}, sort_keys=True))\n",
            encoding="ascii",
        )
        (self.root / "tests" / "test_tracked.py").write_text(
            "from pathlib import Path\n\n"
            "def test_tracked():\n"
            "    assert Path('local/index.sqlite').read_bytes() == b'rebuilt'\n",
            encoding="ascii",
        )
        (self.root / "tests" / "test_untracked.py").unlink()
        run(self.root, "git", "add", ".")
        (self.root / "local").mkdir()
        (self.root / "local" / "index.sqlite").write_bytes(b"poison")

        result = self.invoke(
            "--no-manifest-file",
            "--",
            "-q",
            environment={
                "PYTHONUSERBASE": str(self.root / "poison-user-base"),
                "COVERAGE_PROCESS_START": str(self.root / "poison.coveragerc"),
            },
        )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("1 passed", result.stdout)
        manifest = json.loads(result.stdout.splitlines()[0])
        self.assertEqual(
            manifest["runtime_projection"],
            {
                "authority": "git_index_tree_journal",
                "mode": "explicit_recovery",
            },
        )
        self.assertNotIn("runtime_inputs", manifest)


if __name__ == "__main__":
    unittest.main()
