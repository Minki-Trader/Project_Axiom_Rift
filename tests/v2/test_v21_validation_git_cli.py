from __future__ import annotations

import io
import json
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import yaml

from axiom_rift.v2.cli import (
    GoalActionError,
    build_parser,
    load_goal_action,
    load_validation_surface,
    main,
    reconcile_state,
    structured_goal_action,
)
from axiom_rift.v2.git_closeout import (
    git_preflight,
    scoped_git_closeout,
    verify_content_checkpoint,
    verify_metadata_checkpoint,
)
from axiom_rift.v2.identity import ObjectStore
from axiom_rift.v2.ledger import HashChainLedger
from axiom_rift.v2.validation.budget import (
    IdenticalFailedValidationError,
    SliceValidationBudget,
    ValidationBudgetError,
    ValidationDurationExceeded,
)
from axiom_rift.v2.validation.receipts import ValidationReceiptStore


def receipt_store(root: Path) -> ValidationReceiptStore:
    return ValidationReceiptStore(
        ObjectStore(root / "objects"),
        HashChainLedger(root / "receipts.jsonl", "validation_receipt"),
    )


class SliceValidationBudgetTests(unittest.TestCase):
    def test_cached_success_spends_no_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = receipt_store(root)
            store.record(
                "VR1",
                "2026-07-10T00:00:00Z",
                {"validation_key": "key-pass", "outcome": "pass", "issues": []},
            )
            budget = SliceValidationBudget("SL1", store)

            authorization = budget.authorize_validation("key-pass")

            self.assertTrue(authorization.cache_hit)
            self.assertFalse(authorization.budget_spent)
            self.assertEqual(budget.validation_used, 0)

    def test_identical_failed_key_is_not_retried(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            store = receipt_store(root)
            store.record(
                "VR1",
                "2026-07-10T00:00:00Z",
                {"validation_key": "key-fail", "outcome": "fail", "issues": ["broken"]},
            )
            budget = SliceValidationBudget("SL1", store)

            with self.assertRaises(IdenticalFailedValidationError):
                budget.authorize_validation("key-fail")
            self.assertEqual(budget.validation_used, 0)

    def test_validate_repair_recheck_and_duration_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            budget = SliceValidationBudget("SL1", receipt_store(Path(temp_dir)))
            budget.authorize_validation("key-1")
            with self.assertRaises(ValidationBudgetError):
                budget.authorize_validation("key-2")
            budget.authorize_repair()
            with self.assertRaises(ValidationBudgetError):
                budget.authorize_repair()
            budget.authorize_validation("key-3", recheck=True)
            with self.assertRaises(ValidationBudgetError):
                budget.authorize_validation("key-4", recheck=True)
            budget.check_duration(30.0)
            with self.assertRaises(ValidationDurationExceeded):
                budget.check_duration(30.000001)


GIT = shutil.which("git")


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [GIT or "git", *args],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )


def initialize_temp_repo(root: Path) -> tuple[Path, Path]:
    remote = root / "remote.git"
    repo = root / "work"
    remote.mkdir()
    repo.mkdir()
    run_git(remote, "init", "--bare")
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.email", "v21@example.invalid")
    run_git(repo, "config", "user.name", "V21 Test")
    (repo / "declared.txt").write_text("initial declared\n", encoding="ascii")
    (repo / "unrelated.txt").write_text("initial unrelated\n", encoding="ascii")
    run_git(repo, "add", "--", "declared.txt", "unrelated.txt")
    run_git(repo, "commit", "-m", "initial")
    run_git(repo, "remote", "add", "origin", remote.as_posix())
    run_git(repo, "push", "-u", "origin", "main")
    return repo, remote


@unittest.skipUnless(GIT, "git is required")
class ScopedGitCloseoutTests(unittest.TestCase):
    def test_declared_paths_only_are_committed_and_pushed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo, remote = initialize_temp_repo(Path(temp_dir))
            (repo / "declared.txt").write_text("changed declared\n", encoding="ascii")
            (repo / "unrelated.txt").write_text("changed unrelated\n", encoding="ascii")

            result = scoped_git_closeout(repo, ("declared.txt",), "v21 scoped closeout")

            self.assertTrue(result.ok, result.to_payload())
            self.assertEqual(result.push_attempts, 1)
            self.assertEqual(result.head, result.remote_head)
            self.assertEqual(run_git(repo, "show", "HEAD:declared.txt").stdout, "changed declared\n")
            remote_unrelated = run_git(remote, "show", f"{result.remote_head}:unrelated.txt").stdout
            self.assertEqual(remote_unrelated, "initial unrelated\n")
            self.assertIn("unrelated.txt", run_git(repo, "status", "--short").stdout)

    def test_preflight_rejects_staged_paths_outside_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo, _ = initialize_temp_repo(Path(temp_dir))
            (repo / "unrelated.txt").write_text("staged unrelated\n", encoding="ascii")
            run_git(repo, "add", "--", "unrelated.txt")

            result = git_preflight(repo, ("declared.txt",))

            self.assertFalse(result.ok)
            self.assertEqual(result.blocker.code, "unscoped_staged_paths")

    def test_rejected_push_returns_structured_blocker_after_at_most_one_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo, remote = initialize_temp_repo(Path(temp_dir))
            hook = remote / "hooks" / "pre-receive"
            hook.write_text("#!/bin/sh\necho rejected-by-test >&2\nexit 1\n", encoding="ascii")
            hook.chmod(0o755)
            (repo / "declared.txt").write_text("push must fail\n", encoding="ascii")

            result = scoped_git_closeout(repo, ("declared.txt",), "rejected closeout")

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.push_attempts, 2)
            self.assertEqual(result.blocker.code, "push_failed")
            self.assertEqual(result.blocker.external_state_required, "remote_or_auth_state")

    def test_content_and_metadata_checkpoints_are_derived_without_third_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo, _ = initialize_temp_repo(Path(temp_dir))
            control = repo / "registries" / "v2" / "control_state.yaml"
            control.parent.mkdir(parents=True)
            control.write_text("revision: 1\n", encoding="ascii")
            run_git(repo, "add", "--", "registries/v2/control_state.yaml")
            run_git(repo, "commit", "-m", "content A")
            run_git(repo, "push", "origin", "main")
            content_commit = run_git(repo, "rev-parse", "HEAD").stdout.strip()

            content = verify_content_checkpoint(
                repo,
                control,
                content_commit,
                ("registries/v2/control_state.yaml",),
            )
            self.assertTrue(content.ok, content.to_payload())

            control.write_text("revision: 2\n", encoding="ascii")
            (repo / "registries" / "v2" / "evidence_ledger.jsonl").write_text(
                "{}\n", encoding="ascii"
            )
            run_git(repo, "add", "--", "registries/v2")
            run_git(repo, "commit", "-m", "metadata B")
            sync = {
                "status": "metadata_pending_push",
                "validated_content_commit": content_commit,
                "metadata_allowed_paths": [
                    "registries/v2/control_state.yaml",
                    "registries/v2/evidence_ledger.jsonl",
                ],
            }
            before_push = verify_metadata_checkpoint(repo, sync)
            self.assertFalse(before_push.ok)
            self.assertEqual("metadata_not_pushed", before_push.code)

            run_git(repo, "push", "origin", "main")
            bad_scope = verify_metadata_checkpoint(
                repo,
                {**sync, "metadata_allowed_paths": ["registries/v2/control_state.yaml"]},
            )
            self.assertFalse(bad_scope.ok)
            self.assertEqual("metadata_scope_violation", bad_scope.code)
            after_push = verify_metadata_checkpoint(repo, sync)
            self.assertTrue(after_push.ok, after_push.to_payload())
            self.assertEqual(content_commit, after_push.validated_content_commit)
            self.assertEqual(content_commit, run_git(repo, "rev-parse", "HEAD^").stdout.strip())


class BoundedCliTests(unittest.TestCase):
    def test_cli_surface_is_bounded(self) -> None:
        parser = build_parser()
        action = next(item for item in parser._actions if item.dest == "command")
        self.assertEqual(
            set(action.choices),
            {
                "status",
                "goal-run",
                "resume",
                "validate-surface",
                "reconcile-state",
                "diagnostic-validate-bootstrap",
            },
        )

    def test_goal_action_is_deterministic_single_step_and_does_not_invent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "action.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "schema": "axiom_rift_v21_goal_action_v1",
                        "goal_id": "V2G0002",
                        "action_id": "V2A0001",
                        "action_kind": "execute_declared_job",
                        "parameters": {
                            "job_id": "V2S0002",
                            "job_kind": "scout",
                            "spec_object_id": "a" * 64,
                            "hypothesis_id": "V2H0002",
                        },
                    },
                    sort_keys=False,
                ),
                encoding="ascii",
            )
            action = load_goal_action(path)
            first = structured_goal_action(action, mode="goal-run")
            second = structured_goal_action(action, mode="goal-run")

            self.assertEqual(first, second)
            self.assertEqual(first["bounded_steps"], 1)
            self.assertFalse(first["daemon"])
            self.assertFalse(first["hypothesis_invented"])
            self.assertFalse(first["side_effects_executed"])
            resumed = structured_goal_action(action, mode="resume", resume_token="V2A0001")
            self.assertEqual(resumed["action_sha256"], first["action_sha256"])
            with self.assertRaises(GoalActionError):
                structured_goal_action(action, mode="resume", resume_token="different")

    def test_goal_action_rejects_arbitrary_import_or_missing_hypothesis(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.yaml"
            payload = {
                "schema": "axiom_rift_v21_goal_action_v1",
                "goal_id": "V2G0002",
                "action_id": "V2A0001",
                "action_kind": "execute_declared_job",
                "parameters": {
                    "job_id": "V2S0002",
                    "job_kind": "scout",
                    "spec_object_id": "a" * 64,
                    "module": "arbitrary.module",
                },
            }
            path.write_text(yaml.safe_dump(payload), encoding="ascii")
            with self.assertRaises(GoalActionError):
                load_goal_action(path)

    def test_declared_validation_surface_is_returned_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "configs/v2/validation_surfaces.yaml"
            config.parent.mkdir(parents=True)
            config.write_text(
                yaml.safe_dump(
                    {
                        "schema": "axiom_rift_v21_validation_surfaces_v1",
                        "surfaces": {
                            "research_core": {
                                "checks": ["research_core_unit"],
                                "forbidden": ["mt5_test", "model_training"],
                            }
                        },
                    }
                ),
                encoding="ascii",
            )
            declaration = load_validation_surface(root, "research_core")
            self.assertEqual(declaration["focused_checks"], ["research_core_unit"])
            output = io.StringIO()
            with redirect_stdout(output):
                return_code = main(
                    [
                        "validate-surface",
                        "--surface",
                        "research_core",
                        "--slice-id",
                        "SL1",
                    ],
                    root=root,
                )
            self.assertEqual(return_code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["execution"], "declaration_only")
            self.assertFalse(payload["evidence_jobs_launched"])

    def test_reconcile_state_is_read_only_and_finite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            registry = root / "registries/v2"
            registry.mkdir(parents=True)
            state_path = registry / "control_state.yaml"
            state_path.write_text(
                yaml.safe_dump(
                    {
                        "schema": "axiom_rift_v2_control_state_v1",
                        "revision": 1,
                        "status": "active",
                        "active_truth": "v2",
                        "goal_id": "V2G0002",
                        "cursor": {"stage": "H", "exact_next_action": "declared_action"},
                        "claim": {"current_level": "none"},
                        "reentry": {},
                        "ledger_heads": {
                            "hypothesis": None,
                            "evidence": None,
                            "material": None,
                            "validation_receipt": None,
                        },
                    },
                    sort_keys=False,
                ),
                encoding="ascii",
            )
            before = state_path.read_bytes()

            result = reconcile_state(root)

            self.assertEqual(result["status"], "aligned")
            self.assertEqual(result["bounded_steps"], 1)
            self.assertFalse(result["mutation_performed"])
            self.assertFalse(result["daemon"])
            self.assertEqual(state_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
