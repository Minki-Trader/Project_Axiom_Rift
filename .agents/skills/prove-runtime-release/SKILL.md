---
name: prove-runtime-release
description: Plan and execute candidate-bound ONNX, MQL5, MQH, EA, MT5, execution-proof, parity, materialization, and Release evidence for Axiom. Use whenever work touches model export or inference, EA or include code, MetaEditor compilation, Strategy Tester runs, logic or intent parity, lifecycle and cost parity, runtime recertification, or pre-live handoff.
---

# Prove Runtime Release

Read `contracts/runtime.yaml`, `contracts/evidence.yaml`, the frozen candidate Executable, its source bindings, and its active Job. Return evidence and a proposed Decision to the root operator; never mutate canonical state directly.

## Entry Gates

- Require candidate-bound evidence depth and a valid RuntimePermit before runtime work.
- Preregister each runtime-bound Job's action, evidence depth, claim surfaces,
  durable outputs, and exact Executable subject. Start it only after the writer
  jointly validates its JobPermit and RuntimePermit against the current
  candidate activation.
- Revalidate the actual signed permit, active candidate, and every current source
  state through `StateWriter.validate_runtime_entry` at the engine boundary;
  caller booleans are never authority.
- Persist the exact runtime engine-entry attestation before completion. A
  registered implementation-bound validator must read every declared durable
  artifact from an immutable request and the writer rechecks its hash after return.
- Require a frozen Executable and exact component, data, split, feature-order, preprocessing, model, selector, trade, risk, lifecycle, cost, clock, engine, and source identities before materialization.
- Do not spend MT5 or materialization work on every discovery clue.
- Do not avoid decision-relevant runtime proof because it is inconvenient or likely to fail.

## Evidence Chain

Prove only what each step executes:

1. Raw input and causal availability.
2. Python feature versus MQL feature.
3. Python model versus ONNX Runtime.
4. ONNX Runtime versus EA inference.
5. Python decision versus EA decision and position intent.
6. Entry, exit, and position lifecycle.
7. Native completed-bar logic.
8. Native real-tick economics, costs, and execution divergence.

Timestamps and directions require exact parity. Freeze numeric tolerances before results. Compile success, an ONNX file, schedule replay, and aggregate profit each prove only their own narrow surface.

## Materialization And Release

- Keep the EA thin and reusable MQL logic in focused include modules.
- Bind exact model I/O names, shapes, types, feature order, and artifact hashes.
- Cover cold start, warmup, duplicate-bar protection, restart, source interruption, stale or missing input, model-load failure, clock and DST, symbol mapping, and missing KPI.
- Recheck source eligibility at startup, refresh, and decision boundaries.
- Suspend on semantic drift; same-semantics recertification may restore eligibility without a new scientific trial.
- Require a ReleasePermit and all candidate-bound evidence before freezing the local handoff bundle.
- Build `ReleaseEvidence` only from successful runtime Job completion record
  IDs. The writer derives parity, materialization cases, artifacts, Mission,
  Executable, candidate activation, permit, and source receipts; caller-written
  coverage summaries are never Release authority.
- Declare and freeze Release only through the writer so its permit, artifacts,
  candidate, Executable, Mission, parity surfaces, and materialization cases are
  one bound terminal basis.
- Require exactly one artifact for each Release role in `contracts/runtime.yaml`;
  the canonical local handoff manifest binds all other role hashes and the
  Mission/candidate/Executable/source authority. Dispose an invalid or abandoned
  Release before candidate disposition or replacement.
- Never claim live-ready authority.
- While a frozen Release is the pending positive terminal basis, permit only
  exact Mission close or `release_disposed` with invalidated disposition. Use
  the latter when final revalidation breaks the frozen basis, then resume
  candidate-bound evidence.

Treat export, compile, parser, terminal, tester, and parity plumbing failures as Repair unless scientific semantics changed.
