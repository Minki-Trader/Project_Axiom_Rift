"""Small validation result types with no evidence-job dependencies."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "detail": self.detail}


@dataclass(frozen=True)
class ValidationResult:
    target: str
    issues: tuple[ValidationIssue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "axiom_rift_v2_validation_result_v1",
            "target": self.target,
            "ok": self.ok,
            "issue_count": len(self.issues),
            "issues": [issue.to_dict() for issue in self.issues],
        }
