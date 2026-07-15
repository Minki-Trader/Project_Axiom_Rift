from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import stat
from threading import Barrier

import pytest

import axiom_rift.research.reproducible_cache as cache_module
from axiom_rift.research.reproducible_cache import (
    ReproducibleCacheError,
    publish_reproducible_cache,
)


def test_concurrent_different_bytes_never_replace_the_winner(
    tmp_path: Path,
) -> None:
    barrier = Barrier(2)
    path = "local/cache/race/value.bin"

    def publish(content: bytes) -> tuple[str, bytes]:
        barrier.wait()
        try:
            publish_reproducible_cache(
                repository_root=tmp_path,
                relative_path=path,
                content=content,
            )
        except ReproducibleCacheError:
            return "rejected", content
        return "published", content

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(publish, (b"first", b"second")))

    assert sorted(status for status, _ in results) == ["published", "rejected"]
    winner = next(content for status, content in results if status == "published")
    target = tmp_path / path
    assert target.read_bytes() == winner
    assert not tuple(target.parent.glob(".reproducible-cache-*.tmp"))

    publish_reproducible_cache(
        repository_root=tmp_path,
        relative_path=path,
        content=winner,
    )
    loser = b"second" if winner == b"first" else b"first"
    with pytest.raises(ReproducibleCacheError, match="different bytes"):
        publish_reproducible_cache(
            repository_root=tmp_path,
            relative_path=path,
            content=loser,
        )
    assert target.read_bytes() == winner


def test_concurrent_same_bytes_are_both_idempotent(tmp_path: Path) -> None:
    barrier = Barrier(2)
    path = "local/cache/race/same.bin"

    def publish() -> str:
        barrier.wait()
        return publish_reproducible_cache(
            repository_root=tmp_path,
            relative_path=path,
            content=b"same",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _: publish(), range(2)))

    assert results[0] == results[1]
    assert (tmp_path / path).read_bytes() == b"same"
    assert not tuple(
        (tmp_path / path).parent.glob(".reproducible-cache-*.tmp")
    )


def test_link_parent_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    link = (tmp_path / "local").absolute()
    original_lstat = Path.lstat

    def linked_parent_lstat(path: Path):
        metadata = original_lstat(path)
        if path.absolute() == link:
            values = list(metadata)
            values[0] = stat.S_IFLNK | 0o777
            return type(metadata)(values)
        return metadata

    monkeypatch.setattr(Path, "lstat", linked_parent_lstat)

    with pytest.raises(ReproducibleCacheError, match="link or reparse"):
        publish_reproducible_cache(
            repository_root=tmp_path,
            relative_path="local/cache/value.bin",
            content=b"value",
        )
    assert not (tmp_path / "local" / "cache" / "value.bin").exists()


def test_textual_root_link_is_rejected_before_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path.absolute()
    original_lstat = Path.lstat

    def linked_root_lstat(path: Path):
        metadata = original_lstat(path)
        if path.absolute() == root:
            values = list(metadata)
            values[0] = stat.S_IFLNK | 0o777
            return type(metadata)(values)
        return metadata

    monkeypatch.setattr(Path, "lstat", linked_root_lstat)
    with pytest.raises(ReproducibleCacheError, match="link or reparse"):
        publish_reproducible_cache(
            repository_root=root,
            relative_path="local/cache/value.bin",
            content=b"value",
        )


def test_existing_target_hardlink_alias_is_rejected(tmp_path: Path) -> None:
    path = "local/cache/aliases/value.bin"
    publish_reproducible_cache(
        repository_root=tmp_path,
        relative_path=path,
        content=b"value",
    )
    target = tmp_path / path
    alias = target.with_name("alias.bin")
    try:
        cache_module.os.link(target, alias)
    except OSError:
        pytest.skip("hard links are unavailable in this environment")
    with pytest.raises(ReproducibleCacheError, match="hard-link aliases"):
        publish_reproducible_cache(
            repository_root=tmp_path,
            relative_path=path,
            content=b"value",
        )


def test_target_swap_between_lstat_and_open_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = "local/cache/swap/value.bin"
    publish_reproducible_cache(
        repository_root=tmp_path,
        relative_path=path,
        content=b"value",
    )
    target = (tmp_path / path).absolute()
    original_open = cache_module.os.open
    swapped = False

    def swap_before_open(value, flags, *args, **kwargs):
        nonlocal swapped
        candidate = Path(value).absolute()
        if not swapped and candidate == target:
            swapped = True
            target.unlink()
            target.write_bytes(b"value")
        return original_open(value, flags, *args, **kwargs)

    monkeypatch.setattr(cache_module.os, "open", swap_before_open)
    with pytest.raises(ReproducibleCacheError, match="identity changed"):
        publish_reproducible_cache(
            repository_root=tmp_path,
            relative_path=path,
            content=b"value",
        )


def test_cleanup_failure_never_masks_the_primary_race_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = "local/cache/cleanup/value.bin"
    target = tmp_path / path
    original_unlink = Path.unlink

    def competing_link(source, destination, **kwargs):
        Path(destination).write_bytes(b"other")
        raise FileExistsError

    def blocked_temporary_cleanup(value: Path, *args, **kwargs):
        if value.name.startswith(".reproducible-cache-"):
            raise PermissionError("simulated cleanup denial")
        return original_unlink(value, *args, **kwargs)

    monkeypatch.setattr(cache_module.os, "link", competing_link)
    monkeypatch.setattr(Path, "unlink", blocked_temporary_cleanup)
    with pytest.raises(ReproducibleCacheError, match="different bytes"):
        publish_reproducible_cache(
            repository_root=tmp_path,
            relative_path=path,
            content=b"value",
        )
    assert target.read_bytes() == b"other"


@pytest.mark.parametrize(
    "relative_path",
    (
        "cache/value.bin",
        "local/cache",
        "local/cache/../escaped.bin",
        "../local/cache/escaped.bin",
        "local\\cache\\value.bin",
        "local/cache/C:alias.bin",
        "local/cache/con.txt",
        "local/cache/trailing.",
        "local//cache/value.bin",
    ),
)
def test_cache_path_requires_canonical_local_cache_confinement(
    tmp_path: Path,
    relative_path: str,
) -> None:
    with pytest.raises(ReproducibleCacheError):
        publish_reproducible_cache(
            repository_root=tmp_path,
            relative_path=relative_path,
            content=b"value",
        )
