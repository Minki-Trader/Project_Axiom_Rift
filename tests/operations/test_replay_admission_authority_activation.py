from __future__ import annotations

import importlib.util
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/apply_replay_admission_recertification_authority.py"


def load_script():
    spec = importlib.util.spec_from_file_location(
        "replay_admission_authority_activation_tested",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ReplayAdmissionAuthorityActivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_script()

    def authority_files(self):
        module = self.module
        return tuple(
            module.AuthorityFileBinding(
                path=path,
                predecessor_sha256=hashes[0],
                prospective_sha256=hashes[1],
            )
            for path, hashes in sorted(
                module.EXPECTED_CHANGED_AUTHORITY_HASHES.items()
            )
        )

    def prospective_blob_patch(self):
        module = self.module
        original = module._git_blob
        prospective_paths = {
            *module.EXPECTED_CHANGED_AUTHORITY_HASHES,
            module.AUDIT_REPORT_PATH,
        }

        def blob(reference: str, relative: str) -> bytes:
            if reference == "HEAD" and relative in prospective_paths:
                return (ROOT / relative).read_bytes()
            return original(reference, relative)

        return patch.object(module, "_git_blob", side_effect=blob)

    @classmethod
    def require_shadow_fixture(cls):
        if hasattr(cls, "shadow_material"):
            return
        module = cls.module
        original = module._git_blob
        prospective_paths = {
            *module.EXPECTED_CHANGED_AUTHORITY_HASHES,
            module.AUDIT_REPORT_PATH,
        }

        def blob(reference: str, relative: str) -> bytes:
            if reference == "HEAD" and relative in prospective_paths:
                return (ROOT / relative).read_bytes()
            return original(reference, relative)

        cls.shadow_blob_patcher = patch.object(
            module,
            "_git_blob",
            side_effect=blob,
        )
        cls.shadow_blob_patcher.start()
        cls.addClassCleanup(cls.shadow_blob_patcher.stop)
        timestamp_one = "2026-07-17T12:00:00.000001Z"
        timestamp_two = "2026-07-17T12:00:00.000002Z"
        journal_events = module._read_journal()
        with module._prepared_replay(journal_events) as (
            material,
            replay,
            existing_suffix,
        ):
            if existing_suffix:
                raise AssertionError("canonical activation fixture is not pristine")
            journal_path = (
                replay.writer.root / material.core.baseline.journal_path
            )
            before_size = journal_path.stat().st_size
            before_hash = module.sha256(journal_path.read_bytes()).hexdigest()
            with cls._assert_raises_static(Exception):
                with replay.writer.journal.expect_next_event({}):
                    module._invoke_at(
                        replay.writer,
                        timestamp_one,
                        lambda: module._apply_action(
                            replay.writer,
                            material,
                            1,
                        ),
                    )
            cls.preappend_unchanged = (
                journal_path.stat().st_size == before_size
                and module.sha256(journal_path.read_bytes()).hexdigest()
                == before_hash
            )
            first = replay.preview_next(timestamp_one)
            replay.accept_next(first)
            second = replay.preview_next(timestamp_two)
            replay.accept_next(second)
            receipts = tuple(replay.receipts)
        cls.shadow_material = material
        cls.shadow_first = first
        cls.shadow_second = second
        cls.shadow_receipts = receipts

    @staticmethod
    def _assert_raises_static(exception_type):
        return unittest.TestCase().assertRaises(exception_type)

    def material(self):
        module = self.module
        activation = module.ResearchProtocolActivation(
            protocol=module.ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
            validator_id=module.SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
            authority_manifest_digest=(
                module.EXPECTED_PROSPECTIVE_AUTHORITY_DIGEST
            ),
            audit_artifact_hash="a" * 64,
        )
        events = (
            SimpleNamespace(
                operation_id="operation-one",
                event_kind="authority_migrated",
                subject="Authority:active",
            ),
            SimpleNamespace(
                operation_id="operation-two",
                event_kind="research_protocol_activated",
                subject="ProjectGoal:OPERATING_DIRECTION.md",
            ),
        )
        core = SimpleNamespace(
            authority_replacements=self.authority_files(),
            baseline=SimpleNamespace(
                index_projection_digest="5" * 64,
                index_record_count=0,
                journal_event_id="6" * 64,
                journal_size_bytes=0,
                journal_start_offset=0,
            ),
            events=events,
        )
        return module.ActivationMaterial(
            core=core,
            report_bytes=b"report",
            activation=activation,
            migration_payload=module._migration_payload(self.authority_files()),
            prior_protocol_record_id="research-protocol:" + "b" * 64,
            protocol_ordinal=14,
            non_authority_control_sha256="c" * 64,
            scientific_inventory=dict(module.EXPECTED_SCIENTIFIC_INVENTORY),
            study_close_delivery_observation=(
                module.StudyCloseDeliveryObservation(
                    checkpoint_commit="1" * 40,
                    checkpoint_digest="2" * 64,
                    main_head="3" * 40,
                    remote_commit="4" * 40,
                )
            ),
        )

    def test_frozen_authority_transition_is_exactly_two_changed_contracts(self):
        module = self.module
        self.assertEqual(
            set(module.EXPECTED_CHANGED_AUTHORITY_HASHES),
            {"contracts/operations.yaml", "contracts/science.yaml"},
        )
        payload = module._migration_payload(self.authority_files())
        self.assertEqual(payload["old_manifest_digest"], module.EXPECTED_PREDECESSOR_AUTHORITY_DIGEST)
        self.assertEqual(payload["new_manifest_digest"], module.EXPECTED_PROSPECTIVE_AUTHORITY_DIGEST)
        self.assertEqual(payload["trial_delta"], 0)
        self.assertEqual(payload["holdout_delta"], 0)
        self.assertEqual(payload["scientific_claim"], "none")
        self.assertEqual(
            [row["path"] for row in payload["replacements"]],
            ["contracts/operations.yaml", "contracts/science.yaml"],
        )

    def test_action_dispatch_uses_only_typed_writer_boundaries(self):
        module = self.module
        material = self.material()

        class Writer:
            def __init__(self):
                self.calls = []

            def migrate_authority(self, **kwargs):
                self.calls.append(("migration", kwargs))
                return "migration-result"

            def activate_research_protocol(self, **kwargs):
                self.calls.append(("protocol", kwargs))
                return "protocol-result"

        writer = Writer()
        with patch.object(
            module,
            "_git_blob",
            side_effect=lambda _ref, path: path.encode("ascii"),
        ):
            self.assertEqual(
                module._apply_action(writer, material, 1),
                "migration-result",
            )
        self.assertEqual(
            module._apply_action(writer, material, 2),
            "protocol-result",
        )
        self.assertEqual([name for name, _ in writer.calls], ["migration", "protocol"])
        migration = writer.calls[0][1]
        protocol = writer.calls[1][1]
        self.assertIs(migration["allow_active_stable_boundary"], True)
        self.assertEqual(migration["reason"], module.AUTHORITY_REASON)
        self.assertEqual(
            set(migration["replacements"]),
            {"contracts/operations.yaml", "contracts/science.yaml"},
        )
        self.assertIs(protocol["allow_active_stable_boundary"], True)
        self.assertIs(protocol["activation"], material.activation)

    def test_event_components_preserve_non_authority_control_and_zero_credit(self):
        module = self.module
        material = self.material()
        baseline = {
            "authority": {"manifest_digest": module.EXPECTED_PREDECESSOR_AUTHORITY_DIGEST},
            "engineering": {"harness_status": "ready"},
            "initiative": {"id": "INI-0001"},
            "scientific": {"active_mission": "MIS-0006", "claim": "none"},
            "next_action": dict(module.EXPECTED_NEXT_ACTION),
            "authorizations": {"Mission:MIS-0006": {}},
            "schema": "axiom_control",
            "revision": module.EXPECTED_BASELINE_REVISION,
            "heads": {},
            "control_hash": "d" * 64,
        }
        material = module.ActivationMaterial(
            core=material.core,
            report_bytes=material.report_bytes,
            activation=material.activation,
            migration_payload=material.migration_payload,
            prior_protocol_record_id=material.prior_protocol_record_id,
            protocol_ordinal=material.protocol_ordinal,
            non_authority_control_sha256=module._non_authority_control_sha256(baseline),
            scientific_inventory=material.scientific_inventory,
            study_close_delivery_observation=(
                material.study_close_delivery_observation
            ),
        )
        with patch.object(module, "_baseline_control_from_core", return_value=baseline):
            first = module._expected_event_components(material, 1)
            second = module._expected_event_components(material, 2)
        for control, _payload, result, semantic in (first, second):
            self.assertEqual(
                control["authority"]["manifest_digest"],
                module.EXPECTED_PROSPECTIVE_AUTHORITY_DIGEST,
            )
            self.assertEqual(
                module._non_authority_control_sha256(control),
                material.non_authority_control_sha256,
            )
            self.assertEqual(control["scientific"]["claim"], "none")
            self.assertNotIn("trial", semantic["kind"])
            if "trial_delta" in result:
                self.assertEqual(result["trial_delta"], 0)
        self.assertEqual(first[1]["trial_delta"], 0)
        self.assertEqual(first[1]["holdout_delta"], 0)
        self.assertEqual(second[3]["payload"]["scientific_trial_delta"], 0)

    def test_apply_rejects_git_boundary_before_evidence_publication(self):
        module = self.module
        material = self.material()
        core = material.core
        core.event_count = 2
        core.baseline = SimpleNamespace(authority_manifest_digest="a" * 64)
        boundary = Mock(side_effect=module.ContentAddressedCorrectionError("blocked"))
        evidence = Mock(side_effect=AssertionError("evidence must not open"))

        @contextmanager
        def prepared(_events):
            yield material, Mock(), ()

        with patch.object(module, "_SAFE_STARTUP", True), patch.object(
            module, "_prepared_replay", side_effect=prepared
        ), patch.object(module, "_read_journal", return_value=()), patch.object(
            module, "_current_control", return_value={}
        ), patch.object(
            module, "require_local_main_correction_boundary", boundary
        ), patch.object(module, "EvidenceStore", evidence):
            with self.assertRaisesRegex(
                module.ContentAddressedCorrectionError,
                "blocked",
            ):
                module.apply()
        boundary.assert_called_once()
        evidence.assert_not_called()

    def test_prepared_run_reuses_exactly_one_baseline_shadow(self):
        module = self.module
        material = self.material()
        shadow = Mock()
        artifact = SimpleNamespace(sha256="e" * 64)
        shadow.evidence.finalize.return_value = artifact
        shadow.evidence.read_verified.return_value = material.report_bytes
        entered = []

        @contextmanager
        def baseline(authority_files):
            entered.append(tuple(authority_files))
            yield shadow

        prior = (
            material.prior_protocol_record_id,
            material.protocol_ordinal - 1,
            dict(material.scientific_inventory),
        )
        with patch.object(module, "_durable_core", return_value=None), patch.object(
            module, "_head_control", return_value=(b"control", {})
        ), patch.object(
            module,
            "_authority_bindings",
            return_value=(self.authority_files(), {}),
        ), patch.object(module, "_baseline_shadow", side_effect=baseline), patch.object(
            module, "_prior_protocol_from_writer", return_value=prior
        ), patch.object(
            module, "_build_material", return_value=material
        ) as build, patch.object(
            module, "_require_execution_closure"
        ), patch.object(
            module, "_verify_suffix", return_value=()
        ) as verify:
            with module._prepared_replay(()) as prepared:
                self.assertIs(prepared[0], material)

        self.assertEqual(len(entered), 1)
        build.assert_called_once_with(prior_protocol=prior)
        self.assertIs(verify.call_args.kwargs["replay"].writer, shadow)

    def test_recovery_arguments_bind_only_the_exact_trailing_event(self):
        module = self.module
        event = {
            "sequence": 5411,
            "event_id": "a" * 64,
            "operation_id": "operation",
            "previous_event_id": "b" * 64,
        }
        self.assertEqual(
            module._exact_recovery_arguments((event,)),
            {
                "expected_sequence": 5411,
                "expected_event_id": "a" * 64,
                "expected_operation_id": "operation",
                "expected_previous_event_id": "b" * 64,
            },
        )
        with self.assertRaisesRegex(
            module.ReplayAdmissionActivationError,
            "trailing event",
        ):
            module._exact_recovery_arguments(())

    def test_shadow_replay_proves_both_full_events_without_real_state_write(self):
        module = self.module
        self.require_shadow_fixture()
        control_before = (ROOT / "state/control.json").read_bytes()
        journal_before = (ROOT / "records/journal/journal-000002.jsonl").read_bytes()
        material = self.shadow_material
        first = self.shadow_first
        second = self.shadow_second
        self.assertEqual(first["occurred_at_utc"], "2026-07-17T12:00:00.000001Z")
        self.assertEqual(len(first["payload"]["evidence"]), 2)
        self.assertEqual(second["payload"]["evidence"], [])
        envelope = module.CorrectionReceiptEnvelope(
            core=material.core,
            event_receipts=self.shadow_receipts,
        )
        module.require_exact_correction_receipts(
            envelope,
            (first, second),
        )
        self.assertEqual((ROOT / "state/control.json").read_bytes(), control_before)
        self.assertEqual(
            (ROOT / "records/journal/journal-000002.jsonl").read_bytes(),
            journal_before,
        )

    def test_partial_prefix_replay_rejects_offset_and_projection_tampering(self):
        module = self.module
        self.require_shadow_fixture()
        material = self.shadow_material
        first = self.shadow_first
        cursor = module._IndependentCursor(
            journal_offset=(
                material.core.baseline.journal_start_offset
                + material.core.baseline.journal_size_bytes
            ),
            previous_event_id=material.core.baseline.journal_event_id,
            index_record_count=material.core.baseline.index_record_count,
            index_projection_digest=material.core.baseline.index_projection_digest,
        )
        module._validate_event_envelope(
            material,
            first,
            ordinal=1,
            cursor=cursor,
            occurred_at_utc=first["occurred_at_utc"],
        )
        for field, replacement in (
            ("journal_offset", first["journal_offset"] + 1),
            ("index_record_count", first["index_record_count"] + 1),
            ("index_projection_digest", "f" * 64),
        ):
            with self.subTest(field=field):
                tampered = json.loads(json.dumps(first))
                tampered[field] = replacement
                with self.assertRaisesRegex(
                    module.ReplayAdmissionActivationError,
                    "full independent envelope|projection",
                ):
                    module._validate_event_envelope(
                        material,
                        tampered,
                        ordinal=1,
                        cursor=cursor,
                        occurred_at_utc=first["occurred_at_utc"],
                    )

    def test_preappend_expectation_mismatch_leaves_shadow_journal_unchanged(self):
        self.require_shadow_fixture()
        self.assertIs(self.preappend_unchanged, True)

    def test_durable_core_reentry_preserves_canonical_authority_order(self):
        module = self.module
        self.require_shadow_fixture()
        material = self.shadow_material
        prior = (
            material.prior_protocol_record_id,
            material.protocol_ordinal - 1,
            dict(material.scientific_inventory),
        )
        rebuilt = module._material_from_core(
            material.core,
            prior_protocol=prior,
        )
        self.assertEqual(rebuilt.core, material.core)
        self.assertEqual(
            [item.path for item in rebuilt.core.authority_files],
            sorted(item.path for item in rebuilt.core.authority_files),
        )

    def test_unsafe_apply_is_rejected_before_project_imports(self):
        completed = subprocess.run(
            (sys.executable, str(SCRIPT), "--apply"),
            cwd=ROOT,
            check=False,
            capture_output=True,
            timeout=30,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn(b"python -I -S", completed.stderr)


if __name__ == "__main__":
    unittest.main()
