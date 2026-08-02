"""Durable, resumable job state.

The state file is a single JSON document written atomically (temp file +
``os.replace``) so a kill -9 mid-write cannot leave a half-written file. Every
mutation persists immediately: whatever is on disk is the truth on resume.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Iterable

from .config import STATE_FILENAME

PENDING = "pending"
IN_PROGRESS = "in_progress"
DONE = "done"
FAILED = "failed"
SKIPPED = "skipped"

STATUSES = (PENDING, IN_PROGRESS, DONE, FAILED, SKIPPED)

STATE_VERSION = 1


def _now() -> float:
    return time.time()


def _key(path: str | os.PathLike) -> str:
    """Canonical identity for a file: absolute, normalised path string."""
    return str(Path(path).expanduser().resolve())


class StateStore:
    """Tracks each file's status for one output directory.

    Thread-safe: the background worker mutates it while HTTP requests read it.
    """

    def __init__(self, state_path: str | os.PathLike):
        self.path = Path(state_path)
        self._lock = threading.RLock()
        self._data: dict = self._empty()
        if self.path.exists():
            self._load()

    # ------------------------------------------------------------------ setup

    @classmethod
    def for_output_dir(cls, output_dir: str | os.PathLike) -> "StateStore":
        output_dir = Path(output_dir).expanduser().resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        return cls(output_dir / STATE_FILENAME)

    @staticmethod
    def _empty() -> dict:
        return {
            "version": STATE_VERSION,
            "created_at": _now(),
            "updated_at": _now(),
            "output_dir": None,
            "options": {},
            "files": {},
        }

    def _load(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            # A corrupt state file must not brick the app; start clean but keep
            # the old one around for inspection.
            backup = self.path.with_suffix(self.path.suffix + ".corrupt")
            try:
                os.replace(self.path, backup)
            except OSError:
                pass
            self._data = self._empty()
            return
        if not isinstance(data, dict) or "files" not in data:
            self._data = self._empty()
            return
        data.setdefault("version", STATE_VERSION)
        data.setdefault("options", {})
        data.setdefault("output_dir", None)
        self._data = data

    def _flush(self) -> None:
        """Atomically persist. Caller must hold the lock."""
        self._data["updated_at"] = _now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".state-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # --------------------------------------------------------------- mutation

    def set_context(self, output_dir: str | os.PathLike, options: dict) -> None:
        with self._lock:
            self._data["output_dir"] = str(Path(output_dir).expanduser().resolve())
            self._data["options"] = dict(options)
            self._flush()

    def add_files(self, paths: Iterable[str | os.PathLike]) -> list[str]:
        """Register files as pending. Already-known files keep their status.

        Returns the keys of files that were newly added.
        """
        added: list[str] = []
        with self._lock:
            for raw in paths:
                key = _key(raw)
                if key in self._data["files"]:
                    continue
                self._data["files"][key] = {
                    "path": key,
                    "name": Path(key).name,
                    "status": PENDING,
                    "added_at": _now(),
                    "started_at": None,
                    "finished_at": None,
                    "error": None,
                    "outputs": [],
                    "language": None,
                    "duration": None,
                }
                added.append(key)
            if added:
                self._flush()
        return added

    def remove_file(self, path: str | os.PathLike) -> bool:
        with self._lock:
            if self._data["files"].pop(_key(path), None) is None:
                return False
            self._flush()
            return True

    def _update(self, path: str | os.PathLike, **fields) -> dict:
        key = _key(path)
        with self._lock:
            entry = self._data["files"].get(key)
            if entry is None:
                raise KeyError(f"file not tracked: {key}")
            entry.update(fields)
            self._flush()
            return dict(entry)

    def mark_pending(self, path) -> dict:
        return self._update(
            path, status=PENDING, started_at=None, finished_at=None, error=None
        )

    def mark_in_progress(self, path) -> dict:
        return self._update(
            path, status=IN_PROGRESS, started_at=_now(), finished_at=None, error=None
        )

    def mark_done(
        self,
        path,
        outputs: Iterable[str | os.PathLike] = (),
        language: str | None = None,
        duration: float | None = None,
    ) -> dict:
        return self._update(
            path,
            status=DONE,
            finished_at=_now(),
            error=None,
            outputs=[str(o) for o in outputs],
            language=language,
            duration=duration,
        )

    def mark_failed(self, path, error: str) -> dict:
        return self._update(
            path, status=FAILED, finished_at=_now(), error=str(error)
        )

    def mark_skipped(self, path) -> dict:
        return self._update(path, status=SKIPPED, finished_at=_now(), error=None)

    def reset_in_progress(self) -> list[str]:
        """Interrupted work is not trustworthy: in_progress -> pending.

        Called on startup/resume. Any partial output for those files will be
        overwritten when they are re-transcribed.
        """
        reset: list[str] = []
        with self._lock:
            for key, entry in self._data["files"].items():
                if entry.get("status") == IN_PROGRESS:
                    entry.update(
                        status=PENDING, started_at=None, finished_at=None, error=None
                    )
                    reset.append(key)
            if reset:
                self._flush()
        return reset

    def retry_failed(self) -> list[str]:
        retried: list[str] = []
        with self._lock:
            for key, entry in self._data["files"].items():
                if entry.get("status") == FAILED:
                    entry.update(
                        status=PENDING, started_at=None, finished_at=None, error=None
                    )
                    retried.append(key)
            if retried:
                self._flush()
        return retried

    # ---------------------------------------------------------------- queries

    def get(self, path) -> dict | None:
        with self._lock:
            entry = self._data["files"].get(_key(path))
            return dict(entry) if entry else None

    def status_of(self, path) -> str | None:
        entry = self.get(path)
        return entry["status"] if entry else None

    def pending_files(self) -> list[str]:
        with self._lock:
            return [
                k
                for k, e in self._data["files"].items()
                if e.get("status") == PENDING
            ]

    def files_with_status(self, status: str) -> list[str]:
        with self._lock:
            return [
                k for k, e in self._data["files"].items() if e.get("status") == status
            ]

    def is_done(self, path) -> bool:
        return self.status_of(path) in (DONE, SKIPPED)

    def has_unfinished_work(self) -> bool:
        with self._lock:
            return any(
                e.get("status") in (PENDING, IN_PROGRESS)
                for e in self._data["files"].values()
            )

    def summary(self) -> dict:
        with self._lock:
            counts = {s: 0 for s in STATUSES}
            for entry in self._data["files"].values():
                status = entry.get("status", PENDING)
                counts[status] = counts.get(status, 0) + 1
            counts["total"] = len(self._data["files"])
            return counts

    def snapshot(self) -> dict:
        """Deep-ish copy safe to serialise from a request handler."""
        with self._lock:
            return {
                "version": self._data.get("version"),
                "created_at": self._data.get("created_at"),
                "updated_at": self._data.get("updated_at"),
                "output_dir": self._data.get("output_dir"),
                "options": dict(self._data.get("options", {})),
                "files": [dict(e) for e in self._data["files"].values()],
                "summary": self.summary(),
            }

    def clear(self) -> None:
        with self._lock:
            options = self._data.get("options", {})
            output_dir = self._data.get("output_dir")
            self._data = self._empty()
            self._data["options"] = options
            self._data["output_dir"] = output_dir
            self._flush()
