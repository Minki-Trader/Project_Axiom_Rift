from __future__ import annotations

from dataclasses import replace
import unittest

from axiom_rift.operations.study_close_checkpoint import (
    EMPTY_CLOSE_CHAIN_DIGEST,
    CHECKPOINT_VALIDATOR_VERSION,
    JournalDeliveryCursor,
    LEGACY_V2_CHECKPOINT_VALIDATOR_VERSION,
    StudyCloseCheckpointError,
    StudyCloseDeliveryCheckpoint,
    advance_close_chain,
    validate_checkpoint_transition,
    validate_no_close_suffix,
)


class StudyCloseCheckpointV2Tests(unittest.TestCase):
    def checkpoint_pair(
        self,
    ) -> tuple[StudyCloseDeliveryCheckpoint, StudyCloseDeliveryCheckpoint]:
        first_event = "1" * 64
        close_event = "2" * 64
        first_cursor = JournalDeliveryCursor(
            sequence=1,
            event_id=first_event,
            previous_event_id=None,
            event_offset=0,
            event_bytes=100,
            next_offset=100,
            boundary_sha256="3" * 64,
            journal_path="records/journal.jsonl",
        )
        previous = StudyCloseDeliveryCheckpoint(
            basis="full_audit",
            parent_main="a" * 40,
            previous_checkpoint_commit=None,
            previous_checkpoint_digest=None,
            cursor=first_cursor,
            prospective_close_count=0,
            prospective_close_chain_digest=EMPTY_CLOSE_CHAIN_DIGEST,
            repair_manifest_digest=None,
            control_sha256="4" * 64,
            kpi_sha256="5" * 64,
            last_study_close_event_id=None,
            last_study_close_revision=None,
        )
        current = StudyCloseDeliveryCheckpoint(
            basis="study_close",
            parent_main="b" * 40,
            previous_checkpoint_commit="c" * 40,
            previous_checkpoint_digest=previous.checkpoint_digest,
            cursor=JournalDeliveryCursor(
                sequence=2,
                event_id=close_event,
                previous_event_id=first_event,
                event_offset=100,
                event_bytes=100,
                next_offset=200,
                boundary_sha256="6" * 64,
                journal_path="records/journal.jsonl",
            ),
            prospective_close_count=1,
            prospective_close_chain_digest=advance_close_chain(
                EMPTY_CLOSE_CHAIN_DIGEST, close_event, 2
            ),
            repair_manifest_digest=None,
            control_sha256="7" * 64,
            kpi_sha256=previous.kpi_sha256,
            last_study_close_event_id=close_event,
            last_study_close_revision=2,
        )
        return previous, current

    def test_count_chain_cursor_and_last_close_advance_together(self) -> None:
        previous, current = self.checkpoint_pair()
        validate_checkpoint_transition(
            previous,
            current,
            suffix_closes=(("2" * 64, 2),),
            current_kpi_sha256=previous.kpi_sha256,
        )
        invalid = (
            replace(current, prospective_close_count=0),
            replace(
                current,
                prospective_close_chain_digest=EMPTY_CLOSE_CHAIN_DIGEST,
            ),
            replace(current, last_study_close_revision=1),
            replace(
                current,
                cursor=replace(
                    current.cursor,
                    sequence=1,
                    next_offset=50,
                ),
            ),
        )
        for checkpoint in invalid:
            with self.subTest(checkpoint=checkpoint), self.assertRaises(
                StudyCloseCheckpointError
            ):
                validate_checkpoint_transition(
                    previous,
                    checkpoint,
                    suffix_closes=(("2" * 64, 2),),
                    current_kpi_sha256=previous.kpi_sha256,
                )
        with self.assertRaisesRegex(
            StudyCloseCheckpointError,
            "explicit KPI materialization",
        ):
            validate_checkpoint_transition(
                previous,
                replace(current, kpi_sha256="8" * 64),
                suffix_closes=(("2" * 64, 2),),
                current_kpi_sha256="8" * 64,
            )

    def test_no_close_suffix_inherits_explicit_kpi_hash(self) -> None:
        _previous, checkpoint = self.checkpoint_pair()
        current_cursor = replace(
            checkpoint.cursor,
            sequence=3,
            event_id="9" * 64,
            previous_event_id=checkpoint.cursor.event_id,
            event_offset=200,
            next_offset=300,
        )
        validate_no_close_suffix(
            checkpoint,
            suffix_closes=(),
            current_cursor=current_cursor,
            current_kpi_sha256=checkpoint.kpi_sha256,
        )
        with self.assertRaisesRegex(StudyCloseCheckpointError, "KPI changed"):
            validate_no_close_suffix(
                checkpoint,
                suffix_closes=(),
                current_cursor=current_cursor,
                current_kpi_sha256="0" * 64,
            )

    def test_legacy_v2_history_is_preserved_but_new_close_requires_activation(self) -> None:
        previous, current = self.checkpoint_pair()
        legacy_previous = replace(
            previous,
            validator_version=LEGACY_V2_CHECKPOINT_VALIDATOR_VERSION,
        )
        legacy_current = replace(
            current,
            kpi_sha256="8" * 64,
            previous_checkpoint_digest=legacy_previous.checkpoint_digest,
            validator_version=LEGACY_V2_CHECKPOINT_VALIDATOR_VERSION,
        )
        validate_checkpoint_transition(
            legacy_previous,
            legacy_current,
            suffix_closes=(("2" * 64, 2),),
            current_kpi_sha256="8" * 64,
        )
        with self.assertRaisesRegex(
            StudyCloseCheckpointError,
            "explicit checkpoint maintenance",
        ):
            validate_checkpoint_transition(
                legacy_previous,
                replace(
                    current,
                    previous_checkpoint_digest=legacy_previous.checkpoint_digest,
                ),
                suffix_closes=(("2" * 64, 2),),
                current_kpi_sha256=legacy_previous.kpi_sha256,
            )
        activation = replace(
            legacy_previous,
            basis="maintenance",
            parent_main="d" * 40,
            previous_checkpoint_commit="e" * 40,
            previous_checkpoint_digest=legacy_previous.checkpoint_digest,
            validator_version=CHECKPOINT_VALIDATOR_VERSION,
        )
        validate_checkpoint_transition(
            legacy_previous,
            activation,
            suffix_closes=(),
            current_kpi_sha256=legacy_previous.kpi_sha256,
        )

    def test_maintenance_advances_cursor_or_navigation_but_never_close_authority(self) -> None:
        _initial, previous = self.checkpoint_pair()
        maintenance = replace(
            previous,
            basis="maintenance",
            parent_main="d" * 40,
            previous_checkpoint_commit="e" * 40,
            previous_checkpoint_digest=previous.checkpoint_digest,
            cursor=replace(
                previous.cursor,
                sequence=3,
                event_id="9" * 64,
                previous_event_id=previous.cursor.event_id,
                event_offset=200,
                next_offset=300,
            ),
            control_sha256="a" * 64,
            last_study_close_event_id=None,
            last_study_close_revision=None,
        )
        validate_checkpoint_transition(
            previous,
            maintenance,
            suffix_closes=(),
            current_kpi_sha256=previous.kpi_sha256,
        )
        kpi_only = replace(
            maintenance,
            cursor=previous.cursor,
            kpi_sha256="b" * 64,
        )
        validate_checkpoint_transition(
            previous,
            kpi_only,
            suffix_closes=(),
            current_kpi_sha256="b" * 64,
        )
        for invalid in (
            replace(maintenance, cursor=previous.cursor),
            replace(
                maintenance,
                prospective_close_count=previous.prospective_close_count + 1,
            ),
            replace(
                maintenance,
                prospective_close_chain_digest="f" * 64,
            ),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(
                StudyCloseCheckpointError
            ):
                validate_checkpoint_transition(
                    previous,
                    invalid,
                    suffix_closes=(),
                    current_kpi_sha256=previous.kpi_sha256,
                )


if __name__ == "__main__":
    unittest.main()
