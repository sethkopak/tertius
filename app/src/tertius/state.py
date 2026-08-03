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

# What to do with a file when its turn comes.
MODE_TRANSCRIBE = "transcribe"  # normal: Whisper writes the transcript
MODE_ALIGN = "align"  # timestamp the supplied text instead
MODE_SKIP = "skip"  # leave it alone
MODE_UNDECIDED = "undecided"  # no text found; waiting on the user
MODES = (MODE_TRANSCRIBE, MODE_ALIGN, MODE_SKIP, MODE_UNDECIDED)

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


def _relative_dir(file_path: Path, base_dir: Path | None) -> str:
    """Where this file sits inside the scanned folder, as a relative path.

    Empty string for files at the top of the scan, or added without a base
    (uploads, individually chosen files) - those land straight in the output
    directory, as before.
    """
    if base_dir is None:
        return ""
    try:
        relative = file_path.parent.relative_to(base_dir)
    except ValueError:  # outside the scanned folder entirely
        return ""
    return "" if relative == Path(".") else relative.as_posix()


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
            "reference_dir": None,
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
        data.setdefault("reference_dir", None)
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

    @property
    def reference_dir(self) -> str | None:
        """An extra folder to look in for text files, if the user set one."""
        with self._lock:
            return self._data.get("reference_dir")

    def set_reference_dir(self, directory: str | os.PathLike | None) -> None:
        with self._lock:
            self._data["reference_dir"] = (
                str(Path(directory).expanduser().resolve()) if directory else None
            )
            self._flush()

    def search_locations(self, audio_path: str | os.PathLike) -> list[str]:
        """Every folder that will be searched for this file's text.

        Exposed so the UI can say where it looked, rather than leaving someone
        staring at "no text found" with no idea why.
        """
        places = [str(Path(audio_path).parent)]
        extra = self.reference_dir
        if extra and extra not in places:
            places.append(extra)
        return places

    @staticmethod
    def _text_in(directory: Path, stem: str, recursive: bool = False) -> str | None:
        exact = directory / f"{stem}.txt"
        if exact.is_file():
            return str(exact)
        wanted = stem.lower()
        try:
            # Globbed as "*" and filtered by hand, not as "*.txt": glob is
            # case-insensitive on Windows and case-sensitive everywhere else, so
            # a "*.txt" pattern quietly stops finding "talk.TXT" on Linux and
            # macOS. Lower-casing the stem while leaving the extension
            # case-sensitive is exactly the half-measure the docstring below
            # promises nobody has to think about.
            entries = directory.rglob("*") if recursive else directory.glob("*")
            for candidate in entries:
                if candidate.suffix.lower() != ".txt":
                    continue
                if candidate.stem.lower() == wanted and candidate.is_file():
                    return str(candidate)
        except OSError:
            pass
        return None

    def find_reference_text(self, audio_path: str | os.PathLike) -> str | None:
        """The text file that goes with this audio, matched by name.

        `VolA01.mp3` pairs with `VolA01.txt`. Looked for beside the audio first,
        then in the text folder if one was set - searched recursively there,
        since people keep texts in their own tree. Case-insensitive throughout,
        because Windows users do not think about that and should not have to.
        """
        audio = Path(audio_path)
        found = self._text_in(audio.parent, audio.stem)
        if found:
            return found
        extra = self.reference_dir
        if extra:
            return self._text_in(Path(extra), audio.stem, recursive=True)
        return None

    def add_files(
        self,
        paths: Iterable[str | os.PathLike],
        base_dir: str | os.PathLike | None = None,
        match_reference_text: bool = False,
    ) -> list[str]:
        """Register files as pending. Already-known files keep their status.

        `base_dir` is the folder that was scanned. Each file remembers where it
        sat inside it, so the output directory can mirror the same structure -
        which also stops `A/talk.mp3` and `B/talk.mp3` writing to one transcript.

        Returns the keys of files that were newly added.
        """
        added: list[str] = []
        root = Path(base_dir).expanduser().resolve() if base_dir else None
        with self._lock:
            for raw in paths:
                key = _key(raw)
                if key in self._data["files"]:
                    continue
                reference = (
                    self.find_reference_text(key) if match_reference_text else None
                )
                if not match_reference_text:
                    mode = MODE_TRANSCRIBE
                elif reference:
                    mode = MODE_ALIGN
                else:
                    # No text found: the user decides, rather than us guessing.
                    mode = MODE_UNDECIDED
                self._data["files"][key] = {
                    "path": key,
                    "name": Path(key).name,
                    "subdir": _relative_dir(Path(key), root),
                    "mode": mode,
                    "reference_text": reference,
                    "status": PENDING,
                    "added_at": _now(),
                    "started_at": None,
                    "finished_at": None,
                    "error": None,
                    "outputs": [],
                    "language": None,
                    "duration": None,
                    "words": None,
                }
                added.append(key)
            if added:
                self._flush()
        return added

    def set_mode(self, path, mode: str, reference_text: str | None = None) -> dict:
        """Choose what happens to one file: transcribe, align, or skip."""
        if mode not in MODES:
            raise ValueError(f"unknown mode: {mode!r}")
        fields = {"mode": mode}
        if mode == MODE_ALIGN:
            if reference_text is None:
                reference_text = (self.get(path) or {}).get("reference_text")
            if not reference_text:
                raise ValueError("aligning needs a text file")
            fields["reference_text"] = str(reference_text)
        elif reference_text is not None:
            fields["reference_text"] = str(reference_text) or None
        return self._update(path, **fields)

    def files_needing_a_decision(self) -> list[str]:
        with self._lock:
            return [
                key
                for key, entry in self._data["files"].items()
                if entry.get("mode") == MODE_UNDECIDED
                and entry.get("status") in (PENDING, IN_PROGRESS)
            ]

    def apply_reference_mode(self, enabled: bool) -> tuple[int, int, int]:
        """Switch text-timestamping on or off across the whole pending queue.

        Returns (matched, needing a decision, reverted to plain transcription).
        Files already done, failed or deliberately skipped are left alone.
        """
        matched = undecided = reverted = 0
        with self._lock:
            for key, entry in self._data["files"].items():
                if entry.get("status") not in (PENDING, IN_PROGRESS):
                    continue
                if entry.get("mode") == MODE_SKIP:
                    continue
                if enabled:
                    reference = entry.get("reference_text") or self.find_reference_text(
                        key
                    )
                    if reference:
                        entry["mode"] = MODE_ALIGN
                        entry["reference_text"] = reference
                        matched += 1
                    else:
                        entry["mode"] = MODE_UNDECIDED
                        undecided += 1
                elif entry.get("mode") in (MODE_ALIGN, MODE_UNDECIDED):
                    entry["mode"] = MODE_TRANSCRIBE
                    reverted += 1
            self._flush()
        return matched, undecided, reverted

    def rematch_reference_texts(self) -> int:
        """Re-check for text files, for when they are added after queueing."""
        found = 0
        with self._lock:
            for key, entry in self._data["files"].items():
                if entry.get("mode") != MODE_UNDECIDED:
                    continue
                reference = self.find_reference_text(key)
                if reference:
                    entry["mode"] = MODE_ALIGN
                    entry["reference_text"] = reference
                    found += 1
            if found:
                self._flush()
        return found

    def set_durations(self, durations: dict) -> int:
        """Record media lengths for files that have none yet.

        Takes the whole batch at once: probing a scanned folder would otherwise
        flush the state file once per file. Files that have since been removed,
        or already have a length, are left alone.
        """
        written = 0
        with self._lock:
            for path, seconds in durations.items():
                entry = self._data["files"].get(_key(path))
                if entry is None or entry.get("duration") or not seconds:
                    continue
                entry["duration"] = float(seconds)
                written += 1
            if written:
                self._flush()
        return written

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
        words: int | None = None,
    ) -> dict:
        return self._update(
            path,
            status=DONE,
            finished_at=_now(),
            error=None,
            outputs=[str(o) for o in outputs],
            language=language,
            duration=duration,
            words=words,
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
            files = []
            for entry in self._data["files"].values():
                copied = dict(entry)
                if copied.get("mode") == MODE_UNDECIDED:
                    # Say where we looked, so "no text found" is explicable.
                    copied["searched"] = self.search_locations(copied["path"])
                files.append(copied)
            return {
                "version": self._data.get("version"),
                "created_at": self._data.get("created_at"),
                "updated_at": self._data.get("updated_at"),
                "output_dir": self._data.get("output_dir"),
                "reference_dir": self._data.get("reference_dir"),
                "options": dict(self._data.get("options", {})),
                "files": files,
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
