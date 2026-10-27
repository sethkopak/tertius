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
    # The transcript as continuous prose, rejoined and re-split into sentences.
    # Set by the translator when a reading is going to follow, because the two
    # translations of a file are not equally good: the `.srt` is translated per
    # segment so its timings survive, and those segments are fragments more
    # than half the time. Speaking the fragment stream would read a mistake out
    # loud - "gloom" as *glume* - where the text version can at least be
    # skimmed past.
    prose: str | None = None


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


# Languages Whisper writes without punctuation unless shown some, and a line
# that shows it. Without one, Chinese came back as a run of short phrases with
# no 。 or , in it at all, so the whole transcript was a single "sentence" to
# everything downstream - the translator got 450 characters with no stops in
# them. Measured on 2026-10-19 with large-v3-turbo, 56 s of Chinese:
#
# - no hint: 35 segments, not one mark of punctuation.
# - `initial_prompt`: punctuated, but only in the first 30 s window. With
#   `condition_on_previous_text` off, which it is here for a reason (see
#   `TranscriptionOptions`), the prompt is dropped after the first window.
# - `hotwords`: punctuated in every window. faster-whisper puts hotwords into
#   every window's prompt whatever the conditioning setting is.
#
# The unhinted run also invented a line after the audio ended (a TV channel's
# credit); the hinted one did not. That is one run, so it is a note, not a
# claim.
#
# **The hint alone also dropped text.** Measured on 2026-10-21 over 20 Chinese
# readings of ten Manna files, with this app's settings: the bare sentence lost
# a whole scripture reference that the unhinted run kept (0829, twice in one
# reading; on the CPU, 1111 too), and misheard 5.5% / 4.3% of characters
# against 5.2% / 4.1% unhinted. The same sentence followed by the scripture
# vocabulary these readings use lost nothing the unhinted run kept, misheard
# 5.1% / 4.1%, and still punctuated every window. So that is the hint. The
# words are Bible vocabulary because that is what this app reads; outside it
# they are rare enough not to be heard where they were not said.
#
# **No Hebrew hint** (tried 2026-10-26/27). One gave Whisper's Hebrew full
# stops - 0120 had two without it, eight with - and back to English chrF 50.6
# to 52.6, but
# **any hint skipped speech**: 0723's second take lost three sentences that
# are in the audio, with `להלן משפטים בעברית. מן, הטקסט שוב, האיגרת, תהילים,
# פרק, פסוק.`, with the sentence alone, with the words alone and with just
# `פרק, פסוק.`, the same stretch every time; without a hint it was heard.
# Silently losing sentences costs more than the punctuation gains.
PUNCTUATION_HINTS = {
    "zh": "以下是普通话的句子。吗哪,众民,称颂,经文,诗篇,希伯来书,雅各书,帖撒罗尼迦后书。",
}


# **Speech Whisper jumps over.** faster-whisper decodes 30 s windows; when the
# model ends a window early, the next starts where the window ended, and the
# speech in between is never decoded. Measured on thirty Hebrew readings
# (2026-10-27): two clauses were lost that way, 26.0-30.0 s and 26.1-32.2 s,
# with VAD on or off, timestamps on or off. So every gap of more than
# REFILL_GAP_SECONDS between segments is decoded again on its own. A real
# recovery ends inside its gap; on silence Whisper writes a "thank you"
# (`תודה רבה.`, four times there) whose timestamps run a full 30 s past it,
# so a refilled segment is kept only if it ends within the gap. Hebrew
# then: 640 to 567 letters misheard of 16,512, nothing lost, nothing invented.
#
# **English too** (2026-10-27). Of 62 Manna recordings, Whisper lost the whole
# repeated verse in three (at 55-60 s, the end of its second window) and the
# opening title and verse in one; decoding the gaps again brought back all
# four, word for word against the book, and a skipped title. It also wrote
# `for.` and `19. 19.` - so a refill is kept only if it is REFILL_MIN_WORDS
# or more words. That also takes out Hebrew's `תודה רבה`; every real
# recovery in either language was four words or more.
#
# **Not Chinese.** The thirty Chinese readings went 2.0% to 2.8%: every gap
# decoded again came back invented, inside the gap and long - the YouTube
# outro (`请不吝点赞 订阅 转发...`), `语言语言语言...`. Other languages are
# unmeasured.
REFILL_LANGUAGES = frozenset({"he", "en"})
REFILL_MIN_WORDS = 3
REFILL_GAP_SECONDS = 1.5
REFILL_SLACK_SECONDS = 1.0

# **Segments far too long for their words.** The other way Whisper loses
# speech: a segment whose timestamps swallow what it does not write. Across
# all 375 English Manna recordings, scored against the book (2026-10-27),
# `The text again` ran 60.2-90.2 s in an 83.8 s file with the verse after it
# gone (0421, 0428), and opening segments of 13-18 s held one sentence, the
# title and verse before it gone (0513, 0725, 0730...). Reading runs at about
# READING_WORDS_PER_SECOND; 13 segments in the 375 files ran under
# SLOW_WORDS_PER_SECOND for SLOW_SEGMENT_SECONDS or more, every one in a file
# missing a verse or more. Decoding the segment's span again, and the parts
# before and after what its text accounts for, brought back the missing speech
# in 12 of the 13. The decode with the most words replaces the segment when it
# adds REFILL_MIN_WORDS or more. The line was first 1.0; three more openings
# lost their title and verse inside segments of 13.5-17 s at 1.2 words a
# second (0520, 0827, 1213), and at 1.3 all three came back, errors 7, 8, 9
# to 1, 3, 2. One other segment in the 375 files runs between 1.0 and 1.3
# (0608), and decoding it again changed nothing.
SLOW_SEGMENT_SECONDS = 6.0
SLOW_WORDS_PER_SECOND = 1.3
READING_WORDS_PER_SECOND = 2.5


# **What Whisper writes on the closing silence.** Eight of the 375 English
# Manna transcripts ended in a segment nobody said - `Thank you.` six times,
# `We'll be right back.`, `Here we go.` - each starting within the last
# second of the audio and stamped a full 30 s past its end, over audio at
# about a fiftieth of the speech's loudness (2026-10-27). One real closing
# segment also ran past the end (0719, 1.4 s), but it started 5.7 s before
# it. So a segment that starts within CLOSING_SECONDS of the end and runs
# more than REFILL_SLACK_SECONDS past it is dropped.
CLOSING_SECONDS = 1.5

# **A prompt for what is decoded again.** A stretch decoded on its own can
# come back all lowercase and unpunctuated - 0520's `manna for may 20th a
# peculiar people zealous of good works titus chapter 2 verse 14 a`, from
# 0.08 s, where from 0.10 s it was cased (2026-10-27): Whisper picks a style
# per decode. A punctuated prompt sets it, and every span tried came back
# cased; the prompt is not the reading's own text, because given the
# neighboring sentence Whisper left out whatever matched it. But a prompt can
# lose speech too: 0317's verse, decoded with it, came back as its citation
# alone stretched over the verse's 20 s, every time; without it, whole. So a
# stretch is decoded both ways and the one with more words kept, the
# prompted one on a tie.
REFILL_PROMPTS = {"en": "The following is a transcript, with punctuation."}


def _closing_filler(segment, duration) -> bool:
    return bool(duration) and (
        segment.start > duration - CLOSING_SECONDS
        and segment.end > duration + REFILL_SLACK_SECONDS
    )


def _repeats(text: str, of: str) -> float:
    """How much of `text`, by words, is words of `of`."""
    said = {w.strip(".,;:!?\"'").lower() for w in of.split()}
    words = [w.strip(".,;:!?\"'").lower() for w in text.split()]
    return sum(w in said for w in words) / len(words) if words else 1.0


def _slow(segments, duration):
    """Segments that run SLOW_SEGMENT_SECONDS or more at too few words a second."""
    out = []
    for segment in segments:
        end = min(segment.end, duration) if duration else segment.end
        span = end - segment.start
        if span >= SLOW_SEGMENT_SECONDS and len(segment.text.split()) / span < SLOW_WORDS_PER_SECOND:
            out.append(segment)
    return out


# **Only a gap with speech in it.** Decoded both ways, a silent pause can still
# come back as three invented words - 0412's 1.7 s after its citation, `Oh,
# my God.` and `That's the thing.` So a gap is decoded again only when
# SPEECH_SHARE of it is speech-loud: 0.1 s frames above a third of the
# file's speech level (its loudness at the 75th percentile). The seven real
# recoveries, English and Hebrew, were 46-70% speech-loud; the invented ones
# 0-37% (2026-10-27).
SPEECH_SHARE = 0.4
WHISPER_SAMPLE_RATE = 16_000


def _speech_loud(path, gaps) -> list[tuple[float, float]]:
    """The `gaps` with SPEECH_SHARE or more of their 0.1 s frames speech-loud."""
    import numpy
    from faster_whisper.audio import decode_audio

    audio = decode_audio(str(path), sampling_rate=WHISPER_SAMPLE_RATE)
    frame = WHISPER_SAMPLE_RATE // 10
    frames = audio[: len(audio) // frame * frame].reshape(-1, frame)
    if not len(frames):
        return []
    loud = numpy.sqrt((frames ** 2).mean(axis=1))
    level = numpy.percentile(loud, 75) * 0.3
    kept = []
    for start, end in gaps:
        stretch = loud[int(start * 10):int(end * 10)]
        if len(stretch) and (stretch > level).mean() >= SPEECH_SHARE:
            kept.append((start, end))
    return kept


def _gaps(segments, duration) -> list[tuple[float, float]]:
    """Stretches longer than REFILL_GAP_SECONDS with no segment in them."""
    out = []
    edge = 0.0
    for segment in sorted(segments, key=lambda s: s.start):
        if segment.start - edge > REFILL_GAP_SECONDS:
            out.append((edge, segment.start))
        edge = max(edge, segment.end)
    if duration and duration - edge > REFILL_GAP_SECONDS:
        out.append((edge, duration))
    return out


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
        def run(language: str | None, **extra):
            hint = PUNCTUATION_HINTS.get(language or "")
            return self.model.transcribe(
                str(path),
                language=language,
                beam_size=self.options.beam_size,
                vad_filter=self.options.vad_filter,
                condition_on_previous_text=self.options.condition_on_previous_text,
                word_timestamps=word_timestamps,
                **({"hotwords": hint} if hint else {}),
                **extra,
            )

        def again(language: str | None, a: float, b: float) -> list:
            """A stretch decoded on its own: the decode with more words that
            end inside it, prompted and not; the prompted one on a tie."""
            ways = [{}]
            if language in REFILL_PROMPTS:
                ways.insert(0, {"initial_prompt": REFILL_PROMPTS[language]})
            best: list = []
            for extra in ways:
                found, _ = run(language, clip_timestamps=[a, b], **extra)
                found = [f for f in found if f.end <= b + REFILL_SLACK_SECONDS]
                if sum(len(f.text.split()) for f in found) > sum(len(f.text.split()) for f in best):
                    best = found
            return best

        segments_iter, info = run(self.options.language)
        detected = getattr(info, "language", None)
        if self.options.language is None and detected in PUNCTUATION_HINTS:
            # The language is only known once faster-whisper has detected it,
            # and the hint has to be in the language. Detection happens inside
            # `transcribe`, before any decoding - the segments are a lazy
            # generator - so asking again costs the detection, not a pass.
            segments_iter, info = run(detected)
        audio_seconds = getattr(info, "duration", None)
        # faster-whisper returns a generator; consuming it is what does the work.
        segments = []
        words: list[TimedWord] = []

        def take(segment) -> None:
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

        for segment in segments_iter:
            take(segment)
        language = getattr(info, "language", None)
        gaps = _gaps(segments, audio_seconds) if language in REFILL_LANGUAGES else []
        if gaps:
            try:
                gaps = _speech_loud(path, gaps)
            except Exception:  # pragma: no cover - not knowing is not a reason to decode
                log.debug("could not measure the gaps", exc_info=True)
                gaps = []
        for start, end in gaps:
            try:
                for segment in again(language, start, end):
                    if len(segment.text.split()) >= REFILL_MIN_WORDS:
                        log.info("decoded %.1f-%.1f s again: %s", start, end, segment.text.strip())
                        take(segment)
            except Exception:  # pragma: no cover - a refill must never cost the transcript
                log.debug("could not decode a gap again", exc_info=True)
        slow = _slow(segments, audio_seconds) if language in REFILL_LANGUAGES else []
        for old in slow:
            try:
                start = old.start
                end = min(old.end, audio_seconds) if audio_seconds else old.end
                said = len(old.text.split()) / READING_WORDS_PER_SECOND
                # The whole span decoded again, or the part before what the
                # text accounts for, or the part after - the old text kept on
                # its side, said in the time it takes to say: an opening
                # segment swallowed the title and verse before it (0513), `The
                # text again` the verse after it (0421).
                kept_last = Segment(start=end - said, end=end, text=old.text)
                kept_first = Segment(start=start, end=start + said, text=old.text)
                best: list = []
                for a, b, keep in ((start, end, None), (start, end - said, kept_last),
                                   (start + said, end, kept_first)):
                    if b - a < REFILL_GAP_SECONDS:
                        continue
                    found = again(language, a, b)
                    if keep is not None:
                        # `said` is an estimate, so the old text may come
                        # back in what was decoded (0728, 0828). A piece
                        # mostly made of the old text's words is that.
                        found = [f for f in found if _repeats(f.text, old.text) < 0.6]
                        if not found:
                            continue
                        found = [*found, keep] if keep is kept_last else [keep, *found]
                    if sum(len(f.text.split()) for f in found) > sum(len(f.text.split()) for f in best):
                        best = found
                gained = sum(len(f.text.split()) for f in best) - len(old.text.split())
                if gained < REFILL_MIN_WORDS:
                    continue
                log.info("decoded %.1f-%.1f s again: %s", start, end,
                         " ".join(f.text.strip() for f in best))
                segments.remove(old)
                words[:] = [w for w in words if not (start <= w.start < end)]
                for segment in best:
                    take(segment)
            except Exception:  # pragma: no cover - a refill must never cost the transcript
                log.debug("could not decode a slow segment again", exc_info=True)
        for segment in [s for s in segments if _closing_filler(s, audio_seconds)]:
            log.info("dropped %.1f-%.1f s, past the end: %s",
                     segment.start, segment.end, segment.text.strip())
            segments.remove(segment)
            words[:] = [w for w in words if w.start < segment.start]
        segments.sort(key=lambda s: s.start)
        words.sort(key=lambda w: w.start)
        return TranscriptionResult(
            segments=segments,
            language=getattr(info, "language", None),
            duration=audio_seconds,
            words=words,
        )

    @property
    def loaded(self) -> bool:
        """Whether the model is in memory now, rather than due to load on use."""
        return self._model is not None

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
