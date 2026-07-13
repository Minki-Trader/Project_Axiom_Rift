from __future__ import annotations

import unittest

from axiom_rift.research.chassis import ArchitectureChassisSpec
from axiom_rift.research.forest_replay import build_p0_composite_validation_plan
from axiom_rift.research.governance import ResearchLayer
from axiom_rift.research.portfolio import PortfolioAxis
from axiom_rift.research.portfolio_projection import (
    PortfolioProjectionError,
    architecture_chassis_from_identity_payload,
    component_surface_registry,
    portfolio_axis_from_projection,
)
from axiom_rift.research.selection_inference import HistoricalSearchContext


class PortfolioProjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.plan = build_p0_composite_validation_plan(
            mission_id="MIS-PORTFOLIO-PROJECTION",
            historical_context=HistoricalSearchContext(
                context_id="history:portfolio-projection-test",
                prior_global_exposure_count=470,
            ),
            bootstrap_samples=199,
            block_lengths=(2, 5),
            base_seed=991,
        )
        cls.registry = component_surface_registry(
            (
                cls.plan.baseline_executable.to_identity_payload(),
                cls.plan.executable.to_identity_payload(),
            )
        )
        cls.architecture = ArchitectureChassisSpec.from_executable(
            cls.plan.baseline_executable
        )
        cls.axis = PortfolioAxis(
            axis_id="axis-p0-composite-audit-reanalysis",
            causal_question=(
                "Does an exact composite replay preserve the six selected legacy "
                "surfaces without granting post-selection candidate authority?"
            ),
            mechanism_family="historical_post_selection_composite_audit",
            primary_research_layer=ResearchLayer.SYNTHESIS,
            system_architecture_family=cls.architecture.identity,
            changed_domains=(ResearchLayer.SYNTHESIS,),
            controlled_domains=cls.plan.controlled_chassis().controlled_domains,
            why_now="The exhaustive audit found erased claim structure.",
            stop_or_reopen_condition=(
                "Stop after one exact six-member composite replay and reopen only "
                "with a changed immutable legacy artifact."
            ),
            architecture_chassis=cls.architecture,
        )

    def test_component_and_architecture_payloads_round_trip_exactly(self) -> None:
        rebuilt = architecture_chassis_from_identity_payload(
            self.architecture.to_identity_payload(),
            self.registry,
        )
        self.assertEqual(rebuilt.identity, self.architecture.identity)
        self.assertEqual(
            rebuilt.to_identity_payload(), self.architecture.to_identity_payload()
        )

    def test_portfolio_axis_projection_round_trips_exact_identity(self) -> None:
        payload = {
            "architecture_chassis": self.architecture.to_identity_payload(),
            "architecture_chassis_identity": self.architecture.identity,
            "axis_id": self.axis.axis_id,
            "axis_identity": self.axis.identity,
            "causal_question": self.axis.causal_question,
            "changed_domains": [value.value for value in self.axis.changed_domains],
            "controlled_domains": [
                value.value for value in self.axis.controlled_domains
            ],
            "mechanism_family": self.axis.mechanism_family,
            "primary_research_layer": self.axis.primary_research_layer.value,
            "status": self.axis.status,
            "stop_or_reopen_condition": self.axis.stop_or_reopen_condition,
            "system_architecture_family": self.axis.system_architecture_family,
            "why_now": self.axis.why_now,
        }
        rebuilt = portfolio_axis_from_projection(payload, self.registry)
        self.assertEqual(rebuilt.identity, self.axis.identity)
        self.assertEqual(
            rebuilt.architecture_chassis.to_identity_payload(),
            self.architecture.to_identity_payload(),
        )

    def test_missing_semantic_surface_fails_closed(self) -> None:
        incomplete = dict(self.registry)
        used_surface = next(
            surface
            for role in self.architecture.to_identity_payload()["roles"].values()
            for surface in role["component_semantic_surfaces"]
        )
        incomplete.pop(used_surface)
        with self.assertRaisesRegex(
            PortfolioProjectionError,
            "surface is absent",
        ):
            architecture_chassis_from_identity_payload(
                self.architecture.to_identity_payload(),
                incomplete,
            )


if __name__ == "__main__":
    unittest.main()
