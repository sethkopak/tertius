"""faster-whisper wrapper: model loading, transcription, output writing."""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .config import TranscriptionOptions

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
class TranscriptionResult:
    segments: list[Segment]
    language: str | None = None
    duration: float | None = None


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
    lines = [s.text.strip() for s in segments if s.text and s.text.strip()]
    return "\n".join(lines) + ("\n" if lines else "")


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


RENDERERS = {"txt": segments_to_txt, "srt": segments_to_srt}


def write_outputs(
    source: Path,
    result: TranscriptionResult,
    output_dir: Path,
    formats: Iterable[str],
) -> list[str]:
    """Write one transcript per format, named after the source file.

    Writes to a temp name then replaces, so an interrupted write never leaves a
    truncated transcript that a later run would mistake for finished work.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for fmt in formats:
        render = RENDERERS[fmt]
        target = output_dir / f"{source.stem}.{fmt}"
        tmp = target.with_name(target.name + ".partial")
        tmp.write_text(render(result.segments), encoding="utf-8")
        tmp.replace(target)
        written.append(str(target))
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


CUDA_FIX_HINT = (
    "The NVIDIA driver reports a GPU, but CTranslate2 could not load the CUDA "
    "runtime libraries it needs. Install them into this venv with:\n"
    "    .venv\\Scripts\\pip install nvidia-cublas-cu12 nvidia-cudnn-cu12\n"
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
    """Where `pip install nvidia-cublas-cu12` puts its DLLs, if installed."""
    try:
        import nvidia
    except ImportError:
        return []
    return [
        binary_dir
        for root in getattr(nvidia, "__path__", [])
        for binary_dir in sorted(Path(root).glob("*/bin"))
        if binary_dir.is_dir()
    ]


def register_cuda_dll_directories() -> list[str]:
    """Put the pip-installed NVIDIA DLLs where CTranslate2 will actually find them.

    `pip install nvidia-cublas-cu12` drops its DLLs in `site-packages/nvidia/*/bin`,
    which Windows does not search, so the libraries end up installed and still
    "not found".

    Prepending to PATH is what does the work here. `os.add_dll_directory` alone is
    not enough: it only affects loads that opt into LOAD_LIBRARY_SEARCH_USER_DIRS,
    and CTranslate2 loads cuBLAS with a plain LoadLibrary, which uses the standard
    search order - and that includes PATH. Verified the hard way.
    """
    if os.name != "nt":
        return []

    added = []
    for binary_dir in nvidia_library_dirs():
        text = str(binary_dir)
        try:
            os.add_dll_directory(text)  # helps anything that does opt in
        except OSError:  # pragma: no cover - path vanished
            pass
        if text not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = text + os.pathsep + os.environ.get("PATH", "")
        added.append(text)
    if added:
        log.info("put %d NVIDIA library folder(s) on PATH", len(added))
    return added


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

    def transcribe(self, path: str | Path) -> TranscriptionResult:
        segments_iter, info = self.model.transcribe(
            str(path),
            language=self.options.language,
            beam_size=self.options.beam_size,
            vad_filter=self.options.vad_filter,
        )
        # faster-whisper returns a generator; consuming it is what does the work.
        segments = [
            Segment(start=s.start, end=s.end, text=s.text) for s in segments_iter
        ]
        return TranscriptionResult(
            segments=segments,
            language=getattr(info, "language", None),
            duration=getattr(info, "duration", None),
        )

    def unload(self) -> None:
        self._model = None


def transcribe_file(
    transcriber: WhisperTranscriber,
    source: str | Path,
    output_dir: str | Path,
) -> tuple[list[str], TranscriptionResult]:
    """Transcribe one file and write its transcripts. Raises on failure."""
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(f"file not found: {source}")
    result = transcriber.transcribe(source)
    outputs = write_outputs(
        source, result, Path(output_dir), transcriber.options.formats
    )
    return outputs, result
