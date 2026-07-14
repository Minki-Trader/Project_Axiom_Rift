from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.apply_project_goal_audit_v1 import (
    CORRECTION_OPERATION_PREFIX,
    EXPECTED_LEGACY_SCIENTIFIC_COMPLETIONS,
    EXPECTED_PORTFOLIO_SNAPSHOT_ID,
    read_frozen_audit_report,
)
from scripts.run_project_goal_audit_v1_forest_study import (
    ALL_STEPS,
    AXIS_ID,
    DIAGNOSE_STEPS,
    MISSION_ID,
    OPERATION_PREFIX,
    ROOT,
    STUDY_CLOSE_STEPS,
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
)
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.implementation_closure import (
    require_job_implementation_closure,
)
from axiom_rift.research.validation_v2 import ScientificAdjudicationValidatorV2


class ProjectGoalAuditForestStudyTests(unittest.TestCase):
    def test_operation_plan_has_one_disjoint_strict_stage_split(self) -> None:
        operation_ids = tuple(step.operation_id for step in ALL_STEPS)
        self.assertEqual(len(STUDY_CLOSE_STEPS), 16)
        self.assertEqual(len(DIAGNOSE_STEPS), 4)
        self.assertEqual(len(operation_ids), len(set(operation_ids)))
        self.assertTrue(all(value.startswith(OPERATION_PREFIX) for value in operation_ids))
        self.assertFalse(OPERATION_PREFIX.startswith(CORRECTION_OPERATION_PREFIX))
        self.assertEqual(STUDY_CLOSE_STEPS[-1].event_kind, "study_closed")
        self.assertEqual(DIAGNOSE_STEPS[0].event_kind, "study_diagnosis_recorded")

    def test_read_only_design_retains_every_axis_and_binds_frozen_report(self) -> None:
        writer = StateWriter(
            ROOT,
            validation_registry=EvidenceValidatorRegistry(
                (ScientificAdjudicationValidatorV2(),)
            ),
        )
        _, report_hash = read_frozen_audit_report(ROOT)
        design = build_forest_study_design(
            writer,
            report_hash=report_hash,
            base_snapshot_id=EXPECTED_PORTFOLIO_SNAPSHOT_ID,
            bootstrap_samples=199,
            block_lengths=(2, 5),
            base_seed=991,
        )

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

    def test_job_spec_closes_the_exact_component_implementation_bundle(self) -> None:
        project_writer = StateWriter(
            ROOT,
            validation_registry=EvidenceValidatorRegistry(
                (ScientificAdjudicationValidatorV2(),)
            ),
        )
        _, report_hash = read_frozen_audit_report(ROOT)
        design = build_forest_study_design(
            project_writer,
            report_hash=report_hash,
            base_snapshot_id=EXPECTED_PORTFOLIO_SNAPSHOT_ID,
            bootstrap_samples=199,
            block_lengths=(2, 5),
            base_seed=991,
        )

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
                {expected}
                | {
                    sha256(path.read_bytes()).hexdigest()
                    for path in forest_replay_dependency_paths()
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
                (expected,),
            )
            component_bytes = writer.evidence.read_verified(expected)
            self.assertEqual(component_bytes, forest_replay_implementation_artifact())
            self.assertEqual(sha256(component_bytes).hexdigest(), expected)


if __name__ == "__main__":
    unittest.main()
