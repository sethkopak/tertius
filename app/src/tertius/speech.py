"""Offline speech synthesis: read a text file aloud, in a voice you supply.

The mirror image of the rest of Tertius. Everything else here turns recordings
into text; this turns text into a recording. It is a source kind of its own -
Whisper is never loaded, because there is nothing to decode.

Three decisions worth keeping written down.

**Chatterbox, because of the licence and the gate.** The code is MIT, the
weights are MIT, and none of the three repositories is gated on the Hub. The
models that beat it on paper both fail one of those: IndexTTS-2 has real
duration control and ships under the bilibili Model Use License Agreement
rather than a permissive licence, and XTTS-v2 is CPML and forbids commercial
use outright. Tertius is MIT and is handed to strangers; a default that
quietly removes their rights is not a default.

**The weights are loaded as published, not converted.** The translation models
are converted here from the publisher's checkpoint precisely so that nothing
depends on a stranger's upload - see translate.py. That is not possible for
these: CTranslate2 cannot run them, they are a torch stack end to end. What
stands in for it is that the repositories belong to Resemble AI, the
organisation that wrote the model, rather than to an individual account.

**Chatterbox has no emotion conditioning, and the style tags do not pretend
otherwise.** There is no input to this model that means "sad". What it exposes
is how hard delivery is pushed and how closely it holds to the reference clip.
The feeling in a generated line comes from the *reference clip* - a voice
sampled from someone reading gently reads gently. So the tag vocabulary is
named for delivery, and an emotion word written as a tag is accepted, mapped to
the nearest delivery, and warned about. See SPEECH_STYLES in config.py.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import wave
from array import array
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .config import (
    DEFAULT_SPEECH_MODEL,
    DEFAULT_SPEECH_STYLE,
    FALLBACK_SPEECH_LANGUAGES,
    PARALINGUISTIC_TAGS,
    SPEECH_CHUNK_CHARS,
    SPEECH_GAP_SECONDS,
    SPEECH_MODELS,
    SPEECH_PARAGRAPH_GAP_SECONDS,
    SPEECH_STYLE_ALIASES,
    SPEECH_STYLES,
)

log = logging.getLogger(__name__)

# What speaking needs beyond the base install. Unlike translation, `torch` here
# is not a setup-only dependency that is never touched again - it *is* the
# runtime. That is the whole reason this is an opt-in extra.
SPEECH_REQUIREMENTS = {"torch": "torch", "chatterbox": "chatterbox-tts"}

# `chatterbox-tts` is installed with `--no-deps`, and its dependencies are
# named here instead. That is not tidiness; a plain `pip install chatterbox-tts`
# does not work, and would damage translation if it did.
#
# Three separate problems, all from the same metadata:
#
# 1. **`spacy-pkuseg` cannot be installed at all on Python 3.14.** It publishes
#    no cp314 wheel in any version, so pip falls back to building it from
#    source, which needs the MSVC C++ build tools. On a machine without them
#    the whole install dies with "Microsoft Visual C++ 14.0 or greater is
#    required" - having installed nothing. It is a *hard* requirement in the
#    metadata and an *optional* one in the code: `tokenizer.py` imports it
#    inside a try/except and degrades to no Chinese word segmentation.
#    `pykakasi` is the same shape, for Japanese, and does have wheels, so it
#    is kept.
# 2. **`transformers==5.2.0` is a hard pin, and translation runs on 5.16.1.**
#    Taking chatterbox's pins would silently downgrade the library the
#    translation adapters depend on. Run against 5.16.1 it works: the model
#    loads and generates. Pinned metadata is not the same as a tested floor.
# 3. **`gradio==6.8.0` is never imported by the library.** It is there for the
#    publisher's demo apps. Accepting it pulls a web framework, FastAPI and
#    uvicorn into an app that already has Flask and is documented as making
#    exactly four kinds of network request.
#
# What is listed here is what `chatterbox/mtl_tts.py`, `tts_turbo.py` and
# `models/tokenizers/tokenizer.py` actually import. Re-read those when the
# package is upgraded: a dependency dropped from this list fails at *use*,
# which is minutes into a reading rather than at install time.
CHATTERBOX_DEPENDENCIES = (
    "librosa",
    "resemble-perth",
    "s3tokenizer",
    "conformer",
    "diffusers",
    "omegaconf",
    "pyloudnorm",
    "pykakasi",
    "transformers",
    "safetensors",
    "numpy",
)

# torch from the CUDA index when there is a GPU to use, and from the CPU index
# when there is not.
#
# This is the opposite of the translation installer, which always takes the CPU
# build because conversion never runs a model. Here the model runs, and on the
# CPU it runs perhaps twenty times slower. The two share one virtual
# environment and therefore one torch, so whichever installs first decides -
# which is why `torch_install_problem` exists to say so out loud rather than
# let someone sit through a CPU synthesis wondering why their GPU is idle.
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"
# cu126, and the number matters more than it looks.
#
# This said cu124 first, which was a guess, and it is wrong in the way that
# fails worst: that index carries **no cp314 wheels at all**, so on Python 3.14
# pip reports "No matching distribution found for torch" - as though torch did
# not exist - rather than anything about CUDA. Found by running it.
#
# cu126 was checked against the index rather than assumed. It carries torch
# 2.14.0 - the same version as the CPU build, so nothing else in the
# environment shifts - for cp311, cp313 and cp314, on win_amd64 and
# manylinux_2_28 x86_64/aarch64. It is also the safe end of the CUDA range:
# 12.6 still builds for every architecture back to Maxwell, where the 13.x
# indexes have dropped some of them.
#
# Re-check this when the floor Python moves. An index that lacks a wheel for
# the running interpreter does not say so in terms anyone can act on.
TORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu126"

# `[word]`. Deliberately narrow: one token, no spaces, so that a bracketed
# phrase in ordinary prose - "[name of the speaker unclear]" - is never
# mistaken for a tag and eaten.
TAG = re.compile(r"\[([A-Za-z][A-Za-z0-9_-]*)\]")

PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")

# Audio is written as 16-bit PCM. The model hands back float32 in [-1, 1].
_INT16_MAX = 32767


class SpeechUnavailableError(RuntimeError):
    """Speaking was asked for but the machine cannot do it yet.

    Carries what would fix it, because "speech is unavailable" on its own has
    never helped anybody.
    """


# --------------------------------------------------------------------- markup


@dataclass(frozen=True)
class SpokenChunk:
    """One call to the model: some text, and how it should be delivered."""

    text: str
    style: str
    params: dict
    # Whether a blank line came before this chunk, which decides how long a
    # pause is left in front of it.
    starts_paragraph: bool = False


@dataclass
class ParsedScript:
    """What a text file turned into, plus everything worth saying about it."""

    chunks: list[SpokenChunk] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    styles_used: list[str] = field(default_factory=list)

    @property
    def characters(self) -> int:
        return sum(len(chunk.text) for chunk in self.chunks)


def resolve_style(name: str | None) -> tuple[str, str | None]:
    """Resolve a tag to a style name, and say so when it was an alias.

    Returns `(style, warning)`. A warning rather than silence, because the
    person who wrote `[angry]` is owed the news that this model has no anger in
    it - only intensity - and that the feeling has to come from the reference
    clip instead.
    """
    if not name:
        return DEFAULT_SPEECH_STYLE, None
    key = name.strip().lower()
    if key in SPEECH_STYLES:
        return key, None
    alias = SPEECH_STYLE_ALIASES.get(key)
    if alias is not None:
        return alias, (
            f"[{key}] was read as [{alias}]. Chatterbox has no emotion "
            f"conditioning - it can be told how hard to push a line, not what "
            f"to feel. The feeling comes from the voice clip you give it."
        )
    return DEFAULT_SPEECH_STYLE, None


def style_params(model_key: str, style: str) -> dict:
    """The generation parameters for one style on one model.

    Styles are deltas from the model's own idea of ordinary delivery, because
    the models disagree about what that is: Turbo and Nano default
    `exaggeration` and `cfg_weight` to 0.0 where the multilingual model defaults
    both to 0.5. A table of absolute numbers would make `[neutral]` mean two
    different things depending on which model was chosen, which is exactly the
    kind of silent difference the translation adapters exist to prevent.
    """
    if model_key not in SPEECH_MODELS:
        raise ValueError(f"unknown speech model: {model_key!r}")
    if style not in SPEECH_STYLES:
        raise ValueError(f"unknown speaking style: {style!r}")
    baseline = SPEECH_MODELS[model_key]["baseline"]
    delta = SPEECH_STYLES[style]

    def clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    return {
        "exaggeration": round(
            clamp(baseline["exaggeration"] + delta["exaggeration"], 0.0, 1.5), 3
        ),
        "cfg_weight": round(
            clamp(baseline["cfg_weight"] + delta["cfg_weight"], 0.0, 1.0), 3
        ),
        "temperature": round(clamp(delta["temperature"], 0.05, 1.5), 3),
    }


def _tokenize(text: str, paralinguistic: bool) -> tuple[list[tuple[str, str]], list[str]]:
    """Split text into ("text", body) and ("style", name) events.

    Three kinds of bracket, and they are treated differently on purpose:

    * A **style tag** is ours. It changes delivery for everything after it and
      is removed from what gets spoken.
    * A **paralinguistic tag** is the model's own - `[laugh]`, `[chuckle]`,
      `[cough]` - and is left in the text for Turbo and Nano to act on. The
      multilingual model does not understand them, so there they are removed:
      left in, they would simply be read out as the word "laugh".
    * **Anything else in brackets stays exactly as written.** Transcripts are
      full of `[inaudible]` and `[crosstalk]`, and a tag vocabulary that ate
      them would corrupt the very files this feature exists to read. It is
      reported instead, once per distinct token, so a misspelt style tag is
      visible rather than silently spoken aloud.
    """
    events: list[tuple[str, str]] = []
    warnings: list[str] = []
    seen_unknown: set[str] = set()
    buffer: list[str] = []
    cursor = 0

    def flush() -> None:
        body = "".join(buffer)
        buffer.clear()
        if body:
            events.append(("text", body))

    for match in TAG.finditer(text):
        token = match.group(1).lower()
        known_style = token in SPEECH_STYLES or token in SPEECH_STYLE_ALIASES
        known_para = token in PARALINGUISTIC_TAGS

        if known_style:
            # The one tag that really does end a run of text: what follows it
            # is generated with different numbers, so it cannot share a call.
            buffer.append(text[cursor : match.start()])
            flush()
            style, warning = resolve_style(token)
            if warning and warning not in warnings:
                warnings.append(warning)
            events.append(("style", style))
            cursor = match.end()
        elif known_para and not paralinguistic:
            # Dropped, and said so. Speaking the word "laugh" out loud in the
            # middle of a sentence is a worse outcome than a missing chuckle.
            #
            # The text either side keeps accumulating into the *same* run.
            # Flushing here instead would put a chunk boundary - and so a pause
            # the writer never wrote - wherever a tag happened to be removed.
            buffer.append(text[cursor : match.start()])
            if token not in seen_unknown:
                seen_unknown.add(token)
                warnings.append(
                    f"[{token}] was removed: only chatterbox-turbo and "
                    f"chatterbox-nano act on paralinguistic tags, and this "
                    f"model would have read it out as a word."
                )
            cursor = match.end()
        elif not known_para and token not in seen_unknown:
            # Left in the text, deliberately, and the cursor does not move.
            # Reported so that a typo is visible rather than simply spoken.
            seen_unknown.add(token)
            warnings.append(
                f"[{token}] is not a style tag, so it stays in the text and "
                f"will be read aloud. If you meant a style, the ones that "
                f"exist are: {', '.join(sorted(SPEECH_STYLES))}."
            )

    buffer.append(text[cursor:])
    flush()
    return events, warnings


def _pack(sentences: Sequence[str], budget: int) -> list[str]:
    """Group sentences into chunks of at most `budget` characters.

    A sentence longer than the budget on its own is still sent whole. Cutting
    one mid-clause to satisfy a number would put a breath in the middle of a
    thought, which is worse than a long generation.
    """
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        # Runs of spaces are collapsed here rather than left alone, because
        # removing a tag from the middle of a line leaves two spaces glued
        # together and the model reads an unexplained gap as a pause.
        sentence = re.sub(r"[ 	]+", " ", sentence).strip()
        if not sentence:
            continue
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= budget:
            current = f"{current} {sentence}"
        else:
            chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def parse_script(
    text: str,
    model_key: str = DEFAULT_SPEECH_MODEL,
    default_style: str = DEFAULT_SPEECH_STYLE,
    budget: int = SPEECH_CHUNK_CHARS,
) -> ParsedScript:
    """Turn a text file into the sequence of calls that will read it aloud.

    Pure: it loads nothing and needs no model on disk, which is what lets the UI
    show someone what their tags did before they commit to minutes of GPU time.
    """
    from .alignment import split_sentences

    if model_key not in SPEECH_MODELS:
        raise ValueError(f"unknown speech model: {model_key!r}")
    default_style, _ = resolve_style(default_style)

    paralinguistic = bool(SPEECH_MODELS[model_key].get("paralinguistic"))
    events, warnings = _tokenize(text, paralinguistic)

    parsed = ParsedScript(warnings=list(warnings))
    current_style = default_style
    styles_used: list[str] = []
    # A chunk begins a paragraph when a blank line came before it. Tracked
    # across events rather than per run, because a style tag can land in the
    # middle of a paragraph and must not invent a pause there.
    pending_break = True

    for kind, value in events:
        if kind == "style":
            current_style = value
            continue
        blocks = PARAGRAPH_BREAK.split(value)
        for index, block in enumerate(blocks):
            if index > 0:
                pending_break = True
            block = block.strip()
            if not block:
                continue
            params = style_params(model_key, current_style)
            for chunk_index, body in enumerate(_pack(split_sentences(block), budget)):
                parsed.chunks.append(
                    SpokenChunk(
                        text=body,
                        style=current_style,
                        params=params,
                        starts_paragraph=pending_break and chunk_index == 0,
                    )
                )
                if current_style not in styles_used:
                    styles_used.append(current_style)
                pending_break = False

    parsed.styles_used = styles_used
    return parsed


# ------------------------------------------------------------------ wav output


def _as_samples(wav) -> Sequence[float]:
    """Flatten whatever the model returned into a flat sequence of floats.

    Accepts a torch tensor, a numpy array, or a plain list - the last so that
    the tests can drive every line of the writer without torch installed.
    """
    for attribute in ("detach", "cpu", "numpy"):
        method = getattr(wav, attribute, None)
        if callable(method):
            wav = method()
    reshape = getattr(wav, "reshape", None)
    if callable(reshape):
        wav = reshape(-1)
    tolist = getattr(wav, "tolist", None)
    if callable(tolist):
        wav = tolist()
    # A single-channel tensor arrives as [[...]] when nothing reshaped it.
    while isinstance(wav, (list, tuple)) and len(wav) == 1 and isinstance(
        wav[0], (list, tuple)
    ):
        wav = wav[0]
    return list(wav)


class WavWriter:
    """Append-only 16-bit mono WAV, written straight to disk.

    Streamed rather than accumulated. A 40-minute reading is around 115 MB of
    samples, and holding that as a Python list of floats first would cost the
    better part of a gigabyte for no reason - the frames are final the moment
    the model returns them.

    Written to a `.partial` and moved into place at the end, like every other
    output here: an interrupted run must never leave a truncated file that a
    later run would take for finished work.
    """

    def __init__(self, target: Path, sample_rate: int):
        self.target = Path(target)
        self.sample_rate = int(sample_rate)
        self.frames = 0
        self._tmp = self.target.with_name(self.target.name + ".partial")
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self._handle = wave.open(str(self._tmp), "wb")
        self._handle.setnchannels(1)
        self._handle.setsampwidth(2)
        self._handle.setframerate(self.sample_rate)

    @property
    def seconds(self) -> float:
        return self.frames / self.sample_rate if self.sample_rate else 0.0

    def append(self, wav) -> float:
        """Write samples, and return the position afterwards in seconds."""
        samples = _as_samples(wav)
        if samples:
            block = array(
                "h",
                (
                    int(max(-1.0, min(1.0, float(value))) * _INT16_MAX)
                    for value in samples
                ),
            )
            self._handle.writeframes(block.tobytes())
            self.frames += len(block)
        return self.seconds

    def silence(self, seconds: float) -> float:
        count = int(max(0.0, seconds) * self.sample_rate)
        if count:
            self._handle.writeframes(array("h", bytes(2 * count)).tobytes())
            self.frames += count
        return self.seconds

    def close(self) -> str:
        self._handle.close()
        self._tmp.replace(self.target)
        return str(self.target)

    def abandon(self) -> None:
        """Give up without leaving a half-written file behind."""
        try:
            self._handle.close()
        except Exception:  # pragma: no cover - defensive
            pass
        self._tmp.unlink(missing_ok=True)

    def __enter__(self) -> "WavWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            self.abandon()
        else:
            self.close()


# ------------------------------------------------------------------- the model


def missing_requirements() -> list[str]:
    """Which speech libraries are not importable yet, by pip name."""
    missing = []
    for module, package in SPEECH_REQUIREMENTS.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    return missing


def _in_a_virtualenv() -> bool:
    return sys.prefix != sys.base_prefix


def cuda_is_present() -> bool:
    """Is there an NVIDIA GPU here at all?

    Asked through CTranslate2, which is already installed for transcription, so
    that the question can be answered *before* deciding which torch to install.
    Asking torch would be circular.
    """
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count()) > 0
    except Exception:
        return False


def torch_install_problem() -> str | None:
    """Warn when the installed torch cannot use the GPU that is sitting there.

    One virtual environment holds one torch, and translation installs the
    CPU-only build deliberately - conversion never runs a model, and the CUDA
    build is ten times the download. Whichever feature installs first wins. A
    machine that translated before it ever spoke therefore has a CPU torch and
    a perfectly good GPU, and synthesis will run perhaps twenty times slower
    with nothing anywhere saying why. This is that thing saying why.
    """
    try:
        import torch
    except ImportError:
        return None
    if not cuda_is_present():
        return None
    if torch.cuda.is_available():
        return None
    # Two things in this command are load-bearing, and both were learned by
    # getting them wrong.
    #
    # **`--force-reinstall`**, because pip counts `torch` as already satisfied
    # by `2.14.0+cpu` when asked for `torch` from the CUDA index: the part
    # after the `+` is a local version identifier and does not make it a
    # different version. Without the flag pip prints "Requirement already
    # satisfied", changes nothing, and **exits 0** - so the GPU stays unused
    # and nothing anywhere reports a failure.
    #
    # **This interpreter**, rather than a bare `pip`. Tertius runs from its own
    # virtual environment, and a bare `pip install` pasted into a terminal hits
    # whichever Python is on PATH - installing gigabytes somewhere that has no
    # effect on this one, announcing "Defaulting to user installation" as it
    # goes.
    return (
        "There is an NVIDIA GPU here, but the installed torch "
        f"({getattr(torch, '__version__', 'unknown')}) is a CPU-only build, so "
        "speaking will run on the CPU and be much slower. That build is the one "
        "translation installs, on purpose - it only ever converts a model and "
        "never runs one. To use the GPU, reinstall torch from the CUDA index, "
        "into this environment:\n\n"
        f'    "{sys.executable}" -m pip install --force-reinstall '
        f"--index-url {TORCH_CUDA_INDEX} torch\n"
    )


def install_requirements(on_line: Callable[[str], None] | None = None) -> list[str]:
    """Install what speaking needs, into the environment we are running in.

    Refuses outside a virtual environment, for the same reason the translation
    installer does: quietly putting a couple of gigabytes of torch into
    somebody's system Python because they clicked a button in a transcription
    app is not a thing to do. There the command is printed instead.
    """
    missing = missing_requirements()
    if not missing:
        return []

    if not _in_a_virtualenv():
        raise SpeechUnavailableError(
            "speaking needs "
            + ", ".join(missing)
            + ", and Tertius is not running in a virtual environment, so it will "
            "not install them for you. Install them yourself with:\n\n"
            "    pip install " + " ".join(missing) + "\n"
        )

    def run(arguments: list[str]) -> None:
        command = [sys.executable, "-m", "pip", "install", *arguments]
        log.info("installing: %s", " ".join(arguments))
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for line in process.stdout or ():
            line = line.rstrip()
            if line and on_line is not None:
                on_line(line)
        if process.wait() != 0:
            raise SpeechUnavailableError(
                "could not install " + " ".join(arguments) + ". The output above "
                "says why; the usual cause is no network."
            )

    # torch gets its own call, from whichever index suits the hardware. Letting
    # pip resolve it alongside chatterbox would take the default PyPI wheel,
    # which on Linux carries a bundled CUDA runtime whether or not there is a
    # GPU to use it.
    if "torch" in missing:
        index = TORCH_CUDA_INDEX if cuda_is_present() else TORCH_CPU_INDEX
        log.info("installing torch from %s", index)
        run(["--index-url", index, "torch"])
    if "chatterbox-tts" in missing:
        # Its own dependencies first, then the package with none of them. The
        # order matters only for the error message: a failure here names a
        # dependency rather than chatterbox itself.
        run(list(CHATTERBOX_DEPENDENCIES))
        run(["--no-deps", "chatterbox-tts"])

    rest = [
        name for name in missing if name not in ("torch", "chatterbox-tts")
    ]
    if rest:
        run(rest)

    still_missing = missing_requirements()
    if still_missing:
        raise SpeechUnavailableError(
            "installed, but still cannot import: " + ", ".join(still_missing)
        )
    return missing


def is_downloaded(model_key: str) -> bool:
    """Are this model's weights already on disk, with no network needed?"""
    entry = SPEECH_MODELS.get(model_key)
    if entry is None:
        raise ValueError(f"unknown speech model: {model_key!r}")
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(
            entry["repo"],
            allow_patterns=entry["allow_patterns"],
            local_files_only=True,
        )
        return True
    except Exception:
        return False


def speech_language_choices(model_key: str = DEFAULT_SPEECH_MODEL) -> tuple[str, ...]:
    """Codes this model will accept, read from the package where possible.

    Same principle as the Whisper menu and the translation menu: ask the
    library rather than keep a table by hand, so the menu can never offer a
    language the model would reject. Unlike the translation menu this one can
    be answered before the weights are downloaded - the list is a constant in
    the package, not something read out of a converted vocabulary.
    """
    entry = SPEECH_MODELS.get(model_key)
    if entry is None:
        raise ValueError(f"unknown speech model: {model_key!r}")
    if entry["family"] != "chatterbox-mtl":
        return ("en",)
    try:
        from chatterbox.mtl_tts import SUPPORTED_LANGUAGES

        return tuple(sorted(SUPPORTED_LANGUAGES))
    except Exception:
        return FALLBACK_SPEECH_LANGUAGES


class Speaker:
    """A loaded speech model, reused across a batch.

    Mirrors Translator: lazily loaded, reused for the whole run, and honouring
    the same process-wide "CUDA is broken here" memory, so a machine whose GPU
    has already failed a transcription does not go and wedge itself again.
    """

    def __init__(
        self,
        model_key: str = DEFAULT_SPEECH_MODEL,
        device: str = "auto",
        on_download_progress: Callable[[int, int], None] | None = None,
    ):
        if model_key not in SPEECH_MODELS:
            raise ValueError(f"unknown speech model: {model_key!r}")
        self.model_key = model_key
        self.requested_device = device
        self.on_download_progress = on_download_progress
        self._model = None
        self.active_device: str | None = None
        self.gpu_fallback_reason: str | None = None

    @property
    def family(self) -> str:
        return SPEECH_MODELS[self.model_key]["family"]

    @property
    def paralinguistic(self) -> bool:
        return bool(SPEECH_MODELS[self.model_key].get("paralinguistic"))

    @property
    def sample_rate(self) -> int:
        # 24 kHz is what every Chatterbox model reports, but it is read off the
        # loaded model rather than written down: a wrong sample rate does not
        # fail, it just plays back at the wrong pitch and speed.
        return int(getattr(self._model, "sr", 24000))

    def _resolve_device(self) -> str:
        from .transcribe import cuda_known_broken, register_cuda_dll_directories

        register_cuda_dll_directories()
        broken = cuda_known_broken()
        wanted = self.requested_device
        if wanted == "cpu":
            return "cpu"
        if broken:
            self.gpu_fallback_reason = broken
            return "cpu"

        try:
            import torch

            available = bool(torch.cuda.is_available())
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("could not ask torch about CUDA: %s", exc)
            available = False

        if available:
            return "cuda"
        if wanted == "cuda":
            raise SpeechUnavailableError(
                "speaking was asked to use the GPU, but torch cannot see a CUDA "
                "device. " + (torch_install_problem() or "")
            )
        self.gpu_fallback_reason = (
            torch_install_problem() or "no CUDA device was found"
        )
        return "cpu"

    def download(self) -> None:
        """Fetch the weights without loading them onto a device.

        Split from `load` so that a model can be made ready - and so the UI can
        put the multi-gigabyte download in the open where the user chooses it -
        before anyone has committed to a run. The model's own `from_pretrained`
        downloads and loads in one step, which would take VRAM for a model
        nobody has asked to run yet.
        """
        entry = SPEECH_MODELS[self.model_key]
        from huggingface_hub import snapshot_download

        from .transcribe import _progress_tqdm_class

        kwargs: dict = {"allow_patterns": entry["allow_patterns"]}
        if self.on_download_progress is not None:
            kwargs["tqdm_class"] = _progress_tqdm_class(self.on_download_progress)
        log.info("downloading %s for speech", entry["repo"])
        snapshot_download(entry["repo"], **kwargs)

    def prepare(self, on_line: Callable[[str], None] | None = None) -> None:
        """Install what is needed and fetch the weights. Installs nothing else.

        This is the one place allowed to install anything, and only because a
        person just pressed a button asking for exactly this.
        """
        install_requirements(on_line)
        self.download()

    def load(self) -> None:
        """Download if needed, then load the model onto a device.

        Called at job start for the same reason `warmup` is: a missing model or
        an unusable device should fail before the queue has been half consumed,
        not on file nine.
        """
        if self._model is not None:
            return
        missing = missing_requirements()
        if missing:
            raise SpeechUnavailableError(
                "speaking needs " + ", ".join(missing) + ", which is not "
                "installed. Press Download and prepare, or install it yourself:\n\n"
                "    pip install -e app[speak]\n"
            )

        self.download()
        device = self._resolve_device()
        log.info("loading speech model %s on %s", self.model_key, device)
        try:
            if self.family == "chatterbox-mtl":
                from chatterbox.mtl_tts import ChatterboxMultilingualTTS

                model = ChatterboxMultilingualTTS.from_pretrained(device=device)
            else:
                from chatterbox.tts_turbo import ChatterboxTurboTTS

                model = ChatterboxTurboTTS.from_pretrained(
                    device=device, nano=self.model_key == "chatterbox-nano"
                )
        except Exception as exc:
            if device == "cuda":
                from .transcribe import mark_cuda_broken

                mark_cuda_broken(f"speech model failed to load on CUDA: {exc}")
                raise SpeechUnavailableError(
                    f"the speech model could not be loaded on the GPU: {exc}"
                ) from exc
            raise
        self._model = model
        self.active_device = device

    def speak(self, chunk: SpokenChunk, language: str, voice: str | None = None):
        """Generate one chunk. Returns whatever the model returns.

        The two families take different arguments, which is the whole reason
        this method exists rather than the caller talking to the model: the
        multilingual model *requires* `language_id` and Turbo does not accept
        it at all. Passing it to Turbo is a TypeError; leaving it off the
        multilingual model is a different voice in a different language.
        """
        self.load()
        assert self._model is not None
        arguments = dict(chunk.params)
        if voice:
            arguments["audio_prompt_path"] = voice
        if self.family == "chatterbox-mtl":
            arguments["language_id"] = language
        return self._model.generate(chunk.text, **arguments)

    def unload(self) -> None:
        self._model = None


# ------------------------------------------------------------------ the output


def _cues(chunks: Iterable[tuple[SpokenChunk, float, float]]):
    """Turn the spoken chunks and their measured spans into a result object.

    These timings are not a guess. Each chunk's audio is measured as it is
    written, so the `.srt` that comes out of this describes the recording that
    came out with it, exactly - which is the one case in this whole program
    where a subtitle file cannot drift from its audio.
    """
    from .transcribe import Segment, TranscriptionResult

    return TranscriptionResult(
        segments=[
            Segment(start=start, end=end, text=chunk.text)
            for chunk, start, end in chunks
        ],
        language=None,
        duration=0.0,
        words=[],
    )


def speak_text_file(
    source,
    output_dir,
    speaker: Speaker,
    language: str | None = None,
    voice: str | None = None,
    default_style: str = DEFAULT_SPEECH_STYLE,
    formats: Sequence[str] = ("txt", "srt"),
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[list[str], object]:
    """Read a `.txt` aloud and write the recording beside it.

    Always writes a `.wav`. Writes an `.srt` and a `.json` when those formats
    are asked for, timed against the audio that was just generated rather than
    against anything estimated. Never writes a `.txt`: the text is the input,
    and writing a near-copy of it back into the output folder would be one more
    file to tell apart from the one the user wrote.

    The audio is streamed to disk as it is generated, so a reading that fails
    on chunk four hundred does not lose the first three hundred and
    ninety-nine - it leaves nothing, which is the same bargain every other
    output here makes, but without ever holding the whole recording in memory.
    """
    from .transcribe import (
        result_to_json,
        safe_output_path,
        segments_to_srt,
        write_atomically,
    )

    source = Path(source)
    output_dir = Path(output_dir)
    # `utf-8-sig`, not `utf-8`. Notepad and PowerShell both write a BOM, and
    # read as plain utf-8 it survives as an invisible character glued to the
    # first word - which here would be read out loud.
    text = source.read_text(encoding="utf-8-sig")

    script = parse_script(text, speaker.model_key, default_style)
    if not script.chunks:
        raise ValueError(f"there is no text to read aloud in {source.name}")

    language = (language or "en").strip().lower()
    allowed = speech_language_choices(speaker.model_key)
    if allowed and language not in allowed:
        raise ValueError(
            f"{speaker.model_key} cannot speak {language!r} "
            f"(it knows: {', '.join(allowed)})"
        )

    # Loaded before the first chunk so that a missing model or an unusable
    # device fails here, with nothing written, rather than after some of the
    # recording exists.
    speaker.load()

    target = safe_output_path(output_dir, source.stem, "wav")
    spans: list[tuple[SpokenChunk, float, float]] = []
    total = len(script.chunks)

    writer = WavWriter(target, speaker.sample_rate)
    try:
        for index, chunk in enumerate(script.chunks):
            if index:
                writer.silence(
                    SPEECH_PARAGRAPH_GAP_SECONDS
                    if chunk.starts_paragraph
                    else SPEECH_GAP_SECONDS
                )
            start = writer.seconds
            end = writer.append(speaker.speak(chunk, language, voice))
            spans.append((chunk, start, end))
            if on_progress is not None:
                # A reporting callback must never be able to fail a reading.
                try:
                    on_progress(index + 1, total)
                except Exception:  # pragma: no cover - defensive
                    log.debug("speech progress callback failed", exc_info=True)
    except Exception:
        writer.abandon()
        raise

    written = [writer.close()]
    result = _cues(spans)
    result.duration = writer.seconds
    result.language = language
    result.speech = {
        "model": speaker.model_key,
        "repo": SPEECH_MODELS[speaker.model_key]["repo"],
        "language": language,
        "voice": str(voice) if voice else None,
        "default_style": default_style,
        "styles_used": list(script.styles_used),
        "chunks": total,
        "seconds": round(writer.seconds, 3),
        "warnings": list(script.warnings),
        # Chatterbox watermarks everything it generates with Resemble AI's
        # PerTh watermarker, inaudibly and unconditionally. Recorded because it
        # is true of every file this writes and someone should be able to find
        # that out from the output rather than from the source of a dependency.
        "watermarked": True,
    }

    formats = list(formats or ())
    if "srt" in formats:
        written.append(
            write_atomically(
                safe_output_path(output_dir, source.stem, "srt"),
                segments_to_srt(result.segments),
            )
        )
    if "json" in formats:
        written.append(
            write_atomically(
                safe_output_path(output_dir, source.stem, "json"),
                result_to_json(result, source),
            )
        )

    log.info(
        "read %s aloud into %s (%d chunk(s), %.1fs%s)",
        source.name,
        Path(written[0]).name,
        total,
        writer.seconds,
        f", {len(script.warnings)} warning(s)" if script.warnings else "",
    )
    return written, result
