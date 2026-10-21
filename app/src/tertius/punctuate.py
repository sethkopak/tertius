"""Putting back the punctuation Whisper sometimes leaves out.

Whisper decides early whether a recording is punctuated prose or a run of
lowercase words, and now and then picks the second for a whole 30 s window.
Measured on 2026-10-20, ten Manna recordings: three came back with an opening
window of 90-150 words in lowercase with no stops at all (`manna for may
10th thou anointest my head with oil my cup runneth over psalm 23 verse 5
the fullness ...`). The sentence pass then hands the translator 150 words
as one sentence, and madlad wrote word salad into Chinese with the English
`yieldeth` left in it.

Prompting Whisper does not fix it. A punctuated `initial_prompt` or
`hotwords` gave punctuation and **lost words**: 0510 dropped its whole title
and verse (149 -> 131 words), 0616 a third of its text. Turning timestamps
off lost more. Losing words is worse than losing commas.

So the words are left exactly as Whisper heard them, and a punctuation model
labels each one with what follows it. A word classifier cannot drop or add a
word. `oliverguhr/fullstop-punctuation-multilang-large` (MIT, trained on
English, German, French and Italian speech transcripts) kept all 149, 168
and 137 words of the three broken files, under a second each on the CPU.

It only touches the broken stretches. Run over text Whisper had punctuated,
it made it worse (`grievous Nevertheless.`), so a stretch is repunctuated
only when it is long and has almost no punctuation in it - which a long but
real sentence, full of commas, does not match.
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Sequence

log = logging.getLogger(__name__)

MODEL_REPO = "oliverguhr/fullstop-punctuation-multilang-large"
# Pinned: a different revision is a different model, and these numbers were
# measured on this one.
MODEL_REVISION = "345e80adc07e761d3a35feafd20f2f44a151f453"
MODEL_FILES = [
    "config.json",
    "model.safetensors",
    "sentencepiece.bpe.model",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
]
# What the model was trained on. Anything else is left as Whisper wrote it.
LANGUAGES = frozenset({"en", "de", "fr", "it"})

# A stretch between sentence ends at least this long, with fewer than one
# comma, colon or semicolon per this many words, is taken to be unpunctuated.
# The broken stretches measured were 91-149 words with none at all; the
# longest real sentence in the same ten files was 96 words with 15 commas.
MIN_RUN_WORDS = 40

# The model reads 512 tokens at most. Windows of words, overlapping so no
# word is labeled without context on both sides.
WINDOW_WORDS = 200
STEP_WORDS = 180

_ENDS_SENTENCE = re.compile(r"[.!?…][\"'”’)\]]*$")
_INNER_MARK = re.compile(r"[,;:]")
_TRAILING = re.compile(r"[.,!?:;…-]+$")

_model = None


def _cached_snapshot() -> str | None:
    try:
        from huggingface_hub import snapshot_download

        return snapshot_download(
            MODEL_REPO,
            revision=MODEL_REVISION,
            allow_patterns=MODEL_FILES,
            local_files_only=True,
        )
    except Exception:
        return None


def ensure_model(on_progress: Callable[[int, int], None] | None = None) -> str | None:
    """Download the model if it is not here yet. Returns its folder, or None.

    Called at job start, beside the translation model's own download, so the
    2.2 GB arrives before any work begins rather than in the middle of a
    file. A failure is logged and is not fatal: the transcript is then
    translated as Whisper punctuated it, which is what happened before.
    """
    cached = _cached_snapshot()
    if cached:
        return cached
    try:
        from huggingface_hub import snapshot_download

        kwargs = {}
        if on_progress is not None:
            from .transcribe import _progress_tqdm_class

            kwargs["tqdm_class"] = _progress_tqdm_class(on_progress)
        log.info("downloading %s for restoring punctuation", MODEL_REPO)
        return snapshot_download(
            MODEL_REPO, revision=MODEL_REVISION, allow_patterns=MODEL_FILES, **kwargs
        )
    except Exception as exc:
        log.warning("could not download the punctuation model: %s", exc)
        return None


def _load():
    """The model, on the CPU, loaded once. None when it cannot be."""
    global _model
    if _model is None:
        folder = _cached_snapshot()
        if folder is None:
            return None
        try:
            import torch  # noqa: F401
            from transformers import AutoModelForTokenClassification, AutoTokenizer

            tokenizer = AutoTokenizer.from_pretrained(folder)
            model = AutoModelForTokenClassification.from_pretrained(folder).eval()
        except Exception as exc:
            log.warning("could not load the punctuation model: %s", exc)
            return None
        _model = (tokenizer, model)
    return _model


def _label(words: Sequence[str]) -> list[str] | None:
    """One label per word: "0" for nothing, or the mark that follows it."""
    loaded = _load()
    if loaded is None:
        return None
    import torch

    tokenizer, model = loaded
    id2label = model.config.id2label
    labels: list[str] = ["0"] * len(words)
    start = 0
    while start < len(words):
        window = list(words[start : start + WINDOW_WORDS])
        last = start + len(window) >= len(words)
        keep = len(window) if last else STEP_WORDS
        encoded = tokenizer(
            window, is_split_into_words=True, return_tensors="pt",
            truncation=True, max_length=512,
        )
        with torch.no_grad():
            predicted = model(**encoded).logits.argmax(-1)[0].tolist()
        seen: set[int] = set()
        for position, word in enumerate(encoded.word_ids()):
            if word is None or word in seen:
                continue
            seen.add(word)
            if word < keep:
                labels[start + word] = id2label[predicted[position]]
        if last:
            break
        start += STEP_WORDS
    return labels


def _reference_spans(words: Sequence[str]) -> list[tuple[int, int]]:
    """`(first, last)` word indexes of each scripture reference.

    The model put a stop in the middle of one: `amiss james. Chapter 4, verse
    3:`. A reference is one unit, and the scripture code downstream has to
    find it whole.
    """
    from .scripture import find_references

    text = " ".join(words)
    starts = []
    position = 0
    for word in words:
        starts.append(position)
        position += len(word) + 1
    spans = []
    for begin, end in find_references(text):
        covered = [i for i, s in enumerate(starts) if begin <= s < end]
        if covered:
            spans.append((covered[0], covered[-1]))
    return spans


def unpunctuated_runs(words: Sequence[str]) -> list[tuple[int, int]]:
    """`(start, end)` word ranges that Whisper left unpunctuated."""
    runs = []
    start = 0
    for i, word in enumerate(words):
        if _ENDS_SENTENCE.search(word) or i == len(words) - 1:
            end = i + 1
            stretch = words[start:end]
            marks = sum(1 for w in stretch[:-1] if _INNER_MARK.search(w))
            if len(stretch) >= MIN_RUN_WORDS and marks * MIN_RUN_WORDS < len(stretch):
                runs.append((start, end))
            start = end
    return runs


def restore(texts: Sequence[str], language: str | None) -> list[str]:
    """`texts` with punctuation restored in any stretch Whisper left without.

    Each text keeps exactly its own words, so segment `i` still holds what was
    said in segment `i`. Returned unchanged when nothing needs it, the
    language is not one the model knows, or the model is unavailable.
    """
    texts = list(texts)
    if (language or "").lower() not in LANGUAGES:
        return texts
    words: list[str] = []
    owner: list[int] = []
    for index, text in enumerate(texts):
        for word in (text or "").split():
            words.append(word)
            owner.append(index)
    runs = unpunctuated_runs(words)
    if not runs:
        return texts
    for start, end in runs:
        bare = [_TRAILING.sub("", w) or w for w in words[start:end]]
        labels = _label(bare)
        if labels is None:
            return texts
        for first, last in _reference_spans(bare):
            # A stop the model put inside the reference marks a boundary it
            # heard there; it belongs before the reference, and the reference
            # then ends its own sentence: `amiss. James chapter 4 verse 3.`
            stopped = any(labels[i] in (".", "?") for i in range(first, last))
            for i in range(first, last):
                labels[i] = "0"
            if stopped:
                if first > 0:
                    labels[first - 1] = "."
                if labels[last] not in (".", "?"):
                    labels[last] = "."
        capitalize = True
        for offset, (word, label) in enumerate(zip(bare, labels)):
            if capitalize and word[:1].islower():
                word = word[:1].upper() + word[1:]
            is_last = offset == len(bare) - 1
            if is_last:
                # The stretch ends on a stop Whisper did write, or on nothing;
                # either way the model gets no say over its final word.
                tail = _TRAILING.search(words[end - 1])
                word += tail.group(0) if tail else "."
            elif label != "0":
                word += label
            capitalize = word.endswith((".", "?"))
            words[start + offset] = word
        log.info(
            "restored punctuation in %d unpunctuated words (%s ...)",
            end - start,
            " ".join(words[start : start + 6]),
        )
    rebuilt: list[list[str]] = [[] for _ in texts]
    for word, index in zip(words, owner):
        rebuilt[index].append(word)
    return [" ".join(parts) if parts else texts[i] for i, parts in enumerate(rebuilt)]
