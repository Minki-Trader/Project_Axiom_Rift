from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.operations.completion_validity_projection import (
    validate_completion_validity_invalidation_binding,
)
from axiom_rift.research.historical_scientific_validity import (
    DecisionPredicateActivationState,
)
from axiom_rift.research.historical_spread_time_invalidation_builder import (
    AUDIT_SLICE_DIGEST_INVENTORY_SCHEMA,
    EXPECTED_ATOMIC_ACTIVATION_COUNTS,
    EXPECTED_COMPLETION_COUNT,
    EXPECTED_STUDY_CONTEXTS,
    HistoricalSpreadTimeInvalidationBuilderError,
    build_historical_spread_time_invalidation_inventory,
)
from axiom_rift.storage.evidence import EvidenceStore
from axiom_rift.storage.index import IndexRecord, LocalIndex


CLAIMS = (
    "activity_and_concentration",
    "after_cost_fixed_lot_economics",
    "causal_feature_and_execution_validity",
    "registered_control_contrast",
    "selection_aware_signal_evidence",
    "temporal_and_regime_stability",
)
LEGACY_MODES = (
    "causal_contrast",
    "cost_and_execution",
    "extreme_or_boundary",
    "regime_stability",
    "sensitivity_or_stress",
    "temporal_stability",
)
ATOMIC_MODES = (
    "causal_contrast",
    "cost_and_execution",
    "sensitivity_or_stress",
    "temporal_stability",
)
CRITERIA = (
    ("A01-minimum-trades", "activity_and_concentration"),
    ("A02-positive-density", "activity_and_concentration"),
    ("A03-profit-day-concentration", "activity_and_concentration"),
    ("B01-positive-native-cost", "after_cost_fixed_lot_economics"),
    ("B02-fold-profit-factor", "after_cost_fixed_lot_economics"),
    ("B03-slippage-stress", "after_cost_fixed_lot_economics"),
    ("B04-monthly-realized-drawdown-share", "after_cost_fixed_lot_economics"),
    ("C01-feature-prefix-invariance", "causal_feature_and_execution_validity"),
    ("C02-decision-append-invariance", "causal_feature_and_execution_validity"),
    ("C03-decision-time-causality", "causal_feature_and_execution_validity"),
    ("C04-resolved-cost", "causal_feature_and_execution_validity"),
    ("C05-finite-metrics", "causal_feature_and_execution_validity"),
    ("D01-opposite-sign-control", "registered_control_contrast"),
    ("D02-opposite-sign-uncertainty", "registered_control_contrast"),
    ("D03-feature-control", "registered_control_contrast"),
    ("D04-feature-control-uncertainty", "registered_control_contrast"),
    ("E01-familywise-selection", "selection_aware_signal_evidence"),
    ("F01-evaluable-folds", "temporal_and_regime_stability"),
    ("F02-winning-folds", "temporal_and_regime_stability"),
    ("F03-positive-regimes", "temporal_and_regime_stability"),
)

ATOMIC_0107 = (
    "executable:c8b62dac5ef859ee2db6e6adbdcc758384867811174e5be3a765da904db4dcaf",
    "executable:51193460ecf100b1c0053ebf87acc5197928d01e7c28385d3d39770cbe6977bc",
    "executable:93c03f0a5d8545cafc53fbfcbcb7791ac0ac27175b2a05e26947281f09fe81d1",
    "executable:0fc036a7825f29ca2aca8129855c4315e4b81cfa894330afe2d899b2c3b42762",
)
ATOMIC_0108 = (
    "executable:d8f54d95a5a630377d9a82f7c2801d362008304d1e3096e1fb3117966799d905",
    "executable:eabf4c41722ac77fadccff0b669be9e9226cd250fd911878c8d594b7acbc7990",
    "executable:3a90958f5e1dca92bf61f7ed5abd0375ce1c15c8cab161512ffb480b37f0f915",
    "executable:8392b61ce0b248381ac51be7975cacb75d7d74467b0903393656cbc2491f88e4",
)

BAR_CLOCK = "clock:fpmarkets_m5_bar_open_completed_plus_5m_v2"
SEGMENT_COST = (
    "cost:bid_bar_segment_positive_median_min_1_unknown_entry_cancel_"
    "half_spread_stress_v1"
)
GAP_COST = (
    "cost:bid_bar_gap_segment_positive_median_min_1_unknown_entry_cancel_"
    "half_spread_stress_v1"
)
CONTRACTS = {
    "STU-0046": (BAR_CLOCK, GAP_COST),
    "STU-0047": (BAR_CLOCK, GAP_COST),
    "STU-0048": (BAR_CLOCK, SEGMENT_COST),
    "STU-0049": (BAR_CLOCK, SEGMENT_COST),
    "STU-0050": (BAR_CLOCK, SEGMENT_COST),
    "STU-0051": (BAR_CLOCK, SEGMENT_COST),
    "STU-0071": (
        "clock:fpmarkets_m5_entry_quote_observed_before_order_v1",
        "cost:bid_bar_spread_point_0_01_causal_zero_repair_entry_quote_gate_"
        "half_spread_stress_v1",
    ),
    "STU-0101": (
        "clock:fpmarkets_m5_causal_one_bar_quote_deferral_v1",
        "cost:bid_bar_spread_point_0_01_causal_zero_repair_one_bar_quote_"
        "deferral_half_spread_stress_v1",
    ),
    "STU-0107": (BAR_CLOCK, SEGMENT_COST),
    "STU-0108": (BAR_CLOCK, SEGMENT_COST),
}


def _digest(label: str) -> str:
    return sha256(label.encode("ascii")).hexdigest()


def _artifact(store: EvidenceStore, value: object) -> str:
    return store.finalize(canonical_bytes(value)).sha256


def _row_inventory() -> tuple[tuple[str, str, str], ...]:
    rows: list[tuple[str, str, str]] = []
    ordinal = 0
    for study_id in (
        "STU-0046",
        "STU-0047",
        "STU-0048",
        "STU-0049",
        "STU-0050",
        "STU-0051",
    ):
        for _member in range(4):
            rows.append(
                (
                    study_id,
                    "executable:" + _digest(f"legacy-executable-{ordinal}"),
                    _digest(f"legacy-completion-{ordinal}"),
                )
            )
            ordinal += 1
    rows.extend(
        (
            (
                "STU-0071",
                "executable:" + _digest("stu0071-reused-executable"),
                _digest("stu0071-scientific-completion"),
            ),
            (
                "STU-0101",
                "executable:" + _digest("stu0101-executable"),
                _digest("stu0101-scientific-completion"),
            ),
        )
    )
    rows.extend(
        ("STU-0107", executable_id, _digest(f"completion-{executable_id}"))
        for executable_id in ATOMIC_0107
    )
    rows.extend(
        ("STU-0108", executable_id, _digest(f"completion-{executable_id}"))
        for executable_id in ATOMIC_0108
    )
    return tuple(rows)


def _criteria_payload() -> list[dict[str, str]]:
    return [
        {"claim_id": claim_id, "criterion_id": criterion_id}
        for criterion_id, claim_id in CRITERIA
    ]


def _adjudication_payload() -> dict[str, object]:
    return {
        "claims": [{"claim_id": claim_id} for claim_id in CLAIMS],
        "criteria": _criteria_payload(),
    }


def _atomic_trace(
    *,
    study_id: str,
    subject_executable_id: str,
    job_id: str,
    mission_id: str,
    malformed: bool,
) -> dict[str, object]:
    activators = ATOMIC_0107[:2] if study_id == "STU-0107" else ATOMIC_0108[:2]
    rows: list[dict[str, object]] = []
    ordinal = 0
    for executable_id in activators:
        for decision_index, entry_index in ((415914, 415915), (415915, 415916)):
            for scope in ("full", "prefix"):
                rows.append(
                    {
                        "decision_bar_index": decision_index,
                        "entry_bar_index": entry_index,
                        "executable_id": executable_id,
                        "observation_id": "observation:"
                        + _digest(
                            f"{subject_executable_id}-{executable_id}-{ordinal}-{scope}"
                        ),
                        "scope": scope,
                        "status": "entry_cancelled_unknown_cost",
                    }
                )
            ordinal += 1
    if malformed:
        rows.pop()
    return {
        "intent_observations": rows,
        "job_hash": job_id.removeprefix("job:"),
        "job_id": job_id,
        "mission_id": mission_id,
        "schema": "scientific_evaluation_trace.v1",
        "subject_executable_id": subject_executable_id,
    }


def _audit_document(
    rows: tuple[tuple[str, str, str], ...],
    trace_hashes: dict[str, str],
) -> bytes:
    lines = [
        "# Test Spread Time Audit",
        "",
        "## Bound Findings",
        "",
        "- AX-SPREAD-TIME-001:",
        "  reason decision_input_point_in_time_unproven",
        "  field MqlRates.spread",
        "  prohibited use same_scheduled_or_deferred_entry_bar_order_decision",
        "  affected scientific completion count 34",
        "  affected Study contexts " + " ".join(EXPECTED_STUDY_CONTEXTS),
    ]
    lines.extend(
        f"  {study_id} {executable_id} completion {completion_id}"
        for study_id, executable_id, completion_id in rows
    )
    lines.extend(
        (
            "",
            "- AX-SPREAD-TIME-002:",
            "  exact source index transitions 415914_to_415915 and 415915_to_415916",
            "  STU-0107 atomic traces "
            + " ".join(trace_hashes[item] for item in ATOMIC_0107),
            "  STU-0108 atomic traces "
            + " ".join(trace_hashes[item] for item in ATOMIC_0108),
            "  observed branch entry_cancelled_unknown_cost",
            "  each stored family trace contains 8 full_or_prefix rows "
            "representing 4 distinct events",
            "",
        )
    )
    return "\n".join(lines).encode("ascii")


@contextmanager
def _fixture(*, malformed_trace: bool = False):
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = EvidenceStore(root / "evidence")
        rows = _row_inventory()
        mission_id = "MIS-SPREAD-TIME-TEST"
        records: list[IndexRecord] = []
        closes: dict[str, str] = {}
        for study_id in sorted({row[0] for row in rows}):
            close_id = _digest(f"close-{study_id}")
            closes[study_id] = close_id
            records.extend(
                (
                    IndexRecord(
                        kind="study-open",
                        record_id=study_id,
                        subject=f"Study:{study_id}",
                        status="open",
                        fingerprint=_digest(f"open-{study_id}"),
                        payload={"mission_id": mission_id},
                    ),
                    IndexRecord(
                        kind="study-close",
                        record_id=close_id,
                        subject=f"Study:{study_id}",
                        status="preserved",
                        fingerprint=_digest(f"close-fingerprint-{study_id}"),
                        payload={"outcome": "preserved"},
                    ),
                )
            )

        trace_hashes: dict[str, str] = {}
        implementation_hashes = (
            _digest("component-implementation-one"),
            _digest("component-implementation-two"),
        )
        for ordinal, (study_id, executable_id, completion_id) in enumerate(rows):
            atomic = study_id in {"STU-0107", "STU-0108"}
            modes = ATOMIC_MODES if atomic else LEGACY_MODES
            job_id = "job:" + _digest(f"job-{ordinal}")
            plan_hash = _artifact(
                store,
                {
                    "criteria": _criteria_payload(),
                    "evidence_modes": list(modes),
                    "executable_id": executable_id,
                    "mission_id": mission_id,
                    "planned_claims": list(CLAIMS),
                    "schema": (
                        "scientific_validation_plan.v2"
                        if atomic
                        else "scientific_validation_plan.v1"
                    ),
                },
            )
            measurement = {
                "evidence_modes": list(modes),
                "executable_id": executable_id,
                "job_hash": job_id.removeprefix("job:"),
                "job_id": job_id,
                "mission_id": mission_id,
                "schema": (
                    "scientific_measurement.v2"
                    if atomic
                    else "scientific_measurement.v1"
                ),
            }
            if not atomic:
                measurement["claims"] = list(CLAIMS)
            measurement_hash = _artifact(store, measurement)
            result_hash = _artifact(
                store,
                {
                    "executable_id": executable_id,
                    "job_hash": job_id.removeprefix("job:"),
                    "job_id": job_id,
                    "mission_id": mission_id,
                    "observations": [
                        {
                            "claim_id": claim_id,
                            "measurement_artifact_hash": measurement_hash,
                        }
                        for claim_id in CLAIMS
                    ],
                    "schema": "scientific_job_evidence.v1",
                },
            )
            outputs = {
                f"scientific/{study_id}/{ordinal}/measurement.json": measurement_hash,
                f"scientific/{study_id}/{ordinal}/result.json": result_hash,
                f"scientific/{study_id}/{ordinal}/validation-plan.json": plan_hash,
            }
            scientific: dict[str, object] = {
                "candidate_eligible": False,
                "claims": list(CLAIMS),
                "executed_evidence_modes": list(modes),
                "executable_id": executable_id,
                "measurement_artifact_hashes": [measurement_hash],
                "result_manifest_hash": result_hash,
                "scientific_eligible": True,
                "validation_plan_hash": plan_hash,
                "verdict": "failed",
            }
            if atomic:
                scientific["adjudication"] = _adjudication_payload()
                trace_hash = _artifact(
                    store,
                    _atomic_trace(
                        study_id=study_id,
                        subject_executable_id=executable_id,
                        job_id=job_id,
                        mission_id=mission_id,
                        malformed=malformed_trace and executable_id == ATOMIC_0107[0],
                    ),
                )
                trace_hashes[executable_id] = trace_hash
                outputs[
                    f"scientific/{study_id}/{ordinal}/evaluation-trace.json"
                ] = trace_hash

            clock_contract, cost_contract = CONTRACTS[study_id]
            trial_study_id = "STU-0070" if study_id == "STU-0071" else study_id
            records.extend(
                (
                    IndexRecord(
                        kind="trial",
                        record_id=executable_id,
                        subject=f"Batch:BAT-{ordinal}",
                        status="evaluated",
                        fingerprint=executable_id.removeprefix("executable:"),
                        payload={
                            "engineering_fixture": False,
                            "executable": {
                                "clock_contract": clock_contract,
                                "component_manifests": [
                                    {
                                        "implementation": (
                                            "axiom_rift.research.fixture.one@sha256:"
                                            + implementation_hashes[0]
                                        )
                                    },
                                    {
                                        "implementation": (
                                            "axiom_rift.research.fixture.two@sha256:"
                                            + implementation_hashes[1]
                                        )
                                    },
                                ],
                                "cost_contract": cost_contract,
                            },
                            "mission_id": mission_id,
                            "scientific_eligible": True,
                            "study_id": trial_study_id,
                        },
                    ),
                    IndexRecord(
                        kind="job-declared",
                        record_id=job_id,
                        subject=f"Job:{job_id}",
                        status="declared",
                        fingerprint=_digest(f"declaration-{ordinal}"),
                        payload={
                            "mission_id": mission_id,
                            "spec": {
                                "evidence_subject": {
                                    "id": executable_id,
                                    "kind": "Executable",
                                }
                            },
                            "study_id": study_id,
                        },
                    ),
                    IndexRecord(
                        kind="job-completed",
                        record_id=completion_id,
                        subject=f"Job:{job_id}",
                        status="success",
                        fingerprint=_digest(f"completion-fingerprint-{ordinal}"),
                        payload={
                            "job_id": job_id,
                            "outputs": outputs,
                            "scientific": scientific,
                        },
                    ),
                )
            )
            if not atomic:
                adjudication_id = (
                    "historical-adjudication:"
                    + _digest(f"historical-adjudication-{ordinal}")
                )
                records.append(
                    IndexRecord(
                        kind="historical-scientific-adjudication",
                        record_id=adjudication_id,
                        subject=f"Study:{study_id}",
                        status="exact_surface_prune_retained",
                        fingerprint=adjudication_id.removeprefix(
                            "historical-adjudication:"
                        ),
                        payload={
                            "adjudication": _adjudication_payload(),
                            "completion_record_id": completion_id,
                            "executable_id": executable_id,
                            "measurement_artifact_hash": measurement_hash,
                            "study_close_record_id": closes[study_id],
                            "study_id": study_id,
                            "validation_plan_hash": plan_hash,
                        },
                        event_stream=f"historical-adjudication:{completion_id}",
                        event_sequence=1,
                    )
                )

        audit = _audit_document(rows, trace_hashes)
        audit_hash = store.finalize(audit).sha256
        with LocalIndex(root / "index.sqlite3") as index:
            index.put_many(records)
            yield index, store, audit_hash, audit


class HistoricalSpreadTimeInvalidationBuilderTests(unittest.TestCase):
    def test_builds_exact_inventory_and_recomputes_atomic_activation(self) -> None:
        with _fixture() as (index, store, audit_hash, _audit):
            with patch(
                "axiom_rift.research.historical_spread_time_invalidation_builder."
                "validate_completion_validity_invalidation_binding",
                wraps=validate_completion_validity_invalidation_binding,
            ) as binding_validator:
                inventory = build_historical_spread_time_invalidation_inventory(
                    index,
                    store,
                    audit_artifact_hash=audit_hash,
                )

            self.assertEqual(len(inventory.invalidations), EXPECTED_COMPLETION_COUNT)
            self.assertEqual(inventory.study_contexts, EXPECTED_STUDY_CONTEXTS)
            self.assertEqual(binding_validator.call_count, EXPECTED_COMPLETION_COUNT)
            self.assertEqual(
                [item.completion_record_id for item in inventory.invalidations],
                sorted(item.completion_record_id for item in inventory.invalidations),
            )
            self.assertNotIn(
                "STU-0070",
                {item.study_id for item in inventory.invalidations},
            )
            self.assertEqual(
                {
                    item.executable_id: item.predicate_activation_count
                    for item in inventory.invalidations
                    if item.executable_id in EXPECTED_ATOMIC_ACTIVATION_COUNTS
                },
                EXPECTED_ATOMIC_ACTIVATION_COUNTS,
            )
            for item in inventory.invalidations:
                self.assertEqual(item.affected_claim_ids, CLAIMS)
                self.assertEqual(
                    item.affected_criterion_ids,
                    tuple(sorted(criterion_id for criterion_id, _claim in CRITERIA)),
                )
                if item.executable_id in EXPECTED_ATOMIC_ACTIVATION_COUNTS:
                    expected = EXPECTED_ATOMIC_ACTIVATION_COUNTS[item.executable_id]
                    self.assertEqual(
                        item.activation_state,
                        (
                            DecisionPredicateActivationState.ACTIVATED
                            if expected
                            else (
                                DecisionPredicateActivationState
                                .EVALUATED_NOT_ACTIVATED
                            )
                        ),
                    )
                else:
                    self.assertEqual(
                        item.activation_state,
                        (
                            DecisionPredicateActivationState
                            .LEGACY_AGGREGATE_NOT_SERIALIZED
                        ),
                    )
                    self.assertIsNone(item.predicate_activation_count)

            payload = inventory.to_audit_slice_digest_inventory_payload()
            self.assertEqual(payload["schema"], AUDIT_SLICE_DIGEST_INVENTORY_SCHEMA)
            self.assertEqual(payload["completion_count"], EXPECTED_COMPLETION_COUNT)
            self.assertEqual(len(payload["entries"]), EXPECTED_COMPLETION_COUNT)
            self.assertEqual(
                inventory.audit_slice_digest_inventory_digest,
                build_historical_spread_time_invalidation_inventory(
                    index,
                    store,
                    audit_artifact_hash=audit_hash,
                ).audit_slice_digest_inventory_digest,
            )

    def test_report_count_and_atomic_duplicate_shape_fail_closed(self) -> None:
        with _fixture() as (index, store, _audit_hash, audit):
            bad_audit_hash = store.finalize(
                audit.replace(
                    b"affected scientific completion count 34",
                    b"affected scientific completion count 35",
                )
            ).sha256
            with self.assertRaisesRegex(
                HistoricalSpreadTimeInvalidationBuilderError,
                "completion count changed",
            ):
                build_historical_spread_time_invalidation_inventory(
                    index,
                    store,
                    audit_artifact_hash=bad_audit_hash,
                )

        with _fixture(malformed_trace=True) as (index, store, audit_hash, _audit):
            with self.assertRaisesRegex(
                HistoricalSpreadTimeInvalidationBuilderError,
                "eight branch rows",
            ):
                build_historical_spread_time_invalidation_inventory(
                    index,
                    store,
                    audit_artifact_hash=audit_hash,
                )


if __name__ == "__main__":
    unittest.main()
