"""Deterministic float32 linear-model ONNX boundary for V2."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
from onnx import TensorProto, helper, numpy_helper

from axiom_rift.v2.features import FEATURE_NAMES
from axiom_rift.v2.identity import sha256_payload


@dataclass(frozen=True)
class LinearModelBundle:
    mean: tuple[float, ...]
    scale: tuple[float, ...]
    coefficient: tuple[float, ...]
    intercept: float

    def validate(self) -> None:
        expected = len(FEATURE_NAMES)
        if not (len(self.mean) == len(self.scale) == len(self.coefficient) == expected):
            raise ValueError(f"linear bundle must contain {expected} values per vector")
        arrays = [np.asarray(self.mean), np.asarray(self.scale), np.asarray(self.coefficient)]
        if not all(np.isfinite(array).all() for array in arrays) or not np.isfinite(self.intercept):
            raise ValueError("linear bundle contains non-finite values")
        if np.any(np.asarray(self.scale) <= 0.0):
            raise ValueError("linear bundle scales must be positive")

    @property
    def content_sha256(self) -> str:
        self.validate()
        return sha256_payload(
            {
                "coefficient": list(self.coefficient),
                "intercept": self.intercept,
                "mean": list(self.mean),
                "scale": list(self.scale),
            }
        )


def python_scores(features: np.ndarray, bundle: LinearModelBundle) -> np.ndarray:
    bundle.validate()
    values = np.asarray(features, dtype=np.float32)
    if values.ndim != 2 or values.shape[1] != len(FEATURE_NAMES):
        raise ValueError("feature matrix shape differs from the linear bundle")
    mean = np.asarray(bundle.mean, dtype=np.float32)
    scale = np.asarray(bundle.scale, dtype=np.float32)
    coefficient = np.asarray(bundle.coefficient, dtype=np.float32)
    return (((values - mean) / scale) @ coefficient + np.float32(bundle.intercept)).astype(np.float32)


def export_linear_onnx(path: Path, bundle: LinearModelBundle) -> Path:
    bundle.validate()
    feature_count = len(FEATURE_NAMES)
    graph = helper.make_graph(
        [
            helper.make_node("Sub", ["features", "mean"], ["centered"]),
            helper.make_node("Div", ["centered", "scale"], ["normalized"]),
            helper.make_node("MatMul", ["normalized", "coefficient"], ["linear"]),
            helper.make_node("Add", ["linear", "intercept"], ["score"]),
        ],
        "axiom_rift_v2_linear_score",
        [helper.make_tensor_value_info("features", TensorProto.FLOAT, [None, feature_count])],
        [helper.make_tensor_value_info("score", TensorProto.FLOAT, [None, 1])],
        initializer=[
            numpy_helper.from_array(np.asarray(bundle.mean, dtype=np.float32).reshape(1, feature_count), "mean"),
            numpy_helper.from_array(np.asarray(bundle.scale, dtype=np.float32).reshape(1, feature_count), "scale"),
            numpy_helper.from_array(np.asarray(bundle.coefficient, dtype=np.float32).reshape(feature_count, 1), "coefficient"),
            numpy_helper.from_array(np.asarray([bundle.intercept], dtype=np.float32).reshape(1, 1), "intercept"),
        ],
    )
    model = helper.make_model(
        graph,
        producer_name="axiom_rift_v2",
        producer_version="1",
        opset_imports=[helper.make_opsetid("", 13)],
    )
    model.ir_version = 8
    onnx.checker.check_model(model)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(model.SerializeToString(deterministic=True))
    return path


def onnx_scores(path: Path, features: np.ndarray) -> np.ndarray:
    values = np.asarray(features, dtype=np.float32)
    session = ort.InferenceSession(path.read_bytes(), providers=["CPUExecutionProvider"])
    output = session.run(["score"], {"features": values})[0]
    return np.asarray(output, dtype=np.float32).reshape(-1)
