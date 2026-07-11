"""Foundation-aware scientific trial and prior-warning accounting."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

import yaml

from axiom_rift.core.identity import canonical_digest


class TrialAccountingError(ValueError):
    """Raised when trial exposure cannot be accounted honestly."""


@dataclass(frozen=True, slots=True, kw_only=True)
class NegativeMemory:
    executable_identity: str
    scope: str
    evidence_references: tuple[str, ...]
    reason: str
    reopen_condition: str
    identity: str = field(init=False)

    def __post_init__(self) -> None:
        executable = _ascii("executable_identity", self.executable_identity)
        if not executable.startswith("executable:") or len(executable) != 75:
            raise TrialAccountingError("negative memory requires an Executable identity")
        _ascii("scope", self.scope)
        _ascii("reason", self.reason)
        _ascii("reopen_condition", self.reopen_condition)
        references = tuple(
            sorted(
                _ascii("evidence_reference", item)
                for item in self.evidence_references
            )
        )
        if not references or len(set(references)) != len(references):
            raise TrialAccountingError("negative memory evidence must be unique and non-empty")
        object.__setattr__(self, "evidence_references", references)
        memory_digest = canonical_digest(
            domain="negative-memory",
            payload={
                "evidence_references": list(references),
                "executable_identity": executable,
                "reason": self.reason,
                "reopen_condition": self.reopen_condition,
                "scope": self.scope,
            },
        )
        object.__setattr__(self, "identity", f"negative-memory:{memory_digest}")


def _ascii(name: str, value: object) -> str:
    if type(value) is not str:
        raise TypeError(f"{name} must be str")
    if not value:
        raise ValueError(f"{name} must not be empty")
    if not value.isascii():
        raise ValueError(f"{name} must be ASCII")
    return value


def _load_mapping(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise TrialAccountingError(f"foundation manifest not found: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise TrialAccountingError(f"cannot read foundation manifest: {path}") from exc
    if type(value) is not dict:
        raise TrialAccountingError(f"foundation manifest must be a mapping: {path}")
    return value


def _terms(value: object) -> frozenset[str]:
    result: set[str] = set()

    def visit(item: object) -> None:
        if type(item) is str:
            stripped = item.strip().casefold()
            if stripped:
                result.add(stripped)
            return
        if type(item) is list:
            for child in item:
                visit(child)
            return
        if type(item) is dict:
            for child in item.values():
                visit(child)

    visit(value)
    return frozenset(result)


def _requires_explicit_equivalence(rule: object) -> bool:
    if type(rule) is str:
        normalized = rule.casefold()
        return "explicit" in normalized and "equivalence" in normalized
    if type(rule) is dict:
        for key, value in rule.items():
            combined = f"{key} {value}".casefold()
            if (
                type(key) is str
                and "explicit" in combined
                and "equivalence" in combined
                and value is not False
            ):
                return True
            if _requires_explicit_equivalence(value):
                return True
    return False


@dataclass(frozen=True, slots=True, kw_only=True)
class MaterialReference:
    identity: str
    display_name: str = field(compare=False)

    def __post_init__(self) -> None:
        _ascii("identity", self.identity)
        _ascii("display_name", self.display_name)


@dataclass(frozen=True, slots=True, kw_only=True)
class SemanticWarning:
    warning_id: str
    semantic_key: str | None
    mechanism: str | None
    disposition: str | None
    reopen_condition: str | None
    search_terms: frozenset[str] = field(repr=False)
    scheduler_weight: str = "none"
    negative_evidence_eligible: bool = False

    def matches(self, proposal: object) -> bool:
        query = _terms(proposal)
        if not query:
            return True
        return bool(self.search_terms.intersection(query))


def _optional_ascii(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is str and value and value.isascii():
        return value
    if type(value) is list:
        rendered = "; ".join(str(item) for item in value)
        if rendered and rendered.isascii():
            return rendered
    return None


def _warning_from_mapping(
    value: object,
    *,
    index: int,
    scheduler_weight: str,
) -> SemanticWarning:
    if type(value) is not dict:
        raise TrialAccountingError("prior scientific warnings must be mappings")
    warning_id = value.get("warning_id", value.get("id", f"warning-{index + 1}"))
    _ascii("warning_id", warning_id)
    semantic_key = _optional_ascii(
        value.get(
            "semantic_key",
            value.get("semantic_identity", value.get("identity")),
        )
    )
    mechanism = _optional_ascii(value.get("mechanism"))
    disposition = _optional_ascii(value.get("disposition"))
    reopen = _optional_ascii(
        value.get("reopen_condition", value.get("reopen_conditions"))
    )
    return SemanticWarning(
        warning_id=warning_id,
        semantic_key=semantic_key,
        mechanism=mechanism,
        disposition=disposition,
        reopen_condition=reopen,
        search_terms=_terms(value),
        scheduler_weight=scheduler_weight,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class StudyTrialContext:
    material_identity: str
    prior_global_multiplicity: int
    semantic_warnings: tuple[SemanticWarning, ...]
    warning_scheduler_weight: str


@dataclass(frozen=True, slots=True, kw_only=True)
class TrialDecision:
    executable_identity: str
    trial_delta: int
    global_multiplicity: int
    disposition: str


class TrialAccountant:
    """Account against immutable Foundation exposure, not display labels."""

    def __init__(
        self,
        *,
        observed_material_identity: str,
        prior_global_multiplicity_floor: int,
        warnings: Iterable[SemanticWarning],
        scheduler_weight: str,
        reuse_rule: object,
    ) -> None:
        self._material_identity = _ascii(
            "observed_material_identity", observed_material_identity
        )
        if (
            type(prior_global_multiplicity_floor) is not int
            or prior_global_multiplicity_floor < 0
        ):
            raise TrialAccountingError(
                "prior_global_multiplicity_floor must be a non-negative int"
            )
        if scheduler_weight != "none":
            raise TrialAccountingError(
                "prior semantic warnings must have scheduler_weight none"
            )
        if not _requires_explicit_equivalence(reuse_rule):
            raise TrialAccountingError(
                "reuse_rule must require explicit identity equivalence"
            )
        self._prior_floor = prior_global_multiplicity_floor
        self._warnings = tuple(warnings)
        self._warnings_by_id = {warning.warning_id: warning for warning in self._warnings}
        if len(self._warnings_by_id) != len(self._warnings):
            raise TrialAccountingError("semantic warning ids must be unique")
        self._scheduler_weight = scheduler_weight
        self._seen: dict[str, str] = {}

    @classmethod
    def from_foundation(cls, root: str | Path) -> TrialAccountant:
        root_path = Path(root)
        foundation = root_path / "foundation"
        if not foundation.is_dir() and root_path.name == "foundation":
            foundation = root_path
        return cls.from_paths(
            data_exposure_path=foundation / "data_exposure.yaml",
            prior_memory_path=foundation / "prior_scientific_memory.yaml",
        )

    @classmethod
    def from_paths(
        cls,
        *,
        data_exposure_path: str | Path,
        prior_memory_path: str | Path,
    ) -> TrialAccountant:
        exposure = _load_mapping(Path(data_exposure_path))
        memory = _load_mapping(Path(prior_memory_path))

        observed = exposure.get("observed_development_material")
        if type(observed) is not dict:
            raise TrialAccountingError(
                "observed_development_material must be a mapping"
            )
        material_identity = observed.get("identity")
        identity_domain = observed.get("identity_domain")
        identity_inputs = observed.get("identity_inputs")
        prior_floor = observed.get("prior_global_multiplicity_floor")
        if (
            type(identity_domain) is not str
            or type(identity_inputs) is not dict
            or material_identity
            != canonical_digest(domain=identity_domain, payload=identity_inputs)
        ):
            raise TrialAccountingError(
                "observed development material identity does not match its inputs"
            )
        if isinstance(prior_floor, bool) or not isinstance(prior_floor, int) or prior_floor < 0:
            raise TrialAccountingError("prior global multiplicity floor is invalid")
        scheduler_weight = memory.get("scheduler_weight")
        reuse_rule = memory.get("reuse_rule")
        warning_values = memory.get("warnings")
        if type(warning_values) is not list:
            raise TrialAccountingError("prior scientific warnings must be a list")
        if type(scheduler_weight) is not str:
            raise TrialAccountingError("scheduler_weight must be a string")

        warnings = tuple(
            _warning_from_mapping(
                value,
                index=index,
                scheduler_weight=scheduler_weight,
            )
            for index, value in enumerate(warning_values)
        )
        return cls(
            observed_material_identity=material_identity,
            prior_global_multiplicity_floor=prior_floor,
            warnings=warnings,
            scheduler_weight=scheduler_weight,
            reuse_rule=reuse_rule,
        )

    @property
    def observed_material_identity(self) -> str:
        return self._material_identity

    @property
    def prior_global_multiplicity_floor(self) -> int:
        return self._prior_floor

    def prior_global_multiplicity(self, material: MaterialReference) -> int:
        # display_name is intentionally absent from this comparison.
        if material.identity == self._material_identity:
            return self._prior_floor
        return 0

    def lookup_semantic_warnings(
        self,
        proposal: object | None = None,
    ) -> tuple[SemanticWarning, ...]:
        if proposal is None:
            return self._warnings
        return tuple(
            warning for warning in self._warnings if warning.matches(proposal)
        )

    def open_study(
        self,
        *,
        material: MaterialReference,
        semantic_proposal: object | None = None,
    ) -> StudyTrialContext:
        if material.identity != self._material_identity:
            raise TrialAccountingError(
                "Study material is not the Foundation-registered development material"
            )
        return StudyTrialContext(
            material_identity=material.identity,
            prior_global_multiplicity=self.prior_global_multiplicity(material),
            semantic_warnings=self.lookup_semantic_warnings(semantic_proposal),
            warning_scheduler_weight=self._scheduler_weight,
        )

    def account_trial(
        self,
        *,
        material: MaterialReference,
        executable_identity: str,
        result: str,
        changed_information: bool = False,
    ) -> TrialDecision:
        """Count unique executable evaluations and reject identical failures."""

        _ascii("executable_identity", executable_identity)
        result = _ascii("result", result)
        previous = self._seen.get(executable_identity)
        prior = self.prior_global_multiplicity(material)
        if previous is None:
            self._seen[executable_identity] = result
            return TrialDecision(
                executable_identity=executable_identity,
                trial_delta=1,
                global_multiplicity=prior + len(self._seen),
                disposition="counted",
            )
        if previous == "success" and result == "success":
            return TrialDecision(
                executable_identity=executable_identity,
                trial_delta=0,
                global_multiplicity=prior + len(self._seen),
                disposition="successful_cache_reuse",
            )
        if not changed_information:
            raise TrialAccountingError(
                "identical evaluated executable cannot be retried without new information"
            )
        # A changed implementation or information state must have a new
        # executable identity. This branch therefore refuses identity reuse.
        raise TrialAccountingError(
            "changed information requires a new executable identity"
        )


__all__ = [
    "MaterialReference",
    "NegativeMemory",
    "SemanticWarning",
    "StudyTrialContext",
    "TrialAccountant",
    "TrialAccountingError",
    "TrialDecision",
]
