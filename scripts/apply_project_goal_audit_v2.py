from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping, Sequence

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.operations.validation import EvidenceValidatorRegistry  # noqa: E402
from axiom_rift.operations.writer import RecoveryRequired, StateWriter  # noqa: E402
from axiom_rift.research.protocol import (  # noqa: E402
    ResearchProtocol,
    ResearchProtocolActivation,
)
from axiom_rift.research.replay_obligation import (  # noqa: E402
    ReplayResolutionScope,
    ReplaySatisfaction,
)
from axiom_rift.research.validation_v2 import (  # noqa: E402
    ScientificAdjudicationValidatorV2,
)
from axiom_rift.operations.study_close_checkpoint import (  # noqa: E402
    CHECKPOINT_PATH,
    CHECKPOINT_SCHEMA,
    StudyCloseDeliveryCheckpoint,
)
from axiom_rift.operations.study_close_git import (  # noqa: E402
    StudyCloseDeliveryError,
    inspect_tracked_study_close_delivery,
    require_local_main,
    require_study_close_guard_ready,
)
from axiom_rift.storage.index import LocalIndex  # noqa: E402


AUDIT_REPORT_RELATIVE_PATH = Path(
    "records/audits/2026-07-14_project_goal_audit_v2.md"
)
INTEGRATION_ADDENDUM_RELATIVE_PATH = Path(
    "records/audits/2026-07-14_project_goal_audit_v2_integration_addendum.md"
)
EXPECTED_REPORT_SHA256 = (
    "1f86b0800bb4d4bf7b6d6b903cfbe70736da40d9efed437fce35b6fc3eb655bc"
)
EXPECTED_REPORT_SIZE = 15466
EXPECTED_REPORT_MARKERS = (
    "status: second_pass_complete_pending_prospective_p1_replay",
    "control_revision: 4935",
    "control_event: a13c697cd559749efa6a1dac2983faabcf8db6507c522a1776faa7cf09ec78d0",
    "holdout_reads: 0",
    "quarantine_reads: 0",
    "candidate_claim_delta: 0",
    "release_claim_delta: 0",
    "audit does not claim that replay has run or passed.",
    "### V2-14 P2: a reconstructible SQLite projection polluted the worktree",
    "A real stable-head read created `state/index.sqlite3`.",
)
EXPECTED_ADDENDUM_SHA256 = (
    "052d3c039e811f7140bc54bf003eb0ff4def8d9db490e89d481cd152886ab82d"
)
EXPECTED_ADDENDUM_SIZE = 17811
EXPECTED_ADDENDUM_MARKERS = (
    "status: integration_findings_repaired_pending_activation_and_p1_execution",
    "parent_report_sha256: 1f86b0800bb4d4bf7b6d6b903cfbe70736da40d9efed437fce35b6fc3eb655bc",
    "### V2-I01: completion scope was widened into axis-wide exclusion",
    "### V2-I04: vectorized family evaluation preceded full trial registration",
    "### V2-I10: a shared source outage could not enter an exact wait",
    "### V2-I11: exact-index testing omitted protected development prerequisites",
    "### V2-I12: a Component bundle digest had no durable artifact bytes",
    "### V2-I13: isolated testing copied the quarantined parent material",
    "### V2-I14: implementation closure stopped at direct facade modules",
    "### V2-I15: isolated Git metadata and host environment disclosed the source host",
    "The Project Goal remains active.",
)

EXPECTED_INITIAL_REVISION = 4935
EXPECTED_INITIAL_EVENT_ID = (
    "a13c697cd559749efa6a1dac2983faabcf8db6507c522a1776faa7cf09ec78d0"
)
EXPECTED_INITIAL_AUTHORITY_MANIFEST = (
    "4501b53541568485dbc43ed8c6f0d600a5960d99d6a76db99e300d9e001fd680"
)
EXPECTED_MISSION_ID = "MIS-0006"
EXPECTED_V2_VALIDATOR_ID = (
    "validator:f883c146fcd16e47312182f476cc574e6fa67e248ae1de3e5bd666e468f40f4b"
)
EXPECTED_INITIAL_ACTION = {
    "kind": "choose_next_initiative_or_terminal",
    "mission_id": EXPECTED_MISSION_ID,
}
REPLAY_STUDY_ID = "STU-0105"

AUTHORITY_OPERATION_ID = "project-goal-audit-v2-authority"
PROTOCOL_OPERATION_ID = "project-goal-audit-v2-activate-protocol"
REPLAY_OPERATION_ID = "project-goal-audit-v2-record-replay-correction"
AUTHORITY_REASON = (
    "activate second-pass evidence replay, data isolation, and delivery corrections"
)


@dataclass(frozen=True, slots=True)
class CorrectionStep:
    operation_id: str
    event_kind: str


STEPS = (
    CorrectionStep(AUTHORITY_OPERATION_ID, "authority_migrated"),
    CorrectionStep(PROTOCOL_OPERATION_ID, "research_protocol_activated"),
    CorrectionStep(REPLAY_OPERATION_ID, "historical_replay_correction_recorded"),
)

ADJUDICATION_RECORD_IDS = tuple(
    sorted(
        (
            "historical-adjudication:1b8316d9cf2c8e0c0690e946777d948f555a6225305a3c2ed5661fa7609c74a1",
            "historical-adjudication:c3a274985327f47dafe9fd2646b2af2327fe47590ebacfad771c4919b7a272b7",
            "historical-adjudication:ef2e758385189af51095bf91d7ab9fb0fc9d57115ea741cbd07331561685c667",
            "historical-adjudication:926d16d6109993be8db8f1f261a5c5cf6d231996b0a9ccb88e02e2808bf07b60",
            "historical-adjudication:2d55072ee7ad30b0a834297fa79c1ccc93e80dd3b0c88850e80ec9838184d042",
            "historical-adjudication:72ed4986a684c9a5d8853f92a41577993ed52d8f845ef463431ad6defd874b06",
            "historical-adjudication:572c336b044c1617782ebb34b8d6a79e419fa5018a3fb727e0cc5114dc57d8cf",
            "historical-adjudication:d3f8298c3a3d547f871b7e788a39ca294a797523392a7be45314a082104bb280",
            "historical-adjudication:690beb59b19775474b0df8a9c47dcb82bc30fc2084bbfbecdd5460d66b758e22",
            "historical-adjudication:643ec8884e757ec1f6c3baed6706c9ff1405b4c398628bdbe08bc09b6f653c3b",
            "historical-adjudication:df114fb1ff63794b3f35ca305b72e726f6cd1182e739b17f0f24d86c04c794d3",
            "historical-adjudication:4e59c82733cab309f8210a09d83dc4b0a842689abf3a028413c0de8686d1da18",
            "historical-adjudication:c6007ca8c2a0b277ceace3e056b17b5c50cf7d39a8e96f3b2f0910ad44a7916d",
        )
    )
)
EXPECTED_P0_OBLIGATION_IDS = tuple(
    sorted(
        (
            "historical-replay-obligation:409f9584ccc73f10df1c0f9170d2162542d9e8f21e5d13f9528d9bb498b7e9bc",
            "historical-replay-obligation:a3c2ec0c0a30ae893b104c73b63449d7a880b0b95371767ad0091b7cd183be95",
            "historical-replay-obligation:adde922feac0e2bb6d5eefa1fb5f4407ecde862f4509059a873f35224e2918ef",
            "historical-replay-obligation:ccae0263f1eed51ec85e598dfa7a07be423760c35970796ea2e0f8e9c1fb8bff",
            "historical-replay-obligation:d7fd0428985e7f085686608777ff56061e94500f52df9eaa281f49e182315048",
            "historical-replay-obligation:e4eeb9ab30c30549c153486dc49ac05d3c3e80e581dc01a1cced418ca71466f1",
        )
    )
)
EXPECTED_P1_OBLIGATION_IDS = tuple(
    sorted(
        (
            "historical-replay-obligation:218391cba288e0e97fba30047cc277de1339cd310338728058f976fbac4b0d89",
            "historical-replay-obligation:2fba53f243135ffb9836d1859f3ee11bbab99c9b6a5e6087ffdb2e122036994e",
            "historical-replay-obligation:56799cac8878850c33c0fe59b35ae43425d8ea0f2446f3db1db66c592f63adc8",
            "historical-replay-obligation:5d369574dc42c01849cad0c50b2bdec1632f9bb837cc5a07ca19a537b3813b1e",
            "historical-replay-obligation:76e0d687a149430422231dd36c1853456dccf34724af77309d218455b94aecfa",
            "historical-replay-obligation:a8da0fda7ff53c1951c59bf2bdc4fb8db722cf21c2090dd2e5220c5d2069a904",
            "historical-replay-obligation:c537b4ebc7085331cd21e52c26fbc994728c0520d5474473cc246f4e8c85322e",
        )
    )
)
EXPECTED_STU0061_OBLIGATION_ID = (
    "historical-replay-obligation:56799cac8878850c33c0fe59b35ae43425d8ea0f2446f3db1db66c592f63adc8"
)
EXPECTED_SCOPE_OVERLAY_ID = (
    "historical-evidence-scope:10ba053123fb6697ee4c839a491161d0206e6a4855367438c5c48c2294784ff4"
)

EXPECTED_PRE_V2_AUTHORITY_SHA256 = {
    "OPERATING_DIRECTION.md": "91b8130fa03e8e759c3d7d36640ab426a16ca9aa4cda40e3f3fcd9d782fef4bf",
    "contracts/evidence.yaml": "fbe092b96bb9de6545c5dc50e0b74d7237f85a4273cd0a66976e6ee771707e5d",
    "contracts/operations.yaml": "ffc766b24a207b34fb15ff17521f4c5b9729e5c09acadc739d2a699058bcaca1",
    "contracts/science.yaml": "3df192328a004a1fa53b4355b4e60e29ff0bb1fc02006005b80321d8231c1b7b",
    "foundation/data.yaml": "39138ff9304468d2f9d98feb49ead174f2aab299ae2ca2e4aa70a18853c5efa3",
}

EXPECTED_AUTHORITY_SHA256 = {
    "OPERATING_DIRECTION.md": "af90e2f4b6b51d0441f499a640f5b91d0886e741fd5641cbbe01e246bb3c5804",
    "contracts/evidence.yaml": "73c1ca0e82690c709f25d837408e00fbb0e2a2bb9dd0c3c48ba95b0e7c8c38f1",
    "contracts/operations.yaml": "60280c5964c67e02d974a16e95677a33b41eb895056311a95dbe3e63ccc7d80b",
    "contracts/science.yaml": "a5d0fd389b9c32d0a1c064eb228fbd514a13f8d188aca04f3c7a0cd819b8e919",
    "foundation/data.yaml": "f0467a7c6dca1c8738f0788a633c60166622e7925e098e96d38ab8adc1b4b131",
}

OBSERVED_DEVELOPMENT_RELATIVE_PATH = Path(
    "data/processed/datasets/us100_m5_observed_development.csv"
)
EXPECTED_OBSERVED_DEVELOPMENT_SHA256 = (
    "a7f097242f46ab45e8f58387c35a76a8c7d8ea1b04519f0878b66747442acbbe"
)
EXPECTED_OBSERVED_DEVELOPMENT_SIZE = 37029769

OD_V2_BLOCK = """- [MUST] OD-AUD-019 An evidence-mode name, caller declaration, cache artifact, or
  prior verdict is not a capability. A mode receives scientific or terminal
  credit only when the registered validator recomputes its exact protocol from
  durable subject-bound inputs and opens every declared proof artifact.
- [MUST] OD-AUD-020 Audit-integrity work can establish reconstruction and
  provenance only. Its effective evidence scope is `audit_integrity`; it creates
  no causal, temporal, regime, stress, cost, economic, exhaustion, candidate, or
  terminal credit. Additive scope overlays remove mistaken historical credit
  without rewriting the original event.
- [MUST] OD-AUD-021 Scientific evidence preserves an exact plan, atomic support,
  statistical proof, execution trace, and result. The trace binds protocol,
  data, split, Executable, decision, entry and exit times, fold and regime,
  gross PnL, native cost, stress cost, and result attribution. Summary metrics
  or cached point values alone cannot establish the proof.
- [MUST] OD-AUD-022 Comparison state and scientific state are distinct. A
  criterion may compare as passed, failed, or not_evaluable while its claim
  contribution remains supported, contradicted, unresolved, invalid, or
  diagnostic. Terminal and scheduler readers use only the scientific state.
- [MUST] OD-AUD-023 An audit-created replay duty is a typed P0 or P1
  ReplayObligation with pending, in_progress, satisfied, or deferred lifecycle,
  the exact original Executable and claim criteria, and a bounded satisfaction
  or defer condition. P0 blocks affected scientific credit; P1 receives the
  highest information-value bounded opportunity without freezing unrelated
  valid research.
- [MUST] OD-AUD-024 Replay progress binds each new Executable to at most one exact
  original Executable. Position, display order, first-trial fallback, Study-wide
  substitution, and family-level evidence cannot satisfy an unmatched member.
  Effective-scope overlays, not rewritten history, govern later credit.
- [MUST] OD-AUD-025 Portfolio snapshots are immutable observations. Scheduling,
  architecture review, and terminal reasoning use a current effective-axis
  projection that applies source invalidations, replay obligations, and scope
  overlays. An invalidated source axis is never restored; research resumes only
  through a new eligible SourceContract and a new axis identity.
- [MUST] OD-AUD-026 An economic composite must execute actual member trades with
  declared timing, exposure netting, native and stressed costs, and portfolio
  drawdown attribution. A bundle label, combined significance score, or
  collection of component summaries is not composite economic evidence.
- [MUST] OD-AUD-027 Prospective implementation authority closes the exact chain
  from current Component bytes and semantic dependencies through Executable to
  Job implementation artifacts. Historical modules with embedded Mission or
  Study identities are frozen reconstruction surfaces and cannot be registered
  for prospective work.
- [MUST] OD-AUD-028 A repository-wide engineering run uses a Git-index-bound
  tracked-test manifest with exact path and byte identities and reports excluded
  untracked tests. Untracked or unrelated user work never silently expands,
  shrinks, or supplies acceptance authority.
- [MUST] OD-AUD-029 Study-close checkpoint v2 binds the authenticated historical
  KPI-backfill proof and every prospective close, is monotone across close and
  no-close boundaries, and advances only with exact staged bytes. Routine
  verification is a fast bounded suffix check; complete reconstruction is an
  explicit full-maintenance action.
- [MUST] OD-AUD-030 Git delivery checks fail closed when the repository, HEAD,
  required local-main relation, hook, checkpoint, or authenticated path is
  absent or malformed. Only a typed isolated engineering fixture may bypass a
  real-worktree check, and it cannot create scientific authority.
- [MUST] OD-AUD-031 Validation is proportionate to the changed reusable surface
  and claim at risk. Slow full-history, full-suite, and exact-staging audits are
  coherent maintenance or delivery checks, not repeated per-experiment gates;
  they do not delay an otherwise permitted bounded scientific Job.
- [MUST] OD-AUD-032 Scientific judgment uses plural quant-team lenses for
  causality, statistics, economics, execution, risk, data, and architecture.
  The harness enforces identities, permits, budgets, and claim boundaries but
  does not replace bounded autonomous judgment with one scalar score, rigid
  calendar rotation, or serial single-branch policy.
- [MUST] OD-AUD-033 A corrected harness or audit replay does not satisfy a
  scientific ReplayObligation by implication. The exact prospective protocol
  must execute, validly recompute, and adjudicate every original subject-bound
  criterion, whether supported or contradicted, or record the typed unresolved
  or deferred condition honestly.
- [MUST] OD-AUD-034 Permanent source invalidation retires an old axis only
  through additive SourceReplacementLineage that binds the exact invalidation,
  an eligible distinct SourceContract, and a distinct replacement axis. The old
  axis then receives no scientific or terminal credit and is not schedulable;
  the replacement and unrelated eligible forest axes remain independently
  schedulable. An external wait requires the exact unresolved source-replacement
  capability or, for a shared outage, its typed sorted unique capability set.
- [MUST] OD-AUD-035 An external resume action preserves the exact canonical
  typed next action, including ordered replay-obligation bindings. Lossy scalar
  coercion, generic nested payloads, or a restored action that differs from the
  frozen action is not reentry authority.
- [MUST] OD-AUD-036 A concurrent scientific family is a typed Batch-bound set of
  exact Executable identities. Every member is durably registered before any
  member Job is declared, started, or evaluated; runner ordering is not an
  engine capability.
- [MUST] OD-AUD-037 Reproducible-cache provenance follows the exact named
  producer declaration, start, permit consumption, engine entry, completion,
  trace, and outputs. A later attempt sharing a work fingerprint cannot replace
  or validate the named producer.
- [MUST] OD-AUD-038 Authority activation planning is local and read-only.
  Network observation and receipt mutation belong only to an explicit delivery
  readiness phase, and activation binds exact old-to-new authority rows,
  authenticated checkpoint state, local main, and frozen audit provenance.
- [MUST] OD-AUD-039 Exact-index engineering tests may materialize only the
  protected development inputs named by the indexed Foundation manifest. Paths,
  roles, hashes, sizes, and independent copies fail closed; the inputs are test
  prerequisites only and create no scientific or claim authority.
- [MUST] OD-AUD-040 A Component implementation-bundle digest closes only when
  the exact bytes hashing to that digest and every source dependency bound by
  the bundle are durable Job artifacts. A digest label or source list without
  the exact bundle bytes is not implementation evidence.
- [MUST] OD-AUD-041 Observed development is a separately content-addressed
  prefix bound to its parent dataset and split. Routine science and engineering
  tests materialize that prefix, never the quarantined parent; full-parent
  access is limited to sealed integrity maintenance and creates no reveal or
  claim authority.
- [MUST] OD-AUD-042 An implementation bundle includes the complete
  project-local semantic dependency closure reached by its execution roots.
  A delegated implementation change that leaves the bundle identity unchanged
  is not closed implementation evidence.
- [MUST] OD-AUD-043 Exact-index testing exposes neither source-repository Git
  metadata nor the ambient host environment to collected tests. The executable
  sandbox is a standalone snapshot with minimum explicit environment inputs and
  sandbox-confined home and temporary paths."""

SCIENCE_V2_BLOCK = """project_goal_audit_v2_protocol:
  quant_team_judgment:
    plural_lenses_required: true
    universal_scalar_decision_score_allowed: false
    harness_selects_scientific_allocation: false
    harness_enforces_bounds_but_does_not_choose_judgment: true
  implementation_closure:
    component_current_bytes_and_semantic_dependencies_required: true
    executable_contains_every_participating_component_identity: true
    job_artifacts_cover_every_executable_component_implementation: true
    caller_or_fixed_identity_without_current_bytes_allowed: false
    implementation_bundle:
      exact_domain_framed_bytes_are_durable_artifact: true
      every_bound_source_dependency_is_durable_artifact: true
      transitive_project_local_semantic_closure_required: true
      delegated_dependency_change_changes_bundle_identity: true
      digest_without_exact_artifact_bytes_allowed: false
    historical_hardcoded_module:
      reconstruction_allowed: true
      prospective_registration_allowed: false
      byte_identity_frozen: true
      parity_required_before_retirement: true
  data_exposure:
    observed_development_is_distinct_content_addressed_prefix: true
    prefix_binds_parent_dataset_and_split: true
    routine_loader_opens_quarantined_parent: false
    engineering_test_sandbox_contains_quarantined_parent: false
    full_parent_integrity_materialization_scientific_or_claim_authority: false
  adjudication:
    comparison_state_is_scientific_state: false
    comparison_states:
      - passed
      - failed
      - not_evaluable
    terminal_and_scheduler_read_scientific_state_only: true
    audit_integrity:
      scientific_mode_credit: false
      terminal_or_exhaustion_credit: false
      economic_or_candidate_authority: false
      effective_evidence_modes:
        - audit_integrity
  historical_correction:
    effective_scope_overlay_required_for_mistaken_mode_credit: true
    overlay_is_additive_and_original_event_preserving: true
  replay_obligation:
    priorities:
      - P0
      - P1
    lifecycle:
      - pending
      - in_progress
      - satisfied
      - deferred
    exact_original_executable_and_criteria_bound: true
    exact_original_study_and_adjudication_bound: true
    P0_blocks_affected_scientific_credit: true
    P1_highest_information_value_bounded_opportunity: true
    P1_blocks_unrelated_valid_research: false
    progress_requires_exact_new_to_original_executable_match: true
    first_trial_or_position_fallback_allowed: false
    one_new_executable_satisfies_at_most_one_original: true
    family_level_evidence_satisfies_unmatched_member: false
    satisfaction_requires_recomputed_original_criteria: true
    defer_requires_typed_exact_resume_condition: true
  effective_axis_projection:
    immutable_portfolio_snapshot_preserved: true
    applies_source_invalidations: true
    applies_replay_obligations: true
    applies_effective_evidence_scope_overlays: true
    invalidated_source_axis_scheduler_eligible: false
    invalidated_source_axis_terminal_credit: false
    invalidated_source_axis_restoration_allowed: false
    new_source_contract_and_new_axis_identity_required: true
    source_replacement_lineage:
      exact_old_invalidation_source_and_axis_bound: true
      eligible_distinct_replacement_source_state_bound: true
      distinct_replacement_axis_bound: true
      original_snapshot_and_latch_immutable: true
      retired_old_axis_scientific_or_terminal_credit: false
      retired_old_axis_terminal_eligible_without_credit: true
      retired_old_axis_schedulable: false
      replacement_and_unrelated_eligible_axes_remain_schedulable: true
      external_wait_requires_exact_replacement_capability: true
      shared_outage_uses_typed_sorted_unique_capability_set: true
      capability_set_may_hide_replay_scope_or_internal_blocker: false
  concurrent_family_registration:
    typed_manifest_bound_into_batch_identity: true
    exact_executable_membership_required: true
    all_members_registered_before_any_job_declaration_start_or_evaluation: true
    runner_order_is_engine_authority: false
    legacy_or_single_member_batch_behavior_preserved: true
  economic_composite:
    component_summary_bundle_is_economic_evidence: false
    combined_significance_label_is_economic_evidence: false
    actual_member_trade_execution_required: true
    declared_entry_and_exit_timing_required: true
    exposure_netting_required: true
    native_and_stressed_costs_required: true
    portfolio_drawdown_attribution_required: true"""

EVIDENCE_V2_BLOCK = """project_goal_audit_v2_evidence:
  mode_authority:
    caller_label_is_capability: false
    cache_presence_is_capability: false
    prior_verdict_is_capability: false
    registered_protocol_recomputation_required: true
    durable_subject_bound_proof_required: true
    audit_integrity:
      only_effective_mode: audit_integrity
      scientific_credit: false
      terminal_or_exhaustion_credit: false
      economic_candidate_or_release_authority: false
  atomic_scientific_proof:
    exact_bundle:
      - validation_plan
      - atomic_support
      - statistical_proof
      - execution_trace
      - result_manifest
    every_artifact_content_addressed_and_opened: true
    summary_metric_without_atomic_support_allowed: false
    cached_point_value_without_recomputation_allowed: false
    support_binds:
      - protocol_identity
      - data_identity
      - split_identity
      - executable_identity
    statistical_proof_binds:
      - exact_concurrent_family
      - method
      - seed
      - resample_count
      - alpha
      - raw_statistic
      - adjusted_statistic
      - monte_carlo_uncertainty
    execution_trace_binds:
      - decision_time
      - entry_time
      - exit_time
      - fold
      - regime
      - intent
      - gross_pnl
      - native_cost
      - stress_cost
      - native_net_pnl
      - stress_net_pnl
      - result_attribution
    recomputation_must_match_declared_result: true
    decision_day_and_exit_day_attribution_explicit: true
  adjudication:
    comparison_state_and_scientific_state_are_distinct: true
    terminal_and_scheduler_use_scientific_state_only: true
  historical_scope_overlay:
    additive_only: true
    original_completion_rewrite_allowed: false
    exact_completion_and_executable_bound: true
    effective_modes_replace_mistaken_credit_for_readers: true
    audit_integrity_overlay_scientific_credit: false
    audit_integrity_overlay_terminal_credit: false
    applies_to_scheduler_axis_and_exhaustion_readers: true
  economic_composite_proof:
    component_summary_bundle_allowed: false
    actual_trade_rows_required: true
    member_identity_and_exposure_netting_required: true
    entry_and_exit_timing_required: true
    native_and_stressed_costs_required: true
    portfolio_drawdown_attribution_required: true"""

OPERATIONS_V2_BLOCK = """project_goal_audit_v2_operations:
  implementation_closure:
    component_to_executable_to_job_required: true
    executable_component_current_byte_identities_required: true
    job_artifacts_cover_all_executable_component_implementations: true
    typed_bundle_dependencies_are_recursively_closed: true
    bundle_without_dependency_artifacts_allowed: false
    artifact_reader_reverifies_exact_bytes: true
    historical_hardcoded_mission_or_study_module_prospective_use_allowed: false
  real_worktree_checks_fail_closed:
    missing_git_repository_allowed: false
    unborn_or_missing_head_allowed: false
    missing_local_main_allowed: false
    malformed_or_missing_hook_allowed: false
    malformed_or_missing_checkpoint_allowed: false
    typed_isolated_engineering_fixture_is_only_bypass: true
    fixture_scientific_authority: false
  audit_correction:
    historical_evidence_scope_overlay_is_additive: true
    effective_axis_projection_applies_invalid_source_and_replay_overlays: true
    replay_obligation:
      priorities:
        - P0
        - P1
      lifecycle:
        - pending
        - in_progress
        - satisfied
        - deferred
      exact_original_executable_and_criteria_bound: true
      exact_new_executable_match_required: true
      first_trial_fallback_allowed: false
      one_new_executable_matches_at_most_one_original: true
      satisfaction_is_single_writer_only: true
      defer_requires_exact_resume_condition: true
  validation_economics:
    routine_mode: fast_bounded_suffix
    full_maintenance_mode: explicit_complete_reconstruction
    exact_staging_mode: explicit_delivery_check
    permitted_scientific_job_waits_for_unrelated_full_suite: false
    tracked_test_manifest:
      source: git_index
      exact_path_and_byte_hash_required: true
      excluded_untracked_tests_reported: true
      untracked_or_unrelated_user_test_is_acceptance_authority: false
      intended_new_test_must_be_staged_before_inclusion: true
      protected_development_inputs:
        declaration_source: indexed_foundation_data_manifest
        allowed_roles:
          - observed_development
          - split_artifact
        exact_path_sha256_and_size_required: true
        independent_opaque_copy_required: true
        traversal_link_junction_or_alternate_stream_allowed: false
        missing_or_changed_input_fails_closed: true
        scientific_or_claim_authority: false
      sandbox_repository:
        standalone_snapshot_required: true
        location_outside_source_repository_required: true
        source_alternate_remote_or_reflog_metadata_allowed: false
        host_environment_policy: minimum_explicit_allowlist
        home_and_temporary_paths_confined_to_sandbox: true
  study_close_delivery_checkpoint_v2:
    schema: study_close_delivery_checkpoint.v2
    v1_to_v2_upgrade_requires_explicit_full_maintenance: true
    monotone_across_close_and_no_close_boundaries: true
    no_close_boundary_cannot_advance_authenticated_close_count: true
    historical_backfill_proof:
      event_kind: study_kpi_backfilled
      exact_source_close_count: 21
      exact_source_set_required: true
      each_source_binds:
        - original_close_event
        - authenticated_commit
        - commit_tree
        - required_path_blobs
        - trailer_or_typed_attestation
        - local_main_ancestry
      deterministic_kpi_bytes_bound: true"""

SCIENCE_BATCH_V2_INSERT = (
    "  concurrent_family_all_executables_registered_before_first_evaluation: true\n"
    "  concurrent_family_typed_manifest_bound_to_batch_identity: true\n"
    "  concurrent_family_exact_ordered_executable_ids_required: true\n"
    "  concurrent_family_size_derived_from_unique_executable_ids: true\n"
    "  concurrent_family_size_equals_frozen_trial_bound: true\n"
    "  concurrent_family_all_members_required_before_job_declaration_and_start: true\n"
    "  concurrent_family_runner_order_is_authority: false\n"
)

EVIDENCE_CACHE_V2_INSERT = """    local_presence_required_for_scientific_or_terminal_credit: false
    rematerialization_requires_exact_durable_producer_trace_and_hash: true
    producer_identity_binds_exact_declaration_start_permit_entry_and_completion: true
    later_same_work_fingerprint_attempt_may_substitute: false
"""

EVIDENCE_AXIS_V2_INSERT = """  audit_only_scope_is_completion_bound_not_axis_wide: true
  historical_adjudication_cannot_restore_overlayed_credit: true
  source_replacement_lineage_is_additive_and_snapshot_preserving: true
  source_replacement_lineage_is_authority_disposition_not_scientific_evidence: true
  retired_invalidated_axis_scientific_or_terminal_credit: false
"""

OPERATIONS_CACHE_V2_INSERT = """  missing_reproducible_cache_may_be_rematerialized: true
  rematerialization_is_not_job_success_cache_reuse: true
  rematerialization_requires_exact_durable_producer_completion_trace_manifest_and_hash: true
  rematerialization_is_atomic_and_consumer_initiated: true
  present_reproducible_cache_hash_mismatch_fails_closed: true
  study_close_credit_requires_local_reproducible_cache_presence: false
  study_close_reverifies_exact_durable_producer_and_consumer_traces: true
  producer_lookup_starts_from_exact_manifest_execution_and_declaration: true
  producer_start_permit_consumption_engine_entry_and_completion_rejoined: true
  later_same_work_fingerprint_attempt_may_substitute: false
"""

OPERATIONS_EXTERNAL_PLAN_V2_INSERT = """  typed_recovery_plan:
    exact_stable_boundary_event_required: true
    boundary_event_participates_in_plan_identity: true
    validation_plan_content_addressed_and_reverified: true
    ordered_paths_required: true
    required_path_kinds:
      - external_probe
      - local_recovery
      - safe_substitute_search
    continuation_keeps_one_plan_identity: true
    recurrent_outage_requires_new_current_boundary_plan: true
    stale_boundary_plan_allowed: false
  standalone_external_judgement_required_before_next_job: true
  external_evidence_grants_scientific_candidate_or_release_credit: false
  judgement:
    failed_with_all_blocker_predicates_advances_only_to_next_frozen_path: true
    failed_without_blocker_predicates_restores_exact_mission_action: true
    final_failed_path_may_propose_blocker: true
    passed_restores_exact_mission_action: true
    not_evaluable_restores_exact_mission_action: true
    not_evaluable_has_blocker_credit: false
"""

OPERATIONS_EXTERNAL_REENTRY_V2_INSERT = """  blocker_record_requires_every_ordered_failed_judgement: true
  portfolio_snapshot_required_for_blocked_external: false
  close_preserves_typed_resume_condition_and_action: true
  reentry:
    same_mission_required: true
    exact_wait_boundary_required: true
    exact_validator_derived_passed_change_required: true
    fresh_mission_authorization_epoch_required: true
    successor_mission_created: false
    scientific_trial_claim_and_holdout_delta: 0
    repeated_operation_id_is_idempotent: true
    resume_action_requires_exact_action_specific_schema: true
    canonical_nested_ascii_json_bindings_allowed: true
    canonical_binding_name_order_required: true
    exact_recovery_plan_payload_round_trip_required: true
    lossy_scalar_coercion_allowed: false
    restored_action_must_equal_frozen_action: true
"""

OPERATIONS_SOURCE_REPLACEMENT_V2_BLOCK = """source_replacement_lifecycle:
  additive_lineage_only: true
  exact_old_invalidation_source_axis_and_snapshot_required: true
  exact_eligible_distinct_replacement_source_state_required: true
  distinct_replacement_axis_required: true
  original_source_latch_and_snapshot_remain_immutable: true
  retired_old_axis_scheduler_eligible: false
  retired_old_axis_scientific_or_terminal_credit: false
  retired_old_axis_terminal_eligible_without_credit: true
  replacement_axis_must_be_selectable_at_recording: true
  blocked_external_requires_exact_unresolved_replacement_capability: true
  multiple_unresolved_replacements_use_typed_sorted_unique_capability_set: true
  capability_set_excludes_completed_replacement_lineages: true
  capability_set_may_hide_replay_scope_or_internal_blocker: false
  blocked_external_replacement_wait_scientific_credit: false
concurrent_family_engine_boundary:
  typed_manifest_bound_to_batch_identity: true
  exact_ordered_unique_executable_membership_required: true
  derived_family_size_equals_frozen_batch_trial_bound: true
  all_members_registered_before_any_member_job_declaration: true
  all_members_reverified_before_any_member_job_start: true
  job_subject_must_be_exact_family_member: true
  untyped_family_label_or_size_is_authority: false
  runner_convention_is_capability: false
authority_activation_boundary:
  planning_is_local_and_read_only: true
  planning_network_fetch_allowed: false
  planning_receipt_write_allowed: false
  explicit_delivery_readiness_owns_network_and_receipt_mutation: true
  local_main_required: true
  authenticated_v2_checkpoint_required: true
  exact_unique_complete_old_to_new_authority_mapping_required: true
  frozen_parent_and_addendum_provenance_required: true
  observed_development_materialization_required_before_apply: true
  foundation_data_replacement_uses_same_authority_event: true
"""

FOUNDATION_DATA_V2_INSERT = """observed_development:
  path: data/processed/datasets/us100_m5_observed_development.csv
  sha256: a7f097242f46ab45e8f58387c35a76a8c7d8ea1b04519f0878b66747442acbbe
  byte_count: 37029769
  row_count: 560552
  first_time: "2018-05-07 01:00:00"
  last_time: "2026-04-30 23:55:00"
  parent_dataset_sha256: fb02fe8754b8b9643a346982367813238d11475ca39de46f1cd8d4d0e33a2aa5
  split_artifact_sha256: 21830ac109c810cf2b463106127090d586d90de96472c3d043990246d75aa606
  derivation: exact_prefix_before_quarantined_tail
"""


def correction_steps() -> tuple[CorrectionStep, ...]:
    return STEPS


def _ascii_text(root: Path, relative: str) -> str:
    try:
        return (root / relative).read_bytes().decode("ascii")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"authority document is not ASCII: {relative}") from exc


def _append_block(text: str, block: str, *, marker: str, label: str) -> str:
    if marker in text:
        raise RuntimeError(f"{label} v2 block is already materialized")
    if not text.endswith("\n"):
        raise RuntimeError(f"{label} lacks its final newline")
    return text + block + "\n"


def _insert_after_exact(
    text: str,
    *,
    anchor: str,
    addition: str,
    marker: str,
    label: str,
) -> str:
    if marker in text:
        raise RuntimeError(f"{label} is already materialized")
    if text.count(anchor) != 1:
        raise RuntimeError(f"{label} anchor differs")
    return text.replace(anchor, anchor + addition, 1)


def _replace_exact(
    text: str,
    *,
    old: str,
    new: str,
    label: str,
) -> str:
    if text.count(old) != 1 or new in text:
        raise RuntimeError(f"{label} replacement basis differs")
    return text.replace(old, new, 1)


def _transform_authority_basis(
    pre_v2: Mapping[str, str],
) -> dict[str, bytes]:
    """Purely derive the exact integrated V2 authority from frozen text."""

    operating = pre_v2["OPERATING_DIRECTION.md"]
    anchor = "\n\n## 23. Governing Principle\n"
    if operating.count(anchor) != 1 or "OD-AUD-019" in operating:
        raise RuntimeError("Operating Direction is not the exact pre-V2 surface")
    operating = operating.replace(
        anchor,
        "\n" + OD_V2_BLOCK + anchor,
        1,
    )
    foundation_data = _insert_after_exact(
        pre_v2["foundation/data.yaml"],
        anchor="    - real_volume\n",
        addition=FOUNDATION_DATA_V2_INSERT,
        marker="observed_development:\n",
        label="Foundation observed-development materialization",
    )
    science = _insert_after_exact(
        pre_v2["contracts/science.yaml"],
        anchor="  frozen_before_evidence: true\n",
        addition=SCIENCE_BATCH_V2_INSERT,
        marker=(
            "  concurrent_family_all_executables_registered_before_first_evaluation: true\n"
        ),
        label="science concurrent-family registration rule",
    )
    evidence = _insert_after_exact(
        pre_v2["contracts/evidence.yaml"],
        anchor="    eviction_allowed: true\n",
        addition=EVIDENCE_CACHE_V2_INSERT,
        marker="    local_presence_required_for_scientific_or_terminal_credit: false\n",
        label="evidence reproducible-cache rule",
    )
    evidence = _insert_after_exact(
        evidence,
        anchor="  additive_and_portfolio_snapshot_preserving: true\n",
        addition=EVIDENCE_AXIS_V2_INSERT,
        marker="  audit_only_scope_is_completion_bound_not_axis_wide: true\n",
        label="evidence completion-scope rule",
    )
    operations = _insert_after_exact(
        pre_v2["contracts/operations.yaml"],
        anchor="  reproducible_cache_reuse_requires_present_exact_bytes: true\n",
        addition=OPERATIONS_CACHE_V2_INSERT,
        marker="  missing_reproducible_cache_may_be_rematerialized: true\n",
        label="operations reproducible-cache rule",
    )
    operations = _insert_after_exact(
        operations,
        anchor="  external_cause_required: true\n",
        addition=OPERATIONS_EXTERNAL_PLAN_V2_INSERT,
        marker="  typed_recovery_plan:\n",
        label="operations external recovery plan",
    )
    operations = _insert_after_exact(
        operations,
        anchor="  blocked_mission_capability_required: true\n",
        addition=OPERATIONS_EXTERNAL_REENTRY_V2_INSERT,
        marker="  blocker_record_requires_every_ordered_failed_judgement: true\n",
        label="operations external reentry rule",
    )
    operations = _replace_exact(
        operations,
        old="  schema: study_close_delivery_checkpoint.v1\n",
        new="  schema: study_close_delivery_checkpoint.v2\n",
        label="operations Study-close checkpoint schema",
    )
    replacements = {
        "OPERATING_DIRECTION.md": operating.encode("ascii"),
        "contracts/science.yaml": _append_block(
            science,
            SCIENCE_V2_BLOCK,
            marker="project_goal_audit_v2_protocol:",
            label="science contract",
        ).encode("ascii"),
        "contracts/evidence.yaml": _append_block(
            evidence,
            EVIDENCE_V2_BLOCK,
            marker="project_goal_audit_v2_evidence:",
            label="evidence contract",
        ).encode("ascii"),
        "contracts/operations.yaml": _append_block(
            operations,
            OPERATIONS_V2_BLOCK + "\n" + OPERATIONS_SOURCE_REPLACEMENT_V2_BLOCK,
            marker="project_goal_audit_v2_operations:",
            label="operations contract",
        ).encode("ascii"),
        "foundation/data.yaml": foundation_data.encode("ascii"),
    }
    observed = {name: sha256(content).hexdigest() for name, content in replacements.items()}
    if observed != EXPECTED_AUTHORITY_SHA256:
        raise RuntimeError("deterministic V2 authority replacement hashes differ")
    for relative, content in replacements.items():
        if relative.endswith(".yaml") and not isinstance(
            yaml.safe_load(content.decode("ascii")), dict
        ):
            raise RuntimeError(f"transformed authority is not YAML: {relative}")
    return replacements


def build_authority_replacements(root: Path = ROOT) -> dict[str, bytes]:
    """Build exact V2 bytes from the active pre-V2 authority without writing."""

    pre_v2 = {
        relative: _ascii_text(root, relative)
        for relative in EXPECTED_PRE_V2_AUTHORITY_SHA256
    }
    observed_pre_v2 = {
        relative: sha256(content.encode("ascii")).hexdigest()
        for relative, content in pre_v2.items()
    }
    if observed_pre_v2 != EXPECTED_PRE_V2_AUTHORITY_SHA256:
        raise RuntimeError("active authority differs from the exact pre-V2 basis")
    return _transform_authority_basis(pre_v2)


def read_frozen_audit_report(root: Path = ROOT) -> tuple[bytes, str]:
    content = (root / AUDIT_REPORT_RELATIVE_PATH).read_bytes()
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as exc:
        raise RuntimeError("V2 audit report is not ASCII") from exc
    digest = sha256(content).hexdigest()
    if len(content) != EXPECTED_REPORT_SIZE or digest != EXPECTED_REPORT_SHA256:
        raise RuntimeError("V2 audit report bytes differ from the frozen basis")
    if any(text.count(marker) != 1 for marker in EXPECTED_REPORT_MARKERS):
        raise RuntimeError("V2 audit report markers differ from the frozen basis")
    return content, digest


def read_frozen_integration_addendum(root: Path = ROOT) -> tuple[bytes, str]:
    content = (root / INTEGRATION_ADDENDUM_RELATIVE_PATH).read_bytes()
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as exc:
        raise RuntimeError("V2 integration addendum is not ASCII") from exc
    digest = sha256(content).hexdigest()
    if len(content) != EXPECTED_ADDENDUM_SIZE or digest != EXPECTED_ADDENDUM_SHA256:
        raise RuntimeError("V2 integration addendum bytes differ from the frozen basis")
    if any(text.count(marker) != 1 for marker in EXPECTED_ADDENDUM_MARKERS):
        raise RuntimeError("V2 integration addendum markers differ from the frozen basis")
    if f"parent_report_sha256: {EXPECTED_REPORT_SHA256}" not in text:
        raise RuntimeError("V2 integration addendum lost its parent report binding")
    return content, digest


def replay_satisfaction_from_payload(value: Mapping[str, Any]) -> ReplaySatisfaction:
    try:
        satisfaction = ReplaySatisfaction(
            obligation_id=value["obligation_id"],
            resolution_scope=ReplayResolutionScope(value["resolution_scope"]),
            portfolio_decision_id=value["portfolio_decision_id"],
            replay_study_id=value["replay_study_id"],
            replay_executable_id=value["replay_executable_id"],
            replay_study_close_record_id=value["replay_study_close_record_id"],
            study_diagnosis_id=value["study_diagnosis_id"],
            satisfied_criterion_ids=tuple(value["satisfied_criterion_ids"]),
            evidence_record_ids=tuple(value["evidence_record_ids"]),
            remaining_scientific_condition=value["remaining_scientific_condition"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError("replay satisfaction template is malformed") from exc
    if satisfaction.to_identity_payload() != dict(value):
        raise RuntimeError("replay satisfaction template is not canonical")
    return satisfaction


def validate_replay_plan(plan: Mapping[str, Any]) -> tuple[ReplaySatisfaction, ...]:
    overlay = plan.get("effective_scope_overlay")
    payload = None if not isinstance(overlay, Mapping) else overlay.get("payload")
    templates = plan.get("satisfaction_templates")
    if (
        plan.get("schema") != "historical_replay_correction_plan.v2"
        or plan.get("operation") != "record_historical_replay_correction"
        or plan.get("governing_mission_id") != EXPECTED_MISSION_ID
        or tuple(plan.get("adjudication_record_ids", ())) != ADJUDICATION_RECORD_IDS
        or tuple(plan.get("satisfied_after_apply", ())) != EXPECTED_P0_OBLIGATION_IDS
        or tuple(plan.get("pending_after_apply", ())) != EXPECTED_P1_OBLIGATION_IDS
        or EXPECTED_STU0061_OBLIGATION_ID not in EXPECTED_P1_OBLIGATION_IDS
        or not isinstance(overlay, Mapping)
        or overlay.get("record_id") != EXPECTED_SCOPE_OVERLAY_ID
        or not isinstance(payload, Mapping)
        or payload.get("effective_evidence_modes") != ["audit_integrity"]
        or payload.get("scientific_eligible") is not False
        or payload.get("candidate_eligible") is not False
        or payload.get("credit")
        != {"candidate": 0, "economic": 0, "scientific": 0, "terminal": 0}
        or not isinstance(templates, list)
        or len(templates) != 6
    ):
        raise RuntimeError("historical replay correction plan differs")
    satisfactions = tuple(
        sorted(
            (replay_satisfaction_from_payload(item) for item in templates),
            key=lambda item: item.obligation_id,
        )
    )
    if (
        tuple(item.obligation_id for item in satisfactions)
        != EXPECTED_P0_OBLIGATION_IDS
        or any(
            item.resolution_scope is not ReplayResolutionScope.AUDIT_ONLY
            or item.replay_study_id != REPLAY_STUDY_ID
            or item.remaining_scientific_condition
            != "prospective_paired_control_or_independent_family"
            for item in satisfactions
        )
    ):
        raise RuntimeError("audit-only replay satisfaction family differs")
    return satisfactions


@dataclass(frozen=True, slots=True)
class CorrectionPlan:
    report_bytes: bytes
    report_hash: str
    addendum_bytes: bytes
    addendum_hash: str
    authority_replacements: Mapping[str, bytes]
    replay_plan: Mapping[str, Any]
    satisfactions: tuple[ReplaySatisfaction, ...]


def build_correction_plan(writer: StateWriter, *, root: Path = ROOT) -> CorrectionPlan:
    report_bytes, report_hash = read_frozen_audit_report(root)
    addendum_bytes, addendum_hash = read_frozen_integration_addendum(root)
    replacements = build_authority_replacements(root)
    replay_plan = writer.plan_historical_replay_correction(
        adjudication_record_ids=ADJUDICATION_RECORD_IDS,
        replay_study_id=REPLAY_STUDY_ID,
    )
    satisfactions = validate_replay_plan(replay_plan)
    return CorrectionPlan(
        report_bytes=report_bytes,
        report_hash=report_hash,
        addendum_bytes=addendum_bytes,
        addendum_hash=addendum_hash,
        authority_replacements=replacements,
        replay_plan=replay_plan,
        satisfactions=satisfactions,
    )


def _materialized_authority_replacements(root: Path) -> dict[str, bytes]:
    replacements = {
        relative: (root / relative).read_bytes()
        for relative in EXPECTED_AUTHORITY_SHA256
    }
    observed = {
        relative: sha256(content).hexdigest()
        for relative, content in replacements.items()
    }
    if observed != EXPECTED_AUTHORITY_SHA256:
        raise RuntimeError("materialized V2 authority bytes differ")
    return replacements


def build_resume_plan(writer: StateWriter, *, root: Path = ROOT) -> CorrectionPlan:
    report_bytes, report_hash = read_frozen_audit_report(root)
    addendum_bytes, addendum_hash = read_frozen_integration_addendum(root)
    replacements = _materialized_authority_replacements(root)
    replay_plan = writer.plan_historical_replay_correction(
        adjudication_record_ids=ADJUDICATION_RECORD_IDS,
        replay_study_id=REPLAY_STUDY_ID,
    )
    satisfactions = validate_replay_plan(replay_plan)
    return CorrectionPlan(
        report_bytes=report_bytes,
        report_hash=report_hash,
        addendum_bytes=addendum_bytes,
        addendum_hash=addendum_hash,
        authority_replacements=replacements,
        replay_plan=replay_plan,
        satisfactions=satisfactions,
    )


def _operation_event(writer: StateWriter, operation: Any) -> Mapping[str, Any]:
    if (
        operation is None
        or operation.kind != "operation"
        or operation.status != "success"
        or operation.authority_sequence is None
        or operation.authority_event_id is None
        or operation.authority_offset is None
    ):
        raise RuntimeError("V2 correction operation projection is invalid")
    event = writer.journal.read_event_at(
        offset=operation.authority_offset,
        expected_sequence=operation.authority_sequence,
        expected_event_id=operation.authority_event_id,
    )
    if not isinstance(event, Mapping):
        raise RuntimeError("V2 correction Journal event is invalid")
    return event


def inspect_correction_prefix(writer: StateWriter) -> int:
    """Require one exact gap-free three-event suffix from revision 4935."""

    with LocalIndex.open_read_only(writer.index_path) as index:
        operations = tuple(
            index.get("operation", step.operation_id) for step in STEPS
        )
    present = tuple(item is not None for item in operations)
    prefix = 0
    while prefix < len(present) and present[prefix]:
        prefix += 1
    if any(present[prefix:]):
        raise RuntimeError("V2 correction operations do not form a strict prefix")
    previous = EXPECTED_INITIAL_EVENT_ID
    for position, (step, operation) in enumerate(
        zip(STEPS[:prefix], operations[:prefix], strict=True)
    ):
        sequence = EXPECTED_INITIAL_REVISION + position + 1
        event = _operation_event(writer, operation)
        if (
            operation.record_id != step.operation_id
            or operation.payload.get("event_kind") != step.event_kind
            or operation.authority_sequence != sequence
            or event.get("sequence") != sequence
            or event.get("event_kind") != step.event_kind
            or event.get("operation_id") != step.operation_id
            or event.get("previous_event_id") != previous
        ):
            raise RuntimeError("V2 correction operation order differs")
        previous = event["event_id"]
    return prefix


def _require_mission_boundary(
    control: Mapping[str, Any], *, with_replay_constraints: bool
) -> None:
    science = control.get("scientific")
    expected_action = dict(EXPECTED_INITIAL_ACTION)
    if with_replay_constraints:
        expected_action.update(
            {
                "pending_replay_obligation_ids": list(EXPECTED_P1_OBLIGATION_IDS),
                "required_replay_priority": "p1",
            }
        )
    inactive = (
        "active_batch",
        "active_executable",
        "active_holdout_evaluation",
        "active_initiative",
        "active_job",
        "active_lineage",
        "active_release",
        "active_repair",
        "active_study",
    )
    if (
        not isinstance(science, Mapping)
        or science.get("active_mission") != EXPECTED_MISSION_ID
        or any(science.get(name) is not None for name in inactive)
        or science.get("claim") != "none"
        or science.get("holdout_reveals") != 0
        or science.get("required_future_holdout_id") is not None
        or control.get("next_action") != expected_action
        or set(control.get("authorizations", {}))
        != {f"Mission:{EXPECTED_MISSION_ID}"}
    ):
        raise RuntimeError("V2 correction Mission boundary differs")


def require_initial_predecessor(writer: StateWriter) -> Mapping[str, Any]:
    control = writer.read_control()
    journal = None if not isinstance(control, Mapping) else control.get("heads", {}).get(
        "journal"
    )
    if (
        not isinstance(control, Mapping)
        or control.get("revision") != EXPECTED_INITIAL_REVISION
        or not isinstance(journal, Mapping)
        or journal.get("sequence") != EXPECTED_INITIAL_REVISION
        or journal.get("event_id") != EXPECTED_INITIAL_EVENT_ID
        or control.get("authority", {}).get("manifest_digest")
        != EXPECTED_INITIAL_AUTHORITY_MANIFEST
    ):
        raise RuntimeError("V2 correction predecessor differs")
    _require_mission_boundary(control, with_replay_constraints=False)
    return control


def _events_for_prefix(
    writer: StateWriter, prefix: int
) -> tuple[Mapping[str, Any], ...]:
    with LocalIndex.open_read_only(writer.index_path) as index:
        operations = tuple(
            index.get("operation", step.operation_id) for step in STEPS[:prefix]
        )
    return tuple(_operation_event(writer, item) for item in operations)


def _without_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "evidence"}


def _validate_authority_event(event: Mapping[str, Any]) -> str:
    payload = event.get("payload")
    control = event.get("control")
    if not isinstance(payload, Mapping) or not isinstance(control, Mapping):
        raise RuntimeError("V2 authority event is malformed")
    rows = payload.get("replacements")
    if (
        payload.get("schema") != "authority_manifest_migration.v1"
        or payload.get("boundary") != "active_stable"
        or payload.get("reason") != AUTHORITY_REASON
        or payload.get("old_manifest_digest") != EXPECTED_INITIAL_AUTHORITY_MANIFEST
        or payload.get("trial_delta") != 0
        or payload.get("holdout_delta") != 0
        or payload.get("scientific_claim") != "none"
        or not isinstance(payload.get("new_manifest_digest"), str)
        or not isinstance(rows, list)
        or len(rows) != len(EXPECTED_AUTHORITY_SHA256)
    ):
        raise RuntimeError("V2 authority migration payload differs")
    observed_new: dict[str, str] = {}
    observed_old: dict[str, str] = {}
    for row in rows:
        if (
            not isinstance(row, Mapping)
            or set(row)
            != {"artifact_sha256", "new_sha256", "old_sha256", "path"}
        ):
            raise RuntimeError("V2 authority replacement row is malformed")
        relative = row.get("path")
        new_digest = row.get("new_sha256")
        old_digest = row.get("old_sha256")
        if (
            type(relative) is not str
            or relative in observed_new
            or type(new_digest) is not str
            or type(old_digest) is not str
            or row.get("artifact_sha256") != new_digest
        ):
            raise RuntimeError("V2 authority replacement row is incomplete")
        observed_new[relative] = new_digest
        observed_old[relative] = old_digest
    if (
        observed_new != EXPECTED_AUTHORITY_SHA256
        or observed_old != EXPECTED_PRE_V2_AUTHORITY_SHA256
    ):
        raise RuntimeError("V2 authority replacement identities differ")
    if control.get("authority", {}).get("manifest_digest") != payload.get(
        "new_manifest_digest"
    ):
        raise RuntimeError("V2 authority control binding differs")
    _require_mission_boundary(control, with_replay_constraints=False)
    if any(
        item.get("kind") in {"trial", "candidate", "holdout-evaluation"}
        for item in event.get("index_records", ())
        if isinstance(item, Mapping)
    ):
        raise RuntimeError("V2 authority migration changed scientific inventory")
    return payload["new_manifest_digest"]


def _validate_protocol_event(
    event: Mapping[str, Any], *, authority_manifest_digest: str
) -> None:
    payload = event.get("payload")
    control = event.get("control")
    if (
        not isinstance(payload, Mapping)
        or not isinstance(control, Mapping)
        or _without_evidence(payload)
        != {
            "audit_artifact_hash": EXPECTED_ADDENDUM_SHA256,
            "authority_manifest_digest": authority_manifest_digest,
            "protocol": "scientific_adjudication_v2",
            "schema": "research_protocol_activation.v1",
            "validator_id": EXPECTED_V2_VALIDATOR_ID,
        }
    ):
        raise RuntimeError("V2 protocol activation payload differs")
    protocol_records = [
        item
        for item in event.get("index_records", ())
        if isinstance(item, Mapping)
        and item.get("kind") == "research-protocol-activation"
    ]
    operations = [
        item
        for item in event.get("index_records", ())
        if isinstance(item, Mapping) and item.get("kind") == "operation"
    ]
    result = None if len(operations) != 1 else operations[0].get("payload", {}).get(
        "result"
    )
    if (
        len(protocol_records) != 1
        or len(operations) != 1
        or not isinstance(result, Mapping)
        or result.get("trial_delta") != 0
    ):
        raise RuntimeError("V2 protocol activation projection differs")
    _require_mission_boundary(control, with_replay_constraints=False)


def _validate_replay_event(
    writer: StateWriter, event: Mapping[str, Any]
) -> tuple[ReplaySatisfaction, ...]:
    from axiom_rift.operations.replay_projection import (
        derive_obligation_from_record,
        require_satisfaction,
    )

    payload = event.get("payload")
    control = event.get("control")
    if not isinstance(payload, Mapping) or not isinstance(control, Mapping):
        raise RuntimeError("V2 replay correction event is malformed")
    values = payload.get("satisfactions")
    if (
        tuple(payload.get("adjudication_record_ids", ()))
        != ADJUDICATION_RECORD_IDS
        or not isinstance(values, list)
        or len(values) != 6
    ):
        raise RuntimeError("V2 replay correction request differs")
    satisfactions = tuple(
        sorted(
            (replay_satisfaction_from_payload(item) for item in values),
            key=lambda item: item.obligation_id,
        )
    )
    if tuple(item.obligation_id for item in satisfactions) != EXPECTED_P0_OBLIGATION_IDS:
        raise RuntimeError("V2 replay correction satisfaction set differs")
    with LocalIndex.open_read_only(writer.index_path) as index:
        obligations = {
            derive_obligation_from_record(
                index,
                adjudication_record_id=record_id,
                mission_id=EXPECTED_MISSION_ID,
            ).identity: derive_obligation_from_record(
                index,
                adjudication_record_id=record_id,
                mission_id=EXPECTED_MISSION_ID,
            )
            for record_id in ADJUDICATION_RECORD_IDS
        }
        for satisfaction in satisfactions:
            obligation = obligations.get(satisfaction.obligation_id)
            if obligation is None:
                raise RuntimeError("V2 replay correction obligation differs")
            require_satisfaction(
                index,
                obligation=obligation,
                satisfaction=satisfaction,
                allow_legacy_decision_binding=True,
            )
        overlay = index.get("historical-evidence-scope-overlay", EXPECTED_SCOPE_OVERLAY_ID)
    if overlay is None or overlay.status != "audit_only" or overlay.payload.get(
        "effective_evidence_modes"
    ) != ["audit_integrity"]:
        raise RuntimeError("V2 evidence-scope overlay differs")
    records = tuple(
        item for item in event.get("index_records", ()) if isinstance(item, Mapping)
    )
    forbidden = {"trial", "candidate", "candidate-freeze", "holdout-evaluation"}
    if any(item.get("kind") in forbidden for item in records):
        raise RuntimeError("V2 replay correction changed scientific inventory")
    obligation_ids = {
        item.get("record_id")
        for item in records
        if item.get("kind") == "historical-replay-obligation"
    }
    resolution_ids = {
        item.get("record_id")
        for item in records
        if item.get("kind") == "historical-replay-obligation-resolution"
    }
    if (
        obligation_ids != set(EXPECTED_P0_OBLIGATION_IDS + EXPECTED_P1_OBLIGATION_IDS)
        or resolution_ids != {item.identity for item in satisfactions}
        or not any(
            item.get("kind") == "historical-evidence-scope-overlay"
            and item.get("record_id") == EXPECTED_SCOPE_OVERLAY_ID
            for item in records
        )
    ):
        raise RuntimeError("V2 replay correction projection inventory differs")
    _require_mission_boundary(control, with_replay_constraints=True)
    return satisfactions


def validate_completed_correction_suffix_boundary(
    *, current: object, replay_event: Mapping[str, Any]
) -> int:
    boundary_revision = EXPECTED_INITIAL_REVISION + len(STEPS)
    boundary_control = replay_event.get("control")
    if replay_event.get("sequence") != boundary_revision or not isinstance(
        boundary_control, Mapping
    ):
        raise RuntimeError("V2 correction terminal boundary differs")
    _require_mission_boundary(boundary_control, with_replay_constraints=True)
    head = (
        None
        if not isinstance(current, Mapping)
        else current.get("heads", {}).get("journal")
    )
    if (
        not isinstance(current, Mapping)
        or not isinstance(head, Mapping)
        or type(current.get("revision")) is not int
        or current["revision"] < boundary_revision
        or head.get("sequence") != current["revision"]
    ):
        raise RuntimeError("current control is not a legal V2 correction suffix")
    return current["revision"] - boundary_revision


def validate_completed_correction_ancestor(
    writer: StateWriter, *, root: Path = ROOT
) -> dict[str, object]:
    if inspect_correction_prefix(writer) != len(STEPS):
        raise RuntimeError("V2 correction chain is incomplete")
    require_observed_development_materialization(root)
    report_bytes, report_hash = read_frozen_audit_report(root)
    addendum_bytes, addendum_hash = read_frozen_integration_addendum(root)
    events = _events_for_prefix(writer, len(STEPS))
    manifest = _validate_authority_event(events[0])
    _validate_protocol_event(events[1], authority_manifest_digest=manifest)
    satisfactions = _validate_replay_event(writer, events[2])
    # The immutable migration event is the authority for the historical
    # replacement bytes.  _validate_authority_event already binds every path,
    # old digest, new digest, and artifact digest to that event.  Comparing the
    # live files to those historical digests here would incorrectly make every
    # later prospective authority evolution invalidate its own ancestor.
    current = writer.read_control()
    suffix = validate_completed_correction_suffix_boundary(
        current=current,
        replay_event=events[2],
    )
    return {
        "boundary_event_id": events[2]["event_id"],
        "boundary_revision": EXPECTED_INITIAL_REVISION + len(STEPS),
        "current_revision": current["revision"],
        "effective_scope_overlay_id": EXPECTED_SCOPE_OVERLAY_ID,
        "mode": "completed_immutable_ancestor",
        "operation_count": len(STEPS),
        "p0_satisfied_count": len(satisfactions),
        "p1_pending_count": len(EXPECTED_P1_OBLIGATION_IDS),
        "report_sha256": sha256(report_bytes).hexdigest(),
        "integration_addendum_sha256": sha256(addendum_bytes).hexdigest(),
        "stu0061_obligation_id": EXPECTED_STU0061_OBLIGATION_ID,
        "suffix_event_count": suffix,
        "trial_delta": 0,
        "holdout_delta": 0,
        "candidate_delta": 0,
    }


def validate_correction_progress(
    writer: StateWriter, *, prefix: int | None = None
) -> int:
    observed = inspect_correction_prefix(writer) if prefix is None else prefix
    if observed < 0 or observed > len(STEPS):
        raise RuntimeError("V2 correction prefix is invalid")
    read_frozen_audit_report(writer.root)
    read_frozen_integration_addendum(writer.root)
    if observed == 0:
        require_initial_predecessor(writer)
        return 0
    events = _events_for_prefix(writer, observed)
    manifest = _validate_authority_event(events[0])
    if observed >= 2:
        _validate_protocol_event(events[1], authority_manifest_digest=manifest)
    if observed == len(STEPS):
        validate_completed_correction_ancestor(writer, root=writer.root)
        return observed
    control = writer.read_control()
    head = control.get("heads", {}).get("journal", {})
    if (
        control.get("revision") != EXPECTED_INITIAL_REVISION + observed
        or head.get("sequence") != control.get("revision")
        or head.get("event_id") != events[-1].get("event_id")
    ):
        raise RuntimeError("partial V2 correction has a foreign suffix")
    _require_mission_boundary(control, with_replay_constraints=False)
    return observed


def _finalize_audit_artifacts(writer: StateWriter, plan: CorrectionPlan) -> None:
    artifacts = (
        ("parent report", plan.report_bytes, plan.report_hash),
        ("integration addendum", plan.addendum_bytes, plan.addendum_hash),
    )
    for label, content, digest in artifacts:
        artifact = writer.evidence.finalize(content)
        if artifact.sha256 != digest:
            raise RuntimeError(f"finalized V2 {label} hash differs")
        writer.evidence.verify(digest)


def require_current_validator_for_apply() -> None:
    """Fail before mutation when current code cannot enact the frozen protocol."""

    if ScientificAdjudicationValidatorV2.validator_id != EXPECTED_V2_VALIDATOR_ID:
        raise RuntimeError(
            "current V2 validator differs from the frozen activation identity"
        )


def require_observed_development_materialization(
    root: Path = ROOT,
) -> dict[str, object]:
    """Verify the exact permitted prefix without parsing any market value."""

    repository = root.resolve()
    candidate = repository / OBSERVED_DEVELOPMENT_RELATIVE_PATH
    cursor = candidate
    while cursor != repository:
        is_junction = getattr(cursor, "is_junction", None)
        if cursor.is_symlink() or bool(
            is_junction is not None and is_junction()
        ):
            raise RuntimeError(
                "observed development materialization traverses a link-like path"
            )
        cursor = cursor.parent
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(
            "observed development materialization is unavailable"
        ) from exc
    if resolved != candidate or not candidate.is_file():
        raise RuntimeError(
            "observed development materialization is not a confined regular file"
        )
    digest = sha256()
    size = 0
    try:
        with candidate.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise RuntimeError(
            "observed development materialization cannot be hashed"
        ) from exc
    observed = digest.hexdigest()
    if (
        observed != EXPECTED_OBSERVED_DEVELOPMENT_SHA256
        or size != EXPECTED_OBSERVED_DEVELOPMENT_SIZE
    ):
        raise RuntimeError("observed development materialization identity differs")
    return {
        "path": OBSERVED_DEVELOPMENT_RELATIVE_PATH.as_posix(),
        "sha256": observed,
        "size": size,
    }


def _read_v2_delivery_checkpoint(root: Path) -> StudyCloseDeliveryCheckpoint:
    try:
        checkpoint = StudyCloseDeliveryCheckpoint.from_bytes(
            (root / CHECKPOINT_PATH).read_bytes()
        )
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeError("V2 activation delivery checkpoint is unavailable") from exc
    if checkpoint.schema != CHECKPOINT_SCHEMA:
        raise RuntimeError("V2 activation requires the authenticated v2 checkpoint")
    return checkpoint


def inspect_v2_delivery_preflight(*, root: Path = ROOT) -> None:
    """Authenticate local delivery readiness without network or filesystem writes."""

    checkpoint = _read_v2_delivery_checkpoint(root)
    try:
        require_local_main(root)
        require_study_close_guard_ready(root)
        inspected = inspect_tracked_study_close_delivery(root)
    except StudyCloseDeliveryError as exc:
        raise RuntimeError("V2 activation local delivery preflight failed") from exc
    if inspected.checkpoint_digest != checkpoint.checkpoint_digest:
        raise RuntimeError("V2 activation checkpoint inspection drifted")


def require_v2_delivery_preflight(
    writer: StateWriter, *, root: Path = ROOT
) -> None:
    """Reject mutation unless local-main and full delivery authority are ready."""

    _read_v2_delivery_checkpoint(root)
    try:
        require_local_main(root)
    except StudyCloseDeliveryError as exc:
        raise RuntimeError("V2 activation is not on checked-out local main") from exc
    writer.require_study_close_delivery_guard()


def require_activation_ready(
    writer: StateWriter,
    *,
    prefix: int,
    root: Path = ROOT,
    allow_delivery_mutation: bool = False,
) -> None:
    """Share the same fail-closed apply readiness in CLI plan and mutation modes."""

    if prefix < 0 or prefix > len(STEPS):
        raise RuntimeError("V2 activation prefix is invalid")
    if type(allow_delivery_mutation) is not bool:
        raise RuntimeError("V2 delivery preflight mode is invalid")
    if prefix == len(STEPS):
        return
    # Authenticate the cheap local checkpoint before hashing the large protected
    # prerequisite or permitting a delivery-side mutation.
    _read_v2_delivery_checkpoint(root)
    require_current_validator_for_apply()
    require_observed_development_materialization(root)
    if prefix == 0:
        observed = {
            relative: sha256((root / relative).read_bytes()).hexdigest()
            for relative in EXPECTED_PRE_V2_AUTHORITY_SHA256
        }
        if observed != EXPECTED_PRE_V2_AUTHORITY_SHA256:
            raise RuntimeError("active authority differs from the exact V2 predecessor")
    else:
        _materialized_authority_replacements(root)
    if allow_delivery_mutation:
        require_v2_delivery_preflight(writer, root=root)
    else:
        inspect_v2_delivery_preflight(root=root)


def _apply_step(
    writer: StateWriter, *, plan: CorrectionPlan, step_index: int
) -> None:
    if step_index == 0:
        writer.migrate_authority(
            replacements=plan.authority_replacements,
            reason=AUTHORITY_REASON,
            operation_id=AUTHORITY_OPERATION_ID,
            allow_active_stable_boundary=True,
        )
        return
    if step_index == 1:
        control = writer.read_control()
        writer.activate_research_protocol(
            activation=ResearchProtocolActivation(
                protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
                validator_id=EXPECTED_V2_VALIDATOR_ID,
                authority_manifest_digest=control["authority"]["manifest_digest"],
                audit_artifact_hash=plan.addendum_hash,
            ),
            operation_id=PROTOCOL_OPERATION_ID,
            allow_active_stable_boundary=True,
        )
        return
    if step_index == 2:
        writer.record_historical_replay_correction(
            adjudication_record_ids=ADJUDICATION_RECORD_IDS,
            satisfactions=plan.satisfactions,
            operation_id=REPLAY_OPERATION_ID,
        )
        return
    raise RuntimeError("unknown V2 correction step")


def apply_corrections(
    *,
    root: Path = ROOT,
    writer_factory: Callable[..., StateWriter] = StateWriter,
    explicit_recovery: bool = False,
) -> dict[str, object]:
    """Recover explicitly, then execute only the missing strict suffix."""

    registry = EvidenceValidatorRegistry((ScientificAdjudicationValidatorV2(),))
    writer = writer_factory(root, validation_registry=registry)
    try:
        stable = writer.require_stable_head()
        recovery: Mapping[str, object] = {
            "mode": "stable_head_no_recovery",
            **stable,
        }
    except RecoveryRequired:
        if not explicit_recovery:
            raise
        recovery = {"mode": "explicit_recovery", **writer.recover()}
    prefix = inspect_correction_prefix(writer)
    if prefix == len(STEPS):
        completed = validate_completed_correction_ancestor(writer, root=root)
        return {
            **completed,
            "applied_step_count": 0,
            "initial_prefix": prefix,
            "recovery": recovery,
            "schema": "project_goal_audit_v2_correction_result.v1",
        }
    validate_correction_progress(writer, prefix=prefix)
    plan = (
        build_correction_plan(writer, root=root)
        if prefix == 0
        else build_resume_plan(writer, root=root)
    )
    require_activation_ready(
        writer,
        prefix=prefix,
        root=root,
        allow_delivery_mutation=True,
    )
    _finalize_audit_artifacts(writer, plan)
    initial_prefix = prefix
    for step_index in range(prefix, len(STEPS)):
        read_frozen_audit_report(root)
        if inspect_correction_prefix(writer) != step_index:
            raise RuntimeError("V2 correction prefix changed concurrently")
        _apply_step(writer, plan=plan, step_index=step_index)
        if inspect_correction_prefix(writer) != step_index + 1:
            raise RuntimeError("V2 correction step did not advance exactly once")
        validate_correction_progress(writer, prefix=step_index + 1)
    completed = validate_completed_correction_ancestor(writer, root=root)
    return {
        **completed,
        "applied_step_count": len(STEPS) - initial_prefix,
        "initial_prefix": initial_prefix,
        "recovery": recovery,
        "schema": "project_goal_audit_v2_correction_result.v1",
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or crash-resumably apply the strict Project Goal audit V2 "
            "canonical correction chain."
        )
    )
    parser.add_argument(
        "--apply-corrections",
        action="store_true",
        help="apply authority, protocol, and replay correction through StateWriter",
    )
    parser.add_argument(
        "--recover",
        action="store_true",
        help="explicitly authorize projection recovery before applying corrections",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    if arguments.apply_corrections:
        print(
            json.dumps(
                apply_corrections(
                    root=ROOT,
                    explicit_recovery=arguments.recover,
                ),
                sort_keys=True,
            )
        )
        return
    if arguments.recover:
        raise SystemExit("--recover requires --apply-corrections")
    writer = StateWriter(
        ROOT,
        validation_registry=EvidenceValidatorRegistry(
            (ScientificAdjudicationValidatorV2(),)
        ),
    )
    writer.require_stable_head()
    prefix = inspect_correction_prefix(writer)
    if prefix == len(STEPS):
        summary = validate_completed_correction_ancestor(writer, root=ROOT)
    else:
        validate_correction_progress(writer, prefix=prefix)
        plan = (
            build_correction_plan(writer, root=ROOT)
            if prefix == 0
            else build_resume_plan(writer, root=ROOT)
        )
        require_activation_ready(writer, prefix=prefix, root=ROOT)
        summary = {
            "apply_flag": "--apply-corrections",
            "authority_replacement_sha256": EXPECTED_AUTHORITY_SHA256,
            "current_prefix": prefix,
            "effective_scope_overlay_id": plan.replay_plan[
                "effective_scope_overlay"
            ]["record_id"],
            "mode": "read_only_plan",
            "operation_count": len(STEPS),
            "p0_satisfaction_count": len(plan.satisfactions),
            "p1_pending_count": len(plan.replay_plan["pending_after_apply"]),
            "report_sha256": plan.report_hash,
            "integration_addendum_sha256": plan.addendum_hash,
            "stu0061_obligation_id": EXPECTED_STU0061_OBLIGATION_ID,
        }
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
