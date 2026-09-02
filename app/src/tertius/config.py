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

# Text that can be queued as a source in its own right, to be translated with
# no audio involved. Deliberately narrow: a `.txt` sitting beside an audio file
# is a *reference* to be timestamped, and only ever becomes a source when it is
# scanned as one.
TEXT_EXTENSIONS = frozenset({".txt"})

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
OUTPUT_FORMATS = ("txt", "srt", "json")

# Translation models, converted here from the original publisher's weights
# rather than pulled from someone's pre-converted upload.
#
# Every one of these is permissively licensed. NLLB-200 is the obvious choice
# on quality and is deliberately absent: it is CC-BY-NC-4.0, which would forbid
# commercial use to everyone Tertius is given to. That restriction is Meta's to
# set, and converting the weights ourselves would not have lifted it.
#
# `family` selects the adapter. The two families say "translate into Spanish"
# in completely different ways - see translate.py.
TRANSLATION_MODELS = {
    "m2m100-418M": {
        "repo": "facebook/m2m100_418M",
        "family": "m2m100",
        "license": "MIT",
        "download_bytes": 1_940_000_000,
        "languages": 100,
        "speed": "Fast",
        "quality": "Serviceable. The smallest here worth using.",
    },
    "m2m100-1.2B": {
        "repo": "facebook/m2m100_1.2B",
        "family": "m2m100",
        "license": "MIT",
        "download_bytes": 4_960_000_000,
        "languages": 100,
        "speed": "Moderate",
        "quality": "Clearly better than 418M.",
    },
    "madlad400-3B": {
        "repo": "google/madlad400-3b-mt",
        "family": "t5",
        "license": "Apache-2.0",
        "download_bytes": 11_780_000_000,
        "languages": 400,
        "speed": "Slow",
        "quality": "Best here, and much the widest language coverage.",
    },
}

TRANSLATION_MODEL_SIZES = tuple(TRANSLATION_MODELS)
DEFAULT_TRANSLATION_MODEL = "m2m100-418M"

# The files each family needs in order to convert. Named explicitly so a
# download never drags in the duplicate TensorFlow, Flax, Rust and GGUF copies
# the Hub also carries - on madlad400-3b-mt those alone would add ~4 GB to an
# already large fetch.
TRANSLATION_FILE_PATTERNS = {
    "m2m100": [
        "pytorch_model.bin",
        "sentencepiece.bpe.model",
        "vocab.json",
        "config.json",
        "generation_config.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
    ],
    "t5": [
        "model.safetensors",
        "spiece.model",
        "tokenizer.json",
        "config.json",
        "generation_config.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "added_tokens.json",
    ],
}

# The `.json` output carries this so a reader can tell what it is holding. Two
# different shapes are written - a fresh transcription's segments and supplied
# text's chunks - and neither used to say which it was or that it might change.
# Bump it whenever an existing key is renamed, removed, or changes meaning;
# adding a new key does not need a bump, since a reader keyed on the old ones
# still works. Lives here rather than in either renderer so the two cannot
# drift apart silently, which is the failure this exists to prevent.
JSON_SHAPE_VERSION = 1
TRANSCRIPTION_SHAPE = "transcription"
ALIGNMENT_SHAPE = "alignment"
# A translated transcript is segments like a transcription, but the text is not
# what was said - it is a machine's rendering of it into another language. A
# reader that treats the two alike would quote a translation as a quotation.
TRANSLATION_SHAPE = "translation"

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


def translation_language_choices(model_key: str) -> tuple[str, ...]:
    """Codes the chosen translation model will accept as a target, sorted.

    Read from the converted model's own vocabulary, for the same reason the
    Whisper menu is read from Whisper's: a hand-written table goes stale, and a
    menu that offers a code the model rejects fails the job rather than the
    click. Empty until the model has been converted - nothing can be promised
    about a model that is not on disk yet, and the UI says so rather than
    guessing.
    """
    from .translate import supported_target_languages

    return supported_target_languages(model_key)


@dataclass
class TranscriptionOptions:
    """Per-job transcription settings, exposed in the UI."""

    model_size: str = "large-v3-turbo"
    device: str = "auto"
    compute_type: str = "default"
    language: str | None = None  # None => auto-detect
    beam_size: int = 5
    vad_filter: bool = True
    # faster-whisper defaults this to True: each 30s window is prompted with the
    # previous window's text. When a window comes back unpunctuated, that becomes
    # the prompt, and the model keeps being told that is the house style - it
    # never recovers. Measured on a 38-minute talk: punctuation stopped at 14:45
    # and the remaining 23 minutes arrived as 2,197 one-word segments. Off by
    # default; the cost is consistency of rare proper nouns across a long file,
    # which is a far smaller loss than an unreadable transcript.
    condition_on_previous_text: bool = False
    formats: list[str] = field(default_factory=lambda: ["txt", "srt"])
    # Timestamp text you supply instead of writing a fresh transcript.
    use_reference_text: bool = False
    alignment_granularity: str = "auto"
    # Translate the finished transcript into another language. A post-step, so
    # it applies equally to a fresh transcription and to timestamped supplied
    # text; the source-language files are always written too, and the
    # translation lands beside them as `talk.<target>.txt`.
    translate: bool = False
    translation_model: str = DEFAULT_TRANSLATION_MODEL
    target_language: str | None = None
    # Translate the `.txt` as whole sentences rather than as the timing-cut
    # segments Whisper produced. Measured on a 38-minute talk: 71% of segments
    # begin mid-sentence and 54% are fragments at both ends, and translating
    # those one at a time gave a `.txt` of 116 run-on lines where the English
    # had 204 sentences. With this on it comes back at 206.
    #
    # On by default because an unreadable transcript is the thing `.txt` exists
    # to avoid. It costs a second pass over the whole file - measured at 221s
    # against 12s for the segment pass, so a 64-second run becomes about 285 -
    # and it changes nothing about the `.srt`, whose timings need segments.
    translate_sentences: bool = True

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
        if self.translation_model not in TRANSLATION_MODELS:
            raise ValueError(
                f"unknown translation model: {self.translation_model!r} "
                f"(expected one of: {', '.join(TRANSLATION_MODEL_SIZES)})"
            )
        if isinstance(self.target_language, str):
            self.target_language = self.target_language.strip() or None
        if self.translate and not self.target_language:
            # Rejected up front rather than per file: the alternative is a whole
            # batch failing one file at a time, which is the shape of the
            # language check above and exists for the same reason.
            raise ValueError(
                "a target language is required to translate - pick one from the "
                "Translate into menu"
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
    """Where transcripts land when the user does not say otherwise.

    Anchored to where Tertius is installed, not to the current directory. The
    launcher used to pass `--output-dir` on every start, which hid the fact that
    this fallback depended on the shell's working directory: start the server
    from anywhere else and it would quietly attach to a different queue.
    """
    env = os.environ.get("TERTIUS_OUTPUT_DIR")
    if env:
        return Path(env).expanduser().resolve()
    # This file is app/src/tertius/config.py; transcripts/ sits beside app/.
    return (Path(__file__).resolve().parents[3] / "transcripts").resolve()


def is_media_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS


def is_text_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in TEXT_EXTENSIONS


SOURCE_KINDS = ("media", "text")


def scan_directory(
    directory: Path, recursive: bool = True, kind: str = "media"
) -> list[Path]:
    """Return source files in `directory`, sorted, ignoring our own scratch dirs.

    `kind="text"` looks for `.txt` to be translated on its own, with no audio.
    It is a separate scan rather than an extra extension in the media list
    because the same `.txt` means two different things depending on why it was
    picked up: found beside an audio file it is reference text to be
    timestamped, and scanning for both at once would make that ambiguous.
    """
    if kind not in SOURCE_KINDS:
        raise ValueError(f"unknown source kind: {kind!r}")
    directory = Path(directory).expanduser()
    if not directory.is_dir():
        raise NotADirectoryError(f"not a directory: {directory}")
    walker = directory.rglob("*") if recursive else directory.glob("*")
    matches = is_text_file if kind == "text" else is_media_file
    found = [
        p
        for p in walker
        if matches(p) and UPLOAD_DIRNAME not in p.parts
    ]
    return sorted(found, key=lambda p: str(p).lower())
