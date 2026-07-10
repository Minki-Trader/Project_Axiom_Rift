from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import unittest

import yaml

from axiom_rift.v2.identity import sha256_payload
from axiom_rift.v2.research.scientific_programs import (
    SESSION_GAP_BUNDLE_ROLES,
    bind_session_gap_failure_runtime,
    build_scientific_bundle_batch,
    load_scientific_program_registry,
)
from axiom_rift.v2.research.scientific_scout import (
    SESSION_GAP_SELECTION_RULE_SHA256,
)
from axiom_rift.v2.research.session_gap_failure import (
    SESSION_GAP_FAILURE_EXECUTABLE_SHA256,
)
from axiom_rift.v2.research.scout import validate_hypothesis_v2_payload


ROOT = Path(__file__).resolve().parents[2]
GLOBAL_CONFIGURATION_HASHES = [
    "027be0975647858cae1d71d319a20ccaeda85d2c5feda1deebd78de7ea6d04c0",
    "0dff348fab1d3f88b47d9d0ef49963fbd961460fb6fe3794da3be367b4e29675",
    "1b0d2674b6d1e43143540f1b7cf12302d322078f296097810d41382aa0fb319e",
    "24bcdb33ed57176a3b66eb9880a6d4067ad91760751d72921a1ff271978b5f42",
    "2a111689327a43ce46a784287017196ad25b1ac4f8446b913e78e25ad841df06",
    "4d4547c912f54da4b6db48342e1565f4495e5ab48db43809491e5d8318ccbdc3",
    "604cf897b7a0541513bb873fc3ae487ca83919da88bdbe873da55b15cf1ea5d9",
    "6062b06da9742489024366829b01d5cb40899668169edbd4ed225ebfe7993683",
    "6c76fcfa91c68f4a7dfd29062c06f5a22090902d064f3e3fdad6359c1f9f5636",
    "87de6d8c9e67d1b8643f99eb8a134dcf5c6522f129f7e01ca979826f9f5a0478",
    "a1b7a59e25493666519a162455aec7fcdd10de43de573d65a19f721154c76d2c",
    "b3f2d185f1b87ba715fc02ba2e030773c3e8951ac2514edc84f98bd813828b7e",
    "c28f0e7b72d81dc0293bb77c9eed29b1bc0618cb2f3e54711e6bfcdee46b6d9b",
    "cdd8cb3132a04aaa747fafe7214759276ef14f9ff4df1480d6f071e780fcdce0",
    "e83325fca18e065a7bb207ab65ef3f36534110d2ac8e85b7cfd67323fdce03c8",
]


def session_hypothesis_payload() -> dict[str, object]:
    payload = yaml.safe_load(
        (
            ROOT
            / "campaigns/v2/V2G0002_scientific_root/hypotheses/V2H0004.yaml"
        ).read_text(encoding="ascii")
    )
    registry = load_scientific_program_registry(ROOT)
    selectors = dict(
        zip(
            SESSION_GAP_BUNDLE_ROLES,
            ("V2SEL4001", "V2SEL4002", "V2SEL4003"),
            strict=True,
        )
    )
    shared = {
        "feature": "V2FP2001",
        "label": "V2LP1001",
        "model": "V2MP1001",
        "calibration": "V2CP1001",
        "trade": "V2TP1002",
        "sizing": "V2SZ1001",
        "portfolio_risk": "V2PR1001",
    }
    roles = {
        role: {**shared, "selector": selectors[role]}
        for role in SESSION_GAP_BUNDLE_ROLES
    }
    batch = build_scientific_bundle_batch(registry, roles)
    release_hashes = dict(bind_session_gap_failure_runtime(registry, batch))

    payload["hypothesis_id"] = "V2H0005"
    payload["name"] = "cash_open_gap_failure_fixture"
    payload["question"] = "does_the_fixed_session_contrast_validate"
    payload["program_registry"]["sha256"] = registry.registry_sha256
    payload["autonomy_batch"].update(
        hypothesis_id="V2H0005",
        family_id="cash_open_gap_failure_v1",
        hypothesis_type="structural_batch",
        dominant_axis="axis_session",
        scout_mode="s_breadth",
        bundle_roles=dict(batch.bundle_role_hashes),
        semantic_signature_sha256=sha256_payload(
            {"fixture": "cash_open_gap_failure_v1"}
        ),
        parent_evidence_ids=[],
        coupled_program_kinds=[],
        numeric_knobs=[],
        local_calibration_rounds=0,
        automatic_range_extensions=0,
    )
    payload["executable_programs"].update(
        bundle_roles=roles,
        runtime_sha256=registry.runtime_sha256,
        runtime_executable_sha256=SESSION_GAP_FAILURE_EXECUTABLE_SHA256,
        release_configuration_hashes=release_hashes,
        selection_rule_sha256=SESSION_GAP_SELECTION_RULE_SHA256,
    )

    data_config = yaml.safe_load(
        (ROOT / "configs/v2/data.yaml").read_text(encoding="ascii")
    )
    payload["data"]["causal_cost_policy"] = deepcopy(
        data_config["cost_quality"]["active_causal_fallback"]
    )
    payload["data"]["material_ids"] = sorted(
        [*payload["data"]["material_ids"], "V2MAT000006"]
    )
    payload["data"]["session_clock_binding"] = {
        "clock_contract_material_id": "V2MAT000006",
        "clock_rule_id": "fpmarkets_ny_close_plus_7_v1",
        "server_minus_new_york_hours": 7,
        "server_cash_open_bar": "16:30",
        "cash_open_semantics": "dataset_timestamp_proxy",
        "clock_authority_claim": False,
        "market_calendar_authority": False,
        "historical_mt5_clock_receipt_pending": True,
    }
    payload["falsification"] = {
        "scientific_reject_conditions": ["economic_or_control_failure"],
        "repair_conditions": ["invalid_runtime_or_clock"],
        "scale_miss_conditions": ["registered_timestamp_surface_sparse"],
    }

    acceptance = payload["acceptance_profile"]
    acceptance["profile_id"] = "V2SAP0005"
    for rule in acceptance["resolved_rules"]:
        if rule["name"] == "evaluable_trade_count":
            rule["failure_effect"] = "evidence_gap"
        if rule["name"] == "net_broker_points":
            rule["tuning_role"] = "none"
    acceptance["profile_sha256"] = sha256_payload(
        {
            "profile_id": acceptance["profile_id"],
            "resolved_rules": acceptance["resolved_rules"],
            "dimension_order": acceptance["dimension_order"],
        }
    )
    payload["sensitivity_plan"] = {
        "enabled": False,
        "disabled_reason": (
            "fixed_matched_mechanism_and_controls_no_registered_numeric_surface"
        ),
        "data_role": "validation_oos",
        "development_variant_selection_allowed": False,
        "holdout_revealed": False,
        "candidate_frozen": False,
        "selection_feasibility": {
            "causal_checks_required": True,
            "unknown_cost_observation_count_max": 0,
            "evaluable_trade_count_min_per_fold": 20,
        },
        "policy": {},
        "local_calibration_rounds_max": 0,
        "surface_rule": {
            "metric_name": "shadow_net_broker_points",
            "higher_is_better": True,
            "viability_threshold": 0.0,
            "pass_threshold": 0.01,
            "plateau_tolerance": 0.0,
            "fold_consistency_min": 0.67,
        },
    }
    payload["trial_plan"] = {
        "frozen_before_results": True,
        "family_id": "cash_open_gap_failure_v1",
        "unique_variant_cap": 3,
        "validation_evaluation_cell_cap": 9,
        "local_calibration_new_evaluations_per_outer_fold_max": 0,
        "development_paths_per_fold_max": 1,
        "family_trials_before": 0,
        "family_configuration_hashes_before": [],
        "family_history_sha256_before": sha256_payload([]),
        "global_trials_before": len(GLOBAL_CONFIGURATION_HASHES),
        "global_configuration_hashes_before": GLOBAL_CONFIGURATION_HASHES,
        "global_history_sha256_before": sha256_payload(
            GLOBAL_CONFIGURATION_HASHES
        ),
    }
    payload["evidence_budget"] = {
        "scout_jobs_max": 1,
        "configuration_trials_max": 3,
        "validation_evaluation_cells_max": 9,
        "development_paths_per_fold_max": 1,
        "mt5_runs_max": 0,
        "holdout_reveals_max": 0,
        "job_timeout_seconds": 900,
    }
    return payload


class SessionHypothesisContractTests(unittest.TestCase):
    def test_active_three_role_session_hypothesis_is_exactly_validated(self) -> None:
        validated = validate_hypothesis_v2_payload(
            session_hypothesis_payload(),
            project_root=ROOT,
        )
        self.assertEqual(
            SESSION_GAP_SELECTION_RULE_SHA256,
            validated["selection_rule_sha256"],
        )
        self.assertEqual(3, len(validated["initial_configuration_hashes"]))
        self.assertEqual(0.0, validated["surface_rule"].plateau_tolerance)
        self.assertEqual(
            SESSION_GAP_FAILURE_EXECUTABLE_SHA256,
            validated["runtime_executable_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
