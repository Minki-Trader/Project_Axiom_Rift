---
name: obsidian-performance-attribution
description: Explain why KPI changed by decomposing performance across time, sample, tier, feature, threshold, model, trade shape, drawdown, and regime before claiming improvement.
---

# Obsidian Performance Attribution

Use this skill when a result is better, worse, surprising, unstable, or used to choose the next experiment.

## Required Output

- `observed_change`: KPI or behavior that changed
- `comparison_baseline`: what it changed against
- `likely_drivers`: threshold, model, feature, data scope, tier mix, trade frequency, risk shape, or market regime
- `segment_checks`: time period, tier, direction, volatility, session, drawdown cluster, or trade bucket checks performed or missing
- `trade_shape`: count, win rate, payoff ratio, average win/loss, drawdown, concentration, and exposure when available
- `alternative_explanations`: possible non-signal explanations
- `attribution_confidence`: high, medium, low, inconclusive, or invalid
- `next_probe`: smallest follow-up that can confirm or reject the explanation

## Guardrails

- Do not say a model improved just because one headline KPI improved.
- Do not hide a worse drawdown, trade concentration, or sample shrink behind profit.
- Do not over-explain noise; mark low-confidence attribution when evidence is thin.
