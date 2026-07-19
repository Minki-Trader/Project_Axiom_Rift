"""Activate the bounded-validation and Writer-decomposition authority patch."""

from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.operations.writer import StateWriter  # noqa: E402


OPERATION_ID = "harness-quality-and-writer-decomposition-authority-v1"
AUTHORITY_PATHS = (
    "OPERATING_DIRECTION.md",
    "contracts/evidence.yaml",
    "contracts/operations.yaml",
    "contracts/science.yaml",
)


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    if text.count(old) != 1:
        raise RuntimeError(f"{label} predecessor differs")
    return text.replace(old, new, 1)


def _operating_direction(text: str) -> str:
    if "OD-AUD-049 StateWriter remains the sole public transition facade" in text:
        return text
    replacements = (
        (
            """- [MUST] OD-REC-018 Prospective Study-close delivery is mechanically enforced.
  The tracked commit-msg hook reads the staged Journal, control, and KPI bytes,
  requires all three paths in one commit, deterministically rerenders the KPI,
  and accepts only one contiguous final trailer block bound to the exact close
  event and revision. Bypassing the hook is prohibited. Routine StateWriter
  boundaries verify the exact guard, a tamper-evident local high-water, and only
  the new delivery suffix. A separate explicit maintenance action may rebuild
  that projection by a complete audit. Missing, modified, or malformed delivery
  evidence blocks later scientific mutation without making routine cost grow
  with all historical closes.
""",
            """- [MUST] OD-REC-018 Prospective Study-close delivery is mechanically enforced.
  The tracked commit-msg hook requires staged control, the resolved Journal
  suffix, and the tracked checkpoint in one commit, validates the new immutable
  study-kpi record and exact final trailers, and forbids routine KPI Markdown
  changes. Routine StateWriter guards read only the checkpoint, local-main
  relation, bounded no-close suffix, and retained origin-attempt receipt; they
  never fetch, push, refresh a remote ref, write a receipt or projection, render
  KPI Markdown, or scan complete history. Only the explicit post-commit
  `update_study_close_delivery_checkpoint.py --attempt-origin` action performs
  one bounded fetch and non-force push attempt and records delivered or delivery
  debt. Ordinary descendants and no-close checkpoints reuse the close-producing
  receipt. Missing or malformed evidence routes to that explicit action or full
  maintenance and blocks later scientific mutation without hidden routine cost.
""",
            "OD-REC-018",
        ),
        (
            """- [MUST] OD-AUD-014 Architecture family identity is semantic: stable component
  roles, causal boundaries, and runtime bindings define the family. Artifact
  hashes remain Component and Executable identity, not gratuitous family splits.
""",
            """- [MUST] OD-AUD-014 Architecture family identity is semantic: stable component
  roles, dependency-domain topology, causal boundaries, and runtime categories
  define the family. Historical architecture_chassis.v2 and Executable identities
  remain immutable. Prospective scheduling and review use additive semantic v4;
  implementation or artifact hashes, library or build versions, protocol release
  suffixes, seeds, and experiment parameter values cannot create family splits.
  Without complete Component context the Writer preserves v2 and invents no v4.
""",
            "OD-AUD-014",
        ),
        (
            """- [MUST] OD-AUD-016 Validation protects the changed surface and claim at risk.
  Routine checks use keyed projections, immutable-segment verification caches,
  and suffix guards; complete audits are explicit maintenance, not per-Job delay.
""",
            """- [MUST] OD-AUD-016 Validation protects the changed surface and claim at risk.
  Routine checks use keyed projections, immutable-segment verification caches,
  bounded suffix guards, and sparse focused test snapshots; complete audits are
  explicit maintenance, not per-Job delay. Once an exact audit or replay
  correctness obligation and resume condition are closed, unrelated performance,
  refactor, or historical-polish debt is nonblocking unless it invalidates the
  current decision basis.
""",
            "OD-AUD-016",
        ),
        (
            """- [MUST] OD-AUD-022 Comparison state and scientific state are distinct. A
  criterion may compare as passed, failed, or not_evaluable while its claim
  contribution remains supported, contradicted, unresolved, invalid, or
  diagnostic. Terminal and scheduler readers use only the scientific state.
""",
            """- [MUST] OD-AUD-022 Comparison state and scientific state are distinct. A
  criterion may compare as passed, failed, or not_evaluable while its claim
  contribution remains supported, contradicted, unresolved, invalid, or
  diagnostic. Terminal and scheduler readers use only the scientific state.
  The registered_control_contrast is a noncompensatory primary causal gate:
  contradicted or unresolved control cannot be offset by other positive claims,
  and prospective confirmation must list that control explicitly as supported.
""",
            "OD-AUD-022",
        ),
        (
            """- [MUST] OD-AUD-023 An audit-created replay duty is a typed P0 or P1
  ReplayObligation with pending, in_progress, satisfied, or deferred lifecycle,
  the exact original Executable and claim criteria, and a bounded satisfaction
  or defer condition. P0 blocks affected scientific credit; P1 receives the
  highest information-value bounded opportunity without freezing unrelated
  valid research.
""",
            """- [MUST] OD-AUD-023 An audit-created replay duty is a typed P0 or P1
  ReplayObligation with pending, in_progress, satisfied, or deferred lifecycle,
  the exact original Executable and claim criteria, and a bounded satisfaction
  or defer condition. P0 blocks affected scientific credit; P1 receives the
  highest information-value bounded opportunity without freezing unrelated
  valid research. Every replay-bound Decision retains an unchosen structural
  option on another axis whose primary layer differs or whose verified semantic
  v4 family differs. Labels, actions, or builds alone are insufficient; this is
  option quality, not a calendar or consecutive-run quota.
""",
            "OD-AUD-023",
        ),
        (
            """- [MUST] OD-AUD-028 A repository-wide engineering run uses a Git-index-bound
  tracked-test manifest with exact path and byte identities and reports excluded
  untracked tests. Untracked or unrelated user work never silently expands,
  shrinks, or supplies acceptance authority.
""",
            """- [MUST] OD-AUD-028 A repository-wide engineering run uses a Git-index-bound
  tracked-test manifest with exact path and byte identities and reports excluded
  untracked tests. A focused run remains index-bound but materializes only the
  selected tests, indexed src tree, ambient pytest configuration, ancestor
  conftest files, declared extra dependencies, and explicitly requested protected
  inputs. Only all-tracked or explicit recovery uses the full index tree.
  Untracked or unrelated work never changes acceptance authority.
""",
            "OD-AUD-028",
        ),
        (
            """- [MUST] OD-AUD-030 Git delivery checks fail closed when the repository, HEAD,
  required local-main relation, hook, checkpoint, or authenticated path is
  absent or malformed. Only a typed isolated engineering fixture may bypass a
  real-worktree check, and it cannot create scientific authority.
""",
            """- [MUST] OD-AUD-030 Git delivery checks fail closed when the repository, HEAD,
  required local-main relation, hook, checkpoint, authenticated path, or retained
  origin-attempt receipt is absent or malformed. The routine guard is local,
  read-only, and side-effect-free; missing delivery routes to the explicit bounded
  origin action. Only a typed isolated engineering fixture may bypass a real-
  worktree check, and it cannot create scientific authority.
""",
            "OD-AUD-030",
        ),
        (
            """- [MUST] OD-AUD-039 Exact-index engineering tests may materialize only the
  protected development inputs named by the indexed Foundation manifest. Paths,
  roles, hashes, sizes, and independent copies fail closed; the inputs are test
  prerequisites only and create no scientific or claim authority.
""",
            """- [MUST] OD-AUD-039 Exact-index focused tests may materialize protected
  development inputs only when the selected frozen test bytes explicitly declare
  the required input role and the indexed Foundation manifest names it. Paths,
  roles, hashes, sizes, and independent copies fail closed; absent declaration
  means zero protected inputs. They remain test prerequisites only and create no
  scientific or claim authority.
""",
            "OD-AUD-039",
        ),
        (
            """- [MUST] OD-AUD-048 Target-specific historical-family authority for pending
  replay members is admitted once per exact immutable family, in one bounded
  Writer event when useful. Admission reauthenticates source bytes, original
  Study, Batch, member order, parameters, controls, and current pending heads;
  it creates no trial, claim, candidate, holdout, satisfaction, or scheduling
  change. Missing admission authority cannot justify repeating a family per
  member.
""",
            """- [MUST] OD-AUD-048 Target-specific historical-family authority for pending
  replay members is admitted once per exact immutable family, in one bounded
  Writer event when useful. Admission reauthenticates source bytes, original
  Study, Batch, member order, parameters, controls, and current pending heads;
  it creates no trial, claim, candidate, holdout, satisfaction, or scheduling
  change. Missing admission authority cannot justify repeating a family per
  member.
- [MUST] OD-AUD-049 StateWriter remains the sole public transition facade and
  owner of the atomic commit path. Large transition families belong to focused
  domain modules that can commit only through that facade; they are not
  independent writers. Public imports remain compatible, and a new large domain
  family is extracted instead of appended to the central facade.
""",
            "OD-AUD-049",
        ),
    )
    for old, new, label in replacements:
        text = _replace_once(text, old, new, label=label)
    return text


def _operations(text: str) -> str:
    if "writer_decomposition:" in text:
        return text
    text = _replace_once(
        text,
        """  local_projection: local/index.sqlite
  single_writer: axiom_rift.operations.writer.StateWriter
transaction:
""",
        """  local_projection: local/index.sqlite
  single_writer: axiom_rift.operations.writer.StateWriter
  writer_decomposition:
    public_transition_facade: axiom_rift.operations.writer.StateWriter
    atomic_commit_owner: axiom_rift.operations.writer.StateWriter._commit
    domain_mixins_are_independent_writers: false
    domain_mixins_commit_only_through_facade_atomic_path: true
    public_import_compatibility_preserved: true
    new_large_transition_family_requires_focused_domain_module: true
transaction:
""",
        label="operations Writer decomposition",
    )
    text = _replace_once(
        text,
        """  writer_derives_history_summary_and_followup_constraints: true
  architecture_review_trigger:
""",
        """  writer_derives_history_summary_and_followup_constraints: true
  prospective_architecture_projection:
    snapshot_field: prospective_architecture_projection
    projection_schema: portfolio_axis_architecture_semantic.v1
    family_schema: architecture_chassis_semantic.v4
    writer_derived_additive_not_portfolio_identity: true
    current_axis_only: true
    conflict_fails_recovery: true
    legacy_identity_rewrite_allowed: false
    v2_only_missing_component_context_may_invent_v4: false
  study_diagnosis_admission:
    exact_writer_derived_claim_pattern_required: true
    registered_control_support_required_for_confirmation: true
    contradicted_or_unresolved_control_is_noncompensatory: true
    legacy_claimless_v1_remains_readable: true
  architecture_review_trigger:
""",
        label="operations prospective research admission",
    )
    text = _replace_once(
        text,
        """    boot_delivery_audit:
      basis: prospective_study_kpi_records_and_exact_commit_trailers
      exact_unique_trailer_commit_reachable_from_local_ref: true
      commit_changes_all_required_same_commit_paths: true
      commit_snapshot_bounded_journal_suffix_matches_event: true
      commit_snapshot_control_and_index_heads_match_event: true
      commit_snapshot_new_kpi_record_and_checkpoint_transition_valid: true
      complete_kpi_projection_scan_required: false
      local_commit_absence_requires_resume_before_state_or_science_action: true
      refresh_remote_tracking_ref_before_observation: true
      remote_relation: closeout_commit_ancestor_of_remote_ref
      remote_absence_requires_immediate_push_attempt: true
""",
        """    boot_delivery_audit:
      basis: tracked_checkpoint_bounded_suffix_and_retained_origin_attempt
      exact_unique_trailer_commit_reachable_from_local_ref: true
      commit_changes_all_required_same_commit_paths: true
      commit_snapshot_bounded_journal_suffix_matches_event: true
      commit_snapshot_control_and_index_heads_match_event: true
      commit_snapshot_new_kpi_record_and_checkpoint_transition_valid: true
      complete_kpi_projection_scan_required: false
      local_commit_absence_requires_resume_before_state_or_science_action: true
      routine_fetch_push_or_remote_refresh_allowed: false
      routine_receipt_projection_or_kpi_write_allowed: false
      missing_receipt_routes_to_explicit_origin_delivery: true
    explicit_origin_delivery:
      command: scripts/update_study_close_delivery_checkpoint.py --attempt-origin
      trigger: post_commit
      bounded_fetch_and_non_force_push_attempt: true
      receipt: local/study-close-origin-attempt.json
      receipt_schema: study_close_origin_attempt.v1
      outcomes:
        - delivered
        - delivery_debt
      failed_attempt_revokes_science: false
      no_close_boundary_creates_new_network_obligation: false
""",
        label="operations Study-close delivery split",
    )
    text = _replace_once(
        text,
        """validation_economics:
  routine_study_close_delivery_basis: tamper_evident_high_water_and_new_suffix
  complete_history_scan: explicit_maintenance_only
""",
        """validation_economics:
  routine_study_close_delivery_basis: tracked_checkpoint_bounded_suffix_and_retained_origin_attempt
  routine_network_or_receipt_write_allowed: false
  explicit_origin_delivery_action_required_when_receipt_missing: true
  complete_history_scan: explicit_maintenance_only
""",
        label="operations routine delivery economics",
    )
    text = _replace_once(
        text,
        """  routine_validation_reads: checkpoint_boundary_and_bounded_suffix
  routine_active_segment_prefix_rehash_required: false
""",
        """  routine_validation_reads: checkpoint_bounded_suffix_and_retained_origin_attempt
  routine_network_or_write_allowed: false
  routine_active_segment_prefix_rehash_required: false
""",
        label="operations checkpoint routine reads",
    )
    text = _replace_once(
        text,
        """      defer_requires_exact_resume_condition: true
      satisfaction_invalidation:
""",
        """      defer_requires_exact_resume_condition: true
      portfolio_option_quality:
        replay_bound_only: true
        unchosen_structural_alternative_required: true
        different_axis_required: true
        different_primary_layer_or_verified_distinct_v4_family_required: true
        same_layer_unknown_family_fails_closed: true
        fixed_calendar_or_consecutive_quota: false
      satisfaction_invalidation:
""",
        label="operations replay option quality",
    )
    text = _replace_once(
        text,
        """      focused_selection_preserves_full_frozen_manifest: true
      focused_selection_rebuilds_runtime_projection_by_default: false
""",
        """      focused_selection_preserves_full_frozen_manifest: false
      focused_snapshot_materializes:
        - selected_frozen_tests
        - complete_indexed_src_tree
        - ambient_pytest_configuration
        - ancestor_conftest_files
        - explicitly_declared_extra_dependencies
        - explicitly_requested_protected_inputs
      full_git_index_tree_only_for_all_tracked_or_explicit_projection_recovery: true
      focused_input_role_declaration_source: selected_frozen_test_bytes
      focused_selection_rebuilds_runtime_projection_by_default: false
""",
        label="operations focused manifest scope",
    )
    text = _replace_once(
        text,
        """        declaration_source: indexed_foundation_data_manifest
        allowed_roles:
""",
        """        declaration_source: indexed_foundation_data_manifest
        focused_materialization_requires_role: protected_development
        allowed_roles:
""",
        label="operations focused protected-input opt-in",
    )
    return text


def _science(text: str) -> str:
    if "prospective_architecture_family:" in text:
        return text
    text = _replace_once(
        text,
        """  axis:
    primary_research_layer_required: true
""",
        """  prospective_architecture_family:
    historical_chassis_v2_and_executable_identity_immutable: true
    family_schema: architecture_chassis_semantic.v4
    used_for:
      - portfolio_scheduling
      - structural_comparison
      - architecture_review
    retains_role_dependency_topology_causal_boundaries_and_runtime_category: true
    implementation_artifact_build_library_protocol_seed_or_parameter_value_splits_family: false
    context_incomplete_legacy_may_invent_v4: false
  axis:
    primary_research_layer_required: true
""",
        label="science prospective architecture family",
    )
    text = _replace_once(
        text,
        """    writer_derives_allowed_actions_and_layers: true
  next_decision_must_follow_dispose_or_structurally_exit: true
""",
        """    writer_derives_allowed_actions_and_layers: true
    primary_control_gate:
      claim_id: registered_control_contrast
      supported_requires_confirmation_requires_explicit_support: true
      contradicted_or_unresolved_is_noncompensatory: true
      uniformly_contradicted_state: absent_information
      uniformly_contradicted_reason: registered_control_contrast_uniformly_contradicted
      legacy_claimless_v1_reconstructible: true
  next_decision_must_follow_dispose_or_structurally_exit: true
""",
        label="science diagnosis control gate",
    )
    text = _replace_once(
        text,
        """  structural_forest_exit_requires_different_primary_layer_or_architecture: true
  architecture_review:
""",
        """  structural_forest_exit_requires_different_primary_layer_or_architecture: true
  replay_bound_option_quality:
    unchosen_structural_alternative_required: true
    different_axis_required: true
    different_primary_layer_or_verified_distinct_prospective_family_required: true
    unknown_same_layer_family_fails_closed: true
    rigid_calendar_or_consecutive_quota: false
  architecture_review:
""",
        label="science replay forest quality",
    )
    text = _replace_once(
        text,
        """    P1_blocks_unrelated_valid_research: false
    progress_requires_exact_new_to_original_executable_match: true
""",
        """    P1_blocks_unrelated_valid_research: false
    audit_completeness_alone_creates_serial_replay_monopoly: false
    exact_correctness_and_resume_closure_ends_blocking: true
    unrelated_polish_performance_or_refactor_debt_is_nonblocking_unless_current_basis_invalid: true
    progress_requires_exact_new_to_original_executable_match: true
""",
        label="science replay non-monopoly",
    )
    return text


def _evidence(text: str) -> str:
    if "registered_control_contrast_is_primary_causal_gate" in text:
        return text
    text = _replace_once(
        text,
        """  dimensions_are_non_compensatory: true
  release_artifact_must_be_referenced_job_durable_output: true
""",
        """  dimensions_are_non_compensatory: true
  registered_control_contrast_is_primary_causal_gate: true
  other_supported_dimensions_may_compensate_for_failed_or_unresolved_control: false
  axis_confirmation_requires_explicit_supported_registered_control_contrast: true
  release_artifact_must_be_referenced_job_durable_output: true
""",
        label="evidence primary control claims",
    )
    text = _replace_once(
        text,
        """    exact_writer_derived_evidence_basis_required: true
    caller_kpi_or_failure_prose_is_authority: false
""",
        """    exact_writer_derived_evidence_basis_required: true
    prospective_claim_pattern_must_match_writer_derivation: true
    legacy_claimless_v1_remains_readable: true
    caller_kpi_or_failure_prose_is_authority: false
""",
        label="evidence diagnosis admission",
    )
    return text


def replacements(root: Path = ROOT) -> dict[str, bytes]:
    transforms = {
        "OPERATING_DIRECTION.md": _operating_direction,
        "contracts/evidence.yaml": _evidence,
        "contracts/operations.yaml": _operations,
        "contracts/science.yaml": _science,
    }
    result: dict[str, bytes] = {}
    for relative, transform in transforms.items():
        text = transform((root / relative).read_text(encoding="ascii"))
        if relative.endswith(".yaml"):
            parsed = yaml.safe_load(text)
            if not isinstance(parsed, dict):
                raise RuntimeError(f"{relative} replacement is not a mapping")
        result[relative] = text.encode("ascii")
    return result


def plan(root: Path = ROOT) -> dict[str, object]:
    planned = replacements(root)
    control = StateWriter(root).read_control()
    if control is None:
        raise RuntimeError("authority plan requires control")
    return {
        "current_manifest_digest": control["authority"]["manifest_digest"],
        "operation_id": OPERATION_ID,
        "replacement_sha256": {
            path: sha256(content).hexdigest()
            for path, content in sorted(planned.items())
        },
        "schema": "harness_quality_authority_plan.v1",
    }


def apply(root: Path = ROOT) -> dict[str, object]:
    writer = StateWriter(root)
    before = writer.read_control()
    if before is None:
        raise RuntimeError("authority migration requires control")
    before = deepcopy(before)
    migration = writer.migrate_authority(
        replacements=replacements(root),
        reason=(
            "align focused validation, semantic architecture, diagnosis, replay, "
            "delivery, and Writer decomposition authority"
        ),
        operation_id=OPERATION_ID,
        allow_active_stable_boundary=True,
    )
    after = writer.read_control()
    if after is None:
        raise RuntimeError("authority migration lost control")
    for field in ("initiative", "next_action", "scientific"):
        if after[field] != before[field]:
            raise RuntimeError(f"authority migration changed {field}")
    return {
        "event_id": migration.event_id,
        "manifest_digest": after["authority"]["manifest_digest"],
        "reused": migration.reused,
        "revision": after["revision"],
        "schema": "harness_quality_authority_result.v1",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = apply(ROOT) if args.apply else plan(ROOT)
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
