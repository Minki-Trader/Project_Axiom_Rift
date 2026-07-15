from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import unittest

from axiom_rift.storage.control_next_action import (
    ControlNextActionError,
    SUPPORTED_NEXT_ACTION_KINDS,
    validate_control_next_action,
)
from axiom_rift.storage.state import (
    ControlStateError,
    control_hash,
    validate_control,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
D0 = "0" * 64
D1 = "1" * 64
D2 = "2" * 64
MISSION = "MIS-NEXT-ACTION"
INITIATIVE = "INI-NEXT-ACTION"
STUDY = "STU-NEXT-ACTION"
BATCH = "batch:" + D0
JOB = "job:" + D0
REPAIR = "repair:" + D0
EXECUTABLE = "executable:" + D0
HOLDOUT = "holdout:" + D0
NEXT_HOLDOUT = "holdout:" + D1
PORTFOLIO = "portfolio:" + D0
DECISION = "decision:" + D0
AXIS = "axis:" + D0
DIAGNOSIS = "diagnosis:" + D0
RESEARCH_INTAKE = "research-intake:" + D0
REPLAY_0 = "historical-replay-obligation:" + D0
REPLAY_1 = "historical-replay-obligation:" + D1


def _science(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "active_batch": None,
        "active_executable": EXECUTABLE,
        "active_holdout_evaluation": None,
        "active_initiative": INITIATIVE,
        "active_job": None,
        "active_mission": MISSION,
        "active_release": None,
        "active_repair": None,
        "active_study": STUDY,
        "required_future_holdout_id": None,
    }
    value.update(updates)
    return value


def _disposed_science() -> dict[str, object]:
    return _science(
        active_executable=None,
        active_initiative=None,
        active_mission=None,
        active_study=None,
    )


def _fixtures() -> dict[str, tuple[dict[str, object], dict[str, object]]]:
    running_job = {"id": JOB, "status": "running"}
    holdout = {
        "candidate_id": "candidate:" + D0,
        "executable_id": EXECUTABLE,
        "holdout_id": HOLDOUT,
        "job_id": JOB,
        "status": "revealed_pending_evaluation",
    }
    completed_holdout = {
        **holdout,
        "completion_record_id": D0,
        "status": "evaluation_completed_pending_disposition",
    }
    engineering_holdout = {
        **completed_holdout,
        "status": "engineering_gap_pending_disposition",
    }
    return {
        "await_external_change": (
            {
                "basis_record_id": D0,
                "kind": "await_external_change",
                "mission_resume_next_action": {
                    "kind": "choose_next_initiative_or_terminal",
                    "mission_id": MISSION,
                    "pending_replay_obligation_ids": [REPLAY_0],
                    "required_replay_priority": "p1",
                },
                "predecessor_mission_close_record_id": D1,
                "predecessor_mission_id": MISSION,
                "required_external_change": "broker service restored",
                "resume_condition_id": "external-resume-condition:" + D0,
            },
            _disposed_science(),
        ),
        "await_new_future_holdout_data": (
            {
                "kind": "await_new_future_holdout_data",
                "predecessor_holdout_id": HOLDOUT,
            },
            _science(active_executable=None, active_study=None),
        ),
        "await_root_goal": ({"kind": "await_root_goal"}, _disposed_science()),
        "build_portfolio": (
            {
                "initiative_id": INITIATIVE,
                "kind": "build_portfolio",
                "research_intake_id": RESEARCH_INTAKE,
            },
            _science(),
        ),
        "choose_next_initiative_or_terminal": (
            {
                "kind": "choose_next_initiative_or_terminal",
                "mission_id": MISSION,
                "pending_replay_obligation_ids": [REPLAY_0],
                "required_replay_priority": "p0",
            },
            _science(),
        ),
        "close_mission": (
            {
                "basis_record_id": "REL-NEXT-ACTION",
                "kind": "close_mission",
                "outcome": "completed_pre_live_handoff",
            },
            _science(
                active_release={
                    "id": "REL-NEXT-ACTION",
                    "status": "frozen",
                }
            ),
        ),
        "complete_engineering_failure": (
            {
                "disposition_hash": D1,
                "job_id": JOB,
                "kind": "complete_engineering_failure",
            },
            _science(
                active_job={
                    "id": JOB,
                    "required_engineering_disposition_hash": D1,
                    "required_engineering_failure_cause_hash": D2,
                    "required_engineering_repair_id": None,
                    "status": "running",
                }
            ),
        ),
        "complete_runtime_source_ineligibility": (
            {
                "job_id": JOB,
                "kind": "complete_runtime_source_ineligibility",
                "observation_id": "runtime-source-drift:" + D0,
                "source_contract_id": "source:" + D0,
                "source_state_record_id": D1,
            },
            _science(active_job=running_job),
        ),
        "declare_external_dependency_job": (
            {
                "kind": "declare_external_dependency_job",
                "prior_completion_record_ids": [D0, D1],
                "recovery_path_id": "safe-substitute-search",
                "recovery_plan_id": "external-recovery-plan:" + D0,
            },
            _science(active_executable=None, active_study=None),
        ),
        "declare_job": (
            {"batch_id": BATCH, "kind": "declare_job"},
            _science(active_batch={"id": BATCH}),
        ),
        "diagnose_study": (
            {
                "kind": "diagnose_study",
                "portfolio_snapshot_id": PORTFOLIO,
                "study_close_record_id": D0,
                "study_id": STUDY,
            },
            _science(active_study=None),
        ),
        "dispose_batch": (
            {"batch_id": BATCH, "kind": "dispose_batch"},
            _science(active_batch={"id": BATCH}),
        ),
        "dispose_revealed_holdout_engineering_gap": (
            {
                "completion_record_id": D0,
                "holdout_id": HOLDOUT,
                "job_id": JOB,
                "kind": "dispose_revealed_holdout_engineering_gap",
            },
            _science(
                active_holdout_evaluation=engineering_holdout,
                active_job=None,
            ),
        ),
        "evaluate_frozen_holdout": (
            {
                "executable_id": EXECUTABLE,
                "kind": "evaluate_frozen_holdout",
            },
            _science(
                active_holdout_evaluation=holdout,
                active_job=running_job,
            ),
        ),
        "execute_portfolio_decision": (
            {
                "action": "contrast",
                "architecture_chassis_identity": "architecture-family:" + D0,
                "baseline_executable_id": EXECUTABLE,
                "decision_id": DECISION,
                "kind": "execute_portfolio_decision",
                "portfolio_snapshot_id": PORTFOLIO,
                "replay_obligation_ids": [REPLAY_0],
                "resolved_architecture_family": "architecture-family:" + D0,
                "target_axis_identity": AXIS,
                "target_id": "axis-next-action",
            },
            _science(),
        ),
        "execute_repair": (
            {"kind": "execute_repair", "repair_id": REPAIR},
            _science(
                active_job={"id": JOB, "status": "interrupted_repair"},
                active_repair={
                    "id": REPAIR,
                    "latest_attempt_record_id": None,
                    "latest_basis_hash": D1,
                },
            ),
        ),
        "freeze_batch": (
            {
                "batch_id": BATCH,
                "continuation_decision_id": (
                    "study-continuation-decision:" + D0
                ),
                "kind": "freeze_batch",
                "study_id": STUDY,
            },
            _science(),
        ),
        "issue_job_permit": (
            {"job_id": JOB, "kind": "issue_job_permit"},
            _science(active_job={"id": JOB, "status": "declared"}),
        ),
        "issue_release_permit": (
            {"kind": "issue_release_permit", "release_id": "REL-NEXT-ACTION"},
            _science(
                active_release={
                    "id": "REL-NEXT-ACTION",
                    "status": "declared",
                }
            ),
        ),
        "judge_external_dependency_evidence": (
            {
                "completion_record_id": D0,
                "job_id": JOB,
                "kind": "judge_external_dependency_evidence",
            },
            _science(active_executable=None, active_study=None),
        ),
        "judge_job_evidence": (
            {
                "completion_record_id": D0,
                "job_id": JOB,
                "kind": "judge_job_evidence",
            },
            _science(active_batch={"id": BATCH}),
        ),
        "judge_study": (
            {"kind": "judge_study", "study_id": STUDY},
            _science(),
        ),
        "open_initiative": (
            {
                "kind": "open_initiative",
                "mission_id": MISSION,
                "research_intake_id": RESEARCH_INTAKE,
            },
            _science(active_initiative=None, active_study=None),
        ),
        "plan_candidate_bound_evidence": (
            {
                "executable_id": EXECUTABLE,
                "kind": "plan_candidate_bound_evidence",
            },
            _science(active_study=None),
        ),
        "portfolio_decision": (
            {
                "constraint_source_id": DIAGNOSIS,
                "kind": "portfolio_decision",
                "pending_replay_obligation_ids": [REPLAY_0],
                "portfolio_snapshot_id": PORTFOLIO,
                "required_replay_priority": "p1",
                "required_target_axis_ids": ["axis-next-action"],
                "study_diagnosis_id": DIAGNOSIS,
            },
            _science(active_study=None),
        ),
        "project_goal_complete": (
            {
                "kind": "project_goal_complete",
                "mission_close_record_id": D0,
                "outcome": "completed_pre_live_handoff",
            },
            _disposed_science(),
        ),
        "record_axis_reopen_authority": (
            {
                "action": "preserve",
                "decision_id": DECISION,
                "evidence_scope_overlay_ids": [
                    "historical-evidence-scope:" + D0
                ],
                "kind": "record_axis_reopen_authority",
                "pending_replay_obligation_ids": [REPLAY_0],
                "portfolio_snapshot_id": PORTFOLIO,
                "replay_obligation_ids": [REPLAY_0],
                "replay_resolution_record_ids": [
                    "historical-replay-satisfaction:" + D0
                ],
                "required_replay_priority": "p1",
                "target_axis_identity": AXIS,
                "target_id": "axis-next-action",
            },
            _science(active_study=None),
        ),
        "record_external_blocker": (
            {
                "completion_record_ids": [D0, D1],
                "dependency_id": "fpmarkets-runtime",
                "kind": "record_external_blocker",
                "recovery_plan_id": "external-recovery-plan:" + D0,
            },
            _science(active_executable=None, active_study=None),
        ),
        "record_holdout_evaluation": (
            {
                "completion_record_id": D0,
                "holdout_id": HOLDOUT,
                "job_id": JOB,
                "kind": "record_holdout_evaluation",
            },
            _science(
                active_holdout_evaluation=completed_holdout,
                active_job=None,
            ),
        ),
        "record_portfolio_snapshot": (
            {
                "action": "new_mechanism",
                "constraint_source_id": DIAGNOSIS,
                "decision_id": DECISION,
                "kind": "record_portfolio_snapshot",
                "pending_replay_obligation_ids": [REPLAY_0],
                "portfolio_snapshot_id": PORTFOLIO,
                "replay_obligation_ids": [REPLAY_0],
                "required_followup_layers": ["data_source", "execution"],
                "required_replay_priority": "p1",
                "target_axis_identity": AXIS,
                "target_id": "axis-next-action",
            },
            _science(active_study=None),
        ),
        "record_research_intake": (
            {"kind": "record_research_intake", "mission_id": MISSION},
            _science(active_initiative=None, active_study=None),
        ),
        "record_source_eligibility": (
            {
                "completion_record_id": D0,
                "job_id": JOB,
                "kind": "record_source_eligibility",
                "resume_next_action": {
                    "executable_id": EXECUTABLE,
                    "kind": "plan_candidate_bound_evidence",
                },
                "source_contract_id": "source:" + D0,
            },
            _science(active_study=None),
        ),
        "register_future_development_material": (
            {
                "holdout_id": NEXT_HOLDOUT,
                "kind": "register_future_development_material",
                "mission_id": MISSION,
                "predecessor_holdout_id": HOLDOUT,
            },
            _science(
                active_executable=None,
                active_study=None,
                required_future_holdout_id=NEXT_HOLDOUT,
            ),
        ),
        "resolve_candidate_engineering_gap": (
            {
                "completion_record_id": D0,
                "disposition": "repair_infeasible",
                "executable_id": EXECUTABLE,
                "job_id": JOB,
                "kind": "resolve_candidate_engineering_gap",
                "resume_condition": "new source receipt is available",
                "successor_scope": None,
                "target_id": "source:" + D0,
                "work_context": "source",
            },
            _science(active_study=None),
        ),
        "resolve_historical_replay_obligations": (
            {
                "kind": "resolve_historical_replay_obligations",
                "replay_obligation_ids": [REPLAY_0],
                "resume_next_action": {
                    "kind": "portfolio_decision",
                    "portfolio_snapshot_id": PORTFOLIO,
                    "study_diagnosis_id": DIAGNOSIS,
                },
                "study_diagnosis_id": DIAGNOSIS,
                "study_id": STUDY,
            },
            _science(active_study=None),
        ),
        "resume_job": (
            {"job_id": JOB, "kind": "resume_job"},
            _science(active_job=running_job),
        ),
        "review_architecture": (
            {"kind": "review_architecture", "trigger_record_id": D0},
            _science(active_study=None),
        ),
        "review_study_continuation": (
            {
                "batch_close_record_id": D0,
                "kind": "review_study_continuation",
                "prior_batch_id": BATCH,
                "study_id": STUDY,
            },
            _science(),
        ),
    }


class ControlNextActionTests(unittest.TestCase):
    def test_fixture_union_is_the_closed_supported_union(self) -> None:
        fixtures = _fixtures()
        self.assertEqual(frozenset(fixtures), SUPPORTED_NEXT_ACTION_KINDS)
        for kind, (action, scientific) in fixtures.items():
            with self.subTest(kind=kind):
                validate_control_next_action(action, scientific)

    def test_all_writer_action_names_are_present_in_the_closed_union(self) -> None:
        sources = "\n".join(
            (REPOSITORY_ROOT / path).read_text("ascii")
            for path in (
                "src/axiom_rift/operations/external_dependency.py",
                "src/axiom_rift/operations/job_completion_projection.py",
                "src/axiom_rift/operations/writer.py",
            )
        )
        missing = [
            kind
            for kind in sorted(SUPPORTED_NEXT_ACTION_KINDS)
            if repr(kind) not in sources and json.dumps(kind) not in sources
        ]
        self.assertEqual(missing, [])

    def test_every_supported_kind_rejects_an_unknown_field(self) -> None:
        for kind, (original, scientific) in _fixtures().items():
            with self.subTest(kind=kind):
                action = deepcopy(original)
                action["forged_extra"] = "accepted-by-the-old-validator"
                with self.assertRaisesRegex(
                    ControlNextActionError, "schema is not exact"
                ):
                    validate_control_next_action(action, scientific)

    def test_every_supported_kind_rejects_a_missing_kind_and_boolean_kind(self) -> None:
        for kind, (original, scientific) in _fixtures().items():
            with self.subTest(kind=kind, mutation="missing"):
                action = deepcopy(original)
                action.pop("kind")
                with self.assertRaises(ControlNextActionError):
                    validate_control_next_action(action, scientific)
            with self.subTest(kind=kind, mutation="boolean"):
                action = deepcopy(original)
                action["kind"] = True
                with self.assertRaises(ControlNextActionError):
                    validate_control_next_action(action, scientific)

    def test_unknown_kind_and_non_ascii_are_rejected(self) -> None:
        with self.assertRaisesRegex(ControlNextActionError, "unsupported"):
            validate_control_next_action(
                {"kind": "forged_action"}, _disposed_science()
            )
        action, scientific = _fixtures()["record_research_intake"]
        action = deepcopy(action)
        action["mission_id"] = "MIS-\ud55c\uae00"
        with self.assertRaisesRegex(ControlNextActionError, "ASCII"):
            validate_control_next_action(action, scientific)

    def test_complex_required_fields_are_not_optional(self) -> None:
        removals = {
            "await_external_change": "resume_condition_id",
            "complete_runtime_source_ineligibility": "source_state_record_id",
            "record_axis_reopen_authority": "evidence_scope_overlay_ids",
            "record_portfolio_snapshot": "target_axis_identity",
            "record_source_eligibility": "resume_next_action",
            "resolve_candidate_engineering_gap": "successor_scope",
            "resolve_historical_replay_obligations": "resume_next_action",
        }
        fixtures = _fixtures()
        for kind, field in removals.items():
            with self.subTest(kind=kind, field=field):
                action, scientific = fixtures[kind]
                action = deepcopy(action)
                action.pop(field)
                with self.assertRaisesRegex(
                    ControlNextActionError, "schema is not exact"
                ):
                    validate_control_next_action(action, scientific)

    def test_identity_prefix_and_digest_mutations_are_rejected(self) -> None:
        cases = (
            ("resume_job", "job_id", "job:not-a-digest"),
            ("portfolio_decision", "portfolio_snapshot_id", "decision:" + D0),
            ("record_axis_reopen_authority", "decision_id", "decision:" + D0[:-1]),
            ("plan_candidate_bound_evidence", "executable_id", "candidate:" + D0),
            ("await_external_change", "resume_condition_id", D0),
        )
        fixtures = _fixtures()
        for kind, field, replacement in cases:
            with self.subTest(kind=kind, field=field):
                action, scientific = fixtures[kind]
                action = deepcopy(action)
                action[field] = replacement
                with self.assertRaises(ControlNextActionError):
                    validate_control_next_action(action, scientific)

    def test_set_semantic_lists_reject_unsorted_and_duplicate_values(self) -> None:
        cases = (
            (
                "choose_next_initiative_or_terminal",
                "pending_replay_obligation_ids",
                [REPLAY_1, REPLAY_0],
            ),
            (
                "execute_portfolio_decision",
                "replay_obligation_ids",
                [REPLAY_1, REPLAY_0],
            ),
            (
                "record_portfolio_snapshot",
                "required_followup_layers",
                ["execution", "data_source"],
            ),
            (
                "record_axis_reopen_authority",
                "evidence_scope_overlay_ids",
                [
                    "historical-evidence-scope:" + D1,
                    "historical-evidence-scope:" + D0,
                ],
            ),
        )
        fixtures = _fixtures()
        for kind, field, values in cases:
            with self.subTest(kind=kind, field=field, mutation="unsorted"):
                action, scientific = fixtures[kind]
                action = deepcopy(action)
                action[field] = values
                with self.assertRaisesRegex(ControlNextActionError, "sorted"):
                    validate_control_next_action(action, scientific)
            with self.subTest(kind=kind, field=field, mutation="duplicate"):
                action, scientific = fixtures[kind]
                action = deepcopy(action)
                action[field] = [values[0], values[0]]
                with self.assertRaisesRegex(ControlNextActionError, "duplicates"):
                    validate_control_next_action(action, scientific)

    def test_ordered_external_histories_still_reject_duplicates(self) -> None:
        for kind, field in (
            ("declare_external_dependency_job", "prior_completion_record_ids"),
            ("record_external_blocker", "completion_record_ids"),
        ):
            with self.subTest(kind=kind):
                action, scientific = _fixtures()[kind]
                action = deepcopy(action)
                action[field] = [D0, D0]
                with self.assertRaisesRegex(ControlNextActionError, "duplicates"):
                    validate_control_next_action(action, scientific)

    def test_all_nested_resume_actions_fail_closed(self) -> None:
        cases = (
            ("await_external_change", "mission_resume_next_action"),
            ("record_source_eligibility", "resume_next_action"),
            ("resolve_historical_replay_obligations", "resume_next_action"),
        )
        for kind, field in cases:
            with self.subTest(kind=kind):
                action, scientific = _fixtures()[kind]
                action = deepcopy(action)
                action[field]["forged_extra"] = "bypass"
                with self.assertRaisesRegex(
                    ControlNextActionError, "schema is not exact"
                ):
                    validate_control_next_action(action, scientific)

    def test_active_job_repair_holdout_and_release_are_cross_bound(self) -> None:
        cases = (
            ("resume_job", "job_id", "job:" + D1),
            ("execute_repair", "repair_id", "repair:" + D1),
            ("record_holdout_evaluation", "holdout_id", NEXT_HOLDOUT),
            ("issue_release_permit", "release_id", "REL-FORGED"),
        )
        for kind, field, replacement in cases:
            with self.subTest(kind=kind):
                action, scientific = _fixtures()[kind]
                action = deepcopy(action)
                action[field] = replacement
                with self.assertRaises(ControlNextActionError):
                    validate_control_next_action(action, scientific)

    def test_architecture_review_constraint_is_an_exact_group(self) -> None:
        action = {
            "architecture_review_id": "architecture-review:" + D0,
            "constraint_source_id": "architecture-review:" + D0,
            "excluded_architecture_family": "architecture-family:" + D0,
            "kind": "portfolio_decision",
            "portfolio_snapshot_id": PORTFOLIO,
        }
        scientific = _science(active_study=None)
        validate_control_next_action(action, scientific)
        implicit_source = deepcopy(action)
        implicit_source.pop("constraint_source_id")
        validate_control_next_action(implicit_source, scientific)
        missing_exclusion = deepcopy(action)
        missing_exclusion.pop("excluded_architecture_family")
        with self.assertRaises(ControlNextActionError):
            validate_control_next_action(missing_exclusion, scientific)
        mismatched_source = deepcopy(action)
        mismatched_source["constraint_source_id"] = "architecture-review:" + D1
        with self.assertRaises(ControlNextActionError):
            validate_control_next_action(mismatched_source, scientific)

    def test_bounded_architecture_continuation_is_closed_and_mode_specific(
        self,
    ) -> None:
        common = {
            "architecture_review_id": "architecture-review:" + D0,
            "architecture_review_trigger_id": D1,
            "constraint_source_id": "architecture-review:" + D0,
            "covered_diagnosis_ids": ["diagnosis:" + D0, "diagnosis:" + D1],
            "kind": "portfolio_decision",
            "portfolio_snapshot_id": PORTFOLIO,
            "required_architecture_family": "architecture-family:" + D0,
        }
        existing = {
            **common,
            "architecture_continuation_mode": "existing_axis",
            "required_target_axis_identity": AXIS,
            "required_target_axis_ids": ["axis-next-action"],
        }
        validate_control_next_action(existing, _science(active_study=None))
        new_mechanism = {
            **common,
            "architecture_continuation_mode": "new_mechanism",
            "required_followup_layers": ["model"],
        }
        validate_control_next_action(new_mechanism, _science(active_study=None))
        materialized = {
            **new_mechanism,
            "required_target_axis_ids": ["axis-materialized"],
        }
        validate_control_next_action(materialized, _science(active_study=None))
        for malformed in (
            {key: value for key, value in existing.items() if key != "covered_diagnosis_ids"},
            {**existing, "required_followup_layers": ["model"]},
            {**new_mechanism, "required_target_axis_identity": AXIS},
            {**new_mechanism, "free_form_override": "bypass"},
        ):
            with self.subTest(malformed=malformed):
                with self.assertRaises(ControlNextActionError):
                    validate_control_next_action(
                        malformed,
                        _science(active_study=None),
                    )

    def test_null_portfolio_snapshot_is_confined_to_engineering_fixture(self) -> None:
        action = {"kind": "portfolio_decision", "portfolio_snapshot_id": None}
        scientific = _science(active_study=None)
        validate_control_next_action(
            action,
            scientific,
            engineering_fixture=True,
        )
        with self.assertRaises(ControlNextActionError):
            validate_control_next_action(action, scientific)

    def test_checkpoint_bound_diagnosis_accepts_int_but_rejects_bool(self) -> None:
        action = {
            "kind": "diagnose_study",
            "study_close_event_id": D0,
            "study_close_revision": 1,
            "study_id": STUDY,
        }
        scientific = _science(active_study=None)
        validate_control_next_action(action, scientific)
        fixture_scientific = _disposed_science()
        validate_control_next_action(
            action,
            fixture_scientific,
            engineering_fixture=True,
        )
        validate_control_next_action(action, fixture_scientific)
        for invalid in (True, False, 0, -1):
            with self.subTest(invalid=invalid):
                malformed = deepcopy(action)
                malformed["study_close_revision"] = invalid
                with self.assertRaises(ControlNextActionError):
                    validate_control_next_action(malformed, scientific)

    def test_active_job_and_batch_hash_bindings_reject_coherent_id_edits(
        self,
    ) -> None:
        job_control: dict[str, object] | None = None
        batch_control: dict[str, object] | None = None
        for path in sorted(
            (REPOSITORY_ROOT / "records" / "journal").glob("journal-*.jsonl")
        ):
            with path.open("r", encoding="ascii") as stream:
                for line in stream:
                    event = json.loads(line)
                    scientific = event["control"]["scientific"]
                    if (
                        job_control is None
                        and isinstance(scientific.get("active_job"), dict)
                        and scientific["active_job"].get("status") == "declared"
                    ):
                        job_control = self._assemble_event_control(event)
                    if (
                        batch_control is None
                        and event["control"]["next_action"].get("kind")
                        == "declare_job"
                    ):
                        batch_control = self._assemble_event_control(event)
                    if job_control is not None and batch_control is not None:
                        break
            if job_control is not None and batch_control is not None:
                break
        assert job_control is not None and batch_control is not None

        forged_job_id = "job:" + D1
        job_scientific = job_control["scientific"]
        assert isinstance(job_scientific, dict)
        active_job = job_scientific["active_job"]
        assert isinstance(active_job, dict)
        active_job["id"] = forged_job_id
        action = job_control["next_action"]
        assert isinstance(action, dict)
        action["job_id"] = forged_job_id
        authorizations = job_control["authorizations"]
        assert isinstance(authorizations, dict)
        job_key = next(key for key in authorizations if key.startswith("Job:"))
        authorization = authorizations.pop(job_key)
        authorization["subject_id"] = forged_job_id
        authorizations[f"Job:{forged_job_id}"] = authorization
        job_control["control_hash"] = control_hash(job_control)
        with self.assertRaisesRegex(ControlStateError, "active Job projection"):
            validate_control(job_control)

        batch_scientific = batch_control["scientific"]
        assert isinstance(batch_scientific, dict)
        active_batch = batch_scientific["active_batch"]
        assert isinstance(active_batch, dict)
        active_batch["id"] = "batch:" + D1
        batch_action = batch_control["next_action"]
        assert isinstance(batch_action, dict)
        batch_action["batch_id"] = "batch:" + D1
        batch_control["control_hash"] = control_hash(batch_control)
        with self.assertRaisesRegex(ControlStateError, "active Batch projection"):
            validate_control(batch_control)

    def test_active_job_authorization_hash_is_recomputed(self) -> None:
        control: dict[str, object] | None = None
        for path in sorted(
            (REPOSITORY_ROOT / "records" / "journal").glob("journal-*.jsonl")
        ):
            with path.open("r", encoding="ascii") as stream:
                for line in stream:
                    event = json.loads(line)
                    active_job = event["control"]["scientific"].get(
                        "active_job"
                    )
                    if isinstance(active_job, dict):
                        control = self._assemble_event_control(event)
                        break
            if control is not None:
                break
        assert control is not None
        authorizations = control["authorizations"]
        assert isinstance(authorizations, dict)
        job_authorization = next(
            value
            for key, value in authorizations.items()
            if key.startswith("Job:")
        )
        job_authorization["authorization_hash"] = D2
        control["control_hash"] = control_hash(control)
        with self.assertRaisesRegex(ControlStateError, "not self-consistent"):
            validate_control(control)

    @staticmethod
    def _assemble_event_control(event: dict[str, object]) -> dict[str, object]:
        control = deepcopy(event["control"])
        control["revision"] = event["sequence"]
        control["heads"] = {
            "index": {
                "required_projection_digest": event[
                    "index_projection_digest"
                ],
                "required_record_count": event["index_record_count"],
                "required_sequence": event["sequence"],
            },
            "journal": {
                "event_id": event["event_id"],
                "sequence": event["sequence"],
            },
        }
        control["control_hash"] = control_hash(control)
        return control

    def test_all_journal_snapshots_preserve_exact_validation_parity(self) -> None:
        event_count = 0
        valid_count = 0
        failures: dict[str, int] = {}
        key_shapes: set[tuple[str, tuple[str, ...]]] = set()
        for path in sorted(
            (REPOSITORY_ROOT / "records" / "journal").glob("journal-*.jsonl")
        ):
            with path.open("r", encoding="ascii") as stream:
                for line in stream:
                    event = json.loads(line)
                    control = dict(event["control"])
                    action = control["next_action"]
                    key_shapes.add(
                        (action["kind"], tuple(sorted(action)))
                    )
                    control["revision"] = event["sequence"]
                    control["heads"] = {
                        "index": {
                            "required_projection_digest": event[
                                "index_projection_digest"
                            ],
                            "required_record_count": event[
                                "index_record_count"
                            ],
                            "required_sequence": event["sequence"],
                        },
                        "journal": {
                            "event_id": event["event_id"],
                            "sequence": event["sequence"],
                        },
                    }
                    control["control_hash"] = control_hash(control)
                    event_count += 1
                    try:
                        validate_control(control)
                    except ControlStateError as exc:
                        failures[str(exc)] = failures.get(str(exc), 0) + 1
                    else:
                        valid_count += 1

        self.assertEqual(event_count, 5_333)
        self.assertEqual(valid_count, 5_316)
        self.assertEqual(len(key_shapes), 34)
        self.assertEqual(
            failures,
            {"active Repair projection is invalid": 17},
        )


if __name__ == "__main__":
    unittest.main()
