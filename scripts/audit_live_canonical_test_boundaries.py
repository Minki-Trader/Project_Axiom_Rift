"""Run current canonical-state checks excluded from default pytest.

Default tests use deterministic fixtures.  This explicit maintenance command
reads the live control, Journal, projection, and evidence cache to confirm that
the current repository surface still satisfies the historical correction
invariants.  Importing this module performs no check and no mutation.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for import_root in (ROOT, SRC):
    value = str(import_root)
    if value not in sys.path:
        sys.path.insert(0, value)

from tests.operations import test_project_goal_audit_v2_orchestrator as audit_v2
from scripts.apply_project_goal_audit_v1 import (
    EXPECTED_LEGACY_SCIENTIFIC_COMPLETIONS,
    EXPECTED_PORTFOLIO_SNAPSHOT_ID,
    read_frozen_audit_report,
)
from scripts.run_project_goal_audit_v1_forest_study import (
    AXIS_ID,
    MISSION_ID,
    _job_spec,
    build_forest_study_design,
)
from axiom_rift.core.canonical import parse_canonical
from axiom_rift.operations.validation import EvidenceValidatorRegistry
from axiom_rift.operations.writer import StateWriter
from axiom_rift.research.forest_replay import (
    forest_replay_dependency_paths,
    forest_replay_implementation_artifact,
    forest_replay_implementation_identity,
    forest_replay_source_closure_artifact,
    forest_replay_source_dependency_paths,
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.implementation_closure import (
    require_job_implementation_closure,
)
from axiom_rift.research.validation_v2 import ScientificAdjudicationValidatorV2


def _forest_design():
    writer = StateWriter(
        ROOT,
        validation_registry=EvidenceValidatorRegistry(
            (ScientificAdjudicationValidatorV2(),)
        ),
    )
    _, report_hash = read_frozen_audit_report(ROOT)
    return report_hash, build_forest_study_design(
        writer,
        report_hash=report_hash,
        base_snapshot_id=EXPECTED_PORTFOLIO_SNAPSHOT_ID,
        bootstrap_samples=199,
        block_lengths=(2, 5),
        base_seed=991,
    )


class ProjectGoalAuditForestCanonicalMaintenanceTests(unittest.TestCase):
    def test_read_only_design_retains_every_axis_and_binds_frozen_report(
        self,
    ) -> None:
        report_hash, design = _forest_design()
        prior = {axis.axis_id: axis for axis in design.prior_axes}
        expanded = {axis.axis_id: axis for axis in design.expanded_snapshot.axes}
        self.assertEqual(set(expanded), {*prior, AXIS_ID})
        for axis_id, axis in prior.items():
            self.assertEqual(expanded[axis_id].identity, axis.identity)
            self.assertEqual(expanded[axis_id].status, axis.status)
        self.assertEqual(design.replay_plan.mission_id, MISSION_ID)
        self.assertEqual(
            design.replay_plan.historical_context.context_id,
            f"audit-report-sha256:{report_hash}",
        )
        self.assertEqual(
            design.replay_plan.historical_context.prior_global_exposure_count,
            EXPECTED_LEGACY_SCIENTIFIC_COMPLETIONS,
        )
        self.assertEqual(
            design.audit_axis.changed_domains,
            (ResearchLayer.SYNTHESIS,),
        )
        self.assertEqual(design.batch_spec.max_trials, 1)
        self.assertEqual(
            design.work_decision.baseline_executable.identity,
            design.replay_plan.baseline_executable.identity,
        )
        classes = design.replay_plan.output_classes()
        self.assertEqual(
            sum(value == "durable_evidence" for value in classes.values()),
            5,
        )
        self.assertEqual(
            sum(value == "reproducible_cache" for value in classes.values()),
            9,
        )

    def test_job_spec_closes_the_exact_component_implementation_bundle(
        self,
    ) -> None:
        _, design = _forest_design()
        with TemporaryDirectory() as temporary:
            writer = StateWriter(
                Path(temporary),
                engineering_fixture=True,
                foundation_root=ROOT,
            )
            spec = _job_spec(writer, design)
            manifest = parse_canonical(
                writer.evidence.read_verified(spec["implementation_identity"])
            )
            expected = forest_replay_implementation_identity().rsplit(":", 1)[-1]
            self.assertEqual(
                set(manifest["artifact_hashes"]),
                {
                    expected,
                    sha256(forest_replay_source_closure_artifact()).hexdigest(),
                }
                | {
                    sha256(path.read_bytes()).hexdigest()
                    for path in forest_replay_source_dependency_paths()
                },
            )
            self.assertEqual(
                require_job_implementation_closure(
                    executable_manifest=(
                        design.replay_plan.executable.to_identity_payload()
                    ),
                    job_artifact_hashes=manifest["artifact_hashes"],
                    artifact_reader=writer.evidence.read_verified,
                ),
                tuple(
                    sorted(
                        {expected}
                        | {
                            sha256(path.read_bytes()).hexdigest()
                            for path in forest_replay_dependency_paths()
                        }
                    )
                ),
            )
            component_bytes = writer.evidence.read_verified(expected)
            self.assertEqual(
                component_bytes,
                forest_replay_implementation_artifact(),
            )
            self.assertEqual(sha256(component_bytes).hexdigest(), expected)


class ProjectGoalAuditV2CanonicalMaintenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = audit_v2.load_script()

    def test_frozen_report_and_pure_authority_transforms_are_exact(self) -> None:
        writer = self.module.StateWriter(ROOT)
        materialized = {
            relative: writer.evidence.read_verified(expected_hash)
            for relative, expected_hash in self.module.EXPECTED_AUTHORITY_SHA256.items()
        }
        current_before = {
            relative: (ROOT / relative).read_bytes()
            for relative in self.module.EXPECTED_AUTHORITY_SHA256
        }
        report, digest = self.module.read_frozen_audit_report(ROOT)
        addendum, addendum_digest = self.module.read_frozen_integration_addendum(ROOT)

        self.assertEqual(
            {
                relative: self.module.sha256(content).hexdigest()
                for relative, content in materialized.items()
            },
            self.module.EXPECTED_AUTHORITY_SHA256,
        )
        frozen_basis = audit_v2.derive_pre_v2_basis(self.module, materialized)
        self.assertEqual(
            {
                relative: self.module.sha256(content.encode("ascii")).hexdigest()
                for relative, content in frozen_basis.items()
            },
            self.module.EXPECTED_PRE_V2_AUTHORITY_SHA256,
        )
        replacements = self.module._transform_authority_basis(frozen_basis)
        self.assertEqual(digest, self.module.EXPECTED_REPORT_SHA256)
        self.assertEqual(len(report), self.module.EXPECTED_REPORT_SIZE)
        self.assertEqual(addendum_digest, self.module.EXPECTED_ADDENDUM_SHA256)
        self.assertEqual(len(addendum), self.module.EXPECTED_ADDENDUM_SIZE)
        self.assertIn(self.module.EXPECTED_REPORT_SHA256.encode("ascii"), addendum)
        self.assertEqual(
            {
                relative: self.module.sha256(content).hexdigest()
                for relative, content in replacements.items()
            },
            self.module.EXPECTED_AUTHORITY_SHA256,
        )
        self.assertEqual(
            current_before,
            {
                relative: (ROOT / relative).read_bytes()
                for relative in self.module.EXPECTED_AUTHORITY_SHA256
            },
        )
        self.assertNotIn("OD-AUD-019", frozen_basis["OPERATING_DIRECTION.md"])
        self.assertIn(b"OD-AUD-033", replacements["OPERATING_DIRECTION.md"])

    def test_read_only_plan_binds_exact_replay_family_without_state_change(self) -> None:
        registry = self.module.EvidenceValidatorRegistry(
            (self.module.ScientificAdjudicationValidatorV2(),)
        )
        writer = self.module.StateWriter(ROOT, validation_registry=registry)
        control_before = (ROOT / "state/control.json").read_bytes()
        prefix = self.module.inspect_correction_prefix(writer)
        self.assertEqual(
            self.module.validate_correction_progress(writer, prefix=prefix),
            prefix,
        )
        if prefix < len(self.module.correction_steps()):
            plan = (
                self.module.build_correction_plan(writer, root=ROOT)
                if prefix == 0
                else self.module.build_resume_plan(writer, root=ROOT)
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
                root=ROOT,
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
                (ROOT / self.module.CHECKPOINT_PATH).read_bytes()
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
                        root=ROOT,
                    )
            else:
                self.module.require_activation_ready(
                    writer,
                    prefix=prefix,
                    root=ROOT,
                )
        self.assertEqual((ROOT / "state/control.json").read_bytes(), control_before)

    def test_completed_validation_does_not_require_reproducible_cache_presence(
        self,
    ) -> None:
        registry = self.module.EvidenceValidatorRegistry(
            (self.module.ScientificAdjudicationValidatorV2(),)
        )
        writer = self.module.StateWriter(ROOT, validation_registry=registry)
        self.assertEqual(
            self.module.inspect_correction_prefix(writer),
            len(self.module.correction_steps()),
        )
        cache_error = AssertionError("reproducible local cache was consulted")
        with patch.object(
            writer.evidence,
            "verify",
            side_effect=cache_error,
        ), patch.object(
            writer.evidence,
            "read_verified",
            side_effect=cache_error,
        ):
            completed = self.module.validate_completed_correction_ancestor(
                writer,
                root=ROOT,
            )
        self.assertEqual(completed["p0_satisfied_count"], 6)
        self.assertEqual(completed["p1_pending_count"], 7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
