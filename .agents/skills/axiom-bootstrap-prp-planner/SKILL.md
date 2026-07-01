---
name: axiom-bootstrap-prp-planner
description: Use this bootstrap-only skill when creating Axiom-native planning runbooks that combine requirements, codebase intelligence, and validation loops without PR or runtime claims.
status: bootstrap_only
---

# Axiom Bootstrap PRP Planner

allowed_use:
  - Create bounded Axiom planning runbooks from user requirements and active project files.
  - Require codebase intelligence before implementation recommendations.
  - Define validation loops as proposed checks, not as proof of runtime authority.
  - Keep plans aligned with `contracts/`, `configs/`, `registries/`, `campaigns/`, `src/axiom_rift/`, `.agents/skills/`, and `tests/`.

forbidden_use:
  - Do not execute external scripts.
  - Do not invoke MCP.
  - Do not install external plugins.
  - Do not use external memory integrations.
  - Do not run autonomous plan to implement to PR loops.
  - Do not create PRs or publish reviews.
  - Do not treat validation samples, compile checks, or diagnostics as runtime authority.
  - Do not create runtime, ONNX, selected model, live, or promotion claims.

source_reference_policy:
  external_prp_repos_are_reference_only: true
  keep_concepts:
    - requirements_plus_codebase_intelligence
    - bounded_scope
    - mandatory_reading_lists
    - validation_loop_design
    - implementation_risk_notes
  exclude_concepts:
    - `.claude/PRPs` path assumptions
    - autonomous loop state files
    - PR creation flow
    - PR review posting
    - external web or memory dependencies as required inputs

axiom_path_policy:
  planning_outputs_may_reference:
    - contracts/
    - configs/
    - registries/
    - campaigns/
    - src/axiom_rift/
    - .agents/skills/
    - tests/
  planning_outputs_must_not_require:
    - .claude/
    - external plugin directories
    - top-level scratch/
    - top-level notes/
    - top-level experiment/
    - top-level scripts/
    - top-level stage/
  active_file_encoding: ascii_only

output_policy:
  produce:
    - problem_statement
    - scope_boundary
    - mandatory_reading
    - files_to_consider
    - validation_plan
    - risks_and_open_questions
  do_not_produce:
    - copied vendor templates
    - implementation commits
    - PR bodies
    - runtime authority summaries
    - model selection summaries
  validation_language:
    - use "proposed check" for future checks
    - use "observed evidence" only for evidence already present in active Axiom files
    - never upgrade diagnostics into claims

removal_condition:
  remove_after: axiom_native_skills_complete
  rationale: Permanent Axiom planning skills should replace this temporary PRP-inspired bridge.

claim_boundary:
  claim_authority: false
  may_change_claim_state: false
  no_runtime_claims: true
  no_model_claims: true
  no_live_claims: true
  no_promotion_claims: true
  must_preserve:
    label_selected: false
    feature_set_selected: false
    model_selected: false
    runtime_authority: false
    live_ready: false
  required_note: A runbook can improve implementation readiness, but it cannot assert selection, promotion, runtime authority, ONNX readiness, or live readiness.
