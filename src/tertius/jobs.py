"""Background batch job manager.

The job runs on a daemon-free worker thread owned by the server process. It has
no reference to any request, response, or client connection: closing the browser
or dropping the network changes nothing. The UI observes progress by polling
:meth:`JobManager.status`, which reads the same state the worker writes.
"""

from __future__ import annotations

import inspect
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Iterable

from .config import STATE_FILENAME, TranscriptionOptions
from .state import (
    DONE,
    MODE_ALIGN,
    MODE_SKIP,
    MODE_TRANSCRIBE,
    SKIPPED,
    StateStore,
)
from .transcribe import WhisperTranscriber, align_file, transcribe_file

log = logging.getLogger(__name__)

IDLE = "idle"
RUNNING = "running"
COMPLETED = "completed"
CANCELLED = "cancelled"
ERROR = "error"

# What a running job is busy with, so the UI can distinguish "downloading a
# 1.5 GB model" from "hung".
DOWNLOADING_MODEL = "downloading_model"
LOADING_MODEL = "loading_model"
TRANSCRIBING = "transcribing"

# Stop the batch after this many files fail in a row with the identical error:
# that is the environment being broken, not a run of bad files.
REPEATED_FAILURE_LIMIT = 3


class JobError(RuntimeError):
    """Raised for invalid job control requests (e.g. start while running)."""


class JobManager:
    """Owns at most one batch job at a time, plus the state store behind it."""

    def __init__(
        self,
        transcriber_factory: Callable[[TranscriptionOptions], WhisperTranscriber]
        | None = None,
        transcribe_fn: Callable = transcribe_file,
        align_fn: Callable = align_file,
    ):
        self._transcriber_factory = transcriber_factory or WhisperTranscriber
        self._transcribe_fn = transcribe_fn
        self._align_fn = align_fn
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._store: StateStore | None = None
        self._options = TranscriptionOptions()
        self._output_dir: Path | None = None
        self._state = IDLE
        self._error: str | None = None
        self._current_file: str | None = None
        self._started_at: float | None = None
        self._finished_at: float | None = None
        self._run = self._empty_run()
        self._phase: str | None = None
        self._download = self._empty_download()
        self._cancel_requested_at: float | None = None
        self._notice: str | None = None
        self._active_device: str | None = None

    # ------------------------------------------------------------------ setup

    @staticmethod
    def _empty_run() -> dict:
        return {"total": 0, "processed": 0, "completed": 0, "failed": 0, "skipped": 0}

    @staticmethod
    def _empty_download() -> dict:
        # `downloaded`/`total` come from huggingface_hub's own bars and are only
        # trustworthy as a *ratio*: it runs overlapping sized bars, so the byte
        # figures can be roughly double the real download. `expected_bytes` is
        # the measured size of the files we fetch, and is what the UI shows.
        return {"downloaded": 0, "total": 0, "model": None, "expected_bytes": None}

    @staticmethod
    def _model_is_cached(model_size: str) -> bool:
        """Best-effort: if we cannot tell, assume a download is coming."""
        try:
            from .transcribe import is_model_cached

            return is_model_cached(model_size)
        except Exception:
            return False

    def _note_download_progress(self, downloaded: int, total: int) -> None:
        with self._lock:
            self._download["downloaded"] = downloaded
            self._download["total"] = total

    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def attach(self, output_dir: str | Path) -> StateStore:
        """Point the manager at an output directory, loading any prior state.

        Interrupted (`in_progress`) files are reset to pending here: a file that
        was mid-transcription when the process died is never treated as done.
        """
        with self._lock:
            if self.is_running():
                raise JobError("a job is already running")
            store = StateStore.for_output_dir(output_dir)
            reset = store.reset_in_progress()
            if reset:
                log.info("reset %d interrupted file(s) to pending", len(reset))
            self._store = store
            self._output_dir = Path(output_dir).expanduser().resolve()
            saved = store.snapshot().get("options") or {}
            if saved:
                try:
                    self._options = TranscriptionOptions.from_dict(saved)
                except (TypeError, ValueError):
                    log.warning("ignoring unreadable saved options in state file")
            return store

    @property
    def store(self) -> StateStore | None:
        with self._lock:
            return self._store

    @property
    def output_dir(self) -> Path | None:
        with self._lock:
            return self._output_dir

    @staticmethod
    def state_file_exists(output_dir: str | Path) -> bool:
        return (Path(output_dir).expanduser() / STATE_FILENAME).is_file()

    # ---------------------------------------------------------- job lifecycle

    def start(
        self,
        files: Iterable[str | Path] | None = None,
        output_dir: str | Path | None = None,
        options: TranscriptionOptions | dict | None = None,
        retry_failed: bool = False,
    ) -> dict:
        """Queue `files` and kick off the worker thread. Returns immediately."""
        with self._lock:
            if self.is_running():
                raise JobError("a job is already running")

            target_dir = output_dir or self._output_dir
            if target_dir is None:
                raise JobError("no output directory set")
            if self._store is None or Path(target_dir).expanduser().resolve() != (
                self._output_dir
            ):
                self.attach(target_dir)
            else:
                self._store.reset_in_progress()

            if options is not None:
                self._options = (
                    options
                    if isinstance(options, TranscriptionOptions)
                    else TranscriptionOptions.from_dict(options)
                )
            self._store.set_context(self._output_dir, self._options.to_dict())

            if files:
                self._store.add_files(files)
            if retry_failed:
                self._store.retry_failed()

            pending = self._store.pending_files()
            if not pending:
                raise JobError("nothing to transcribe — queue has no pending files")

            # Files with no matching text file need an answer first, or the run
            # would quietly do the opposite of what was wanted.
            undecided = self._store.files_needing_a_decision()
            if undecided:
                names = ", ".join(Path(p).name for p in undecided[:3])
                more = f" and {len(undecided) - 3} more" if len(undecided) > 3 else ""
                raise JobError(
                    f"{len(undecided)} file(s) have no matching text file and no "
                    f"choice made yet ({names}{more}). For each one, add a text "
                    f"file, or set it to transcribe normally, or skip it."
                )

            summary = self._store.summary()
            self._run = self._empty_run()
            self._run["total"] = len(pending)
            self._run["skipped"] = summary[DONE] + summary[SKIPPED]
            self._cancel.clear()
            self._state = RUNNING
            self._error = None
            self._current_file = None
            self._phase = None
            self._download = self._empty_download()
            self._cancel_requested_at = None
            self._notice = None
            self._active_device = None
            self._started_at = time.time()
            self._finished_at = None

            self._thread = threading.Thread(
                target=self._run_batch,
                name="transcription-worker",
                daemon=False,
            )
            self._thread.start()
            log.info("started batch: %d pending file(s)", len(pending))
            return self.status()

    def resume(self, output_dir: str | Path | None = None) -> dict:
        """Continue an interrupted job: re-queue nothing, just work the pending set."""
        with self._lock:
            if output_dir is not None:
                self.attach(output_dir)
            if self._store is None:
                raise JobError("no job state to resume")
            return self.start(files=None, output_dir=self._output_dir)

    def cancel(self) -> None:
        """Ask the worker to stop after the file it is currently working on.

        This is cooperative, and the check happens between files. A file wedged
        inside the model's native code cannot be interrupted from Python at all,
        so cancelling can appear to do nothing. `status()` reports how long the
        request has been outstanding so the UI can offer a force stop instead of
        showing "cancelling" forever.
        """
        with self._lock:
            if self._cancel_requested_at is None:
                self._cancel_requested_at = time.time()
        self._cancel.set()

    def force_stop_is_the_only_way_out(self, patience: float = 20.0) -> bool:
        """Has a cancel been pending long enough to look stuck?"""
        with self._lock:
            requested = self._cancel_requested_at
            return bool(
                requested and self.is_running() and time.time() - requested > patience
            )

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    # --------------------------------------------------------------- the work

    def _run_batch(self) -> None:
        store = self._store
        output_dir = self._output_dir
        options = self._options
        assert store is not None and output_dir is not None

        # Ask by signature rather than catching TypeError, which would silently
        # retry a factory that raised TypeError for its own reasons.
        try:
            takes_progress = (
                "on_download_progress"
                in inspect.signature(self._transcriber_factory).parameters
            )
        except (TypeError, ValueError):
            takes_progress = False
        transcriber = (
            self._transcriber_factory(
                options, on_download_progress=self._note_download_progress
            )
            if takes_progress
            else self._transcriber_factory(options)
        )

        warmup = getattr(transcriber, "warmup", None)
        if callable(warmup):
            # The first use of a model size downloads ~0.1-3 GB. Say so, with
            # progress, or it looks like a hang.
            with self._lock:
                self._phase = (
                    LOADING_MODEL
                    if self._model_is_cached(options.model_size)
                    else DOWNLOADING_MODEL
                )
                self._download = self._empty_download()
                self._download["model"] = options.model_size
                from .system import MODEL_CATALOG

                catalog = MODEL_CATALOG.get(options.model_size) or {}
                self._download["expected_bytes"] = catalog.get("download_bytes")
            try:
                warmup()
            except Exception as exc:  # model download/device failure
                log.exception("model failed to load")
                with self._lock:
                    self._state = ERROR
                    self._error = f"model failed to load: {exc}"
                    self._finished_at = time.time()
                    self._phase = None
                return

        with self._lock:
            self._phase = TRANSCRIBING
            if getattr(transcriber, "gpu_fallback_reason", None):
                self._notice = (
                    "The GPU could not be used, so this job is running on the CPU "
                    f"(slower). Reason: {transcriber.gpu_fallback_reason}"
                )
            self._active_device = getattr(transcriber, "active_device", None)

        last_error: str | None = None
        repeated = 0

        try:
            while True:
                if self._cancel.is_set():
                    break
                pending = store.pending_files()
                if not pending:
                    break
                path = pending[0]

                # Files the user marked "skip" are taken out of the queue's way
                # without being touched.
                if (store.get(path) or {}).get("mode") == MODE_SKIP:
                    store.mark_skipped(path)
                    log.info("skipping %s (set to skip)", path)
                    with self._lock:
                        self._run["skipped"] += 1
                    continue
                with self._lock:
                    self._current_file = path
                entry = store.mark_in_progress(path)
                log.info("transcribing %s", path)
                started = time.time()
                # Mirror the scanned folder's layout under the output directory,
                # so `A/talk.mp3` and `B/talk.mp3` do not collide on one name.
                subdir = (entry or {}).get("subdir") or ""
                target_dir = Path(output_dir) / subdir if subdir else output_dir
                mode = (entry or {}).get("mode") or MODE_TRANSCRIBE
                try:
                    if mode == MODE_ALIGN:
                        outputs, result = self._align_fn(
                            transcriber,
                            path,
                            target_dir,
                            entry["reference_text"],
                            options.alignment_granularity,
                        )
                    else:
                        outputs, result = self._transcribe_fn(
                            transcriber, path, target_dir
                        )
                except Exception as exc:  # one bad file must not stop the batch
                    log.exception("failed: %s", path)
                    message = f"{type(exc).__name__}: {exc}"
                    store.mark_failed(path, message)
                    with self._lock:
                        self._run["failed"] += 1
                        self._run["processed"] += 1
                        if message == last_error:
                            repeated += 1
                        else:
                            last_error, repeated = message, 1

                    # A bad file is a bad file; the same error on file after
                    # file is the environment, and grinding through the whole
                    # queue to fail every one of them helps nobody.
                    if repeated >= REPEATED_FAILURE_LIMIT:
                        log.error(
                            "%d files in a row failed identically - stopping", repeated
                        )
                        with self._lock:
                            self._state = ERROR
                            self._error = (
                                f"{repeated} files in a row failed with the same "
                                f"error, so the batch was stopped with "
                                f"{len(store.pending_files())} still pending. "
                                f"Fix the cause and resume.\n\n{message}"
                            )
                            self._finished_at = time.time()
                            self._current_file = None
                            self._phase = None
                        return
                    continue
                store.mark_done(
                    path,
                    outputs=outputs,
                    language=getattr(result, "language", None),
                    duration=getattr(result, "duration", None),
                )
                log.info(
                    "done: %s (%.1fs) -> %s",
                    path,
                    time.time() - started,
                    ", ".join(outputs),
                )
                with self._lock:
                    self._run["completed"] += 1
                    self._run["processed"] += 1
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("batch aborted")
            with self._lock:
                self._state = ERROR
                self._error = f"{type(exc).__name__}: {exc}"
                self._finished_at = time.time()
                self._current_file = None
                self._phase = None
            return
        finally:
            unload = getattr(transcriber, "unload", None)
            if callable(unload):
                unload()

        with self._lock:
            self._current_file = None
            self._phase = None
            self._finished_at = time.time()
            self._state = CANCELLED if self._cancel.is_set() else COMPLETED
            run = dict(self._run)
        log.info(
            "batch %s - %d file(s): %d completed, %d failed, %d already done (skipped)",
            self._state,
            run["total"],
            run["completed"],
            run["failed"],
            run["skipped"],
        )

    # ----------------------------------------------------------------- status

    def status(self, include_files: bool = True) -> dict:
        with self._lock:
            running = self.is_running()
            store = self._store
            payload = {
                "running": running,
                "state": RUNNING if running else self._state,
                "output_dir": str(self._output_dir) if self._output_dir else None,
                "options": self._options.to_dict(),
                "current_file": self._current_file,
                "started_at": self._started_at,
                "finished_at": self._finished_at,
                "error": self._error,
                "run": dict(self._run),
                "phase": self._phase,
                "download": dict(self._download),
                "cancel_requested": self._cancel.is_set(),
                "cancel_pending_seconds": (
                    round(time.time() - self._cancel_requested_at, 1)
                    if self._cancel_requested_at and running
                    else None
                ),
                "notice": self._notice,
                "active_device": self._active_device,
            }
        payload["force_stop_suggested"] = self.force_stop_is_the_only_way_out()
        if store is not None:
            snapshot = store.snapshot()
            payload["summary"] = snapshot["summary"]
            payload["can_resume"] = store.has_unfinished_work() and not payload[
                "running"
            ]
            if include_files:
                payload["files"] = snapshot["files"]
        else:
            payload["summary"] = {"total": 0}
            payload["can_resume"] = False
            if include_files:
                payload["files"] = []
        return payload
