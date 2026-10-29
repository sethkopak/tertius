"""Sentence breaks for Arabic Whisper writes without any.

Whisper writes Tertius's Arabic readings with no stops at all: 30 of them,
heard on 2026-10-28, came to 32 "sentences" against the 324 of the English
they were read from. madlad, handed a 150-word sentence, is unsteady with it
- one reading went into a loop (`my cup` forty times), another dropped its
title and verse - and `punctuate.py`'s model knows English, German, French
and Italian only.

`segment-any-text/sat-12l-sm` (SaT, MIT, 85 languages) marks where sentences
end in text without punctuation. Measured on those 30 readings put back into
English (2026-10-29): chrF 53.5 to 56.8, references right 60/60 kept, the
worst take 39.4 to 42.4. Two others did worse - its 3-layer sibling cut
references so madlad named Hebrews as Psalms (46/60), and an Arabic-only
AraBERT punctuation model wrote mostly commas (55.3).

SaT is published for the `wtpsplit` package, which brings scikit-learn,
pandas, skops, mosestokenizer and onnxruntime. With no lookahead set, as
here, its model is XLM-RoBERTa token classification and nothing more, so it
is loaded with `transformers` and `torch`, which translating already needs,
and `wtpsplit`'s `split()` is reproduced in `_probabilities`: windows of 510
tokens 64 apart, logits averaged, each token's on its last character, a
break wherever the sigmoid passes 0.25. On the 30 readings it gave exactly
`wtpsplit`'s splits.

Only words are labeled, never changed: a stop goes after the word a break
falls in, and none inside a scripture reference - SaT put one in 7 of 60
(`الآية. خمسة.`), and `scripture.arabic_references` reads a reference
whole. Like `punctuate.restore`, only stretches Whisper left unpunctuated are
touched.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Callable, Sequence

from .punctuate import MIN_RUN_WORDS

log = logging.getLogger(__name__)

MODEL_REPO = "segment-any-text/sat-12l-sm"
# Pinned: a different revision is a different model, and these numbers were
# measured on this one.
MODEL_REVISION = "d70c72a9331b2d5a9e82baad00c64964a23a09bb"
MODEL_FILES = ["config.json", "model.safetensors"]
# SaT ships no tokenizer of its own; it is XLM-RoBERTa's.
TOKENIZER_REPO = "facebookAI/xlm-roberta-base"
TOKENIZER_REVISION = "e73636d4f797dec63c3081bb6ed5c7b0bb3f2089"
TOKENIZER_FILES = [
    "config.json",
    "sentencepiece.bpe.model",
    "tokenizer.json",
    "tokenizer_config.json",
]
LANGUAGES = frozenset({"ar"})
# What the page calls it while it downloads, and the pinned files' sizes on
# the Hub (model.safetensors is 1,109,839,340 of it).
MODEL_LABEL = "Arabic sentence model"
DOWNLOAD_BYTES = 1_124_006_716

# `wtpsplit`'s defaults for a "-sm" model.
THRESHOLD = 0.25
BLOCK_TOKENS = 510
STRIDE_TOKENS = 64

_ENDS_SENTENCE = re.compile(r"[.!?؟…][\"'”’)\]»]*$")
_INNER_MARK = re.compile(r"[,;:،؛]")
_TRAILING = re.compile(r"[.,!?:;…،؛؟-]+$")

_model = None


def _snapshots(local_only: bool, **kwargs) -> tuple[str, str] | None:
    try:
        from huggingface_hub import snapshot_download

        return (
            snapshot_download(
                MODEL_REPO, revision=MODEL_REVISION, allow_patterns=MODEL_FILES,
                local_files_only=local_only, **kwargs,
            ),
            snapshot_download(
                TOKENIZER_REPO, revision=TOKENIZER_REVISION,
                allow_patterns=TOKENIZER_FILES, local_files_only=local_only,
            ),
        )
    except Exception as exc:
        if not local_only:
            log.warning("could not download the sentence model: %s", exc)
        return None


def ensure_model(on_progress: Callable[[int, int], None] | None = None) -> bool:
    """Download the model if it is not here yet. True when it is ready.

    Asked for only when the transcript is Arabic, so nobody else pays for
    1.1 GB. A failure is logged and is not fatal: the transcript is then
    translated as Whisper wrote it, which is what happened before.
    """
    if _snapshots(local_only=True):
        return True
    kwargs = {}
    if on_progress is not None:
        from .transcribe import _progress_tqdm_class

        kwargs["tqdm_class"] = _progress_tqdm_class(on_progress)
    log.info("downloading %s for finding sentences", MODEL_REPO)
    return _snapshots(local_only=False, **kwargs) is not None


def _load():
    """The model and tokenizer, on the CPU, loaded once. None when they cannot be."""
    global _model
    if _model is None:
        if not ensure_model():
            return None
        model_folder, tokenizer_folder = _snapshots(local_only=True)
        try:
            from pathlib import Path

            from transformers import (
                AutoTokenizer,
                XLMRobertaConfig,
                XLMRobertaForTokenClassification,
            )

            config = json.loads((Path(model_folder) / "config.json").read_text(encoding="utf-8"))
            # `xlm-token` is wtpsplit's name for it, registered only by wtpsplit.
            config["model_type"] = "xlm-roberta"
            model = XLMRobertaForTokenClassification.from_pretrained(
                model_folder, config=XLMRobertaConfig(**config)
            ).eval()
            tokenizer = AutoTokenizer.from_pretrained(tokenizer_folder)
        except Exception as exc:
            log.warning("could not load the sentence model: %s", exc)
            return None
        _model = (tokenizer, model)
    return _model


def _probabilities(text: str):
    """For each character, how likely a sentence ends there; None without the model."""
    loaded = _load()
    if loaded is None:
        return None
    import numpy as np
    import torch

    tokenizer, model = loaded
    encoded = tokenizer(text, return_offsets_mapping=True, add_special_tokens=False)
    ids, offsets = encoded["input_ids"], encoded["offset_mapping"]
    block = min(BLOCK_TOKENS, len(ids))
    logits = np.zeros(len(ids), dtype=np.float32)
    counts = np.zeros(len(ids), dtype=np.float32)
    for start in range(0, len(ids), STRIDE_TOKENS):
        end = start + block
        last = end >= len(ids)
        if last:
            end = len(ids)
            start = max(end - block, 0)
        window = [tokenizer.cls_token_id, *ids[start:end], tokenizer.sep_token_id]
        with torch.no_grad():
            out = model(
                input_ids=torch.tensor([window]), attention_mask=torch.ones(1, len(window))
            ).logits[0, 1:-1, 0].numpy()
        logits[start:end] += out
        counts[start:end] += 1
        if last:
            break
    logits /= np.maximum(counts, 1)
    chars = np.full(len(text), -np.inf, dtype=np.float32)
    for token, (_, end) in enumerate(offsets):
        if end > 0:
            chars[end - 1] = logits[token]
    return 1 / (1 + np.exp(-chars))


def _breaks(words: Sequence[str]) -> list[bool] | None:
    """Whether a sentence ends after each word; None without the model."""
    probabilities = _probabilities(" ".join(words))
    if probabilities is None:
        return None
    breaks, position = [], 0
    for word in words:
        breaks.append(bool((probabilities[position : position + len(word)] > THRESHOLD).any()))
        position += len(word) + 1
    return breaks


def _reference_spans(words: Sequence[str]) -> list[tuple[int, int]]:
    """`(first, last)` word indexes of each Arabic scripture reference."""
    from .scripture import arabic_references

    text = " ".join(words)
    starts, position = [], 0
    for word in words:
        starts.append(position)
        position += len(word) + 1
    spans = []
    for begin, end, _ in arabic_references(text):
        covered = [i for i, s in enumerate(starts) if begin <= s < end]
        if covered:
            spans.append((covered[0], covered[-1]))
    return spans


def unpunctuated_runs(words: Sequence[str]) -> list[tuple[int, int]]:
    """`(start, end)` word ranges that Whisper left unpunctuated.

    `punctuate.unpunctuated_runs`, with Arabic's own marks counted.
    """
    runs, start = [], 0
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
    """`texts` with a stop wherever SaT finds a sentence end Whisper left out.

    Each text keeps exactly its own words, so segment `i` still holds what was
    said in segment `i`. Returned unchanged when nothing needs it, the
    language is not one this is for, or the model is unavailable.
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
        stretch = words[start:end]
        breaks = _breaks(stretch)
        if breaks is None:
            return texts
        for first, last in _reference_spans(stretch):
            for i in range(first, last):
                breaks[i] = False
        breaks[-1] = False
        for offset, broken in enumerate(breaks):
            if broken:
                words[start + offset] = _TRAILING.sub("", stretch[offset]) + "."
        if not _ENDS_SENTENCE.search(words[end - 1]):
            words[end - 1] = _TRAILING.sub("", words[end - 1]) + "."
        log.info(
            "found %d sentence ends in %d unpunctuated words (%s ...)",
            sum(breaks) + 1, end - start, " ".join(words[start : start + 6]),
        )
    rebuilt: list[list[str]] = [[] for _ in texts]
    for word, index in zip(words, owner):
        rebuilt[index].append(word)
    return [" ".join(parts) if parts else texts[i] for i, parts in enumerate(rebuilt)]
