from __future__ import annotations

import unittest
from pathlib import Path

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.writer import _hardcoded_control_ids
import axiom_rift.research.historical_family_replay as historical_family_module
import axiom_rift.research.historical_family_stu0016 as stu0016_module
import axiom_rift.research.historical_family_stu0017 as stu0017_module
from axiom_rift.research.historical_family_replay import (
    ALL_P1_HISTORICAL_FAMILY_CATALOG,
    ALL_P1_HISTORICAL_FAMILY_CATALOG_DIGEST,
    ControlBinding,
    HistoricalFamilyReplayError,
    HistoricalFamilySpec,
    HistoricalMemberSpec,
    P1_HISTORICAL_FAMILY_CATALOG,
    P1_HISTORICAL_FAMILY_CATALOG_DIGEST,
    P1_ROUTED_HISTORICAL_FAMILY_CATALOG,
    P1_ROUTED_HISTORICAL_FAMILY_CATALOG_DIGEST,
    STU0016_HISTORICAL_FAMILY,
    STU0017_HISTORICAL_FAMILY,
    STU0032_HISTORICAL_FAMILY,
    STU0048_HISTORICAL_FAMILY,
    STU0051_HISTORICAL_FAMILY,
    historical_family_catalog,
    historical_family_catalog_digest,
    historical_family_catalog_manifest,
)


def executable(token: int) -> str:
    return f"executable:{token:064x}"


def member(
    ordinal: int,
    token: int,
    *,
    configuration_id: str | None = None,
    parameters: object | None = None,
) -> HistoricalMemberSpec:
    return HistoricalMemberSpec(
        ordinal=ordinal,
        configuration_id=(
            f"configuration-{ordinal}"
            if configuration_id is None
            else configuration_id
        ),
        historical_reference_executable_id=executable(token),
        parameters=(
            {"profile": f"profile-{ordinal}", "signal_sign": 1}
            if parameters is None
            else parameters
        ),
    )


def four_members() -> tuple[HistoricalMemberSpec, ...]:
    return tuple(member(ordinal, ordinal) for ordinal in range(1, 5))


def four_controls() -> tuple[ControlBinding, ...]:
    return (
        ControlBinding(
            subject_historical_executable_id=executable(1),
            opposite_historical_executable_id=executable(2),
            feature_historical_executable_ids=(executable(3),),
        ),
        ControlBinding(
            subject_historical_executable_id=executable(2),
            opposite_historical_executable_id=executable(1),
            feature_historical_executable_ids=(executable(4),),
        ),
        ControlBinding(
            subject_historical_executable_id=executable(3),
            opposite_historical_executable_id=executable(4),
            feature_historical_executable_ids=(executable(1),),
        ),
        ControlBinding(
            subject_historical_executable_id=executable(4),
            opposite_historical_executable_id=executable(3),
            feature_historical_executable_ids=(executable(2),),
        ),
    )


def family(
    *,
    study_id: str = "STU-9001",
    batch_token: int = 1,
    members: tuple[HistoricalMemberSpec, ...] | None = None,
    controls: tuple[ControlBinding, ...] | None = None,
) -> HistoricalFamilySpec:
    return HistoricalFamilySpec(
        original_study_id=study_id,
        original_batch_id=f"batch:{batch_token:064x}",
        target_historical_executable_id=executable(4),
        members=four_members() if members is None else members,
        controls=four_controls() if controls is None else controls,
    )


def executable_values(value: object) -> tuple[str, ...]:
    found: list[str] = []

    def visit(item: object) -> None:
        if type(item) is str and item.startswith("executable:"):
            found.append(item)
        elif isinstance(item, dict):
            for child in item.values():
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    return tuple(found)


class HistoricalFamilyReplayTests(unittest.TestCase):
    def test_authority_bindings_are_isolated_from_reusable_family_data(
        self,
    ) -> None:
        self.assertEqual(
            _hardcoded_control_ids(
                Path(historical_family_module.__file__).read_bytes()
            ),
            (),
        )
        self.assertEqual(
            _hardcoded_control_ids(Path(stu0016_module.__file__).read_bytes()),
            ("STU-0016",),
        )
        self.assertEqual(
            _hardcoded_control_ids(Path(stu0017_module.__file__).read_bytes()),
            ("STU-0017",),
        )

    def test_builtin_catalog_is_exact_ascii_and_digest_frozen(self) -> None:
        self.assertEqual(
            tuple(
                item.original_study_id
                for item in P1_HISTORICAL_FAMILY_CATALOG
            ),
            ("STU-0032", "STU-0048", "STU-0051"),
        )
        self.assertEqual(
            tuple(item.family_size for item in P1_HISTORICAL_FAMILY_CATALOG),
            (12, 4, 4),
        )
        self.assertEqual(
            P1_HISTORICAL_FAMILY_CATALOG_DIGEST,
            "f2bd2f972ccda102a6ca0d14bbe25f1a049b87b9c909f939d6b7bf60c9203bc3",
        )
        self.assertEqual(
            historical_family_catalog_digest(
                tuple(reversed(P1_HISTORICAL_FAMILY_CATALOG))
            ),
            P1_HISTORICAL_FAMILY_CATALOG_DIGEST,
        )
        self.assertTrue(
            canonical_bytes(
                historical_family_catalog_manifest(
                    P1_HISTORICAL_FAMILY_CATALOG
                )
            ).isascii()
        )
        self.assertEqual(
            tuple(
                item.original_study_id
                for item in P1_ROUTED_HISTORICAL_FAMILY_CATALOG
            ),
            ("STU-0016", "STU-0017"),
        )
        self.assertEqual(
            P1_ROUTED_HISTORICAL_FAMILY_CATALOG_DIGEST,
            "8c3e4d93de028de29f6c33d8e59d948cd7084926568ecf286cf4b339affba80b",
        )
        self.assertEqual(
            tuple(
                item.original_study_id
                for item in ALL_P1_HISTORICAL_FAMILY_CATALOG
            ),
            ("STU-0016", "STU-0017", "STU-0032", "STU-0048", "STU-0051"),
        )
        self.assertEqual(
            ALL_P1_HISTORICAL_FAMILY_CATALOG_DIGEST,
            "f2f08b2db0139d2df91f3702a06b337754d874341f06dfb04f6e8e0a79547e11",
        )

    def test_builtin_target_controls_preserve_exact_original_members(self) -> None:
        stu0016 = STU0016_HISTORICAL_FAMILY.control_for_historical_executable(
            STU0016_HISTORICAL_FAMILY.target_historical_executable_id
        )
        self.assertEqual(
            stu0016.opposite_historical_executable_id,
            "executable:"
            "e1ae93800933f1739becd5e67512c20181948941d0b0bac491f40c206ca56f73",
        )
        self.assertEqual(
            stu0016.feature_historical_executable_ids,
            (
                "executable:"
                "87a549ee3c11ecfa276f03903e3bf46c63c1cb1f1b3f584841cc2005d67ffa1b",
                "executable:"
                "a1cf161817284545c00a7636c30481fa21568d7f0b7a8921d73dff0dbbb84c38",
            ),
        )
        stu0017 = STU0017_HISTORICAL_FAMILY.control_for_historical_executable(
            STU0017_HISTORICAL_FAMILY.target_historical_executable_id
        )
        self.assertEqual(
            stu0017.opposite_historical_executable_id,
            "executable:"
            "415313ffe158c34da4c6a423289c142864d7d5a455e6d1b79b63328d94dc5849",
        )
        self.assertEqual(
            stu0017.feature_historical_executable_ids,
            (
                "executable:"
                "563de482fc6f5fc5967a51f4c0338a505901139024736ad00e3c2cb7e6161d99",
                "executable:"
                "f97438d20e3be08799887750daf3b6191619ddf874008083be70fc9a320dbf50",
            ),
        )
        stu0048 = STU0048_HISTORICAL_FAMILY.control_for_historical_executable(
            STU0048_HISTORICAL_FAMILY.target_historical_executable_id
        )
        self.assertEqual(
            stu0048.opposite_historical_executable_id,
            "executable:"
            "4c6b58e03685bcca2037eb0f4731305d94423b00b7adb5ab54f99e147e645ab5",
        )
        self.assertEqual(
            stu0048.feature_historical_executable_ids,
            (
                "executable:"
                "4b203b0f0eb4e1e12b59f2baafe7e83202b866bc90f0034ad48cf0989bcaa09c",
            ),
        )
        stu0051 = STU0051_HISTORICAL_FAMILY.control_for_historical_executable(
            STU0051_HISTORICAL_FAMILY.target_historical_executable_id
        )
        self.assertEqual(
            stu0051.opposite_historical_executable_id,
            "executable:"
            "05a4320996e315a57eea1c37c542c1d87b23b003a86167526544ea50e7f27bf2",
        )
        self.assertEqual(
            stu0051.feature_historical_executable_ids,
            (
                "executable:"
                "ff53b8828db4e61c1fbdfaccf84d7d8b3493c2e796e19cd1fddf50bb23e94137",
            ),
        )
        stu0032 = STU0032_HISTORICAL_FAMILY.control_for_historical_executable(
            STU0032_HISTORICAL_FAMILY.target_historical_executable_id
        )
        self.assertEqual(
            stu0032.opposite_historical_executable_id,
            "executable:"
            "5b8a1956bb784b766619bc27ae8ae2ca88c25d226f4be5a670109e920fd1f194",
        )
        self.assertEqual(
            stu0032.feature_historical_executable_ids,
            (
                "executable:"
                "207c5f73e29da57e73fc5206f81e0cad483d75ae98b0941f660a7ef713bad09c",
                "executable:"
                "3c35c426ca91dcd11de6fc9e1a74ef8f4678a6ead26d8c91c9dc32fc8beb5f9a",
            ),
        )

    def test_builtin_controls_match_profile_sign_and_horizon_semantics(self) -> None:
        for family_spec in ALL_P1_HISTORICAL_FAMILY_CATALOG:
            by_id = {
                item.historical_reference_executable_id: item
                for item in family_spec.members
            }
            for control in family_spec.controls:
                subject = by_id[control.subject_historical_executable_id]
                opposite = by_id[control.opposite_historical_executable_id]
                subject_parameters = subject.parameter_values()
                opposite_parameters = opposite.parameter_values()
                self.assertEqual(
                    opposite_parameters["profile"],
                    subject_parameters["profile"],
                )
                self.assertEqual(
                    opposite_parameters["holding_bars"],
                    subject_parameters["holding_bars"],
                )
                self.assertEqual(
                    opposite_parameters["signal_sign"],
                    -subject_parameters["signal_sign"],
                )
                for feature_id in control.feature_historical_executable_ids:
                    feature_parameters = by_id[feature_id].parameter_values()
                    self.assertNotEqual(
                        feature_parameters["profile"],
                        subject_parameters["profile"],
                    )
                    self.assertEqual(
                        feature_parameters["holding_bars"],
                        subject_parameters["holding_bars"],
                    )
                    self.assertEqual(
                        feature_parameters["signal_sign"],
                        subject_parameters["signal_sign"],
                    )

    def test_member_has_one_historical_identity_and_frozen_parameters(self) -> None:
        parameters = {
            "nested": {"values": [1, "value"]},
            "profile": "profile-a",
        }
        value = member(1, 1, parameters=parameters)
        parameters["profile"] = "mutated"
        detached = value.parameter_values()
        detached["profile"] = "also-mutated"
        self.assertEqual(value.parameter_values()["profile"], "profile-a")
        self.assertEqual(
            executable_values(value.manifest()),
            (value.historical_reference_executable_id,),
        )
        with self.assertRaisesRegex(
            HistoricalFamilyReplayError, "another Executable identity"
        ):
            member(1, 1, parameters={"peer": executable(2)})
        with self.assertRaisesRegex(
            HistoricalFamilyReplayError, "one authoritative field"
        ):
            member(
                1,
                1,
                parameters={"historical_reference_executable_id": "peer"},
            )

    def test_ascii_and_canonical_parameter_boundaries_fail_closed(self) -> None:
        with self.assertRaisesRegex(HistoricalFamilyReplayError, "ASCII"):
            member(1, 1, configuration_id="configuration-non-ascii-\u2603")
        with self.assertRaisesRegex(HistoricalFamilyReplayError, "ASCII"):
            member(1, 1, parameters={"profile": "non-ascii-\u2603"})
        with self.assertRaisesRegex(HistoricalFamilyReplayError, "canonical"):
            member(1, 1, parameters={"threshold": 0.5})
        with self.assertRaisesRegex(HistoricalFamilyReplayError, "STU-"):
            family(study_id="study-9001")
        with self.assertRaisesRegex(HistoricalFamilyReplayError, "lowercase"):
            HistoricalMemberSpec(
                ordinal=1,
                configuration_id="configuration-1",
                historical_reference_executable_id="executable:" + "A" * 64,
                parameters={"profile": "profile-1"},
            )

    def test_member_order_is_ordinal_bound_not_tuple_position(self) -> None:
        expected = family()
        reordered = family(
            members=tuple(reversed(expected.members)),
            controls=tuple(reversed(expected.controls)),
        )
        self.assertEqual(reordered.manifest(), expected.manifest())
        self.assertEqual(reordered.identity, expected.identity)
        feature_controls = ControlBinding(
            subject_historical_executable_id=executable(1),
            opposite_historical_executable_id=executable(2),
            feature_historical_executable_ids=(executable(4), executable(3)),
        )
        self.assertEqual(
            feature_controls.feature_historical_executable_ids,
            (executable(3), executable(4)),
        )

    def test_member_duplicates_and_ordinal_gaps_are_rejected(self) -> None:
        base = four_members()
        cases = (
            (
                (base[0], member(1, 2), base[2], base[3]),
                "ordinals",
            ),
            (
                (
                    base[0],
                    member(2, 2, configuration_id=base[0].configuration_id),
                    base[2],
                    base[3],
                ),
                "configuration ids",
            ),
            (
                (base[0], member(2, 1), base[2], base[3]),
                "exactly one member",
            ),
            (
                (base[0], base[1], member(4, 3), base[3]),
                "ordinals",
            ),
        )
        for members, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(
                    HistoricalFamilyReplayError, message
                ):
                    family(members=members)

    def test_control_set_must_cover_only_exact_members(self) -> None:
        with self.assertRaisesRegex(
            HistoricalFamilyReplayError, "one exact control binding"
        ):
            family(controls=four_controls()[:-1])
        controls = list(four_controls())
        controls[0] = ControlBinding(
            subject_historical_executable_id=executable(1),
            opposite_historical_executable_id=executable(2),
            feature_historical_executable_ids=(executable(99),),
        )
        with self.assertRaisesRegex(
            HistoricalFamilyReplayError, "exact family members"
        ):
            family(controls=tuple(controls))
        controls = list(four_controls())
        controls[0] = ControlBinding(
            subject_historical_executable_id=executable(1),
            opposite_historical_executable_id=executable(3),
            feature_historical_executable_ids=(executable(4),),
        )
        with self.assertRaisesRegex(
            HistoricalFamilyReplayError, "reciprocal"
        ):
            family(controls=tuple(controls))

    def test_control_binding_rejects_self_overlap_and_duplicates(self) -> None:
        with self.assertRaisesRegex(HistoricalFamilyReplayError, "distinct"):
            ControlBinding(
                subject_historical_executable_id=executable(1),
                opposite_historical_executable_id=executable(1),
                feature_historical_executable_ids=(executable(3),),
            )
        with self.assertRaisesRegex(HistoricalFamilyReplayError, "unique"):
            ControlBinding(
                subject_historical_executable_id=executable(1),
                opposite_historical_executable_id=executable(2),
                feature_historical_executable_ids=(
                    executable(3),
                    executable(3),
                ),
            )
        with self.assertRaisesRegex(HistoricalFamilyReplayError, "distinct"):
            ControlBinding(
                subject_historical_executable_id=executable(1),
                opposite_historical_executable_id=executable(2),
                feature_historical_executable_ids=(executable(2),),
            )

    def test_catalog_rejects_cross_family_historical_identity_reuse(self) -> None:
        first = family(study_id="STU-9001", batch_token=1)
        second = family(study_id="STU-9002", batch_token=2)
        with self.assertRaisesRegex(
            HistoricalFamilyReplayError, "multiple families"
        ):
            historical_family_catalog((second, first))
        with self.assertRaisesRegex(
            HistoricalFamilyReplayError, "original Study ids"
        ):
            historical_family_catalog((first, first))


if __name__ == "__main__":
    unittest.main()
