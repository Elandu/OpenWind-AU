"""Small, thread-safe building blocks for derived local caches."""

from __future__ import annotations

import os
import threading
import time
import uuid
from pathlib import Path

_CACHE_LOCK_STRIPES = tuple(threading.RLock() for _ in range(64))


def cache_target_lock(target: Path) -> threading.RLock:
    """Return one of a bounded set of locks for a normalized cache target."""

    normalized = os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(target))))
    if normalized.startswith("\\\\?\\"):
        normalized = normalized[4:]
    return _CACHE_LOCK_STRIPES[hash(normalized) % len(_CACHE_LOCK_STRIPES)]


def atomic_replace_with_retry(source: Path, target: Path) -> None:
    """Atomically replace a cache target, tolerating brief Windows sharing races."""

    for attempt in range(5):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.02 * (2**attempt))


def atomic_write_bytes(target: Path, payload: bytes) -> None:
    """Durably write bytes beside a target and install them with an atomic replace."""

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.part")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        atomic_replace_with_retry(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


__all__ = [
    "atomic_replace_with_retry",
    "atomic_write_bytes",
    "cache_target_lock",
]
