# Axiom Rift Experiment Direction Contract

schema: axiom_rift_experiment_direction_contract_v1
status: draft_active
encoding: ascii_only
audience: codex_only

## Purpose

Define the exploration posture for Codex during Axiom Rift research.

This contract answers only one question:

How should Codex explore?

This contract does not define KPI fields, sizing rules, execution assumptions, campaign batch
mechanics, campaign transition rules, record layout, promotion gates, materialization gates, or
runtime validation gates.

## Core Direction

Codex should search broadly and autonomously for profitable US100 M5 trading structure without
freezing labels, features, model families, objectives, trade logic, or trade shape before evidence
requires it.

## Principle 1: Autonomous Discovery

Codex may propose and test labels, features, model families, objectives, trade logic, entry logic,
exit logic, filters, ensembles, direction-specific models, and other reproducible decision
surfaces.

No label, feature set, model family, objective, or trade shape is selected by default.

## Principle 2: Wide Surface Search

Exploration is not limited to model comparison.

Valid search surfaces include, but are not limited to:

- label shape
- label horizon
- feature source
- feature representation
- feature count
- model family
- model objective
- entry logic
- exit logic
- long and short separation
- session split
- regime split
- filter logic
- ensemble logic
- risk logic as a research variable

## Principle 3: Campaign As Open Canvas

A campaign is a broad research workspace, not a narrow model/topic stage.

Inside an active discovery campaign, Codex may test many unrelated or loosely related hypotheses
as long as they remain within active project constraints and claim boundaries.

Detailed campaign mechanics belong in a separate campaign contract or campaign manifest.

## Principle 4: No Premature Direction Lock

A single good clue cannot redirect the whole campaign.

A clue may justify follow-up, contrast, recombination, or stress testing. It does not freeze the
campaign direction, selected surface, model family, label family, or trade logic.

## Principle 5: Hypothesis Memory As Search Pressure

Past hypotheses should influence future search behavior.

Use prior results to:

- reduce near-duplicate loops
- lower priority for repeated weak surfaces
- generate contrast hypotheses
- recombine useful fragments
- stress new candidates against known failure modes
- preserve room for unrelated exploration

Prior failure is not a broad ban. Prior success is not a direction freeze.

## Principle 6: Exploit, Contrast, Recombine, Diverge

Future exploration should not follow only the nearest positive clue.

Codex should mix these behaviors when forming new experiments:

- exploit: follow up a useful clue
- contrast: test the opposite or missing side
- recombine: mix useful pieces from different hypotheses
- diverge: keep exploring unrelated surfaces

No fixed ratio is defined here.

## Principle 7: Micro-Repair Loop Guard

Codex should avoid endless adjacent tweaks that pretend to be new hypotheses.

Examples of near-duplicate repair include:

- threshold-only changes
- cooldown-only changes
- small SL/TP changes
- small parameter-only changes
- one-feature add/remove changes on the same surface
- repeating the same label/model/trade-shape cluster without material novelty

Further work on a similar surface should introduce material novelty in at least one major axis,
such as label/target, feature representation, model objective, trade shape, risk logic, session or
regime split, validation philosophy, or runtime representation.

## Principle 8: Evidence Before Claim

Claims must stay no stronger than the evidence.

Proxy evidence can support a scout clue. It cannot claim runtime economics.

Backtest evidence can support candidate interest. It cannot claim live readiness.

MT5 or runtime evidence can support runtime observations only within the tested boundary.

Live-readiness, runtime authority, selected baseline, winner, or operating promotion claims require
separate active contracts and completed evidence.

## Claim Boundary

This contract does not claim:

- label_selected: true
- feature_set_selected: true
- model_selected: true
- runtime_probe_completed: true
- economics_pass: true
- materialization_ready: true
- runtime_authority: true
- live_ready: true

This contract defines exploration posture only.
