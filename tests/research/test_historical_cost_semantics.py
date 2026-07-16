from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import unittest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.research.historical_cost_semantics import (
    AUTHORITY_DELTA_ZERO,
    CAUSAL_INVALID_COMPLETION_IDS,
    CAUSAL_INVALID_STUDY_CONTEXT_IDS,
    EXCEPTIONAL_STUDY_CLASSES,
    GOLDEN_CLASS_COMPLETION_SEALS,
    GOLDEN_INVENTORY_SEALS,
    HistoricalCostSemanticsError,
    HistoricalCostSemanticsLatch,
    HistoricalSpreadSemanticsAuditManifest,
    PRODUCTION_UPPER_CURSOR,
    historical_cost_semantics_latch_from_bytes,
    historical_spread_semantics_audit_manifest_from_bytes,
)


def _manifest(
    audit_artifact_hash: str = "a" * 64,
) -> HistoricalSpreadSemanticsAuditManifest:
    return HistoricalSpreadSemanticsAuditManifest(
        audit_artifact_hash=audit_artifact_hash,
        upper_authority_cursor=PRODUCTION_UPPER_CURSOR,
        causal_invalid_completion_ids=CAUSAL_INVALID_COMPLETION_IDS,
        causal_invalid_study_context_ids=CAUSAL_INVALID_STUDY_CONTEXT_IDS,
        audited_cost_contracts=("cost:completed_bar_spread_proxy_v1",),
        exceptional_study_classes=tuple(
            sorted(
                EXCEPTIONAL_STUDY_CLASSES.items(),
                key=lambda item: item[0].value,
            )
        ),
        inventory_seals=GOLDEN_INVENTORY_SEALS,
        class_completion_seals=GOLDEN_CLASS_COMPLETION_SEALS,
    )


def _report_bytes() -> bytes:
    return (
        "## Bound Findings\n\n"
        "- AX-SPREAD-COST-001:\n"
        "  spread cost Study operation count 104\n"
        "  causal invalid A Study context count 11\n"
        "  proxy-only B Study operation count 93\n"
        "  proxy-only B completion count 501\n"
        "  proxy-only B scientific completion count 488\n"
        "  proxy-only B engineering completion count 13\n"
        "  proxy-only B negative memory count 438\n"
        "  proxy-only B historical adjudication count 444\n"
        "  authority Journal sequence 5385\n"
        "  authority Journal event "
        "6b47964a60a8490e76ce921945071f282be61334e27706093bd51469ae519f65\n"
        "  Study operation inventory digest "
        "03309a5846e1df2d353247d2d1030e52a6c3fbc9f4298e74d31924850d359394\n"
        "  completion inventory digest "
        "6da1d79ad925b596f18d5ef2f42ecdeaa8c83fa4c0baf032968bcdc64b0b9a33\n"
        "  scientific completion inventory digest "
        "f406cd94f82581367a7f52851e63e5799c9e81c8f7343b0e307051447fb501f9\n"
        "  scientific Executable inventory digest "
        "68cebe34170a1a185c5ff2acd787f343c0d85c1fbcfb6e442bb183c4328b8162\n"
        "  adjudication inventory digest "
        "12fd4a6947abd880cca8f81e1ff46bea9b64b47fc93cdbb72e7be0779527c6af\n"
        "  negative memory inventory digest "
        "4e8965d5a2e1b76f16b3520d6812d8bff5b712f9fafb4d02c3cb127e811b1de4\n"
        "  execution_cost_measurement_only scientific completion count 437\n"
        "  completed_period_proxy_feature scientific completion count 8\n"
        "  native_cost_outcome_label_only scientific completion count 36\n"
        "  decision_surface_cost_dependent scientific completion count 6\n"
        "  causal_policy_cost_state_dependent scientific completion count 1\n"
        "  permitted historical interpretation completed_period_bar_spread_proxy\n"
        "  forbidden historical interpretation actual_point_in_time_native_quote\n"
        "  independently preservable scopes gross_mechanism feature_causality\n\n"
        "- AX-SPREAD-NONAFFECTED-001:\n"
        "  independent finding\n"
    ).encode("ascii")


class HistoricalCostSemanticsTests(unittest.TestCase):
    def test_manifest_binds_exact_ascii_cost_finding_in_report(self) -> None:
        report = _report_bytes()
        manifest = _manifest(sha256(report).hexdigest())
        manifest.require_report(report)

        with self.assertRaisesRegex(
            HistoricalCostSemanticsError,
            "hash does not match",
        ):
            manifest.require_report(report + b"\n")

        tampered_documents = (
            report.replace(b"completion count 501", b"completion count 500"),
            report.replace(
                b"6da1d79ad925b596f18d5ef2f42ecdeaa8c83fa4c0baf032968bcdc64b0b9a33",
                b"7da1d79ad925b596f18d5ef2f42ecdeaa8c83fa4c0baf032968bcdc64b0b9a33",
            ),
            report.replace(
                b"completed_period_proxy_feature scientific completion count 8",
                b"completed_period_proxy_feature scientific completion count 9",
            ),
            report.replace(
                b"completed_period_bar_spread_proxy",
                b"actual_point_in_time_native_quote",
                1,
            ),
            report.replace(
                b"- AX-SPREAD-NONAFFECTED-001:",
                b"- AX-SPREAD-COST-001:",
            ),
        )
        for document in tampered_documents:
            with self.subTest(document_hash=sha256(document).hexdigest()):
                forged_manifest = _manifest(sha256(document).hexdigest())
                with self.assertRaises(HistoricalCostSemanticsError):
                    forged_manifest.require_report(document)

        non_ascii = report + b"\nnot-ascii \xec\x9a\xb0\n"
        non_ascii_manifest = _manifest(sha256(non_ascii).hexdigest())
        with self.assertRaisesRegex(HistoricalCostSemanticsError, "ASCII"):
            non_ascii_manifest.require_report(non_ascii)

    def test_manifest_and_zero_credit_latch_round_trip_exactly(self) -> None:
        manifest = _manifest()
        rebuilt_manifest = historical_spread_semantics_audit_manifest_from_bytes(
            canonical_bytes(manifest.to_payload())
        )
        self.assertEqual(rebuilt_manifest, manifest)
        self.assertEqual(
            rebuilt_manifest.causal_invalid_study_context_ids,
            CAUSAL_INVALID_STUDY_CONTEXT_IDS,
        )

        latch = HistoricalCostSemanticsLatch.from_audit_manifest(manifest)
        rebuilt_latch = historical_cost_semantics_latch_from_bytes(
            canonical_bytes(latch.to_payload())
        )
        self.assertEqual(rebuilt_latch, latch)
        self.assertEqual(
            rebuilt_latch.to_payload()["authority_delta"],
            AUTHORITY_DELTA_ZERO,
        )
        self.assertEqual(rebuilt_latch.audit_manifest_hash, manifest.artifact_hash)
        self.assertEqual(rebuilt_latch.audit_manifest_identity, manifest.identity)

    def test_manifest_rejects_any_substitute_causal_inventory(self) -> None:
        manifest = _manifest()
        substituted_completions = (
            "b" * 64,
            *manifest.causal_invalid_completion_ids[1:],
        )
        with self.assertRaisesRegex(
            HistoricalCostSemanticsError,
            "exact 35-record",
        ):
            replace(
                manifest,
                causal_invalid_completion_ids=substituted_completions,
            )
        with self.assertRaisesRegex(
            HistoricalCostSemanticsError,
            "exact 11-Study",
        ):
            replace(
                manifest,
                causal_invalid_study_context_ids=(
                    "STU-0001",
                    *manifest.causal_invalid_study_context_ids[1:],
                ),
            )

    def test_latch_rejects_tampered_inventory_and_nonzero_credit(self) -> None:
        manifest = _manifest()
        latch = HistoricalCostSemanticsLatch.from_audit_manifest(manifest)
        with self.assertRaisesRegex(
            HistoricalCostSemanticsError,
            "inventory is not golden",
        ):
            replace(latch, inventory_seals=GOLDEN_INVENTORY_SEALS[1:])

        payload = latch.to_payload()
        payload["authority_delta"] = {
            **AUTHORITY_DELTA_ZERO,
            "scientific": 1,
        }
        with self.assertRaisesRegex(
            HistoricalCostSemanticsError,
            "latch is malformed",
        ):
            HistoricalCostSemanticsLatch.from_mapping(payload)


if __name__ == "__main__":
    unittest.main()
