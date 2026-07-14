from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "apply_project_goal_audit_v2.py"


def load_script():
    spec = importlib.util.spec_from_file_location(
        "apply_project_goal_audit_v2_tested",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeIndex:
    records: dict[str, object] = {}

    def __init__(self, _path: object) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def records_by_kind(self, kind: str):
        return tuple(self.records.values()) if kind == "operation" else ()

    def get(self, kind: str, record_id: str):
        return self.records.get(record_id) if kind == "operation" else None


class FakeJournal:
    def __init__(self, events: dict[int, dict[str, object]]) -> None:
        self.events = events

    def read_event_at(
        self,
        *,
        offset: int,
        expected_sequence: int,
        expected_event_id: str,
    ):
        event = self.events[offset]
        if (
            event["sequence"] != expected_sequence
            or event["event_id"] != expected_event_id
        ):
            raise AssertionError("fake Journal binding differs")
        return event


class ProjectGoalAuditV2OrchestratorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_script()

    def test_frozen_report_and_pure_authority_transforms_are_exact(self) -> None:
        before = {
            relative: (REPO_ROOT / relative).read_bytes()
            for relative in self.module.EXPECTED_AUTHORITY_SHA256
        }
        report, digest = self.module.read_frozen_audit_report(REPO_ROOT)
        addendum, addendum_digest = (
            self.module.read_frozen_integration_addendum(REPO_ROOT)
        )
        evidence = self.module.StateWriter(REPO_ROOT).evidence
        frozen_basis = {}
        for relative, expected in (
            self.module.EXPECTED_PRE_V2_AUTHORITY_SHA256.items()
        ):
            # Foundation data joins the authority manifest in this migration,
            # so its predecessor bytes have no earlier authority artifact.
            content = (
                (REPO_ROOT / relative).read_bytes()
                if relative == "foundation/data.yaml"
                else evidence.read_verified(expected)
            )
            self.assertEqual(self.module.sha256(content).hexdigest(), expected)
            frozen_basis[relative] = content.decode("ascii")
        replacements = self.module._transform_authority_basis(frozen_basis)
        self.assertEqual(digest, self.module.EXPECTED_REPORT_SHA256)
        self.assertEqual(len(report), self.module.EXPECTED_REPORT_SIZE)
        self.assertEqual(addendum_digest, self.module.EXPECTED_ADDENDUM_SHA256)
        self.assertEqual(len(addendum), self.module.EXPECTED_ADDENDUM_SIZE)
        self.assertIn(
            self.module.EXPECTED_REPORT_SHA256.encode("ascii"),
            addendum,
        )
        self.assertEqual(
            {
                relative: self.module.sha256(content).hexdigest()
                for relative, content in replacements.items()
            },
            self.module.EXPECTED_AUTHORITY_SHA256,
        )
        self.assertEqual(
            before,
            {
                relative: (REPO_ROOT / relative).read_bytes()
                for relative in self.module.EXPECTED_AUTHORITY_SHA256
            },
        )
        self.assertNotIn(
            "OD-AUD-019",
            frozen_basis["OPERATING_DIRECTION.md"],
        )
        self.assertIn(b"OD-AUD-033", replacements["OPERATING_DIRECTION.md"])

    def test_read_only_plan_binds_exact_replay_family_without_state_change(self) -> None:
        registry = self.module.EvidenceValidatorRegistry(
            (self.module.ScientificAdjudicationValidatorV2(),)
        )
        writer = self.module.StateWriter(REPO_ROOT, validation_registry=registry)
        control_before = (REPO_ROOT / "state/control.json").read_bytes()
        writer.require_stable_head()
        prefix = self.module.inspect_correction_prefix(writer)
        self.assertEqual(
            self.module.validate_correction_progress(writer, prefix=prefix),
            prefix,
        )
        if prefix < len(self.module.correction_steps()):
            plan = (
                self.module.build_correction_plan(writer, root=REPO_ROOT)
                if prefix == 0
                else self.module.build_resume_plan(writer, root=REPO_ROOT)
            )
            self.assertEqual(len(plan.satisfactions), 6)
            self.assertEqual(
                tuple(item.obligation_id for item in plan.satisfactions),
                self.module.EXPECTED_P0_OBLIGATION_IDS,
            )
            self.assertEqual(
                tuple(plan.replay_plan["pending_after_apply"]),
                self.module.EXPECTED_P1_OBLIGATION_IDS,
            )
            self.assertEqual(
                plan.replay_plan["effective_scope_overlay"]["record_id"],
                self.module.EXPECTED_SCOPE_OVERLAY_ID,
            )
        else:
            completed = self.module.validate_completed_correction_ancestor(
                writer,
                root=REPO_ROOT,
            )
            self.assertEqual(completed["p0_satisfied_count"], 6)
            self.assertEqual(completed["p1_pending_count"], 7)
            self.assertEqual(
                completed["effective_scope_overlay_id"],
                self.module.EXPECTED_SCOPE_OVERLAY_ID,
            )
        self.assertIn(
            self.module.EXPECTED_STU0061_OBLIGATION_ID,
            self.module.EXPECTED_P1_OBLIGATION_IDS,
        )
        if prefix < len(self.module.correction_steps()):
            checkpoint = self.module.StudyCloseDeliveryCheckpoint.from_bytes(
                (REPO_ROOT / self.module.CHECKPOINT_PATH).read_bytes()
            )
            if checkpoint.schema != self.module.CHECKPOINT_SCHEMA:
                self.assertEqual(prefix, 0)
                with self.assertRaisesRegex(
                    RuntimeError,
                    "authenticated v2 checkpoint",
                ):
                    self.module.require_activation_ready(
                        writer,
                        prefix=prefix,
                        root=REPO_ROOT,
                    )
            else:
                self.module.require_activation_ready(
                    writer,
                    prefix=prefix,
                    root=REPO_ROOT,
                )
        self.assertEqual(
            (REPO_ROOT / "state/control.json").read_bytes(),
            control_before,
        )

    def test_strict_three_step_prefix_rejects_standalone_or_holes(self) -> None:
        steps = self.module.correction_steps()
        self.assertEqual(
            [step.event_kind for step in steps],
            [
                "authority_migrated",
                "research_protocol_activated",
                "historical_replay_correction_recorded",
            ],
        )

        def writer_for(positions: tuple[int, ...]):
            events: dict[int, dict[str, object]] = {}
            FakeIndex.records = {}
            previous = self.module.EXPECTED_INITIAL_EVENT_ID
            for position, step in enumerate(steps):
                sequence = self.module.EXPECTED_INITIAL_REVISION + position + 1
                event_id = f"event-{sequence}"
                if position in positions:
                    record = SimpleNamespace(
                        kind="operation",
                        record_id=step.operation_id,
                        status="success",
                        payload={"event_kind": step.event_kind},
                        authority_sequence=sequence,
                        authority_event_id=event_id,
                        authority_offset=sequence,
                    )
                    FakeIndex.records[step.operation_id] = record
                    events[sequence] = {
                        "event_id": event_id,
                        "event_kind": step.event_kind,
                        "operation_id": step.operation_id,
                        "previous_event_id": previous,
                        "sequence": sequence,
                    }
                previous = event_id
            return SimpleNamespace(
                index_path=Path("unused"),
                journal=FakeJournal(events),
            )

        with patch.object(self.module, "LocalIndex", FakeIndex):
            self.assertEqual(
                self.module.inspect_correction_prefix(writer_for((0, 1, 2))),
                3,
            )
            for positions in ((1,), (0, 2), (1, 2)):
                with self.subTest(positions=positions):
                    with self.assertRaisesRegex(RuntimeError, "strict prefix"):
                        self.module.inspect_correction_prefix(writer_for(positions))

    def test_apply_steps_use_only_typed_statewriter_boundaries(self) -> None:
        calls: list[tuple[str, object]] = []

        class FakeWriter:
            def migrate_authority(self, **kwargs):
                calls.append(("authority", kwargs))

            def read_control(self):
                return {"authority": {"manifest_digest": "b" * 64}}

            def activate_research_protocol(self, **kwargs):
                calls.append(("protocol", kwargs))

            def record_historical_replay_correction(self, **kwargs):
                calls.append(("replay", kwargs))

        plan = SimpleNamespace(
            authority_replacements={"OPERATING_DIRECTION.md": b"replacement"},
            report_hash=self.module.EXPECTED_REPORT_SHA256,
            addendum_hash=self.module.EXPECTED_ADDENDUM_SHA256,
            satisfactions=("typed-satisfaction",),
        )
        writer = FakeWriter()
        for position in range(3):
            self.module._apply_step(writer, plan=plan, step_index=position)
        self.assertEqual([name for name, _ in calls], ["authority", "protocol", "replay"])
        self.assertIs(calls[0][1]["allow_active_stable_boundary"], True)
        self.assertIs(calls[1][1]["allow_active_stable_boundary"], True)
        self.assertEqual(
            calls[1][1]["activation"].validator_id,
            self.module.EXPECTED_V2_VALIDATOR_ID,
        )
        self.assertEqual(
            calls[1][1]["activation"].audit_artifact_hash,
            self.module.EXPECTED_ADDENDUM_SHA256,
        )
        self.assertEqual(
            tuple(calls[2][1]["adjudication_record_ids"]),
            self.module.ADJUDICATION_RECORD_IDS,
        )

    def test_frozen_ancestor_identity_is_separate_from_current_apply_gate(self) -> None:
        self.assertEqual(
            self.module.ScientificAdjudicationValidatorV2.validator_id,
            self.module.EXPECTED_V2_VALIDATOR_ID,
        )
        control = {
            "authorizations": {"Mission:MIS-0006": {}},
            "next_action": dict(self.module.EXPECTED_INITIAL_ACTION),
            "scientific": {
                "active_batch": None,
                "active_executable": None,
                "active_holdout_evaluation": None,
                "active_initiative": None,
                "active_job": None,
                "active_lineage": None,
                "active_mission": "MIS-0006",
                "active_release": None,
                "active_repair": None,
                "active_study": None,
                "claim": "none",
                "holdout_reveals": 0,
                "required_future_holdout_id": None,
            },
        }
        event = {
            "control": control,
            "payload": {
                "audit_artifact_hash": self.module.EXPECTED_ADDENDUM_SHA256,
                "authority_manifest_digest": "a" * 64,
                "protocol": "scientific_adjudication_v2",
                "schema": "research_protocol_activation.v1",
                "validator_id": self.module.EXPECTED_V2_VALIDATOR_ID,
            },
            "index_records": [
                {"kind": "research-protocol-activation"},
                {"kind": "operation", "payload": {"result": {"trial_delta": 0}}},
            ],
        }
        drifted = "validator:" + "f" * 64
        with patch.object(
            self.module.ScientificAdjudicationValidatorV2,
            "validator_id",
            drifted,
        ):
            self.module._validate_protocol_event(
                event,
                authority_manifest_digest="a" * 64,
            )
            with self.assertRaisesRegex(RuntimeError, "current V2 validator differs"):
                self.module.require_current_validator_for_apply()
            with patch.object(
                self.module,
                "_read_v2_delivery_checkpoint",
                side_effect=AssertionError(
                    "completed ancestor read current checkpoint"
                ),
            ):
                self.module.require_activation_ready(
                    SimpleNamespace(),
                    prefix=len(self.module.correction_steps()),
                    root=REPO_ROOT,
                )

    def test_projection_recovery_is_explicit_opt_in(self) -> None:
        class RecoveringWriter:
            def __init__(self, *_args, **_kwargs) -> None:
                self.recover_calls = 0

            def require_stable_head(self):
                raise self_module.RecoveryRequired("test recovery")

            def recover(self):
                self.recover_calls += 1
                return {"recovered": True}

        self_module = self.module
        writer = RecoveringWriter()
        with self.assertRaises(self.module.RecoveryRequired):
            self.module.apply_corrections(
                root=REPO_ROOT,
                writer_factory=lambda *_args, **_kwargs: writer,
            )
        self.assertEqual(writer.recover_calls, 0)
        writer = RecoveringWriter()
        with patch.object(
            self.module,
            "require_v2_delivery_preflight",
        ), patch.object(
            self.module, "inspect_correction_prefix", return_value=3
        ), patch.object(
            self.module,
            "validate_completed_correction_ancestor",
            return_value={"boundary_revision": 4938},
        ):
            result = self.module.apply_corrections(
                root=REPO_ROOT,
                writer_factory=lambda *_args, **_kwargs: writer,
                explicit_recovery=True,
            )
        self.assertEqual(writer.recover_calls, 1)
        self.assertEqual(result["recovery"]["mode"], "explicit_recovery")

    def test_activation_readiness_fails_before_any_apply_step(self) -> None:
        class StableWriter:
            def require_stable_head(self):
                return {"stable": True}

        writer = StableWriter()
        with patch.object(
            self.module,
            "inspect_correction_prefix",
            return_value=0,
        ), patch.object(
            self.module,
            "validate_correction_progress",
        ), patch.object(
            self.module,
            "build_correction_plan",
            return_value=SimpleNamespace(),
        ), patch.object(
            self.module,
            "require_activation_ready",
            side_effect=RuntimeError("delivery not ready"),
        ) as readiness, patch.object(self.module, "_apply_step") as apply_step:
            with self.assertRaisesRegex(RuntimeError, "delivery not ready"):
                self.module.apply_corrections(
                    root=REPO_ROOT,
                    writer_factory=lambda *_args, **_kwargs: writer,
                )
        readiness.assert_called_once_with(
            writer,
            prefix=0,
            root=REPO_ROOT,
            allow_delivery_mutation=True,
        )
        apply_step.assert_not_called()

    def test_mutating_preflight_rejects_off_main_before_full_guard(self) -> None:
        class GuardWriter:
            guard_calls = 0

            def require_study_close_delivery_guard(self) -> None:
                self.guard_calls += 1

        writer = GuardWriter()
        checkpoint = SimpleNamespace(checkpoint_digest="a" * 64)
        with patch.object(
            self.module,
            "_read_v2_delivery_checkpoint",
            return_value=checkpoint,
        ), patch.object(
            self.module,
            "require_local_main",
            side_effect=self.module.StudyCloseDeliveryError("local main"),
        ):
            with self.assertRaisesRegex(RuntimeError, "checked-out local main"):
                self.module.require_v2_delivery_preflight(
                    writer,
                    root=REPO_ROOT,
                )
        self.assertEqual(writer.guard_calls, 0)

    def test_completed_boundary_accepts_only_a_legal_later_suffix(self) -> None:
        action = dict(self.module.EXPECTED_INITIAL_ACTION)
        action.update(
            {
                "pending_replay_obligation_ids": list(
                    self.module.EXPECTED_P1_OBLIGATION_IDS
                ),
                "required_replay_priority": "p1",
            }
        )
        boundary = self.module.EXPECTED_INITIAL_REVISION + 3
        event = {
            "sequence": boundary,
            "control": {
                "authorizations": {"Mission:MIS-0006": {}},
                "next_action": action,
                "scientific": {
                    "active_batch": None,
                    "active_executable": None,
                    "active_holdout_evaluation": None,
                    "active_initiative": None,
                    "active_job": None,
                    "active_lineage": None,
                    "active_mission": "MIS-0006",
                    "active_release": None,
                    "active_repair": None,
                    "active_study": None,
                    "claim": "none",
                    "holdout_reveals": 0,
                    "required_future_holdout_id": None,
                },
            },
        }
        for suffix in (0, 1, 100):
            current = {
                "revision": boundary + suffix,
                "heads": {"journal": {"sequence": boundary + suffix}},
            }
            self.assertEqual(
                self.module.validate_completed_correction_suffix_boundary(
                    current=current,
                    replay_event=event,
                ),
                suffix,
            )
        invalid = {
            "revision": boundary + 1,
            "heads": {"journal": {"sequence": boundary}},
        }
        with self.assertRaisesRegex(RuntimeError, "legal V2 correction suffix"):
            self.module.validate_completed_correction_suffix_boundary(
                current=invalid,
                replay_event=event,
            )


if __name__ == "__main__":
    unittest.main()
