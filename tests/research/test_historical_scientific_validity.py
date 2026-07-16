from __future__ import annotations

import unittest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.research.historical_adjudication import (
    HistoricalAdjudicationRequest,
    HistoricalDisposition,
    HistoricalValidityOverride,
    HistoricalValidityReason,
    ReplayPriority,
)
from axiom_rift.research.historical_scientific_validity import (
    DecisionPredicateActivationState,
    HistoricalScientificValidityError,
    HistoricalScientificValidityInvalidation,
    JobBindingKind,
    historical_scientific_validity_invalidation_from_bytes,
    historical_scientific_validity_invalidation_from_payload,
)


def _invalidation(
    **updates: object,
) -> HistoricalScientificValidityInvalidation:
    values: dict[str, object] = {
        "study_id": "STU-VALIDITY",
        "study_close_record_id": "1" * 64,
        "job_id": "job:" + "2" * 64,
        "job_binding_kind": JobBindingKind.DECLARATION,
        "job_binding_record_id": "job:" + "2" * 64,
        "completion_record_id": "3" * 64,
        "executable_id": "executable:" + "4" * 64,
        "validation_plan_hash": "5" * 64,
        "measurement_artifact_hash": "6" * 64,
        "result_manifest_hash": "7" * 64,
        "component_implementation_hashes": ("8" * 64, "9" * 64),
        "clock_contract": "clock:completed_m5_v1",
        "cost_contract": "cost:bar_spread_proxy_v1",
        "predicate_evaluated": True,
        "activation_state": (
            DecisionPredicateActivationState.EVALUATED_NOT_ACTIVATED
        ),
        "predicate_activation_count": 0,
        "affected_claim_ids": (
            "after_cost_fixed_lot_economics",
            "causal_feature_and_execution_validity",
        ),
        "affected_evidence_modes": ("cost_and_execution",),
        "affected_criterion_ids": (
            "B01-positive-native-cost",
            "C03-decision-time-causality",
        ),
        "audit_finding_id": "AX-SPREAD-TIME-001",
        "audit_artifact_hash": "a" * 64,
    }
    values.update(updates)
    return HistoricalScientificValidityInvalidation(**values)  # type: ignore[arg-type]


class HistoricalScientificValidityTests(unittest.TestCase):
    def test_evaluated_zero_activation_is_invalid_and_round_trips(self) -> None:
        invalidation = _invalidation()
        self.assertEqual(invalidation.predicate_activation_count, 0)
        self.assertEqual(
            invalidation.activation_state,
            DecisionPredicateActivationState.EVALUATED_NOT_ACTIVATED,
        )
        self.assertEqual(
            historical_scientific_validity_invalidation_from_payload(
                invalidation.to_identity_payload()
            ),
            invalidation,
        )
        self.assertEqual(
            historical_scientific_validity_invalidation_from_bytes(
                canonical_bytes(invalidation.to_identity_payload())
            ),
            invalidation,
        )
        self.assertTrue(
            invalidation.identity.startswith(
                "historical-scientific-validity-invalidation:"
            )
        )
        self.assertEqual(
            invalidation.to_identity_payload()["authority_delta"],
            {
                "candidate": 0,
                "economic": 0,
                "holdout": 0,
                "scientific": 0,
                "terminal": 0,
                "trial": 0,
            },
        )

    def test_activation_and_payload_malformed_cases_fail_closed(self) -> None:
        with self.assertRaisesRegex(
            HistoricalScientificValidityError,
            "must have been evaluated",
        ):
            _invalidation(predicate_evaluated=False)
        with self.assertRaisesRegex(
            HistoricalScientificValidityError,
            "positive activation count",
        ):
            _invalidation(
                activation_state=DecisionPredicateActivationState.ACTIVATED,
                predicate_activation_count=0,
            )
        with self.assertRaisesRegex(
            HistoricalScientificValidityError,
            "unserialized",
        ):
            _invalidation(
                activation_state=(
                    DecisionPredicateActivationState.LEGACY_AGGREGATE_NOT_SERIALIZED
                ),
                predicate_activation_count=0,
            )
        payload = _invalidation().to_identity_payload()
        payload["authority_delta"] = {
            "candidate": 0,
            "economic": 0,
            "holdout": 0,
            "scientific": 1,
            "terminal": 0,
            "trial": 0,
        }
        with self.assertRaisesRegex(
            HistoricalScientificValidityError,
            "payload is malformed",
        ):
            historical_scientific_validity_invalidation_from_payload(payload)

        semantic_mutation = _invalidation().to_identity_payload()
        semantic_mutation["affected_criterion_ids"] = [
            "B01-positive-native-cost",
        ]
        with self.assertRaisesRegex(
            HistoricalScientificValidityError,
            "semantic finding slice",
        ):
            historical_scientific_validity_invalidation_from_payload(
                semantic_mutation
            )

    def test_completion_and_source_overrides_form_a_canonical_union(self) -> None:
        completion = _invalidation()
        request = HistoricalAdjudicationRequest(
            completion_record_id=completion.completion_record_id,
            disposition=HistoricalDisposition.NOT_EVALUABLE_QUALIFICATION,
            replay_priority=ReplayPriority.NONE,
            reason_codes=("availability_invalid",),
            validity_overrides=(
                HistoricalValidityOverride(
                    reason=HistoricalValidityReason.SOURCE_AUTHORITY_INVALIDATED,
                    subject_id="source:" + "c" * 64,
                    evidence_record_id=(
                        "source-authority-invalidation:" + "d" * 64
                    ),
                ),
                HistoricalValidityOverride(
                    reason=(
                        HistoricalValidityReason.DECISION_INPUT_POINT_IN_TIME_UNPROVEN
                    ),
                    subject_id=completion.completion_record_id,
                    evidence_record_id=completion.identity,
                ),
            ),
        )
        self.assertEqual(
            tuple(item.reason for item in request.validity_overrides),
            (
                HistoricalValidityReason.DECISION_INPUT_POINT_IN_TIME_UNPROVEN,
                HistoricalValidityReason.SOURCE_AUTHORITY_INVALIDATED,
            ),
        )
        with self.assertRaisesRegex(
            ValueError,
            "lowercase SHA-256 digest",
        ):
            HistoricalValidityOverride(
                reason=(
                    HistoricalValidityReason.DECISION_INPUT_POINT_IN_TIME_UNPROVEN
                ),
                subject_id="not-a-completion",
                evidence_record_id=completion.identity,
            )


if __name__ == "__main__":
    unittest.main()
