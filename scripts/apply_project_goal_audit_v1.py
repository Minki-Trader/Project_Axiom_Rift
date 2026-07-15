from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping, Sequence

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.core.canonical import canonical_bytes, parse_canonical  # noqa: E402
from axiom_rift.operations.validation import (  # noqa: E402
    EvidenceValidatorRegistry,
)
from axiom_rift.operations.writer import RecoveryRequired, StateWriter  # noqa: E402
from axiom_rift.research.adjudication import (  # noqa: E402
    adjudicate_plan_measurement,
)
from axiom_rift.research.historical_adjudication import (  # noqa: E402
    HistoricalAdjudicationRequest,
    HistoricalDisposition,
    HistoricalValidityOverride,
    HistoricalValidityReason,
    ReplayPriority,
    profile_manifest,
)
from axiom_rift.research.protocol import (  # noqa: E402
    ResearchProtocol,
    ResearchProtocolActivation,
)
from axiom_rift.research.decision_withdrawal import (  # noqa: E402
    PortfolioDecisionWithdrawalManifest,
    PortfolioDecisionWithdrawalReason,
)
from axiom_rift.research.source_authority import (  # noqa: E402
    SourceAuthorityAuditManifest,
    SourceAuthorityInvalidation,
    SourceAuthorityReason,
    SourceAuthoritySurface,
)
from axiom_rift.research.validation_v2 import (  # noqa: E402
    ScientificAdjudicationValidatorV2,
)
from axiom_rift.storage.index import LocalIndex  # noqa: E402


AUTHORITY_OPERATION_ID = "project-goal-audit-v1-authority"
AUTHORITY_REASON = (
    "activate forest-first staged adjudication and bounded validation repairs"
)
CORRECTION_OPERATION_PREFIX = "project-goal-audit-v1-"
AUDIT_REPORT_RELATIVE_PATH = Path(
    "records/audits/2026-07-13_project_goal_audit_v1.md"
)
AUDIT_OBSERVED_AT_UTC = "2026-07-13T14:34:18Z"
EXPECTED_INITIAL_REVISION = 4882
EXPECTED_INITIAL_EVENT_ID = (
    "df62b4e57c57b6175440650de020be4eb3c188608c6f23af980217cabc6bf5ad"
)
EXPECTED_INITIAL_AUTHORITY_MANIFEST = (
    "be90cc2b5c7142f164e9505b87028b47de3f2a5edc3f99baa5f4340c70ebe891"
)
EXPECTED_MISSION_ID = "MIS-0006"
EXPECTED_INITIATIVE_ID = "INI-0016"
EXPECTED_PENDING_DECISION_ID = (
    "decision:6f2e008b493dba4b39b1ba93bb0e70435c85ac45c8aac257a1b7058f976eaf7b"
)
EXPECTED_PORTFOLIO_SNAPSHOT_ID = (
    "portfolio:b2ac01b88c260505f07ff20e722f320f6eaa63d7bbf52dd3fe1401c98e28c782"
)
EXPECTED_PENDING_ACTION = {
    "action": "contrast",
    "architecture_chassis_identity": (
        "architecture-family:"
        "c2339764ab5a058ca0c3371ca68b95f6224936610342fd446edc3bc29a5dbc34"
    ),
    "baseline_executable_id": (
        "executable:"
        "5699a83382b4b980287bf7ac397d94bed5b664e80452204f1cb9eea321ba9a39"
    ),
    "decision_id": EXPECTED_PENDING_DECISION_ID,
    "kind": "execute_portfolio_decision",
    "portfolio_snapshot_id": EXPECTED_PORTFOLIO_SNAPSHOT_ID,
    "resolved_architecture_family": (
        "architecture-family:"
        "c2339764ab5a058ca0c3371ca68b95f6224936610342fd446edc3bc29a5dbc34"
    ),
    "target_axis_identity": (
        "axis:4a796c57166fac6ca32cdb30018b91560a96729840608c4cff48b47f7501b8eb"
    ),
    "target_id": "axis-tlt-duration-risk-source",
}
EXPECTED_STABLE_ACTION = {
    "kind": "portfolio_decision",
    "portfolio_snapshot_id": EXPECTED_PORTFOLIO_SNAPSHOT_ID,
}
EXPECTED_FINAL_ACTION = {
    "kind": "choose_next_initiative_or_terminal",
    "mission_id": EXPECTED_MISSION_ID,
}
EXPECTED_INVARIANT_KIND_COUNTS = {
    "job-completed": 497,
    "negative-memory": 462,
    "portfolio-decision": 193,
    "study-open": 104,
    "trial": 555,
}
EXPECTED_LEGACY_SCIENTIFIC_COMPLETIONS = 470
EXPECTED_VALIDITY_OVERRIDE_COUNT = 34
HISTORICAL_V1_VALIDATOR_ID = (
    "validator:bf4491b3f1773c654e89b5e10a3fac226e5f9ab52ed1d6252d56e7733c477d97"
)
HISTORICAL_CHUNK_SIZE = 20
EXPECTED_LEGACY_STATE_COUNTS = {
    "not_evaluable": 8,
    "partial_positive": 422,
    "unresolved": 40,
}
P0_REPLAY_COMPLETIONS = frozenset(
    {
        "7a89fdfc04b975892e474729c1eb74aa690e56c6dc7fb22542a3a64a75c911e5",
        "25464507ca40a7c06990e33817519d534931cfd7f53fd24367e95dbd3d7060b4",
        "c4b2de1fcc471e0332db5e619000a78b7cb79520d2fba68d4059bf474545affc",
        "a41bf5c53dec70cc5a0f9062b64bd883e19b8dbce46fb4c82df843062dfff9e3",
        "fd95d06ec1d08a0470a637130a378dc90dc3b1bfdd4163204749bfe74e8b607e",
        "1f9eb539ce1e6fc84c1877784a0eb0d2d8402479b869d0772b05aee511e7ae7b",
    }
)
P1_REPLAY_COMPLETIONS = frozenset(
    {
        "320c720bee788a042e8e9c04b0af27311284054445272a958f7f2b615fca6a8f",
        "286c700ca699ee143841351e3364778d2bdf726132ae74dca9db2ad6199f48b0",
        "abd0a757858a2e771d063e64c533403993c5eab97c5b6f5f7d2e3752f2bc5a09",
        "1da33b84294f6d6fbcb2c93368d9cb7fc177d6328d45cc858688933e9449eff2",
        "9765f44d5c872bcba69cd3838b0758e7978720e3926cadd78e91d42e020eb1d8",
        "731e78ec1fa83c667d0370d600de6b4ced384cde60499fa47f07f04c81047d03",
        "1dc22a06fbd0537f4f72540fded629e79cb83931c113f9ca564dcff2cac22853",
    }
)
INVENTORY_PARTIAL_POSITIVE_STUDIES = frozenset(
    {
        "STU-0004",
        "STU-0005",
        "STU-0009",
        "STU-0013",
        "STU-0015",
        "STU-0020",
        "STU-0033",
        "STU-0040",
        "STU-0055",
        "STU-0059",
        "STU-0064",
        "STU-0065",
        "STU-0066",
        "STU-0067",
        "STU-0068",
        "STU-0069",
        "STU-0071",
        "STU-0072",
        "STU-0077",
        "STU-0091",
    }
)
EXACT_SURFACE_PRUNE_STUDIES = frozenset(
    {
        "STU-0002",
        "STU-0003",
        "STU-0022",
        "STU-0024",
        "STU-0025",
        "STU-0026",
        "STU-0027",
        "STU-0030",
        "STU-0031",
        "STU-0043",
        "STU-0046",
        "STU-0047",
        "STU-0052",
        "STU-0057",
        "STU-0060",
        "STU-0063",
        "STU-0075",
        "STU-0076",
        "STU-0098",
        "STU-0100",
        "STU-0101",
    }
)


@dataclass(frozen=True, slots=True)
class SourceCorrectionSpec:
    label: str
    source_contract_id: str
    source_state_record_id: str
    report_finding_id: str
    observed_defect: str


@dataclass(frozen=True, slots=True)
class SourceCorrection:
    spec: SourceCorrectionSpec
    manifest: SourceAuthorityAuditManifest
    manifest_bytes: bytes
    invalidation: SourceAuthorityInvalidation


@dataclass(frozen=True, slots=True)
class CorrectionStep:
    operation_id: str
    event_kind: str


@dataclass(frozen=True, slots=True)
class CorrectionPlan:
    report_bytes: bytes
    report_hash: str
    authority_replacements: Mapping[str, bytes]
    withdrawal_manifest: PortfolioDecisionWithdrawalManifest
    withdrawal_manifest_bytes: bytes
    withdrawal_manifest_hash: str
    source_corrections: tuple[SourceCorrection, ...]
    historical_requests: tuple[HistoricalAdjudicationRequest, ...]
    historical_chunks: tuple[tuple[HistoricalAdjudicationRequest, ...], ...]
    steps: tuple[CorrectionStep, ...]


SOURCE_CORRECTION_SPECS = (
    SourceCorrectionSpec(
        label="a4-us500-legacy-1",
        source_contract_id=(
            "source:9b89589ec45d323da788348d0a4b37085c3dd37df770891a90688eb22a2dcf49"
        ),
        source_state_record_id=(
            "f96f8b11059e1dc6ca93d9d1489f927927eaef6e2369e4bddefb620ba75ba084"
        ),
        report_finding_id="A4-US500-LEGACY-1",
        observed_defect=(
            "current broker history cannot prove historical first availability "
            "or original vintage"
        ),
    ),
    SourceCorrectionSpec(
        label="a4-us500-legacy-2",
        source_contract_id=(
            "source:5b1a2771e4eeb04dea645631645fc99d41783e0ce34fc5d40e95bc01ca79c1f7"
        ),
        source_state_record_id=(
            "42a526bfaa126965e00efec20962f8c1b561ef3fe74fe5877ba2eba1e9cc9b7b"
        ),
        report_finding_id="A4-US500-LEGACY-2",
        observed_defect=(
            "current broker history cannot prove historical first availability "
            "or original vintage"
        ),
    ),
    SourceCorrectionSpec(
        label="a4-us30-legacy",
        source_contract_id=(
            "source:040336fe558e3c669e0b20569ec793d3d7ccf81956f14ae9b9bfd240bb8f1c87"
        ),
        source_state_record_id=(
            "e9b460708e619d1a3d52dc85c86679983e992df6d1a5891a61c32a290da16630"
        ),
        report_finding_id="A4-US30-LEGACY",
        observed_defect=(
            "current broker history cannot prove historical first availability "
            "or original vintage"
        ),
    ),
    SourceCorrectionSpec(
        label="a4-usdjpy-legacy",
        source_contract_id=(
            "source:c7e633301aaa5e35029034508eb2f5e7f79507395e0d5385db74c2fe01872e73"
        ),
        source_state_record_id=(
            "f71f2c587ef1ff40e589607d5ff074d45d252816dc88c9588499e3149d573ac7"
        ),
        report_finding_id="A4-USDJPY-LEGACY",
        observed_defect=(
            "current broker history cannot prove historical first availability "
            "or original vintage"
        ),
    ),
    SourceCorrectionSpec(
        label="a4-tlt-unstarted",
        source_contract_id=(
            "source:14356e60dfd9f1830313bb48d845ddd8b029aeeb4e7d6fd0250efb3a3b92724b"
        ),
        source_state_record_id=(
            "1315dee3def882552aacb087c36f7285a7ba757d6f797927dd3a4bd174a7e68c"
        ),
        report_finding_id="A4-TLT-UNSTARTED",
        observed_defect=(
            "unstarted context-only contract asserts unproved UTC, first "
            "availability, and original vintage"
        ),
    ),
)

WITHDRAW_OPERATION_ID = "project-goal-audit-v1-withdraw-tlt-decision"
WITHDRAW_REASON = (
    "the exhaustive audit invalidated the unstarted TLT source authority basis"
)
PROTOCOL_OPERATION_ID = "project-goal-audit-v1-activate-v2-protocol"
CLOSE_INITIATIVE_OPERATION_ID = "project-goal-audit-v1-close-ini-0016-superseded"


def _replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label} anchor count is {count}, expected one")
    return text.replace(old, new, 1)


def _authority_text(root: Path, relative: str) -> str:
    try:
        return (root / relative).read_bytes().decode("ascii")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"authority document is not ASCII: {relative}") from exc


def _operating_direction(root: Path) -> bytes:
    text = _authority_text(root, "OPERATING_DIRECTION.md")
    text = _replace_once(
        text,
        """- [MUST] OD-SNP-010 The previous scientific operation evaluated eighteen unique
  configurations. This remains exposure accounting, while its coupled
  executable hashes are not new duplicate authority. Future work using the same
  observed development material includes eighteen as the minimum prior global
  multiplicity exposure.
""",
        """- [MUST] OD-SNP-010 The previous scientific operation evaluated eighteen unique
  configurations. This remains descriptive exposure and duplicate-search
  context. It is never an automatic multiplicity factor for an unrelated or
  later concurrent family; each adjudication binds its own preregistered family.
""",
        label="OD-SNP-010",
    )
    text = _replace_once(
        text,
        """- [MUST] OD-EXT-011 Symbol synchronization, feed freshness, market closure, and
  latency are tested before the source enters an executable Batch.
""",
        """- [MUST] OD-EXT-011 Historical content and semantic eligibility are checked before
  an offline performance Batch. Live synchronization, freshness, market closure,
  and latency are checked at runtime entry and candidate-bound runtime evidence;
  expired wall-clock freshness alone does not invalidate sealed historical bytes.
""",
        label="OD-EXT-011",
    )
    text = _replace_once(
        text,
        """- [MUST] OD-REP-002 Repair freezes the scientific identity, classifies the cause,
  performs the smallest coherent change, verifies the affected surface, and
  resumes the interrupted Job.
""",
        """- [MUST] OD-REP-002 Repair freezes the scientific identity, classifies the cause,
  performs the smallest coherent change, verifies the affected surface, and
  resumes the interrupted Job. A failed repair attempt remains engineering
  evidence and may be followed by another changed-cause repair while recovery
  remains feasible and has positive expected value.
""",
        label="OD-REP-002",
    )
    text = _replace_once(
        text,
        """- [MUST] OD-REC-018 Prospective Study-close delivery is mechanically enforced.
  The tracked commit-msg hook reads the staged Journal, control, and KPI bytes,
  requires all three paths in one commit, deterministically rerenders the KPI,
  and accepts only one contiguous final trailer block bound to the exact close
  event and revision. Bypassing the hook is prohibited. The StateWriter verifies
  that the exact tracked executable hook is active and independently audits
  every prospective closeout or exact authorized repair on local main before a
  later Portfolio snapshot or Decision, Study, Batch, or Job declaration. A
  missing, disabled, modified, or malformed checkpoint guard blocks those later
  scientific state mutations.
""",
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
        label="OD-REC-018",
    )
    audit_section = """## 22. Audit-Corrected Quant Research Protocol

- [MUST] OD-AUD-001 Historical events, trials, closes, and negative memories are
  immutable. A discovered interpretation defect is corrected by an additive,
  provenance-bound, claim-scoped adjudication or authority invalidation.
- [MUST] OD-AUD-002 Job outcome describes operational execution only. A completed
  computation with valid declared outputs is success; its independent scientific
  verdict is passed, failed, or not_evaluable. Engineering failure has no
  scientific verdict, falsification, negative memory, or trial implication.
- [MUST] OD-AUD-003 Scientific adjudication separates validity, discovery,
  confirmation, and candidate authority. Discovery maps a frontier and can
  preserve a partial positive, but can never create candidate authority.
- [MUST] OD-AUD-004 Each preregistered claim criterion has a typed role and one of
  supported, contradicted, unresolved, invalid, or diagnostic state. Only the
  criteria declared decisive for that claim may contradict it; missing or
  invalid inputs make that claim not evaluable rather than falsely negative.
- [MUST] OD-AUD-005 Selection adjustment binds the exact concurrent family, raw
  p-value, Monte Carlo uncertainty, method, alpha, and adjusted p-value.
  Project-wide search history remains context and duplicate authority only.
- [MUST] OD-AUD-006 A live frontier is scheduled as a simultaneous forest when
  axes share data and a decision boundary. The scheduler compares information
  value, identifiability, cost, architecture, and opportunity cost, then deepens,
  contrasts, recombines, or prunes without recency monopoly.
- [MUST] OD-AUD-007 Monthly drawdown concentration profile B04 is diagnostic in
  discovery unless the preregistration makes it a decisive risk gate. Diagnostic
  failure cannot erase supported signal, activity, or stress economics.
- [MUST] OD-AUD-008 Mission exhaustion is an evidence-bound professional judgment
  under its preregistered standard, not satisfaction of counts alone. Numeric
  floors and required evidence modes remain immutable inside that Mission; an
  audit-exposed standard defect is preserved for the successor standard rather
  than used to reinterpret current evidence. Partial, invalid, or unresolved
  axes require a typed additive preserve, replay, reopen, defer, or reason-bound
  retirement disposition. A partial positive cannot be manufactured into a
  prune. At least one axis must be an exact low-information retirement with its
  required negative depth; every other disposition carries its continuation or
  reopen condition into the successor. Unresolved candidate-eligible positive
  evidence still forbids a negative Mission terminal.
- [MUST] OD-AUD-009 Repair feasibility and expected value, not one failed attempt,
  determine whether engineering recovery continues. Repeated attempts require a
  changed cause, input, implementation, or information state.
- [MUST] OD-AUD-010 Current broker history proves reconstruction under the observed
  current interface only. It cannot prove historical first availability, vintage,
  revision state, or point-in-time knowledge without independent evidence.
- [MUST] OD-AUD-011 MT5 epoch values are an observed coordinate until documentation
  and the actual provider runtime agree. A conflict leaves absolute timezone,
  broker-session mapping, and DST authority unknown and permits no silent shift.
- [MUST] OD-AUD-012 Component and engine identity bind the current implementation
  bytes and declared semantic dependencies. Fixed labels or copied baseline
  engine identities cannot attest changed code or a participating source.
- [MUST] OD-AUD-013 Audit-invalidated source authority is latched on the exact
  source-state head. Ordinary recertification cannot clear it; the declared
  resolution policy, normally a new source contract, is required.
- [MUST] OD-AUD-014 Architecture family identity is semantic: stable component
  roles, causal boundaries, and runtime bindings define the family. Artifact
  hashes remain Component and Executable identity, not gratuitous family splits.
- [MUST] OD-AUD-015 Prospective Studies use reusable component and adjudication
  engines with declarative plans. Historical runners remain compatibility
  surfaces until exact parity evidence supports retirement.
- [MUST] OD-AUD-016 Validation protects the changed surface and claim at risk.
  Routine checks use keyed projections, immutable-segment verification caches,
  and suffix guards; complete audits are explicit maintenance, not per-Job delay.
- [MUST] OD-AUD-017 A missing source at dependent entry means no dependent entry.
  If a held dependent sleeve loses required state, it follows a preregistered
  safe exit. Independent controls and unrelated sleeves remain unaffected.
- [MUST] OD-AUD-018 The first exhaustive audit must be followed by actual research
  under the repaired protocol and a second exhaustive audit. Neither audit alone
  creates candidate, terminal, or Project Goal completion authority.

## 23. Governing Principle
"""
    text = _replace_once(
        text,
        "## 22. Governing Principle\n",
        audit_section,
        label="governing principle section",
    )
    return text.encode("ascii")


def _science_contract(root: Path) -> bytes:
    text = _authority_text(root, "contracts/science.yaml")
    text = _replace_once(
        text,
        "  exhaustion_standard_is_immutable: true\n",
        "  exhaustion_standard_is_immutable: true\n"
        "  in_mission_exhaustion_standard_amendment_allowed: false\n"
        "  audit_defect_routes_to_successor_standard: true\n",
        label="science exhaustion immutability",
    )
    text = _replace_once(
        text,
        "    final_snapshot_all_axes_pruned: true\n",
        "    final_snapshot_all_axes_pruned: false\n"
        "    final_snapshot_all_axes_evidence_bound_disposition: true\n"
        "    axis_disposition_record_required: true\n"
        "    axis_disposition_actions:\n"
        "      - preserve\n"
        "      - replay\n"
        "      - reopen\n"
        "      - defer\n"
        "      - retire_with_reason\n"
        "    partial_positive_retirement_allowed: false\n"
        "    scientific_exhaustion_requires_low_information_negative_depth: true\n"
        "    terminal_requires_at_least_one_scientifically_exhausted_axis: true\n"
        "    nonexhausted_disposition_carries_successor_condition: true\n",
        label="science terminal axes",
    )
    addition = """
scientific_adjudication_v2:
  prospective_activation_required: true
  validator_semantic_and_operational_identity_authority: contracts/evidence.yaml
  stages:
    discovery:
      purpose: frontier_mapping
      candidate_authority: false
      partial_positive_allowed: true
      confirmation_grade_conjunction_required: false
    confirmation:
      purpose: promotion_grade_claim_testing
      untouched_or_separately_permitted_material_required: true
      candidate_authority_requires_all_decisive_claims: true
  criterion_roles:
    - validity
    - component
    - multiplicity
    - risk_diagnostic
    - risk_gate
  criterion_states:
    - supported
    - contradicted
    - unresolved
    - invalid
    - diagnostic
  result_states:
    - not_evaluable
    - contradicted
    - unresolved
    - partial_positive
    - frontier
    - confirmed
  discovery_candidate_eligible: false
  invalid_or_missing_decisive_input: not_evaluable
  unrelated_claim_compensation_allowed: false
  monthly_drawdown_profile_b04_default_role: risk_diagnostic
  multiplicity:
    authority: preregistered_concurrent_family_only
    global_search_history_role: context_and_duplicate_detection_only
    raw_and_adjusted_values_preserved: true
    monte_carlo_point_and_upper_preserved: true
historical_scientific_correction:
  original_event_rewrite_allowed: false
  additive_claim_scoped_adjudication_required: true
  candidate_authority: false
  trial_or_holdout_delta: 0
  missing_uncertainty_evidence_opens_bounded_replay: true
job_science_separation:
  operational_outcomes:
    - success
    - failed
    - not_evaluable
  scientific_verdicts:
    - passed
    - failed
    - not_evaluable
  validator_result_independent_of_job_status: true
  operational_failure_scientific_falsification_allowed: false
forest_execution:
  shared_boundary_axes_may_run_as_one_preregistered_concurrent_family: true
  sequential_recency_monopoly_allowed: false
  generic_engine_preferred_over_temporal_study_module: true
  exact_common_calendar_required: true
  implicit_missing_day_zero_fill_allowed: false
"""
    if "scientific_adjudication_v2:" in text:
        raise RuntimeError("science audit section is already present")
    return (text.rstrip() + "\n" + addition.lstrip()).encode("ascii")


def _operations_contract(root: Path) -> bytes:
    text = _authority_text(root, "contracts/operations.yaml")
    addition = """
project_goal_audit_correction:
  authority_migration_is_single_writer_only: true
  historical_state_rewrite_allowed: false
  accepted_unstarted_decision_withdrawal_requires_exact_basis_and_evidence: true
  source_authority_invalidation_is_additive_and_latched: true
  prospective_protocol_rebinds_after_later_authority_migration: true
job_result_semantics:
  operational_success_requires_declared_outputs_and_validation: true
  scientific_verdict_is_independent: true
  scientific_falsification_as_operational_failure_allowed: false
  legacy_failed_scientific_completion_remains_readable: true
  negative_memory_uses_validator_verdict: true
source_authority_audit:
  exact_active_source_head_bound: true
  canonical_audit_manifest_and_report_provenance_required: true
  unrelated_artifact_reuse_allowed: false
  prior_legitimate_receipt_preserved: true
  audit_invalidation_may_not_impersonate_job_completion: true
  ordinary_same_semantics_recertification_clears_latch: false
  resolution_policy_required: true
  current_point_in_time_defect_resolution: new_source_contract
research_protocol:
  stream: research-protocol:scientific
  supported: scientific_adjudication_v2
  current_authority_manifest_bound: true
  latest_valid_stream_head_is_active: true
  authority_migration_requires_additive_rebinding_before_scientific_job: true
  same_authority_duplicate_activation_allowed: false
  trial_holdout_and_candidate_delta: 0
mission_axis_disposition:
  single_writer_route: record_axis_dispositions
  portfolio_snapshot_rewrite_allowed: false
  accepted_evidence_kinds:
    - job-completed
    - historical-scientific-adjudication
    - negative-memory
  writer_rederives_state_and_candidate_eligibility: true
  actions:
    - preserve
    - replay
    - reopen
    - defer
    - retire_with_reason
  partial_positive_retirement_allowed: false
  low_information_retirement_requires_negative_memory: true
  exact_latest_disposition_required_for_terminal: true
  terminal_requires_at_least_one_scientifically_exhausted_axis: true
  unresolved_candidate_eligible_positive_blocks_terminal: true
  trial_holdout_candidate_and_claim_delta: 0
validation_economics:
  routine_study_close_delivery_basis: tamper_evident_high_water_and_new_suffix
  complete_history_scan: explicit_maintenance_only
  sealed_segment_hash_cache: process_shared_bounded_by_identity
  current_kind_counts: materialized_projection
  routine_cost_may_grow_with_history: false
study_close_delivery_checkpoint:
  tracked_checkpoint: records/STUDY_CLOSE_DELIVERY_CHECKPOINT.json
  schema: study_close_delivery_checkpoint.v1
  git_authenticated_high_water: true
  ignored_local_cache_role: non_authoritative_hint_only
  routine_validation_reads: checkpoint_boundary_and_bounded_suffix
  routine_active_segment_prefix_rehash_required: false
  missing_local_cache_forces_full_audit: false
  initialization_requires_explicit_complete_history_audit: true
  initialization_commit_trailers:
    - Axiom-Study-Close-Checkpoint
    - Axiom-State-Revision
  prospective_close_advances_checkpoint_in_same_commit: true
  prospective_required_same_commit_paths:
    - state/control.json
    - records/STUDY_KPI.md
    - resolved_journal_paths
    - records/STUDY_CLOSE_DELIVERY_CHECKPOINT.json
  omitted_modified_or_malformed_checkpoint_blocks_later_science: true
  no_op_guard_rewrites_local_projection: false
"""
    if "project_goal_audit_correction:" in text:
        raise RuntimeError("operations audit section is already present")
    return (text.rstrip() + "\n" + addition.lstrip()).encode("ascii")


def _evidence_contract(root: Path) -> bytes:
    text = _authority_text(root, "contracts/evidence.yaml")
    text = _replace_once(
        text,
        "  identity_binds_protocol_domains_and_implementation_hash: true\n",
        "  identity_binds_protocol_domains_and_implementation_hash: true\n"
        "  semantic_and_operational_identity:\n"
        "    semantic_validator_identity_binds_protocol_domains_implementation_bytes_and_authored_dependencies: true\n"
        "    semantic_dependency_may_be_downgraded_to_closure_only: false\n"
        "    inferred_recursive_execution_closure_binds_registry_and_job_implementation_authority: true\n"
        "    closure_only_drift_reidentifies_validator_executable_claim_trial_or_history: false\n"
        "    closure_only_drift_blocks_or_reidentifies_future_job_execution: true\n",
        label="validator semantic and operational identity",
    )
    addition = """
scientific_adjudication_v2:
  plan_measurement_and_result_are_exact_bound_artifacts: true
  authored_semantic_validator_dependency_hashes_are_identity: true
  criterion_roles_are_preregistered: true
  component_dimensions_are_non_compensatory: true
  invalid_unresolved_and_diagnostic_are_not_failed: true
  only_exact_contradiction_is_scientific_failure: true
  discovery_candidate_eligible: false
  confirmation_candidate_requires_all_decisive_gates: true
  project_history_fields_in_multiplicity_artifact_allowed: false
  concurrent_family_raw_and_adjusted_pvalues_recomputed: true
historical_adjudication:
  original_evidence_hashes_required: true
  exact_completion_and_study_close_required: true
  legacy_completion_without_rich_v2_only: true
  interpretation_recomputed_by_writer: true
  profile_is_writer_derived_fixed_legacy_v1: true
  caller_multiplicity_or_risk_profile_authority: false
  validity_overrides_are_writer_derived_from_durable_source_latches: true
  validity_override_supersession_is_union_monotone: true
  additive_qualification_only: true
  candidate_trial_and_holdout_delta: 0
axis_disposition:
  additive_and_portfolio_snapshot_preserving: true
  exact_evidence_references_required: true
  effective_state_and_candidate_eligibility_writer_derived: true
  partial_invalid_unresolved_and_low_information_preserved: true
  scientific_exhaustion_requires_exact_negative_depth: true
  candidate_trial_holdout_and_claim_delta: 0
"""
    if "scientific_adjudication_v2:" in text:
        raise RuntimeError("evidence audit section is already present")
    return (text.rstrip() + "\n" + addition.lstrip()).encode("ascii")


def _runtime_contract(root: Path) -> bytes:
    text = _authority_text(root, "contracts/runtime.yaml")
    addition = """
source_time_coordinate:
  mt5_epoch_is_observed_coordinate_not_assumed_timezone: true
  documentation_runtime_conflict_state: absolute_timezone_unknown
  broker_timezone_or_dst_inference_from_offset_allowed: false
  silent_performance_shift_allowed: false
  session_authority_requires_independent_evidence: true
source_freshness_scope:
  sealed_historical_performance_requires_current_wall_clock_freshness: false
  runtime_entry_and_candidate_runtime_evidence_require_freshness: true
  trial_registration_reuses_batch_permit_source_scope: true
source_dependency_lifecycle:
  missing_at_dependent_entry: no_entry
  stale_or_missing_while_held: preregistered_safe_exit
  retain_baseline_pnl_for_missing_dependent_subject: false
  independent_control_unaffected: true
  unrelated_sleeves_unaffected: true
source_authority_invalidation:
  audit_latched_on_exact_source_head: true
  ordinary_recertification_restores_invalidated_contract: false
  point_in_time_authority_defect_requires_new_source_contract: true
implementation_identity:
  actual_python_mql_and_dependency_bytes_required: true
  fixed_placeholder_digest_allowed: false
  copied_baseline_engine_contract_for_changed_engine_allowed: false
"""
    if "source_time_coordinate:" in text:
        raise RuntimeError("runtime audit section is already present")
    return (text.rstrip() + "\n" + addition.lstrip()).encode("ascii")


def build_authority_replacements(root: Path = ROOT) -> dict[str, bytes]:
    replacements = {
        "OPERATING_DIRECTION.md": _operating_direction(root),
        "contracts/evidence.yaml": _evidence_contract(root),
        "contracts/operations.yaml": _operations_contract(root),
        "contracts/runtime.yaml": _runtime_contract(root),
        "contracts/science.yaml": _science_contract(root),
    }
    for relative, content in replacements.items():
        content.decode("ascii")
        if relative.endswith(".yaml"):
            value = yaml.safe_load(content)
            if not isinstance(value, dict):
                raise RuntimeError(f"replacement is not a YAML mapping: {relative}")
    return replacements


def replacement_summary(replacements: Mapping[str, bytes]) -> dict[str, object]:
    return {
        "replacements": [
            {
                "path": relative,
                "sha256": sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
            for relative, content in sorted(replacements.items())
        ],
        "schema": "project_goal_audit_v1_authority_replacements.v1",
    }


def _required_report_markers() -> tuple[str, ...]:
    source_markers = tuple(
        marker
        for spec in SOURCE_CORRECTION_SPECS
        for marker in (
            spec.report_finding_id,
            spec.source_contract_id,
            spec.source_state_record_id,
        )
    )
    return (
        "status: first_pass_complete_repair_verified_pending_canonical_activation",
        f"control_revision: {EXPECTED_INITIAL_REVISION}",
        f"control_event: {EXPECTED_INITIAL_EVENT_ID}",
        "holdout_reads: 0",
        "quarantine_reads: 0",
        AUDIT_OBSERVED_AT_UTC,
        *source_markers,
        "Canonical activation is a fixed single-writer sequence:",
        "## First Repair Acceptance",
        "## Goal Completion Boundary",
        "actual Initiative/Study work",
        "second full audit",
    )


def read_frozen_audit_report(root: Path = ROOT) -> tuple[bytes, str]:
    """Read and fail closed on the exact report that authorizes correction."""

    path = root / AUDIT_REPORT_RELATIVE_PATH
    content = path.read_bytes()
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as exc:
        raise RuntimeError("Project Goal audit report is not ASCII") from exc
    missing = [marker for marker in _required_report_markers() if marker not in text]
    if missing:
        raise RuntimeError(
            "Project Goal audit report is not the frozen correction basis: "
            + ", ".join(missing)
        )
    return content, sha256(content).hexdigest()


def require_frozen_report_unchanged(
    *,
    root: Path,
    expected_hash: str,
) -> None:
    _content, observed_hash = read_frozen_audit_report(root)
    if observed_hash != expected_hash:
        raise RuntimeError("Project Goal audit report changed during correction")


def build_source_corrections(report_artifact_hash: str) -> tuple[SourceCorrection, ...]:
    corrections: list[SourceCorrection] = []
    for spec in SOURCE_CORRECTION_SPECS:
        manifest = SourceAuthorityAuditManifest(
            report_artifact_hash=report_artifact_hash,
            report_finding_id=spec.report_finding_id,
            source_contract_id=spec.source_contract_id,
            source_state_record_id=spec.source_state_record_id,
            surface=SourceAuthoritySurface.AVAILABILITY,
            reason_code=SourceAuthorityReason.POINT_IN_TIME_AUTHORITY_UNPROVEN,
            observed_defect=spec.observed_defect,
            observed_at_utc=AUDIT_OBSERVED_AT_UTC,
        )
        manifest_bytes = canonical_bytes(manifest.to_identity_payload())
        manifest_hash = sha256(manifest_bytes).hexdigest()
        invalidation = SourceAuthorityInvalidation(
            source_contract_id=spec.source_contract_id,
            source_state_record_id=spec.source_state_record_id,
            audit_artifact_hash=manifest_hash,
            surface=manifest.surface,
            reason_code=manifest.reason_code,
            observed_defect=manifest.observed_defect,
            observed_at_utc=manifest.observed_at_utc,
        )
        corrections.append(
            SourceCorrection(
                spec=spec,
                manifest=manifest,
                manifest_bytes=manifest_bytes,
                invalidation=invalidation,
            )
        )
    if len(corrections) != 5 or len(
        {item.invalidation.identity for item in corrections}
    ) != 5:
        raise RuntimeError("source correction plan is not the exact five-item set")
    return tuple(corrections)


def build_withdrawal_manifest(
    report_artifact_hash: str,
) -> tuple[PortfolioDecisionWithdrawalManifest, bytes, str]:
    source = next(
        item for item in SOURCE_CORRECTION_SPECS if item.label == "a4-tlt-unstarted"
    )
    manifest = PortfolioDecisionWithdrawalManifest(
        report_artifact_hash=report_artifact_hash,
        report_finding_id=source.report_finding_id,
        decision_id=EXPECTED_PENDING_DECISION_ID,
        portfolio_snapshot_id=EXPECTED_PORTFOLIO_SNAPSHOT_ID,
        target_axis_id=EXPECTED_PENDING_ACTION["target_id"],
        target_axis_identity=EXPECTED_PENDING_ACTION["target_axis_identity"],
        baseline_executable_id=EXPECTED_PENDING_ACTION["baseline_executable_id"],
        source_contract_id=source.source_contract_id,
        source_state_record_id=source.source_state_record_id,
        reason_code=(
            PortfolioDecisionWithdrawalReason.SOURCE_AUTHORITY_INVALIDATED
        ),
        reason=WITHDRAW_REASON,
    )
    content = canonical_bytes(manifest.to_identity_payload())
    return manifest, content, sha256(content).hexdigest()


def historical_chunk_operation_id(*, start: int, stop: int) -> str:
    if start < 1 or stop < start or stop > EXPECTED_LEGACY_SCIENTIFIC_COMPLETIONS:
        raise ValueError("historical chunk bounds are invalid")
    return f"project-goal-audit-v1-historical-{start:03d}-{stop:03d}"


def correction_steps() -> tuple[CorrectionStep, ...]:
    chunks = tuple(
        (
            start + 1,
            min(
                start + HISTORICAL_CHUNK_SIZE,
                EXPECTED_LEGACY_SCIENTIFIC_COMPLETIONS,
            ),
        )
        for start in range(
            0,
            EXPECTED_LEGACY_SCIENTIFIC_COMPLETIONS,
            HISTORICAL_CHUNK_SIZE,
        )
    )
    steps = (
        CorrectionStep(WITHDRAW_OPERATION_ID, "portfolio_decision_withdrawn"),
        CorrectionStep(AUTHORITY_OPERATION_ID, "authority_migrated"),
        CorrectionStep(PROTOCOL_OPERATION_ID, "research_protocol_activated"),
        *(
            CorrectionStep(
                f"project-goal-audit-v1-invalidate-source-{spec.label}",
                "source_authority_suspended_from_audit",
            )
            for spec in SOURCE_CORRECTION_SPECS
        ),
        *(
            CorrectionStep(
                historical_chunk_operation_id(start=start, stop=stop),
                "historical_scientific_adjudications_recorded",
            )
            for start, stop in chunks
        ),
        CorrectionStep(CLOSE_INITIATIVE_OPERATION_ID, "initiative_closed"),
    )
    if len(steps) != 33 or len({step.operation_id for step in steps}) != len(steps):
        raise RuntimeError("correction operation plan is not the exact 33-step chain")
    return steps


def _operation_event(writer: StateWriter, operation: Any) -> Mapping[str, Any]:
    if (
        operation is None
        or operation.kind != "operation"
        or operation.status != "success"
        or operation.authority_sequence is None
        or operation.authority_event_id is None
        or operation.authority_offset is None
    ):
        raise RuntimeError("correction operation projection is invalid")
    event = writer.journal.read_event_at(
        offset=operation.authority_offset,
        expected_sequence=operation.authority_sequence,
        expected_event_id=operation.authority_event_id,
    )
    if not isinstance(event, Mapping):
        raise RuntimeError("correction operation Journal event is invalid")
    return event


def inspect_correction_prefix(
    writer: StateWriter,
    *,
    steps: Sequence[CorrectionStep] | None = None,
) -> int:
    """Require the audit transitions to be one exact, gap-free Journal prefix."""

    ordered = tuple(correction_steps() if steps is None else steps)
    expected_ids = {step.operation_id for step in ordered}
    with LocalIndex.open_read_only(writer.index_path) as index:
        unknown = sorted(
            record.record_id
            for record in index.records_by_kind_prefix(
                "operation", CORRECTION_OPERATION_PREFIX
            )
            if record.record_id not in expected_ids
        )
        if unknown:
            raise RuntimeError(
                "unknown Project Goal audit correction operation exists: "
                + ", ".join(unknown)
            )
        records = tuple(index.get("operation", step.operation_id) for step in ordered)
    present = tuple(record is not None for record in records)
    prefix = 0
    while prefix < len(present) and present[prefix]:
        prefix += 1
    if any(present[prefix:]):
        raise RuntimeError(
            "Project Goal audit correction operations are not a strict prefix"
        )
    for offset, (step, operation) in enumerate(zip(ordered[:prefix], records[:prefix])):
        assert operation is not None
        expected_sequence = EXPECTED_INITIAL_REVISION + offset + 1
        if (
            operation.authority_sequence != expected_sequence
            or operation.payload.get("event_kind") != step.event_kind
        ):
            raise RuntimeError(
                "Project Goal audit correction operation order or type is invalid"
            )
        event = _operation_event(writer, operation)
        if (
            event.get("sequence") != expected_sequence
            or event.get("operation_id") != step.operation_id
            or event.get("event_kind") != step.event_kind
        ):
            raise RuntimeError(
                "Project Goal audit correction Journal prefix is invalid"
            )
    return prefix


def _recorded_authority_replacements(
    writer: StateWriter,
) -> dict[str, bytes] | None:
    with LocalIndex.open_read_only(writer.index_path) as index:
        operation = index.get("operation", AUTHORITY_OPERATION_ID)
    if operation is None:
        return None
    event = _operation_event(writer, operation)
    payload = event.get("payload")
    rows = None if not isinstance(payload, Mapping) else payload.get("replacements")
    if not isinstance(rows, list):
        raise RuntimeError("recorded authority migration replacements are absent")
    expected_paths = {
        "OPERATING_DIRECTION.md",
        "contracts/evidence.yaml",
        "contracts/operations.yaml",
        "contracts/runtime.yaml",
        "contracts/science.yaml",
    }
    replacements: dict[str, bytes] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise RuntimeError("recorded authority migration row is invalid")
        relative = row.get("path")
        digest = row.get("artifact_sha256")
        if type(relative) is not str or type(digest) is not str:
            raise RuntimeError("recorded authority migration row is incomplete")
        content = writer.evidence.read_verified(digest)
        if sha256(content).hexdigest() != row.get("new_sha256"):
            raise RuntimeError("recorded authority replacement evidence differs")
        replacements[relative] = content
    if set(replacements) != expected_paths:
        raise RuntimeError("recorded authority replacement path set differs")
    return replacements


def resolve_authority_replacements(
    writer: StateWriter,
    *,
    root: Path = ROOT,
) -> dict[str, bytes]:
    recorded = _recorded_authority_replacements(writer)
    return build_authority_replacements(root) if recorded is None else recorded


def build_historical_adjudication_requests(
    writer: StateWriter,
    *,
    source_invalidation_record_ids: Mapping[str, str],
) -> tuple[HistoricalAdjudicationRequest, ...]:
    """Classify the exact pre-audit v1 completion set without rewriting it."""

    rows: list[tuple[str, str, str, tuple[str, ...]]] = []
    state_counts: Counter[str] = Counter()
    with LocalIndex.open_read_only(writer.index_path) as index:
        for completion in index.records_by_kind("job-completed"):
            scientific = completion.payload.get("scientific")
            if not isinstance(scientific, dict):
                continue
            plan_hash = scientific.get("validation_plan_hash")
            measurement_hashes = scientific.get("measurement_artifact_hashes")
            declaration = index.get(
                "job-declared", completion.payload.get("job_id", "")
            )
            if (
                not isinstance(plan_hash, str)
                or not isinstance(measurement_hashes, list)
                or len(measurement_hashes) != 1
                or not isinstance(measurement_hashes[0], str)
                or declaration is None
            ):
                continue
            plan = parse_canonical(writer.evidence.read_verified(plan_hash))
            measurement = parse_canonical(
                writer.evidence.read_verified(measurement_hashes[0])
            )
            if (
                not isinstance(plan, dict)
                or plan.get("schema") != "scientific_validation_plan.v1"
                or not isinstance(measurement, dict)
                or measurement.get("schema") != "scientific_measurement.v1"
            ):
                continue
            adjudication = adjudicate_plan_measurement(plan, measurement)
            study_id = declaration.payload.get("study_id")
            executable_id = scientific.get("executable_id")
            trial = (
                None
                if not isinstance(executable_id, str)
                else index.get("trial", executable_id)
            )
            executable = None if trial is None else trial.payload.get("executable")
            source_contracts = (
                ()
                if not isinstance(executable, dict)
                else executable.get("source_contracts", ())
            )
            if (
                not isinstance(study_id, str)
                or not isinstance(executable_id, str)
                or not isinstance(source_contracts, (list, tuple))
                or any(not isinstance(item, str) for item in source_contracts)
            ):
                raise RuntimeError(
                    "legacy scientific completion has malformed trial provenance"
                )
            invalid_sources = tuple(
                sorted(set(source_contracts) & set(source_invalidation_record_ids))
            )
            rows.append(
                (
                    completion.record_id,
                    study_id,
                    adjudication.state,
                    invalid_sources,
                )
            )
            state_counts[adjudication.state] += 1
    if len(rows) != EXPECTED_LEGACY_SCIENTIFIC_COMPLETIONS:
        raise RuntimeError(
            "legacy scientific completion count differs from the audited boundary"
        )
    if dict(sorted(state_counts.items())) != EXPECTED_LEGACY_STATE_COUNTS:
        raise RuntimeError(
            "legacy component-aware state counts differ from the audit"
        )
    observed_ids = {row[0] for row in rows}
    if not P0_REPLAY_COMPLETIONS.issubset(observed_ids) or not (
        P1_REPLAY_COMPLETIONS.issubset(observed_ids)
    ):
        raise RuntimeError("historical replay priority set is incomplete")

    requests: list[HistoricalAdjudicationRequest] = []
    for completion_id, study_id, state, invalid_sources in sorted(rows):
        overrides = tuple(
            HistoricalValidityOverride(
                reason=HistoricalValidityReason.SOURCE_AUTHORITY_INVALIDATED,
                subject_id=source_id,
                evidence_record_id=source_invalidation_record_ids[source_id],
            )
            for source_id in invalid_sources
        )
        reasons = {
            "legacy_conjunctive_verdict_claim_scope_qualified",
            "project_history_multiplicity_is_context_only",
        }
        if completion_id in P0_REPLAY_COMPLETIONS:
            disposition = HistoricalDisposition.REPLAY_REQUIRED
            replay_priority = ReplayPriority.P0
            reasons.add("p0_raw_daily_uncertainty_replay_required")
        elif completion_id in P1_REPLAY_COMPLETIONS:
            disposition = HistoricalDisposition.REPLAY_REQUIRED
            replay_priority = ReplayPriority.P1
            reasons.add("p1_bounded_replay_required")
        elif overrides or state == "not_evaluable":
            disposition = HistoricalDisposition.NOT_EVALUABLE_QUALIFICATION
            replay_priority = ReplayPriority.NONE
            reasons.add(
                "source_authority_invalidated"
                if overrides
                else "legacy_not_evaluable_outcome_qualified"
            )
        elif study_id in EXACT_SURFACE_PRUNE_STUDIES:
            disposition = HistoricalDisposition.EXACT_SURFACE_PRUNE_RETAINED
            replay_priority = ReplayPriority.NONE
            reasons.add("exact_surface_prune_retained_not_mechanism_ban")
        elif study_id in INVENTORY_PARTIAL_POSITIVE_STUDIES:
            disposition = HistoricalDisposition.INVENTORY_PARTIAL_POSITIVE
            replay_priority = ReplayPriority.NONE
            reasons.add("supported_component_retained_without_candidate_authority")
        else:
            disposition = HistoricalDisposition.CLAIM_SCOPED_QUALIFICATION
            replay_priority = ReplayPriority.NONE
            reasons.add("scheduler_priority_unchanged_absent_typed_replay_queue")
        requests.append(
            HistoricalAdjudicationRequest(
                completion_record_id=completion_id,
                disposition=disposition,
                replay_priority=replay_priority,
                reason_codes=tuple(reasons),
                validity_overrides=overrides,
            )
        )
    return tuple(requests)


def request_chunks(
    requests: tuple[HistoricalAdjudicationRequest, ...],
    *,
    size: int = HISTORICAL_CHUNK_SIZE,
) -> tuple[tuple[HistoricalAdjudicationRequest, ...], ...]:
    if type(size) is not int or size < 1:
        raise ValueError("historical adjudication chunk size must be positive")
    return tuple(
        requests[start : start + size]
        for start in range(0, len(requests), size)
    )


def build_correction_plan(
    writer: StateWriter,
    *,
    root: Path = ROOT,
) -> CorrectionPlan:
    report_bytes, report_hash = read_frozen_audit_report(root)
    authority_replacements = resolve_authority_replacements(writer, root=root)
    (
        withdrawal_manifest,
        withdrawal_manifest_bytes,
        withdrawal_manifest_hash,
    ) = build_withdrawal_manifest(report_hash)
    source_corrections = build_source_corrections(report_hash)
    withdrawal_manifest.require_report(report_bytes)
    for correction in source_corrections:
        correction.manifest.require_report(report_bytes)
    invalidation_ids = {
        item.spec.source_contract_id: item.invalidation.identity
        for item in source_corrections
    }
    historical_requests = build_historical_adjudication_requests(
        writer,
        source_invalidation_record_ids=invalidation_ids,
    )
    historical_chunks = request_chunks(
        historical_requests,
        size=HISTORICAL_CHUNK_SIZE,
    )
    expected_chunk_sizes = tuple(
        min(
            HISTORICAL_CHUNK_SIZE,
            EXPECTED_LEGACY_SCIENTIFIC_COMPLETIONS - start,
        )
        for start in range(
            0,
            EXPECTED_LEGACY_SCIENTIFIC_COMPLETIONS,
            HISTORICAL_CHUNK_SIZE,
        )
    )
    override_count = sum(
        len(request.validity_overrides) for request in historical_requests
    )
    if (
        len(historical_requests) != EXPECTED_LEGACY_SCIENTIFIC_COMPLETIONS
        or len({item.completion_record_id for item in historical_requests})
        != EXPECTED_LEGACY_SCIENTIFIC_COMPLETIONS
        or override_count != EXPECTED_VALIDITY_OVERRIDE_COUNT
        or len(historical_chunks) != len(expected_chunk_sizes)
        or tuple(len(chunk) for chunk in historical_chunks)
        != expected_chunk_sizes
    ):
        raise RuntimeError("historical correction plan differs from the audited set")
    return CorrectionPlan(
        report_bytes=report_bytes,
        report_hash=report_hash,
        authority_replacements=authority_replacements,
        withdrawal_manifest=withdrawal_manifest,
        withdrawal_manifest_bytes=withdrawal_manifest_bytes,
        withdrawal_manifest_hash=withdrawal_manifest_hash,
        source_corrections=source_corrections,
        historical_requests=historical_requests,
        historical_chunks=historical_chunks,
        steps=correction_steps(),
    )


def _historical_request_manifest(
    requests: Sequence[HistoricalAdjudicationRequest],
) -> list[dict[str, object]]:
    return [
        {
            "completion_record_id": item.completion_record_id,
            "disposition": item.disposition.value,
            "profile": profile_manifest(item.profile),
            "reason_codes": list(item.reason_codes),
            "replay_priority": item.replay_priority.value,
            "validity_overrides": [
                override.manifest() for override in item.validity_overrides
            ],
        }
        for item in sorted(requests, key=lambda value: value.completion_record_id)
    ]


def _require_invariant_counts(index: LocalIndex) -> None:
    observed = {
        kind: index.count_by_kind(kind)
        for kind in EXPECTED_INVARIANT_KIND_COUNTS
    }
    if observed != EXPECTED_INVARIANT_KIND_COUNTS:
        raise RuntimeError(
            "immutable scientific inventory changed during audit correction"
        )


def _require_control_progress(
    writer: StateWriter,
    *,
    prefix: int,
) -> Mapping[str, Any]:
    control = writer.read_control()
    if control is None or control.get("revision") != EXPECTED_INITIAL_REVISION + prefix:
        raise RuntimeError("control revision does not match the correction prefix")
    journal_head = control.get("heads", {}).get("journal", {})
    index_head = control.get("heads", {}).get("index", {})
    expected_sequence = EXPECTED_INITIAL_REVISION + prefix
    if (
        journal_head.get("sequence") != expected_sequence
        or index_head.get("required_sequence") != expected_sequence
    ):
        raise RuntimeError("control projection heads do not match the correction prefix")
    if prefix == 0:
        expected_event_id = EXPECTED_INITIAL_EVENT_ID
    else:
        step = correction_steps()[prefix - 1]
        with LocalIndex.open_read_only(writer.index_path) as index:
            operation = index.get("operation", step.operation_id)
        if operation is None or operation.authority_event_id is None:
            raise RuntimeError("correction operation authority is absent")
        expected_event_id = operation.authority_event_id
    if journal_head.get("event_id") != expected_event_id:
        raise RuntimeError("control Journal head differs from the correction prefix")
    science = control.get("scientific")
    if not isinstance(science, Mapping):
        raise RuntimeError("scientific control projection is absent")
    if (
        science.get("active_mission") != EXPECTED_MISSION_ID
        or science.get("holdout_reveals") != 0
        or science.get("claim") != "none"
        or science.get("required_future_holdout_id") is not None
        or any(
            science.get(name) is not None
            for name in (
                "active_batch",
                "active_executable",
                "active_holdout_evaluation",
                "active_job",
                "active_lineage",
                "active_release",
                "active_repair",
                "active_study",
            )
        )
    ):
        raise RuntimeError("scientific state changed during audit correction")
    if prefix == 0:
        expected_action = EXPECTED_PENDING_ACTION
        expected_initiative: str | None = EXPECTED_INITIATIVE_ID
    elif prefix < len(correction_steps()):
        expected_action = EXPECTED_STABLE_ACTION
        expected_initiative = EXPECTED_INITIATIVE_ID
    else:
        expected_action = EXPECTED_FINAL_ACTION
        expected_initiative = None
    if (
        science.get("active_initiative") != expected_initiative
        or control.get("next_action") != expected_action
    ):
        raise RuntimeError("control direction does not match the correction prefix")
    return control


def _require_report_binding(
    writer: StateWriter,
    *,
    prefix: int,
    plan: CorrectionPlan,
) -> None:
    if prefix == 0:
        return
    writer.evidence.verify(plan.report_hash)
    manifest_bytes = writer.evidence.read_verified(
        plan.withdrawal_manifest_hash
    )
    if manifest_bytes != plan.withdrawal_manifest_bytes:
        raise RuntimeError("withdrawal manifest evidence differs")
    with LocalIndex.open_read_only(writer.index_path) as index:
        operation = index.get("operation", WITHDRAW_OPERATION_ID)
    event = _operation_event(writer, operation)
    payload = event.get("payload")
    if (
        not isinstance(payload, Mapping)
        or payload.get("manifest")
        != plan.withdrawal_manifest.to_identity_payload()
        or payload.get("manifest_artifact_hash")
        != plan.withdrawal_manifest_hash
    ):
        raise RuntimeError("withdrawal does not freeze the exact audit report")


def _require_authority_progress(
    writer: StateWriter,
    *,
    prefix: int,
    plan: CorrectionPlan,
    control: Mapping[str, Any],
) -> None:
    authority = control.get("authority")
    if not isinstance(authority, Mapping):
        raise RuntimeError("authority projection is absent")
    if prefix < 2:
        if authority.get("manifest_digest") != EXPECTED_INITIAL_AUTHORITY_MANIFEST:
            raise RuntimeError("pre-migration authority manifest differs")
        return
    with LocalIndex.open_read_only(writer.index_path) as index:
        operation = index.get("operation", AUTHORITY_OPERATION_ID)
    event = _operation_event(writer, operation)
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        raise RuntimeError("authority migration event payload is absent")
    rows = payload.get("replacements")
    expected_hashes = {
        relative: sha256(content).hexdigest()
        for relative, content in plan.authority_replacements.items()
    }
    observed_hashes = (
        {}
        if not isinstance(rows, list)
        else {
            row.get("path"): row.get("new_sha256")
            for row in rows
            if isinstance(row, Mapping)
        }
    )
    if (
        payload.get("reason") != AUTHORITY_REASON
        or payload.get("boundary") != "active_stable"
        or observed_hashes != expected_hashes
        or authority.get("manifest_digest") != payload.get("new_manifest_digest")
    ):
        raise RuntimeError("activated audit authority differs from its fixed plan")
    for relative, expected_hash in expected_hashes.items():
        if sha256((writer.foundation_root / relative).read_bytes()).hexdigest() != (
            expected_hash
        ):
            raise RuntimeError("activated authority file bytes differ from evidence")


def _require_protocol_progress(
    writer: StateWriter,
    *,
    prefix: int,
    report_hash: str,
    authority_manifest_digest: str,
) -> None:
    with LocalIndex.open_read_only(writer.index_path) as index:
        count = index.count_by_kind("research-protocol-activation")
        head = index.event_head("research-protocol:scientific")
        record = None if head is None else index.get(head.record_kind, head.record_id)
    if prefix < 3:
        if count != 0 or head is not None:
            raise RuntimeError("v2 protocol was activated outside the correction prefix")
        return
    if (
        count != 1
        or head is None
        or record is None
        or record.kind != "research-protocol-activation"
        or record.status != "active"
        or record.event_sequence != 1
        or record.payload.get("audit_artifact_hash") != report_hash
        or record.payload.get("authority_manifest_digest")
        != authority_manifest_digest
        or record.payload.get("validator_id")
        != ScientificAdjudicationValidatorV2.validator_id
    ):
        raise RuntimeError("v2 protocol activation projection differs")


def _require_source_progress(
    writer: StateWriter,
    *,
    prefix: int,
    plan: CorrectionPlan,
) -> None:
    applied = max(0, min(len(plan.source_corrections), prefix - 3))
    with LocalIndex.open_read_only(writer.index_path) as index:
        if index.count_by_kind("source-authority-invalidation") != applied:
            raise RuntimeError("source invalidation count differs from the prefix")
        for position, correction in enumerate(plan.source_corrections):
            source_id = correction.spec.source_contract_id
            eligible_record = index.get(
                "source-state",
                correction.spec.source_state_record_id,
            )
            source_head = index.event_head(f"source:{source_id}")
            source_record = (
                None
                if source_head is None
                else index.get(source_head.record_kind, source_head.record_id)
            )
            correction_head = index.event_head(f"source-authority:{source_id}")
            correction_record = (
                None
                if correction_head is None
                else index.get(
                    correction_head.record_kind,
                    correction_head.record_id,
                )
            )
            if position >= applied:
                if (
                    source_head is None
                    or source_record is None
                    or source_record.record_id
                    != correction.spec.source_state_record_id
                    or source_record.status == "suspended"
                    or correction_head is not None
                ):
                    raise RuntimeError("unapplied source head differs from the audit")
                continue
            if (
                source_head is None
                or source_record is None
                or source_record.status != "suspended"
                or correction_head is None
                or correction_record is None
                or correction_head.sequence != 1
                or correction_record.record_id != correction.invalidation.identity
                or correction_record.payload.get("audit_manifest")
                != correction.manifest.to_identity_payload()
                or correction_record.payload.get("invalidation")
                != correction.invalidation.to_identity_payload()
                or correction_record.payload.get("scientific_trial_delta") != 0
                or correction_record.payload.get("replacement_state_record_id")
                != source_record.record_id
                or correction_record.payload.get("eligible_source_state_record_id")
                != correction.spec.source_state_record_id
                or correction_record.payload.get(
                    "prior_active_source_state_record_id"
                )
                != correction.spec.source_state_record_id
                or source_record.payload.get("eligible_source_state_record_id")
                != correction.spec.source_state_record_id
                or source_record.payload.get("prior_active_source_state_record_id")
                != correction.spec.source_state_record_id
                or eligible_record is None
                or eligible_record.event_sequence is None
                or source_head.sequence != eligible_record.event_sequence + 1
            ):
                raise RuntimeError("applied source invalidation projection differs")


def _require_historical_progress(
    writer: StateWriter,
    *,
    prefix: int,
    plan: CorrectionPlan,
) -> None:
    applied_chunks = max(0, min(len(plan.historical_chunks), prefix - 8))
    applied_requests = tuple(
        request
        for chunk in plan.historical_chunks[:applied_chunks]
        for request in chunk
    )
    applied_ids = {request.completion_record_id for request in applied_requests}
    expected_override_count = sum(
        len(request.validity_overrides) for request in applied_requests
    )
    observed_override_count = 0
    with LocalIndex.open_read_only(writer.index_path) as index:
        if index.count_by_kind("historical-scientific-adjudication") != len(
            applied_requests
        ):
            raise RuntimeError("historical overlay count differs from the prefix")
        for request in plan.historical_requests:
            head = index.event_head(
                f"historical-adjudication:{request.completion_record_id}"
            )
            record = None if head is None else index.get(head.record_kind, head.record_id)
            if request.completion_record_id not in applied_ids:
                if head is not None:
                    raise RuntimeError("historical overlay exists beyond the prefix")
                continue
            expected_overrides = [
                item.manifest() for item in request.validity_overrides
            ]
            if (
                head is None
                or record is None
                or head.sequence != 1
                or record.kind != "historical-scientific-adjudication"
                or record.payload.get("completion_record_id")
                != request.completion_record_id
                or record.payload.get("audit_artifact_hash") != plan.report_hash
                or record.payload.get("validity_overrides") != expected_overrides
                or record.payload.get("trial_delta") != 0
                or record.payload.get("holdout_delta") != 0
                or record.payload.get("candidate_delta") != 0
                or record.payload.get("claim_authority")
                != "additive_qualification_only"
            ):
                raise RuntimeError("historical overlay projection differs")
            observed_override_count += len(expected_overrides)
        for chunk_index, chunk in enumerate(plan.historical_chunks[:applied_chunks]):
            step = plan.steps[8 + chunk_index]
            operation = index.get("operation", step.operation_id)
            event = _operation_event(writer, operation)
            payload = event.get("payload")
            if (
                not isinstance(payload, Mapping)
                or payload.get("audit_artifact_hash") != plan.report_hash
                or payload.get("requests") != _historical_request_manifest(chunk)
            ):
                raise RuntimeError("historical chunk operation payload differs")
    if observed_override_count != expected_override_count:
        raise RuntimeError("historical validity override count differs")
    if applied_chunks == len(plan.historical_chunks) and (
        len(applied_requests) != EXPECTED_LEGACY_SCIENTIFIC_COMPLETIONS
        or observed_override_count != EXPECTED_VALIDITY_OVERRIDE_COUNT
    ):
        raise RuntimeError("completed historical correction inventory differs")


def _require_close_progress(
    writer: StateWriter,
    *,
    prefix: int,
    step_count: int,
) -> None:
    if prefix < step_count:
        return
    with LocalIndex.open_read_only(writer.index_path) as index:
        operation = index.get("operation", CLOSE_INITIATIVE_OPERATION_ID)
        closes = tuple(
            record
            for record in index.records_by_subject_status(
                f"Initiative:{EXPECTED_INITIATIVE_ID}",
                "superseded",
            )
            if record.kind == "initiative-close"
            and record.payload.get("outcome") == "superseded"
        )
    event = _operation_event(writer, operation)
    payload = event.get("payload")
    if (
        len(closes) != 1
        or not isinstance(payload, Mapping)
        or payload.get("outcome") != "superseded"
        or operation.payload.get("result", {}).get("initiative_id")
        != EXPECTED_INITIATIVE_ID
        or operation.payload.get("result", {}).get("outcome") != "superseded"
    ):
        raise RuntimeError("INI-0016 superseded close projection differs")


def validate_correction_progress(
    writer: StateWriter,
    *,
    plan: CorrectionPlan,
    prefix: int | None = None,
) -> int:
    observed_prefix = (
        inspect_correction_prefix(writer, steps=plan.steps)
        if prefix is None
        else prefix
    )
    if observed_prefix < 0 or observed_prefix > len(plan.steps):
        raise RuntimeError("correction prefix length is invalid")
    require_frozen_report_unchanged(
        root=writer.root,
        expected_hash=plan.report_hash,
    )
    _require_report_binding(
        writer,
        prefix=observed_prefix,
        plan=plan,
    )
    control = _require_control_progress(writer, prefix=observed_prefix)
    with LocalIndex.open_read_only(writer.index_path) as index:
        _require_invariant_counts(index)
        expected_withdrawals = 0 if observed_prefix == 0 else 1
        if index.count_by_kind("portfolio-decision-withdrawal") != expected_withdrawals:
            raise RuntimeError("Portfolio Decision withdrawal count differs")
    _require_authority_progress(
        writer,
        prefix=observed_prefix,
        plan=plan,
        control=control,
    )
    authority = control["authority"]
    _require_protocol_progress(
        writer,
        prefix=observed_prefix,
        report_hash=plan.report_hash,
        authority_manifest_digest=authority["manifest_digest"],
    )
    _require_source_progress(writer, prefix=observed_prefix, plan=plan)
    _require_historical_progress(writer, prefix=observed_prefix, plan=plan)
    _require_close_progress(
        writer,
        prefix=observed_prefix,
        step_count=len(plan.steps),
    )
    return observed_prefix


def validate_completed_correction_ancestor(
    writer: StateWriter,
    *,
    root: Path = ROOT,
) -> dict[str, object]:
    """Validate the immutable V1 chain without rejecting a legal later suffix."""

    steps = correction_steps()
    prefix = inspect_correction_prefix(writer, steps=steps)
    if prefix != len(steps):
        raise RuntimeError("Project Goal audit correction chain is incomplete")
    report_bytes, report_hash = read_frozen_audit_report(root)
    writer.evidence.verify(report_hash)

    operations: list[Any] = []
    with LocalIndex.open_read_only(writer.index_path) as index:
        for step in steps:
            operation = index.get("operation", step.operation_id)
            if operation is None:
                raise RuntimeError("completed correction operation is absent")
            operations.append(operation)
    events = tuple(_operation_event(writer, operation) for operation in operations)

    withdrawal = events[0].get("payload")
    withdrawal_manifest = (
        None if not isinstance(withdrawal, Mapping) else withdrawal.get("manifest")
    )
    withdrawal_hash = (
        None
        if not isinstance(withdrawal, Mapping)
        else withdrawal.get("manifest_artifact_hash")
    )
    if (
        not isinstance(withdrawal_manifest, Mapping)
        or withdrawal_manifest.get("report_artifact_hash") != report_hash
        or type(withdrawal_hash) is not str
        or writer.evidence.read_verified(withdrawal_hash)
        != canonical_bytes(withdrawal_manifest)
    ):
        raise RuntimeError("completed correction report binding differs")

    authority = events[1].get("payload")
    if (
        not isinstance(authority, Mapping)
        or authority.get("schema") != "authority_manifest_migration.v1"
        or authority.get("boundary") != "active_stable"
        or authority.get("trial_delta") != 0
        or authority.get("holdout_delta") != 0
        or authority.get("scientific_claim") != "none"
        or not isinstance(authority.get("new_manifest_digest"), str)
        or not isinstance(authority.get("replacements"), list)
    ):
        raise RuntimeError("completed correction authority boundary differs")
    replacement_paths: set[str] = set()
    for row in authority["replacements"]:
        if not isinstance(row, Mapping):
            raise RuntimeError("completed authority replacement is malformed")
        relative = row.get("path")
        digest = row.get("artifact_sha256")
        if type(relative) is not str or type(digest) is not str:
            raise RuntimeError("completed authority replacement is incomplete")
        content = writer.evidence.read_verified(digest)
        if sha256(content).hexdigest() != row.get("new_sha256"):
            raise RuntimeError("completed authority replacement evidence differs")
        replacement_paths.add(relative)
    if replacement_paths != {
        "OPERATING_DIRECTION.md",
        "contracts/evidence.yaml",
        "contracts/operations.yaml",
        "contracts/runtime.yaml",
        "contracts/science.yaml",
    }:
        raise RuntimeError("completed authority replacement path set differs")

    protocol = events[2].get("payload")
    if (
        not isinstance(protocol, Mapping)
        or protocol.get("schema") != "research_protocol_activation.v1"
        or protocol.get("protocol") != "scientific_adjudication_v2"
        or protocol.get("validator_id") != HISTORICAL_V1_VALIDATOR_ID
        or protocol.get("audit_artifact_hash") != report_hash
        or protocol.get("authority_manifest_digest")
        != authority.get("new_manifest_digest")
    ):
        raise RuntimeError("completed correction protocol activation differs")

    expected_sources = build_source_corrections(report_hash)
    for event, correction in zip(events[3:8], expected_sources, strict=True):
        payload = event.get("payload")
        if (
            not isinstance(payload, Mapping)
            or {key: value for key, value in payload.items() if key != "evidence"}
            != correction.invalidation.to_identity_payload()
        ):
            raise RuntimeError("completed source invalidation differs")

    historical_events = events[8:-1]
    completion_ids: set[str] = set()
    replay_ids: dict[str, set[str]] = {"p0": set(), "p1": set()}
    validity_override_count = 0
    request_count = 0
    for operation, event in zip(
        operations[8:-1], historical_events, strict=True
    ):
        payload = event.get("payload")
        requests = None if not isinstance(payload, Mapping) else payload.get("requests")
        result = operation.payload.get("result")
        if (
            not isinstance(payload, Mapping)
            or payload.get("audit_artifact_hash") != report_hash
            or not isinstance(requests, list)
            or not isinstance(result, Mapping)
            or result.get("trial_delta") != 0
            or result.get("holdout_delta") != 0
            or result.get("candidate_delta") != 0
        ):
            raise RuntimeError("completed historical correction chunk differs")
        for request in requests:
            if not isinstance(request, Mapping):
                raise RuntimeError("completed historical request is malformed")
            completion_id = request.get("completion_record_id")
            priority = request.get("replay_priority")
            overrides = request.get("validity_overrides")
            if (
                type(completion_id) is not str
                or completion_id in completion_ids
                or priority not in {"none", "p0", "p1"}
                or not isinstance(overrides, list)
            ):
                raise RuntimeError("completed historical request identity differs")
            completion_ids.add(completion_id)
            request_count += 1
            validity_override_count += len(overrides)
            if priority in replay_ids:
                replay_ids[priority].add(completion_id)
    if (
        request_count != EXPECTED_LEGACY_SCIENTIFIC_COMPLETIONS
        or validity_override_count != EXPECTED_VALIDITY_OVERRIDE_COUNT
        or replay_ids["p0"] != P0_REPLAY_COMPLETIONS
        or replay_ids["p1"] != P1_REPLAY_COMPLETIONS
    ):
        raise RuntimeError("completed historical correction inventory differs")

    close_event = events[-1]
    current = writer.read_control()
    boundary_revision = EXPECTED_INITIAL_REVISION + len(steps)
    suffix_event_count = validate_completed_correction_suffix_boundary(
        current=current,
        close_event=close_event,
        boundary_revision=boundary_revision,
    )
    return {
        "boundary_event_id": close_event["event_id"],
        "boundary_revision": boundary_revision,
        "current_revision": current["revision"],
        "historical_adjudication_count": request_count,
        "mode": "completed_immutable_ancestor",
        "operation_count": len(steps),
        "report_sha256": sha256(report_bytes).hexdigest(),
        "source_invalidation_count": len(expected_sources),
        "suffix_event_count": suffix_event_count,
        "validity_override_count": validity_override_count,
    }


def validate_completed_correction_suffix_boundary(
    *,
    current: object,
    close_event: Mapping[str, Any],
    boundary_revision: int,
) -> int:
    """Require one exact correction boundary and permit any later stable head."""

    close_control = close_event.get("control")
    close_payload = close_event.get("payload")
    close_science = (
        None if not isinstance(close_control, Mapping) else close_control.get("scientific")
    )
    if (
        close_event.get("sequence") != boundary_revision
        or not isinstance(close_payload, Mapping)
        or close_payload.get("outcome") != "superseded"
        or not isinstance(close_control, Mapping)
        or close_control.get("next_action") != EXPECTED_FINAL_ACTION
        or not isinstance(close_science, Mapping)
        or close_science.get("active_mission") != EXPECTED_MISSION_ID
        or close_science.get("active_initiative") is not None
        or close_science.get("holdout_reveals") != 0
        or close_science.get("claim") != "none"
    ):
        raise RuntimeError("completed correction terminal boundary differs")

    current_head = (
        None
        if not isinstance(current, Mapping)
        else current.get("heads", {}).get("journal", {})
    )
    if (
        not isinstance(current, Mapping)
        or not isinstance(current_head, Mapping)
        or type(current.get("revision")) is not int
        or current["revision"] < boundary_revision
        or current_head.get("sequence") != current["revision"]
    ):
        raise RuntimeError("current control is not a legal correction suffix")
    return current["revision"] - boundary_revision


def _finalize_exact_evidence(
    writer: StateWriter,
    content: bytes,
    *,
    expected_hash: str,
) -> None:
    artifact = writer.evidence.finalize(content)
    if artifact.sha256 != expected_hash:
        raise RuntimeError("finalized correction evidence hash differs")
    writer.evidence.verify(expected_hash)


def _apply_step(
    writer: StateWriter,
    *,
    plan: CorrectionPlan,
    step_index: int,
) -> None:
    if step_index == 0:
        _finalize_exact_evidence(
            writer,
            plan.withdrawal_manifest_bytes,
            expected_hash=plan.withdrawal_manifest_hash,
        )
        writer.withdraw_pending_portfolio_decision(
            manifest_artifact_hash=plan.withdrawal_manifest_hash,
            operation_id=WITHDRAW_OPERATION_ID,
        )
        return
    if step_index == 1:
        writer.migrate_authority(
            replacements=plan.authority_replacements,
            reason=AUTHORITY_REASON,
            operation_id=AUTHORITY_OPERATION_ID,
            allow_active_stable_boundary=True,
        )
        return
    if step_index == 2:
        control = writer.read_control()
        if control is None:
            raise RuntimeError("control is absent before protocol activation")
        writer.activate_research_protocol(
            activation=ResearchProtocolActivation(
                protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
                validator_id=ScientificAdjudicationValidatorV2.validator_id,
                authority_manifest_digest=control["authority"]["manifest_digest"],
                audit_artifact_hash=plan.report_hash,
            ),
            operation_id=PROTOCOL_OPERATION_ID,
        )
        return
    if 3 <= step_index < 8:
        correction = plan.source_corrections[step_index - 3]
        manifest_hash = sha256(correction.manifest_bytes).hexdigest()
        _finalize_exact_evidence(
            writer,
            correction.manifest_bytes,
            expected_hash=manifest_hash,
        )
        writer.suspend_source_authority_from_audit(
            invalidation=correction.invalidation,
            operation_id=plan.steps[step_index].operation_id,
        )
        return
    historical_stop = 8 + len(plan.historical_chunks)
    if 8 <= step_index < historical_stop:
        chunk = plan.historical_chunks[step_index - 8]
        writer.record_historical_scientific_adjudications(
            requests=chunk,
            audit_artifact_hash=plan.report_hash,
            operation_id=plan.steps[step_index].operation_id,
        )
        return
    if step_index == historical_stop:
        validate_correction_progress(
            writer,
            plan=plan,
            prefix=historical_stop,
        )
        writer.close_initiative(
            outcome="superseded",
            operation_id=CLOSE_INITIATIVE_OPERATION_ID,
        )
        return
    raise RuntimeError("unknown Project Goal audit correction step")


def apply_corrections(
    *,
    root: Path = ROOT,
    writer_factory: Callable[..., StateWriter] = StateWriter,
) -> dict[str, object]:
    """Recover first, then execute only the missing strict correction suffix."""

    registry = EvidenceValidatorRegistry((ScientificAdjudicationValidatorV2(),))
    writer = writer_factory(root, validation_registry=registry)
    try:
        stable = writer.require_stable_head()
        recovery: Mapping[str, object] = {
            "control_revision": stable["control_revision"],
            "index_record_count": stable["index_record_count"],
            "journal_event_id": stable["journal_event_id"],
            "mode": "stable_head_no_recovery",
            "projection_digest": stable["projection_digest"],
        }
    except RecoveryRequired:
        recovery = {"mode": "explicit_recovery", **writer.recover()}
    completed_prefix = inspect_correction_prefix(writer)
    if completed_prefix == len(correction_steps()):
        completed = validate_completed_correction_ancestor(writer, root=root)
        return {
            **completed,
            "applied_step_count": 0,
            "final_revision": completed["boundary_revision"],
            "initial_prefix": completed_prefix,
            "recovery": recovery,
            "schema": "project_goal_audit_v1_correction_result.v1",
        }
    plan = build_correction_plan(writer, root=root)
    prefix = inspect_correction_prefix(writer, steps=plan.steps)
    if prefix == 0:
        _finalize_exact_evidence(
            writer,
            plan.report_bytes,
            expected_hash=plan.report_hash,
        )
    prefix = validate_correction_progress(writer, plan=plan, prefix=prefix)
    initial_prefix = prefix
    for step_index in range(prefix, len(plan.steps)):
        require_frozen_report_unchanged(
            root=root,
            expected_hash=plan.report_hash,
        )
        observed = inspect_correction_prefix(writer, steps=plan.steps)
        if observed != step_index:
            raise RuntimeError("correction prefix changed concurrently")
        _apply_step(writer, plan=plan, step_index=step_index)
        advanced = inspect_correction_prefix(writer, steps=plan.steps)
        if advanced != step_index + 1:
            raise RuntimeError("correction step did not advance exactly once")
        historical_stop = 8 + len(plan.historical_chunks)
        if advanced in {1, 2, 3, 8, historical_stop, len(plan.steps)}:
            validate_correction_progress(writer, plan=plan, prefix=advanced)
    final_prefix = validate_correction_progress(writer, plan=plan)
    if final_prefix != len(plan.steps):
        raise RuntimeError("Project Goal audit correction did not complete")
    return {
        "applied_step_count": final_prefix - initial_prefix,
        "final_revision": EXPECTED_INITIAL_REVISION + final_prefix,
        "historical_adjudication_count": len(plan.historical_requests),
        "historical_chunk_count": len(plan.historical_chunks),
        "initial_prefix": initial_prefix,
        "recovery": recovery,
        "report_sha256": plan.report_hash,
        "schema": "project_goal_audit_v1_correction_result.v1",
        "source_invalidation_count": len(plan.source_corrections),
        "validity_override_count": sum(
            len(item.validity_overrides) for item in plan.historical_requests
        ),
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or crash-resumably apply the complete Project Goal audit V1 "
            "correction chain."
        )
    )
    parser.add_argument(
        "--apply-corrections",
        action="store_true",
        help=(
            "recover first and apply the exact withdrawal, authority, protocol, "
            "source, historical, and Initiative-close suffix"
        ),
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    if arguments.apply_corrections:
        summary = apply_corrections(root=ROOT)
        print(json.dumps(summary, sort_keys=True))
        return
    writer = StateWriter(
        ROOT,
        validation_registry=EvidenceValidatorRegistry(
            (ScientificAdjudicationValidatorV2(),)
        ),
    )
    completed_prefix = inspect_correction_prefix(writer)
    if completed_prefix == len(correction_steps()):
        print(
            json.dumps(
                validate_completed_correction_ancestor(writer, root=ROOT),
                sort_keys=True,
            )
        )
        return
    plan = build_correction_plan(writer, root=ROOT)
    prefix = validate_correction_progress(writer, plan=plan)
    summary = {
        **replacement_summary(plan.authority_replacements),
        "apply_flag": "--apply-corrections",
        "current_prefix": prefix,
        "historical_adjudication_count": len(plan.historical_requests),
        "historical_chunk_count": len(plan.historical_chunks),
        "mode": "read_only_plan",
        "operation_count": len(plan.steps),
        "report_sha256": plan.report_hash,
        "source_invalidation_count": len(plan.source_corrections),
        "validity_override_count": sum(
            len(item.validity_overrides) for item in plan.historical_requests
        ),
    }
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
