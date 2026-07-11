# Axiom

Axiom is a local operating kernel for professional FPMarkets US100 M5
quantitative research and candidate-bound ONNX, EA, and MT5 proof.

`OPERATING_DIRECTION.md` is the persistent Project Goal. A bare `/goal` or a
one-line `/goal` directive is sufficient intake. At most one first or successor
Mission is active; an active Mission resumes, while a successor is admitted
only through its exact predecessor terminal.

Only `completed_pre_live_handoff` completes and latches the persistent API
Goal. A valid `closed_no_candidate` terminal closes one Mission and continues
through its bound successor. A genuine external blocker waits for its exact
resume condition without manufacturing completion or new scientific evidence.

## Structure

- `OPERATING_DIRECTION.md`: permanent sponsor direction
- `AGENTS.md`: boot and trigger router
- `foundation/`: immutable market, environment, data, exposure, and origin facts
- `contracts/`: lifecycle, science, evidence, and runtime rules
- `state/control.json`: the only mutable control projection
- `records/`: append-only durable authority and coherent closeouts
- `src/axiom_rift/core/`: domain identity and canonical value primitives
- `src/axiom_rift/operations/`: the sole writer and typed capabilities
- `src/axiom_rift/research/`: Portfolio, trial, and external-source semantics
- `src/axiom_rift/storage/`: journal, control, index, and local evidence storage
- `src/axiom_rift/runtime/`: late-bound candidate and Release claim guards
- `.agents/skills/`: three progressively disclosed operating workflows
- `local/`: ignored index, evidence, cache, locks, and temporary execution state

Candidate-specific adapters remain absent until a frozen Executable makes one
scientifically relevant. Runtime owns those future adapters; Python retains
training, hashing, parsing, and records, while a future EA stays thin.

## Local Commands

```powershell
$env:PYTHONPATH = (Join-Path $PWD "src")
python -m axiom_rift.cli status
python -m axiom_rift.cli recover
python -m unittest tests.core.test_identity tests.storage.test_index
```

Verification is selected by the changed reusable surface. There is no mandatory
full-suite, PR, CI, external review, or portable deployment requirement.
