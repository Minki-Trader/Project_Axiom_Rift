---
name: obsidian-artifact-lineage
description: Track how inputs, code, configs, runs, models, reports, hashes, manifests, ledgers, and external artifact locations connect before evidence or handoff claims are made.
---

# Obsidian Artifact Lineage

Use this skill when work creates, consumes, moves, ignores, packages, releases, or reports artifacts.

## Required Output

- `source_inputs`: data, config, model, bundle, EA, or report inputs
- `producer`: script, pipeline, tester, manual command, or external system that produced the artifact
- `consumer`: next script, run, report, registry, PR, or user action that depends on it
- `artifact_paths`: repo-relative paths when durable; local absolute paths only as local context
- `artifact_hashes`: content hash, params hash, module hash, model hash, or reason unavailable
- `registry_links`: artifact registry, run registry, alpha ledger, stage ledger, or release note rows
- `availability`: tracked, generated, ignored_with_manifest, external_uri, reproducible_from_command, missing, or blocked
- `lineage_judgment`: connected, connected_with_boundary, disconnected, inconclusive, or blocked

## Guardrails

- Do not let a ledger point to missing evidence without a manifest, external URI, or regeneration command.
- Do not commit heavy artifacts just to close an evidence gap; prefer manifest, hash, release, or regeneration path when appropriate.
- Do not treat a report as the same thing as a model or runtime bundle.
