"""Public fixture surface for replay implementation-Repair admission tests."""

from replay_repair_fixture_factory import _repair_fixture
from replay_repair_fixture_mutations import (
    _add_failed_science_memory,
    _add_second_implementation_repair,
    _add_terminal_cause_repair,
    _prepend_failed_attempt,
    _rehash_completion,
    _rehash_preflight,
    _replace_attempt_payload,
    _replace_resume_payload,
)
from replay_repair_fixture_records import (
    BATCH_ID,
    BATCH_SPEC,
    CONCURRENT_FAMILY,
    MANIFESTS,
    MATERIAL_IDENTITY,
    NEW_IMPLEMENTATION,
    OBLIGATION_ID,
    REGISTERED,
    STUDY_ID,
    _content_record,
    _event_id,
    _request,
)

__all__ = [
    "BATCH_ID",
    "BATCH_SPEC",
    "CONCURRENT_FAMILY",
    "MANIFESTS",
    "MATERIAL_IDENTITY",
    "NEW_IMPLEMENTATION",
    "OBLIGATION_ID",
    "REGISTERED",
    "STUDY_ID",
    "_add_failed_science_memory",
    "_add_second_implementation_repair",
    "_add_terminal_cause_repair",
    "_content_record",
    "_event_id",
    "_prepend_failed_attempt",
    "_rehash_completion",
    "_rehash_preflight",
    "_repair_fixture",
    "_replace_attempt_payload",
    "_replace_resume_payload",
    "_request",
]
