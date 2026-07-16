# Study Continuation Typed-Exit Regression

status: corrected
date: 2026-07-16
mission: MIS-0006
initiative: INI-0025

## Finding

The Study-continuation regression fixture evaluated one Executable, recorded a
`continue_batch` evidence disposition, and then closed the still-started Batch
as `stopped_early`. That route contradicted the already active typed Batch-exit
boundary: `continue_batch` keeps the current bounded Batch open, while a
non-budget exit requires an exact disposition-driving `stop_batch` completion.

Changing the fixture to `stop_batch` would also be wrong for its intended
continuation branch because the Study stop rule would then be reached. The
scientifically coherent intermediate path is to exhaust the frozen first-Batch
trial bound while its evidence remains `continue_batch`, close that Batch as
`budget_exhausted`, and let `StudyContinuationDecision` compare another Batch
against the live Portfolio alternatives.

## Correction

The first Batch now preregisters exactly one trial. Its one evaluated member
exhausts that immutable bound, so `budget_exhausted` is Writer-derived rather
than caller prose. The continuation review then retains the unchanged Study
question, chassis, axis, evidence bindings, and opportunity-cost comparison
before prebinding the second Batch.

production_writer_change: false
scientific_trial_delta: 0
scientific_claim_delta: 0
holdout_delta: 0
false_green_removed: true

The focused real Writer lifecycle test passes through the corrected path.
