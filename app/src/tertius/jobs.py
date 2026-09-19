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
from .settings import remember_output_dir
from .state import (
    DONE,
    MODE_ALIGN,
    MODE_SKIP,
    MODE_TEXT,
    MODE_TRANSCRIBE,
    SKIPPED,
    StateStore,
)
from .speech import Speaker, read_text_source, speak_text_file
from .transcribe import WhisperTranscriber, align_file, transcribe_file
from .translate import Translator, translate_outputs, translate_text_file

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
# Converting a translation model is a one-off that takes minutes and prints
# nothing; without its own phase it is indistinguishable from a hang.
# Installing torch and friends is minutes of silence of its own, before
# any model download starts.
INSTALLING_TRANSLATION_DEPS = "installing_translation_deps"
INSTALLING_SPEECH_DEPS = "installing_speech_deps"
PREPARING_TRANSLATION = "preparing_translation"
TRANSLATING = "translating"
# Speech has the same two silent minutes to account for - a 3-4 GB download,
# and a torch install before it - plus a third phase of its own, because
# generating audio is nothing like decoding it and the UI should not claim
# to be transcribing while it reads a script aloud.
PREPARING_SPEECH = "preparing_speech"
SPEAKING = "speaking"

# Stop the batch after this many files fail in a row with the identical error:
# that is the environment being broken, not a run of bad files.
REPEATED_FAILURE_LIMIT = 3

# How much of the transcript-so-far to keep for the UI's live excerpt. Enough to
# fill two or three lines; the point is to show the thing is alive, not to be a
# second copy of the transcript.
EXCERPT_WORDS = 34


def _accepts(fn: Callable, name: str) -> bool:
    """Does `fn` take a keyword argument called `name`?

    Asked by signature rather than by catching TypeError, which would mistake a
    function's own TypeError for a signature mismatch.
    """
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


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
        translator_factory: Callable[..., Translator] | None = None,
        translate_fn: Callable = translate_outputs,
        translate_text_fn: Callable = translate_text_file,
        speaker_factory: Callable[..., Speaker] | None = None,
        speak_fn: Callable = speak_text_file,
        text_source_fn: Callable = read_text_source,
    ):
        self._transcriber_factory = transcriber_factory or WhisperTranscriber
        self._transcribe_fn = transcribe_fn
        self._align_fn = align_fn
        # Injectable for the same reason the transcriber is: the tests must be
        # able to run a whole batch without a 2 GB download or a real model.
        self._translator_factory = translator_factory or Translator
        self._translate_fn = translate_fn
        self._translate_text_fn = translate_text_fn
        # Injectable for the same reason the other two are: the tests must be
        # able to run a whole batch without a 3 GB download or a real model.
        self._speaker_factory = speaker_factory or Speaker
        self._speak_fn = speak_fn
        self._text_source_fn = text_source_fn
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
        self._active = self._empty_active()

    # ------------------------------------------------------------------ setup

    @staticmethod
    def _empty_run() -> dict:
        return {"total": 0, "processed": 0, "completed": 0, "failed": 0, "skipped": 0}

    @staticmethod
    def _empty_active() -> dict:
        # What the worker is doing *inside* the current file, so the UI can show
        # progress through a 70-minute recording rather than a still frame.
        return {"path": None, "progress": None, "audio_seconds": None, "excerpt": ""}

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

    def _note_install_line(self, line: str) -> None:
        """Show pip's last line, so a long install is visibly alive."""
        with self._lock:
            self._phase = INSTALLING_TRANSLATION_DEPS
            self._notice = line[:200]

    def _note_speech_install_line(self, line: str) -> None:
        """The same, for the speech install, which is the larger of the two.

        Its own phase rather than a shared one: speaking pulls the CUDA build
        of torch where translating takes the CPU build, and a progress line
        saying "installing translation dependencies" during a 2.5 GB download
        nobody asked translation for is how a user concludes the app is
        confused.
        """
        with self._lock:
            self._phase = INSTALLING_SPEECH_DEPS
            self._notice = line[:200]

    def _note_translation_progress(self, done: int, total: int) -> None:
        """How far through translating this file we are.

        Writes the same `active.progress` transcription uses, so the queue row
        keeps moving instead of sitting at 100% for the minutes translation
        takes. The excerpt is left alone: it is the last thing *transcribed*,
        and half a translated sentence in its place would say less.
        """
        with self._lock:
            if total:
                self._active["progress"] = max(0.0, min(1.0, done / total))

    def _note_speech_progress(self, done: int, total: int) -> None:
        """Chunks read so far, for the bar inside the current file."""
        with self._lock:
            if total:
                self._active["progress"] = max(0.0, min(1.0, done / total))

    def _note_download_progress(self, downloaded: int, total: int) -> None:
        with self._lock:
            # The first bytes of the model download end the install phase.
            if self._phase == INSTALLING_TRANSLATION_DEPS:
                self._phase = PREPARING_TRANSLATION
                self._notice = None
            self._download["downloaded"] = downloaded
            self._download["total"] = total

    def _note_segment(self, segment, audio_seconds: float | None) -> None:
        """Called by the transcriber as each segment lands."""
        with self._lock:
            if audio_seconds:
                self._active["audio_seconds"] = audio_seconds
                fraction = (segment.end or 0) / audio_seconds
                self._active["progress"] = max(0.0, min(1.0, fraction))
            text = (segment.text or "").strip()
            if text:
                words = f"{self._active['excerpt']} {text}".split()
                self._active["excerpt"] = " ".join(words[-EXCERPT_WORDS:])

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
            # Every route that changes the output directory ends up here, so
            # this is the single place that has to remember it. Without that,
            # the next launch reattaches to the default folder and its separate
            # queue, and a finished batch looks like unfinished work.
            remember_output_dir(self._output_dir)
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

    def prepare_translation(self, model_key: str) -> dict:
        """Download and convert a translation model, without running a job.

        This exists because the target-language menu is read from the converted
        model's vocabulary, and nothing used to convert a model except starting
        a job - which could not be started without first picking a target
        language. The menu could therefore never be filled. An explicit step
        also puts the multi-gigabyte download in the open, where the user
        chooses it, rather than hiding it inside Begin.

        Returns immediately; the work happens on a worker thread and is
        observed through `status()` like any other job.
        """
        from .config import TRANSLATION_MODELS

        if model_key not in TRANSLATION_MODELS:
            raise JobError(f"unknown translation model: {model_key}")

        with self._lock:
            if self.is_running():
                raise JobError("a job is already running")
            self._cancel.clear()
            self._state = RUNNING
            self._error = None
            self._notice = None
            self._current_file = None
            self._run = self._empty_run()
            self._active = self._empty_active()
            self._phase = PREPARING_TRANSLATION
            self._download = self._empty_download()
            self._download["model"] = model_key
            self._download["expected_bytes"] = TRANSLATION_MODELS[model_key][
                "download_bytes"
            ]
            self._started_at = time.time()
            self._finished_at = None
            self._thread = threading.Thread(
                target=self._prepare_translation,
                args=(model_key,),
                name="translation-prepare",
                daemon=False,
            )
            self._thread.start()
            return self.status(include_files=False)

    def _prepare_translation(self, model_key: str) -> None:
        try:
            translator = self._translator_factory(
                model_key,
                device="cpu",
                on_download_progress=self._note_download_progress,
            )
            # Convert only. Loading it onto a device here would take VRAM for a
            # model nobody has asked to run yet.
            prepare = getattr(translator, "prepare", None)
            if callable(prepare):
                if _accepts(prepare, "on_line"):
                    prepare(on_line=self._note_install_line)
                else:
                    prepare()
            else:  # pragma: no cover - the real Translator always has prepare
                translator.load()
        except Exception as exc:
            log.exception("could not prepare the translation model")
            with self._lock:
                self._state = ERROR
                self._error = f"could not prepare the translation model: {exc}"
                self._finished_at = time.time()
                self._phase = None
            return

        with self._lock:
            self._state = COMPLETED
            self._finished_at = time.time()
            self._phase = None
            self._notice = f"{model_key} is ready to translate with."

    def prepare_speech(self, model_key: str) -> dict:
        """Install what speaking needs and download the weights, without a job.

        The same bargain as `prepare_translation`, and here for the same
        reason: the download is 3-4 GB and the torch that runs it is another
        2.5, so it belongs in the open where the user chooses it rather than
        hidden inside Begin.

        Returns immediately; the work happens on a worker thread and is
        observed through `status()` like any other job.
        """
        from .config import SPEECH_MODELS

        if model_key not in SPEECH_MODELS:
            raise JobError(f"unknown speech model: {model_key}")

        with self._lock:
            if self.is_running():
                raise JobError("a job is already running")
            self._cancel.clear()
            self._state = RUNNING
            self._error = None
            self._notice = None
            self._current_file = None
            self._run = self._empty_run()
            self._active = self._empty_active()
            self._phase = PREPARING_SPEECH
            self._download = self._empty_download()
            self._download["model"] = model_key
            self._download["expected_bytes"] = SPEECH_MODELS[model_key][
                "download_bytes"
            ]
            self._started_at = time.time()
            self._finished_at = None
            self._thread = threading.Thread(
                target=self._prepare_speech,
                args=(model_key,),
                name="speech-prepare",
                daemon=False,
            )
            self._thread.start()
            return self.status(include_files=False)

    def _prepare_speech(self, model_key: str) -> None:
        try:
            speaker = self._speaker_factory(
                model_key,
                device="cpu",
                on_download_progress=self._note_download_progress,
            )
            # Download only. Loading it onto a device here would take VRAM for
            # a model nobody has asked to run yet.
            prepare = getattr(speaker, "prepare", None)
            if callable(prepare):
                if _accepts(prepare, "on_line"):
                    prepare(on_line=self._note_speech_install_line)
                else:
                    prepare()
            else:  # pragma: no cover - the real Speaker always has prepare
                speaker.load()
        except Exception as exc:
            log.exception("could not prepare the speech model")
            with self._lock:
                self._state = ERROR
                self._error = f"could not prepare the speech model: {exc}"
                self._finished_at = time.time()
                self._phase = None
            return

        # Said here rather than only at run time: this is the moment the user
        # finds out whether the GPU they have will actually be used.
        problem = None
        try:
            from .speech import torch_install_problem

            problem = torch_install_problem()
        except Exception:  # pragma: no cover - defensive
            log.debug("could not check the torch install", exc_info=True)

        ready = f"{model_key} is ready to read text aloud."
        with self._lock:
            self._state = COMPLETED
            self._finished_at = time.time()
            self._phase = None
            # Both, not one or the other. The model really is ready, and the
            # GPU really will not be used; saying only the second reads as a
            # failure, and saying only the first hides the reason a reading is
            # about to take twenty times as long as it should.
            self._notice = "\n\n".join([ready, problem]) if problem else ready

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
                # Pressing Begin must never make the queue you are looking at
                # disappear. Each output directory keeps its own history, but
                # files queued and not yet done are the ones being pointed at,
                # so they come along. Without this, starting a run against a
                # different output folder attached to that folder's own (empty)
                # queue and reported "nothing to transcribe" - with the files
                # gone from the screen.
                carried = (
                    self._store.unfinished_entries()
                    if self._store is not None
                    else []
                )
                self.attach(target_dir)
                taken = self._store.adopt(carried) if carried else 0
                if taken:
                    log.info(
                        "output directory changed; carried %d queued file(s) to %s",
                        taken,
                        self._output_dir,
                    )
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
            self._active = self._empty_active()
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

    def _note_speech_warnings(self, path, result) -> None:
        """Say once what Tertius silently changed about the text.

        A dropped paralinguistic tag or an emotion word read as an intensity is
        not recoverable from the audio afterwards, and the `.json` that records
        it is not a file anyone opens.
        """
        notes = (getattr(result, "speech", None) or {}).get("warnings") or []
        if not notes:
            return
        with self._lock:
            self._notice = f"{Path(path).name}: {notes[0]}" + (
                f" (+{len(notes) - 1} more, in the .json)" if len(notes) > 1 else ""
            )

    @staticmethod
    def _free_gpu_for_speech(*models) -> None:
        """Take the earlier stages off the GPU before the reading starts.

        Measured on the 6 GB card this was built on:

        | model                   | VRAM    |
        | whisper large-v3-turbo  | 2.23 GB |
        | m2m100-418M             | 0.27 GB |
        | chatterbox-multilingual | 3.22 GB |

        5.72 GB of models for a 6.44 GB card - of which a browser was already
        holding a gigabyte. Reported as "CUDA out of memory. Tried to allocate
        204.00 MiB" *after* the transcript and the translation had been written,
        which is the worst moment for it: the expensive work was done and the
        only thing missing was the thing the run was for.

        Holding all three at once was never necessary. Nothing transcribes while
        it reads aloud, and both Whisper and the translator reload themselves
        when the next file needs them - `WhisperTranscriber.model` and
        `Translator.translate` are both lazy. So this costs a model load per
        file on a queue, and buys a feature that otherwise cannot run at all on
        a small card.
        """
        freed = []
        for model in models:
            if model is None:
                continue
            if getattr(model, "active_device", None) != "cuda":
                continue
            unload = getattr(model, "unload", None)
            if callable(unload):
                unload()
                freed.append(type(model).__name__)
        if not freed:
            return
        try:
            import torch

            torch.cuda.empty_cache()
        except Exception:  # pragma: no cover - torch may not be installed
            log.debug("could not empty the CUDA cache", exc_info=True)
        log.info("freed the GPU for the reading: %s", ", ".join(freed))

    def _read_aloud(self, path, target_dir, speaker, result, translated, options):
        """Speak a finished transcript. The third stage.

        Two things are decided here rather than by the user, because in both
        cases something else already knows the answer and a hand-made choice
        can only disagree with it:

        **Which words.** The sentence-level translation, never the per-segment
        one. The `.srt` is translated segment by segment so its measured
        timings survive, and Whisper cuts segments for timing rather than
        meaning - so more than half of them are fragments, and the model
        renders them worse. A mistake in a file can be skimmed past; the same
        mistake read out loud cannot.

        **Which voice.** The recording being transcribed, sampled from its own
        densest stretch of speech, so a translation comes back in the voice of
        whoever was talking. A queue of different speakers therefore needs no
        settings at all, which one shared voice clip could never manage.
        """
        import shutil
        import tempfile

        from .speech import chunks_from_prose, speak_chunks, voice_for

        language = options.resolved_speech_language(getattr(result, "language", None))
        source = translated if translated is not None else result
        text = getattr(source, "prose", None)
        if not text:
            # No translation, or a translation that produced no prose: fall
            # back to the transcript's own words.
            text = " ".join(
                (seg.text or "").strip()
                for seg in getattr(source, "segments", None) or ()
                if (seg.text or "").strip()
            )
        if not text.strip():
            raise ValueError("there is nothing to read aloud")

        chunks = chunks_from_prose(text, speaker.model_key, options.speech_style)
        # `.spoken`, and it is not decoration. Without it the reading's `.srt`
        # is written to exactly the name the translation's `.srt` already has,
        # and silently replaces it - two different things that both legitimately
        # answer to "the Spanish subtitles for this file". The translation's
        # cues are timed against the original recording; the reading's are
        # timed against the audio that was just generated. Losing the first to
        # the second destroys the only cues that match the real speech.
        suffix = f".{language}.spoken"

        scratch = tempfile.mkdtemp(prefix="tertius-voice-")
        try:
            voice, temporary = voice_for(
                path, result, options.speech_voice, scratch
            )
            written, spoken = speak_chunks(
                chunks,
                speaker,
                language,
                target_dir,
                Path(path).stem,
                voice=voice,
                suffix=suffix,
                formats=[f for f in options.formats if f != "txt"],
                source=path,
                on_progress=self._note_speech_progress,
            )
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

        self._note_speech_warnings(path, spoken)
        return written

    # --------------------------------------------------------------- the work

    def _run_batch(self) -> None:
        store = self._store
        output_dir = self._output_dir
        options = self._options
        assert store is not None and output_dir is not None

        takes_progress = _accepts(self._transcriber_factory, "on_download_progress")
        # Test doubles stand in for these, and are not obliged to report progress
        # through a file; only offer the callback to something that asked for it.
        transcribe_watches = _accepts(self._transcribe_fn, "on_segment")
        translate_takes_sentence_pass = _accepts(self._translate_fn, "sentence_pass")
        translate_reports_progress = _accepts(self._translate_fn, "on_progress")
        align_watches = _accepts(self._align_fn, "on_segment")
        speak_reports_progress = _accepts(self._speak_fn, "on_progress")
        text_source_reports_progress = _accepts(self._text_source_fn, "on_progress")
        translate_takes_for_speech = _accepts(self._translate_fn, "for_speech")
        transcriber = (
            self._transcriber_factory(
                options, on_download_progress=self._note_download_progress
            )
            if takes_progress
            else self._transcriber_factory(options)
        )

        # A queue of nothing but `.txt` sources has no audio to decode, so
        # loading Whisper would download gigabytes to sit idle - and would fail
        # the whole job on a machine with a broken GPU that was never going to
        # be asked to do anything.
        needs_whisper = any(
            (store.get(path) or {}).get("mode") not in (MODE_TEXT, MODE_SKIP)
            for path in store.pending_files()
        )
        # Reading aloud is a stage now, so this is simply whether the stage is
        # switched on - it applies to a transcript just as it does to a text
        # file, which is the whole point of the change.
        needs_speech = bool(options.speak) and any(
            (store.get(path) or {}).get("mode") != MODE_SKIP
            for path in store.pending_files()
        )
        warmup = getattr(transcriber, "warmup", None) if needs_whisper else None
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

        translator = None
        if options.translate:
            # Loaded before the first file, not on demand. The first use may
            # download and convert several GB, and discovering that halfway
            # through a queue - after files have already been written without a
            # translation - is the failure this ordering exists to prevent.
            with self._lock:
                self._phase = PREPARING_TRANSLATION
                self._download = self._empty_download()
                self._download["model"] = options.translation_model
                from .config import TRANSLATION_MODELS

                entry = TRANSLATION_MODELS.get(options.translation_model) or {}
                self._download["expected_bytes"] = entry.get("download_bytes")
            try:
                translator = self._translator_factory(
                    options.translation_model,
                    device=options.device,
                    on_download_progress=self._note_download_progress,
                )
                load = getattr(translator, "load", None)
                if callable(load):
                    load()
            except Exception as exc:
                log.exception("translation model failed to load")
                with self._lock:
                    self._state = ERROR
                    self._error = f"translation is not available: {exc}"
                    self._finished_at = time.time()
                    self._phase = None
                return

        speaker = None
        if needs_speech:
            # Loaded before the first file for the same reason the translator
            # is: the first use may download 3-4 GB, and finding that out
            # halfway through a queue is the failure this ordering prevents.
            with self._lock:
                self._phase = PREPARING_SPEECH
                self._download = self._empty_download()
                self._download["model"] = options.speech_model
                from .config import SPEECH_MODELS

                entry = SPEECH_MODELS.get(options.speech_model) or {}
                self._download["expected_bytes"] = entry.get("download_bytes")
            try:
                speaker = self._speaker_factory(
                    options.speech_model,
                    device=options.device,
                    on_download_progress=self._note_download_progress,
                )
                load = getattr(speaker, "load", None)
                if callable(load):
                    load()
            except Exception as exc:
                log.exception("speech model failed to load")
                with self._lock:
                    self._state = ERROR
                    self._error = f"speaking is not available: {exc}"
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
            elif getattr(speaker, "gpu_fallback_reason", None):
                # Worth its own branch: the usual cause here is not a missing
                # GPU but a CPU-only torch sitting in front of a perfectly good
                # one, and that reason explains how to fix it.
                self._notice = (
                    "Speaking is running on the CPU, which is much slower. "
                    f"Reason: {speaker.gpu_fallback_reason}"
                )
            self._active_device = getattr(transcriber, "active_device", None)

        last_error: str | None = None
        repeated = 0
        translation_failures = 0
        speech_failures = 0

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
                # Mark the store first, then publish the current file: status
                # must never claim to be working on something the state file
                # has not caught up with yet.
                entry = store.mark_in_progress(path)
                with self._lock:
                    self._current_file = path
                    self._active = self._empty_active()
                    self._active["path"] = path
                    self._active["audio_seconds"] = (entry or {}).get("duration")
                log.info("transcribing %s", path)
                started = time.time()
                # Mirror the scanned folder's layout under the output directory,
                # so `A/talk.mp3` and `B/talk.mp3` do not collide on one name.
                subdir = (entry or {}).get("subdir") or ""
                target_dir = Path(output_dir) / subdir if subdir else output_dir
                mode = (entry or {}).get("mode") or MODE_TRANSCRIBE
                try:
                    if mode == MODE_TEXT:
                        # A text source: no audio to decode, and whichever of
                        # the two stages are on decide what happens to it.
                        if speaker is not None:
                            with self._lock:
                                self._phase = SPEAKING
                            outputs, result = self._text_source_fn(
                                path,
                                target_dir,
                                speaker,
                                translator=translator,
                                target_language=options.target_language,
                                language=options.resolved_speech_language(),
                                voice=options.speech_voice,
                                default_style=options.speech_style,
                                formats=options.formats,
                                **(
                                    {"on_progress": self._note_speech_progress}
                                    if text_source_reports_progress
                                    else {}
                                ),
                            )
                            self._note_speech_warnings(path, result)
                        elif translator is not None:
                            outputs, result = self._translate_text_fn(
                                path,
                                target_dir,
                                translator,
                                options.target_language,
                                options.formats,
                            )
                        else:
                            raise JobError(
                                "this file is text, and neither Translate nor "
                                "Read aloud is switched on - there is nothing "
                                "to do with it. Tick one, or remove it from "
                                "the queue"
                            )
                    elif mode == MODE_ALIGN:
                        outputs, result = self._align_fn(
                            transcriber,
                            path,
                            target_dir,
                            entry["reference_text"],
                            options.alignment_granularity,
                            **({"on_segment": self._note_segment} if align_watches else {}),
                        )
                    else:
                        outputs, result = self._transcribe_fn(
                            transcriber,
                            path,
                            target_dir,
                            **(
                                {"on_segment": self._note_segment}
                                if transcribe_watches
                                else {}
                            ),
                        )
                except Exception as exc:  # one bad file must not stop the batch
                    log.exception("failed: %s", path)
                    message = f"{type(exc).__name__}: {exc}"
                    store.mark_failed(path, message)
                    with self._lock:
                        self._run["failed"] += 1
                        self._run["processed"] += 1
                        self._active = self._empty_active()
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
                            self._active = self._empty_active()
                        return
                    continue

                translated = None
                if translator is not None and mode != MODE_TEXT:
                    # The transcript is already written and correct at this
                    # point. A translation that fails must therefore not fail
                    # the file: marking it failed would send a resume back to
                    # redo a transcription that was fine, which on a 40-minute
                    # recording is an hour thrown away for a tokenizer error.
                    # It is reported, and a run of them still stops the batch.
                    with self._lock:
                        self._phase = TRANSLATING
                        # Transcription left this at 100%; translating is a
                        # second journey through the same file, not a
                        # continuation of the first.
                        self._active["progress"] = 0.0
                    try:
                        translated_outputs, translated = self._translate_fn(
                            result,
                            path,
                            target_dir,
                            options.formats,
                            translator,
                            options.target_language,
                            **(
                                {"sentence_pass": options.translate_sentences}
                                if translate_takes_sentence_pass
                                else {}
                            ),
                            **(
                                {"for_speech": True}
                                if options.speak and translate_takes_for_speech
                                else {}
                            ),
                            **(
                                {"on_progress": self._note_translation_progress}
                                if translate_reports_progress
                                else {}
                            ),
                        )
                        outputs = list(outputs) + list(translated_outputs)
                        translation_failures = 0
                    except Exception as exc:
                        translation_failures += 1
                        message = f"{type(exc).__name__}: {exc}"
                        log.exception("could not translate %s", path)
                        with self._lock:
                            self._notice = (
                                f"{Path(path).name} was transcribed, but could "
                                f"not be translated: {message}"
                            )
                        if translation_failures >= REPEATED_FAILURE_LIMIT:
                            log.error(
                                "%d translations in a row failed - stopping",
                                translation_failures,
                            )
                            store.mark_done(
                                path,
                                outputs=outputs,
                                language=getattr(result, "language", None),
                                duration=getattr(result, "duration", None),
                                words=sum(
                                    len((seg.text or "").split())
                                    for seg in getattr(result, "segments", None) or ()
                                ),
                            )
                            with self._lock:
                                self._state = ERROR
                                self._error = (
                                    f"{translation_failures} files in a row were "
                                    "transcribed but could not be translated, so "
                                    "the batch was stopped. The transcripts "
                                    "written so far are complete.\n\n"
                                    + message
                                )
                                self._run["completed"] += 1
                                self._run["processed"] += 1
                                self._finished_at = time.time()
                                self._current_file = None
                                self._phase = None
                                self._active = self._empty_active()
                            return
                    with self._lock:
                        self._phase = TRANSCRIBING

                if speaker is not None and mode != MODE_TEXT:
                    # The third stage. Like translation before it, a failure
                    # here must not fail the file: the transcript and the
                    # translation are already written and correct, and marking
                    # it failed would send a resume back to redo an hour of
                    # transcription over a voice model that would not load.
                    with self._lock:
                        self._phase = SPEAKING
                        self._active["progress"] = 0.0
                    try:
                        # Three models do not fit on a small card. Nothing
                        # transcribes while it reads aloud, so the earlier
                        # stages give their VRAM back first.
                        self._free_gpu_for_speech(transcriber, translator)
                        spoken = self._read_aloud(
                            path, target_dir, speaker, result, translated, options
                        )
                        outputs = list(outputs) + list(spoken)
                        speech_failures = 0
                    except Exception as exc:
                        speech_failures += 1
                        message = f"{type(exc).__name__}: {exc}"
                        log.exception("could not read %s aloud", path)
                        if "out of memory" in message.lower():
                            # The raw message is four lines of allocator
                            # statistics and does not say what to do about it.
                            message = (
                                "the GPU ran out of memory. The voice model "
                                "needs about 3.2 GB to itself; close anything "
                                "else using the GPU (a browser can hold a "
                                "gigabyte), choose a smaller Whisper model, or "
                                "set Device to cpu for a slower run that always "
                                "fits.\n\n" + message
                            )
                        with self._lock:
                            self._notice = (
                                f"{Path(path).name} was transcribed, but could "
                                f"not be read aloud: {message}"
                            )
                        if speech_failures >= REPEATED_FAILURE_LIMIT:
                            log.error(
                                "%d readings in a row failed - stopping",
                                speech_failures,
                            )
                            with self._lock:
                                self._state = ERROR
                                self._error = (
                                    f"{speech_failures} files in a row were "
                                    "transcribed but could not be read aloud, "
                                    "so the batch was stopped. The transcripts "
                                    "written so far are complete.\n\n" + message
                                )
                    with self._lock:
                        self._phase = TRANSCRIBING

                segments = getattr(result, "segments", None) or ()
                store.mark_done(
                    path,
                    outputs=outputs,
                    language=getattr(result, "language", None),
                    duration=getattr(result, "duration", None),
                    words=sum(len((s.text or "").split()) for s in segments),
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
                    self._active = self._empty_active()
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("batch aborted")
            with self._lock:
                self._state = ERROR
                self._error = f"{type(exc).__name__}: {exc}"
                self._finished_at = time.time()
                self._current_file = None
                self._phase = None
                self._active = self._empty_active()
            return
        finally:
            for model in (transcriber, translator, speaker):
                unload = getattr(model, "unload", None)
                if callable(unload):
                    unload()

        with self._lock:
            self._current_file = None
            self._phase = None
            self._active = self._empty_active()
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
                "active": dict(self._active),
                "elapsed_seconds": (
                    round((self._finished_at or time.time()) - self._started_at, 1)
                    if self._started_at
                    else None
                ),
            }
        payload["force_stop_suggested"] = self.force_stop_is_the_only_way_out()
        if store is not None:
            snapshot = store.snapshot()
            payload["summary"] = snapshot["summary"]
            payload["reference_dir"] = snapshot.get("reference_dir")
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
