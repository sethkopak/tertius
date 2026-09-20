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

# Speech synthesis - reading a text file aloud. Chatterbox, from Resemble AI.
#
# Chosen the same way the translation models were, and for the same reasons:
# the code is MIT, the weights are MIT, and none of the three repositories is
# gated on the Hub, so Tertius can fetch them without asking anyone to hold a
# Hugging Face account or accept a licence on a web page. That last point ruled
# out more capable options. IndexTTS-2 has native duration control, which is
# the thing dubbing actually wants, and ships under the bilibili Model Use
# License Agreement rather than a permissive licence; XTTS-v2 is CPML and
# forbids commercial use outright. Both would have put a restriction on
# everyone downstream that Tertius's own MIT licence does not.
#
# Unlike the translation models these are *not* converted here. CTranslate2
# cannot run them - they are a torch stack end to end - so the publisher's
# weights are loaded as published. That is a real difference in provenance from
# the translation path, and it is written down rather than glossed: what
# protects us here is that the repositories are Resemble AI's own, under the
# organisation that wrote the model, not an individual's re-upload.
#
# `baseline` is what this model calls ordinary delivery. It differs per model
# and is not a detail: Turbo and Nano default `exaggeration` and `cfg_weight`
# to 0.0 where the multilingual model defaults both to 0.5, so a style table
# written as absolute numbers would make "neutral" mean two different things.
# Styles are therefore deltas from this - see SPEECH_STYLES.
#
# `download_bytes` is the sum of the files each model's own loader asks for
# (its `allow_patterns`), not the whole repository, which carries duplicate
# `.pt`/`.safetensors` copies nobody fetches.
SPEECH_MODELS = {
    "chatterbox-multilingual": {
        "repo": "ResembleAI/chatterbox",
        "family": "chatterbox-mtl",
        "license": "MIT",
        "languages": 23,
        "download_bytes": 3_209_000_000,
        # Exactly what ChatterboxMultilingualTTS.from_pretrained asks the Hub
        # for. Copied here so the download can be done - and reported on -
        # before the model is loaded, which its own loader does in one step.
        # Re-check this against mtl_tts.py when the package is upgraded: if
        # it drifts, from_pretrained fetches the difference itself, so the
        # failure is a progress bar that stops short, not a broken model.
        "allow_patterns": [
            "ve.pt",
            "t3_mtl23ls_v2.safetensors",
            "s3gen.pt",
            "grapheme_mtl_merged_expanded_v1.json",
            "conds.pt",
            "Cangjie5_TC.json",
        ],
        "baseline": {"exaggeration": 0.5, "cfg_weight": 0.5},
        # Measured, not estimated: loaded alone on an RTX 2060 and read back
        # from `torch.cuda.memory_allocated`. It is half a 6 GB card, which is
        # why the earlier stages are unloaded before a reading starts.
        "vram_bytes": 3_220_000_000,
        # Paralinguistic tags are documented for Turbo and Nano only. Left in
        # the text here they would simply be read out, so they are stripped.
        "paralinguistic": False,
        "speed": "Moderate",
        "quality": "The only one of the three that speaks anything but English.",
    },
    "chatterbox-turbo": {
        "repo": "ResembleAI/chatterbox-turbo",
        "family": "chatterbox-turbo",
        "license": "MIT",
        "languages": 1,
        "download_bytes": 4_044_000_000,
        "allow_patterns": ["*.safetensors", "*.json", "*.txt", "*.pt", "*.model"],
        "baseline": {"exaggeration": 0.0, "cfg_weight": 0.0},
        # Never loaded, so never measured. Absent rather than guessed.
        "vram_bytes": None,
        "paralinguistic": True,
        "speed": "Fast",
        "quality": "English only, and the only one that can be told to laugh.",
    },
    "chatterbox-nano": {
        "repo": "ResembleAI/chatterbox-nano",
        "family": "chatterbox-turbo",
        "license": "MIT",
        "languages": 1,
        "download_bytes": 2_999_000_000,
        "allow_patterns": ["*.safetensors", "*.json", "*.txt", "*.pt", "*.model"],
        "baseline": {"exaggeration": 0.0, "cfg_weight": 0.0},
        "vram_bytes": None,
        "paralinguistic": True,
        "speed": "Fastest",
        "quality": "Smallest. The publisher reports 3x realtime on 8 CPU cores.",
    },
}

# Read from chatterbox itself when it is installed, for the same reason the
# Whisper menu is read from faster-whisper: a table kept here by hand goes
# stale and offers a language the model will reject. These are the 23 in
# `chatterbox.mtl_tts.SUPPORTED_LANGUAGES` at the version this was written
# against, and are used only until the package is on the machine.
FALLBACK_SPEECH_LANGUAGES = (
    "ar", "da", "de", "el", "en", "es", "fi", "fr", "he", "hi", "it", "ja",
    "ko", "ms", "nl", "no", "pl", "pt", "ru", "sv", "sw", "tr", "zh",
)

SPEECH_MODEL_NAMES = tuple(SPEECH_MODELS)
DEFAULT_SPEECH_MODEL = "chatterbox-multilingual"

# The style vocabulary, and what each style actually does.
#
# Read this before adding to it. **Chatterbox has no emotion conditioning.**
# There is no input that means "sad" to it. What it exposes is `exaggeration`
# (how far delivery is pushed from flat), `cfg_weight` (roughly, how closely it
# holds to the reference clip's own pacing - lower is looser and slower) and
# `temperature`. Everything expressive beyond that comes from the reference
# clip: a voice sampled from someone reading gently will read gently.
#
# So these are named for delivery, not for feeling. Calling one of them
# `[angry]` would be a promise the model cannot keep, and a user who wrote
# `[angry]` and got ordinary speech back would rightly conclude the feature was
# broken rather than that the tag was a lie. Emotion words are accepted as
# aliases - people will write them - and saying so produces a warning rather
# than silence.
#
# Values are deltas from the model's `baseline`, clamped at use. The numbers
# are a considered starting point and nothing more: nobody has listened to any
# of them yet. See STATUS.md.
SPEECH_STYLES = {
    "neutral": {"exaggeration": 0.0, "cfg_weight": 0.0, "temperature": 0.8},
    "calm": {"exaggeration": -0.15, "cfg_weight": 0.0, "temperature": 0.6},
    "gentle": {"exaggeration": -0.2, "cfg_weight": 0.05, "temperature": 0.65},
    "solemn": {"exaggeration": -0.1, "cfg_weight": 0.1, "temperature": 0.6},
    "warm": {"exaggeration": 0.0, "cfg_weight": -0.05, "temperature": 0.75},
    "bright": {"exaggeration": 0.1, "cfg_weight": -0.05, "temperature": 0.85},
    "emphatic": {"exaggeration": 0.2, "cfg_weight": -0.15, "temperature": 0.8},
    "urgent": {"exaggeration": 0.3, "cfg_weight": -0.2, "temperature": 0.85},
}

SPEECH_STYLE_NAMES = tuple(SPEECH_STYLES)
DEFAULT_SPEECH_STYLE = "neutral"

# Emotion words map to the nearest delivery. Accepted, because a person writing
# a script reaches for these before they reach for "emphatic" - and warned
# about, because the result will be that intensity and not that emotion.
SPEECH_STYLE_ALIASES = {
    "excited": "bright",
    "happy": "bright",
    "angry": "urgent",
    "shouting": "urgent",
    "sad": "solemn",
    "serious": "solemn",
    "quiet": "gentle",
    "soft": "gentle",
    "whisper": "gentle",
    "slow": "calm",
    "normal": "neutral",
    "plain": "neutral",
}

# Tags the model itself understands, left in the text for it to act on rather
# than stripped. Only these three: they are what Resemble AI documents. The
# model card says "and more" without saying which, and a guessed tag is read
# out loud as words, so Tertius passes through what is written down and warns
# about everything else rather than inventing a vocabulary.
PARALINGUISTIC_TAGS = frozenset({"laugh", "chuckle", "cough"})

# Audio is written as `.wav`, always, alongside whichever text formats were
# asked for. WAV because writing it needs nothing but the standard library -
# any compressed format would mean an encoder as a new dependency, to save
# space on a file the user is about to listen to once and probably re-encode
# themselves anyway.
SPEECH_AUDIO_FORMAT = "wav"

# How much text goes to the model in one call. Chatterbox is autoregressive and
# degrades on long inputs - it starts dropping or repeating clauses - so text is
# split at sentence boundaries and packed up to this many characters. Sentences
# longer than this on their own are still sent whole: cutting a sentence mid
# clause to satisfy a budget is worse than a long one.
SPEECH_CHUNK_CHARS = 300

# Silence inserted between chunks and between paragraphs, in seconds.
# Concatenated chunks butt together with no gap at all otherwise, which does
# not sound like someone reading; it sounds like an edit.
SPEECH_GAP_SECONDS = 0.28
SPEECH_PARAGRAPH_GAP_SECONDS = 0.7

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
# Audio Tertius generated from a text file, and the timings of that audio.
# The strongest claim of the four: these words were not said by anyone. A
# reader that took this for a transcript would be quoting a machine reading
# a script as though it were a recording of a person.
SPEECH_SHAPE = "speech"

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


def _language_list(value) -> list[str]:
    """Normalise a language selection: trimmed, in order, no repeats.

    Accepts a list, a single string, or a comma-separated string, because all
    three arrive: from the UI, from an older state file, and from anyone
    driving the HTTP API by hand.

    **Trimmed but not lowercased**, unlike the Whisper `language` field.
    MADLAD-400 has codes like `zh_Hant`, and lowercasing them produces
    something it will reject - the same reason the single-target version of
    this was careful about it.
    """
    if value is None:
        return []
    if isinstance(value, str):
        value = value.replace(",", " ").split()
    out: list[str] = []
    for item in value:
        code = str(item).strip()
        if code and code not in out:
            out.append(code)
    return out


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
    # Languages to translate into. A list, because one job over a queue of
    # volumes is the expensive part and doing it three times to get three
    # languages pays that cost three times over.
    #
    # The output names already anticipated this: a translation has always
    # landed as `talk.es.txt`, so `talk.ru.txt` sits beside it with nothing to
    # reconcile.
    target_languages: list[str] = field(default_factory=list)
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
    #
    # **Deliberately not remembered between sessions.** Every other setting
    # here is restored from the last run, and for this one that was a trap: a
    # single unticking stuck to that output folder for good, and every later
    # run there quietly produced the run-on `.txt` this exists to prevent. A
    # stale preference is a bad reason to hand somebody a worse file.
    #
    # The forgetting belongs in the UI rather than here: this still honours an
    # explicit `False` for the run in front of it, because turning it off on
    # purpose has to keep working. What the page does not do is *restore* the
    # last run's answer.
    translate_sentences: bool = True
    # Read the result aloud. The third stage, after transcribing and
    # translating, and deliberately not a source kind of its own.
    #
    # It used to be one, and that was the bug: a queue could be translated *or*
    # spoken but never both, so "take this English talk and give me Spanish
    # audio" - the whole point - was the one thing the app could not express.
    # Someone asking for it picked a language in the speech menu instead, waited
    # for the GPU, and got English back with nothing having warned them.
    speak: bool = False
    speech_model: str = DEFAULT_SPEECH_MODEL
    # What language the model is told it is reading.
    #
    # Consulted **only** for a text source that is not being translated, which
    # is the one case where nothing else knows the answer. Everywhere else it is
    # derived - see `resolved_speech_language` - because a language chosen by
    # hand here is a language that can disagree with the words, and Chatterbox
    # does not translate: told `zh` over English text it reads the English.
    speech_language: str | None = None
    # Which of the translations to read aloud. Always a subset of
    # `target_languages`: speaking a language the text was never translated
    # into is not a thing that can be done, and the UI keeps the two in step
    # in both directions.
    #
    # Separate from `target_languages` rather than derived from it because the
    # two sets are genuinely different sizes - the translator knows a hundred
    # languages and the voice model twenty-three, and wanting Romanian *text*
    # is not the same as being unable to have Romanian text at all.
    speech_languages: list[str] = field(default_factory=list)
    # A recording of the voice to read in. None means: sample it from the audio
    # being transcribed, which is what "in the original speaker's voice" needs,
    # and what a queue of different speakers needs. For a text source with no
    # audio behind it, None means the model's own default voice.
    speech_voice: str | None = None
    # The delivery used until the text says otherwise with a `[style]` tag.
    speech_style: str = DEFAULT_SPEECH_STYLE

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
        self.target_languages = _language_list(self.target_languages)
        self.speech_languages = _language_list(self.speech_languages)
        if self.translate and not self.target_languages:
            # Rejected up front rather than per file: the alternative is a whole
            # batch failing one file at a time, which is the shape of the
            # language check above and exists for the same reason.
            raise ValueError(
                "a target language is required to translate - pick at least "
                "one from the Translate into menu"
            )
        # Reading aloud is a stage on top of translating, never instead of it.
        # A language can only be spoken if the text exists in it first.
        extra = [c for c in self.speech_languages if c not in self.target_languages]
        if extra:
            raise ValueError(
                "cannot read "
                + ", ".join(extra)
                + " aloud without translating into it as well - the text has to "
                "exist before it can be spoken"
            )
        if self.speech_model not in SPEECH_MODELS:
            raise ValueError(
                f"unknown speech model: {self.speech_model!r} "
                f"(expected one of: {', '.join(SPEECH_MODEL_NAMES)})"
            )
        if isinstance(self.speech_style, str):
            self.speech_style = self.speech_style.strip().lower()
        if self.speech_style not in SPEECH_STYLES:
            # Aliases are resolved here rather than at speaking time so that the
            # stored options say what will actually happen. A style that is
            # neither a style nor an alias is rejected up front for the same
            # reason a bad language code is: failing a whole batch one file at a
            # time is the alternative.
            resolved = SPEECH_STYLE_ALIASES.get(self.speech_style)
            if resolved is None:
                raise ValueError(
                    f"unknown speaking style: {self.speech_style!r} "
                    f"(expected one of: {', '.join(SPEECH_STYLE_NAMES)})"
                )
            self.speech_style = resolved
        if isinstance(self.speech_language, str):
            self.speech_language = self.speech_language.strip().lower() or None
        if isinstance(self.speech_voice, str):
            self.speech_voice = self.speech_voice.strip() or None
        if self.speak and self.translate:
            # Rejected up front rather than per file, like every other language
            # check here. The translator knows hundreds of languages and the
            # voice model knows 23; translating a whole queue into Romanian and
            # only then discovering nothing can say it is the failure this
            # prevents.
            from .speech import speech_language_choices

            speakable = speech_language_choices(self.speech_model)
            unsayable = [c for c in self.speech_languages if c not in speakable]
            if speakable and unsayable:
                raise ValueError(
                    f"{self.speech_model} cannot speak "
                    + ", ".join(unsayable)
                    + f". It knows: {', '.join(speakable)}"
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

        # A state file written before there could be more than one target
        # carries `target_language` as a string. Left alone it is dropped as
        # unknown, and a queue set up to produce Spanish quietly stops doing so.
        single = data.pop("target_language", None)
        if single and not data.get("target_languages"):
            data["target_languages"] = [single]
        single_speech = data.get("speech_language")
        if (
            data.get("speak")
            and single_speech
            and not data.get("speech_languages")
            and single_speech in (data.get("target_languages") or [])
        ):
            data["speech_languages"] = [single_speech]

        known = {f for f in cls.__dataclass_fields__}  # noqa: SLF001 - dataclass API
        return cls(**{k: v for k, v in data.items() if k in known})

    @property
    def target_language(self) -> str | None:
        """The first target, for anything that still thinks there is only one."""
        return self.target_languages[0] if self.target_languages else None

    def resolved_compute_type(self) -> str | None:
        """`default` means: let CTranslate2 pick for the device."""
        return None if self.compute_type == "default" else self.compute_type

    def resolved_speech_language(self, detected: str | None = None) -> str:
        """What language the reading is actually in.

        Derived rather than chosen wherever anything else already knows the
        answer, because a language picked by hand is a language that can
        disagree with the words in front of it:

        * translating - the target, necessarily. The words about to be spoken
          are the ones the translator just produced.
        * transcribing - whatever Whisper detected. **Detection beats the
          menu**, because detection is evidence about the words in front of us
          and the menu is a setting that may be years stale. It was the other
          way round once, and a Russian recording was transcribed into Russian
          and then read aloud as English, because a menu left on `en` outranked
          a language the app had just identified with high confidence.
        * a text source with nothing to detect - `speech_language`, the one
          case where nobody else knows.

        Falls back to English, which is what the model assumes anyway.
        """
        if self.translate and self.target_languages:
            return self.target_languages[0]
        return (detected or self.speech_language or "en").strip().lower()


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


# "text" and "speech" scan for the same `.txt` files and differ only in what
# is then done with them - translated, or read aloud. Kept as two kinds
# rather than one plus a flag because the queue has to remember which was
# meant: a file queued to be spoken and a file queued to be translated look
# identical on disk, and the wrong one is an hour of GPU time.
SOURCE_KINDS = ("media", "text", "speech")


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
    matches = is_media_file if kind == "media" else is_text_file
    found = [
        p
        for p in walker
        if matches(p) and UPLOAD_DIRNAME not in p.parts
    ]
    return sorted(found, key=lambda p: str(p).lower())
