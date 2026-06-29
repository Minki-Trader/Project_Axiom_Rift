---
name: obsidian-model-validation
description: Validate project-wide model, threshold, calibration, split, WFO, overfit, and selection decisions before model or threshold results influence promotion, runtime, or next experiment choices.
---

# Obsidian Model Validation

Use this skill when work touches model training, model selection, threshold selection, ranking, calibration, feature importance, WFO, or any claim that one model is better than another.

## Required Output

- `model_family`: model type, training script, or runtime bundle
- `target_and_label`: what the model predicts and how the label is built
- `split_method`: holdout, WFO, cross-validation, runtime probe, or other split
- `selection_metric`: metric used to choose the model or threshold
- `secondary_metrics`: metrics that can reveal hidden failure
- `threshold_policy`: fixed, searched, calibrated, or runtime-configured
- `overfit_risk`: most likely overfitting or multiple-testing path
- `calibration_risk`: whether scores mean probability, rank, or only ordering
- `comparison_baseline`: previous model, no-trade baseline, random baseline, or manual rule
- `validation_judgment`: exploratory, candidate, inconclusive, invalid, blocked, or stronger project term allowed by policy

## Guardrails

- Do not promote a model because one threshold or one split looks good.
- Do not describe rank scores as probabilities unless calibration supports it.
- Do not let WFO absence kill exploration; downgrade the claim instead.
- Do not choose a threshold without naming what it optimizes and what it may harm.
