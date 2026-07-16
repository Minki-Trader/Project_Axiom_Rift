from __future__ import annotations

import unittest

from axiom_rift.research.semantic_question import (
    SEMANTIC_QUESTION_CORE_SCHEMA,
    SemanticQuestionCore,
    SemanticQuestionEquivalenceProposal,
    SemanticQuestionError,
    SemanticQuestionLineageProposal,
    SemanticQuestionRelation,
)


def question(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "causal_question": (
            "Does a fixed causal market residual event create stable utility "
            "beyond a target-only control?"
        ),
        "changed_variables": ["feature", "trade"],
        "controlled_variables": ["execution", "risk"],
        "done_conditions": ["register three Executables"],
        "evidence_modes": ["causal_contrast", "cost_and_execution"],
        "axis_id": "axis-market-residual-synthesis",
        "mechanism_family": "market_residual_event",
        "primary_research_layer": "synthesis",
        "chassis": {"identity": "architecture-family:" + "a" * 64},
    }
    value.update(changes)
    return value


class SemanticQuestionCoreTests(unittest.TestCase):
    def test_same_semantics_ignore_protocol_and_canonicalize_order(self) -> None:
        first = SemanticQuestionCore.from_question_manifest(
            question(
                causal_question=(
                    "  Does a fixed causal market residual event\n"
                    "create stable utility\tbeyond a target-only control?  "
                ),
                changed_variables=["trade", "feature"],
                controlled_variables=["risk", "execution"],
            )
        )
        second = SemanticQuestionCore.from_question_manifest(
            question(
                done_conditions=["reuse one baseline and register two subjects"],
                evidence_modes=[
                    "causal_contrast",
                    "cost_and_execution",
                    "sensitivity_or_stress",
                ],
                axis_id="axis-market-residual-portfolio",
                mechanism_family="market_residual_portfolio",
                primary_research_layer="portfolio",
                chassis={"identity": "architecture-family:" + "b" * 64},
            )
        )

        self.assertEqual(first.identity, second.identity)
        self.assertEqual(first.to_identity_payload(), second.to_identity_payload())
        self.assertEqual(
            first.causal_question,
            "Does a fixed causal market residual event create stable utility "
            "beyond a target-only control?",
        )
        self.assertEqual(first.changed_variables, ("feature", "trade"))
        self.assertEqual(first.controlled_variables, ("execution", "risk"))
        self.assertEqual(
            first.to_identity_payload()["schema"], SEMANTIC_QUESTION_CORE_SCHEMA
        )
        self.assertRegex(
            first.identity, r"^semantic-question-core:[0-9a-f]{64}$"
        )

    def test_semantic_field_changes_create_distinct_cores(self) -> None:
        baseline = SemanticQuestionCore.from_question_manifest(question())
        variants = (
            question(
                causal_question=(
                    "Does a fixed causal market residual event create stable "
                    "continuation utility beyond a target-only control?"
                )
            ),
            question(changed_variables=["feature", "selector", "trade"]),
            question(controlled_variables=["execution", "lifecycle", "risk"]),
        )
        for variant in variants:
            with self.subTest(variant=variant):
                observed = SemanticQuestionCore.from_question_manifest(variant)
                self.assertNotEqual(observed.identity, baseline.identity)

    def test_identity_payload_round_trips_only_in_canonical_form(self) -> None:
        core = SemanticQuestionCore.from_question_manifest(question())
        rebuilt = SemanticQuestionCore.from_identity_payload(
            core.to_identity_payload()
        )
        self.assertEqual(rebuilt.identity, core.identity)

        noncanonical = core.to_identity_payload()
        noncanonical["changed_variables"] = ["trade", "feature"]
        with self.assertRaisesRegex(SemanticQuestionError, "not canonical"):
            SemanticQuestionCore.from_identity_payload(noncanonical)

    def test_invalid_core_inputs_fail_closed(self) -> None:
        invalid = (
            question(changed_variables=["feature", "feature"]),
            question(
                changed_variables=["feature", "risk"],
                controlled_variables=["execution", "risk"],
            ),
            question(changed_variables=[" feature", "trade"]),
            question(causal_question="\uacfc\ud559\uc801 \uc9c8\ubb38"),
            question(controlled_variables=[]),
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(SemanticQuestionError):
                    SemanticQuestionCore.from_question_manifest(value)

        with self.assertRaisesRegex(SemanticQuestionError, "lacks"):
            SemanticQuestionCore.from_question_manifest(
                {"causal_question": "Is the question complete?"}
            )

    def test_stu0097_and_stu0098_exact_history_share_one_core(self) -> None:
        shared = {
            "causal_question": (
                "Does a fixed causal fold-train US100-US500 market residual "
                "event create stable six-bar mean-reversion utility beyond a "
                "source-bound target-only mean-reversion control after native "
                "and stressed costs?"
            ),
            "changed_variables": [
                "fold-train OLS US500 beta with one intercept and no parameter grid",
                "completed twelve-bar US100 market residual versus target-only return",
                "residual mean reversion primary subject with continuation direction control",
            ],
            "controlled_variables": [
                "same exact current US500 SourceContract and SourcePermit",
                "same observed development material and nine rolling folds",
                "same exact timestamp inner alignment without fill asof or offset inference",
                "same fixed top-decile train-only absolute selector",
                "same fixed six-bar nonoverlap next-open lifecycle",
                "same fixed one lot and native plus stressed FPMarkets costs",
                "same target-only source-bound but source-value-independent control",
                "global selection exposure total 592",
                "no beta lookback selector holding direction or source grid",
                "no activity quota holdout candidate or live authority",
            ],
            "evidence_modes": [
                "causal_contrast",
                "cost_and_execution",
                "extreme_or_boundary",
                "regime_stability",
                "sensitivity_or_stress",
                "temporal_stability",
            ],
        }
        stu0097 = {
            **shared,
            "done_conditions": [
                "register exactly three fixed Executables before source performance values"
            ],
            "axis_id": "axis-market-residual-event-synthesis",
            "primary_research_layer": "synthesis",
            "controlled_chassis_identity": "controlled-chassis:" + "9" * 64,
        }
        stu0098 = {
            **shared,
            "done_conditions": [
                "reuse the exact baseline and register two residual Executables before source performance values"
            ],
            "axis_id": "axis-market-residual-event-portfolio",
            "primary_research_layer": "portfolio",
            "controlled_chassis_identity": "controlled-chassis:" + "5" * 64,
        }
        first = SemanticQuestionCore.from_question_manifest(stu0097)
        second = SemanticQuestionCore.from_question_manifest(stu0098)
        self.assertEqual(first.identity, second.identity)
        self.assertEqual(
            first.identity,
            "semantic-question-core:"
            "19ba9f5f24519fbc4797598d23081f3a5f0b636071afa2e0a805ee02d356edc5",
        )


class SemanticQuestionEquivalenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.canonical = SemanticQuestionCore.from_question_manifest(question())
        self.equivalent = SemanticQuestionCore.from_question_manifest(
            question(
                causal_question=(
                    "Against a target-only control, does the fixed causal market "
                    "residual event create stable utility?"
                )
            )
        )

    def test_explicit_equivalence_is_typed_canonical_and_round_trippable(
        self,
    ) -> None:
        proposal = SemanticQuestionEquivalenceProposal(
            canonical_study_id="STU-0097",
            equivalent_study_id="STU-0098",
            canonical_core_id=self.canonical.identity,
            equivalent_core_id=self.equivalent.identity,
            rationale="  Expert review confirms the same estimand.\n",
            basis_record_ids=(
                "quant-team-review:" + "b" * 64,
                "audit-finding:" + "a" * 64,
            ),
        )
        self.assertEqual(
            proposal.basis_record_ids,
            (
                "audit-finding:" + "a" * 64,
                "quant-team-review:" + "b" * 64,
            ),
        )
        self.assertEqual(
            proposal.rationale, "Expert review confirms the same estimand."
        )
        self.assertRegex(
            proposal.identity,
            r"^semantic-question-equivalence:[0-9a-f]{64}$",
        )
        rebuilt = SemanticQuestionEquivalenceProposal.from_identity_payload(
            proposal.to_identity_payload()
        )
        self.assertEqual(rebuilt.identity, proposal.identity)

    def test_relation_enum_has_the_closed_expected_surface(self) -> None:
        self.assertEqual(
            {relation.value for relation in SemanticQuestionRelation},
            {
                "engineering_reentry",
                "continuation",
                "independent_replication",
                "confirmation",
                "semantic_revision",
            },
        )

    def test_invalid_equivalence_is_rejected(self) -> None:
        valid = {
            "canonical_study_id": "STU-0097",
            "equivalent_study_id": "STU-0098",
            "canonical_core_id": self.canonical.identity,
            "equivalent_core_id": self.equivalent.identity,
            "rationale": "Exact expert adjudication binds the two cores.",
            "basis_record_ids": ("quant-team-review:" + "c" * 64,),
        }
        invalid_changes = (
            {
                "equivalent_core_id": self.canonical.identity,
            },
            {
                "basis_record_ids": (),
            },
            {
                "canonical_core_id": "semantic-question-core:not-a-digest",
            },
            {
                "canonical_core_id": " " + self.canonical.identity,
            },
            {
                "equivalent_study_id": "STU-0097",
            },
            {
                "canonical_study_id": " STU-0097",
            },
        )
        for changes in invalid_changes:
            with self.subTest(changes=changes):
                values = {**valid, **changes}
                with self.assertRaises(SemanticQuestionError):
                    SemanticQuestionEquivalenceProposal(**values)

        payload = SemanticQuestionEquivalenceProposal(**valid).to_identity_payload()
        payload["automatic_similarity_score"] = 1
        with self.assertRaisesRegex(SemanticQuestionError, "malformed"):
            SemanticQuestionEquivalenceProposal.from_identity_payload(payload)


class SemanticQuestionLineageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.first = SemanticQuestionCore.from_question_manifest(question())
        self.second = SemanticQuestionCore.from_question_manifest(
            question(controlled_variables=["execution", "risk", "trial accounting"])
        )
        self.basis = ("study-open:STU-0097", "study-open:STU-0098")
        self.predecessor_study_id = "STU-0097"
        self.successor_study_id = "STU-0098"

    def test_same_core_engineering_reentry_needs_no_equivalence(self) -> None:
        proposal = SemanticQuestionLineageProposal(
            predecessor_study_id=self.predecessor_study_id,
            successor_study_id=self.successor_study_id,
            predecessor_core_id=self.first.identity,
            successor_core_id=self.first.identity,
            relation=SemanticQuestionRelation.ENGINEERING_REENTRY,
            rationale=(
                "The predecessor ended in an engineering gap before scientific "
                "evaluation."
            ),
            basis_record_ids=self.basis,
        )
        self.assertIsNone(proposal.equivalence_proposal_id)
        self.assertRegex(
            proposal.identity, r"^semantic-question-lineage:[0-9a-f]{64}$"
        )
        rebuilt = SemanticQuestionLineageProposal.from_identity_payload(
            proposal.to_identity_payload()
        )
        self.assertEqual(rebuilt.identity, proposal.identity)

    def test_different_exact_cores_require_explicit_equivalence(self) -> None:
        with self.assertRaisesRegex(SemanticQuestionError, "explicit equivalence"):
            SemanticQuestionLineageProposal(
                predecessor_study_id=self.predecessor_study_id,
                successor_study_id=self.successor_study_id,
                predecessor_core_id=self.first.identity,
                successor_core_id=self.second.identity,
                relation=SemanticQuestionRelation.CONTINUATION,
                rationale="Accounting-only wording changed between retries.",
                basis_record_ids=self.basis,
            )

        equivalence = SemanticQuestionEquivalenceProposal(
            canonical_study_id=self.predecessor_study_id,
            equivalent_study_id=self.successor_study_id,
            canonical_core_id=self.first.identity,
            equivalent_core_id=self.second.identity,
            rationale="Typed review isolates an accounting-only wording change.",
            basis_record_ids=self.basis,
        )
        proposal = SemanticQuestionLineageProposal(
            predecessor_study_id=self.predecessor_study_id,
            successor_study_id=self.successor_study_id,
            predecessor_core_id=self.first.identity,
            successor_core_id=self.second.identity,
            relation=SemanticQuestionRelation.CONTINUATION,
            rationale="Continue the same estimand after explicit reconciliation.",
            basis_record_ids=self.basis,
            equivalence_proposal_id=equivalence.identity,
        )
        self.assertEqual(proposal.equivalence_proposal_id, equivalence.identity)

    def test_semantic_revision_must_be_distinct_and_non_equivalent(self) -> None:
        with self.assertRaisesRegex(SemanticQuestionError, "distinct"):
            SemanticQuestionLineageProposal(
                predecessor_study_id=self.predecessor_study_id,
                successor_study_id=self.successor_study_id,
                predecessor_core_id=self.first.identity,
                successor_core_id=self.first.identity,
                relation=SemanticQuestionRelation.SEMANTIC_REVISION,
                rationale="A revision cannot retain the exact same core.",
                basis_record_ids=self.basis,
            )

        equivalence = SemanticQuestionEquivalenceProposal(
            canonical_study_id=self.predecessor_study_id,
            equivalent_study_id=self.successor_study_id,
            canonical_core_id=self.first.identity,
            equivalent_core_id=self.second.identity,
            rationale="Explicit review says these cores are equivalent.",
            basis_record_ids=self.basis,
        )
        with self.assertRaisesRegex(SemanticQuestionError, "non-equivalent"):
            SemanticQuestionLineageProposal(
                predecessor_study_id=self.predecessor_study_id,
                successor_study_id=self.successor_study_id,
                predecessor_core_id=self.first.identity,
                successor_core_id=self.second.identity,
                relation=SemanticQuestionRelation.SEMANTIC_REVISION,
                rationale="Equivalent cores cannot manufacture a revision.",
                basis_record_ids=self.basis,
                equivalence_proposal_id=equivalence.identity,
            )

        revision = SemanticQuestionLineageProposal(
            predecessor_study_id=self.predecessor_study_id,
            successor_study_id=self.successor_study_id,
            predecessor_core_id=self.first.identity,
            successor_core_id=self.second.identity,
            relation=SemanticQuestionRelation.SEMANTIC_REVISION,
            rationale="The controlled semantic surface changed materially.",
            basis_record_ids=self.basis,
        )
        self.assertEqual(
            revision.relation, SemanticQuestionRelation.SEMANTIC_REVISION
        )

    def test_plain_string_and_unknown_payload_relation_fail_closed(self) -> None:
        with self.assertRaisesRegex(SemanticQuestionError, "relation"):
            SemanticQuestionLineageProposal(
                predecessor_study_id=self.predecessor_study_id,
                successor_study_id=self.successor_study_id,
                predecessor_core_id=self.first.identity,
                successor_core_id=self.first.identity,
                relation="continuation",  # type: ignore[arg-type]
                rationale="Untyped relations are not authority.",
                basis_record_ids=self.basis,
            )

        payload = SemanticQuestionLineageProposal(
            predecessor_study_id=self.predecessor_study_id,
            successor_study_id=self.successor_study_id,
            predecessor_core_id=self.first.identity,
            successor_core_id=self.first.identity,
            relation=SemanticQuestionRelation.CONFIRMATION,
            rationale="Confirmation retains one exact semantic core.",
            basis_record_ids=self.basis,
        ).to_identity_payload()
        payload["relation"] = "fuzzy_text_match"
        with self.assertRaisesRegex(SemanticQuestionError, "relation"):
            SemanticQuestionLineageProposal.from_identity_payload(payload)


if __name__ == "__main__":
    unittest.main()
