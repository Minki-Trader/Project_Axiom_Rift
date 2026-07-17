from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_replay_admission_contract_has_one_operational_authority_home() -> None:
    operations = yaml.safe_load(
        (ROOT / "contracts" / "operations.yaml").read_text(encoding="ascii")
    )
    science = yaml.safe_load(
        (ROOT / "contracts" / "science.yaml").read_text(encoding="ascii")
    )
    admission = operations["replay_implementation_admission"]
    legacy = admission["legacy_registration_only_recertification"]
    terminal = admission["replacement_required_terminal"]

    assert admission["single_writer"] == (
        "axiom_rift.operations.writer.StateWriter"
    )
    assert admission["schemas"] == {
        "legacy_registration_only_recertification": (
            "replay_implementation_admission.v2"
        ),
        "prospective_atomic_study_open": "replay_implementation_admission.v1",
    }
    assert legacy["study_must_precede_exact_current_protocol_activation"] is True
    assert legacy["post_activation_missing_admission_may_recertify"] is False
    assert legacy["protocol_rebind_is_replacement_or_terminal_authority"] is False
    assert legacy["counted_prefix_refund_rewrite_reorder_or_recount_allowed"] is False
    assert terminal["same_identity_repair_or_protocol_rebind_is_terminal_authority"] is False
    assert terminal["one_accepted_replacement_per_rejected_preflight"] is True
    assert terminal["prior_counted_prefix_is_never_refunded_or_reused"] is True
    assert science["study_kpi_projection"]["representative_executable"][
        "no_final_validator_completion"
    ]["legacy_registration_only_replay_implementation_rejection"][
        "operations_authority"
    ] == "replay_implementation_admission.replacement_required_terminal"


def test_research_skill_routes_to_contract_without_copying_protocol_failure() -> None:
    skill = (
        ROOT / ".agents" / "skills" / "run-research-portfolio" / "SKILL.md"
    ).read_text(encoding="ascii")

    assert "`replay_implementation_admission`" in skill
    assert "never refund or recount its existing multiplicity" in skill
    assert "scientific_protocol_not_current" not in skill
