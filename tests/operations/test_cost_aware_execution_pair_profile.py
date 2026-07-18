from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

import axiom_rift.operations.cost_aware_execution_pair_profile as profile
from axiom_rift.operations.bound_fixed_hold_profile import (
    BoundFixedHoldExposureContext,
)
from axiom_rift.research.cost_aware_execution_protocol import (
    COST_AWARE_EXECUTION_CONTROL_HISTORICAL_EXECUTABLE_ID,
    COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT,
    COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID,
)
from axiom_rift.research.historical_family_binding import (
    HistoricalFamilyAuthority,
    HistoricalFamilySpec,
)
from axiom_rift.research.historical_family_stu0070 import (
    STU0070_HISTORICAL_FAMILY,
)


_OBLIGATION_ID = (
    "historical-replay-obligation:"
    "ab4d0fcd6d5f88756fbed17f32dbf2831217a7c158d043b7f85f3c69b149b63e"
)
_EXPECTED_CRITERION_IDS = (
    "A01-minimum-trades",
    "A02-positive-density",
    "A03-profit-day-concentration",
    "B01-positive-native-cost",
    "B02-fold-profit-factor",
    "B03-slippage-stress",
    "B04-monthly-realized-drawdown-share",
    "C01-feature-prefix-invariance",
    "C02-decision-append-invariance",
    "C03-decision-time-causality",
    "C04-resolved-cost",
    "C05-finite-metrics",
    "D03-primary-control",
    "D04-primary-control-uncertainty",
    "E01-familywise-selection",
    "F01-evaluable-folds",
    "F02-winning-folds",
    "F03-positive-regimes",
)


def _spec() -> SimpleNamespace:
    return SimpleNamespace(
        mission_id="MIS-0006",
        study_id="STU-9000",
        target_obligation_id=_OBLIGATION_ID,
        original_study_id="STU-0070",
    )


def _authority(
    family: HistoricalFamilySpec = STU0070_HISTORICAL_FAMILY,
) -> HistoricalFamilyAuthority:
    return HistoricalFamilyAuthority(
        replay_obligation_id=_OBLIGATION_ID,
        family=family,
        reconstruction_source_path=(
            "src/axiom_rift/research/historical_family_stu0070.py"
        ),
        reconstruction_source_sha256="a" * 64,
    )


def _member(
    *,
    ordinal: int,
    historical_reference_executable_id: str,
    prospective_digest: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        ordinal=ordinal,
        historical_reference_executable_id=(
            historical_reference_executable_id
        ),
        executable=SimpleNamespace(identity="executable:" + prospective_digest * 64),
    )


class CostAwareExecutionPairProfileTests(unittest.TestCase):
    @patch.object(profile, "require_bound_fixed_hold_family_authority")
    def test_writer_authority_must_be_the_exact_stu0070_family(
        self,
        require_bound: Mock,
    ) -> None:
        exact = _authority()
        require_bound.return_value = exact
        self.assertIs(
            profile.require_cost_aware_execution_pair_family_authority(
                Mock(),
                spec=_spec(),
                historical_family_authority_id=exact.identity,
            ),
            exact,
        )

        wrong_family = HistoricalFamilySpec(
            original_study_id=STU0070_HISTORICAL_FAMILY.original_study_id,
            original_batch_id="batch:" + "b" * 64,
            target_historical_executable_id=(
                STU0070_HISTORICAL_FAMILY.target_historical_executable_id
            ),
            members=STU0070_HISTORICAL_FAMILY.members,
            controls=STU0070_HISTORICAL_FAMILY.controls,
        )
        require_bound.return_value = _authority(wrong_family)
        with self.assertRaisesRegex(RuntimeError, "exact STU-0070"):
            profile.require_cost_aware_execution_pair_family_authority(
                Mock(),
                spec=_spec(),
                historical_family_authority_id=require_bound.return_value.identity,
            )

    @patch.object(profile, "project_bound_fixed_hold_exposure_context")
    def test_exposure_projection_keeps_current_prior_separate_from_end_526(
        self,
        project_bound: Mock,
    ) -> None:
        context = BoundFixedHoldExposureContext(
            prior_global_exposure_count=581,
            original_family_end_global_exposure_count=(
                COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
            ),
        )
        project_bound.return_value = context
        self.assertIs(
            profile.project_cost_aware_execution_pair_exposure_context(
                Mock(),
                spec=_spec(),
                historical_family=STU0070_HISTORICAL_FAMILY,
            ),
            context,
        )
        self.assertEqual(context.prior_global_exposure_count, 581)
        self.assertEqual(
            context.original_family_end_global_exposure_count,
            COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT,
        )

        project_bound.return_value = BoundFixedHoldExposureContext(
            prior_global_exposure_count=581,
            original_family_end_global_exposure_count=(
                COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
                - 1
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "end 526"):
            profile.project_cost_aware_execution_pair_exposure_context(
                Mock(),
                spec=_spec(),
                historical_family=STU0070_HISTORICAL_FAMILY,
            )

    @patch.object(profile, "FixedHoldReplayMember")
    @patch.object(profile, "build_cost_aware_execution_pair_job_plan")
    def test_members_bind_exact_historical_order_and_both_exposure_counts(
        self,
        build_job_plan: Mock,
        member_type: Mock,
    ) -> None:
        build_job_plan.side_effect = lambda **kwargs: SimpleNamespace(
            executable_id=kwargs["executable_id"]
        )
        member_type.side_effect = lambda **kwargs: SimpleNamespace(**kwargs)
        exposure = BoundFixedHoldExposureContext(
            prior_global_exposure_count=581,
            original_family_end_global_exposure_count=(
                COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
            ),
        )
        authority = _authority()

        members = profile.cost_aware_execution_pair_members(
            _spec(),
            exposure_context=exposure,
            historical_family=STU0070_HISTORICAL_FAMILY,
            historical_family_authority_id=authority.identity,
        )

        self.assertEqual(tuple(member.ordinal for member in members), (1, 2))
        self.assertEqual(
            tuple(
                member.historical_reference_executable_id
                for member in members
            ),
            (
                COST_AWARE_EXECUTION_CONTROL_HISTORICAL_EXECUTABLE_ID,
                COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID,
            ),
        )
        self.assertEqual(build_job_plan.call_count, 2)
        for member, job_call in zip(
            members,
            build_job_plan.call_args_list,
            strict=True,
        ):
            arguments = job_call.kwargs
            self.assertEqual(arguments["executable_id"], member.executable.identity)
            self.assertEqual(
                arguments["historical_context_prior_global_exposure_count"],
                581,
            )
            self.assertEqual(
                arguments["original_family_end_global_exposure_count"],
                COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT,
            )
            self.assertIs(
                arguments["historical_family"],
                STU0070_HISTORICAL_FAMILY,
            )
            self.assertEqual(
                arguments["historical_family_authority_id"],
                authority.identity,
            )
            self.assertEqual(arguments["replay_obligation_id"], _OBLIGATION_ID)

    def test_real_members_share_one_ordered_generic_replay_definition(self) -> None:
        authority = _authority()
        members = profile.cost_aware_execution_pair_members(
            _spec(),
            exposure_context=BoundFixedHoldExposureContext(
                prior_global_exposure_count=581,
                original_family_end_global_exposure_count=(
                    COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
                ),
            ),
            historical_family=STU0070_HISTORICAL_FAMILY,
            historical_family_authority_id=authority.identity,
        )

        executable_ids = tuple(
            member.executable.identity for member in members
        )
        self.assertEqual(
            executable_ids,
            members[0].job_plan.definition.prospective_executable_ids,
        )
        self.assertEqual(
            len(
                {
                    member.job_plan.definition.identity
                    for member in members
                }
            ),
            1,
        )
        self.assertEqual(
            tuple(member.job_plan.produces_family_cache for member in members),
            (True, False),
        )

    @patch.object(profile, "require_bound_fixed_hold_registration_prefix")
    def test_registration_rejects_reordered_pair_before_generic_boundary(
        self,
        require_bound: Mock,
    ) -> None:
        exposure = BoundFixedHoldExposureContext(
            prior_global_exposure_count=581,
            original_family_end_global_exposure_count=(
                COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
            ),
        )
        members = (
            _member(
                ordinal=2,
                historical_reference_executable_id=(
                    COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID
                ),
                prospective_digest="b",
            ),
            _member(
                ordinal=1,
                historical_reference_executable_id=(
                    COST_AWARE_EXECUTION_CONTROL_HISTORICAL_EXECUTABLE_ID
                ),
                prospective_digest="a",
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "registration pair"):
            profile.require_cost_aware_execution_pair_registration_prefix(
                Mock(),
                spec=_spec(),
                members=members,
                exposure_context=exposure,
            )
        require_bound.assert_not_called()

    def test_criterion_boundary_seals_the_exact_18_member_inventory(self) -> None:
        self.assertEqual(
            profile._cost_aware_execution_pair_criterion_ids(),
            _EXPECTED_CRITERION_IDS,
        )
        drifted = tuple(
            {**item, "criterion_id": "Z99-drift"}
            if item["criterion_id"] == "F03-positive-regimes"
            else item
            for item in profile.COST_AWARE_EXECUTION_REPLAY_CRITERIA
        )
        with patch.object(
            profile,
            "COST_AWARE_EXECUTION_REPLAY_CRITERIA",
            drifted,
        ):
            with self.assertRaisesRegex(RuntimeError, "inventory drifted"):
                profile._cost_aware_execution_pair_criterion_ids()

    @patch.object(profile, "build_fixed_hold_replay_design")
    @patch.object(profile, "cost_aware_execution_pair_controlled_chassis")
    @patch.object(
        profile,
        "require_cost_aware_execution_pair_registration_prefix",
    )
    @patch.object(profile, "cost_aware_execution_pair_members")
    @patch.object(
        profile,
        "project_cost_aware_execution_pair_exposure_context",
    )
    @patch.object(profile, "require_bound_fixed_hold_family_authorities")
    def test_profile_composes_exact_pair_through_generic_design_port(
        self,
        require_authorities: Mock,
        project_exposure: Mock,
        build_members: Mock,
        require_registration: Mock,
        build_chassis: Mock,
        build_design: Mock,
    ) -> None:
        authority = _authority()
        exposure = BoundFixedHoldExposureContext(
            prior_global_exposure_count=581,
            original_family_end_global_exposure_count=(
                COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
            ),
        )
        members = (
            _member(
                ordinal=1,
                historical_reference_executable_id=(
                    COST_AWARE_EXECUTION_CONTROL_HISTORICAL_EXECUTABLE_ID
                ),
                prospective_digest="a",
            ),
            _member(
                ordinal=2,
                historical_reference_executable_id=(
                    COST_AWARE_EXECUTION_TARGET_HISTORICAL_EXECUTABLE_ID
                ),
                prospective_digest="b",
            ),
        )
        sentinel = object()
        chassis = object()
        require_authorities.return_value = (authority,)
        project_exposure.return_value = exposure
        build_members.return_value = members
        build_chassis.return_value = chassis
        build_design.return_value = sentinel

        result = profile.build_cost_aware_execution_pair_profile_design(
            Mock(),
            spec=_spec(),
            historical_family_authority_id=authority.identity,
        )

        self.assertIs(result, sentinel)
        require_registration.assert_called_once()
        build_design.assert_called_once()
        arguments = build_design.call_args.kwargs
        self.assertIs(arguments["members"], members)
        self.assertEqual(
            arguments["target_executable_id"],
            "executable:" + "b" * 64,
        )
        self.assertIs(arguments["controlled_chassis"], chassis)
        self.assertEqual(arguments["criterion_ids"], _EXPECTED_CRITERION_IDS)
        self.assertEqual(
            arguments["historical_family_manifest"],
            STU0070_HISTORICAL_FAMILY.manifest(),
        )
        self.assertEqual(
            build_chassis.call_args,
            call(
                historical_family=STU0070_HISTORICAL_FAMILY,
                historical_context_prior_global_exposure_count=581,
                original_family_end_global_exposure_count=(
                    COST_AWARE_EXECUTION_ORIGINAL_FAMILY_END_GLOBAL_EXPOSURE_COUNT
                ),
            ),
        )


if __name__ == "__main__":
    unittest.main()
