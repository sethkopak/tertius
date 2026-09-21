"""Adding niqqud to Hebrew text before it is read aloud.

Hebrew is written without vowels. A reader supplies them from knowing the
word; a speech model cannot, and Chatterbox does not try - it expects text
that already carries the vowel points (niqqud) and guesses when it does not.

**Guessing produces fluent Hebrew made of the wrong words.** Measured on a
devotional translated into Hebrew, read aloud and transcribed back:

    text        תהילים 66:8,9              "Psalms 66:8,9"
    spoken as   תאים שישים ושמונה תש       a non-word, then "sixty-eight"

The book name was gone and the chapter had changed. Whisper still detected the
audio as Hebrew with probability 0.93, which is the trap: it *sounds* like
Hebrew, so nothing downstream reports a problem. With niqqud added first, the
same line came back `תהילים 66, 8, 9` - correct.

**Order matters.** Digits must be spelled out *before* diacritization, not
after. Diacritizing first leaves the spelled numbers bare and `66` still comes
back as `60`. See `Speaker.speak` in speech.py, which is the only caller.

**Why this file exists at all.** Chatterbox has a hook for exactly this and it
cannot work: `tokenizer.py` calls `Dicta()` with no arguments, while the
`dicta_onnx` package it imports requires a model path. Installing that package
only changes the warning from "not available" to "diacritization failed". It
also carries no licence of any kind - no LICENSE file, no `license` field -
which makes it unshippable here regardless.

The *model* is clean, and is the same one that package wraps:
`dicta-il/dictabert-large-char-menaked`, CC-BY-4.0, ungated. See
THIRD-PARTY-NOTICES.md.

**The model class below is vendored from that repository** rather than loaded
with `trust_remote_code=True`, so no code from the Hub is ever executed here -
the same reasoning that makes translate.py convert its own checkpoints instead
of trusting a stranger's upload. It is CC-BY-4.0 and the changes made to it are
listed in the class docstring.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Sequence

log = logging.getLogger(__name__)

MODEL_REPO = "dicta-il/dictabert-large-char-menaked"
MODEL_FILES = ("config.json", "model.safetensors", "tokenizer.json")

# Which languages need this. Only Hebrew for now: Arabic is also an abjad and
# probably has the same defect, but Chatterbox has no equivalent hook for it
# and nothing has measured it.
DIACRITIZED_LANGUAGES = frozenset({"he"})

# A Hebrew letter, and the vowel points that may be hung on one.
_ALEF, _TAV = ord("א"), ord("ת")
_NIQQUD = re.compile(r"[ְ-ׇֽׁׂ]")
# Letters that can stand in for a vowel rather than carry one.
_MATRES = frozenset("אוי")


def has_hebrew(text: str) -> bool:
    return any(_ALEF <= ord(ch) <= _TAV for ch in text or "")


def strip_niqqud(text: str) -> str:
    return _NIQQUD.sub("", text or "")


def _build_model_class():
    """The vendored `BertForDiacritization`, built lazily so torch stays optional.

    Adapted from `BertForDiacritization.py` in the model repository named
    above, (c) Dicta, CC-BY-4.0. Changes from the original:

    * Only the parts needed to run a forward pass are kept. The training
      losses, the `MenakedLabels` plumbing and the original `predict` are
      dropped - `predict` because it does not work here at all, for the reason
      in `Diacritizer.add_niqqud` below.
    * The two classifier heads are inlined rather than held in a `BertMenakedHead`
      submodule wrapper; the parameter names are unchanged, so the published
      weights load as they are.
    """
    import torch
    from torch import nn
    from transformers import BertModel, BertPreTrainedModel

    class BertMenakedHead(nn.Module):
        def __init__(self, config):
            super().__init__()
            self.config = config
            self.nikud_cls = nn.Linear(config.hidden_size, len(config.nikud_classes))
            self.shin_cls = nn.Linear(config.hidden_size, len(config.shin_classes))

        def forward(self, hidden_states):
            return self.nikud_cls(hidden_states), self.shin_cls(hidden_states)

    class BertForDiacritization(BertPreTrainedModel):
        def __init__(self, config):
            super().__init__(config)
            self.config = config
            self.bert = BertModel(config, add_pooling_layer=False)
            dropout = (
                config.classifier_dropout
                if config.classifier_dropout is not None
                else config.hidden_dropout_prob
            )
            self.dropout = nn.Dropout(dropout)
            self.menaked = BertMenakedHead(config)
            self.post_init()

        @torch.no_grad()
        def diacritics(self, input_ids, attention_mask):
            hidden = self.bert(
                input_ids, attention_mask=attention_mask, return_dict=True
            ).last_hidden_state
            nikud, shin = self.menaked(self.dropout(hidden))
            return nikud.argmax(dim=-1).tolist(), shin.argmax(dim=-1).tolist()

    return BertForDiacritization


@dataclass
class _Loaded:
    model: object
    tokenizer: object
    nikud_classes: list
    shin_classes: list
    mat_lect: str
    device: str


class Diacritizer:
    """Adds niqqud to Hebrew text. Loaded once, reused across a batch."""

    def __init__(self, device: str = "auto"):
        self.requested_device = device
        self._loaded: _Loaded | None = None

    @property
    def ready(self) -> bool:
        return self._loaded is not None

    def load(self) -> None:
        if self._loaded is not None:
            return

        import torch
        from huggingface_hub import hf_hub_download
        from safetensors.torch import load_file
        from tokenizers import Tokenizer
        from transformers import BertConfig

        paths = {name: hf_hub_download(MODEL_REPO, name) for name in MODEL_FILES}

        # **The tokenizer is loaded from `tokenizer.json` directly, not through
        # `AutoTokenizer`.** This is the whole reason the published `predict`
        # cannot be used: on transformers 5.16 `AutoTokenizer` returns a
        # tokenizer that renders every Hebrew word as a single `[UNK]` with
        # word-level offsets, where this model is character-level and needs one
        # token per letter. The decode loop keys on `offsets[1] - offsets[0] ==
        # 1`, so with word-level offsets nothing matches, the cursor never
        # advances, and the output is the input repeated in growing prefixes.
        #
        # The same file read by `tokenizers` gives one token per character with
        # correct offsets, so that is what is used.
        tokenizer = Tokenizer.from_file(paths["tokenizer.json"])

        config = BertConfig.from_pretrained(paths["config.json"])
        model = _build_model_class()(config)
        model.load_state_dict(load_file(paths["model.safetensors"]), strict=False)
        model.eval()

        device = self.requested_device
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        try:
            model.to(device)
        except Exception:
            log.warning("could not put the diacritizer on %s; using cpu", device)
            device = "cpu"
            model.to(device)

        self._loaded = _Loaded(
            model=model,
            tokenizer=tokenizer,
            nikud_classes=list(config.nikud_classes),
            shin_classes=list(config.shin_classes),
            mat_lect=config.mat_lect_token,
            device=device,
        )
        log.info("diacritizer ready on %s", device)

    def unload(self) -> None:
        self._loaded = None

    def add_niqqud(self, text: str) -> str:
        """Return `text` with vowel points added. Unchanged if it cannot help.

        Never raises. A reading that goes out without niqqud is wrong in a way
        only a Hebrew speaker will notice; a reading that does not happen is
        wrong in a way everyone notices, and this is not worth the second.
        """
        if not text or not has_hebrew(text):
            return text
        try:
            self.load()
            return self._run(strip_niqqud(text))
        except Exception:
            log.warning("could not add niqqud; speaking the text as it is",
                        exc_info=True)
            return text

    def _run(self, sentence: str) -> str:
        import torch

        state = self._loaded
        assert state is not None
        encoded = state.tokenizer.encode(sentence)
        ids = torch.tensor([encoded.ids], device=state.device)
        mask = torch.tensor([encoded.attention_mask], device=state.device)
        nikud_ids, shin_ids = state.model.diacritics(ids, mask)
        nikud_ids, shin_ids = nikud_ids[0], shin_ids[0]

        out: list[str] = []
        cursor = 0
        for index, (start, end) in enumerate(encoded.offsets):
            if start > cursor:
                out.append(sentence[cursor:start])
            if end - start != 1:            # [CLS], [SEP], and anything merged
                continue
            char = sentence[start:end]
            cursor = end
            if not (_ALEF <= ord(char) <= _TAV):
                out.append(char)
                continue

            nikud = state.nikud_classes[nikud_ids[index]]
            shin = "" if char != "ש" else state.shin_classes[shin_ids[index]]
            if nikud == state.mat_lect:
                # A letter standing in for a vowel carries no point of its own.
                if char not in _MATRES:
                    nikud = ""
                else:
                    continue
            out.append(char + shin + nikud)
        out.append(sentence[cursor:])
        return "".join(out)
