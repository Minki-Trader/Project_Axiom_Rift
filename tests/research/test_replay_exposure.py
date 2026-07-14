from __future__ import annotations

import unittest

from axiom_rift.research.replay_exposure import (
    ReplayExposureError,
    derive_frozen_family_exposure_context,
)
from axiom_rift.storage.index import IndexRecord


def _trial(
    sequence: int,
    *,
    study_id: str,
    executable_id: str,
    context: int,
) -> IndexRecord:
    return IndexRecord(
        kind="trial",
        record_id=executable_id,
        subject=f"Study:{study_id}",
        status="registered",
        fingerprint=str(sequence),
        payload={
            "study_id": study_id,
            "executable": {
                "parameters": {
                    "historical_context_prior_global_exposure_count": context,
                }
            },
        },
        authority_sequence=sequence,
        authority_event_id=f"{sequence:064x}",
        authority_offset=sequence,
    )


class ReplayExposureTests(unittest.TestCase):
    def test_unregistered_family_uses_current_trial_count(self) -> None:
        trials = tuple(
            _trial(
                sequence,
                study_id=f"STU-{sequence:04d}",
                executable_id=f"executable:{sequence:064x}",
                context=0,
            )
            for sequence in range(1, 4)
        )
        result = derive_frozen_family_exposure_context(
            trials=trials,
            prior_global_exposure_floor=18,
            study_id="STU-9001",
            expected_family_size=2,
            parameter_name="historical_context_prior_global_exposure_count",
            allow_unregistered=True,
        )
        self.assertEqual(result.prior_global_exposure_count, 21)
        self.assertEqual(result.family_executable_ids, ())

    def test_later_trials_do_not_change_registered_family_context(self) -> None:
        trials = (
            _trial(
                1,
                study_id="STU-8001",
                executable_id="executable:" + "1" * 64,
                context=0,
            ),
            _trial(
                2,
                study_id="STU-8002",
                executable_id="executable:" + "2" * 64,
                context=0,
            ),
            _trial(
                3,
                study_id="STU-9001",
                executable_id="executable:" + "3" * 64,
                context=20,
            ),
            _trial(
                4,
                study_id="STU-9001",
                executable_id="executable:" + "4" * 64,
                context=20,
            ),
            _trial(
                5,
                study_id="STU-9002",
                executable_id="executable:" + "5" * 64,
                context=0,
            ),
        )
        result = derive_frozen_family_exposure_context(
            trials=trials,
            prior_global_exposure_floor=18,
            study_id="STU-9001",
            expected_family_size=2,
            parameter_name="historical_context_prior_global_exposure_count",
            allow_unregistered=False,
        )
        self.assertEqual(result.prior_global_exposure_count, 20)
        self.assertEqual(result.first_family_authority_sequence, 3)

    def test_partial_registered_family_fails_closed(self) -> None:
        trials = (
            _trial(
                1,
                study_id="STU-9001",
                executable_id="executable:" + "1" * 64,
                context=18,
            ),
        )
        with self.assertRaisesRegex(ReplayExposureError, "incomplete"):
            derive_frozen_family_exposure_context(
                trials=trials,
                prior_global_exposure_floor=18,
                study_id="STU-9001",
                expected_family_size=2,
                parameter_name=(
                    "historical_context_prior_global_exposure_count"
                ),
                allow_unregistered=True,
            )


if __name__ == "__main__":
    unittest.main()
