"""Build the exact AX-SPREAD-TIME-001 completion invalidation inventory.

This module is deliberately read-only.  The audit document supplies the exact
completion inventory and atomic-trace identities, while the authenticated
index supplies the immutable completion -> Job declaration -> Trial binding.
Content-addressed evidence supplies the scientific artifacts and the eight
atomic evaluation traces.  No caller-authored semantic fields are accepted.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any

from axiom_rift.core.canonical import canonical_bytes, parse_canonical
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.completion_validity_projection import (
    CompletionValidityProjectionError,
    validate_completion_validity_invalidation_binding,
)
from axiom_rift.research.historical_scientific_validity import (
    DecisionPredicateActivationState,
    HistoricalScientificValidityError,
    HistoricalScientificValidityInvalidation,
    JobBindingKind,
)
from axiom_rift.storage.evidence import EvidenceStore
from axiom_rift.storage.index import IndexRecord, LocalIndex, LocalIndexView


AUDIT_FINDING_ID = "AX-SPREAD-TIME-001"
AUDIT_TRACE_FINDING_ID = "AX-SPREAD-TIME-002"
EXPECTED_COMPLETION_COUNT = 34
AUDIT_SLICE_DIGEST_INVENTORY_SCHEMA = (
    "historical_spread_time_audit_slice_digest_inventory.v1"
)

EXPECTED_STUDY_CONTEXTS = (
    "STU-0046",
    "STU-0047",
    "STU-0048",
    "STU-0049",
    "STU-0050",
    "STU-0051",
    "STU-0070",
    "STU-0071",
    "STU-0101",
    "STU-0107",
    "STU-0108",
)

EXPECTED_ATOMIC_ACTIVATION_COUNTS = {
    "executable:c8b62dac5ef859ee2db6e6adbdcc758384867811174e5be3a765da904db4dcaf": 2,
    "executable:51193460ecf100b1c0053ebf87acc5197928d01e7c28385d3d39770cbe6977bc": 2,
    "executable:93c03f0a5d8545cafc53fbfcbcb7791ac0ac27175b2a05e26947281f09fe81d1": 0,
    "executable:0fc036a7825f29ca2aca8129855c4315e4b81cfa894330afe2d899b2c3b42762": 0,
    "executable:d8f54d95a5a630377d9a82f7c2801d362008304d1e3096e1fb3117966799d905": 2,
    "executable:eabf4c41722ac77fadccff0b669be9e9226cd250fd911878c8d594b7acbc7990": 2,
    "executable:3a90958f5e1dca92bf61f7ed5abd0375ce1c15c8cab161512ffb480b37f0f915": 0,
    "executable:8392b61ce0b248381ac51be7975cacb75d7d74467b0903393656cbc2491f88e4": 0,
}

_ATOMIC_STUDIES = frozenset({"STU-0107", "STU-0108"})
_EXACT_TRANSITIONS = frozenset({(415914, 415915), (415915, 415916)})
_DIGEST_PATTERN = r"[0-9a-f]{64}"
_ROW_PATTERN = re.compile(
    rf"  (STU-[0-9]{{4}}) (executable:{_DIGEST_PATTERN}) "
    rf"completion ({_DIGEST_PATTERN})"
)
_TRACE_PATTERN = re.compile(
    rf"  (STU-010[78]) atomic traces ((?:{_DIGEST_PATTERN})(?: {_DIGEST_PATTERN}){{3}})"
)

_BAR_CLOCK = "clock:fpmarkets_m5_bar_open_completed_plus_5m_v2"
_SEGMENT_COST = (
    "cost:bid_bar_segment_positive_median_min_1_unknown_entry_cancel_"
    "half_spread_stress_v1"
)
_GAP_SEGMENT_COST = (
    "cost:bid_bar_gap_segment_positive_median_min_1_unknown_entry_cancel_"
    "half_spread_stress_v1"
)
_EXPECTED_CONTRACTS_BY_JOB_STUDY = {
    "STU-0046": (_BAR_CLOCK, _GAP_SEGMENT_COST),
    "STU-0047": (_BAR_CLOCK, _GAP_SEGMENT_COST),
    "STU-0048": (_BAR_CLOCK, _SEGMENT_COST),
    "STU-0049": (_BAR_CLOCK, _SEGMENT_COST),
    "STU-0050": (_BAR_CLOCK, _SEGMENT_COST),
    "STU-0051": (_BAR_CLOCK, _SEGMENT_COST),
    "STU-0071": (
        "clock:fpmarkets_m5_entry_quote_observed_before_order_v1",
        "cost:bid_bar_spread_point_0_01_causal_zero_repair_entry_quote_gate_"
        "half_spread_stress_v1",
    ),
    "STU-0101": (
        "clock:fpmarkets_m5_causal_one_bar_quote_deferral_v1",
        "cost:bid_bar_spread_point_0_01_causal_zero_repair_one_bar_quote_"
        "deferral_half_spread_stress_v1",
    ),
    "STU-0107": (_BAR_CLOCK, _SEGMENT_COST),
    "STU-0108": (_BAR_CLOCK, _SEGMENT_COST),
}


class HistoricalSpreadTimeInvalidationBuilderError(RuntimeError):
    """The frozen audit inventory cannot be rebuilt from exact authority."""


@dataclass(frozen=True, slots=True)
class AuditSliceDigestInventoryEntry:
    """One stable completion -> semantic audit-slice digest binding."""

    completion_record_id: str
    audit_slice_digest: str

    def to_payload(self) -> dict[str, str]:
        return {
            "audit_slice_digest": self.audit_slice_digest,
            "completion_record_id": self.completion_record_id,
        }


@dataclass(frozen=True, slots=True)
class HistoricalSpreadTimeInvalidationInventory:
    """The exact typed invalidations plus their canonical digest inventory."""

    audit_artifact_hash: str
    study_contexts: tuple[str, ...]
    invalidations: tuple[HistoricalScientificValidityInvalidation, ...]

    def __post_init__(self) -> None:
        if (
            self.study_contexts != EXPECTED_STUDY_CONTEXTS
            or len(self.invalidations) != EXPECTED_COMPLETION_COUNT
            or len(
                {item.completion_record_id for item in self.invalidations}
            )
            != EXPECTED_COMPLETION_COUNT
            or len({item.identity for item in self.invalidations})
            != EXPECTED_COMPLETION_COUNT
            or any(
                item.audit_artifact_hash != self.audit_artifact_hash
                or item.audit_finding_id != AUDIT_FINDING_ID
                for item in self.invalidations
            )
        ):
            raise HistoricalSpreadTimeInvalidationBuilderError(
                "historical spread-time invalidation inventory is not exact"
            )

    @property
    def audit_slice_digest_inventory(
        self,
    ) -> tuple[AuditSliceDigestInventoryEntry, ...]:
        entries: list[AuditSliceDigestInventoryEntry] = []
        for item in sorted(
            self.invalidations,
            key=lambda candidate: candidate.completion_record_id,
        ):
            digest = item.audit_slice_digest
            if type(digest) is not str:
                raise HistoricalSpreadTimeInvalidationBuilderError(
                    "historical spread-time audit slice digest is absent"
                )
            entries.append(
                AuditSliceDigestInventoryEntry(
                    completion_record_id=item.completion_record_id,
                    audit_slice_digest=digest,
                )
            )
        return tuple(entries)

    def to_audit_slice_digest_inventory_payload(self) -> dict[str, Any]:
        return {
            "audit_artifact_hash": self.audit_artifact_hash,
            "audit_finding_id": AUDIT_FINDING_ID,
            "completion_count": EXPECTED_COMPLETION_COUNT,
            "entries": [
                item.to_payload() for item in self.audit_slice_digest_inventory
            ],
            "schema": AUDIT_SLICE_DIGEST_INVENTORY_SCHEMA,
            "study_contexts": list(self.study_contexts),
        }

    @property
    def audit_slice_digest_inventory_digest(self) -> str:
        return canonical_digest(
            domain="historical-spread-time-audit-slice-digest-inventory",
            payload=self.to_audit_slice_digest_inventory_payload(),
        )


@dataclass(frozen=True, slots=True)
class _AuditRow:
    study_id: str
    executable_id: str
    completion_record_id: str
    trace_hash: str | None = None


@dataclass(frozen=True, slots=True)
class _AuditInventory:
    rows: tuple[_AuditRow, ...]
    study_contexts: tuple[str, ...]


def _builder_error(message: str) -> HistoricalSpreadTimeInvalidationBuilderError:
    return HistoricalSpreadTimeInvalidationBuilderError(message)


def _require_digest(name: str, value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise _builder_error(f"{name} must be a lowercase SHA-256 digest")
    return value


def _require_ascii(name: str, value: object) -> str:
    if type(value) is not str or not value or not value.isascii():
        raise _builder_error(f"{name} must be non-empty ASCII")
    return value


def _require_string_set(
    name: str,
    value: object,
    *,
    allow_mappings: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise _builder_error(f"{name} must be a non-empty list")
    resolved: list[str] = []
    for item in value:
        if allow_mappings and isinstance(item, Mapping):
            item = item.get("claim_id")
        resolved.append(_require_ascii(name, item))
    if len(resolved) != len(set(resolved)):
        raise _builder_error(f"{name} must be unique")
    return tuple(sorted(resolved))


def _finding(lines: list[str], finding_id: str) -> list[str]:
    heading = f"- {finding_id}:"
    starts = [position for position, line in enumerate(lines) if line == heading]
    if len(starts) != 1:
        raise _builder_error(f"audit finding {finding_id} is not unique")
    start = starts[0]
    end = len(lines)
    for position in range(start + 1, len(lines)):
        line = lines[position]
        if line.startswith("- AX-") and line.endswith(":"):
            end = position
            break
    return lines[start:end]


def _single_prefixed(finding: list[str], prefix: str) -> str:
    matches = [line.removeprefix(prefix) for line in finding if line.startswith(prefix)]
    if len(matches) != 1 or not matches[0]:
        raise _builder_error(f"audit line {prefix!r} is not unique")
    return matches[0]


def _parse_audit_document(document: bytes) -> _AuditInventory:
    try:
        lines = document.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise _builder_error("historical spread-time audit must be ASCII") from exc

    timing = _finding(lines, AUDIT_FINDING_ID)
    if _single_prefixed(timing, "  reason ") != (
        "decision_input_point_in_time_unproven"
    ):
        raise _builder_error("historical spread-time audit reason changed")
    if _single_prefixed(timing, "  field ") != "MqlRates.spread":
        raise _builder_error("historical spread-time audit field changed")
    if _single_prefixed(timing, "  prohibited use ") != (
        "same_scheduled_or_deferred_entry_bar_order_decision"
    ):
        raise _builder_error("historical spread-time prohibited use changed")
    count_text = _single_prefixed(
        timing,
        "  affected scientific completion count ",
    )
    if count_text != str(EXPECTED_COMPLETION_COUNT):
        raise _builder_error("historical spread-time completion count changed")

    context_text = _single_prefixed(timing, "  affected Study contexts ")
    contexts = tuple(sorted(context_text.split(" ")))
    if contexts != EXPECTED_STUDY_CONTEXTS:
        raise _builder_error("historical spread-time Study contexts changed")

    rows: list[_AuditRow] = []
    candidate_lines = [line for line in timing if line.startswith("  STU-")]
    for line in candidate_lines:
        match = _ROW_PATTERN.fullmatch(line)
        if match is None:
            raise _builder_error("historical spread-time completion row is malformed")
        rows.append(_AuditRow(*match.groups()))
    if (
        len(rows) != EXPECTED_COMPLETION_COUNT
        or len({row.completion_record_id for row in rows})
        != EXPECTED_COMPLETION_COUNT
        or len({row.executable_id for row in rows})
        != EXPECTED_COMPLETION_COUNT
        or any(row.study_id == "STU-0070" for row in rows)
    ):
        raise _builder_error(
            "historical spread-time rows are not 34 unique scientific completions"
        )

    trace_finding = _finding(lines, AUDIT_TRACE_FINDING_ID)
    required_trace_lines = {
        "  exact source index transitions 415914_to_415915 and 415915_to_415916",
        "  observed branch entry_cancelled_unknown_cost",
        "  each stored family trace contains 8 full_or_prefix rows "
        "representing 4 distinct events",
    }
    if any(trace_finding.count(line) != 1 for line in required_trace_lines):
        raise _builder_error("historical spread-time atomic trace semantics changed")

    trace_lines = [line for line in trace_finding if " atomic traces " in line]
    traces_by_study: dict[str, tuple[str, ...]] = {}
    for line in trace_lines:
        match = _TRACE_PATTERN.fullmatch(line)
        if match is None:
            raise _builder_error("historical spread-time atomic trace row is malformed")
        study_id, hashes_text = match.groups()
        if study_id in traces_by_study:
            raise _builder_error("historical spread-time atomic trace Study repeats")
        traces_by_study[study_id] = tuple(hashes_text.split(" "))
    if set(traces_by_study) != set(_ATOMIC_STUDIES) or len(
        {digest for hashes in traces_by_study.values() for digest in hashes}
    ) != 8:
        raise _builder_error("historical spread-time atomic trace inventory changed")

    bound_rows: list[_AuditRow] = []
    atomic_offsets = {study_id: 0 for study_id in _ATOMIC_STUDIES}
    for row in rows:
        if row.study_id not in _ATOMIC_STUDIES:
            bound_rows.append(row)
            continue
        offset = atomic_offsets[row.study_id]
        hashes = traces_by_study[row.study_id]
        if offset >= len(hashes):
            raise _builder_error("historical spread-time atomic trace count changed")
        bound_rows.append(
            _AuditRow(
                study_id=row.study_id,
                executable_id=row.executable_id,
                completion_record_id=row.completion_record_id,
                trace_hash=hashes[offset],
            )
        )
        atomic_offsets[row.study_id] = offset + 1
    if any(offset != 4 for offset in atomic_offsets.values()):
        raise _builder_error("historical spread-time atomic row count changed")
    return _AuditInventory(rows=tuple(bound_rows), study_contexts=contexts)


def _read_mapping(
    evidence: EvidenceStore,
    artifact_hash: str,
    *,
    label: str,
) -> Mapping[str, Any]:
    try:
        value = parse_canonical(evidence.read_verified(artifact_hash))
    except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise _builder_error(f"{label} is unavailable or non-canonical") from exc
    if not isinstance(value, Mapping):
        raise _builder_error(f"{label} must be a canonical mapping")
    return value


def _criterion_scope(
    source: Mapping[str, Any],
    *,
    label: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    criteria = source.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        raise _builder_error(f"{label} criteria are absent")
    criterion_ids: list[str] = []
    claim_ids: list[str] = []
    for criterion in criteria:
        if not isinstance(criterion, Mapping):
            raise _builder_error(f"{label} criterion is malformed")
        criterion_ids.append(
            _require_ascii(f"{label} criterion id", criterion.get("criterion_id"))
        )
        claim_ids.append(
            _require_ascii(f"{label} criterion claim", criterion.get("claim_id"))
        )
    if len(criterion_ids) != len(set(criterion_ids)):
        raise _builder_error(f"{label} criterion ids repeat")
    return tuple(sorted(criterion_ids)), tuple(sorted(set(claim_ids)))


def _component_implementation_hashes(trial: IndexRecord) -> tuple[str, ...]:
    executable = trial.payload.get("executable")
    manifests = (
        executable.get("component_manifests")
        if isinstance(executable, Mapping)
        else None
    )
    if not isinstance(manifests, list) or not manifests:
        raise _builder_error("historical spread-time Trial lacks component manifests")
    resolved: set[str] = set()
    for manifest in manifests:
        implementation = (
            manifest.get("implementation") if isinstance(manifest, Mapping) else None
        )
        if (
            type(implementation) is not str
            or not implementation.isascii()
            or "@sha256:" not in implementation
        ):
            raise _builder_error(
                "historical spread-time component implementation is malformed"
            )
        resolved.add(
            _require_digest(
                "historical spread-time component implementation",
                implementation.rsplit("@sha256:", 1)[1],
            )
        )
    return tuple(sorted(resolved))


def _require_completion_artifacts(
    evidence: EvidenceStore,
    *,
    completion: IndexRecord,
    declaration: IndexRecord,
    executable_id: str,
    validation_plan_hash: str,
    measurement_artifact_hash: str,
    result_manifest_hash: str,
    claims: tuple[str, ...],
    modes: tuple[str, ...],
    atomic: bool,
) -> tuple[str, ...]:
    mission_id = _require_ascii(
        "historical spread-time declaration mission",
        declaration.payload.get("mission_id"),
    )
    job_id = declaration.record_id
    plan = _read_mapping(
        evidence,
        validation_plan_hash,
        label="historical spread-time validation plan",
    )
    expected_plan_schema = (
        "scientific_validation_plan.v2" if atomic else "scientific_validation_plan.v1"
    )
    planned_claims = _require_string_set(
        "historical spread-time planned claims",
        plan.get("planned_claims"),
    )
    planned_modes = _require_string_set(
        "historical spread-time planned modes",
        plan.get("evidence_modes"),
    )
    criterion_ids, criterion_claim_ids = _criterion_scope(
        plan,
        label="historical spread-time validation plan",
    )
    if (
        plan.get("schema") != expected_plan_schema
        or plan.get("mission_id") != mission_id
        or plan.get("executable_id") != executable_id
        or planned_claims != claims
        or planned_modes != modes
        or criterion_claim_ids != claims
    ):
        raise _builder_error(
            "historical spread-time validation plan binding is not exact"
        )

    measurement = _read_mapping(
        evidence,
        measurement_artifact_hash,
        label="historical spread-time measurement",
    )
    expected_measurement_schema = (
        "scientific_measurement.v2" if atomic else "scientific_measurement.v1"
    )
    measured_modes = _require_string_set(
        "historical spread-time measured modes",
        measurement.get("evidence_modes"),
    )
    if (
        measurement.get("schema") != expected_measurement_schema
        or measurement.get("mission_id") != mission_id
        or measurement.get("job_id") != job_id
        or measurement.get("job_hash") != job_id.removeprefix("job:")
        or measurement.get("executable_id") != executable_id
        or measured_modes != modes
    ):
        raise _builder_error(
            "historical spread-time measurement binding is not exact"
        )
    if not atomic and _require_string_set(
        "historical spread-time measured claims",
        measurement.get("claims"),
    ) != claims:
        raise _builder_error("historical spread-time measured claims changed")

    result = _read_mapping(
        evidence,
        result_manifest_hash,
        label="historical spread-time result manifest",
    )
    observations = result.get("observations")
    if not isinstance(observations, list) or not observations:
        raise _builder_error("historical spread-time result observations are absent")
    result_claims: list[str] = []
    for observation in observations:
        if (
            not isinstance(observation, Mapping)
            or observation.get("measurement_artifact_hash")
            != measurement_artifact_hash
        ):
            raise _builder_error(
                "historical spread-time result observation binding is not exact"
            )
        result_claims.append(
            _require_ascii(
                "historical spread-time result claim",
                observation.get("claim_id"),
            )
        )
    if (
        result.get("schema") != "scientific_job_evidence.v1"
        or result.get("mission_id") != mission_id
        or result.get("job_id") != job_id
        or result.get("job_hash") != job_id.removeprefix("job:")
        or result.get("executable_id") != executable_id
        or tuple(sorted(result_claims)) != claims
        or len(result_claims) != len(set(result_claims))
    ):
        raise _builder_error(
            "historical spread-time result manifest binding is not exact"
        )

    outputs = completion.payload.get("outputs")
    if (
        not isinstance(outputs, Mapping)
        or not {
            validation_plan_hash,
            measurement_artifact_hash,
            result_manifest_hash,
        }.issubset(set(outputs.values()))
    ):
        raise _builder_error(
            "historical spread-time completion artifact outputs are not exact"
        )
    return criterion_ids


def _adjudication_scope(
    adjudication: Mapping[str, Any],
    *,
    label: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    claims = _require_string_set(
        f"{label} claims",
        adjudication.get("claims"),
        allow_mappings=True,
    )
    criteria, criterion_claims = _criterion_scope(adjudication, label=label)
    if criterion_claims != claims:
        raise _builder_error(f"{label} claim-to-criterion scope is not exact")
    return claims, criteria


def _require_adjudication_scope(
    index: LocalIndex | LocalIndexView,
    *,
    completion: IndexRecord,
    scientific: Mapping[str, Any],
    study_id: str,
    study_close_record_id: str,
    executable_id: str,
    validation_plan_hash: str,
    measurement_artifact_hash: str,
    claims: tuple[str, ...],
    criterion_ids: tuple[str, ...],
    atomic: bool,
) -> None:
    if atomic:
        adjudication = scientific.get("adjudication")
        if not isinstance(adjudication, Mapping):
            raise _builder_error(
                "historical spread-time atomic completion lacks adjudication"
            )
        adjudicated_claims, adjudicated_criteria = _adjudication_scope(
            adjudication,
            label="historical spread-time atomic adjudication",
        )
    else:
        if scientific.get("adjudication") is not None:
            raise _builder_error(
                "historical spread-time legacy completion changed evidence generation"
            )
        stream = f"historical-adjudication:{completion.record_id}"
        head = index.event_head(stream)
        record = (
            None
            if head is None
            else index.get(head.record_kind, head.record_id)
        )
        payload = None if record is None else record.payload
        adjudication = (
            payload.get("adjudication") if isinstance(payload, Mapping) else None
        )
        if (
            record is None
            or record.kind != "historical-scientific-adjudication"
            or record.event_stream != stream
            or not isinstance(payload, Mapping)
            or payload.get("completion_record_id") != completion.record_id
            or payload.get("study_id") != study_id
            or payload.get("study_close_record_id") != study_close_record_id
            or payload.get("executable_id") != executable_id
            or payload.get("validation_plan_hash") != validation_plan_hash
            or payload.get("measurement_artifact_hash")
            != measurement_artifact_hash
            or not isinstance(adjudication, Mapping)
        ):
            raise _builder_error(
                "historical spread-time legacy adjudication binding is not exact"
            )
        adjudicated_claims, adjudicated_criteria = _adjudication_scope(
            adjudication,
            label="historical spread-time legacy adjudication",
        )
    if adjudicated_claims != claims or adjudicated_criteria != criterion_ids:
        raise _builder_error(
            "historical spread-time adjudication scope differs from preregistration"
        )


def _distinct_atomic_activations(
    evidence: EvidenceStore,
    *,
    trace_hash: str,
    executable_id: str,
    job_id: str,
    mission_id: str,
) -> int:
    trace = _read_mapping(
        evidence,
        trace_hash,
        label="historical spread-time atomic evaluation trace",
    )
    observations = trace.get("intent_observations")
    if (
        trace.get("schema") != "scientific_evaluation_trace.v1"
        or trace.get("subject_executable_id") != executable_id
        or trace.get("job_id") != job_id
        or trace.get("job_hash") != job_id.removeprefix("job:")
        or trace.get("mission_id") != mission_id
        or not isinstance(observations, list)
    ):
        raise _builder_error(
            "historical spread-time atomic evaluation trace binding is not exact"
        )

    branch_rows: list[Mapping[str, Any]] = []
    for observation in observations:
        if not isinstance(observation, Mapping):
            raise _builder_error(
                "historical spread-time atomic intent observation is malformed"
            )
        if observation.get("status") == "entry_cancelled_unknown_cost":
            branch_rows.append(observation)
    if len(branch_rows) != 8:
        raise _builder_error(
            "historical spread-time atomic trace must contain eight branch rows"
        )

    grouped: dict[bytes, list[Mapping[str, Any]]] = defaultdict(list)
    for row in branch_rows:
        scope = row.get("scope")
        observation_id = row.get("observation_id")
        row_executable_id = row.get("executable_id")
        decision_index = row.get("decision_bar_index")
        entry_index = row.get("entry_bar_index")
        if (
            scope not in {"full", "prefix"}
            or type(observation_id) is not str
            or not observation_id.startswith("observation:")
            or type(row_executable_id) is not str
            or not row_executable_id.startswith("executable:")
            or type(decision_index) is not int
            or type(entry_index) is not int
        ):
            raise _builder_error(
                "historical spread-time atomic branch row is malformed"
            )
        semantic = {
            key: value
            for key, value in row.items()
            if key not in {"observation_id", "scope"}
        }
        grouped[canonical_bytes(semantic)].append(row)

    if len(grouped) != 4:
        raise _builder_error(
            "historical spread-time atomic trace must contain four distinct events"
        )
    transitions: set[tuple[int, int]] = set()
    events_by_executable: Counter[str] = Counter()
    for duplicates in grouped.values():
        if Counter(item.get("scope") for item in duplicates) != Counter(
            {"full": 1, "prefix": 1}
        ):
            raise _builder_error(
                "historical spread-time atomic full/prefix duplicate is not exact"
            )
        representative = duplicates[0]
        decision_index = representative["decision_bar_index"]
        entry_index = representative["entry_bar_index"]
        row_executable_id = representative["executable_id"]
        transitions.add((decision_index, entry_index))
        events_by_executable[row_executable_id] += 1
    if (
        transitions != set(_EXACT_TRANSITIONS)
        or sorted(events_by_executable.values()) != [2, 2]
    ):
        raise _builder_error(
            "historical spread-time atomic source-index transitions changed"
        )

    activation_count = events_by_executable.get(executable_id, 0)
    expected = EXPECTED_ATOMIC_ACTIVATION_COUNTS.get(executable_id)
    if expected is None or activation_count != expected:
        raise _builder_error(
            "historical spread-time atomic predicate activation count changed"
        )
    return activation_count


def _build_one(
    index: LocalIndex | LocalIndexView,
    evidence: EvidenceStore,
    *,
    row: _AuditRow,
    audit_artifact_hash: str,
    study_close_record_id: str,
) -> tuple[HistoricalScientificValidityInvalidation, str]:
    completion = index.get("job-completed", row.completion_record_id)
    scientific = None if completion is None else completion.payload.get("scientific")
    if (
        completion is None
        or completion.record_id != row.completion_record_id
        or not isinstance(scientific, Mapping)
        or scientific.get("scientific_eligible") is not True
        or scientific.get("executable_id") != row.executable_id
    ):
        raise _builder_error(
            "historical spread-time audit row is not an exact scientific completion"
        )
    job_id = _require_ascii(
        "historical spread-time completion Job",
        completion.payload.get("job_id"),
    )
    declaration = index.get("job-declared", job_id)
    spec = None if declaration is None else declaration.payload.get("spec")
    evidence_subject = (
        spec.get("evidence_subject") if isinstance(spec, Mapping) else None
    )
    if (
        declaration is None
        or declaration.record_id != job_id
        or declaration.payload.get("study_id") != row.study_id
        or evidence_subject
        != {"id": row.executable_id, "kind": "Executable"}
    ):
        raise _builder_error(
            "historical spread-time completion-to-Job declaration join is not exact"
        )
    mission_id = _require_ascii(
        "historical spread-time declaration mission",
        declaration.payload.get("mission_id"),
    )

    trial = index.get("trial", row.executable_id)
    executable = None if trial is None else trial.payload.get("executable")
    trial_study_id = None if trial is None else trial.payload.get("study_id")
    if (
        trial is None
        or trial.record_id != row.executable_id
        or trial.status != "evaluated"
        or trial.payload.get("mission_id") != mission_id
        or trial.payload.get("scientific_eligible") is not True
        or trial.payload.get("engineering_fixture") is not False
        or not isinstance(executable, Mapping)
        or type(trial_study_id) is not str
    ):
        raise _builder_error(
            "historical spread-time Job declaration-to-Trial join is not exact"
        )

    expected_contracts = _EXPECTED_CONTRACTS_BY_JOB_STUDY.get(row.study_id)
    clock_contract = executable.get("clock_contract")
    cost_contract = executable.get("cost_contract")
    if expected_contracts is None or (
        clock_contract,
        cost_contract,
    ) != expected_contracts:
        raise _builder_error(
            "historical spread-time clock-cost contract pair changed"
        )
    assert isinstance(clock_contract, str)
    assert isinstance(cost_contract, str)

    validation_plan_hash = _require_digest(
        "historical spread-time validation plan hash",
        scientific.get("validation_plan_hash"),
    )
    result_manifest_hash = _require_digest(
        "historical spread-time result manifest hash",
        scientific.get("result_manifest_hash"),
    )
    measurements = scientific.get("measurement_artifact_hashes")
    if not isinstance(measurements, list) or len(measurements) != 1:
        raise _builder_error(
            "historical spread-time completion must bind one measurement"
        )
    measurement_artifact_hash = _require_digest(
        "historical spread-time measurement artifact hash",
        measurements[0],
    )
    claims = _require_string_set(
        "historical spread-time completion claims",
        scientific.get("claims"),
        allow_mappings=True,
    )
    modes = _require_string_set(
        "historical spread-time completion evidence modes",
        scientific.get("executed_evidence_modes"),
    )
    atomic = row.study_id in _ATOMIC_STUDIES
    criterion_ids = _require_completion_artifacts(
        evidence,
        completion=completion,
        declaration=declaration,
        executable_id=row.executable_id,
        validation_plan_hash=validation_plan_hash,
        measurement_artifact_hash=measurement_artifact_hash,
        result_manifest_hash=result_manifest_hash,
        claims=claims,
        modes=modes,
        atomic=atomic,
    )
    _require_adjudication_scope(
        index,
        completion=completion,
        scientific=scientific,
        study_id=row.study_id,
        study_close_record_id=study_close_record_id,
        executable_id=row.executable_id,
        validation_plan_hash=validation_plan_hash,
        measurement_artifact_hash=measurement_artifact_hash,
        claims=claims,
        criterion_ids=criterion_ids,
        atomic=atomic,
    )

    if atomic:
        trace_hash = _require_digest(
            "historical spread-time atomic trace hash",
            row.trace_hash,
        )
        outputs = completion.payload.get("outputs")
        trace_outputs = (
            [
                value
                for path, value in outputs.items()
                if type(path) is str and path.endswith("/evaluation-trace.json")
            ]
            if isinstance(outputs, Mapping)
            else []
        )
        if trace_outputs != [trace_hash]:
            raise _builder_error(
                "historical spread-time atomic trace output binding is not exact"
            )
        activation_count = _distinct_atomic_activations(
            evidence,
            trace_hash=trace_hash,
            executable_id=row.executable_id,
            job_id=job_id,
            mission_id=mission_id,
        )
        activation_state = (
            DecisionPredicateActivationState.ACTIVATED
            if activation_count > 0
            else DecisionPredicateActivationState.EVALUATED_NOT_ACTIVATED
        )
    else:
        if row.trace_hash is not None:
            raise _builder_error(
                "historical spread-time legacy completion gained an atomic trace"
            )
        activation_count = None
        activation_state = (
            DecisionPredicateActivationState.LEGACY_AGGREGATE_NOT_SERIALIZED
        )

    try:
        invalidation = HistoricalScientificValidityInvalidation(
            study_id=row.study_id,
            study_close_record_id=study_close_record_id,
            job_id=job_id,
            job_binding_kind=JobBindingKind.DECLARATION,
            job_binding_record_id=job_id,
            completion_record_id=row.completion_record_id,
            executable_id=row.executable_id,
            validation_plan_hash=validation_plan_hash,
            measurement_artifact_hash=measurement_artifact_hash,
            result_manifest_hash=result_manifest_hash,
            component_implementation_hashes=(
                _component_implementation_hashes(trial)
            ),
            clock_contract=clock_contract,
            cost_contract=cost_contract,
            predicate_evaluated=True,
            activation_state=activation_state,
            predicate_activation_count=activation_count,
            affected_claim_ids=claims,
            affected_evidence_modes=modes,
            affected_criterion_ids=criterion_ids,
            audit_finding_id=AUDIT_FINDING_ID,
            audit_artifact_hash=audit_artifact_hash,
        )
        validate_completion_validity_invalidation_binding(index, invalidation)
    except (
        CompletionValidityProjectionError,
        HistoricalScientificValidityError,
        TypeError,
        ValueError,
    ) as exc:
        raise _builder_error(
            "historical spread-time invalidation binding validation failed for "
            f"{row.completion_record_id}"
        ) from exc
    return invalidation, trial_study_id


def build_historical_spread_time_invalidation_inventory(
    index: LocalIndex | LocalIndexView,
    evidence: EvidenceStore,
    *,
    audit_artifact_hash: str,
) -> HistoricalSpreadTimeInvalidationInventory:
    """Rebuild the frozen 34-completion inventory without mutating authority."""

    if not isinstance(index, (LocalIndex, LocalIndexView)) or not isinstance(
        evidence,
        EvidenceStore,
    ):
        raise _builder_error(
            "historical spread-time builder requires LocalIndex/View and EvidenceStore"
        )
    audit_hash = _require_digest(
        "historical spread-time audit artifact hash",
        audit_artifact_hash,
    )
    try:
        audit_document = evidence.read_verified(audit_hash)
    except (FileNotFoundError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise _builder_error(
            "historical spread-time audit artifact is unavailable"
        ) from exc
    audit = _parse_audit_document(audit_document)

    closes_by_study: dict[str, list[IndexRecord]] = defaultdict(list)
    for close in index.records_by_kind("study-close"):
        if close.subject.startswith("Study:"):
            closes_by_study[close.subject.removeprefix("Study:")].append(close)

    invalidations: list[HistoricalScientificValidityInvalidation] = []
    derived_contexts: set[str] = set()
    for row in audit.rows:
        study = index.get("study-open", row.study_id)
        closes = closes_by_study.get(row.study_id, [])
        if study is None or len(closes) != 1:
            raise _builder_error(
                "historical spread-time Study or unique close is unavailable"
            )
        invalidation, trial_study_id = _build_one(
            index,
            evidence,
            row=row,
            audit_artifact_hash=audit_hash,
            study_close_record_id=closes[0].record_id,
        )
        invalidations.append(invalidation)
        derived_contexts.add(row.study_id)
        derived_contexts.add(trial_study_id)

    contexts = tuple(sorted(derived_contexts))
    if contexts != audit.study_contexts or contexts != EXPECTED_STUDY_CONTEXTS:
        raise _builder_error(
            "historical spread-time derived Study contexts differ from the audit"
        )
    normalized = tuple(
        sorted(invalidations, key=lambda item: item.completion_record_id)
    )
    return HistoricalSpreadTimeInvalidationInventory(
        audit_artifact_hash=audit_hash,
        study_contexts=contexts,
        invalidations=normalized,
    )


def build_historical_spread_time_invalidations(
    index: LocalIndex | LocalIndexView,
    evidence: EvidenceStore,
    *,
    audit_artifact_hash: str,
) -> tuple[HistoricalScientificValidityInvalidation, ...]:
    """Return only the exact 34 typed objects for Writer admission."""

    return build_historical_spread_time_invalidation_inventory(
        index,
        evidence,
        audit_artifact_hash=audit_artifact_hash,
    ).invalidations


__all__ = [
    "AUDIT_FINDING_ID",
    "AUDIT_SLICE_DIGEST_INVENTORY_SCHEMA",
    "AuditSliceDigestInventoryEntry",
    "EXPECTED_ATOMIC_ACTIVATION_COUNTS",
    "EXPECTED_COMPLETION_COUNT",
    "EXPECTED_STUDY_CONTEXTS",
    "HistoricalSpreadTimeInvalidationBuilderError",
    "HistoricalSpreadTimeInvalidationInventory",
    "build_historical_spread_time_invalidation_inventory",
    "build_historical_spread_time_invalidations",
]
