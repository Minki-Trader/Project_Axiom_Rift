---
name: axiom-bootstrap-campaign-skeletonizer
description: Use this bootstrap-only skill when converting Axiom planning intent into repo-local campaign skeleton proposals that preserve Axiom paths and claim boundaries.
status: bootstrap_only
---

# Axiom Bootstrap Campaign Skeletonizer

allowed_use:
  - Draft Axiom-native campaign skeletons under `campaigns/<campaign_id>/`.
  - Map PRD-like or epic-like planning ideas into Axiom files: `campaign.yaml`, `inputs.yaml`, and `selected.yaml`.
  - Propose task breakdowns with dependencies, blocked status, and next-work fields.
  - Keep GitHub Issues, worktrees, and vendor paths outside Axiom active truth.

forbidden_use:
  - Do not execute external scripts.
  - Do not invoke MCP.
  - Do not install external plugins.
  - Do not use external memory integrations.
  - Do not sync Axiom tasks to GitHub Issues.
  - Do not create worktrees or PR automation.
  - Do not place raw data or run artifacts in campaign roots.
  - Do not mark label, feature set, model, runtime, promotion, ONNX, or live readiness as selected.

source_reference_policy:
  planning_refs_are_reference_only: true
  allowed_reference_concepts:
    - PRD to task decomposition
    - spec traceability
    - status reporting
    - blocked and next queues
  disallowed_reference_concepts:
    - `.claude/prds` as required path
    - `.claude/epics` as required path
    - GitHub Issues as source of truth
    - worktree automation
    - autonomous PR loops

axiom_path_policy:
  campaign_root: campaigns/<campaign_id>/
  required_campaign_files:
    - campaign.yaml
    - inputs.yaml
    - selected.yaml
  allowed_existing_paths:
    - contracts/
    - configs/
    - registries/
    - campaigns/
    - src/axiom_rift/
    - .agents/skills/
    - tests/
  forbidden_top_level_paths:
    - scratch/
    - notes/
    - experiment/
    - experiments/
    - scripts/
    - stage/
  active_file_encoding: ascii_only

output_policy:
  produce:
    - campaign_skeleton_plan
    - task_inventory
    - dependency_notes
    - blocked_next_status
    - validation_placeholders_without_runtime_claims
  do_not_produce:
    - executable vendor scripts
    - installer steps
    - GitHub issue mappings
    - worktree commands
    - PR creation instructions
  default_status_values:
    campaign_status: draft
    selected_status: none
    claim_authority: false

removal_condition:
  remove_after: axiom_native_skills_complete
  rationale: Replace this temporary wrapper with permanent Axiom campaign planning skills.

claim_boundary:
  claim_authority: false
  may_change_claim_state: false
  must_preserve:
    label_selected: false
    feature_set_selected: false
    model_selected: false
    runtime_authority: false
    live_ready: false
  prohibited_claims:
    - runtime_probe_completed
    - economics_pass
    - materialization_ready
    - promotion_ready
    - onnx_ready
  required_note: A campaign skeleton may organize exploration, but it does not freeze labels, features, models, objectives, or trade shapes.
