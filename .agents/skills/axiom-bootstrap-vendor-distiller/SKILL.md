---
name: axiom-bootstrap-vendor-distiller
description: Use this bootstrap-only skill when distilling external skill pack ideas into Axiom-native skill design notes without treating vendor repos as active truth.
status: bootstrap_only
---

# Axiom Bootstrap Vendor Distiller

allowed_use:
  - Inspect external skill pack structure as read-only reference material.
  - Extract portable ideas for Axiom skill packaging, validation, and scope control.
  - Produce concise Axiom-native recommendations for files under `.agents/skills/`.
  - Record vendor source boundaries in `registries/bootstrap_vendor_sources.yaml`.

forbidden_use:
  - Do not execute external scripts.
  - Do not invoke MCP.
  - Do not install external plugins.
  - Do not use external memory integrations.
  - Do not import GitHub Issues, worktrees, PR automation, or vendor registries as Axiom truth.
  - Do not copy external files or skill text verbatim into active Axiom files.

source_reference_policy:
  external_repos_are_reference_only: true
  active_truth_sources:
    - AGENTS.md
    - registries/reentry.yaml
    - registries/claim_state.yaml
    - contracts/
    - configs/
  vendor_material_may_inform:
    - skill_packaging_shape
    - progressive_disclosure
    - validation_checklist_design
    - temporary_bootstrap_skill_boundaries
  vendor_material_must_not_define:
    - Axiom claims
    - Axiom runtime authority
    - selected labels
    - selected features
    - selected models
    - live readiness

axiom_path_policy:
  preserve_paths:
    - contracts/
    - configs/
    - registries/
    - campaigns/
    - src/axiom_rift/
    - .agents/skills/
    - tests/
  do_not_create_top_level:
    - scratch/
    - notes/
    - experiment/
    - experiments/
    - scripts/
    - stage/
  active_file_encoding: ascii_only

output_policy:
  outputs_are:
    - distilled_design_notes
    - proposed_axiom_skill_shapes
    - exclusion_lists
    - registry_entries_for_vendor_sources
  outputs_are_not:
    - active contracts
    - selected baselines
    - runtime configs
    - model artifacts
    - live readiness evidence
  style:
    - concise
    - machine_oriented
    - ASCII only

removal_condition:
  remove_after: axiom_native_skills_complete
  rationale: This wrapper only bridges external audit findings into first Axiom-native skill drafts.

claim_boundary:
  claim_authority: false
  may_change_claim_state: false
  prohibited_claims:
    - runtime_authority
    - live_ready
    - model_selected
    - feature_set_selected
    - label_selected
    - promotion_ready
    - onnx_ready
  required_note: Any recommendation from this skill is advisory until accepted by active Axiom contracts or decision records.
