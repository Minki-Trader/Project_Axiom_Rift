"""Evidence-gated H/S/R/P/M lifecycle decisions independent of I/O."""

from __future__ import annotations

import re
from typing import Any, Mapping

from axiom_rift.v2.state.transitions import TransitionError, claim_index


STAGE_ID_PATTERNS = {
    "H": re.compile(r"^V2H[0-9]{4}$"),
    "S": re.compile(r"^V2S[0-9]{4}$"),
    "R": re.compile(r"^V2R[0-9]{4}$"),
    "P": re.compile(r"^V2P[0-9]{4}$"),
    "M": re.compile(r"^V2M[0-9]{4}$"),
}


def validate_stage_basis(
    *,
    current_stage: str,
    new_stage: str,
    new_stage_id: str,
    current_claim: str,
    basis: Mapping[str, Any] | None,
) -> None:
    pattern = STAGE_ID_PATTERNS.get(new_stage)
    if pattern is None or not pattern.fullmatch(new_stage_id):
        raise TransitionError(f"stage id does not match {new_stage}: {new_stage_id}")
    receipt = dict(basis or {})
    if current_stage == "bootstrap" and new_stage == "H":
        if receipt.get("hypothesis_preregistered") is not True:
            raise TransitionError("bootstrap -> H requires a preregistered hypothesis")
        return
    if current_stage == "H" and new_stage == "S":
        if receipt.get("hypothesis_preregistered") is not True:
            raise TransitionError("H -> S requires the active preregistration receipt")
        return
    if current_stage == "S" and new_stage == "R":
        if receipt.get("outcome") != "route_to_R" or receipt.get("gate_passed") is not True:
            raise TransitionError("S -> R requires a surviving scout receipt")
        if claim_index(current_claim) < claim_index("diagnostic_observation"):
            raise TransitionError("S -> R requires diagnostic_observation")
        return
    if current_stage == "R" and new_stage == "P":
        if receipt.get("outcome") != "research_candidate_confirmed":
            raise TransitionError("R -> P requires confirmed research-candidate evidence")
        if claim_index(current_claim) < claim_index("research_candidate"):
            raise TransitionError("R -> P requires research_candidate")
        return
    if current_stage == "P" and new_stage == "M":
        if receipt.get("outcome") != "selected":
            raise TransitionError("P -> M requires a selected frozen identity receipt")
        if receipt.get("frozen_identity_bundle_sha256") in {None, ""}:
            raise TransitionError("P -> M requires a frozen identity bundle")
        if claim_index(current_claim) < claim_index("selected"):
            raise TransitionError("P -> M requires selected")
        return
    if new_stage == "H" and current_stage in {"S", "R", "P"}:
        if receipt.get("disposition_recorded") is not True:
            raise TransitionError(f"{current_stage} -> H requires a closed disposition")
        return
    raise TransitionError(f"unsupported evidence-gated transition: {current_stage} -> {new_stage}")


def prove_full_lifecycle_guard_path() -> dict[str, bool]:
    cases = (
        ("bootstrap", "H", "V2H9991", "none", {"hypothesis_preregistered": True}),
        ("H", "S", "V2S9991", "none", {"hypothesis_preregistered": True}),
        ("S", "R", "V2R9991", "diagnostic_observation", {"outcome": "route_to_R", "gate_passed": True}),
        ("R", "P", "V2P9991", "research_candidate", {"outcome": "research_candidate_confirmed"}),
        ("P", "M", "V2M9991", "selected", {"outcome": "selected", "frozen_identity_bundle_sha256": "0" * 64}),
    )
    results: dict[str, bool] = {}
    for current, new, stage_id, claim, basis in cases:
        validate_stage_basis(
            current_stage=current,
            new_stage=new,
            new_stage_id=stage_id,
            current_claim=claim,
            basis=basis,
        )
        results[f"{current}_to_{new}"] = True
    return results
