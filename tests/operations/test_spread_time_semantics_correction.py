from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "apply_spread_time_semantics_correction.py"


def _load_script():
    name = "apply_spread_time_semantics_correction_for_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_script_has_no_hardcoded_predecessor_commit_or_delivery_mutation() -> None:
    source = SCRIPT.read_text("ascii")
    assert "PREDECESSOR_COMMIT" not in source
    assert '"commit"' not in source
    assert '"push"' not in source
    assert "--apply" in source
    assert "apply(explicit_recovery=arguments.recover)" in source
    assert "--recover requires --apply" in source


def test_apply_boundary_precedes_evidence_and_is_rechecked_before_mutation() -> None:
    tree = ast.parse(SCRIPT.read_text("ascii"))
    apply_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "apply"
    )

    def call_name(call: ast.Call) -> str:
        function = call.func
        if isinstance(function, ast.Name):
            return function.id
        if isinstance(function, ast.Attribute):
            return function.attr
        return ""

    calls = [node for node in ast.walk(apply_node) if isinstance(node, ast.Call)]
    boundary_lines = sorted(
        call.lineno
        for call in calls
        if call_name(call) == "require_local_main_correction_boundary"
    )
    evidence_line = next(
        call.lineno
        for call in calls
        if call_name(call) == "_materialize_apply_evidence"
    )
    recovery_line = next(
        call.lineno
        for call in calls
        if call_name(call) == "recover_exact_trailing_event"
    )
    assert not [call for call in calls if call_name(call) == "recover"]
    append_line = next(
        call.lineno for call in calls if call_name(call) == "expect_next_event"
    )
    assert len(boundary_lines) >= 3
    assert boundary_lines[0] < evidence_line < boundary_lines[1]
    assert boundary_lines[1] < recovery_line
    assert boundary_lines[1] < append_line


def test_correction_governance_contract_binds_exact_execution_boundaries() -> None:
    operations = yaml.safe_load(
        (ROOT / "contracts" / "operations.yaml").read_text("ascii")
    )
    startup = operations["authority_migration"][
        "local_main_correction_delivery"
    ]["canonical_apply_python_startup"]
    execution = operations["project_goal_audit_correction"][
        "correction_event_execution"
    ]
    assert startup[
        "isolated_no_site_no_user_site_ignore_environment_and_safe_path_required"
    ] is True
    assert startup[
        "python_implementation_version_executable_and_pyyaml_record_provenance_are_plan_bound"
    ] is True
    assert startup[
        "empty_private_pycache_prefix_and_no_bytecode_write_required"
    ] is True
    assert execution[
        "one_shot_full_canonical_event_preappend_expectation_required"
    ] is True
    assert execution[
        "independently_derived_full_semantic_row_mapping_is_core_bound"
    ] is True
    assert execution[
        "independently_derived_full_operation_result_mapping_is_core_bound"
    ] is True
    assert execution[
        "independently_derived_full_event_control_mapping_is_required"
    ] is True
    assert execution[
        "events_four_through_six_control_delta_is_exact_typed_scheduler_constraints_only"
    ] is True
    assert execution[
        "independent_index_record_count_and_projection_digest_chain_is_required"
    ] is True
    assert execution[
        "independent_sequence_predecessor_global_offset_and_event_id_chain_is_required"
    ] is True
    assert execution[
        "subset_identity_payload_status_fingerprint_or_result_comparison_allowed"
    ] is False
    assert execution[
        "apply_boundary_is_verified_before_any_durable_evidence_mutation"
    ] is True
    assert execution[
        "apply_boundary_binds_supplied_control_and_journal_snapshot_to_exact_worktree_bytes"
    ] is True
    assert execution[
        "apply_boundary_independently_assembles_full_control_from_the_verified_prefix"
    ] is True
    assert execution[
        "apply_boundary_is_reverified_after_evidence_readback_before_recovery_or_append"
    ] is True
    assert execution["recovery_without_a_verified_correction_suffix_allowed"] is False
    assert execution[
        "recovery_requires_exact_trailing_event_and_full_predecessor_projection_audit"
    ] is True
    assert execution["recovery_admission_and_mutation_share_one_writer_lock"] is True
    assert execution["canonical_correction_may_call_generic_recover"] is False

    research_skill = (
        ROOT / ".agents" / "skills" / "run-research-portfolio" / "SKILL.md"
    ).read_text("ascii")
    router = (ROOT / "AGENTS.md").read_text("ascii")
    assert "evidence_completion_validity_invalid" in research_skill
    assert "MqlRates.spread" in research_skill
    assert "deferred_requires_reopen" in research_skill
    for route in (
        "completion-scientific-validity invalidation",
        "replay-priority escalation",
        "historical-cost-semantics latch activation",
    ):
        assert route in router


def test_missing_cost_writer_api_blocks_apply_gate_not_read_only_construction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()

    class FakeWriter:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

    for method in module._REQUIRED_WRITER_METHODS:
        setattr(FakeWriter, method, lambda self: None)
    FakeWriter.record_historical_cost_semantics_latch = None
    monkeypatch.setattr(module, "StateWriter", FakeWriter)

    assert isinstance(module._writer(require_apply_api=False), FakeWriter)
    with pytest.raises(module.SpreadTimeCorrectionError):
        module._writer(require_apply_api=True)
