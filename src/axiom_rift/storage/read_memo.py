"""Bounded defensive memo for one pinned local-index read action."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any


class MemoizedReadToken:
    """Expiring capability shared by one read action and its cache."""

    __slots__ = ("active",)

    def __init__(self) -> None:
        self.active = True

    def expire(self) -> None:
        self.active = False


class ActionReadMemo:
    """Cache only demonstrated hot joins inside one pinned read snapshot."""

    MAX_RECORDS = 4_096
    MAX_QUERIES = 256
    MAX_EVENT_HEADS = 1_024
    MAX_EVENT_RECORDS = 4_096

    __slots__ = (
        "event_heads",
        "event_records",
        "queries",
        "records",
        "token",
        "_integrity_error",
    )

    def __init__(
        self,
        token: MemoizedReadToken,
        *,
        integrity_error: Callable[[str], Exception],
    ) -> None:
        self.token = token
        self._integrity_error = integrity_error
        self.records: dict[tuple[str, str], Any | None] = {}
        self.queries: dict[tuple[object, ...], tuple[Any, ...]] = {}
        self.event_heads: dict[str, Any | None] = {}
        self.event_records: dict[tuple[str, int], Any | None] = {}

    def clear(self) -> None:
        self.records.clear()
        self.queries.clear()
        self.event_heads.clear()
        self.event_records.clear()

    def get(
        self,
        key: tuple[str, str],
        loader: Callable[[], Any | None],
    ) -> Any | None:
        if key in self.records:
            return deepcopy(self.records[key])
        record = loader()
        if len(self.records) < self.MAX_RECORDS:
            self.records[key] = deepcopy(record)
        return record

    def query(
        self,
        key: tuple[object, ...],
        loader: Callable[[], tuple[Any, ...]],
    ) -> tuple[Any, ...]:
        if key in self.queries:
            return deepcopy(self.queries[key])
        records = loader()
        stored = deepcopy(records)
        pending: dict[tuple[str, str], Any] = {}
        for record in stored:
            record_key = (record.kind, record.record_id)
            existing = self.records.get(record_key, _MISSING)
            pending_existing = pending.get(record_key, _MISSING)
            if (
                existing is not _MISSING
                and existing != record
                or pending_existing is not _MISSING
                and pending_existing != record
            ):
                raise self._integrity_error(
                    "memoized record differs within one read session"
                )
            pending[record_key] = record
        new_count = sum(key not in self.records for key in pending)
        if (
            len(self.queries) >= self.MAX_QUERIES
            or len(self.records) + new_count > self.MAX_RECORDS
        ):
            return records
        self.queries[key] = stored
        self.records.update(pending)
        return records

    def event_head(
        self,
        stream: str,
        loader: Callable[[], Any | None],
    ) -> Any | None:
        if stream in self.event_heads:
            return self.event_heads[stream]
        head = loader()
        if len(self.event_heads) < self.MAX_EVENT_HEADS:
            self.event_heads[stream] = head
        return head

    def event_record(
        self,
        key: tuple[str, int],
        loader: Callable[[], Any | None],
    ) -> Any | None:
        if key in self.event_records:
            return deepcopy(self.event_records[key])
        record = loader()
        record_key = (
            None if record is None else (record.kind, record.record_id)
        )
        if (
            record_key is not None
            and record_key in self.records
            and self.records[record_key] != record
        ):
            raise self._integrity_error(
                "memoized event record differs within one read session"
            )
        if (
            len(self.event_records) < self.MAX_EVENT_RECORDS
            and (
                record_key is None
                or record_key in self.records
                or len(self.records) < self.MAX_RECORDS
            )
        ):
            self.event_records[key] = deepcopy(record)
            if record_key is not None:
                self.records[record_key] = deepcopy(record)
        return record


_MISSING = object()
