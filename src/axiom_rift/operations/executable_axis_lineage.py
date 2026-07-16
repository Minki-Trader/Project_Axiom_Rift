"""Exact Executable registration and completion-axis lineage.

An immutable Executable has one counted Trial registration.  The same exact
Executable may later be reused by a Job in another Study without fabricating a
second Trial.  Registration therefore proves identity and exposure, while the
Job declaration and its Study own the axis context of that completion.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from axiom_rift.core.identity import canonical_digest
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


class ExecutableAxisLineageError(RuntimeError):
    """Raised when an Executable-to-axis join is absent or ambiguous."""


def _ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise ExecutableAxisLineageError(f"{name} must be non-empty ASCII")
    return value


def _identity(name: str, value: object, prefix: str) -> str:
    text = _ascii(name, value)
    digest = text.removeprefix(prefix)
    if text == digest or len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise ExecutableAxisLineageError(f"{name} must use {prefix}<sha256>")
    return text


@dataclass(frozen=True, slots=True)
class RegisteredExecutableAxisLineage:
    """The one counted Trial registration context for an Executable."""

    executable_id: str
    mission_id: str
    study_id: str
    axis_id: str
    axis_identity: str


@dataclass(frozen=True, slots=True)
class DeclaredExecutableAxisLineage:
    """The Job-declared Study axis plus the immutable registration context."""

    executable_id: str
    mission_id: str
    study_id: str
    axis_id: str
    axis_identity: str
    registration: RegisteredExecutableAxisLineage


@dataclass(frozen=True, slots=True)
class HoldoutExecutableLineage:
    """A Study-less typed holdout completion and its registration anchor."""

    executable_id: str
    mission_id: str
    holdout_id: str
    registration: RegisteredExecutableAxisLineage


def registered_executable_axis_lineage(
    index: LocalIndex | LocalIndexView,
    executable_id: str,
) -> RegisteredExecutableAxisLineage:
    """Validate and return the unique counted registration axis."""

    typed_executable_id = _identity(
        "lineage Executable id", executable_id, "executable:"
    )
    trial = index.get("trial", typed_executable_id)
    if trial is None:
        raise ExecutableAxisLineageError(
            "Executable lacks its counted Trial registration"
        )
    payload = trial.payload
    executable = payload.get("executable")
    mission_id = _ascii("Trial Mission id", payload.get("mission_id"))
    study_id = _ascii("Trial Study id", payload.get("study_id"))
    axis_id = _ascii("Trial Portfolio axis id", payload.get("portfolio_axis_id"))
    axis_identity = _identity(
        "Trial Portfolio axis identity",
        payload.get("portfolio_axis_identity"),
        "axis:",
    )
    study = index.get("study-open", study_id)
    if (
        trial.kind != "trial"
        or trial.record_id != typed_executable_id
        or trial.status != "evaluated"
        or trial.fingerprint != typed_executable_id.removeprefix("executable:")
        or not isinstance(executable, Mapping)
        or typed_executable_id
        != "executable:"
        + canonical_digest(domain="executable", payload=dict(executable))
        or study is None
        or study.kind != "study-open"
        or study.record_id != study_id
        or study.status not in {"open", "closed"}
        or study.subject != f"Study:{study_id}"
        or study.payload.get("mission_id") != mission_id
        or study.payload.get("portfolio_axis_id") != axis_id
        or study.payload.get("portfolio_axis_identity") != axis_identity
    ):
        raise ExecutableAxisLineageError(
            "Executable Trial registration axis lineage is malformed or ambiguous"
        )
    return RegisteredExecutableAxisLineage(
        executable_id=typed_executable_id,
        mission_id=mission_id,
        study_id=study_id,
        axis_id=axis_id,
        axis_identity=axis_identity,
    )


def declared_executable_axis_lineage(
    index: LocalIndex | LocalIndexView,
    declaration: IndexRecord,
) -> DeclaredExecutableAxisLineage:
    """Resolve the axis owned by one exact Executable Job declaration."""

    job_id = _identity("Job declaration id", declaration.record_id, "job:")
    mission_id = _ascii(
        "Job declaration Mission id", declaration.payload.get("mission_id")
    )
    study_id = _ascii(
        "Job declaration Study id", declaration.payload.get("study_id")
    )
    spec = declaration.payload.get("spec")
    subject = None if not isinstance(spec, Mapping) else spec.get("evidence_subject")
    executable_id = (
        None
        if not isinstance(subject, Mapping) or subject.get("kind") != "Executable"
        else subject.get("id")
    )
    typed_executable_id = _identity(
        "Job declaration Executable id", executable_id, "executable:"
    )
    registration = registered_executable_axis_lineage(index, typed_executable_id)
    study = index.get("study-open", study_id)
    axis_id = _ascii(
        "declared Study Portfolio axis id",
        None if study is None else study.payload.get("portfolio_axis_id"),
    )
    axis_identity = _identity(
        "declared Study Portfolio axis identity",
        None if study is None else study.payload.get("portfolio_axis_identity"),
        "axis:",
    )
    if (
        declaration.kind != "job-declared"
        or declaration.status != "declared"
        or declaration.subject != f"Job:{job_id}"
        or subject != {"id": typed_executable_id, "kind": "Executable"}
        or study is None
        or study.kind != "study-open"
        or study.record_id != study_id
        or study.status not in {"open", "closed"}
        or study.subject != f"Study:{study_id}"
        or study.payload.get("mission_id") != mission_id
    ):
        raise ExecutableAxisLineageError(
            "Job declaration-to-Study-to-Executable axis lineage is malformed"
        )
    return DeclaredExecutableAxisLineage(
        executable_id=typed_executable_id,
        mission_id=mission_id,
        study_id=study_id,
        axis_id=axis_id,
        axis_identity=axis_identity,
        registration=registration,
    )


def completion_executable_axis_lineage(
    index: LocalIndex | LocalIndexView,
    completion: IndexRecord,
) -> DeclaredExecutableAxisLineage:
    """Resolve a completion through its exact Job declaration, not Trial Study."""

    job_id = _identity(
        "completion Job id", completion.payload.get("job_id"), "job:"
    )
    declaration = index.get("job-declared", job_id)
    if declaration is None:
        raise ExecutableAxisLineageError(
            "completion lacks its exact Job declaration"
        )
    lineage = declared_executable_axis_lineage(index, declaration)
    scientific = completion.payload.get("scientific")
    executable_id = (
        None
        if not isinstance(scientific, Mapping)
        else scientific.get("executable_id")
    )
    if (
        completion.kind != "job-completed"
        or completion.status not in {"success", "failed", "not_evaluable"}
        or completion.subject != f"Job:{job_id}"
        or declaration.record_id != job_id
        or executable_id != lineage.executable_id
    ):
        raise ExecutableAxisLineageError(
            "completion-to-Job-to-Executable axis lineage is malformed"
        )
    return lineage


def holdout_completion_executable_lineage(
    index: LocalIndex | LocalIndexView,
    completion: IndexRecord,
) -> HoldoutExecutableLineage:
    """Validate a Study-less completion through its exact holdout binding."""

    job_id = _identity(
        "holdout completion Job id",
        completion.payload.get("job_id"),
        "job:",
    )
    declaration = index.get("job-declared", job_id)
    if declaration is None:
        raise ExecutableAxisLineageError(
            "holdout completion lacks its exact Job declaration"
        )
    mission_id = _ascii(
        "holdout Job Mission id", declaration.payload.get("mission_id")
    )
    spec = declaration.payload.get("spec")
    subject = None if not isinstance(spec, Mapping) else spec.get("evidence_subject")
    holdout_binding = (
        None if not isinstance(spec, Mapping) else spec.get("holdout_binding")
    )
    executable_id = (
        None
        if not isinstance(subject, Mapping) or subject.get("kind") != "Executable"
        else subject.get("id")
    )
    typed_executable_id = _identity(
        "holdout Job Executable id", executable_id, "executable:"
    )
    holdout_id = _identity(
        "holdout id",
        None
        if not isinstance(holdout_binding, Mapping)
        else holdout_binding.get("holdout_id"),
        "holdout:",
    )
    registration = registered_executable_axis_lineage(index, typed_executable_id)
    scientific = completion.payload.get("scientific")
    if (
        declaration.kind != "job-declared"
        or declaration.record_id != job_id
        or declaration.status != "declared"
        or declaration.subject != f"Job:{job_id}"
        or declaration.payload.get("study_id") is not None
        or subject != {"id": typed_executable_id, "kind": "Executable"}
        or holdout_binding != {"holdout_id": holdout_id}
        or completion.kind != "job-completed"
        or completion.status not in {"success", "failed", "not_evaluable"}
        or completion.subject != f"Job:{job_id}"
        or not isinstance(scientific, Mapping)
        or scientific.get("executable_id") != typed_executable_id
    ):
        raise ExecutableAxisLineageError(
            "Study-less holdout completion lineage is malformed"
        )
    return HoldoutExecutableLineage(
        executable_id=typed_executable_id,
        mission_id=mission_id,
        holdout_id=holdout_id,
        registration=registration,
    )


__all__ = [
    "DeclaredExecutableAxisLineage",
    "ExecutableAxisLineageError",
    "HoldoutExecutableLineage",
    "RegisteredExecutableAxisLineage",
    "completion_executable_axis_lineage",
    "declared_executable_axis_lineage",
    "holdout_completion_executable_lineage",
    "registered_executable_axis_lineage",
]
