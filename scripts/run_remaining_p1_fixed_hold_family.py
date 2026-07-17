"""Run one exact four-member family from the remaining P1 audit queue.

The runner keeps one reusable execution surface for STU-0046, STU-0047,
STU-0049, and STU-0050.  Callers provide the exact stable-head boundary and
natural Study identity.  Every route borrows the active Initiative, records
all four obligation assignments, and declares explicit lineage from the
original historical Study without transferring its scientific verdict.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from axiom_rift.operations.drawdown_fixed_hold_profile import (  # noqa: E402
    build_drawdown_fixed_hold_profile_design,
)
from axiom_rift.operations.fixed_hold_replay_cli import (  # noqa: E402
    run_fixed_hold_replay_command,
)
from axiom_rift.operations.fixed_hold_replay_profile import (  # noqa: E402
    require_borrowed_production_profile,
)
from axiom_rift.operations.fixed_hold_replay_workflow import (  # noqa: E402
    FixedHoldReplayMissionSpec,
    ReplayAuthorityBoundary,
    ReplayAxisAdmission,
    ReplayInitiativeLifecycle,
)
from axiom_rift.operations.gap_fixed_hold_profile import (  # noqa: E402
    build_gap_fixed_hold_profile_design,
)
from axiom_rift.operations.volatility_duration_fixed_hold_profile import (  # noqa: E402
    build_volatility_duration_fixed_hold_profile_design,
)
from axiom_rift.operations.writer import StateWriter  # noqa: E402
from axiom_rift.research.portfolio import PortfolioAction  # noqa: E402
from axiom_rift.research.drawdown_state_replay_job import (  # noqa: E402
    CALLABLE_IDENTITY as DRAWDOWN_CALLABLE_IDENTITY,
    JOB_IMPLEMENTATION_PROTOCOL as DRAWDOWN_JOB_PROTOCOL,
    drawdown_replay_job_implementation_sha256,
    execute_drawdown_state_replay_job,
    materialize_drawdown_replay_job_implementation,
)
from axiom_rift.research.gap_fixed_hold_job import (  # noqa: E402
    CALLABLE_IDENTITY as GAP_CALLABLE_IDENTITY,
    JOB_IMPLEMENTATION_PROTOCOL as GAP_JOB_PROTOCOL,
    execute_gap_fixed_hold_job,
    gap_fixed_hold_job_implementation_sha256,
    materialize_gap_fixed_hold_job_implementation,
)
from axiom_rift.research.semantic_question import (  # noqa: E402
    SemanticQuestionCore,
    SemanticQuestionLineageProposal,
    SemanticQuestionRelation,
)
from axiom_rift.research.volatility_duration_fixed_hold_job import (  # noqa: E402
    CALLABLE_IDENTITY as VOLATILITY_CALLABLE_IDENTITY,
    JOB_IMPLEMENTATION_PROTOCOL as VOLATILITY_JOB_PROTOCOL,
    execute_volatility_duration_fixed_hold_job,
    materialize_volatility_duration_fixed_hold_job_implementation,
    volatility_duration_fixed_hold_job_implementation_sha256,
)


MISSION_ID = "MIS-0006"
INITIATIVE_ID = "INI-0025"
PERMIT_EXPIRY_UTC = "2027-12-31T23:59:59Z"
GAP_BRIDGE_AXIS_ID = "axis-stu0032-distribution-asymmetry-replay-bridge"


@dataclass(frozen=True, slots=True)
class FamilyRoute:
    name: str
    original_study_id: str
    original_core_id: str
    original_close_record_id: str
    primary_obligation_id: str
    additional_obligation_ids: tuple[str, ...]
    primary_family_authority_id: str
    additional_family_authority_ids: tuple[str, ...]
    axis_id: str
    bridge_axis_id: str
    operation_prefix: str
    decision_prefix: str
    display_name: str
    job_protocol: str
    callable_identity: str
    implementation_identity_builder: Callable[[], str]
    profile_builder: Callable[..., Any]
    job_runner: Callable[..., Any]
    implementation_materializer: Callable[[StateWriter], str]

    def __post_init__(self) -> None:
        if (
            self.additional_obligation_ids
            != tuple(sorted(set(self.additional_obligation_ids)))
            or self.primary_obligation_id in self.additional_obligation_ids
            or self.additional_family_authority_ids
            != tuple(sorted(set(self.additional_family_authority_ids)))
            or self.primary_family_authority_id
            in self.additional_family_authority_ids
            or len(self.additional_obligation_ids) != 3
            or len(self.additional_family_authority_ids) != 3
        ):
            raise ValueError("remaining P1 route does not bind one exact family")


FAMILY_ROUTES = {
    "stu0046": FamilyRoute(
        name="stu0046",
        original_study_id="STU-0046",
        original_core_id=(
            "semantic-question-core:"
            "e9c1178e4ff274a88fe9fb4459afa04d988b4a1496fbf9dbc05a49ccee6a524f"
        ),
        original_close_record_id=(
            "034fa48eb86ad81faf84528a7956276794af707bb67c7a1421d21ff00cb6e82c"
        ),
        primary_obligation_id=(
            "historical-replay-obligation:"
            "9e01b7b2d1056e667f00ef2694791acb47d97c71f119a589d47d7c114cf26655"
        ),
        additional_obligation_ids=tuple(sorted((
            "historical-replay-obligation:159a599340c95f130c1b674344557a0312219b76c16b863cae4bf228f0769d94",
            "historical-replay-obligation:2580acb5b07384e277bc51747e78c56c765640bbb0e431b4270f2acd3365ac30",
            "historical-replay-obligation:9bbcca0175b84c00c68ea37b98e18f31d60e808b58793ac75bf1f8b9388fc7b6",
        ))),
        primary_family_authority_id=(
            "historical-family-authority:"
            "0ba4b3572cf9c40d2e93b8bf7b34cf3ade0d53b1f194d5a3440c14605ffbd37e"
        ),
        additional_family_authority_ids=tuple(sorted((
            "historical-family-authority:3e516ad3d0eded0868140717708ab719e862a54c90c1155cd9ef0bc1f87c7e95",
            "historical-family-authority:49cf22ebbb0aacfb8a95b8a844cd81ae9c56a52f608e800684a3ae9d7fb8247d",
            "historical-family-authority:72ac28a5d7aca3baa48722e938499ec3282db3a59702d1c11a3d1dc455ea5ee9",
        ))),
        axis_id="axis-stu0046-gap-event-replay-bridge",
        bridge_axis_id=GAP_BRIDGE_AXIS_ID,
        operation_prefix="p1-stu0046-gap-event-replay-v1-",
        decision_prefix="DEC-P1-STU0046-GAP-EVENT",
        display_name="STU-0046 exact prospective gap-event replay family",
        job_protocol=GAP_JOB_PROTOCOL,
        callable_identity=GAP_CALLABLE_IDENTITY,
        implementation_identity_builder=gap_fixed_hold_job_implementation_sha256,
        profile_builder=build_gap_fixed_hold_profile_design,
        job_runner=execute_gap_fixed_hold_job,
        implementation_materializer=materialize_gap_fixed_hold_job_implementation,
    ),
    "stu0047": FamilyRoute(
        name="stu0047",
        original_study_id="STU-0047",
        original_core_id=(
            "semantic-question-core:"
            "c8785e0d39449ed49928eb9cd2adeb8d9f3b9249f9f155b052f105d9587e4f35"
        ),
        original_close_record_id=(
            "fa2d90034a195cf0b14722363ccf56a3338fd794e2c28d3e78019d63baf275cb"
        ),
        primary_obligation_id=(
            "historical-replay-obligation:"
            "d6926257f10fbfeaffa1a5c31c7ac89a7e68bd350bb25d59af3f1f111220da8e"
        ),
        additional_obligation_ids=tuple(sorted((
            "historical-replay-obligation:671cfce27c8d763e8238fdd15c9e4dd00c04450c789dc96d8d18eddd98d5037f",
            "historical-replay-obligation:be4867b5989b526eebd033d0ccac666df45580d887585bb3afca7e55125d0efe",
            "historical-replay-obligation:c9fb9597dc1fc432d1a9185f9e0b0c7b7539824cb8013e1d67091f63b0dadb1f",
        ))),
        primary_family_authority_id=(
            "historical-family-authority:"
            "c58bf23ba6ac95a9fe5c9283d2d4bb2fe4334a661147ecf50ab0a153afb6e5d1"
        ),
        additional_family_authority_ids=tuple(sorted((
            "historical-family-authority:10d8f52e164b019d5d5d75c6a66e6f0ec5241ec2e8eab8450142c4395fbfbeb0",
            "historical-family-authority:25aba45822fa44dd45ee8663f1113c2ff8c6bd2cd737d81f3802a90007358c56",
            "historical-family-authority:8d1929c8966fa6886a249199358dc138f7dec5e4d7256c7b0e9c11a1892408bb",
        ))),
        axis_id="axis-stu0047-post-gap-path-replay-bridge",
        bridge_axis_id=GAP_BRIDGE_AXIS_ID,
        operation_prefix="p1-stu0047-post-gap-path-replay-v1-",
        decision_prefix="DEC-P1-STU0047-GAP-PATH",
        display_name="STU-0047 exact prospective post-gap-path replay family",
        job_protocol=GAP_JOB_PROTOCOL,
        callable_identity=GAP_CALLABLE_IDENTITY,
        implementation_identity_builder=gap_fixed_hold_job_implementation_sha256,
        profile_builder=build_gap_fixed_hold_profile_design,
        job_runner=execute_gap_fixed_hold_job,
        implementation_materializer=materialize_gap_fixed_hold_job_implementation,
    ),
    "stu0049": FamilyRoute(
        name="stu0049",
        original_study_id="STU-0049",
        original_core_id=(
            "semantic-question-core:"
            "4f4da2f8ae22cd625eb2ec5e91028850c90c48bc43a945cb952f9bf0a8d212f7"
        ),
        original_close_record_id=(
            "ae799f284c6f4893f9ece22f3249cca18d391e51c2dbcefb39eea1436eabdd7e"
        ),
        primary_obligation_id=(
            "historical-replay-obligation:"
            "c2474c4b772dfa0f59407b5dfc6b89f71becfa6ba9587f465b26dba4a5b2bc84"
        ),
        additional_obligation_ids=tuple(sorted((
            "historical-replay-obligation:2e10d2ca5b2edf2eab10e03f4a6e397062248a1c763e0a154f172af5740eefe9",
            "historical-replay-obligation:60f4c9cf299a9b96fb1bf343d0c72276fa0b8754d6a32a421265a2f135c19274",
            "historical-replay-obligation:e267830fc7cb3fca62d331c40fca836f4c6c624722dd121a0c6e2e0950d36151",
        ))),
        primary_family_authority_id=(
            "historical-family-authority:"
            "d6b96beb77ed02c7a6447579d57c415db5f6de395f088056922edc91dd67771e"
        ),
        additional_family_authority_ids=tuple(sorted((
            "historical-family-authority:14c887e4171a4be0d0ed31c4d428081396bedfd9160a57728229b349711362ab",
            "historical-family-authority:4878dcc4f84cd8c4808613fcd2207229703a297b927e69d50f858f28d819678e",
            "historical-family-authority:de86e21862f2c8c4854fc5b08022db50aa3f995544ffab3e9d1c4578579c8fea",
        ))),
        axis_id="axis-stu0049-drawdown-phase-replay-bridge",
        bridge_axis_id="axis-stu0048-drawdown-state-replay-bridge",
        operation_prefix="p1-stu0049-drawdown-phase-replay-v1-",
        decision_prefix="DEC-P1-STU0049-DRAWDOWN-PHASE",
        display_name="STU-0049 exact prospective drawdown-phase replay family",
        job_protocol=DRAWDOWN_JOB_PROTOCOL,
        callable_identity=DRAWDOWN_CALLABLE_IDENTITY,
        implementation_identity_builder=drawdown_replay_job_implementation_sha256,
        profile_builder=build_drawdown_fixed_hold_profile_design,
        job_runner=execute_drawdown_state_replay_job,
        implementation_materializer=materialize_drawdown_replay_job_implementation,
    ),
    "stu0050": FamilyRoute(
        name="stu0050",
        original_study_id="STU-0050",
        original_core_id=(
            "semantic-question-core:"
            "640d66a54391484153ad17d42120a5e13bb97ea865fec959257ad62394c9067c"
        ),
        original_close_record_id=(
            "7d246009e2ded235314d86b5ffd1aa8e1007439c398b6c9309a8d8537372f886"
        ),
        primary_obligation_id=(
            "historical-replay-obligation:"
            "17e4b86d8538c0dbd3b644ce1e3e33dc64e10d22c9dba419488bcd80187e6be5"
        ),
        additional_obligation_ids=tuple(sorted((
            "historical-replay-obligation:9d06939dcc26075efbb0c9e081ed060a8ea84f8e19a65e320139df6c22b0580a",
            "historical-replay-obligation:a635a46426c85fe4fb9e4426270bd36fd902ef1f0e1da351d0beb41ba5d7451d",
            "historical-replay-obligation:ac58c5a2bc7a885edc771416afc82a6fda26cf3404b3389bffc71ccc8d941685",
        ))),
        primary_family_authority_id=(
            "historical-family-authority:"
            "f71a63008c0428c4d01017d955b287794485033be094829447cf703864888514"
        ),
        additional_family_authority_ids=tuple(sorted((
            "historical-family-authority:44927666c0aab94fcb8fe02a3c8d65787d76b3badc4fcd1462d3b705ec4d2a34",
            "historical-family-authority:d8f18b31702054bd2aed55d9550af168a5c74e8994bc120e9b2b73059f3ce5d5",
            "historical-family-authority:f7ae433a5b7fdcb52ae68e85717bdf932f5a84355723e7889696fa64267efe87",
        ))),
        axis_id="axis-stu0050-volatility-level-duration-replay-bridge",
        bridge_axis_id="axis-stu0051-volatility-duration-replay-bridge",
        operation_prefix="p1-stu0050-volatility-level-duration-replay-v1-",
        decision_prefix="DEC-P1-STU0050-VOLATILITY-LEVEL-DURATION",
        display_name=(
            "STU-0050 exact prospective volatility level-duration replay family"
        ),
        job_protocol=VOLATILITY_JOB_PROTOCOL,
        callable_identity=VOLATILITY_CALLABLE_IDENTITY,
        implementation_identity_builder=(
            volatility_duration_fixed_hold_job_implementation_sha256
        ),
        profile_builder=build_volatility_duration_fixed_hold_profile_design,
        job_runner=execute_volatility_duration_fixed_hold_job,
        implementation_materializer=(
            materialize_volatility_duration_fixed_hold_job_implementation
        ),
    ),
}


@dataclass(frozen=True, slots=True)
class RunAuthority:
    route: FamilyRoute
    study_id: str
    batch_display_id: str
    predecessor_revision: int
    predecessor_event_id: str


def parse_arguments(
    argv: Sequence[str] | None,
) -> tuple[RunAuthority, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--family", choices=tuple(FAMILY_ROUTES), required=True)
    parser.add_argument("--study-id", required=True)
    parser.add_argument("--batch-display-id", required=True)
    parser.add_argument("--predecessor-revision", type=int, required=True)
    parser.add_argument("--predecessor-event-id", required=True)
    arguments, remaining = parser.parse_known_args(argv)
    expected_batch = "BAT-" + arguments.study_id.removeprefix("STU-")
    if arguments.batch_display_id != expected_batch:
        raise RuntimeError("remaining P1 Study and Batch display ids diverged")
    return (
        RunAuthority(
            route=FAMILY_ROUTES[arguments.family],
            study_id=arguments.study_id,
            batch_display_id=arguments.batch_display_id,
            predecessor_revision=arguments.predecessor_revision,
            predecessor_event_id=arguments.predecessor_event_id,
        ),
        remaining,
    )


def mission_spec(authority: RunAuthority) -> FixedHoldReplayMissionSpec:
    route = authority.route
    return FixedHoldReplayMissionSpec(
        axis_admission=ReplayAxisAdmission.ADD_NEW_MECHANISM,
        new_axis_action=PortfolioAction.CONTRAST,
        initiative_lifecycle=ReplayInitiativeLifecycle.BORROW_ACTIVE_INITIATIVE,
        mission_id=MISSION_ID,
        initiative_id=INITIATIVE_ID,
        study_id=authority.study_id,
        batch_display_id=authority.batch_display_id,
        axis_id=route.axis_id,
        bridge_axis_id=route.bridge_axis_id,
        operation_prefix=route.operation_prefix,
        decision_prefix=route.decision_prefix,
        target_obligation_id=route.primary_obligation_id,
        additional_obligation_ids=route.additional_obligation_ids,
        original_study_id=route.original_study_id,
        job_protocol=route.job_protocol,
        callable_identity=route.callable_identity,
        job_implementation_identity=route.implementation_identity_builder(),
        permit_expiry_utc=PERMIT_EXPIRY_UTC,
        boundary=ReplayAuthorityBoundary(
            sequence=authority.predecessor_revision,
            event_id=authority.predecessor_event_id,
        ),
        display_name=route.display_name,
    )


def _profile_design(
    writer: StateWriter,
    *,
    authority: RunAuthority,
    lineage: SemanticQuestionLineageProposal | None,
):
    route = authority.route
    return route.profile_builder(
        writer,
        spec=mission_spec(authority),
        historical_family_authority_id=route.primary_family_authority_id,
        additional_historical_family_authority_ids=(
            route.additional_family_authority_ids
        ),
        semantic_question_lineage=lineage,
    )


def build_design(writer: StateWriter, authority: RunAuthority):
    route = authority.route
    preliminary = _profile_design(
        writer,
        authority=authority,
        lineage=None,
    )
    successor_core_id = SemanticQuestionCore.from_question_manifest(
        preliminary.question
    ).identity
    relation = (
        SemanticQuestionRelation.CONTINUATION
        if successor_core_id == route.original_core_id
        else SemanticQuestionRelation.SEMANTIC_REVISION
    )
    lineage = SemanticQuestionLineageProposal(
        predecessor_study_id=route.original_study_id,
        successor_study_id=authority.study_id,
        predecessor_core_id=route.original_core_id,
        successor_core_id=successor_core_id,
        relation=relation,
        rationale=(
            "Replace the audit-invalid historical decision-input proof with "
            "one exact prospective four-member family evaluation without "
            "transferring the historical scientific verdict."
        ),
        basis_record_ids=(
            f"study-open:{route.original_study_id}",
            f"study-close:{route.original_close_record_id}",
        ),
    )
    design = _profile_design(
        writer,
        authority=authority,
        lineage=lineage,
    )
    return require_borrowed_production_profile(writer, design)


def main(argv: Sequence[str] | None = None) -> None:
    authority, remaining = parse_arguments(argv)
    summary = run_fixed_hold_replay_command(
        repository_root=ROOT,
        design_builder=lambda writer: build_design(writer, authority),
        job_runner=authority.route.job_runner,
        job_implementation_materializer=(
            authority.route.implementation_materializer
        ),
        study_id=authority.study_id,
        argv=remaining,
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
