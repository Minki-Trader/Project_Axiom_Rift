# Analog Replay Performance Repair

status: repaired_benchmarked_and_prospective_job_route_activated
mission: MIS-0006
historical_study: STU-0106
reference_completion_record_id: 6a440e0bb2176ae9cf6dad6a4458077a473d2c87053fbc03633f5c8bb052f791
reference_trace_sha256: 42fb5e3556387e681e0e18ec64a4eec8dd8bd8674ae7b59b6927d4d20e5b1651
implementation_bundle_sha256: 87d179020c6648f1f719f26366a142ec928507c9435a2e42be44744c33e9fe66
holdout_reads: 0
quarantine_reads: 0
scientific_trial_delta: 0
candidate_claim_delta: 0

## Scope

This repair addresses the observed compute and memory bottleneck in the exact
four-member STU-0106 analog replay. It is engineering evidence only. It does
not alter STU-0106, create a scientific result, satisfy another replay
obligation, expose holdout data, or create candidate authority.

The v1 implementation and every v1-bound evidence file remain byte-stable.
All repaired paths have new implementation and Executable identities.

## Root Cause

The historical producer built fold features repeatedly and queried a KD-tree
for every valid row in both the full and prefix frames. It retained full and
prefix arrays for every fold and profile until all four configurations had
been evaluated. The result combined three independent costs:

- repeated feature and target construction across folds;
- unbounded full-frame neighbour matrices and retained fold arrays;
- about 18.90 million full/prefix query rows, producing about 491.7 million
  neighbour outputs even though only train-calibration and test-decision rows
  can affect the registered scientific result.

The original first producer Job ran from approximately 2026-07-14T07:33:00Z
to 2026-07-14T07:44:43Z. That 703 second operational boundary includes the
complete Job environment and is preserved as historical observation, not used
as the controlled benchmark baseline below.

## Repair

The successor implementation:

- prepares immutable shared frame arrays once and profile arrays once;
- bounds KD-tree query allocations to 50,000 rows;
- streams one profile through the complete family before releasing it;
- keeps a full-vector path solely for exact v1 certification;
- gives the prospective repeated-research path a distinct registered query
  scope, Component protocol, parameter, engine contract, and Executable ID;
- derives that scope only from the registered train-calibration and test
  decision windows; callers cannot provide arbitrary masks;
- fails closed on invalid time, family, chunk, capture, inventory, or
  implementation bindings.

The prospective scope is
`train_calibration_union_test_decision_rows_v1`. Scores outside that scope are
not computed and cannot influence selector calibration, test decisions,
trades, intents, costs, or metrics.

## Controlled Benchmark Evidence

All runs used the same current PC, Python environment, observed-development
material, nine registered folds, four-member family, reference completion,
and 50,000-row query chunk. Peak RSS was sampled with psutil; absence of
psutil is a hard failure.

| Engine | Elapsed seconds | Peak RSS bytes | Parity |
| --- | ---: | ---: | --- |
| frozen v1 full trace | 178.930 | 1,312,575,488 | full trace exact |
| v2 full-vector certification | 176.858 | 537,452,544 | full trace exact |
| v2 prospective scoped trace | 61.673 | 532,938,752 | reachable decisions exact |

The full-vector v2 is not claimed as a CPU repair: it reduced controlled peak
RSS by about 59 percent while leaving elapsed time essentially unchanged. The
prospective scoped path reduced elapsed time by about 65 percent, or about
2.90 times, while preserving every reachable decision and raw metric.

The separate row-level verifier performed 36 exact/scoped full-prefix
comparisons:

- exact query rows: 18,899,558;
- scoped query rows ratio: 0.235775;
- exact fit time: 151.770 seconds;
- scoped fit time: 35.941 seconds;
- scoped/exact fit time ratio: 0.236815;
- exact equality on every declared row: passed;
- no value outside the declared query scope: passed.

The repeatable verifier enforces these conservative acceptance bounds:

- full-vector v2: at most 360 seconds and 1 GiB peak RSS;
- scoped trace: at most 150 seconds and 768 MiB peak RSS;
- scoped row ratio: at most 0.30;
- scoped fit-time ratio: at most 0.60.

## Evidence Boundary And Activation

`full_exact_v1_parity` is a maintenance certification path and must not be
selected for repeated research. `decision_scope_v2` is the prospective
research path and has a different identity. A v1 cache or STU-0106 artifact
must never be relabelled as a v2 output.

The code-level engine and identities are repaired and benchmarked. The
prospective route now has a writer-permitted Job callable, a first-member-only
producer, a producer-trace plus cache-hash consumer binding, missing-cache
recovery only from the verified producer trace, and a registered atomic proof
dispatcher. A real full trace was wrapped in the new Job evidence envelope and
recomputed through that dispatcher:

- neutral cache SHA-256:
  `4a5f37025962f68a4d0fd95fc446f131469622c11a75c33ba9f775fa26b25a98`;
- subject trace SHA-256:
  `b06319a3e54b0f020f6c9fa4ecdbd7f1d5925262303f6e0d3df0d6088f640d28`;
- protocol: `analog_state.concurrent_four_config.scoped_query.v2`;
- all four registered evidence modes dispatched and recomputed;
- projected v1 identities existed only as non-authoritative in-memory formula
  inputs and were never emitted as evidence.

This engineering certification is not a canonical scientific Job completion.
A future permitted analog Study can now select the repaired route, but this
record grants it no trial, claim, candidate, or terminal credit in advance.
