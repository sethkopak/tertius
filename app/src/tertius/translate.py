"""Offline translation: CTranslate2 over models we convert ourselves.

Whisper can already translate, but only ever *into English* - that is the whole
of the feature, and it is not what "translate this into Spanish" means. So
translation here is a second model, run after transcription.

Two decisions worth keeping written down.

**We convert the publisher's weights rather than downloading someone's
conversion.** The Hub has ready-made CTranslate2 builds of all of these, and
using one would have saved this whole module. They are individual accounts with
no organizational backing, no signature, and nothing tying their `model.bin` to
the weights it claims to be - and Tertius points every user it ever gets at
whatever it names here. Converting from `facebook/...` and `google/...` costs a
`torch` install at setup and nothing afterwards.

**NLLB-200 is not offered**, despite being the best small translation model
available. It is CC-BY-NC-4.0. Tertius is MIT, and shipping a default feature
that quietly forbids commercial use to everyone downstream is worse than
shipping a slightly weaker model.

The two model families disagree about how to be told a target language, which
is what the adapters exist to hide:

* **M2M-100** puts a source-language token in front of the input and forces the
  target-language token as the first token of the output.
* **MADLAD-400** is a T5: the target goes in the *input text*, as a `<2es>`
  prefix, and the output carries no language token at all.

Get that wrong and neither model fails - they translate into the wrong language
or echo the source back, which is why each adapter has a test pinning the exact
tokens it builds.
"""

from __future__ import annotations

import functools
import json
import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Sequence

from .config import TRANSLATION_FILE_PATTERNS, TRANSLATION_MODELS

log = logging.getLogger(__name__)

# Where converted models live. Beside the Hugging Face cache rather than inside
# it: these are our artifacts, not something `huggingface_hub` put there, and a
# `huggingface-cli delete-cache` should not take them with it.
CACHE_DIRNAME = "tertius-translation"

# int8 throughout. A 3B model at float32 is 12 GB of VRAM and will not fit
# beside Whisper on any card this is likely to meet; int8 costs very little
# translation quality and is what makes madlad400 usable on a 6 GB card at all.
QUANTIZATION = "int8"

# How many segments go to the model at once. CTranslate2 batches well, and the
# alternative - one call per segment - spends most of its time in overhead on a
# transcript with two thousand of them.
BATCH_SIZE = 16

M2M100_LANG_TOKEN = re.compile(r"^__([a-z]{2,3})__$")
T5_LANG_TOKEN = re.compile(r"^<2([a-zA-Z_]{2,})>$")

# What translating needs beyond the base install. `torch` is used only to read
# the publisher's checkpoint during conversion and is never touched afterwards;
# `transformers` and `sentencepiece` tokenize at run time, because M2M-100 ships
# no `tokenizer.json` and no fast tokenizer class.
TRANSLATION_REQUIREMENTS = ("torch", "transformers", "sentencepiece")

# CPU-only torch, deliberately. Conversion loads a checkpoint and writes it back
# out; it never runs the model, so a GPU build buys nothing. On Linux the
# difference is not small - the default PyPI wheel carries a bundled CUDA
# runtime and is well over a gigabyte, against roughly 120 MB here. The index
# has cp3xx wheels for Windows, Linux x86_64 and Linux aarch64; macOS resolves
# from PyPI, whose macOS wheels are CPU-only anyway.
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"

# Files CTranslate2 writes into the output directory itself. Handing any of
# these to the converter as a file to copy makes it stop with "already exists
# in the model directory" - after the whole download, which is the expensive
# part. Only the tokenizer's own files may ride along.
CONVERTER_WRITES = frozenset(
    {
        "config.json",
        "model.bin",
        "shared_vocabulary.json",
        "shared_vocabulary.txt",
        "source_vocabulary.json",
        "target_vocabulary.json",
    }
)

# The tokenizer class per family, named rather than left to `AutoTokenizer`.
# Auto would have to work out what it is looking at, and the converted
# directory is a bad place to ask: `config.json` there is CTranslate2's runtime
# config, not a transformers model config, and M2M-100's `tokenizer_config.json`
# names no `tokenizer_class` for it to fall back on.
TOKENIZER_CLASSES = {"m2m100": "M2M100Tokenizer", "t5": "T5Tokenizer"}


class TranslationUnavailableError(RuntimeError):
    """Translation was asked for but the machine cannot do it yet.

    Carries the command that fixes it, because "translation is unavailable" on
    its own has never helped anybody.
    """


def cache_root() -> Path:
    """Where converted translation models are kept."""
    from huggingface_hub.constants import HF_HUB_CACHE

    return Path(HF_HUB_CACHE).parent / CACHE_DIRNAME


def converted_dir(model_key: str) -> Path:
    """The directory a converted model lives in, whether or not it exists yet."""
    if model_key not in TRANSLATION_MODELS:
        raise ValueError(f"unknown translation model: {model_key!r}")
    return cache_root() / model_key


def is_converted(model_key: str) -> bool:
    """True if this model is converted and ready, with no network needed.

    Checks for the tokenizer as well as the weights. A conversion killed part
    way through leaves a `model.bin` that loads and a tokenizer that is not
    there, which fails later and much less clearly.
    """
    directory = converted_dir(model_key)
    if not (directory / "model.bin").is_file():
        return False
    return any(
        (directory / name).is_file()
        for name in ("tokenizer.json", "sentencepiece.bpe.model", "spiece.model")
    )


# Answers are cached because the vocabulary is a few megabytes of JSON and the
# UI asks on every change of the model menu. Deliberately *not* lru_cache: an
# empty answer must never be remembered. A model that is not converted yet
# answers with nothing, and a model prepared afterwards - by another process, or
# by a run this one did not do - would otherwise keep answering with nothing for
# as long as the server stayed up.
_LANGUAGE_CACHE: dict[str, tuple[str, ...]] = {}


def supported_target_languages(model_key: str) -> tuple[str, ...]:
    """Target codes this model will accept, read from its own vocabulary.

    Empty when the model has not been converted yet. That is deliberate: the
    codes live in the converted vocabulary, and the alternative is a
    hand-written table that goes stale silently and offers the user a language
    the model will reject.
    """
    cached = _LANGUAGE_CACHE.get(model_key)
    if cached:
        return cached

    directory = converted_dir(model_key)
    vocabulary = directory / "shared_vocabulary.json"
    if not vocabulary.is_file():
        return ()
    try:
        with open(vocabulary, encoding="utf-8") as handle:
            tokens = json.load(handle)
    except (OSError, ValueError):
        log.warning("could not read the vocabulary for %s", model_key)
        return ()

    pattern = (
        M2M100_LANG_TOKEN
        if TRANSLATION_MODELS[model_key]["family"] == "m2m100"
        else T5_LANG_TOKEN
    )
    found = set()
    for token in tokens:
        match = pattern.match(token if isinstance(token, str) else "")
        if match:
            found.add(match.group(1))
    languages = tuple(sorted(found))
    if languages:
        _LANGUAGE_CACHE[model_key] = languages
    return languages


def converted_size(model_key: str) -> int | None:
    """How much disk a converted model actually takes, or None if it is absent.

    Measured rather than predicted: int8 makes it a fraction of the download
    (1.94 GB of float32 weights convert to a 490 MB `model.bin`), and the ratio
    is not worth guessing at when the directory is right there.
    """
    directory = converted_dir(model_key)
    if not is_converted(model_key):
        return None
    try:
        return sum(f.stat().st_size for f in directory.iterdir() if f.is_file())
    except OSError:
        return None


def forget_cached_languages() -> None:
    """Test hook, and what conversion calls so a fresh model is seen at once."""
    _LANGUAGE_CACHE.clear()


def missing_requirements() -> list[str]:
    """Which translation libraries are not importable yet."""
    missing = []
    for name in TRANSLATION_REQUIREMENTS:
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    return missing


def _in_a_virtualenv() -> bool:
    return sys.prefix != sys.base_prefix


def install_requirements(
    on_line: Callable[[str], None] | None = None,
) -> list[str]:
    """Install whatever translating needs, into the environment we are running in.

    Tertius already builds its own virtual environment and pip-installs
    `requirements.txt` on first launch, so installing the rest on demand is the
    same bargain rather than a new one. It happens only when someone presses
    Download and prepare - never as a side effect of transcribing.

    Refuses to run outside a virtual environment: quietly putting 120 MB of
    torch into somebody's system Python because they clicked a button in a
    transcription app is not a thing to do. There the command is printed
    instead.

    Returns the packages it installed, so a caller can say what it did.
    """
    missing = missing_requirements()
    if not missing:
        return []

    if not _in_a_virtualenv():
        raise TranslationUnavailableError(
            "translating needs "
            + ", ".join(missing)
            + ", and Tertius is not running in a virtual environment, so it "
            "will not install them for you. Install them yourself with:\n\n"
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
            raise TranslationUnavailableError(
                "could not install " + " ".join(arguments) + ". The output above "
                "says why; the usual cause is no network."
            )

    # torch comes from the CPU index and therefore in its own call: resolving
    # the others through that index would fail, and letting pip fall back to
    # PyPI for torch is exactly what the CPU index exists to avoid.
    if "torch" in missing:
        run(["--index-url", TORCH_CPU_INDEX, "torch"])
    rest = [name for name in missing if name != "torch"]
    if rest:
        run(rest)

    still_missing = missing_requirements()
    if still_missing:
        raise TranslationUnavailableError(
            "installed, but still cannot import: " + ", ".join(still_missing)
        )
    return missing


def _require(module: str, extra: str) -> None:
    """Import a setup-only dependency, or explain exactly how to install it."""
    try:
        __import__(module)
    except ImportError as exc:
        raise TranslationUnavailableError(
            f"translation needs {module}, which is not installed. Press "
            f"Download and prepare, or install it yourself:\n\n"
            f"    pip install -e app[{extra}]\n"
        ) from exc


def ensure_translation_model(
    model_key: str,
    on_progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Return a converted model directory, downloading and converting if needed.

    Returns immediately when the model is already converted, which is every run
    after the first. The first run downloads the publisher's weights (1.9-11.8
    GB depending on the model) and converts them, which needs `torch` and
    `transformers`; neither is imported unless a conversion actually happens, so
    a machine that only transcribes never pays for them.
    """
    target = converted_dir(model_key)
    if is_converted(model_key):
        return target

    entry = TRANSLATION_MODELS[model_key]
    _require("torch", "translate")
    _require("transformers", "translate")

    from huggingface_hub import snapshot_download

    from .transcribe import _progress_tqdm_class

    patterns = TRANSLATION_FILE_PATTERNS[entry["family"]]
    kwargs: dict = {"allow_patterns": patterns}
    if on_progress is not None:
        kwargs["tqdm_class"] = _progress_tqdm_class(on_progress)
    log.info("downloading %s for translation", entry["repo"])
    source = snapshot_download(entry["repo"], **kwargs)

    # Convert into a scratch directory and move it into place only once it is
    # complete. A conversion interrupted half way through would otherwise leave
    # a directory that `is_converted` might accept, and every later run would
    # load a truncated model instead of redoing the work.
    scratch = target.with_name(target.name + ".converting")
    if scratch.exists():
        shutil.rmtree(scratch, ignore_errors=True)
    scratch.parent.mkdir(parents=True, exist_ok=True)

    from ctranslate2.converters import TransformersConverter

    # The tokenizer files ride along so the converted directory is self
    # contained - nothing later has to find its way back to the original repo.
    copy_files = [
        name
        for name in patterns
        if not name.endswith((".bin", ".safetensors"))
        and name not in CONVERTER_WRITES
        and (Path(source) / name).is_file()
    ]
    log.info("converting %s to CTranslate2 (%s)", model_key, QUANTIZATION)
    try:
        converter = TransformersConverter(source, copy_files=copy_files)
        converter.convert(str(scratch), quantization=QUANTIZATION, force=True)
    except Exception:
        shutil.rmtree(scratch, ignore_errors=True)
        raise

    scratch.replace(target)
    forget_cached_languages()
    log.info("translation model ready: %s", target)
    return target


class _M2M100Adapter:
    """M2M-100: source language token in, target language token forced out."""

    family = "m2m100"

    def __init__(self, tokenizer):
        self.tokenizer = tokenizer

    def encode(self, text: str, source_language: str) -> list[str]:
        # `src_lang` is what puts `__en__` at the front of the encoded source.
        # It is set per call rather than once, because a batch can follow a
        # transcript whose detected language differs from the last one's.
        self.tokenizer.src_lang = source_language
        return self.tokenizer.convert_ids_to_tokens(self.tokenizer.encode(text))

    def target_prefix(self, target_language: str) -> list[str]:
        return [self.tokenizer.lang_code_to_token[target_language]]

    def decode(self, tokens: Sequence[str]) -> str:
        # Drop the forced language token; it is an instruction, not output.
        body = list(tokens[1:]) if tokens else []
        return self.tokenizer.decode(
            self.tokenizer.convert_tokens_to_ids(body), skip_special_tokens=True
        )


class _T5Adapter:
    """MADLAD-400: the target language is a `<2xx>` prefix on the input text."""

    family = "t5"

    def __init__(self, tokenizer):
        self.tokenizer = tokenizer

    def encode(self, text: str, source_language: str) -> list[str]:
        # MADLAD is not told the source language at all - it works it out. The
        # argument is accepted so both adapters present one interface.
        raise NotImplementedError("T5 encodes the target, not the source")

    def encode_for(self, text: str, target_language: str) -> list[str]:
        return self.tokenizer.convert_ids_to_tokens(
            self.tokenizer.encode(f"<2{target_language}> {text}")
        )

    def target_prefix(self, target_language: str) -> list[str] | None:
        return None

    def decode(self, tokens: Sequence[str]) -> str:
        return self.tokenizer.decode(
            self.tokenizer.convert_tokens_to_ids(list(tokens)),
            skip_special_tokens=True,
        )


class Translator:
    """A loaded translation model, reused across a batch.

    Mirrors WhisperTranscriber: lazily loaded, reused for the whole run, and
    honouring the same process-wide "CUDA is broken here" memory, so a machine
    whose GPU has already failed a transcription does not go and wedge itself
    again on the translation.
    """

    def __init__(
        self,
        model_key: str,
        device: str = "auto",
        on_download_progress: Callable[[int, int], None] | None = None,
    ):
        if model_key not in TRANSLATION_MODELS:
            raise ValueError(f"unknown translation model: {model_key!r}")
        self.model_key = model_key
        self.requested_device = device
        self.on_download_progress = on_download_progress
        self._translator = None
        self._adapter = None
        self.active_device: str | None = None
        self.gpu_fallback_reason: str | None = None

    @property
    def family(self) -> str:
        return TRANSLATION_MODELS[self.model_key]["family"]

    def _resolve_device(self) -> str:
        from .transcribe import cuda_known_broken, register_cuda_dll_directories

        register_cuda_dll_directories()
        broken = cuda_known_broken()
        wanted = self.requested_device
        if wanted == "cpu":
            return "cpu"
        if broken:
            # The transcription that ran just before this one already proved the
            # GPU cannot work here, and retrying CUDA after a failure can hang
            # in native code where nothing can interrupt it.
            self.gpu_fallback_reason = broken
            return "cpu"

        import ctranslate2

        try:
            devices = ctranslate2.get_cuda_device_count()
        except Exception as exc:  # pragma: no cover - defensive
            devices = 0
            log.debug("could not count CUDA devices: %s", exc)
        if devices > 0:
            return "cuda"
        if wanted == "cuda":
            raise TranslationUnavailableError(
                "translation was asked to use the GPU, but no CUDA device is "
                "visible to CTranslate2"
            )
        self.gpu_fallback_reason = "no CUDA device was found"
        return "cpu"

    def prepare(self, on_line: Callable[[str], None] | None = None) -> Path:
        """Install what is needed, download the weights, and convert them.

        Split out from `load` so the UI can make a model ready - and so fill in
        its language menu - before anyone has committed to a run. This is the
        one place allowed to install anything, and only because a person just
        pressed a button asking for exactly this.
        """
        install_requirements(on_line)
        return ensure_translation_model(self.model_key, self.on_download_progress)

    def load(self) -> None:
        """Download, convert, and load the model now.

        Called at job start for the same reason `warmup` is: a missing model or
        an unusable device should fail before the queue has been half consumed,
        not on file nine.
        """
        if self._translator is not None:
            return
        directory = ensure_translation_model(self.model_key, self.on_download_progress)
        _require("transformers", "translate")

        import ctranslate2
        import transformers

        device = self._resolve_device()
        log.info("loading translation model %s on %s", self.model_key, device)
        try:
            translator = ctranslate2.Translator(
                str(directory), device=device, compute_type=QUANTIZATION
            )
        except Exception as exc:
            if device == "cuda":
                from .transcribe import mark_cuda_broken

                mark_cuda_broken(f"translation model failed to load on CUDA: {exc}")
                raise TranslationUnavailableError(
                    f"the translation model could not be loaded on the GPU: {exc}"
                ) from exc
            raise

        tokenizer_class = getattr(transformers, TOKENIZER_CLASSES[self.family])
        tokenizer = tokenizer_class.from_pretrained(str(directory))
        self._translator = translator
        self._adapter = (
            _M2M100Adapter(tokenizer)
            if self.family == "m2m100"
            else _T5Adapter(tokenizer)
        )
        self.active_device = device

    def translate(
        self,
        texts: Sequence[str],
        target_language: str,
        source_language: str | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[str]:
        """Translate a list of texts, preserving order and length.

        Empty and whitespace-only inputs come back unchanged rather than being
        sent to the model, which would hallucinate a sentence into a gap. The
        returned list always matches the input one for length, because callers
        zip it back onto segment timings.

        `on_progress(done, total)` is called after each batch. Translating a
        long transcript is minutes of one silent call otherwise, which in the
        UI is indistinguishable from a hang - the same reason transcription
        reports per segment.
        """
        self.load()
        adapter = self._adapter
        assert adapter is not None and self._translator is not None

        # Remember where the blanks were, so they can be put back afterwards.
        wanted = [i for i, text in enumerate(texts) if text and text.strip()]
        if not wanted:
            return list(texts)

        source_language = source_language or "en"
        if adapter.family == "t5":
            encoded = [
                adapter.encode_for(texts[i].strip(), target_language) for i in wanted
            ]
            prefixes = None
        else:
            encoded = [
                adapter.encode(texts[i].strip(), source_language) for i in wanted
            ]
            prefixes = [adapter.target_prefix(target_language)] * len(wanted)

        # Batched here rather than left to CTranslate2's own `max_batch_size`,
        # so there is somewhere to report from between batches. The work is the
        # same either way.
        out = list(texts)
        done = 0
        total = len(wanted)
        for start in range(0, total, BATCH_SIZE):
            chunk = encoded[start : start + BATCH_SIZE]
            chunk_prefixes = (
                prefixes[start : start + BATCH_SIZE] if prefixes is not None else None
            )
            results = self._translator.translate_batch(
                chunk, target_prefix=chunk_prefixes, beam_size=4
            )
            for index, result in zip(wanted[start : start + BATCH_SIZE], results):
                out[index] = adapter.decode(result.hypotheses[0]).strip()
            done += len(chunk)
            if on_progress is not None:
                # A reporting callback must never be able to fail a translation.
                try:
                    on_progress(done, total)
                except Exception:  # pragma: no cover - defensive
                    log.debug("translation progress callback failed", exc_info=True)
        return out

    def unload(self) -> None:
        self._translator = None
        self._adapter = None


def _source_code_for(translator: "Translator", detected: str | None) -> str:
    """The source language to hand the model, given what Whisper detected.

    M2M-100 must be told the source language; MADLAD works it out for itself.
    Whisper's code set and M2M-100's overlap but are not identical, so a code
    the translation model does not know falls back to English with a warning
    rather than raising - a slightly worse translation beats a failed file, and
    the code actually used is recorded on the result either way.
    """
    if translator.family == "t5":
        return ""
    known = supported_target_languages(translator.model_key)
    if detected and (not known or detected in known):
        return detected
    if detected:
        log.warning(
            "%s does not know the language Whisper detected (%s); translating "
            "as if it were English",
            translator.model_key,
            detected,
        )
    return "en"


def _provenance(translator: "Translator", target_language: str, result) -> dict:
    """Where a translation came from, for the `.json` and for the record."""
    return {
        "model": translator.model_key,
        "repo": TRANSLATION_MODELS[translator.model_key]["repo"],
        "target_language": target_language,
        "source_language": _source_code_for(translator, result.language)
        or result.language,
    }


def translated_result(
    result,
    translator: "Translator",
    target_language: str,
    on_progress: Callable[[int, int], None] | None = None,
):
    """A copy of `result` with every segment's text translated.

    Segments are translated one for one, so the timings are exactly the ones
    that were measured. Translating the transcript as a whole would read a
    little better - a model sees more context - but there would then be no
    honest way to say when any of it was said, and a `.srt` whose cues have
    drifted from the audio is worse than a slightly stiffer sentence.
    """
    from .transcribe import Segment, TranscriptionResult

    source_code = _source_code_for(translator, result.language)
    texts = [segment.text for segment in result.segments]
    rendered = translator.translate(
        texts,
        target_language,
        source_language=source_code or None,
        on_progress=on_progress,
    )
    return TranscriptionResult(
        segments=[
            Segment(start=old.start, end=old.end, text=new)
            for old, new in zip(result.segments, rendered)
        ],
        language=result.language,
        duration=result.duration,
        # Word timings describe the *source* words and do not survive
        # translation, so they are deliberately not carried over.
        words=[],
        translation=_provenance(translator, target_language, result),
    )


def prose_sentences(result) -> list[str]:
    """The transcript rejoined and re-split into sentences.

    Split out so a caller can count the work before paying for it - the queue
    needs to know how many sentences there are to report progress against.
    """
    from .alignment import split_sentences

    text = " ".join(
        segment.text.strip()
        for segment in result.segments
        if segment.text and segment.text.strip()
    )
    return split_sentences(text) if text else []


def translated_prose(
    result,
    translator: "Translator",
    target_language: str,
    on_progress: Callable[[int, int], None] | None = None,
    sentences: Sequence[str] | None = None,
) -> str:
    """The transcript translated as sentences, for reading rather than for timing.

    Whisper cuts segments for timing, not for meaning. Measured on a 38-minute
    talk: 71% of segments begin mid-sentence, 78% end without a full stop, and
    54% are fragments at both ends. Handing those to a translator one at a time
    means it renders "the doubt and gloom intensified by" with no subject and no
    end - which is how *gloom* came back as *glume*, jokes.

    So for the `.txt`, the segments are rejoined and re-split into sentences
    first - the same rejoining `segments_to_txt` already does for readability -
    and whole sentences are what the model is given. The `.srt` cannot be done
    this way: its timings belong to segments, and only a segment has them.
    """
    if sentences is None:
        sentences = prose_sentences(result)
    if not sentences:
        return ""
    source_code = _source_code_for(translator, result.language)
    rendered = translator.translate(
        list(sentences),
        target_language,
        source_language=source_code or None,
        on_progress=on_progress,
    )
    lines = [line.strip() for line in rendered if line and line.strip()]
    return "\n".join(lines) + "\n" if lines else ""


def translate_outputs(
    result,
    source,
    output_dir,
    formats,
    translator: "Translator",
    target_language: str,
    sentence_pass: bool = True,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[list[str], object]:
    """Translate a finished result and write it beside the original files.

    Two translations, not one, when `sentence_pass` is on. The `.srt` and
    `.json` carry timings, so they are translated segment by segment - the
    timings are the point and only a segment has them. The `.txt` carries no
    timings and is meant to be read, so it is translated as whole sentences,
    which the model is markedly better at. See `translated_prose`.

    With `sentence_pass` off, the `.txt` is rendered from the segment
    translation like everything else and there is only one pass. That is
    roughly four times faster and gives a `.txt` that reads badly; the setting
    exists because on a long queue that trade is the user's to make.

    Only the work that is asked for is done: a run writing no `.txt` never pays
    for the second pass whatever this is set to.

    Returns the paths written and the segment-level result. The source-language
    files are never touched: the translation lands as `talk.es.txt`, so a bad
    translation costs you nothing you already had.
    """
    from .transcribe import safe_output_path, write_atomically, write_outputs

    formats = list(formats)
    source = Path(source)
    output_dir = Path(output_dir)
    suffix = f".{target_language}"

    wants_sentences = sentence_pass and "txt" in formats
    timed_formats = [fmt for fmt in formats if not (wants_sentences and fmt == "txt")]

    # Both passes count towards one number, so the percentage only ever goes
    # up. Sentences cost more each than segments do, so it is not a time
    # estimate - but a bar that restarts half way looks broken, and a bar that
    # goes backwards looks worse.
    sentences = prose_sentences(result) if wants_sentences else []
    total = (len(result.segments) if timed_formats else 0) + len(sentences)
    done_so_far = 0

    def report(done: int, _batch_total: int) -> None:
        if on_progress is not None and total:
            on_progress(done_so_far + done, total)

    translated = (
        translated_result(result, translator, target_language, on_progress=report)
        if timed_formats
        else None
    )
    if timed_formats:
        done_so_far = len(result.segments)

    written: list[str] = []
    if timed_formats:
        written.extend(
            write_outputs(source, translated, output_dir, timed_formats, suffix=suffix)
        )

    prose = ""
    if wants_sentences:
        prose = translated_prose(
            result,
            translator,
            target_language,
            on_progress=report,
            sentences=sentences,
        )
        written.append(
            write_atomically(
                safe_output_path(output_dir, source.stem, "txt", suffix), prose
            )
        )

    if translated is None:
        # Only a `.txt` was asked for, so the segments were never translated.
        # Describe what *was* produced rather than translating a second time
        # just to have something to return: the sentences, with no timings,
        # because sentences do not have any.
        from .transcribe import Segment, TranscriptionResult

        translated = TranscriptionResult(
            segments=[
                Segment(0.0, 0.0, line) for line in prose.splitlines() if line.strip()
            ],
            language=result.language,
            duration=result.duration,
            translation=_provenance(translator, target_language, result),
        )

    log.info(
        "translated %s into %s (%d segments%s)",
        source.name,
        target_language,
        len(result.segments),
        ", plus sentences for the .txt" if wants_sentences else "",
    )
    return written, translated


def _paragraphs(text: str) -> list[list[str]]:
    """Split text into paragraphs, and each paragraph into sentences.

    The shape is kept so it can be put back: a translated file that arrives as
    one wall of text has lost something the original had.
    """
    from .alignment import split_sentences

    blocks = re.split(r"\n\s*\n", text)
    return [split_sentences(block.strip()) for block in blocks if block.strip()]


def translate_text_file(
    source,
    output_dir,
    translator: "Translator",
    target_language: str,
    formats=("txt",),
    source_language: str | None = None,
) -> tuple[list[str], object]:
    """Translate a `.txt` that has no audio behind it at all.

    Whisper is never involved. The file is split into paragraphs and sentences,
    every sentence is translated, and the paragraph breaks are put back, so the
    output has the shape the input had.

    There are no timings, so no `.srt` is written however the format chips are
    set - a subtitle file whose cues were invented would be worse than none.
    """
    from .transcribe import (
        Segment,
        TranscriptionResult,
        safe_output_path,
        write_atomically,
    )

    source = Path(source)
    text = source.read_text(encoding="utf-8")
    blocks = _paragraphs(text)
    flat = [sentence for block in blocks for sentence in block]
    if not flat:
        raise ValueError(f"there is no text to translate in {source.name}")

    rendered = translator.translate(
        flat, target_language, source_language=source_language
    )

    # Reassemble, paragraph by paragraph.
    out_blocks: list[str] = []
    cursor = 0
    for block in blocks:
        taken = rendered[cursor : cursor + len(block)]
        cursor += len(block)
        out_blocks.append("\n".join(s.strip() for s in taken if s and s.strip()))
    body = "\n\n".join(b for b in out_blocks if b) + "\n"

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    target = safe_output_path(output_dir, source.stem, "txt", f".{target_language}")
    written.append(write_atomically(target, body))

    # Times are zero throughout and deliberately so: this result exists to be
    # rendered and to carry its provenance, and there is nothing to time.
    result = TranscriptionResult(
        segments=[Segment(0.0, 0.0, line) for line in body.splitlines() if line.strip()],
        language=source_language,
        translation={
            "model": translator.model_key,
            "repo": TRANSLATION_MODELS[translator.model_key]["repo"],
            "target_language": target_language,
            "source_language": source_language,
            "from_text": True,
        },
    )

    if "json" in formats:
        from .transcribe import result_to_json

        target = safe_output_path(
            output_dir, source.stem, "json", f".{target_language}"
        )
        written.append(write_atomically(target, result_to_json(result, source)))

    log.info(
        "translated the text of %s into %s (%d sentences)",
        source.name,
        target_language,
        len(flat),
    )
    return written, result
