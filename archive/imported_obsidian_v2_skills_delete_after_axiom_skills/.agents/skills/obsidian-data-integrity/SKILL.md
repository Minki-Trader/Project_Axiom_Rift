---
name: obsidian-data-integrity
description: Check data, time-axis, timezone, split, missing row, duplicate row, leakage, and feature-label boundary risks before trading research results are trusted.
---

# Obsidian Data Integrity

Use this skill whenever work touches datasets, features, labels, splits, bars, timestamps, joins, resampling, training windows, runtime inputs, or KPI interpretation.

## Required Output

- `data_source`: source files, broker feed, runtime output, or generated artifact
- `time_axis`: timestamp meaning, timezone policy, bar close/open convention, and ordering
- `sample_scope`: symbol, timeframe, date range, tiers, rows, and exclusions
- `missing_or_duplicate_check`: whether gaps or duplicates matter here
- `feature_label_boundary`: how future data is prevented from entering features
- `split_boundary`: train, validation, test, WFO, or runtime split meaning
- `leakage_risk`: most likely lookahead or selection-bias path
- `data_hash_or_identity`: file hash, row count, artifact id, or reason unavailable
- `integrity_judgment`: usable, usable_with_boundary, inconclusive, invalid, or blocked

## Guardrails

- Do not trust a profitable result before the time axis and label boundary are named.
- Do not hide timezone assumptions in variable names.
- Do not mix feature and label logic without an explicit boundary and test intent.
- Do not call a result invalid when it is only incomplete; name the missing integrity check.
