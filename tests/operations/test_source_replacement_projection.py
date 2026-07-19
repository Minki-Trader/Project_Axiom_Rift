from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from axiom_rift.core.canonical import canonical_bytes
from axiom_rift.core.identity import canonical_digest
from axiom_rift.operations.effective_axis_projection import (
    EffectiveAxisProjectionError,
    effective_axis_resolution,
    selectable_axis_ids,
)
from axiom_rift.operations.permits import PermitAuthority
from axiom_rift.operations.writer import (
    StateWriter,
    TransitionError,
    _exact_source_replacement_wait_capability,
)
from axiom_rift.research.effective_axis import (
    EffectiveAxisStatus,
    ReplayAxisBinding,
    SourceInvalidationBinding,
    SourceReplacementBinding,
    resolve_effective_axis,
)
from axiom_rift.research.portfolio import PortfolioSnapshot
from axiom_rift.research.source_authority import (
    SourceAuthorityAuditManifest,
    SourceAuthorityInvalidation,
    SourceAuthorityLatch,
    SourceAuthorityReason,
    SourceAuthoritySurface,
    SourceReplacementLineage,
    source_replacement_capability_id,
    source_replacement_capability_set_id,
)
from axiom_rift.research.replay_obligation import ReplayObligationStatus
from axiom_rift.research.sources import (
    SourceContract,
    SourceEligibility,
    SourceEligibilityReceipt,
    SourceTransitionEvidence,
    SourceType,
)
from axiom_rift.storage.index import IndexRecord, LocalIndex
from tests.operations.test_writer import (
    FIXED_NOW,
    REPO_ROOT,
    PortfolioAxis,
    initiative_objective,
    mission_goal,
    source_audit_report_bytes,
)


MISSION_ID = "MIS-SOURCE-REPLACEMENT"


def _contract(token: str) -> SourceContract:
    return SourceContract(
        display_name=f"source replacement {token}",
        canonical_instrument="synthetic-index",
        runtime_identifier=f"SYN.{token}",
        source_type=SourceType.BAR,
        instrument_semantics={
            "asset_type": "index",
            "quote_basis": "bid",
            "contract_size": "one",
            "currency": "USD",
            "digits": 2,
            "point": "0.01",
            "session": "declared",
            "timezone": "UTC",
            "adjustment": "none",
            "roll": "none",
        },
        mapping_semantics={
            "runtime_symbol": f"SYN.{token}",
            "mapping_rule": f"exact_local_symbol_{token}",
        },
        schema_semantics={
            "columns": ["time", "open", "high", "low", "close"],
            "schema_revision": f"fixture-{token}",
        },
        field_semantics={
            "bar_open": "open",
            "bar_close": "close",
            "event_time": "bar_open_time",
            "information_complete_at": "bar_close_time",
            "first_available_at": f"independent_archive_{token}",
        },
        clock_semantics={
            "decision_alignment": "completed_m5_bar",
            "timezone_conversion": "declared_utc",
        },
        availability_semantics={
            "acquisition": f"local_fixture_connector_{token}",
            "content_hash": "sha256",
            "coverage": "declared_fixture_window",
            "gap_policy": "fail_closed",
            "revision_or_vintage": f"immutable_fixture_{token}",
            "causal_ttl_seconds": 60,
            "runtime_retrieval_method": f"local_fixture_poll_{token}",
        },
    )


def _source_states(
    contract: SourceContract,
    *,
    token: int,
) -> tuple[IndexRecord, IndexRecord]:
    source_id = contract.source_contract_id
    context_id = canonical_digest(
        domain="source-state",
        payload={
            "source_id": source_id,
            "state": "context_only",
            "ordinal": 1,
            "evidence_receipt_id": None,
        },
    )
    shared = {
        "availability_identity": contract.availability_identity,
        "clock_identity": contract.clock_identity,
        "contract": contract.to_identity_payload(),
        "contract_hash": source_id.removeprefix("source:"),
        "field_identity": contract.field_identity,
        "mapping_identity": contract.mapping_identity,
        "schema_identity": contract.schema_identity,
    }
    context = IndexRecord(
        kind="source-state",
        record_id=context_id,
        subject=f"Source:{source_id}",
        status="context_only",
        fingerprint=source_id,
        payload={
            **shared,
            "alpha_failure": False,
            "evidence_receipt_id": None,
            "ordinal": 1,
            "receipt": None,
            "scientific_trial_delta": 0,
            "suspension_reason": None,
            "transition_evidence": None,
        },
        event_stream=f"source:{source_id}",
        event_sequence=1,
    )
    receipt = SourceEligibilityReceipt(
        source_contract_id=source_id,
        evidence=SourceTransitionEvidence.HISTORICAL_AUDIT,
        producer_completion_id=f"source-producer-{token}",
        observed_at_utc="2026-07-14T00:00:00Z",
        artifact_hashes=(f"{token:064x}",),
        facts={
            "acquisition_observed": True,
            "content_hash_verified": True,
            "event_time_audited": True,
            "information_complete_at_audited": True,
            "first_availability_audited": True,
            "coverage_audited": True,
            "gaps_audited": True,
            "revision_or_vintage_audited": True,
        },
    )
    audited_id = canonical_digest(
        domain="source-state",
        payload={
            "source_id": source_id,
            "state": "historical_audited",
            "ordinal": 2,
            "evidence_receipt_id": receipt.identity,
        },
    )
    audited = IndexRecord(
        kind="source-state",
        record_id=audited_id,
        subject=f"Source:{source_id}",
        status="historical_audited",
        fingerprint=source_id,
        payload={
            **shared,
            "alpha_failure": False,
            "evidence_receipt_id": receipt.identity,
            "ordinal": 2,
            "receipt": receipt.to_identity_payload(),
            "scientific_trial_delta": 0,
            "suspension_reason": None,
            "transition_evidence": receipt.evidence.value,
        },
        event_stream=f"source:{source_id}",
        event_sequence=2,
    )
    return context, audited


def _invalidation_record(
    contract: SourceContract,
    state: IndexRecord,
    *,
    token: int,
) -> IndexRecord:
    manifest = SourceAuthorityAuditManifest(
        report_artifact_hash=f"{token + 1:064x}",
        report_finding_id=f"SOURCE-REPLACEMENT-{token}",
        source_contract_id=contract.source_contract_id,
        source_state_record_id=state.record_id,
        surface=SourceAuthoritySurface.AVAILABILITY,
        reason_code=SourceAuthorityReason.POINT_IN_TIME_AUTHORITY_UNPROVEN,
        observed_defect="old point-in-time authority was not proven",
        observed_at_utc="2026-07-14T00:00:00Z",
    )
    invalidation = SourceAuthorityInvalidation(
        source_contract_id=contract.source_contract_id,
        source_state_record_id=state.record_id,
        audit_artifact_hash=f"{token + 2:064x}",
        surface=manifest.surface,
        reason_code=manifest.reason_code,
        observed_defect=manifest.observed_defect,
        observed_at_utc=manifest.observed_at_utc,
    )
    latch = SourceAuthorityLatch.bind(
        invalidation=invalidation,
        manifest=manifest,
    )
    return IndexRecord(
        kind="source-authority-invalidation",
        record_id=invalidation.identity,
        subject=f"Source:{contract.source_contract_id}",
        status="confirmed_and_suspended",
        fingerprint=invalidation.identity.removeprefix(
            "source-authority-invalidation:"
        ),
        payload={
            "audit_manifest": manifest.to_identity_payload(),
            "eligible_source_state_record_id": state.record_id,
            "invalidated_state": state.status,
            "invalidation": invalidation.to_identity_payload(),
            "latch": latch.to_identity_payload(),
            "preserved_receipt_id": state.payload["evidence_receipt_id"],
            "prior_active_source_state_record_id": state.record_id,
            "replacement_state_record_id": f"{token + 3:064x}",
            "scientific_trial_delta": 0,
        },
        event_stream=f"source-authority:{contract.source_contract_id}",
        event_sequence=1,
    )


def _axis(token: str, *, status: str) -> dict[str, str]:
    return {
        "axis_id": f"axis-{token}",
        "axis_identity": "axis:" + token * 64,
        "status": status,
    }


def _source_decision(
    *,
    axis: dict[str, str],
    source_ids: list[str],
    token: str,
) -> IndexRecord:
    executable = {
        "schema": "source_replacement_executable_fixture.v1",
        "source_contracts": source_ids,
    }
    return IndexRecord(
        kind="portfolio-decision",
        record_id="decision:" + token * 64,
        subject=f"Mission:{MISSION_ID}",
        status="new_mechanism",
        fingerprint=token * 64,
        payload={
            "baseline_executable": executable,
            "baseline_executable_id": "executable:"
            + canonical_digest(domain="executable", payload=executable),
            "target_axis_identity": axis["axis_identity"],
        },
    )


def _replacement_record(lineage: SourceReplacementLineage) -> IndexRecord:
    stream = (
        f"source-replacement:{lineage.mission_id}:"
        f"{lineage.original_axis_identity}:"
        f"{lineage.invalidated_source_contract_id}"
    )
    return IndexRecord(
        kind="source-replacement-lineage",
        record_id=lineage.identity,
        subject=f"Axis:{lineage.original_axis_identity}",
        status="retired_original_axis",
        fingerprint=lineage.identity.removeprefix(
            "source-replacement-lineage:"
        ),
        payload={
            "candidate_delta": 0,
            "claim_delta": "none",
            "holdout_delta": 0,
            "lineage": lineage.to_identity_payload(),
            "scientific_credit": 0,
            "terminal_scientific_credit": 0,
            "trial_delta": 0,
        },
        event_stream=stream,
        event_sequence=1,
    )


class SourceReplacementProjectionTests(unittest.TestCase):
    def _seed(self, index: LocalIndex):
        old_contract = _contract("old")
        new_contract = _contract("new")
        old_context, old_state = _source_states(old_contract, token=10)
        new_context, new_state = _source_states(new_contract, token=20)
        invalidation = _invalidation_record(
            old_contract, old_state, token=30
        )
        old_axis = _axis("a", status="pruned")
        new_axis = _axis("b", status="open")
        portfolio_id = "portfolio:" + "c" * 64
        snapshot = IndexRecord(
            kind="portfolio-snapshot",
            record_id=portfolio_id,
            subject=f"Mission:{MISSION_ID}",
            status="current",
            fingerprint="c" * 64,
            payload={
                "axes": [deepcopy(old_axis), deepcopy(new_axis)],
                "mission_id": MISSION_ID,
            },
            event_stream=f"portfolio:{MISSION_ID}",
            event_sequence=1,
        )
        index.put_many(
            (
                old_context,
                old_state,
                new_context,
                new_state,
                invalidation,
                snapshot,
                _source_decision(
                    axis=old_axis,
                    source_ids=[old_contract.source_contract_id],
                    token="d",
                ),
                _source_decision(
                    axis=new_axis,
                    source_ids=[new_contract.source_contract_id],
                    token="e",
                ),
            )
        )
        lineage = SourceReplacementLineage(
            mission_id=MISSION_ID,
            portfolio_snapshot_id=portfolio_id,
            original_axis_id=old_axis["axis_id"],
            original_axis_identity=old_axis["axis_identity"],
            invalidation_id=invalidation.record_id,
            invalidated_source_contract_id=old_contract.source_contract_id,
            replacement_source_contract_id=new_contract.source_contract_id,
            replacement_source_state_record_id=new_state.record_id,
            replacement_axis_id=new_axis["axis_id"],
            replacement_axis_identity=new_axis["axis_identity"],
        )
        return old_axis, new_axis, lineage

    def test_typed_new_source_and_axis_terminal_retire_only_the_old_axis(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                old_axis, new_axis, lineage = self._seed(index)
                original_snapshot = deepcopy(old_axis)
                before = effective_axis_resolution(index, old_axis)
                self.assertIs(
                    before.effective_status,
                    EffectiveAxisStatus.BLOCKED_BY_INVALIDATED_SOURCE,
                )
                self.assertFalse(before.terminal_eligible)

                index.put(_replacement_record(lineage))
                retired = effective_axis_resolution(index, old_axis)
                replacement = effective_axis_resolution(index, new_axis)

                self.assertEqual(old_axis, original_snapshot)
                self.assertIs(
                    retired.effective_status,
                    EffectiveAxisStatus.RETIRED_BY_SOURCE_REPLACEMENT,
                )
                self.assertFalse(retired.selectable)
                self.assertFalse(retired.decision_option_eligible)
                self.assertTrue(retired.terminal_eligible)
                self.assertEqual(len(retired.source_replacements), 1)
                self.assertEqual(
                    retired.source_replacements[0].replacement_axis_identity,
                    new_axis["axis_identity"],
                )
                self.assertTrue(replacement.selectable)
                self.assertEqual(
                    selectable_axis_ids(index, (old_axis, new_axis)),
                    (new_axis["axis_id"],),
                )
                self.assertEqual(
                    index.get(
                        "source-replacement-lineage", lineage.identity
                    ).payload["terminal_scientific_credit"],
                    0,
                )

    def test_untyped_or_tampered_replacement_cannot_clear_the_latch(self) -> None:
        with TemporaryDirectory() as temporary:
            with LocalIndex(Path(temporary) / "index.sqlite3") as index:
                old_axis, _new_axis, lineage = self._seed(index)
                tampered = _replacement_record(lineage)
                tampered_payload = dict(tampered.payload)
                tampered_payload["terminal_scientific_credit"] = 1
                index.put(
                    IndexRecord(
                        kind=tampered.kind,
                        record_id=tampered.record_id,
                        subject=tampered.subject,
                        status=tampered.status,
                        fingerprint=tampered.fingerprint,
                        payload=tampered_payload,
                        event_stream=tampered.event_stream,
                        event_sequence=tampered.event_sequence,
                    )
                )
                with self.assertRaisesRegex(
                    EffectiveAxisProjectionError,
                    "record is not canonical",
                ):
                    effective_axis_resolution(index, old_axis)


class SourceReplacementCapabilityTests(unittest.TestCase):
    @staticmethod
    def _invalidation(token: str) -> SourceInvalidationBinding:
        return SourceInvalidationBinding(
            source_contract_id="source:" + token * 64,
            invalidation_record_id=(
                "source-authority-invalidation:" + token * 64
            ),
        )

    @staticmethod
    def _resolution(
        *,
        axis_id: str,
        token: str,
        invalidations: tuple[SourceInvalidationBinding, ...],
        replacements: tuple[SourceReplacementBinding, ...] = (),
        replays: tuple[ReplayAxisBinding, ...] = (),
    ):
        return resolve_effective_axis(
            axis_id=axis_id,
            axis_identity="axis:" + token * 64,
            snapshot_status="open",
            source_contract_ids=tuple(
                item.source_contract_id for item in invalidations
            ),
            invalidations=invalidations,
            source_replacements=replacements,
            replay_bindings=replays,
        )

    def test_multiple_source_only_blockers_form_one_exact_sorted_capability_set(
        self,
    ) -> None:
        invalidation_a = self._invalidation("1")
        invalidation_b = self._invalidation("2")
        axes = {
            "axis-a": {"axis_id": "axis-a", "axis_identity": "axis:" + "a" * 64},
            "axis-b": {"axis_id": "axis-b", "axis_identity": "axis:" + "b" * 64},
        }
        resolutions = {
            "axis-a": self._resolution(
                axis_id="axis-a",
                token="a",
                invalidations=(invalidation_a,),
            ),
            "axis-b": self._resolution(
                axis_id="axis-b",
                token="b",
                invalidations=(invalidation_b,),
            ),
        }
        members = tuple(
            source_replacement_capability_id(
                mission_id=MISSION_ID,
                original_axis_id=axis_id,
                original_axis_identity=axes[axis_id]["axis_identity"],
                invalidation_id=(
                    resolutions[axis_id].invalidations[0].invalidation_record_id
                ),
                invalidated_source_contract_id=(
                    resolutions[axis_id].invalidations[0].source_contract_id
                ),
            )
            for axis_id in ("axis-a", "axis-b")
        )
        expected = source_replacement_capability_set_id(tuple(reversed(members)))
        self.assertEqual(
            source_replacement_capability_set_id(members),
            expected,
        )
        self.assertEqual(
            _exact_source_replacement_wait_capability(
                mission_id=MISSION_ID,
                terminal_axes=axes,
                terminal_resolutions=resolutions,
                terminal_hard_blockers=("axis-b", "axis-a"),
            ),
            expected,
        )
        with self.assertRaises(ValueError):
            source_replacement_capability_set_id((members[0],))
        with self.assertRaises(ValueError):
            source_replacement_capability_set_id(
                (members[0], members[0])
            )

    def test_aggregate_excludes_replaced_sources_and_rejects_hidden_replay(
        self,
    ) -> None:
        invalidation_a = self._invalidation("3")
        invalidation_b = self._invalidation("4")
        axis_id = "axis-partial"
        axis_identity = "axis:" + "c" * 64
        replacement = SourceReplacementBinding(
            record_id="source-replacement-lineage:" + "5" * 64,
            mission_id=MISSION_ID,
            original_axis_id=axis_id,
            original_axis_identity=axis_identity,
            invalidation_record_id=invalidation_a.invalidation_record_id,
            invalidated_source_contract_id=invalidation_a.source_contract_id,
            replacement_source_contract_id="source:" + "6" * 64,
            replacement_source_state_record_id="7" * 64,
            replacement_axis_id="axis-replacement",
            replacement_axis_identity="axis:" + "8" * 64,
        )
        axis = {"axis_id": axis_id, "axis_identity": axis_identity}
        partial = self._resolution(
            axis_id=axis_id,
            token="c",
            invalidations=(invalidation_a, invalidation_b),
            replacements=(replacement,),
        )
        expected = source_replacement_capability_id(
            mission_id=MISSION_ID,
            original_axis_id=axis_id,
            original_axis_identity=axis_identity,
            invalidation_id=invalidation_b.invalidation_record_id,
            invalidated_source_contract_id=invalidation_b.source_contract_id,
        )
        self.assertEqual(
            _exact_source_replacement_wait_capability(
                mission_id=MISSION_ID,
                terminal_axes={axis_id: axis},
                terminal_resolutions={axis_id: partial},
                terminal_hard_blockers=(axis_id,),
            ),
            expected,
        )

        replay = ReplayAxisBinding(
            axis_id=axis_id,
            axis_identity=axis_identity,
            governing_mission_id=MISSION_ID,
            obligation_id="historical-replay-obligation:" + "9" * 64,
            original_executable_id="executable:" + "a" * 64,
            original_study_id="STU-HIDDEN-REPLAY",
            state_record_id="historical-replay-obligation:" + "9" * 64,
            status=ReplayObligationStatus.PENDING,
        )
        replay_hidden_by_source = self._resolution(
            axis_id=axis_id,
            token="c",
            invalidations=(invalidation_a, invalidation_b),
            replacements=(replacement,),
            replays=(replay,),
        )
        self.assertIs(
            replay_hidden_by_source.effective_status,
            EffectiveAxisStatus.BLOCKED_BY_INVALIDATED_SOURCE,
        )
        self.assertIsNone(
            _exact_source_replacement_wait_capability(
                mission_id=MISSION_ID,
                terminal_axes={axis_id: axis},
                terminal_resolutions={axis_id: replay_hidden_by_source},
                terminal_hard_blockers=(axis_id,),
            )
        )


class SourceReplacementWriterTests(unittest.TestCase):
    """Exercise the additive replacement through the single state writer."""

    @staticmethod
    def _qualify_source(
        writer: StateWriter,
        *,
        contract: SourceContract,
        token: str,
    ) -> str:
        context = SourceEligibility.register(contract)
        writer.record_source_eligibility(
            eligibility=context,
            receipt=None,
            operation_id=f"{token}-source-register",
        )
        history_artifact = writer.evidence.finalize(
            f"{token} independent point-in-time history".encode("ascii")
        )
        history_receipt = SourceEligibilityReceipt(
            source_contract_id=contract.source_contract_id,
            evidence=SourceTransitionEvidence.HISTORICAL_AUDIT,
            producer_completion_id=f"{token}-history-producer",
            observed_at_utc=FIXED_NOW,
            artifact_hashes=(history_artifact.sha256,),
            facts={
                "acquisition_observed": True,
                "content_hash_verified": True,
                "coverage_audited": True,
                "event_time_audited": True,
                "first_availability_audited": True,
                "gaps_audited": True,
                "information_complete_at_audited": True,
                "revision_or_vintage_audited": True,
            },
        )
        audited = context.complete_historical_audit(history_receipt.identity)
        writer.record_source_eligibility(
            eligibility=audited,
            receipt=history_receipt,
            operation_id=f"{token}-source-history-audit",
        )
        runtime_artifact = writer.evidence.finalize(
            f"{token} local runtime availability".encode("ascii")
        )
        runtime_receipt = SourceEligibilityReceipt(
            source_contract_id=contract.source_contract_id,
            evidence=SourceTransitionEvidence.RUNTIME_AVAILABILITY_PROOF,
            producer_completion_id=f"{token}-runtime-producer",
            observed_at_utc=FIXED_NOW,
            artifact_hashes=(runtime_artifact.sha256,),
            facts={
                "complete_or_closed": True,
                "fresh": True,
                "historical_runtime_field_parity": True,
                "latency_ms": 1,
                "local_realtime_retrieval": True,
                "synchronized": True,
            },
        )
        eligible = audited.prove_runtime_availability(runtime_receipt.identity)
        result = writer.record_source_eligibility(
            eligibility=eligible,
            receipt=runtime_receipt,
            operation_id=f"{token}-source-runtime-eligible",
        )
        return canonical_digest(
            domain="source-state",
            payload={
                "source_id": contract.source_contract_id,
                "state": "runtime_eligible",
                "ordinal": result.result["ordinal"],
                "evidence_receipt_id": runtime_receipt.identity,
            },
        )

    def test_writer_records_exact_replacement_without_credit_or_snapshot_rewrite(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary:
            writer = StateWriter(
                temporary,
                permit_authority=PermitAuthority(b"r" * 32),
                clock=lambda: FIXED_NOW,
                engineering_fixture=True,
                foundation_root=REPO_ROOT,
            )
            writer.initialize_ready()
            writer.open_mission(
                mission_id=MISSION_ID,
                goal=mission_goal("source replacement lineage"),
                operation_id="source-replacement-mission",
            )
            writer.open_initiative(
                initiative_id="INI-SOURCE-REPLACEMENT",
                objective=initiative_objective("source replacement lineage"),
                operation_id="source-replacement-initiative",
            )

            old_contract = _contract("writer-old")
            new_contract = _contract("writer-new")
            old_state_id = self._qualify_source(
                writer,
                contract=old_contract,
                token="old",
            )
            new_state_id = self._qualify_source(
                writer,
                contract=new_contract,
                token="new",
            )
            old_axis = PortfolioAxis(
                axis_id="source-replacement-axis-a",
                causal_question="Can the invalid old source support this axis?",
                mechanism_family="source-replacement-old",
                status="pruned",
            )
            new_axis = PortfolioAxis(
                axis_id="source-replacement-axis-b",
                causal_question="Can the new eligible source support a new axis?",
                mechanism_family="source-replacement-new",
            )
            snapshot = PortfolioSnapshot(
                mission_id=MISSION_ID,
                axes=(old_axis, new_axis),
                opportunity_cost_basis=(
                    "retain the old latch while testing a distinct source axis"
                ),
            )
            writer.record_portfolio_snapshot(
                snapshot=snapshot,
                operation_id="source-replacement-portfolio",
            )
            axis_payloads = {
                axis["axis_id"]: axis
                for axis in snapshot.to_identity_payload()["axes"]
            }

            def seed_source_lineage(current, _index):
                assert current is not None
                executable_by_axis = {
                    axis_id: {
                        "schema": "source_replacement_writer_fixture.v1",
                        "source_contracts": [source_id],
                    }
                    for axis_id, source_id in (
                        (old_axis.axis_id, old_contract.source_contract_id),
                        (new_axis.axis_id, new_contract.source_contract_id),
                    )
                }
                records = tuple(
                    IndexRecord(
                        kind="portfolio-decision",
                        record_id="decision:"
                        + canonical_digest(
                            domain="source-replacement-writer-lineage",
                            payload={
                                "axis_identity": axis_payloads[axis_id][
                                    "axis_identity"
                                ],
                                "source_id": source_id,
                            },
                        ),
                        subject=f"Mission:{MISSION_ID}",
                        status="new_mechanism",
                        fingerprint=canonical_digest(
                            domain="source-replacement-writer-fingerprint",
                            payload=axis_id,
                        ),
                        payload={
                            "baseline_executable": executable_by_axis[axis_id],
                            "baseline_executable_id": "executable:"
                            + canonical_digest(
                                domain="executable",
                                payload=executable_by_axis[axis_id],
                            ),
                            "target_axis_identity": axis_payloads[axis_id][
                                "axis_identity"
                            ],
                        },
                    )
                    for axis_id, source_id in (
                        (old_axis.axis_id, old_contract.source_contract_id),
                        (new_axis.axis_id, new_contract.source_contract_id),
                    )
                )
                return writer._body(current), list(records), {"seeded": True}

            writer._commit(
                event_kind="source_replacement_writer_lineage_fixture_seeded",
                operation_id="source-replacement-lineage-seed",
                subject=f"Mission:{MISSION_ID}",
                payload={"scientific_credit": 0, "trial_delta": 0},
                prepare=seed_source_lineage,
            )
            report = writer.evidence.finalize(
                source_audit_report_bytes(
                    finding_id="SOURCE-REPLACEMENT-WRITER-001",
                    source_contract_id=old_contract.source_contract_id,
                    source_state_record_id=old_state_id,
                )
            )
            manifest = SourceAuthorityAuditManifest(
                report_artifact_hash=report.sha256,
                report_finding_id="SOURCE-REPLACEMENT-WRITER-001",
                source_contract_id=old_contract.source_contract_id,
                source_state_record_id=old_state_id,
                surface=SourceAuthoritySurface.AVAILABILITY,
                reason_code=(
                    SourceAuthorityReason.POINT_IN_TIME_AUTHORITY_UNPROVEN
                ),
                observed_defect=(
                    "the old source lacks independent point-in-time authority"
                ),
                observed_at_utc=FIXED_NOW,
            )
            manifest_artifact = writer.evidence.finalize(
                canonical_bytes(manifest.to_identity_payload())
            )
            invalidation = SourceAuthorityInvalidation(
                source_contract_id=old_contract.source_contract_id,
                source_state_record_id=old_state_id,
                audit_artifact_hash=manifest_artifact.sha256,
                surface=manifest.surface,
                reason_code=manifest.reason_code,
                observed_defect=manifest.observed_defect,
                observed_at_utc=manifest.observed_at_utc,
            )
            writer.suspend_source_authority_from_audit(
                invalidation=invalidation,
                operation_id="source-replacement-invalidate-old-source",
            )
            old_payload = axis_payloads[old_axis.axis_id]
            new_payload = axis_payloads[new_axis.axis_id]
            lineage = SourceReplacementLineage(
                mission_id=MISSION_ID,
                portfolio_snapshot_id=snapshot.identity,
                original_axis_id=old_axis.axis_id,
                original_axis_identity=old_payload["axis_identity"],
                invalidation_id=invalidation.identity,
                invalidated_source_contract_id=old_contract.source_contract_id,
                replacement_source_contract_id=new_contract.source_contract_id,
                replacement_source_state_record_id=new_state_id,
                replacement_axis_id=new_axis.axis_id,
                replacement_axis_identity=new_payload["axis_identity"],
            )
            invalid_lineage = SourceReplacementLineage(
                mission_id=lineage.mission_id,
                portfolio_snapshot_id=lineage.portfolio_snapshot_id,
                original_axis_id=lineage.original_axis_id,
                original_axis_identity=lineage.original_axis_identity,
                invalidation_id=lineage.invalidation_id,
                invalidated_source_contract_id=(
                    lineage.invalidated_source_contract_id
                ),
                replacement_source_contract_id=(
                    lineage.replacement_source_contract_id
                ),
                replacement_source_state_record_id="f" * 64,
                replacement_axis_id=lineage.replacement_axis_id,
                replacement_axis_identity=lineage.replacement_axis_identity,
            )
            with self.assertRaises(TransitionError):
                writer.record_source_replacement_lineage(
                    lineage=invalid_lineage,
                    operation_id="reject-stale-replacement-source-head",
                )

            before_control = writer.read_control()
            original_snapshot = snapshot.to_identity_payload()
            with LocalIndex(writer.index_path) as index:
                original_latch_record = index.get(
                    "source-authority-invalidation", invalidation.identity
                )
                original_authority_head = index.event_head(
                    f"source-authority:{old_contract.source_contract_id}"
                )
                original_source_head = index.event_head(
                    f"source:{old_contract.source_contract_id}"
                )
            assert original_latch_record is not None
            recorded = writer.record_source_replacement_lineage(
                lineage=lineage,
                operation_id="record-source-replacement-lineage",
            )
            self.assertEqual(recorded.result["trial_delta"], 0)
            self.assertEqual(recorded.result["claim_delta"], "none")
            self.assertEqual(recorded.result["holdout_delta"], 0)
            after_control = writer.read_control()
            assert before_control is not None and after_control is not None
            self.assertEqual(after_control["next_action"], before_control["next_action"])
            self.assertEqual(
                after_control["scientific"], before_control["scientific"]
            )
            self.assertEqual(snapshot.to_identity_payload(), original_snapshot)

            with LocalIndex(writer.index_path) as index:
                record = index.get("source-replacement-lineage", lineage.identity)
                current_latch_record = index.get(
                    "source-authority-invalidation", invalidation.identity
                )
                current_authority_head = index.event_head(
                    f"source-authority:{old_contract.source_contract_id}"
                )
                current_source_head = index.event_head(
                    f"source:{old_contract.source_contract_id}"
                )
                old_resolution = effective_axis_resolution(index, old_payload)
                new_resolution = effective_axis_resolution(index, new_payload)
            assert record is not None
            self.assertEqual(current_latch_record, original_latch_record)
            self.assertEqual(current_authority_head, original_authority_head)
            self.assertEqual(current_source_head, original_source_head)
            self.assertEqual(record.payload["scientific_credit"], 0)
            self.assertEqual(record.payload["terminal_scientific_credit"], 0)
            self.assertEqual(record.payload["trial_delta"], 0)
            self.assertIs(
                old_resolution.effective_status,
                EffectiveAxisStatus.RETIRED_BY_SOURCE_REPLACEMENT,
            )
            self.assertFalse(old_resolution.selectable)
            self.assertTrue(old_resolution.terminal_eligible)
            self.assertTrue(new_resolution.selectable)

            reused = writer.record_source_replacement_lineage(
                lineage=lineage,
                operation_id="record-source-replacement-lineage",
            )
            self.assertTrue(reused.reused)
            with self.assertRaises(TransitionError):
                writer.record_source_replacement_lineage(
                    lineage=lineage,
                    operation_id="reject-second-source-replacement-lineage",
                )


if __name__ == "__main__":
    unittest.main()
