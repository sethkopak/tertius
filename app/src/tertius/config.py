"""Configuration objects and defaults."""

from __future__ import annotations

import functools
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Extensions faster-whisper can decode (it hands the file to av/ffmpeg, so this
# is a conservative subset of what actually works).
MEDIA_EXTENSIONS = frozenset(
    {
        ".mp3",
        ".wav",
        ".m4a",
        ".mp4",
        ".flac",
        ".ogg",
        ".opus",
        ".webm",
        ".mkv",
        ".mov",
        ".aac",
        ".wma",
        ".avi",
    }
)

# Names faster-whisper resolves itself (see faster_whisper.utils._MODELS).
# large-v3-turbo maps to mobiuslabsgmbh/faster-whisper-large-v3-turbo.
MODEL_SIZES = (
    "tiny",
    "base",
    "small",
    "medium",
    "large-v2",
    "large-v3",
    "large-v3-turbo",
)

# Names faster-whisper accepts that we do not offer, because two entries for one
# model just makes the list confusing. Still honoured if one arrives from an old
# state file or a direct API call.
MODEL_ALIASES = {"turbo": "large-v3-turbo", "large": "large-v3"}

# How finely supplied text is timestamped. "auto" picks paragraphs when the
# text has them and sentences otherwise.
GRANULARITIES = ("auto", "paragraph", "sentence")

DEVICES = ("auto", "cpu", "cuda")
COMPUTE_TYPES = ("default", "int8", "int8_float16", "float16", "float32")
OUTPUT_FORMATS = ("txt", "srt")

STATE_FILENAME = "transcription_state.json"
LOG_FILENAME = "tertius.log"
UPLOAD_DIRNAME = "_uploads"


# Shown in the Language menu when faster-whisper is not installed to tell us the
# real list. Every one of these is in Whisper's own set.
FALLBACK_LANGUAGE_CODES = (
    "ar", "de", "el", "en", "es", "fr", "he", "hi", "it", "ja",
    "ko", "la", "nl", "pl", "pt", "ru", "sw", "tr", "uk", "zh",
)


@functools.lru_cache(maxsize=1)
def known_language_codes() -> frozenset[str] | None:
    """The ~100 codes Whisper accepts, or None if faster-whisper isn't installed.

    Imported lazily and only when a language is actually specified, so the app
    still runs (and the tests still pass) without the model stack.
    """
    try:
        from faster_whisper.tokenizer import _LANGUAGE_CODES

        return frozenset(_LANGUAGE_CODES)
    except Exception:
        return None


def language_choices() -> tuple[str, ...]:
    """Codes to offer in the Language menu, sorted.

    Whisper's own list when faster-whisper can tell us, so the menu can never
    offer a code the model would reject.
    """
    codes = known_language_codes()
    return tuple(sorted(codes)) if codes else FALLBACK_LANGUAGE_CODES


@dataclass
class TranscriptionOptions:
    """Per-job transcription settings, exposed in the UI."""

    model_size: str = "large-v3-turbo"
    device: str = "auto"
    compute_type: str = "default"
    language: str | None = None  # None => auto-detect
    beam_size: int = 5
    vad_filter: bool = True
    formats: list[str] = field(default_factory=lambda: ["txt", "srt"])
    # Timestamp text you supply instead of writing a fresh transcript.
    use_reference_text: bool = False
    alignment_granularity: str = "auto"

    def __post_init__(self) -> None:
        self.model_size = MODEL_ALIASES.get(self.model_size, self.model_size)
        if self.model_size not in MODEL_SIZES:
            raise ValueError(f"unknown model size: {self.model_size!r}")
        if self.device not in DEVICES:
            raise ValueError(f"unknown device: {self.device!r}")
        if self.compute_type not in COMPUTE_TYPES:
            raise ValueError(f"unknown compute type: {self.compute_type!r}")
        if isinstance(self.language, str):
            self.language = self.language.strip().lower() or None
        if self.language is not None:
            # Checked here rather than at transcribe time: faster-whisper raises
            # on a bad code once per file, which would fail an entire batch one
            # file at a time instead of rejecting the job up front.
            codes = known_language_codes()
            if codes is not None and self.language not in codes:
                raise ValueError(
                    f"{self.language!r} is not a Whisper language code - use a "
                    "short code like en, es, fr, de, zh, ja (or leave it blank "
                    "to auto-detect)"
                )
        if self.alignment_granularity not in GRANULARITIES:
            raise ValueError(
                f"unknown timestamp granularity: {self.alignment_granularity!r} "
                f"(expected one of: {', '.join(GRANULARITIES)})"
            )
        if not self.formats:
            raise ValueError("at least one output format is required")
        bad = [f for f in self.formats if f not in OUTPUT_FORMATS]
        if bad:
            raise ValueError(f"unknown output format(s): {', '.join(bad)}")
        self.beam_size = int(self.beam_size)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "TranscriptionOptions":
        data = dict(data or {})
        known = {f for f in cls.__dataclass_fields__}  # noqa: SLF001 - dataclass API
        return cls(**{k: v for k, v in data.items() if k in known})

    def resolved_compute_type(self) -> str | None:
        """`default` means: let CTranslate2 pick for the device."""
        return None if self.compute_type == "default" else self.compute_type


def default_output_dir() -> Path:
    """Where transcripts land when the user does not say otherwise."""
    env = os.environ.get("TERTIUS_OUTPUT_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.cwd() / "transcripts").resolve()


def is_media_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS


def scan_directory(directory: Path, recursive: bool = True) -> list[Path]:
    """Return media files in `directory`, sorted, ignoring our own scratch dirs."""
    directory = Path(directory).expanduser()
    if not directory.is_dir():
        raise NotADirectoryError(f"not a directory: {directory}")
    walker = directory.rglob("*") if recursive else directory.glob("*")
    found = [
        p
        for p in walker
        if is_media_file(p) and UPLOAD_DIRNAME not in p.parts
    ]
    return sorted(found, key=lambda p: str(p).lower())
