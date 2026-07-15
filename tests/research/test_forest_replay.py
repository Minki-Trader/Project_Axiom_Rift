from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import (
    ExecutableSpec,
    parse_canonical_identity_bytes,
)
from axiom_rift.operations.validation import (
    EvidenceValidationError,
    EvidenceValidationRequest,
    EvidenceValidatorRegistry,
    ValidationArtifact,
)
from axiom_rift.operations.permits import (
    PermitAuthority,
    PermitKind,
    SubjectKind,
)
from axiom_rift.operations.study_close_delivery import StudyCloseGuardCapability
from axiom_rift.operations.writer import StateWriter, TransitionError
from axiom_rift.research.chassis import (
    ArchitectureChassisSpec,
    ArchitectureRole,
    component_domain,
    validate_controlled_executable,
)
from axiom_rift.research.discovery import OBSERVED_MATERIAL_ID
from axiom_rift.research.forest_replay import (
    AxisReplay,
    ForestReplayError,
    P0_AXIS_SPECS,
    P0_COMPOSITE_MEASUREMENT_OUTPUT,
    P0_COMPOSITE_PLAN_OUTPUT,
    P0_COMPOSITE_RESULT_OUTPUT,
    P0_COMPOSITE_SUPPORT_OUTPUT,
    P0_PNL_ATTRIBUTION,
    P0_REPLAY_CLAIMS,
    P0_REPLAY_EVIDENCE_MODES,
    P0_STATISTICAL_OUTPUT,
    build_p0_composite_validation_plan,
    build_p0_forest_bundle,
    forest_replay_dependency_paths,
    forest_replay_implementation_artifact,
    forest_replay_implementation_identity,
    forest_replay_implementation_manifest,
    forest_replay_source_closure_artifact,
    forest_replay_source_dependency_paths,
    p0_replay_family_inventory_hash,
)
from axiom_rift.research.governance import (
    MissionResearchIntake,
    REQUIRED_INTAKE_SURFACES,
    ResearchLayer,
)
from axiom_rift.research.evidence_proofs import (
    AUDIT_INTEGRITY_MODE,
    ScientificEvidenceProofError,
    TERMINAL_EVIDENCE_MODES,
    _validate_statistical_manifest,
)
from axiom_rift.research.portfolio import (
    BatchSpec,
    DecisionBasisRecord,
    DecisionLens,
    DecisionLensAssessment,
    DecisionLensPosition,
    DecisionOption,
    PortfolioAction,
    PortfolioAxis,
    PortfolioDecision,
    PortfolioDecisionError,
    PortfolioSnapshot,
    QuantTeamDecisionReview,
)
from axiom_rift.research.p0_replay_adapters import (
    forest_replay_adapter_dependency_paths,
)
from axiom_rift.research.protocol import (
    ResearchProtocol,
    ResearchProtocolActivation,
)
from axiom_rift.storage.index import LocalIndex
from axiom_rift.research.selection_inference import (
    HistoricalSearchContext,
    P0_REPLAY_EXECUTABLE_IDS,
    infer_p0_simultaneous_forest,
)
from axiom_rift.research.validation_v2 import (
    SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
    ScientificAdjudicationValidatorV2,
)


MISSION_ID = "MIS-P0-FOREST-TEST"
JOB_ID = "job:p0-forest-test"
JOB_HASH = "a" * 64
FIXED_NOW = "2026-07-14T00:00:00Z"
FIXED_EXPIRY = "2026-07-15T00:00:00Z"
HISTORICAL_CONTEXT = HistoricalSearchContext(
    context_id="history:p0-selected-after-470-test",
    prior_global_exposure_count=470,
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _finalize_forest_job_implementation(
    writer: StateWriter, *, callable_identity: str
) -> tuple[str, list[str]]:
    component_implementation = writer.evidence.finalize(
        forest_replay_implementation_artifact()
    )
    expected_component_hash = forest_replay_implementation_identity().rsplit(
        ":", 1
    )[-1]
    if component_implementation.sha256 != expected_component_hash:
        raise AssertionError("forest replay implementation artifact identity changed")
    source_hashes = sorted(
        {component_implementation.sha256}
        | {
            writer.evidence.finalize(path.read_bytes()).sha256
            for path in forest_replay_source_dependency_paths()
        }
        | {writer.evidence.finalize(forest_replay_source_closure_artifact()).sha256}
    )
    implementation = writer.evidence.finalize(
        canonical_bytes(
            {
                "artifact_hashes": source_hashes,
                "callable_identity": callable_identity,
                "protocol": "python.source.p0_composite_reanalysis.v1",
                "schema": "job_implementation_evidence.v1",
            }
        )
    )
    return implementation.sha256, source_hashes


def _metrics(net_profit_micropoints: int) -> dict[str, int]:
    return {
        "append_invariance_mismatch_count": 0,
        "causality_violation_count": 0,
        "entries_per_day_milli": 1_250,
        "evaluable_folds": 9,
        "median_fold_profit_factor_milli": 1_175,
        "monthly_realized_exit_drawdown_share_of_gross_profit_ppm": 800_000,
        "net_profit_micropoints": net_profit_micropoints,
        "nonfinite_metric_count": 0,
        "prefix_invariance_mismatch_count": 0,
        "stress_net_profit_micropoints": max(1, net_profit_micropoints // 2),
        "supported_positive_regime_count": 2,
        "top5_profit_day_share_ppm": 250_000,
        "trade_count": 150,
        "unknown_cost_unresolved_signal_count": 0,
        "winning_fold_count": 6,
    }


def _axes() -> tuple[AxisReplay, ...]:
    first = date(2022, 1, 1)
    axes: list[AxisReplay] = []
    for axis_index, spec in enumerate(P0_AXIS_SPECS):
        daily_pnl = tuple(
            (
                (first + timedelta(days=day_index)).isoformat(),
                400 + 25 * ((day_index + axis_index) % 7) - 30 * axis_index,
            )
            for day_index in range(42)
        )
        net = sum(value for _, value in daily_pnl)
        axes.append(
            AxisReplay(
                spec=spec,
                evaluation={
                    "evaluable": True,
                    "metrics": _metrics(net),
                    "subject_configuration_id": spec.configuration_id,
                    "subject_executable_id": spec.executable_id,
                },
                daily_pnl=daily_pnl,
            )
        )
    return tuple(axes)


class ForestReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.axes = _axes()
        cls.replay_plan = build_p0_composite_validation_plan(
            mission_id=MISSION_ID,
            historical_context=HISTORICAL_CONTEXT,
            bootstrap_samples=199,
            block_lengths=(2, 5),
            base_seed=991,
        )
        cls.inference = infer_p0_simultaneous_forest(
            {
                axis.spec.executable_id: axis.daily_pnl_mapping()
                for axis in cls.axes
            },
            historical_context=HISTORICAL_CONTEXT,
            bootstrap_samples=199,
            block_lengths=(2, 5),
            base_seed=991,
        )
        cls.bundle = build_p0_forest_bundle(
            replay_plan=cls.replay_plan,
            job_id=JOB_ID,
            job_hash=JOB_HASH,
            axes=cls.axes,
            inference=cls.inference,
        )

    def test_one_composite_executable_binds_exact_ordered_legacy_inventory(self) -> None:
        self.assertEqual(
            tuple(spec.executable_id for spec in P0_AXIS_SPECS),
            P0_REPLAY_EXECUTABLE_IDS,
        )
        self.assertEqual(len(P0_AXIS_SPECS), 6)
        analysis = self.replay_plan.analysis_plan
        self.assertEqual(
            analysis["family_inventory_hash"], p0_replay_family_inventory_hash()
        )
        self.assertEqual(
            [item["executable_id"] for item in analysis["ordered_legacy_members"]],
            list(P0_REPLAY_EXECUTABLE_IDS),
        )
        self.assertEqual(
            len({item["configuration_id"] for item in analysis["ordered_legacy_members"]}),
            6,
        )
        self.assertEqual(
            len({item["study_id"] for item in analysis["ordered_legacy_members"]}),
            6,
        )
        self.assertEqual(
            self.bundle.executable_id, self.replay_plan.executable.identity
        )

    def test_baseline_and_trial_form_a_strict_controlled_study_chassis(self) -> None:
        baseline = self.replay_plan.baseline_executable
        candidate = self.replay_plan.executable
        self.assertNotEqual(baseline.identity, candidate.identity)
        self.assertEqual(
            candidate.components[:-1],
            baseline.components,
        )
        self.assertEqual(len(candidate.components), len(baseline.components) + 1)
        self.assertEqual(
            component_domain(candidate.components[-1]),
            ResearchLayer.SYNTHESIS,
        )
        self.assertEqual(
            sum(
                component_domain(component) is ResearchLayer.SYNTHESIS
                for component in baseline.components
            ),
            1,
        )
        architecture = ArchitectureChassisSpec.from_executable(baseline)
        for role in ArchitectureRole:
            self.assertTrue(
                getattr(architecture, role.value).component_identities,
                role.value,
            )
        chassis = self.replay_plan.controlled_chassis()
        self.assertEqual(chassis.baseline_executable.identity, baseline.identity)
        self.assertEqual(chassis.changed_domains, (ResearchLayer.SYNTHESIS,))
        self.assertEqual(
            set(chassis.controlled_domains),
            {
                ResearchLayer.LABEL,
                ResearchLayer.MODEL,
                ResearchLayer.TRADE,
                ResearchLayer.LIFECYCLE,
                ResearchLayer.EXECUTION,
            },
        )
        self.assertEqual(
            chassis.embedded_controlled_domains,
            (ResearchLayer.FEATURE,),
        )
        validate_controlled_executable(chassis.to_identity_payload(), candidate)

    def test_support_and_surface_bind_axis_baseline_and_trial_subject(self) -> None:
        baseline_id = self.replay_plan.baseline_executable.identity
        candidate_id = self.replay_plan.executable.identity
        self.assertEqual(
            self.bundle.support_manifest()["baseline_executable_id"],
            baseline_id,
        )
        self.assertEqual(
            self.bundle.support_manifest()["composite_executable_id"],
            candidate_id,
        )
        self.assertEqual(
            self.bundle.surface_manifest()["baseline_executable_id"],
            baseline_id,
        )
        self.assertEqual(
            self.bundle.surface_manifest()["composite_executable_id"],
            candidate_id,
        )

    def test_pure_synthesis_axis_is_narrowly_typed_and_fail_closed(self) -> None:
        baseline = self.replay_plan.baseline_executable
        architecture = ArchitectureChassisSpec.from_executable(baseline)
        controls = (
            ResearchLayer.LABEL,
            ResearchLayer.MODEL,
            ResearchLayer.TRADE,
            ResearchLayer.LIFECYCLE,
            ResearchLayer.EXECUTION,
        )
        common = {
            "axis_id": "axis-p0-pure-synthesis-audit",
            "causal_question": (
                "Does the selected-set audit reanalysis preserve its exact control path?"
            ),
            "mechanism_family": "post-selection-audit-reanalysis",
            "primary_research_layer": ResearchLayer.SYNTHESIS,
            "system_architecture_family": architecture.identity,
            "changed_domains": (ResearchLayer.SYNTHESIS,),
            "controlled_domains": controls,
            "why_now": "repair the selected-set audit without changing trading logic",
            "stop_or_reopen_condition": "stop after the exact descriptive audit result",
        }
        axis = PortfolioAxis(**common, architecture_chassis=architecture)
        self.assertEqual(axis.changed_domains, (ResearchLayer.SYNTHESIS,))
        self.assertEqual(set(axis.controlled_domains), set(controls))

        with self.assertRaisesRegex(
            PortfolioDecisionError, "typed architecture chassis"
        ):
            PortfolioAxis(**common)

        with self.assertRaisesRegex(
            PortfolioDecisionError, "required controlled domains"
        ):
            PortfolioAxis(
                **{
                    **common,
                    "controlled_domains": tuple(
                        domain
                        for domain in controls
                        if domain is not ResearchLayer.MODEL
                    ),
                },
                architecture_chassis=architecture,
            )

        incomplete_baseline = ExecutableSpec(
            display_name="P0 audit control without synthesis role",
            components=baseline.components[:-1],
            parameters=baseline.parameter_values(),
            data_contract=baseline.data_contract,
            split_contract=baseline.split_contract,
            clock_contract=baseline.clock_contract,
            cost_contract=baseline.cost_contract,
            engine_contract=baseline.engine_contract,
            source_contracts=baseline.source_contracts,
        )
        incomplete_architecture = ArchitectureChassisSpec.from_executable(
            incomplete_baseline
        )
        with self.assertRaisesRegex(
            PortfolioDecisionError, "all architecture roles"
        ):
            PortfolioAxis(
                **{
                    **common,
                    "system_architecture_family": incomplete_architecture.identity,
                },
                architecture_chassis=incomplete_architecture,
            )

        with self.assertRaisesRegex(
            PortfolioDecisionError, "require multiple changed domains"
        ):
            PortfolioAxis(
                **{
                    **common,
                    "axis_id": "axis-single-portfolio-rejected",
                    "primary_research_layer": ResearchLayer.PORTFOLIO,
                    "changed_domains": (ResearchLayer.PORTFOLIO,),
                },
                architecture_chassis=architecture,
            )

    def test_plan_and_statistics_are_pre_job_while_support_is_execution_bound(self) -> None:
        plan_bytes = canonical_bytes(dict(self.replay_plan.plan))
        self.assertNotIn(JOB_ID.encode("ascii"), plan_bytes)
        self.assertNotIn(JOB_HASH.encode("ascii"), plan_bytes)
        alternate = build_p0_forest_bundle(
            replay_plan=self.replay_plan,
            job_id="job:p0-forest-alternate",
            job_hash="b" * 64,
            axes=self.axes,
            inference=self.inference,
        )
        self.assertEqual(
            self.bundle.validation_artifacts.plan_hash,
            alternate.validation_artifacts.plan_hash,
        )
        self.assertEqual(
            self.bundle.statistical_manifest(), alternate.statistical_manifest()
        )
        self.assertNotEqual(
            self.bundle.support_manifest(), alternate.support_manifest()
        )
        self.assertEqual(self.bundle.support_manifest()["job_id"], JOB_ID)
        self.assertEqual(self.bundle.support_manifest()["job_hash"], JOB_HASH)
        self.assertNotEqual(
            self.bundle.validation_artifacts.measurement_hash,
            alternate.validation_artifacts.measurement_hash,
        )
        self.assertNotEqual(
            self.bundle.validation_artifacts.result_hash,
            alternate.validation_artifacts.result_hash,
        )

    def test_support_binds_common_parents_statistics_and_post_selection_limits(self) -> None:
        support = self.bundle.support_manifest()
        self.assertFalse(support["economic_composite"])
        self.assertEqual(support["pnl_attribution"], P0_PNL_ATTRIBUTION)
        self.assertEqual(support["calendar"]["date_count"], 42)
        self.assertEqual(
            support["calendar"]["missing_day_policy"],
            "exact_shared_calendar_no_implicit_zero_fill",
        )
        self.assertEqual(
            support["historical_search_context"], HISTORICAL_CONTEXT.manifest()
        )
        self.assertEqual(
            support["statistical_plan"]["block_lengths"], [2, 5]
        )
        self.assertEqual(support["statistical_plan"]["bootstrap_samples"], 199)
        self.assertEqual(
            support["statistical_plan"]["monte_carlo_confidence_ppm"],
            self.inference.plan.monte_carlo_confidence_ppm,
        )
        self.assertEqual(len(support["statistical_plan"]["seeds"]), 2)
        self.assertEqual(
            set(support["common_parent_artifacts"]),
            {"daily_pnl", "inference", "statistical_inference"},
        )
        outputs = self.bundle.artifact_bytes()
        for parent in support["common_parent_artifacts"].values():
            self.assertEqual(
                sha256(outputs[parent["output_path"]]).hexdigest(),
                parent["sha256"],
            )
        self.assertEqual(len(support["post_selection_diagnostics"]), 6)
        self.assertEqual(len(support["members"]), 6)
        self.assertTrue(
            all(member["descriptive_metrics"] for member in support["members"])
        )
        for diagnostic in support["post_selection_diagnostics"]:
            self.assertEqual(
                diagnostic["decisive_value_kind"],
                "none_post_selection_descriptive_only",
            )
            self.assertIn("point_pvalue_ppm", diagnostic["raw"])
            self.assertIn(
                "monte_carlo_upper_pvalue_ppm", diagnostic["raw"]
            )
        self.assertIn(
            "within_replayed_set_familywise_values_are_not_selection_correction",
            support["claim_limits"],
        )

    def test_statistical_pvalue_must_recompute_from_durable_exceedance_count(self) -> None:
        statistical = deepcopy(self.bundle.statistical_manifest())
        raw = statistical["hypotheses"][0]["block_results"][0]["raw"]
        point = raw["point_pvalue_ppm"]
        upper = raw["monte_carlo_upper_pvalue_ppm"]
        raw["point_pvalue_ppm"] = point + 1 if point < upper else point - 1

        with self.assertRaisesRegex(
            ScientificEvidenceProofError,
            "do not recompute from exceedance counts",
        ):
            _validate_statistical_manifest(statistical)

    def test_composite_claims_never_impersonate_selection_correction(self) -> None:
        artifacts = self.bundle.validation_artifacts
        self.assertEqual(tuple(artifacts.plan["planned_claims"]), P0_REPLAY_CLAIMS)
        self.assertEqual(
            tuple(artifacts.plan["evidence_modes"]), P0_REPLAY_EVIDENCE_MODES
        )
        self.assertFalse(artifacts.plan["candidate_eligible_on_pass"])
        self.assertEqual(P0_REPLAY_EVIDENCE_MODES, (AUDIT_INTEGRITY_MODE,))
        self.assertTrue(
            set(P0_REPLAY_EVIDENCE_MODES).isdisjoint(TERMINAL_EVIDENCE_MODES)
        )
        self.assertEqual(
            artifacts.plan["adjudication_profile"]["promotion_criterion_ids"], []
        )
        self.assertEqual(
            artifacts.plan["adjudication_profile"]["multiplicity"], []
        )
        surface = canonical_bytes(
            {
                "binding": artifacts.binding(
                    validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
                ),
                "plan": dict(artifacts.plan),
            }
        ).decode("ascii")
        for prohibited in (
            "selection_aware_signal_evidence",
            "selection_corrected",
            "E01-familywise-selection",
        ):
            self.assertNotIn(prohibited, surface)

    def test_one_composite_artifact_bundle_is_consumable_by_validator_v2(self) -> None:
        artifacts = self.bundle.validation_artifacts
        classes = self.bundle.output_classes()
        self.assertEqual(classes, self.replay_plan.output_classes())
        self.assertEqual(
            tuple(self.bundle.artifact_bytes()), self.replay_plan.expected_outputs()
        )
        durable_paths = [
            path for path, value in classes.items() if value == "durable_evidence"
        ]
        self.assertEqual(
            set(durable_paths),
            {
                P0_COMPOSITE_PLAN_OUTPUT,
                P0_COMPOSITE_MEASUREMENT_OUTPUT,
                P0_COMPOSITE_RESULT_OUTPUT,
                P0_COMPOSITE_SUPPORT_OUTPUT,
                P0_STATISTICAL_OUTPUT,
            },
        )
        validator = ScientificAdjudicationValidatorV2()
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.bundle.write_artifacts(root)
            declared = tuple(
                ValidationArtifact(
                    output_name=path,
                    sha256=sha256((root / path).read_bytes()).hexdigest(),
                    _source=root / path,
                )
                for path in sorted(durable_paths)
            )
            validated = validator.validate(
                EvidenceValidationRequest(
                    domain="scientific",
                    validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
                    validation_plan_hash=artifacts.plan_hash,
                    job_id=JOB_ID,
                    job_hash=JOB_HASH,
                    mission_id=MISSION_ID,
                    evidence_subject={
                        "kind": "Executable",
                        "id": self.bundle.executable_id,
                    },
                    binding=artifacts.binding(
                        validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
                    ),
                    result_manifest=artifacts.result,
                    artifacts=declared,
                )
            )
        self.assertTrue(validated.scientific_eligible)
        self.assertFalse(validated.candidate_eligible)
        self.assertEqual(validated.verdict, "passed")
        rich = validated.facts["scientific_adjudication"]
        self.assertEqual(rich["state"], "frontier")
        self.assertFalse(rich["candidate_eligible"])
        self.assertEqual(
            {item["claim_id"]: item["state"] for item in rich["claims"]},
            {claim: "supported" for claim in P0_REPLAY_CLAIMS},
        )
        self.assertEqual(
            artifacts.binding(
                validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
            )["result_manifest_output"],
            P0_COMPOSITE_RESULT_OUTPUT,
        )

    def test_measurement_self_report_cannot_override_durable_member_proofs(self) -> None:
        artifacts = self.bundle.validation_artifacts
        payloads = dict(self.bundle.artifact_bytes())
        measurement = deepcopy(artifacts.measurement)
        measurement["metrics"]["audit_reanalysis_integrity"][
            "replayed_member_count"
        ] = 5
        measurement_content = canonical_bytes(measurement)
        measurement_hash = sha256(measurement_content).hexdigest()
        result = deepcopy(artifacts.result)
        for observation in result["observations"]:
            observation["measurement_artifact_hash"] = measurement_hash
        payloads[P0_COMPOSITE_MEASUREMENT_OUTPUT] = measurement_content
        payloads[P0_COMPOSITE_RESULT_OUTPUT] = canonical_bytes(result)

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            declared: list[ValidationArtifact] = []
            for output_name, storage_class in self.bundle.output_classes().items():
                if storage_class != "durable_evidence":
                    continue
                path = root / output_name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payloads[output_name])
                declared.append(
                    ValidationArtifact(
                        output_name=output_name,
                        sha256=sha256(payloads[output_name]).hexdigest(),
                        _source=path,
                    )
                )
            request = EvidenceValidationRequest(
                domain="scientific",
                validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
                validation_plan_hash=artifacts.plan_hash,
                job_id=JOB_ID,
                job_hash=JOB_HASH,
                mission_id=MISSION_ID,
                evidence_subject={
                    "kind": "Executable",
                    "id": self.bundle.executable_id,
                },
                binding=artifacts.binding(
                    validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
                ),
                result_manifest=result,
                artifacts=tuple(declared),
            )
            with self.assertRaisesRegex(
                EvidenceValidationError, "proof validation failed"
            ):
                ScientificAdjudicationValidatorV2().validate(request)

    def test_family_order_and_current_implementation_are_fail_closed(self) -> None:
        with self.assertRaisesRegex(ForestReplayError, "exact P0 inventory"):
            build_p0_forest_bundle(
                replay_plan=self.replay_plan,
                job_id=JOB_ID,
                job_hash=JOB_HASH,
                axes=tuple(reversed(self.axes)),
                inference=self.inference,
            )
        implementation = self.bundle.support_manifest()["implementation"]
        dependency_hashes = {
            item["sha256"] for item in implementation["dependencies"]
        }
        self.assertEqual(
            dependency_hashes,
            {sha256(path.read_bytes()).hexdigest() for path in forest_replay_dependency_paths()},
        )
        self.assertEqual(
            implementation["dependency_artifact_hashes"],
            sorted(dependency_hashes),
        )
        self.assertEqual(
            implementation["implementation_bundle_schema"],
            "component_implementation_bundle.v1",
        )

    def test_materialization_is_idempotent_and_drift_closed(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = self.bundle.write_artifacts(root)
            second = self.bundle.write_artifacts(root)
            self.assertEqual(first, second)
            self.assertEqual(len(first), 14)
            target = root / P0_COMPOSITE_MEASUREMENT_OUTPUT
            target.write_bytes(b"{}")
            with self.assertRaisesRegex(ForestReplayError, "different bytes"):
                self.bundle.write_artifacts(root)

    def test_dependency_manifest_uses_real_unique_files_and_ascii(self) -> None:
        paths = forest_replay_dependency_paths()
        self.assertEqual(len(paths), len(set(paths)))
        self.assertTrue(all(path.is_file() for path in paths))
        relative_paths = {
            path.relative_to(REPOSITORY_ROOT / "src").as_posix()
            for path in paths
        }
        self.assertTrue(
            {
                "axiom_rift/operations/validation.py",
                "axiom_rift/research/analog_state_family.py",
                "axiom_rift/research/analog_state_trace.py",
                "axiom_rift/research/audit_integrity_proof.py",
                "axiom_rift/research/equity_premium_trade_chassis.py",
                "axiom_rift/research/implementation_closure.py",
                "axiom_rift/research/p0_selection_inference.py",
                "axiom_rift/research/scientific_trace.py",
                (
                    "axiom_rift/research/"
                    "session_dense_positive_sleeve_chassis.py"
                ),
            }.issubset(relative_paths)
        )
        adapter_relative_paths = {
            path.relative_to(REPOSITORY_ROOT / "src").as_posix()
            for path in forest_replay_adapter_dependency_paths()
        }
        self.assertIn(
            "axiom_rift/research/p0_selection_inference.py",
            adapter_relative_paths,
        )
        self.assertTrue(
            {
                "axiom_rift/research/regime_direction_router_discovery.py",
                "axiom_rift/research/three_way_regime_router_discovery.py",
            }.isdisjoint(relative_paths)
        )
        canonical_bytes(self.bundle.surface_manifest()).decode("ascii")
        canonical_bytes(self.bundle.support_manifest()).decode("ascii")

    def test_transitive_source_mutation_reidentifies_forest_bundle(self) -> None:
        for target_name in (
            "analog_state_family.py",
            "p0_selection_inference.py",
        ):
            with self.subTest(target_name=target_name):
                original_manifest = forest_replay_implementation_manifest()
                original_identity = forest_replay_implementation_identity()
                target = next(
                    path
                    for path in forest_replay_dependency_paths()
                    if path.name == target_name
                )
                original_read_bytes = Path.read_bytes
                original_content = original_read_bytes(target)
                original_hash = sha256(original_content).hexdigest()
                mutated_hash = sha256(original_content + b"\n").hexdigest()

                def one_byte_mutation(path: Path) -> bytes:
                    content = original_read_bytes(path)
                    if path.resolve() == target.resolve():
                        return content + b"\n"
                    return content

                with patch.object(Path, "read_bytes", one_byte_mutation):
                    mutated_manifest = forest_replay_implementation_manifest()
                    mutated_identity = forest_replay_implementation_identity()

                original_hashes = set(
                    original_manifest["dependency_artifact_hashes"]
                )
                mutated_hashes = set(
                    mutated_manifest["dependency_artifact_hashes"]
                )
                self.assertIn(original_hash, original_hashes)
                self.assertNotIn(original_hash, mutated_hashes)
                self.assertIn(mutated_hash, mutated_hashes)
                self.assertEqual(
                    original_hashes - {original_hash},
                    mutated_hashes - {mutated_hash},
                )
                self.assertNotEqual(original_identity, mutated_identity)

    def test_implementation_artifact_is_the_component_identity_preimage(self) -> None:
        expected = forest_replay_implementation_identity().rsplit(":", 1)[-1]
        artifact = forest_replay_implementation_artifact()
        self.assertEqual(
            sha256(artifact).hexdigest(),
            expected,
        )
        domain, payload = parse_canonical_identity_bytes(artifact)
        self.assertEqual(domain, "forest-replay-implementation")
        self.assertEqual(payload, self.bundle.support_manifest()["implementation"])

    def test_writer_declaration_paths_and_implementation_evidence_are_valid(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        callable_identity = (
            "axiom_rift.research.forest_replay.compute_p0_forest_replay.v1"
        )
        with TemporaryDirectory() as temporary:
            writer = StateWriter(
                temporary,
                permit_authority=PermitAuthority(b"p" * 32),
                engineering_fixture=True,
                foundation_root=repository_root,
            )
            implementation_identity, source_hashes = (
                _finalize_forest_job_implementation(
                    writer,
                    callable_identity=callable_identity,
                )
            )
            self.assertIn(
                forest_replay_implementation_identity().rsplit(":", 1)[-1],
                source_hashes,
            )
            spec = {
                "budget": {"compute_seconds": 600, "wall_seconds": 900},
                "callable_identity": callable_identity,
                "evidence_subject": {
                    "id": self.replay_plan.executable_id,
                    "kind": "Executable",
                },
                "expected_outputs": list(self.replay_plan.expected_outputs()),
                "implementation_identity": implementation_identity,
                "input_hashes": list(self.replay_plan.job_input_hashes()),
                "log_path": "local/jobs/p0-forest/job.log",
                "output_classes": self.replay_plan.output_classes(),
                "resume_action": "stop_batch",
                "scientific_binding": self.replay_plan.scientific_binding(
                    validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
                ),
                "timeout_or_stop_rule": "finish exact composite audit replay",
                "worker_claims": [],
            }
            StateWriter._validate_job_spec(spec)
            self.assertEqual(
                P0_STATISTICAL_OUTPUT,
                "evidence/p0-forest/composite/statistical-inference.json",
            )
            self.assertEqual(
                P0_COMPOSITE_SUPPORT_OUTPUT,
                "evidence/p0-forest/composite/composite-support.json",
            )
            legacy = deepcopy(spec)
            replacements = {
                P0_STATISTICAL_OUTPUT: (
                    "local/cache/p0-forest/support/statistical-inference.json"
                ),
                P0_COMPOSITE_SUPPORT_OUTPUT: (
                    "local/cache/p0-forest/support/composite-support.json"
                ),
            }
            legacy["expected_outputs"] = [
                replacements.get(path, path)
                for path in legacy["expected_outputs"]
            ]
            for current, old in replacements.items():
                legacy["output_classes"][old] = legacy["output_classes"].pop(
                    current
                )
            with self.assertRaisesRegex(
                TransitionError,
                "durable_evidence output is outside its logical namespace",
            ):
                StateWriter._validate_job_spec(legacy)
            resolved = writer._require_job_implementation_evidence(spec)
        self.assertEqual(
            resolved["artifact_hashes"], source_hashes
        )

        with TemporaryDirectory() as temporary:
            writer = StateWriter(
                temporary,
                permit_authority=PermitAuthority(b"q" * 32),
                engineering_fixture=False,
                foundation_root=repository_root,
                study_close_guard_capability=(
                    StudyCloseGuardCapability.ISOLATED_ENGINEERING_FIXTURE
                ),
                validation_registry=EvidenceValidatorRegistry(
                    (ScientificAdjudicationValidatorV2(),)
                ),
            )
            payloads = self.bundle.artifact_bytes()
            classes = self.bundle.output_classes()
            for path, storage_class in classes.items():
                if storage_class == "durable_evidence":
                    artifact = writer.evidence.finalize(payloads[path])
                    self.assertEqual(
                        artifact.sha256, self.bundle.output_hashes()[path]
                    )
            validated, trace = writer._run_registered_validator(
                domain="scientific",
                job_id=JOB_ID,
                job_hash=JOB_HASH,
                mission_id=MISSION_ID,
                evidence_subject={
                    "id": self.replay_plan.executable_id,
                    "kind": "Executable",
                },
                binding=self.replay_plan.scientific_binding(
                    validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
                ),
                result_manifest=self.bundle.validation_artifacts.result,
                output_manifest=self.bundle.output_hashes(),
                output_classes=classes,
                result_name=P0_COMPOSITE_RESULT_OUTPUT,
            )
        self.assertTrue(validated.scientific_eligible)
        self.assertFalse(validated.candidate_eligible)
        self.assertEqual(trace["declared_artifact_count"], 5)

    def test_full_writer_lifecycle_uses_baseline_trial_and_storage_classes(self) -> None:
        repository_root = Path(__file__).resolve().parents[2]
        mission_id = "MIS-P0-FOREST-LIFECYCLE"
        initiative_id = "INI-P0-FOREST-LIFECYCLE"
        study_id = "STU-P0-FOREST-LIFECYCLE"
        batch_id = "BAT-P0-FOREST-LIFECYCLE"
        replay_plan = build_p0_composite_validation_plan(
            mission_id=mission_id,
            historical_context=HISTORICAL_CONTEXT,
            bootstrap_samples=199,
            block_lengths=(2, 5),
            base_seed=991,
        )
        baseline_architecture = ArchitectureChassisSpec.from_executable(
            replay_plan.baseline_executable
        )
        alternate_architecture = ArchitectureChassisSpec.from_executable(
            replay_plan.executable
        )
        synthesis_controls = (
            ResearchLayer.LABEL,
            ResearchLayer.MODEL,
            ResearchLayer.TRADE,
            ResearchLayer.LIFECYCLE,
            ResearchLayer.EXECUTION,
        )
        synthesis_axis = PortfolioAxis(
            axis_id="p0-forest-selected-set-audit",
            causal_question=(
                "Does post-selection reanalysis preserve the exact audit control path?"
            ),
            mechanism_family="post-selection-audit-reanalysis",
            primary_research_layer=ResearchLayer.SYNTHESIS,
            system_architecture_family=baseline_architecture.identity,
            changed_domains=(ResearchLayer.SYNTHESIS,),
            controlled_domains=synthesis_controls,
            why_now="repair the selected-set audit before further interpretation",
            stop_or_reopen_condition="stop after the exact descriptive audit result",
            architecture_chassis=baseline_architecture,
        )
        label_axis = PortfolioAxis(
            axis_id="p0-forest-future-label-contrast",
            causal_question="Would a prospective label contrast change the conclusion?",
            mechanism_family="prospective-label-contrast",
            primary_research_layer=ResearchLayer.LABEL,
            system_architecture_family=alternate_architecture.identity,
            changed_domains=(ResearchLayer.LABEL,),
            controlled_domains=(ResearchLayer.MODEL,),
            why_now="preserve a prospective alternative outside the selected-set audit",
            stop_or_reopen_condition="open only after a separately registered decision",
            architecture_chassis=alternate_architecture,
            status="deferred",
        )
        trade_axis = PortfolioAxis(
            axis_id="p0-forest-future-trade-contrast",
            causal_question="Would a prospective trade rule contrast add information?",
            mechanism_family="prospective-trade-contrast",
            primary_research_layer=ResearchLayer.TRADE,
            system_architecture_family=alternate_architecture.identity,
            changed_domains=(ResearchLayer.TRADE,),
            controlled_domains=(ResearchLayer.MODEL,),
            why_now="preserve an unrelated trade-policy branch in the forest",
            stop_or_reopen_condition="open only after a separately registered decision",
            architecture_chassis=alternate_architecture,
            status="deferred",
        )

        with TemporaryDirectory() as temporary:
            writer = StateWriter(
                temporary,
                permit_authority=PermitAuthority(b"w" * 32),
                clock=lambda: FIXED_NOW,
                engineering_fixture=False,
                foundation_root=repository_root,
                study_close_guard_capability=(
                    StudyCloseGuardCapability.ISOLATED_ENGINEERING_FIXTURE
                ),
                validation_registry=EvidenceValidatorRegistry(
                    (ScientificAdjudicationValidatorV2(),)
                ),
            )
            writer.initialize_ready()
            writer.open_mission(
                mission_id=mission_id,
                goal={
                    "objective": "complete one selected-set forest audit reanalysis",
                    "scope": ["local", "scientific_audit"],
                    "terminal_contract": "no_scientific_terminal",
                },
                operation_id="p0-forest-life-mission",
            )
            control = writer.read_control()
            assert control is not None
            intake = MissionResearchIntake(
                mission_id=mission_id,
                history_head_sequence=control["heads"]["journal"]["sequence"],
                history_head_event_id=control["heads"]["journal"]["event_id"],
                reviewed_surfaces=tuple(sorted(REQUIRED_INTAKE_SURFACES)),
                mission_thesis=(
                    "audit the selected legacy set without creating candidate authority"
                ),
                architecture_findings=(
                    "the audit needs an exact prediction-to-position control chassis",
                ),
                bottleneck_hypotheses=(
                    "post-selection interpretation may exceed its evidence authority",
                    "legacy replay surfaces may have lost a common control path",
                ),
                underexplored_layers=(
                    ResearchLayer.LABEL,
                    ResearchLayer.MODEL,
                    ResearchLayer.SYNTHESIS,
                    ResearchLayer.TRADE,
                ),
                legacy_limitations=(
                    "the six members were selected after a larger historical search"
                ),
            )
            writer.record_research_intake(
                intake=intake,
                operation_id="p0-forest-life-intake",
            )
            writer.open_initiative(
                initiative_id=initiative_id,
                objective={
                    "objective": "run the exact selected-set composite audit",
                    "bounds": {"wall_seconds": 1200, "trial_delta": 1},
                    "done_conditions": ["one validator-v2 result is complete"],
                },
                operation_id="p0-forest-life-initiative",
            )
            snapshot = PortfolioSnapshot(
                mission_id=mission_id,
                axes=(synthesis_axis, label_axis, trade_axis),
                opportunity_cost_basis=(
                    "run one bounded audit while preserving prospective alternatives"
                ),
                research_intake_id=intake.identity,
                exhaustion_standard={
                    "architecture_review_minimum_axes": 2,
                    "architecture_review_minimum_studies": 3,
                    "minimum_axes": 3,
                    "minimum_distinct_studies_per_axis": 2,
                    "minimum_mechanism_families": 3,
                    "minimum_negative_executables_per_family": 2,
                    "minimum_primary_research_layers": 3,
                    "minimum_system_architecture_families": 2,
                    "required_evidence_modes": [
                        "causal_contrast",
                        "cost_and_execution",
                        "sensitivity_or_stress",
                    ],
                    "stop_basis": (
                        "all preregistered structural frontiers lose information value"
                    ),
                },
            )
            writer.record_portfolio_snapshot(
                snapshot=snapshot,
                operation_id="p0-forest-life-portfolio",
            )
            protocol_audit = writer.evidence.finalize(
                canonical_bytes(
                    {
                        "finding": "validator v2 proof protocol is available",
                        "schema": "research_protocol_audit.v1",
                    }
                )
            )
            protocol_control = writer.read_control()
            assert protocol_control is not None
            writer.activate_research_protocol(
                activation=ResearchProtocolActivation(
                    protocol=ResearchProtocol.SCIENTIFIC_ADJUDICATION_V2,
                    validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID,
                    authority_manifest_digest=protocol_control["authority"][
                        "manifest_digest"
                    ],
                    audit_artifact_hash=protocol_audit.sha256,
                ),
                operation_id="p0-forest-life-protocol-v2",
            )
            decision = PortfolioDecision(
                decision_id="DEC-P0-FOREST-LIFECYCLE",
                chosen_option_id="run-selected-set-audit",
                options=(
                    DecisionOption(
                        option_id="run-selected-set-audit",
                        action=PortfolioAction.SYNTHESIZE,
                        target_id=synthesis_axis.axis_id,
                        expected_information_value="positive audit information",
                        opportunity_cost="one bounded Batch",
                    ),
                    DecisionOption(
                        option_id="retain-label-contrast",
                        action=PortfolioAction.CONTRAST,
                        target_id=label_axis.axis_id,
                        expected_information_value="positive prospective information",
                        opportunity_cost="deferred",
                        omission_reason="the bounded historical audit is completed first",
                    ),
                ),
                rationale=(
                    "repair historical interpretation while preserving prospective branches"
                ),
                commitment_batches=1,
                quant_team_review=QuantTeamDecisionReview(
                    assessments=(
                        DecisionLensAssessment(
                            lens=DecisionLens.CAUSALITY,
                            position=DecisionLensPosition.SUPPORT,
                            option_ids=(
                                "retain-label-contrast",
                                "run-selected-set-audit",
                            ),
                            basis_records=(
                                DecisionBasisRecord(
                                    kind="portfolio-snapshot",
                                    record_id=snapshot.identity,
                                ),
                            ),
                            finding=(
                                "the selected-set audit isolates the current "
                                "historical interpretation defect"
                            ),
                        ),
                        DecisionLensAssessment(
                            lens=DecisionLens.RISK,
                            position=DecisionLensPosition.UNCERTAIN,
                            option_ids=("run-selected-set-audit",),
                            basis_records=(
                                DecisionBasisRecord(
                                    kind="portfolio-snapshot",
                                    record_id=snapshot.identity,
                                ),
                            ),
                            finding=(
                                "one bounded audit Batch delays the retained "
                                "prospective label contrast"
                            ),
                        ),
                    ),
                    claim_boundary=(
                        "allocation only; no scientific or candidate claim"
                    ),
                    resolution_basis=(
                        "repair the exact historical interpretation before "
                        "spending a prospective contrast"
                    ),
                    disagreement_resolution=(
                        "retain the label contrast as an independently "
                        "selectable Portfolio branch"
                    ),
                ),
                baseline_executable=replay_plan.baseline_executable,
            )
            writer.record_portfolio_decision(
                decision=decision,
                operation_id="p0-forest-life-decision",
            )
            chassis = replay_plan.controlled_chassis()
            question = {
                "causal_question": (
                    "Does exact post-selection reanalysis preserve audit integrity?"
                ),
                "changed_variables": ["synthesis_reanalysis"],
                "controlled_variables": [
                    "label",
                    "model",
                    "trade",
                    "lifecycle",
                    "execution",
                ],
                "done_conditions": ["the exact validator-v2 result is complete"],
                "evidence_modes": list(P0_REPLAY_EVIDENCE_MODES),
            }
            proposal = {
                "authority": "post_selection_descriptive_audit_only",
                "mechanism": "selected_set_composite_reanalysis",
            }
            study_hash = writer.study_input_hash(
                question=question,
                material_identity=OBSERVED_MATERIAL_ID,
                semantic_proposal=proposal,
                controlled_chassis=chassis,
                portfolio_axis_id=synthesis_axis.axis_id,
                portfolio_axis_identity=synthesis_axis.identity,
                portfolio_decision_id=decision.identity,
            )
            study_permit = writer.issue_permit(
                kind=PermitKind.STUDY,
                subject_kind=SubjectKind.INITIATIVE,
                subject_id=initiative_id,
                input_hash=study_hash,
                actions=("open_study",),
                scope=(
                    "study",
                    f"decision:{decision.identity}",
                    f"axis:{synthesis_axis.identity}",
                    f"baseline:{replay_plan.baseline_executable.identity}",
                    f"chassis:{baseline_architecture.identity}",
                    f"snapshot:{snapshot.identity}",
                ),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="p0-forest-life-study-permit",
            )
            opened = writer.open_study(
                study_id=study_id,
                question=question,
                material_identity=OBSERVED_MATERIAL_ID,
                material_display_name="foundation observed development material",
                semantic_proposal=proposal,
                controlled_chassis=chassis,
                portfolio_axis_id=synthesis_axis.axis_id,
                portfolio_axis_identity=synthesis_axis.identity,
                portfolio_decision_id=decision.identity,
                permit=study_permit,
                operation_id="p0-forest-life-study-open",
            )
            batch = BatchSpec(
                batch_id=batch_id,
                study_id=study_id,
                study_hash=opened.result["study_hash"],
                display_name="P0 selected-set composite audit Batch",
                max_trials=1,
                max_compute_seconds=900,
                max_wall_seconds=1200,
                stop_rule="stop after the exact composite audit result",
                acceptance_profile={
                    "candidate_authority": "none",
                    "validity": "all preregistered integrity checks pass",
                },
                adaptive_basis={
                    "uncertainty": "historical selection context is explicit",
                    "causal_complexity": "one exact audit composition",
                    "surface_curvature": "not adaptive",
                    "compute_cost": "one bounded replay",
                    "expected_information_value": "repair interpretation authority",
                    "portfolio_opportunity_cost": "one deferred prospective contrast",
                },
            )
            batch_permit = writer.issue_permit(
                kind=PermitKind.BATCH,
                subject_kind=SubjectKind.STUDY,
                subject_id=study_id,
                input_hash=batch.identity.removeprefix("batch:"),
                actions=("open_batch",),
                scope=("batch",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="p0-forest-life-batch-permit",
            )
            writer.open_batch(
                batch_spec=batch,
                permit=batch_permit,
                operation_id="p0-forest-life-batch-open",
            )
            trial = writer.register_trial(
                executable=replay_plan.executable,
                operation_id="p0-forest-life-trial",
            )
            self.assertEqual(trial.result["trial_delta"], 1)

            callable_identity = (
                "axiom_rift.research.forest_replay.compute_p0_forest_replay.v1"
            )
            implementation_identity, source_hashes = (
                _finalize_forest_job_implementation(
                    writer,
                    callable_identity=callable_identity,
                )
            )
            spec = {
                "budget": {"compute_seconds": 600, "wall_seconds": 900},
                "callable_identity": callable_identity,
                "evidence_subject": {
                    "id": replay_plan.executable_id,
                    "kind": "Executable",
                },
                "expected_outputs": list(replay_plan.expected_outputs()),
                "implementation_identity": implementation_identity,
                "input_hashes": list(replay_plan.job_input_hashes()),
                "log_path": "local/jobs/p0-forest/lifecycle.log",
                "output_classes": replay_plan.output_classes(),
                "resume_action": "stop_batch",
                "scientific_binding": replay_plan.scientific_binding(
                    validator_id=SCIENTIFIC_ADJUDICATION_VALIDATOR_V2_ID
                ),
                "timeout_or_stop_rule": "finish exact composite audit replay",
                "worker_claims": [],
            }
            declared = writer.declare_job(
                spec=spec,
                operation_id="p0-forest-life-job-declare",
            )
            job_permit = writer.issue_permit(
                kind=PermitKind.JOB,
                subject_kind=SubjectKind.JOB,
                subject_id=declared.result["job_id"],
                input_hash=declared.result["job_hash"],
                actions=("start_job",),
                scope=("job",),
                expires_at_utc=FIXED_EXPIRY,
                one_shot=True,
                operation_id="p0-forest-life-job-permit",
            )
            writer.start_job(
                permit=job_permit,
                operation_id="p0-forest-life-job-start",
            )
            bundle = build_p0_forest_bundle(
                replay_plan=replay_plan,
                job_id=declared.result["job_id"],
                job_hash=declared.result["job_hash"],
                axes=self.axes,
                inference=self.inference,
            )
            payloads = bundle.artifact_bytes()
            classes = bundle.output_classes()
            for output_name, content in payloads.items():
                if classes[output_name] == "durable_evidence":
                    finalized = writer.evidence.finalize(content)
                    self.assertEqual(
                        finalized.sha256,
                        bundle.output_hashes()[output_name],
                    )
                else:
                    target = writer.root / output_name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
            completed = writer.complete_job(
                outcome="success",
                output_manifest=bundle.output_hashes(),
                operation_id="p0-forest-life-job-complete",
            )
            self.assertEqual(completed.result["scientific_verdict"], "passed")
            self.assertEqual(
                writer.read_control()["next_action"],
                {
                    "completion_record_id": completed.result[
                        "completion_record_id"
                    ],
                    "job_id": declared.result["job_id"],
                    "kind": "judge_job_evidence",
                },
            )
            for output_name, storage_class in classes.items():
                if storage_class == "durable_evidence":
                    writer.evidence.verify(bundle.output_hashes()[output_name])
                    self.assertFalse((writer.root / output_name).exists())
                else:
                    self.assertEqual(
                        (writer.root / output_name).read_bytes(),
                        payloads[output_name],
                    )
            with LocalIndex(writer.index_path) as index:
                study = index.get("study-open", study_id)
                trial_record = index.get("trial", replay_plan.executable_id)
                decision_record = index.get(
                    "portfolio-decision", decision.identity
                )
                completion = index.get(
                    "job-completed",
                    completed.result["completion_record_id"],
                )
            assert study is not None
            assert trial_record is not None
            assert decision_record is not None
            assert completion is not None
            self.assertEqual(
                decision_record.payload["baseline_executable_id"],
                replay_plan.baseline_executable.identity,
            )
            self.assertEqual(
                decision_record.payload["target_axis_identity"],
                synthesis_axis.identity,
            )
            self.assertEqual(
                study.payload["controlled_chassis"]["baseline_executable_id"],
                replay_plan.baseline_executable.identity,
            )
            self.assertEqual(
                trial_record.payload["executable"],
                replay_plan.executable.to_identity_payload(),
            )
            self.assertEqual(
                completion.payload["scientific"]["validation_trace"][
                    "declared_artifact_count"
                ],
                5,
            )


if __name__ == "__main__":
    unittest.main()
