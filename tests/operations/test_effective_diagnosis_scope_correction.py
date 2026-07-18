from __future__ import annotations

import ast
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/apply_effective_diagnosis_scope_correction.py"


def _tree() -> ast.Module:
    return ast.parse(SCRIPT.read_text(encoding="ascii"), filename=str(SCRIPT))


def _calls(node: ast.AST, name: str) -> tuple[ast.Call, ...]:
    return tuple(
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id == name
    )


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    found = tuple(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    assert len(found) == 1
    return found[0]


@pytest.mark.parametrize("mode", ("--plan", "--apply", "--recover"))
def test_exact_modes_require_isolated_no_site_startup(mode: str) -> None:
    completed = subprocess.run(
        (sys.executable, str(SCRIPT), mode),
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        timeout=30,
    )

    assert completed.returncode != 0
    assert "exact effective diagnosis correction modes require" in (
        completed.stdout + completed.stderr
    )


def test_apply_uses_one_baseline_reconstruction_and_no_full_preview() -> None:
    tree = _tree()
    apply = _function(tree, "apply")
    preview = _function(tree, "_preview")

    assert len(_calls(apply, "_shadow")) == 1
    assert not _calls(apply, "_preview")
    assert len(_calls(preview, "_shadow")) == 1


def test_replay_derives_exact_diagnosis_semantics_before_mutation() -> None:
    tree = _tree()
    replay = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "_ReplaySession"
    )
    append = next(
        node
        for node in replay.body
        if isinstance(node, ast.FunctionDef) and node.name == "append"
    )
    derivations = _calls(append, "_derive_expected_diagnosis_action")
    mutations = _calls(append, "_perform_action")

    assert len(derivations) == len(mutations) == 1
    assert derivations[0].lineno < mutations[0].lineno


def test_audited_origin_checkpoint_is_immutable_ancestor() -> None:
    tree = _tree()
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "EXPECTED_ORIGIN_MAIN_COMMIT"
            for target in node.targets
        )
    )
    expected = ast.literal_eval(assignment.value)
    ancestry = subprocess.run(
        ("git", "merge-base", "--is-ancestor", expected, "HEAD"),
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="ascii",
        timeout=30,
    )
    control = json.loads(
        subprocess.run(
            ("git", "show", f"{expected}:state/control.json"),
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="ascii",
            timeout=30,
        ).stdout
    )

    assert ancestry.returncode == 0
    assert control["revision"] == 5708
    assert control["heads"]["journal"] == {
        "event_id": (
            "f95050a5dca1ba2a956a20dfc1a0495f0fda612be35ccb513021ce8e525b7769"
        ),
        "sequence": 5708,
    }
