"""faster-whisper wrapper: model loading, transcription, output writing."""

from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .alignment import split_sentences
from .config import (
    JSON_SHAPE_VERSION,
    SPEECH_SHAPE,
    TRANSCRIPTION_SHAPE,
    TRANSLATION_SHAPE,
    TranscriptionOptions,
)

log = logging.getLogger(__name__)

# Mirrors faster_whisper.utils.download_model so we fetch exactly the same files.
# We call snapshot_download ourselves only because download_model hard-codes
# tqdm_class=disabled_tqdm, which throws progress away.
MODEL_FILE_PATTERNS = [
    "config.json",
    "preprocessor_config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.*",
]


@dataclass
class Segment:
    """Minimal segment shape; faster-whisper's own segments are duck-compatible."""

    start: float
    end: float
    text: str


@dataclass
class TimedWord:
    """One word with its timing - what aligning supplied text needs."""

    word: str
    start: float
    end: float


@dataclass
class TranscriptionResult:
    segments: list[Segment]
    language: str | None = None
    duration: float | None = None
    words: list[TimedWord] = field(default_factory=list)
    alignment: dict | None = None  # set when supplied text was timestamped
    # Set when this result *is* a translation: which model produced it, out of
    # what language, into what. Written into the `.json` so a translated file
    # can never be mistaken for a transcript of what was actually said.
    translation: dict | None = None
    # Set when this result is a *reading* rather than a transcript: text
    # that was turned into audio, and the timings of the audio that came
    # out. The one case here where a cue cannot have drifted from its
    # recording, both having been made in the same pass.
    speech: dict | None = None


def format_timestamp(seconds: float, separator: str = ",") -> str:
    """SRT timestamp: HH:MM:SS,mmm."""
    if seconds is None or seconds < 0:
        seconds = 0.0
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def segments_to_txt(segments: Sequence[Segment]) -> str:
    """The transcript, one sentence per line.

    Whisper's segments are cut for timing, not for reading: they run on, break
    mid-sentence, and sometimes carry three sentences at once. Joining them back
    into one block and re-splitting on sentence ends gives something you can
    actually read and diff, without changing a single word.

    The `.srt` is deliberately not treated this way - its lines are timing units
    and have to stay matched to their cues.
    """
    text = " ".join(s.text.strip() for s in segments if s.text and s.text.strip())
    if not text:
        return ""
    lines = split_sentences(text)
    return "\n".join(lines) + "\n" if lines else ""


def segments_to_srt(segments: Sequence[Segment]) -> str:
    blocks = []
    index = 1
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        blocks.append(
            f"{index}\n"
            f"{format_timestamp(seg.start)} --> {format_timestamp(seg.end)}\n"
            f"{text}\n"
        )
        index += 1
    return "\n".join(blocks)


def _shape_of(result: TranscriptionResult) -> str:
    """What kind of thing this `.json` describes.

    Checked in the order of how badly a reader would be misled by getting
    it wrong. A reading is the strongest claim of the three - those words
    were never said by anybody - so it wins over a translation, which in
    turn wins over a plain transcript. (Timestamped supplied text writes
    its own `.json` in alignment.py and never comes through here.)
    """
    if result.speech:
        return SPEECH_SHAPE
    if result.translation:
        return TRANSLATION_SHAPE
    return TRANSCRIPTION_SHAPE


def result_to_json(result: TranscriptionResult, source: Path) -> str:
    """The transcript as data: every segment with its timings, plus what is known.

    For feeding another tool rather than for reading - a search index, a player
    that wants to seek to a phrase, a diff between two runs. Times are seconds
    as floats, which is what everything downstream wants; the `.srt` already
    covers the HH:MM:SS,mmm case.

    Only what was actually measured goes in. `language` is null when the model
    did not report one rather than being guessed at, and `duration` is absent
    for the same reason.

    `version` and `kind` come first so a reader knows what it has before it
    reads any of it. `kind` matters because timestamped supplied text writes a
    genuinely different shape - chunks, not segments - and the file extension
    alone cannot tell the two apart. A translation is a third kind: the same
    segment shape as a transcription, but the words are a machine's rendering
    rather than what was said, and a reader must not quote it as speech.
    """
    payload = {
        "version": JSON_SHAPE_VERSION,
        "kind": _shape_of(result),
        "source": source.name,
        "language": result.language,
        "duration": result.duration,
        "segments": [
            {
                "id": index,
                "start": round(segment.start, 3),
                "end": round(segment.end, 3),
                "text": segment.text.strip(),
            }
            for index, segment in enumerate(result.segments)
            if segment.text and segment.text.strip()
        ],
    }
    if result.translation:
        # Which model, and which way. Without it a translated `.json` cannot
        # be told from a transcript of speech already in that language.
        payload["translation"] = dict(result.translation)
    if result.speech:
        # Which model read it, in what voice, and what the style tags did.
        # The warnings in here are the record of what Tertius changed about
        # the text before speaking it, which cannot be recovered from the
        # audio afterwards.
        payload["speech"] = dict(result.speech)
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


# Every renderer takes (result, source) so the JSON one can name its file and
# carry the language; the text ones simply ignore what they do not need.
RENDERERS = {
    "txt": lambda result, source: segments_to_txt(result.segments),
    "srt": lambda result, source: segments_to_srt(result.segments),
    "json": result_to_json,
}


def safe_output_path(
    output_dir: Path, stem: str, fmt: str, suffix: str = ""
) -> Path:
    """Where a transcript goes, never on top of one of Tertius's own files.

    Adding `.json` as an output format made this reachable: a recording called
    `transcription_state.mp3` would otherwise write its transcript straight over
    the queue's state file, part-way through the very run that is using it.
    Same shape as the existing guard against overwriting supplied text.
    """
    from .config import LOG_FILENAME, STATE_FILENAME

    reserved = {STATE_FILENAME.lower(), LOG_FILENAME.lower()}
    target = output_dir / f"{stem}{suffix}.{fmt}"
    if target.name.lower() in reserved:
        target = output_dir / f"{stem}{suffix}.transcript.{fmt}"
        log.warning(
            "a transcript would have overwritten Tertius's own %s; writing %s",
            f"{stem}.{fmt}",
            target.name,
        )
    return target


def write_atomically(target: Path, body: str) -> str:
    """Write via a temp name then replace.

    An interrupted write must never leave a truncated transcript that a later
    run would mistake for finished work. Shared so that everything writing an
    output does it the same way.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".partial")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(target)
    return str(target)


def write_outputs(
    source: Path,
    result: TranscriptionResult,
    output_dir: Path,
    formats: Iterable[str],
    suffix: str = "",
) -> list[str]:
    """Write one transcript per format, named after the source file.

    Writes to a temp name then replaces, so an interrupted write never leaves a
    truncated transcript that a later run would mistake for finished work.

    `suffix` goes between the stem and the extension, which is how a
    translation lands beside its transcript as `talk.es.txt` rather than on
    top of it.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for fmt in formats:
        render = RENDERERS[fmt]
        target = safe_output_path(output_dir, source.stem, fmt, suffix)
        written.append(write_atomically(target, render(result, source)))
    return written


def resolve_repo_id(size_or_id: str) -> str:
    """Model size (`large-v3-turbo`) or an explicit repo id -> repo id."""
    if "/" in size_or_id:
        return size_or_id
    from faster_whisper.utils import _MODELS

    repo_id = _MODELS.get(size_or_id)
    if repo_id is None:
        raise ValueError(
            f"unknown model {size_or_id!r}; expected one of: {', '.join(_MODELS)}"
        )
    return repo_id


def _progress_tqdm_class(on_progress: Callable[[int, int], None]):
    """A tqdm subclass that reports overall byte progress for a model download.

    huggingface_hub's bars are messier than they look, and the details matter:

    * A non-byte "Fetching N files" bar exists and must never be counted.
    * Some bars have no total at all (an open-ended "Downloading bytes" counter).
    * A bar's ``total`` can be set and then *grow* after construction, so it has
      to be read live rather than captured in ``__init__``.

    So: aggregate over the bars that currently have a total, reading ``n`` and
    ``total`` fresh each time. When none do yet, report bytes with a zero total
    and let the UI say "starting" rather than invent a percentage.
    """
    from tqdm.auto import tqdm as base_tqdm

    bars: list = []
    lock = threading.Lock()

    def report():
        with lock:
            tracked = list(bars)
        with_total = [b for b in tracked if (getattr(b, "total", 0) or 0) > 0]
        if with_total:
            total = sum(b.total for b in with_total)
            done = sum(min(b.n or 0, b.total) for b in with_total)
        else:
            total = 0
            done = sum(b.n or 0 for b in tracked)
        on_progress(done, total)

    class ProgressTqdm(base_tqdm):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._counts_bytes = kwargs.get("unit") == "B"
            if self._counts_bytes:
                with lock:
                    bars.append(self)
                report()

        def update(self, n=1):
            result = super().update(n)
            if self._counts_bytes:
                report()
            return result

    return ProgressTqdm


def is_model_cached(size_or_id: str) -> bool:
    """True if the model is already on disk (no network needed)."""
    from huggingface_hub import snapshot_download

    try:
        snapshot_download(
            resolve_repo_id(size_or_id),
            allow_patterns=MODEL_FILE_PATTERNS,
            local_files_only=True,
        )
        return True
    except Exception:
        return False


def ensure_model_downloaded(
    size_or_id: str, on_progress: Callable[[int, int], None] | None = None
) -> str:
    """Return a local path for the model, downloading it if needed.

    Reports (bytes_done, bytes_total) while downloading. Returns instantly when
    the model is already cached.
    """
    from huggingface_hub import snapshot_download

    kwargs = {"allow_patterns": MODEL_FILE_PATTERNS}
    if on_progress is not None:
        kwargs["tqdm_class"] = _progress_tqdm_class(on_progress)
    return snapshot_download(resolve_repo_id(size_or_id), **kwargs)


class GpuUnavailableError(RuntimeError):
    """The GPU was asked for but cannot actually run a model."""


def _venv_pip() -> str:
    """The pip command for this venv, written the way this platform writes it."""
    if sys.platform == "win32":
        return "app\\.venv\\Scripts\\pip"
    return "app/.venv/bin/pip"


CUDA_FIX_HINT = (
    "The NVIDIA driver reports a GPU, but CTranslate2 could not load the CUDA "
    "runtime libraries it needs. Install them into this venv with:\n"
    f"    {_venv_pip()} install nvidia-cublas-cu12 nvidia-cudnn-cu12\n"
    "(about 1.2 GB), or set Device to cpu."
)


# Once a CUDA operation has failed in this process, CTranslate2 can *deadlock*
# on the next one instead of raising - observed on a machine with an NVIDIA
# driver but no CUDA runtime libraries. So the first failure is remembered for
# the life of the process and the GPU is never touched again.
_cuda_failure: str | None = None
_cuda_failure_lock = threading.Lock()


def cuda_known_broken() -> str | None:
    with _cuda_failure_lock:
        return _cuda_failure


def mark_cuda_broken(reason: str) -> None:
    global _cuda_failure
    with _cuda_failure_lock:
        if _cuda_failure is None:
            _cuda_failure = reason
            log.warning(
                "CUDA is unusable in this process; every later job will use the "
                "CPU without retrying the GPU (a retry can hang)"
            )


def reset_cuda_state() -> None:
    """Test hook - forget that CUDA failed."""
    global _cuda_failure
    with _cuda_failure_lock:
        _cuda_failure = None


def nvidia_library_dirs() -> list[Path]:
    """Where `pip install nvidia-cublas-cu12` puts its libraries, if installed.

    The wheels use a different subfolder per platform - `nvidia/*/bin` on
    Windows, `nvidia/*/lib` on Linux - so both are checked rather than guessed
    at from the running platform.
    """
    try:
        import nvidia
    except ImportError:
        return []
    return [
        library_dir
        for root in getattr(nvidia, "__path__", [])
        for pattern in ("*/bin", "*/lib")
        for library_dir in sorted(Path(root).glob(pattern))
        if library_dir.is_dir()
    ]


def _register_windows(directories: list[Path]) -> list[str]:
    """Prepend the NVIDIA folders to PATH so a plain LoadLibrary finds them.

    `os.add_dll_directory` alone is not enough: it only affects loads that opt
    into LOAD_LIBRARY_SEARCH_USER_DIRS, and CTranslate2 loads cuBLAS with a
    plain LoadLibrary, which uses the standard search order - and that includes
    PATH. Verified the hard way.
    """
    added = []
    for binary_dir in directories:
        text = str(binary_dir)
        try:
            os.add_dll_directory(text)  # helps anything that does opt in
        except OSError:  # pragma: no cover - path vanished
            pass
        if text not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = text + os.pathsep + os.environ.get("PATH", "")
        added.append(text)
    return added


def _register_linux(directories: list[Path]) -> list[str]:
    """Load the NVIDIA shared objects into the process, globally.

    The Windows trick has no Linux equivalent: the dynamic loader reads
    LD_LIBRARY_PATH once at exec, so setting it from inside a running process
    changes nothing. What does work is opening each library with RTLD_GLOBAL,
    which puts its symbols in the global namespace where CTranslate2's own
    dlopen of cuBLAS/cuDNN will resolve against them.

    Order matters: cuDNN needs cuBLAS already loaded, so the sort puts `cublas`
    before `cudnn`. Failures are logged and skipped - a library that will not
    load here would have failed at first encode anyway, and the `auto` device
    proves the GPU with a real transcription before trusting it.
    """
    added = []
    for library_dir in sorted(directories, key=lambda p: "cudnn" in str(p)):
        for library in sorted(library_dir.glob("lib*.so*")):
            try:
                ctypes.CDLL(str(library), mode=ctypes.RTLD_GLOBAL)
            except OSError as exc:
                log.debug("could not preload %s: %s", library.name, exc)
                continue
            added.append(str(library))
    return added


def register_cuda_dll_directories() -> list[str]:
    """Make the pip-installed NVIDIA libraries findable by CTranslate2.

    `pip install nvidia-cublas-cu12` drops its libraries inside site-packages,
    which neither platform's loader searches on its own - so they end up
    installed and still "not found". The mechanism that fixes that differs by
    platform; see the two helpers.

    macOS never has any of this: there is no CUDA on Apple hardware.
    """
    directories = nvidia_library_dirs()
    if not directories:
        return []

    # Keyed off sys.platform rather than os.name: pathlib picks its flavour from
    # os.name, so anything that stubs os.name to exercise the other branch stops
    # Path working underneath it.
    if sys.platform == "win32":
        added = _register_windows(directories)
        if added:
            log.info("put %d NVIDIA library folder(s) on PATH", len(added))
        return added

    if sys.platform.startswith("linux"):
        added = _register_linux(directories)
        if added:
            log.info("preloaded %d NVIDIA shared object(s)", len(added))
        return added

    return []


class WhisperTranscriber:
    """Lazily loads a faster-whisper model and reuses it across the batch."""

    def __init__(
        self,
        options: TranscriptionOptions,
        on_download_progress: Callable[[int, int], None] | None = None,
    ):
        self.options = options
        self.on_download_progress = on_download_progress
        self._model = None
        self.active_device: str | None = None
        self.gpu_fallback_reason: str | None = None

    def _build(self, device: str):
        # Imported here so the app, its tests, and the UI all work on a machine
        # where the (heavy) model stack is not installed yet.
        from faster_whisper import WhisperModel

        kwargs = {"device": device}
        compute_type = self.options.resolved_compute_type()
        if compute_type:
            kwargs["compute_type"] = compute_type

        # Resolve to a local directory ourselves so the download is visible in
        # the UI; WhisperModel accepts a path just as happily as a size name.
        model_path = ensure_model_downloaded(
            self.options.model_size, self.on_download_progress
        )
        log.info(
            "loading model %s (device=%s, compute_type=%s)",
            self.options.model_size,
            device,
            compute_type or "auto",
        )
        return WhisperModel(model_path, **kwargs)

    @staticmethod
    def _prove_device_works(model) -> None:
        """Actually run the model once, on one second of silence.

        Loading a model on CUDA succeeds even when the CUDA *runtime* libraries
        are missing - the failure only surfaces on the first encode. Worse, once
        that has failed, the next call can wedge in native code where Python
        cannot interrupt it. So force the first encode here, on audio we made
        up, where a failure is cheap and catchable.
        """
        import numpy

        silence = numpy.zeros(16_000, dtype=numpy.float32)
        segments, _info = model.transcribe(
            silence, language="en", beam_size=1, vad_filter=False
        )
        for _ in segments:  # consuming the generator is what runs the encoder
            break

    def _load_model(self):
        register_cuda_dll_directories()
        wanted = self.options.device
        cuda_devices = 0
        try:
            import ctranslate2

            cuda_devices = ctranslate2.get_cuda_device_count()
        except Exception:  # pragma: no cover - ctranslate2 always present in practice
            pass

        target = "cuda" if wanted == "cuda" or (wanted == "auto" and cuda_devices) else "cpu"

        # Never retry a GPU that has already failed in this process: the retry
        # can hang forever instead of raising.
        already_broken = cuda_known_broken()
        if target == "cuda" and already_broken:
            if wanted == "cuda":
                raise GpuUnavailableError(f"{already_broken}\n\n{CUDA_FIX_HINT}")
            self.gpu_fallback_reason = already_broken
            target = "cpu"

        if target == "cuda":
            try:
                model = self._build("cuda")
                self._prove_device_works(model)
                self.active_device = "cuda"
                return model
            except Exception as exc:
                mark_cuda_broken(str(exc))
                if wanted == "cuda":
                    # They asked for the GPU explicitly; do not silently ignore it.
                    raise GpuUnavailableError(f"{exc}\n\n{CUDA_FIX_HINT}") from exc
                self.gpu_fallback_reason = str(exc)
                log.warning("GPU unusable (%s) - falling back to the CPU", exc)

        model = self._build("cpu")
        self.active_device = "cpu"
        return model

    @property
    def model(self):
        if self._model is None:
            self._model = self._load_model()
        return self._model

    def warmup(self) -> None:
        """Force the model to load *and run* now, so a broken device fails at
        job start rather than part-way through a queue."""
        _ = self.model

    def transcribe(
        self,
        path: str | Path,
        word_timestamps: bool = False,
        on_segment: Callable[[Segment, float | None], None] | None = None,
    ) -> TranscriptionResult:
        """Transcribe one file.

        `on_segment(segment, audio_seconds)` is called as each segment lands, so
        a caller can report progress through a long file. `audio_seconds` is the
        length faster-whisper measured, and is known before the first segment.
        """
        segments_iter, info = self.model.transcribe(
            str(path),
            language=self.options.language,
            beam_size=self.options.beam_size,
            vad_filter=self.options.vad_filter,
            condition_on_previous_text=self.options.condition_on_previous_text,
            word_timestamps=word_timestamps,
        )
        audio_seconds = getattr(info, "duration", None)
        # faster-whisper returns a generator; consuming it is what does the work.
        segments = []
        words: list[TimedWord] = []
        for segment in segments_iter:
            done = Segment(start=segment.start, end=segment.end, text=segment.text)
            segments.append(done)
            if on_segment is not None:
                # A reporting callback must never be able to fail a transcription.
                try:
                    on_segment(done, audio_seconds)
                except Exception:  # pragma: no cover - defensive
                    log.debug("segment callback failed", exc_info=True)
            for word in getattr(segment, "words", None) or ():
                words.append(
                    TimedWord(
                        word=word.word, start=word.start, end=word.end
                    )
                )
        return TranscriptionResult(
            segments=segments,
            language=getattr(info, "language", None),
            duration=audio_seconds,
            words=words,
        )

    def unload(self) -> None:
        self._model = None


def align_file(
    transcriber: WhisperTranscriber,
    source: str | Path,
    output_dir: str | Path,
    reference_path: str | Path,
    granularity: str = "auto",
    on_segment: Callable | None = None,
) -> tuple[list[str], TranscriptionResult]:
    """Timestamp the supplied text instead of writing a fresh transcript."""
    from .alignment import align, render_json, render_srt, render_timestamped_text

    source = Path(source)
    reference_path = Path(reference_path)
    if not source.is_file():
        raise FileNotFoundError(f"file not found: {source}")
    if not reference_path.is_file():
        raise FileNotFoundError(f"text file not found: {reference_path}")

    # utf-8-sig, not utf-8: Notepad and PowerShell both write a BOM, and read as
    # plain utf-8 it survives as an invisible character glued to the first word -
    # which then appears in the output and stops that chunk matching the audio.
    # Files without a BOM are unaffected.
    reference_text = reference_path.read_text(encoding="utf-8-sig", errors="replace")
    result = transcriber.transcribe(
        source, word_timestamps=True, on_segment=on_segment
    )
    if not result.words:
        raise RuntimeError(
            "the model returned no word timings, so the text cannot be aligned"
        )

    alignment = align(reference_text, result.words, granularity)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    renderers = {
        "txt": render_timestamped_text,
        "srt": render_srt,
        "json": render_json,
    }
    written: list[str] = []
    for fmt in transcriber.options.formats:
        render = renderers.get(fmt)
        if render is None:
            continue
        target = safe_output_path(output_dir, source.stem, fmt)
        # Never write over the very text we were given.
        if target.resolve() == reference_path.resolve():
            target = output_dir / f"{source.stem}.timestamped.{fmt}"
            log.warning(
                "output would overwrite the supplied text; writing %s instead",
                target.name,
            )
        tmp = target.with_name(target.name + ".partial")
        tmp.write_text(render(alignment), encoding="utf-8")
        tmp.replace(target)
        written.append(str(target))

    summary = alignment.summary()
    log.info(
        "aligned %s: %d chunk(s) by %s, %d timed, %d left untimed",
        source.name,
        summary["chunks"],
        summary["granularity"],
        summary["timed"],
        summary["unmatched"],
    )
    result.alignment = summary
    return written, result


def transcribe_file(
    transcriber: WhisperTranscriber,
    source: str | Path,
    output_dir: str | Path,
    on_segment: Callable | None = None,
) -> tuple[list[str], TranscriptionResult]:
    """Transcribe one file and write its transcripts. Raises on failure."""
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(f"file not found: {source}")
    result = transcriber.transcribe(source, on_segment=on_segment)
    outputs = write_outputs(
        source, result, Path(output_dir), transcriber.options.formats
    )
    return outputs, result
