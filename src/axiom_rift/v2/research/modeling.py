"""Train-only scaling, deterministic Ridge fitting, and residual calibration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from axiom_rift.v2.research.samples import SupervisedSample
from axiom_rift.v2.research.specs import FeatureSpec, ModelSpec


@dataclass(frozen=True)
class ValidationBand:
    lower_residual: float
    upper_residual: float
    empirical_coverage: float
    sample_count: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "lower_residual": self.lower_residual,
            "upper_residual": self.upper_residual,
            "empirical_coverage": self.empirical_coverage,
            "sample_count": self.sample_count,
        }


@dataclass(frozen=True)
class FittedRidge:
    feature_names: tuple[str, ...]
    scaler_mean: tuple[float, ...]
    scaler_scale: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    alpha: float
    validation_band: ValidationBand

    def predict(self, values: tuple[float, ...]) -> float:
        if len(values) != len(self.feature_names):
            raise ValueError("feature vector length differs from the fitted feature order")
        standardized = tuple(
            (value - mean) / scale
            for value, mean, scale in zip(values, self.scaler_mean, self.scaler_scale, strict=True)
        )
        return float(
            self.intercept
            + sum(coefficient * value for coefficient, value in zip(self.coefficients, standardized, strict=True))
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "family": "ridge",
            "feature_names": list(self.feature_names),
            "scaler_mean": list(self.scaler_mean),
            "scaler_scale": list(self.scaler_scale),
            "coefficients": list(self.coefficients),
            "intercept": self.intercept,
            "alpha": self.alpha,
            "validation_band": self.validation_band.to_payload(),
        }


def _matrix(samples: tuple[SupervisedSample, ...]) -> tuple[np.ndarray, np.ndarray]:
    if not samples:
        raise ValueError("model fitting requires nonempty samples")
    return (
        np.asarray([sample.features for sample in samples], dtype=np.float64),
        np.asarray([sample.target for sample in samples], dtype=np.float64),
    )


def fit_ridge(
    train_samples: tuple[SupervisedSample, ...],
    validation_samples: tuple[SupervisedSample, ...],
    feature_spec: FeatureSpec,
    model_spec: ModelSpec,
) -> FittedRidge:
    """Fit scaler and Ridge on train only, then calibrate residuals on validation."""

    train_x, train_y = _matrix(train_samples)
    validation_x, validation_y = _matrix(validation_samples)
    if train_x.shape[1] != len(feature_spec.names) or validation_x.shape[1] != len(feature_spec.names):
        raise ValueError("sample feature width differs from the declarative feature order")

    scaler = StandardScaler()
    train_scaled = scaler.fit_transform(train_x)
    validation_scaled = scaler.transform(validation_x)
    ridge = Ridge(alpha=model_spec.alpha, solver="svd")
    ridge.fit(train_scaled, train_y)
    validation_predictions = ridge.predict(validation_scaled)
    residuals = validation_y - validation_predictions
    lower = float(np.quantile(residuals, model_spec.residual_alpha / 2.0))
    upper = float(np.quantile(residuals, 1.0 - model_spec.residual_alpha / 2.0))
    coverage = float(np.mean((residuals >= lower) & (residuals <= upper)))
    band = ValidationBand(lower, upper, coverage, len(validation_samples))
    return FittedRidge(
        feature_names=feature_spec.names,
        scaler_mean=tuple(float(value) for value in scaler.mean_),
        scaler_scale=tuple(float(value) for value in scaler.scale_),
        coefficients=tuple(float(value) for value in np.ravel(ridge.coef_)),
        intercept=float(ridge.intercept_),
        alpha=model_spec.alpha,
        validation_band=band,
    )
