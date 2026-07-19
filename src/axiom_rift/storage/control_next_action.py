"""Closed validation for the sole projected control next action.

The journal contains old, still-authoritative action shapes as well as newer
typed Writer branches.  This module accepts that explicit union and nothing
else.  It is deliberately pure: it neither reads durable state nor derives a
replacement action.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable


class ControlNextActionError(ValueError):
    """One projected next action is malformed or misbound."""


_REPLAY_SCHEDULER_KEYS = frozenset(
    {"pending_replay_obligation_ids", "required_replay_priority"}
)
_RESEARCH_LAYERS = frozenset(
    {
        "calibration",
        "data_source",
        "execution",
        "feature",
        "label",
        "lifecycle",
        "model",
        "objective",
        "portfolio",
        "regime",
        "risk",
        "selector",
        "synthesis",
        "trade",
    }
)
_PORTFOLIO_SNAPSHOT_ACTIONS = frozenset(
    {"new_mechanism", "preserve", "prune", "revise_protocol"}
)
_PORTFOLIO_EXECUTION_ACTIONS = frozenset(
    {
        "complementary_sleeve",
        "contrast",
        "deepen",
        "recombine",
        "rotate",
        "synthesize",
    }
)
_ENGINEERING_DISPOSITIONS = frozenset(
    {
        "repair_exhausted_changed_causes",
        "repair_infeasible",
        "repair_nonpositive_expected_value",
        "requires_scientific_change",
    }
)
_ENGINEERING_FIXTURE_CONTEXT = "__axiom_engineering_fixture__"


SUPPORTED_NEXT_ACTION_KINDS = frozenset(
    {
        "await_external_change",
        "await_new_future_holdout_data",
        "await_root_goal",
        "build_portfolio",
        "choose_next_initiative_or_terminal",
        "close_mission",
        "complete_engineering_failure",
        "complete_runtime_source_ineligibility",
        "declare_external_dependency_job",
        "declare_job",
        "diagnose_study",
        "dispose_batch",
        "dispose_revealed_holdout_engineering_gap",
        "evaluate_frozen_holdout",
        "execute_portfolio_decision",
        "execute_repair",
        "freeze_batch",
        "issue_job_permit",
        "issue_release_permit",
        "judge_external_dependency_evidence",
        "judge_job_evidence",
        "judge_study",
        "open_initiative",
        "plan_candidate_bound_evidence",
        "portfolio_decision",
        "project_goal_complete",
        "record_axis_reopen_authority",
        "record_external_blocker",
        "record_holdout_evaluation",
        "record_portfolio_snapshot",
        "record_research_intake",
        "record_source_eligibility",
        "register_future_development_material",
        "resolve_candidate_engineering_gap",
        "resolve_historical_replay_obligations",
        "resume_job",
        "review_architecture",
        "review_study_continuation",
    }
)


def _fail(message: str) -> None:
    raise ControlNextActionError(message)


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        _fail(f"{name} must be non-empty ASCII")
    return value


def _digest(name: str, value: object) -> str:
    text = _ascii(name, value)
    if len(text) != 64 or any(
        character not in "0123456789abcdef" for character in text
    ):
        _fail(f"{name} must be a lowercase SHA-256 digest")
    return text


def _prefixed(name: str, value: object, prefix: str) -> str:
    text = _ascii(name, value)
    if not text.startswith(prefix):
        _fail(f"{name} must use the {prefix} identity prefix")
    _digest(name, text.removeprefix(prefix))
    return text


def _validate_diagnosis_authority_context(
    action: Mapping[str, Any],
) -> None:
    diagnosis_id = action.get("study_diagnosis_id")
    correction_id = action.get("study_diagnosis_correction_id")
    audit_id = action.get("diagnosis_correction_audit_id")
    if correction_id is not None:
        _prefixed(
            "Study diagnosis correction identity",
            correction_id,
            "diagnosis-correction:",
        )
    if audit_id is not None:
        _prefixed(
            "Study diagnosis correction audit identity",
            audit_id,
            "diagnosis-correction-audit:",
        )
    if diagnosis_id is None and (correction_id is not None or audit_id is not None):
        _fail("diagnosis overlay authority lacks its original diagnosis")
    if (correction_id is None) != (audit_id is None):
        _fail(
            "diagnosis correction and complete-inventory audit must travel together"
        )


def _exact(
    name: str,
    value: Mapping[str, Any],
    required: set[str] | frozenset[str],
    optional: set[str] | frozenset[str] = frozenset(),
) -> None:
    observed = set(value)
    missing = set(required).difference(observed)
    extra = observed.difference(set(required) | set(optional))
    if missing or extra:
        _fail(f"{name} schema is not exact")


def _canonical_list(
    name: str,
    value: object,
    *,
    prefix: str | None = None,
    digest_values: bool = False,
    allowed: frozenset[str] | None = None,
    allow_empty: bool = False,
    ordered: bool = False,
) -> list[str]:
    if type(value) is not list or (not value and not allow_empty):
        _fail(f"{name} must be a canonical identity list")
    normalized: list[str] = []
    for item in value:
        text = _ascii(name, item)
        if prefix is not None:
            _prefixed(name, text, prefix)
        elif digest_values:
            _digest(name, text)
        if allowed is not None and text not in allowed:
            _fail(f"{name} contains an unsupported value")
        normalized.append(text)
    if len(normalized) != len(set(normalized)):
        _fail(f"{name} must not contain duplicates")
    if not ordered and normalized != sorted(normalized):
        _fail(f"{name} must be sorted")
    return normalized


def _ascii_tree(name: str, value: object) -> None:
    if value is None:
        return
    if type(value) is int:
        return
    if type(value) is str:
        _ascii(name, value)
        return
    if type(value) is list:
        for ordinal, child in enumerate(value):
            _ascii_tree(f"{name}[{ordinal}]", child)
        return
    if type(value) is dict:
        for key, child in value.items():
            _ascii(f"{name} key", key)
            _ascii_tree(f"{name}.{key}", child)
        return
    _fail(f"{name} contains a non-canonical action value")


def _active_match(
    scientific: Mapping[str, Any],
    active_key: str,
    value: str,
    label: str,
) -> None:
    active = scientific.get(active_key)
    if type(active) is not str or active != value:
        _fail(f"{label} does not match the active scientific projection")


def _scheduler(action: Mapping[str, Any]) -> None:
    present = set(action).intersection(_REPLAY_SCHEDULER_KEYS)
    if present not in (set(), set(_REPLAY_SCHEDULER_KEYS)):
        _fail("replay scheduler bindings must be present together")
    if not present:
        return
    _canonical_list(
        "pending replay obligation",
        action["pending_replay_obligation_ids"],
        prefix="historical-replay-obligation:",
    )
    if action["required_replay_priority"] not in {"p0", "p1"}:
        _fail("required replay priority is invalid")


def _mission_action(
    action: Mapping[str, Any],
    scientific: Mapping[str, Any],
    *,
    name: str,
    required: set[str],
    optional: set[str] | frozenset[str] = frozenset(),
) -> str:
    _exact(name, action, required, optional)
    mission_id = _ascii("Mission identity", action.get("mission_id"))
    _active_match(scientific, "active_mission", mission_id, name)
    return mission_id


def _validate_await_root_goal(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del scientific, depth
    successor = {
        "kind",
        "predecessor_basis_record_id",
        "predecessor_mission_close_record_id",
        "predecessor_mission_id",
        "predecessor_outcome",
    }
    if set(action) == {"kind"}:
        return
    _exact("root-goal successor boundary", action, successor)
    _digest("successor basis record", action["predecessor_basis_record_id"])
    _digest(
        "successor Mission close record",
        action["predecessor_mission_close_record_id"],
    )
    _ascii("successor predecessor Mission", action["predecessor_mission_id"])
    if action["predecessor_outcome"] != "closed_no_candidate":
        _fail("successor boundary requires a negative Mission terminal")


def _validate_record_research_intake(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    _mission_action(
        action,
        scientific,
        name="research intake action",
        required={"kind", "mission_id"},
    )


def _validate_open_initiative(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    _mission_action(
        action,
        scientific,
        name="Initiative admission action",
        required={"kind", "mission_id"},
        optional={
            "post_holdout_development_id",
            "research_intake_id",
            *_REPLAY_SCHEDULER_KEYS,
        },
    )
    if "research_intake_id" in action:
        _prefixed(
            "research intake identity",
            action["research_intake_id"],
            "research-intake:",
        )
    if "post_holdout_development_id" in action:
        _digest(
            "post-holdout development authority",
            action["post_holdout_development_id"],
        )
    _scheduler(action)


def _validate_build_portfolio(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    _exact(
        "Portfolio build action",
        action,
        {"initiative_id", "kind"},
        {"research_intake_id"},
    )
    initiative_id = _ascii("Initiative identity", action["initiative_id"])
    _active_match(
        scientific, "active_initiative", initiative_id, "Portfolio build action"
    )
    if "research_intake_id" in action:
        _prefixed(
            "research intake identity",
            action["research_intake_id"],
            "research-intake:",
        )


def _validate_choose_next(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    _mission_action(
        action,
        scientific,
        name="Mission direction action",
        required={"kind", "mission_id"},
        optional=_REPLAY_SCHEDULER_KEYS,
    )
    _scheduler(action)


def _validate_portfolio_decision(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    from axiom_rift.operations.architecture_review_direction import (
        ARCHITECTURE_CONTINUATION_ACTION_FIELDS,
        ArchitectureReviewDirectionError,
        constraint_from_action,
    )

    required = {"kind", "portfolio_snapshot_id"}
    optional = {
        "architecture_review_id",
        "constraint_source_id",
        "diagnosis_correction_audit_id",
        "excluded_architecture_family",
        "excluded_research_layers",
        "pending_replay_obligation_ids",
        "post_holdout_development_id",
        "required_replay_priority",
        "required_target_axis_ids",
        "study_diagnosis_id",
        "study_diagnosis_correction_id",
    } | set(ARCHITECTURE_CONTINUATION_ACTION_FIELDS)
    _exact("Portfolio decision action", action, required, optional)
    try:
        continuation = constraint_from_action(action)
    except ArchitectureReviewDirectionError as exc:
        _fail(str(exc))
    portfolio_snapshot_id = action["portfolio_snapshot_id"]
    if not (
        portfolio_snapshot_id is None
        and scientific.get(_ENGINEERING_FIXTURE_CONTEXT) is True
    ):
        _prefixed(
            "Portfolio snapshot identity",
            portfolio_snapshot_id,
            "portfolio:",
        )
    if type(scientific.get("active_initiative")) is not str:
        _fail("Portfolio decision requires an active Initiative")
    if "study_diagnosis_id" in action:
        _prefixed(
            "Study diagnosis identity",
            action["study_diagnosis_id"],
            "diagnosis:",
        )
    if "post_holdout_development_id" in action:
        _digest(
            "post-holdout development authority",
            action["post_holdout_development_id"],
        )
    _validate_diagnosis_authority_context(action)
    review_fields = {
        "architecture_review_id",
        "excluded_architecture_family",
        "excluded_research_layers",
    }.intersection(action)
    if continuation is not None:
        if {
            "excluded_architecture_family",
            "excluded_research_layers",
        }.intersection(action):
            _fail("bounded architecture continuation cannot carry legacy exclusions")
    elif review_fields:
        if "architecture_review_id" not in action:
            _fail("architecture constraint lacks its review identity")
        review_id = _prefixed(
            "architecture review identity",
            action["architecture_review_id"],
            "architecture-review:",
        )
        if (
            "constraint_source_id" in action
            and action["constraint_source_id"] != review_id
        ):
            _fail("architecture constraint source differs from its review")
        exclusions = {
            "excluded_architecture_family",
            "excluded_research_layers",
        }.intersection(action)
        if len(exclusions) != 1:
            _fail("architecture review must project exactly one exclusion")
        if "excluded_architecture_family" in action:
            _prefixed(
                "excluded architecture family",
                action["excluded_architecture_family"],
                "architecture-family:",
            )
        else:
            _canonical_list(
                "excluded research layer",
                action["excluded_research_layers"],
                allowed=_RESEARCH_LAYERS,
            )
    target_fields = {"constraint_source_id", "required_target_axis_ids"}.intersection(
        action
    )
    if "required_target_axis_ids" in action:
        if "constraint_source_id" not in action:
            _fail("required Portfolio targets lack their constraint source")
        _canonical_list(
            "required target axis",
            action["required_target_axis_ids"],
        )
    if "constraint_source_id" in action:
        _ascii("Portfolio constraint source", action["constraint_source_id"])
        if not review_fields and "required_target_axis_ids" not in action:
            _fail("Portfolio constraint source has no constrained field")
    elif target_fields:
        _fail("Portfolio constraint fields are incomplete")
    _scheduler(action)


def _portfolio_mutation_base(
    name: str,
    action: Mapping[str, Any],
    *,
    optional: set[str] | frozenset[str],
) -> None:
    _exact(
        name,
        action,
        {
            "action",
            "decision_id",
            "kind",
            "portfolio_snapshot_id",
            "target_axis_identity",
            "target_id",
        },
        optional,
    )
    _prefixed("Portfolio decision identity", action["decision_id"], "decision:")
    _prefixed(
        "Portfolio snapshot identity",
        action["portfolio_snapshot_id"],
        "portfolio:",
    )
    _prefixed("Portfolio axis identity", action["target_axis_identity"], "axis:")
    _ascii("Portfolio target axis", action["target_id"])
    if "replay_obligation_ids" in action:
        _canonical_list(
            "replay obligation",
            action["replay_obligation_ids"],
            prefix="historical-replay-obligation:",
        )


def _validate_record_portfolio_snapshot(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    from axiom_rift.operations.architecture_review_direction import (
        ARCHITECTURE_CONTINUATION_ACTION_FIELDS,
        ArchitectureReviewDirectionError,
        constraint_from_action,
    )
    from axiom_rift.research.governance import ArchitectureContinuationMode

    optional = {
        "axis_reopen_authority_id",
        "constraint_source_id",
        "excluded_architecture_family",
        "excluded_research_layers",
        "pending_replay_obligation_ids",
        "post_holdout_development_id",
        "protocol_revision_id",
        "replay_obligation_ids",
        "required_followup_layers",
        "required_replay_priority",
    } | set(ARCHITECTURE_CONTINUATION_ACTION_FIELDS)
    _portfolio_mutation_base(
        "Portfolio snapshot action", action, optional=optional
    )
    try:
        continuation = constraint_from_action(action)
    except ArchitectureReviewDirectionError as exc:
        _fail(str(exc))
    if (
        continuation is not None
        and continuation.mode is not ArchitectureContinuationMode.NEW_MECHANISM
    ):
        _fail("Portfolio snapshot cannot carry an existing-axis continuation")
    if action["action"] not in _PORTFOLIO_SNAPSHOT_ACTIONS:
        _fail("Portfolio snapshot action is not a snapshot mutation")
    if "protocol_revision_id" in action:
        _prefixed(
            "axis protocol revision",
            action["protocol_revision_id"],
            "axis-protocol-revision:",
        )
        if action["action"] != "revise_protocol":
            _fail("axis protocol revision requires its exact action")
    elif action["action"] == "revise_protocol":
        _fail("protocol revision action lacks typed authority")
    if type(scientific.get("active_initiative")) is not str:
        _fail("Portfolio snapshot action requires an active Initiative")
    if "axis_reopen_authority_id" in action:
        _prefixed(
            "axis reopen authority",
            action["axis_reopen_authority_id"],
            "axis-reopen-authority:",
        )
        if action["action"] != "preserve":
            _fail("axis reopen authority may only preserve its axis")
    if "post_holdout_development_id" in action:
        _digest(
            "post-holdout development authority",
            action["post_holdout_development_id"],
        )
    constraint_children = {
        "excluded_architecture_family",
        "excluded_research_layers",
        "required_architecture_family",
        "required_followup_layers",
    }.intersection(action)
    if constraint_children or "constraint_source_id" in action:
        if action["action"] != "new_mechanism":
            _fail("Portfolio mutation constraints require a new mechanism")
        if not constraint_children or "constraint_source_id" not in action:
            _fail("Portfolio mutation constraint is incomplete")
        _ascii("Portfolio mutation constraint source", action["constraint_source_id"])
    if "excluded_architecture_family" in action:
        _prefixed(
            "excluded architecture family",
            action["excluded_architecture_family"],
            "architecture-family:",
        )
    for key in ("excluded_research_layers", "required_followup_layers"):
        if key in action:
            _canonical_list(
                key.replace("_", " "),
                action[key],
                allowed=_RESEARCH_LAYERS,
            )
    if "axis_reopen_authority_id" in action and constraint_children:
        _fail("axis reopen action cannot also create a constrained mechanism")
    _scheduler(action)


def _validate_record_axis_reopen_authority(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    optional = {
        "pending_replay_obligation_ids",
        "post_holdout_development_id",
        "replay_obligation_ids",
        "required_replay_priority",
    }
    _portfolio_mutation_base(
        "axis reopen authority action",
        action,
        optional={
            *optional,
            "evidence_scope_overlay_ids",
            "replay_resolution_record_ids",
        },
    )
    _exact(
        "axis reopen authority action",
        action,
        {
            "action",
            "decision_id",
            "evidence_scope_overlay_ids",
            "kind",
            "portfolio_snapshot_id",
            "replay_resolution_record_ids",
            "target_axis_identity",
            "target_id",
        },
        optional,
    )
    if action["action"] != "preserve":
        _fail("axis reopen authority may only preserve its axis")
    if "post_holdout_development_id" in action:
        _digest(
            "post-holdout development authority",
            action["post_holdout_development_id"],
        )
    if type(scientific.get("active_initiative")) is not str:
        _fail("axis reopen authority requires an active Initiative")
    _canonical_list(
        "historical evidence scope",
        action["evidence_scope_overlay_ids"],
        prefix="historical-evidence-scope:",
    )
    _canonical_list(
        "historical replay satisfaction",
        action["replay_resolution_record_ids"],
        prefix="historical-replay-satisfaction:",
    )
    _scheduler(action)


def _validate_execute_portfolio_decision(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    from axiom_rift.operations.architecture_review_direction import (
        ARCHITECTURE_CONTINUATION_ACTION_FIELDS,
        ArchitectureReviewDirectionError,
        constraint_from_action,
    )

    architecture = {
        "architecture_chassis_identity",
        "baseline_executable_id",
        "resolved_architecture_family",
    }
    _portfolio_mutation_base(
        "Portfolio execution action",
        action,
        optional={
            *architecture,
            *ARCHITECTURE_CONTINUATION_ACTION_FIELDS,
            "diagnosis_correction_audit_id",
            "engineering_reentry_id",
            "engineering_reentry_validation",
            "post_holdout_development_id",
            "prospective_reentry_equivalence",
            "study_diagnosis_id",
            "study_diagnosis_correction_id",
            "replacement_architecture_equivalence",
            "replay_obligation_ids",
        },
    )
    try:
        constraint_from_action(action)
    except ArchitectureReviewDirectionError as exc:
        _fail(str(exc))
    diagnosis_id = action.get("study_diagnosis_id")
    if diagnosis_id is not None:
        _prefixed("Study diagnosis", diagnosis_id, "diagnosis:")
    if "post_holdout_development_id" in action:
        _digest(
            "post-holdout development authority",
            action["post_holdout_development_id"],
        )
    _validate_diagnosis_authority_context(action)
    architecture_review_id = action.get("architecture_review_id")
    if architecture_review_id is not None:
        _prefixed(
            "architecture review",
            architecture_review_id,
            "architecture-review:",
        )
    if action["action"] not in _PORTFOLIO_EXECUTION_ACTIONS:
        _fail("Portfolio execution action is not executable work")
    if type(scientific.get("active_initiative")) is not str:
        _fail("Portfolio execution requires an active Initiative")
    present = architecture.intersection(action)
    if present not in (set(), architecture):
        _fail("Portfolio execution architecture bindings are incomplete")
    if present:
        _prefixed(
            "architecture chassis identity",
            action["architecture_chassis_identity"],
            "architecture-family:",
        )
        _prefixed(
            "baseline Executable identity",
            action["baseline_executable_id"],
            "executable:",
        )
        _prefixed(
            "resolved architecture family",
            action["resolved_architecture_family"],
            "architecture-family:",
        )
    replacement = action.get("replacement_architecture_equivalence")
    if replacement is not None:
        if not isinstance(replacement, Mapping):
            _fail("replacement architecture equivalence must be an object")
        required = {
            "accepted_axis_architecture_family",
            "accepted_replacement_preflight_id",
            "prospective_study_binding_hash",
            "replacement_architecture_family",
            "replacement_baseline_executable_id",
            "replacement_batch_id",
            "replacement_executable_ids",
            "replacement_lineage_id",
            "replacement_request_identity",
            "replay_obligation_ids",
            "schema",
            "scientific_equivalence_hash",
            "target_axis_identity",
        }
        _exact(
            "replacement architecture equivalence",
            replacement,
            required,
            {"engineering_gap_diagnosis_id"},
        )
        if replacement["schema"] != (
            "replay_replacement_architecture_equivalence.v1"
        ):
            _fail("replacement architecture equivalence schema is invalid")
        _prefixed(
            "accepted replacement preflight",
            replacement["accepted_replacement_preflight_id"],
            "job-implementation-preflight:",
        )
        accepted_family = _prefixed(
            "accepted axis architecture family",
            replacement["accepted_axis_architecture_family"],
            "architecture-family:",
        )
        replacement_family = _prefixed(
            "replacement architecture family",
            replacement["replacement_architecture_family"],
            "architecture-family:",
        )
        baseline_id = _prefixed(
            "replacement baseline Executable",
            replacement["replacement_baseline_executable_id"],
            "executable:",
        )
        _prefixed(
            "replacement Batch",
            replacement["replacement_batch_id"],
            "batch:",
        )
        _prefixed(
            "replacement request",
            replacement["replacement_request_identity"],
            "replay-job-implementation-preflight-request:",
        )
        _prefixed(
            "replacement semantic lineage",
            replacement["replacement_lineage_id"],
            "semantic-question-lineage:",
        )
        target_axis_identity = _prefixed(
            "replacement target axis",
            replacement["target_axis_identity"],
            "axis:",
        )
        _digest(
            "replacement scientific equivalence",
            replacement["scientific_equivalence_hash"],
        )
        _digest(
            "replacement prospective Study binding",
            replacement["prospective_study_binding_hash"],
        )
        obligations = _canonical_list(
            "replacement replay obligation",
            replacement["replay_obligation_ids"],
            prefix="historical-replay-obligation:",
        )
        _canonical_list(
            "replacement Executable",
            replacement["replacement_executable_ids"],
            prefix="executable:",
            ordered=True,
        )
        if "engineering_gap_diagnosis_id" in replacement:
            _prefixed(
                "replacement engineering-gap diagnosis",
                replacement["engineering_gap_diagnosis_id"],
                "diagnosis:",
            )
        if (
            present != architecture
            or "replay_obligation_ids" not in action
            or accepted_family == replacement_family
            or replacement_family != action["resolved_architecture_family"]
            or baseline_id != action["baseline_executable_id"]
            or target_axis_identity != action["target_axis_identity"]
            or obligations != action["replay_obligation_ids"]
        ):
            _fail(
                "replacement architecture equivalence differs from its action"
            )
    reentry_id = action.get("engineering_reentry_id")
    reentry_validation = action.get("engineering_reentry_validation")
    if (reentry_id is None) != (reentry_validation is None):
        _fail("prospective engineering reentry action is incomplete")
    if reentry_id is not None:
        _prefixed(
            "prospective engineering reentry",
            reentry_id,
            "prospective-engineering-reentry:",
        )
        if not isinstance(reentry_validation, Mapping):
            _fail("prospective engineering reentry validation must be an object")
        _exact(
            "prospective engineering reentry validation",
            reentry_validation,
            {
                "engineering_reentry_id",
                "portfolio_action",
                "required_review_basis",
                "schema",
                "scientific_claim_delta",
                "scientific_failure_delta",
                "scientific_trial_delta",
                "semantic_question_lineage_id",
                "successor_artifact_hash",
                "successor_baseline_executable_id",
                "successor_study_id",
            },
        )
        if (
            reentry_validation["schema"]
            != "prospective_engineering_reentry_validation.v1"
            or reentry_validation["engineering_reentry_id"] != reentry_id
            or reentry_validation["portfolio_action"] != action["action"]
            or any(
                reentry_validation[name] != 0
                for name in (
                    "scientific_claim_delta",
                    "scientific_failure_delta",
                    "scientific_trial_delta",
                )
            )
        ):
            _fail("prospective engineering reentry validation is invalid")
        _prefixed(
            "prospective reentry semantic lineage",
            reentry_validation["semantic_question_lineage_id"],
            "semantic-question-lineage:",
        )
        _digest(
            "prospective reentry successor artifact",
            reentry_validation["successor_artifact_hash"],
        )
        baseline_id = _prefixed(
            "prospective reentry baseline",
            reentry_validation["successor_baseline_executable_id"],
            "executable:",
        )
        _ascii(
            "prospective reentry successor Study",
            reentry_validation["successor_study_id"],
        )
        if not reentry_validation["successor_study_id"].startswith("STU-"):
            _fail("prospective reentry successor Study identity is invalid")
        basis = reentry_validation["required_review_basis"]
        if (
            type(basis) is not list
            or not basis
            or any(
                not isinstance(item, Mapping)
                or set(item) != {"kind", "record_id"}
                or type(item["kind"]) is not str
                or type(item["record_id"]) is not str
                for item in basis
            )
            or basis
            != sorted(
                basis,
                key=lambda item: (item["kind"], item["record_id"]),
            )
            or len({(item["kind"], item["record_id"]) for item in basis})
            != len(basis)
        ):
            _fail("prospective reentry review basis is malformed")
        if (
            present != architecture
            or baseline_id != action["baseline_executable_id"]
            or diagnosis_id is None
            or replacement is not None
            or bool(action.get("replay_obligation_ids"))
        ):
            _fail("prospective reentry baseline differs from its action")
    prospective_equivalence = action.get(
        "prospective_reentry_equivalence"
    )
    if prospective_equivalence is not None:
        if reentry_id is None or not isinstance(
            prospective_equivalence,
            Mapping,
        ):
            _fail("prospective reentry equivalence lacks its authority")
        _exact(
            "prospective reentry equivalence",
            prospective_equivalence,
            {
                "accepted_axis_architecture_family",
                "engineering_gap_diagnosis_id",
                "engineering_reentry_id",
                "replacement_architecture_family",
                "replacement_baseline_executable_id",
                "schema",
                "semantic_question_lineage_id",
                "successor_artifact_hash",
                "successor_study_id",
                "target_axis_identity",
            },
        )
        accepted_family = _prefixed(
            "prospective reentry accepted architecture",
            prospective_equivalence["accepted_axis_architecture_family"],
            "architecture-family:",
        )
        replacement_family = _prefixed(
            "prospective reentry replacement architecture",
            prospective_equivalence["replacement_architecture_family"],
            "architecture-family:",
        )
        replacement_baseline = _prefixed(
            "prospective reentry replacement baseline",
            prospective_equivalence["replacement_baseline_executable_id"],
            "executable:",
        )
        _prefixed(
            "prospective reentry diagnosis",
            prospective_equivalence["engineering_gap_diagnosis_id"],
            "diagnosis:",
        )
        _prefixed(
            "prospective reentry equivalence lineage",
            prospective_equivalence["semantic_question_lineage_id"],
            "semantic-question-lineage:",
        )
        _digest(
            "prospective reentry equivalence artifact",
            prospective_equivalence["successor_artifact_hash"],
        )
        if (
            prospective_equivalence["schema"]
            != "prospective_engineering_reentry_equivalence.v1"
            or prospective_equivalence["engineering_reentry_id"]
            != reentry_id
            or accepted_family == replacement_family
            or replacement_family != action["resolved_architecture_family"]
            or replacement_baseline != action["baseline_executable_id"]
            or prospective_equivalence["target_axis_identity"]
            != action["target_axis_identity"]
            or prospective_equivalence["engineering_gap_diagnosis_id"]
            != diagnosis_id
            or prospective_equivalence["semantic_question_lineage_id"]
            != reentry_validation["semantic_question_lineage_id"]
            or prospective_equivalence["successor_artifact_hash"]
            != reentry_validation["successor_artifact_hash"]
            or prospective_equivalence["successor_study_id"]
            != reentry_validation["successor_study_id"]
        ):
            _fail("prospective reentry equivalence differs from its action")


def _validate_freeze_batch(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    simple = {"kind", "study_id"}
    continued = {
        "batch_id",
        "continuation_decision_id",
        "kind",
        "study_id",
    }
    if set(action) not in (simple, continued):
        _fail("Batch freeze action schema is not exact")
    study_id = _ascii("Study identity", action["study_id"])
    _active_match(scientific, "active_study", study_id, "Batch freeze action")
    if set(action) == continued:
        _prefixed("next Batch identity", action["batch_id"], "batch:")
        _prefixed(
            "Study continuation decision",
            action["continuation_decision_id"],
            "study-continuation-decision:",
        )


def _validate_batch_action(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    simple = {"batch_id", "kind"}
    preflight_bound = {"basis_record_id", "batch_id", "kind"}
    if set(action) not in (simple, preflight_bound):
        _fail("Batch action schema is not exact")
    if set(action) == preflight_bound:
        if action.get("kind") != "dispose_batch":
            _fail("Only Batch disposition can carry a preflight basis")
        _prefixed(
            "Batch disposition preflight basis",
            action["basis_record_id"],
            "job-implementation-preflight:",
        )
    batch_id = _prefixed("Batch identity", action["batch_id"], "batch:")
    active = scientific.get("active_batch")
    if not isinstance(active, Mapping) or active.get("id") != batch_id:
        _fail("Batch action does not match the active Batch")


def _validate_job_identity_action(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del scientific, depth
    _exact("Job identity action", action, {"job_id", "kind"})
    _prefixed("Job identity", action["job_id"], "job:")


def _validate_resume_job(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del scientific, depth
    _exact(
        "Job resume action",
        action,
        {"job_id", "kind"},
        {"repair_close_record_id"},
    )
    _prefixed("Job identity", action["job_id"], "job:")
    if "repair_close_record_id" in action:
        _digest("Repair close record", action["repair_close_record_id"])


def _validate_judge_job_evidence(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del scientific, depth
    _exact(
        "Job evidence judgement action",
        action,
        {"job_id", "kind"},
        {"completion_record_id"},
    )
    _prefixed("Job identity", action["job_id"], "job:")
    if "completion_record_id" in action:
        _digest("Job completion record", action["completion_record_id"])


def _validate_review_study_continuation(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    _exact(
        "Study continuation review action",
        action,
        {"batch_close_record_id", "kind", "prior_batch_id", "study_id"},
    )
    _digest("Batch close record", action["batch_close_record_id"])
    _prefixed("prior Batch identity", action["prior_batch_id"], "batch:")
    study_id = _ascii("Study identity", action["study_id"])
    _active_match(
        scientific,
        "active_study",
        study_id,
        "Study continuation review action",
    )


def _validate_judge_study(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    _exact("Study judgement action", action, {"kind", "study_id"})
    study_id = _ascii("Study identity", action["study_id"])
    _active_match(scientific, "active_study", study_id, "Study judgement action")


def _validate_diagnose_study(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    record_bound = {
        "kind",
        "portfolio_snapshot_id",
        "study_close_record_id",
        "study_id",
    }
    checkpoint_bound = {
        "kind",
        "study_close_event_id",
        "study_close_revision",
        "study_id",
    }
    if set(action) not in (record_bound, checkpoint_bound):
        _fail("Study diagnosis action schema is not exact")
    _ascii("Study identity", action["study_id"])
    if set(action) == record_bound:
        _digest("Study close record", action["study_close_record_id"])
        _prefixed(
            "Portfolio snapshot identity",
            action["portfolio_snapshot_id"],
            "portfolio:",
        )
    else:
        _digest("Study close event", action["study_close_event_id"])
        revision = action["study_close_revision"]
        if type(revision) is not int or revision < 1:
            _fail("Study close revision must be a positive integer")
    if (
        set(action) == record_bound
        and type(scientific.get("active_initiative")) is not str
    ):
        _fail("Study diagnosis requires an active Initiative")


def _validate_review_architecture(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    _exact(
        "architecture review action",
        action,
        {"kind", "trigger_record_id"},
        {"post_holdout_development_id"},
    )
    _digest("architecture review trigger", action["trigger_record_id"])
    if "post_holdout_development_id" in action:
        _digest(
            "post-holdout development authority",
            action["post_holdout_development_id"],
        )
    if type(scientific.get("active_initiative")) is not str:
        _fail("architecture review requires an active Initiative")


def _validate_resolve_replay(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    _exact(
        "historical replay resolution action",
        action,
        {
            "kind",
            "replay_obligation_ids",
            "resume_next_action",
            "study_diagnosis_id",
            "study_id",
        },
    )
    _canonical_list(
        "historical replay obligation",
        action["replay_obligation_ids"],
        prefix="historical-replay-obligation:",
    )
    diagnosis_id = _prefixed(
        "Study diagnosis identity", action["study_diagnosis_id"], "diagnosis:"
    )
    _ascii("Study identity", action["study_id"])
    if type(scientific.get("active_initiative")) is not str:
        _fail("historical replay resolution requires an active Initiative")
    nested = action["resume_next_action"]
    if not isinstance(nested, Mapping) or nested.get("kind") != "portfolio_decision":
        _fail("historical replay resume action must restore Portfolio decision")
    _validate_action(nested, scientific, depth=depth + 1, cross_bind=False)
    if nested.get("study_diagnosis_id") != diagnosis_id:
        _fail("historical replay resume action differs from its diagnosis")


def _validate_plan_candidate(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    _exact(
        "candidate-bound evidence action", action, {"executable_id", "kind"}
    )
    executable_id = _prefixed(
        "Executable identity", action["executable_id"], "executable:"
    )
    _active_match(
        scientific,
        "active_executable",
        executable_id,
        "candidate-bound evidence action",
    )


def _validate_candidate_gap(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    _exact(
        "candidate engineering-gap action",
        action,
        {
            "completion_record_id",
            "disposition",
            "executable_id",
            "job_id",
            "kind",
            "resume_condition",
            "successor_scope",
            "target_id",
            "work_context",
        },
    )
    _digest("candidate gap completion", action["completion_record_id"])
    _prefixed("candidate gap Job", action["job_id"], "job:")
    executable_id = _prefixed(
        "candidate gap Executable", action["executable_id"], "executable:"
    )
    _active_match(
        scientific,
        "active_executable",
        executable_id,
        "candidate engineering-gap action",
    )
    disposition = action["disposition"]
    if disposition not in _ENGINEERING_DISPOSITIONS:
        _fail("candidate engineering disposition is invalid")
    scope = action["successor_scope"]
    if disposition == "requires_scientific_change":
        if scope not in {"executable", "study"}:
            _fail("scientific-change disposition requires its successor scope")
    elif scope is not None:
        _fail("engineering-only disposition cannot name a successor scope")
    _ascii("candidate gap resume condition", action["resume_condition"])
    work_context = action["work_context"]
    if work_context not in {"pre_reveal_holdout", "runtime", "source"}:
        _fail("candidate engineering work context is invalid")
    target_id = action["target_id"]
    if work_context == "pre_reveal_holdout":
        _prefixed("candidate gap holdout", target_id, "holdout:")
    elif work_context == "source":
        _prefixed("candidate gap source", target_id, "source:")
    else:
        _ascii("candidate runtime evidence depth", target_id)


def _validate_record_source_eligibility(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    _exact(
        "source eligibility action",
        action,
        {
            "completion_record_id",
            "job_id",
            "kind",
            "resume_next_action",
            "source_contract_id",
        },
    )
    _digest("source Job completion", action["completion_record_id"])
    _prefixed("source Job identity", action["job_id"], "job:")
    _prefixed(
        "source contract identity", action["source_contract_id"], "source:"
    )
    nested = action["resume_next_action"]
    if not isinstance(nested, Mapping):
        _fail("source eligibility resume action is not structured")
    if nested.get("kind") == "record_source_eligibility":
        _fail("source eligibility action cannot recursively restore itself")
    _validate_action(nested, scientific, depth=depth + 1, cross_bind=False)


def _validate_runtime_source_ineligibility(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del scientific, depth
    _exact(
        "runtime source-ineligibility action",
        action,
        {
            "job_id",
            "kind",
            "observation_id",
            "source_contract_id",
            "source_state_record_id",
        },
    )
    _prefixed("runtime source Job", action["job_id"], "job:")
    _prefixed(
        "runtime source observation",
        action["observation_id"],
        "runtime-source-drift:",
    )
    _prefixed(
        "runtime source contract", action["source_contract_id"], "source:"
    )
    _digest("runtime source state record", action["source_state_record_id"])


def _validate_completion_job_action(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del scientific, depth
    _exact(
        "completed Job action",
        action,
        {"completion_record_id", "job_id", "kind"},
    )
    _digest("Job completion record", action["completion_record_id"])
    _prefixed("Job identity", action["job_id"], "job:")


def _validate_declare_external_job(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    _exact(
        "external dependency Job action",
        action,
        {
            "kind",
            "prior_completion_record_ids",
            "recovery_path_id",
            "recovery_plan_id",
        },
    )
    _canonical_list(
        "prior external completion",
        action["prior_completion_record_ids"],
        digest_values=True,
        ordered=True,
    )
    _ascii("external recovery path", action["recovery_path_id"])
    _prefixed(
        "external recovery plan",
        action["recovery_plan_id"],
        "external-recovery-plan:",
    )
    if type(scientific.get("active_mission")) is not str:
        _fail("external dependency Job requires an active Mission")


def _validate_record_external_blocker(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    _exact(
        "external blocker action",
        action,
        {"completion_record_ids", "dependency_id", "kind", "recovery_plan_id"},
    )
    _canonical_list(
        "external blocker completion",
        action["completion_record_ids"],
        digest_values=True,
        ordered=True,
    )
    _ascii("external dependency identity", action["dependency_id"])
    _prefixed(
        "external recovery plan",
        action["recovery_plan_id"],
        "external-recovery-plan:",
    )
    if type(scientific.get("active_mission")) is not str:
        _fail("external blocker action requires an active Mission")


def _validate_execute_repair(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del scientific, depth
    first = {"kind", "repair_id"}
    retried = {
        "kind",
        "prior_attempt_record_id",
        "repair_id",
        "required_previous_basis_hash",
    }
    if set(action) not in (first, retried):
        _fail("Repair execution action schema is not exact")
    _prefixed("Repair identity", action["repair_id"], "repair:")
    if set(action) == retried:
        _digest("prior Repair attempt", action["prior_attempt_record_id"])
        _digest("previous Repair basis", action["required_previous_basis_hash"])


def _validate_engineering_failure(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del scientific, depth
    _exact(
        "engineering failure completion action",
        action,
        {"disposition_hash", "disposition_record_id", "job_id", "kind"},
    )
    _digest("engineering disposition", action["disposition_hash"])
    _digest("engineering disposition record", action["disposition_record_id"])
    _prefixed("engineering failure Job", action["job_id"], "job:")


def _validate_issue_release_permit(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    _exact("Release permit action", action, {"kind", "release_id"})
    release_id = _ascii("Release identity", action["release_id"])
    active = scientific.get("active_release")
    if not isinstance(active, Mapping) or active.get("id") != release_id:
        _fail("Release permit action does not match the active Release")


def _validate_evaluate_holdout(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    _exact(
        "holdout evaluation action", action, {"executable_id", "kind"}
    )
    executable_id = _prefixed(
        "holdout Executable", action["executable_id"], "executable:"
    )
    _active_match(
        scientific,
        "active_executable",
        executable_id,
        "holdout evaluation action",
    )


def _validate_holdout_disposition(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    _exact(
        "holdout disposition action",
        action,
        {"completion_record_id", "holdout_id", "job_id", "kind"},
    )
    completion_id = _digest(
        "holdout Job completion", action["completion_record_id"]
    )
    holdout_id = _prefixed("holdout identity", action["holdout_id"], "holdout:")
    job_id = _prefixed("holdout Job identity", action["job_id"], "job:")
    active = scientific.get("active_holdout_evaluation")
    if not isinstance(active, Mapping) or any(
        active.get(key) != expected
        for key, expected in (
            ("completion_record_id", completion_id),
            ("holdout_id", holdout_id),
            ("job_id", job_id),
        )
    ):
        _fail("holdout disposition does not match the active holdout")


def _validate_await_new_holdout(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    _exact(
        "future holdout wait action",
        action,
        {"kind", "predecessor_holdout_id"},
    )
    _prefixed(
        "predecessor holdout",
        action["predecessor_holdout_id"],
        "holdout:",
    )
    if type(scientific.get("active_mission")) is not str:
        _fail("future holdout wait requires an active Mission")


def _validate_register_future_material(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    _exact(
        "future development material action",
        action,
        {"holdout_id", "kind", "mission_id", "predecessor_holdout_id"},
    )
    mission_id = _ascii("Mission identity", action["mission_id"])
    _active_match(
        scientific,
        "active_mission",
        mission_id,
        "future development material action",
    )
    holdout_id = _prefixed("future holdout", action["holdout_id"], "holdout:")
    predecessor_id = _prefixed(
        "predecessor holdout",
        action["predecessor_holdout_id"],
        "holdout:",
    )
    if holdout_id == predecessor_id:
        _fail("future holdout must differ from its predecessor")
    required_id = scientific.get("required_future_holdout_id")
    if required_id is not None and required_id != holdout_id:
        _fail("future development action differs from the required holdout")


def _validate_close_mission(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del depth
    _exact("Mission terminal action", action, {"basis_record_id", "kind", "outcome"})
    outcome = action["outcome"]
    if outcome not in {
        "blocked_external",
        "closed_no_candidate",
        "completed_pre_live_handoff",
    }:
        _fail("Mission terminal outcome is invalid")
    basis = action["basis_record_id"]
    if outcome == "completed_pre_live_handoff":
        _ascii("Release terminal basis", basis)
        active_release = scientific.get("active_release")
        if (
            not isinstance(active_release, Mapping)
            or active_release.get("status") != "frozen"
            or active_release.get("id") != basis
        ):
            _fail("positive Mission terminal lacks its frozen Release")
    else:
        _digest("Mission terminal basis", basis)
    if type(scientific.get("active_mission")) is not str:
        _fail("Mission terminal action requires an active Mission")


def _external_resume_action(
    value: object,
    *,
    predecessor_mission_id: str,
) -> None:
    if not isinstance(value, Mapping):
        _fail("external resume action is not structured")
    kind = value.get("kind")
    if kind == "choose_next_initiative_or_terminal":
        _exact(
            "external Mission scheduler resume action",
            value,
            {"kind", "mission_id"},
            _REPLAY_SCHEDULER_KEYS,
        )
        _scheduler(value)
    elif kind == "open_initiative":
        _exact(
            "external Initiative resume action",
            value,
            {"kind", "mission_id", "research_intake_id"},
        )
        _prefixed(
            "external resume research intake",
            value["research_intake_id"],
            "research-intake:",
        )
    else:
        _fail("external resume action kind is unsupported")
    if value.get("mission_id") != predecessor_mission_id:
        _fail("external resume action names another Mission")


def _validate_await_external_change(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del scientific, depth
    _exact(
        "external-change boundary",
        action,
        {
            "basis_record_id",
            "kind",
            "mission_resume_next_action",
            "predecessor_mission_close_record_id",
            "predecessor_mission_id",
            "required_external_change",
            "resume_condition_id",
        },
    )
    _digest("external blocker basis", action["basis_record_id"])
    _digest(
        "blocked Mission close record",
        action["predecessor_mission_close_record_id"],
    )
    mission_id = _ascii(
        "blocked predecessor Mission", action["predecessor_mission_id"]
    )
    _ascii("required external change", action["required_external_change"])
    _prefixed(
        "external resume condition",
        action["resume_condition_id"],
        "external-resume-condition:",
    )
    _external_resume_action(
        action["mission_resume_next_action"],
        predecessor_mission_id=mission_id,
    )


def _validate_project_goal_complete(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    del scientific, depth
    _exact(
        "Project Goal completion action",
        action,
        {"kind", "mission_close_record_id", "outcome"},
    )
    _digest("Project Goal Mission close", action["mission_close_record_id"])
    if action["outcome"] != "completed_pre_live_handoff":
        _fail("Project Goal completion outcome is invalid")


_Validator = Callable[[Mapping[str, Any], Mapping[str, Any], int], None]


_VALIDATORS: dict[str, _Validator] = {
    "await_external_change": _validate_await_external_change,
    "await_new_future_holdout_data": _validate_await_new_holdout,
    "await_root_goal": _validate_await_root_goal,
    "build_portfolio": _validate_build_portfolio,
    "choose_next_initiative_or_terminal": _validate_choose_next,
    "close_mission": _validate_close_mission,
    "complete_engineering_failure": _validate_engineering_failure,
    "complete_runtime_source_ineligibility": _validate_runtime_source_ineligibility,
    "declare_external_dependency_job": _validate_declare_external_job,
    "declare_job": _validate_batch_action,
    "diagnose_study": _validate_diagnose_study,
    "dispose_batch": _validate_batch_action,
    "dispose_revealed_holdout_engineering_gap": _validate_holdout_disposition,
    "evaluate_frozen_holdout": _validate_evaluate_holdout,
    "execute_portfolio_decision": _validate_execute_portfolio_decision,
    "execute_repair": _validate_execute_repair,
    "freeze_batch": _validate_freeze_batch,
    "issue_job_permit": _validate_job_identity_action,
    "issue_release_permit": _validate_issue_release_permit,
    "judge_external_dependency_evidence": _validate_completion_job_action,
    "judge_job_evidence": _validate_judge_job_evidence,
    "judge_study": _validate_judge_study,
    "open_initiative": _validate_open_initiative,
    "plan_candidate_bound_evidence": _validate_plan_candidate,
    "portfolio_decision": _validate_portfolio_decision,
    "project_goal_complete": _validate_project_goal_complete,
    "record_axis_reopen_authority": _validate_record_axis_reopen_authority,
    "record_external_blocker": _validate_record_external_blocker,
    "record_holdout_evaluation": _validate_holdout_disposition,
    "record_portfolio_snapshot": _validate_record_portfolio_snapshot,
    "record_research_intake": _validate_record_research_intake,
    "record_source_eligibility": _validate_record_source_eligibility,
    "register_future_development_material": _validate_register_future_material,
    "resolve_candidate_engineering_gap": _validate_candidate_gap,
    "resolve_historical_replay_obligations": _validate_resolve_replay,
    "resume_job": _validate_resume_job,
    "review_architecture": _validate_review_architecture,
    "review_study_continuation": _validate_review_study_continuation,
}


def _cross_bind_active_job(
    action: Mapping[str, Any], scientific: Mapping[str, Any], depth: int
) -> None:
    active_job = scientific.get("active_job")
    active_repair = scientific.get("active_repair")
    active_holdout = scientific.get("active_holdout_evaluation")
    active_release = scientific.get("active_release")
    kind = action["kind"]
    if isinstance(active_job, Mapping):
        status = active_job.get("status")
        allowed = {
            "declared": {"issue_job_permit"},
            "running": {
                "complete_engineering_failure",
                "complete_runtime_source_ineligibility",
                "evaluate_frozen_holdout",
                "resume_job",
            },
            "interrupted_repair": {"execute_repair"},
        }.get(status, set())
        if kind not in allowed:
            _fail("active Job and next action are incoherent")
        job_id = active_job.get("id")
        if "job_id" in action and action["job_id"] != job_id:
            _fail("next action names another active Job")
        if kind == "resume_job":
            repair_close = active_job.get("required_repair_resume_record_id")
            expected = {"job_id": job_id, "kind": "resume_job"}
            if repair_close is not None:
                expected["repair_close_record_id"] = repair_close
            if dict(action) != expected:
                _fail("active Job resume action is not exact")
        if kind == "complete_engineering_failure":
            disposition_hash = active_job.get(
                "required_engineering_disposition_hash"
            )
            disposition_record_id = active_job.get(
                "required_engineering_disposition_record_id"
            )
            cause_hash = active_job.get("required_engineering_failure_cause_hash")
            if (
                active_job.get("status") != "running"
                or action.get("disposition_hash") != disposition_hash
                or action.get("disposition_record_id")
                != disposition_record_id
                or not isinstance(disposition_record_id, str)
                or not isinstance(cause_hash, str)
                or "required_engineering_repair_id" not in active_job
            ):
                _fail("engineering failure action differs from its active Job")
        saved_return = active_job.get("return_next_action")
        if saved_return is not None:
            if not isinstance(saved_return, Mapping):
                _fail("active Job return action is not structured")
            _validate_action(
                saved_return,
                scientific,
                depth=depth + 1,
                cross_bind=False,
            )
    elif kind in {
        "complete_engineering_failure",
        "complete_runtime_source_ineligibility",
        "issue_job_permit",
        "resume_job",
    }:
        _fail("Job-bound action has no active Job")

    if isinstance(active_repair, Mapping):
        latest_attempt = active_repair.get("latest_attempt_record_id")
        expected: dict[str, Any] = {
            "kind": "execute_repair",
            "repair_id": active_repair.get("id"),
        }
        if latest_attempt is not None:
            expected.update(
                {
                    "prior_attempt_record_id": latest_attempt,
                    "required_previous_basis_hash": active_repair.get(
                        "latest_basis_hash"
                    ),
                }
            )
        if dict(action) != expected:
            _fail("active Repair next action is not exact")
    elif kind == "execute_repair":
        _fail("Repair execution action has no active Repair")

    if isinstance(active_holdout, Mapping):
        status = active_holdout.get("status")
        if status == "revealed_pending_evaluation":
            if not isinstance(active_job, Mapping) or active_job.get(
                "id"
            ) != active_holdout.get("job_id"):
                _fail("revealed holdout is not bound to its active Job")
            if kind == "evaluate_frozen_holdout" and action.get(
                "executable_id"
            ) != active_holdout.get("executable_id"):
                _fail("holdout evaluation names another Executable")
        else:
            expected_kind = {
                "engineering_gap_pending_disposition": (
                    "dispose_revealed_holdout_engineering_gap"
                ),
                "evaluation_completed_pending_disposition": (
                    "record_holdout_evaluation"
                ),
            }.get(status)
            if kind != expected_kind:
                _fail("active holdout and next action are incoherent")

    if isinstance(active_release, Mapping):
        release_status = active_release.get("status")
        if release_status == "declared" and kind != "issue_release_permit":
            _fail("declared Release lacks its permit action")
        if release_status == "frozen" and (
            kind != "close_mission"
            or action.get("outcome") != "completed_pre_live_handoff"
            or action.get("basis_record_id") != active_release.get("id")
        ):
            _fail("frozen Release lacks its positive Mission terminal")


def _validate_action(
    action: Mapping[str, Any],
    scientific: Mapping[str, Any],
    *,
    depth: int,
    cross_bind: bool,
) -> None:
    if depth > 4:
        _fail("nested next action depth is excessive")
    if not isinstance(action, Mapping):
        _fail("one structured next action is required")
    _ascii_tree("next action", dict(action))
    kind = _ascii("next action kind", action.get("kind"))
    validator = _VALIDATORS.get(kind)
    if validator is None:
        _fail(f"unsupported next action kind: {kind}")
    validator(action, scientific, depth)
    if cross_bind:
        _cross_bind_active_job(action, scientific, depth)


def validate_control_next_action(
    next_action: object,
    scientific: Mapping[str, Any],
    *,
    engineering_fixture: bool = False,
) -> None:
    """Validate the closed historical-and-prospective Writer action union."""

    if not isinstance(scientific, Mapping):
        _fail("scientific projection is unavailable to next-action validation")
    if type(engineering_fixture) is not bool:
        _fail("engineering fixture context must be boolean")
    if not isinstance(next_action, Mapping):
        _fail("one structured next action is required")
    context = dict(scientific)
    if engineering_fixture:
        context[_ENGINEERING_FIXTURE_CONTEXT] = True
    _validate_action(next_action, context, depth=0, cross_bind=True)


def is_successor_mission_boundary(next_action: object) -> bool:
    """Return whether the action is the exact negative-Mission successor gate."""

    return bool(
        isinstance(next_action, Mapping)
        and next_action.get("kind") == "await_root_goal"
        and set(next_action)
        == {
            "kind",
            "predecessor_basis_record_id",
            "predecessor_mission_close_record_id",
            "predecessor_mission_id",
            "predecessor_outcome",
        }
    )


__all__ = [
    "ControlNextActionError",
    "SUPPORTED_NEXT_ACTION_KINDS",
    "is_successor_mission_boundary",
    "validate_control_next_action",
]
