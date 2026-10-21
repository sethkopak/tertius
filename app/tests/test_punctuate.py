"""Restoring punctuation where Whisper left none.

The model itself is not loaded here; `_label` is replaced with a stand-in.
What it did on real transcripts is recorded in punctuate.py.
"""

from __future__ import annotations

import pytest

from tertius import punctuate
from tertius.punctuate import MIN_RUN_WORDS, restore, unpunctuated_runs

# 0510 as Whisper wrote it: one window, no stops, no capitals.
BROKEN = (
    "manna for may 10th thou anointest my head with oil my cup runneth over "
    "psalm 23 verse 5 the fullness of the cup running over has a double "
    "significance it is a cup of joy and a cup of sorrow and in both respects "
    "it overflows he who would partake of the joys of the lord must also partake"
)


def _labels_at(**marks):
    """A stand-in model: `word=mark` puts that mark after that word."""

    def label(words):
        return [marks.get(w, "0") for w in words]

    return label


def test_a_long_stretch_with_no_punctuation_is_found():
    words = BROKEN.split()
    assert len(words) >= MIN_RUN_WORDS
    assert unpunctuated_runs(words) == [(0, len(words))]


def test_a_long_sentence_full_of_commas_is_left_alone():
    """0120's 96-word sentence is real, with fifteen commas in it."""
    words = ("It needs the sunshine of love, frequent watering, much cultivating, " * 8).split()
    words[-1] += "."
    assert unpunctuated_runs(words) == []


def test_words_are_kept_and_each_segment_keeps_its_own(monkeypatch):
    monkeypatch.setattr(punctuate, "_label", _labels_at(**{"10th": ".", "oil": ".", "over": "."}))
    first, second = BROKEN.split(" psalm ")
    out = restore([first, "psalm " + second], "en")

    assert out[0].startswith("Manna for may 10th. Thou anointest my head with oil. My cup runneth over.")
    assert out[1].startswith("Psalm 23 verse 5")
    assert " ".join(out).replace(".", "").lower().split() == BROKEN.split()


def test_a_stop_inside_a_reference_moves_in_front_of_it(monkeypatch):
    """`amiss james. Chapter 4, verse 3:` became `amiss. James chapter 4 verse 3.`"""
    text = "ye ask and receive not because ye ask amiss james chapter 4 verse 3 " + BROKEN
    monkeypatch.setattr(punctuate, "_label", _labels_at(james=".", **{"3": ":"}))
    [out] = restore([text], "en")

    assert "ye ask amiss. James chapter 4 verse 3. Manna for may" in out


def test_only_the_languages_the_model_knows(monkeypatch):
    monkeypatch.setattr(punctuate, "_label", _labels_at(oil="."))
    assert restore([BROKEN], "ru") == [BROKEN]
    assert restore([BROKEN], None) == [BROKEN]


def test_without_the_model_the_text_is_unchanged(monkeypatch):
    monkeypatch.setattr(punctuate, "_label", lambda words: None)
    assert restore([BROKEN], "en") == [BROKEN]


@pytest.mark.parametrize("text", ["Manna for June 16th. No chastening seemeth joyous.", ""])
def test_punctuated_or_empty_text_never_reaches_the_model(monkeypatch, text):
    def refuse(words):
        raise AssertionError("the model should not have been asked")

    monkeypatch.setattr(punctuate, "_label", refuse)
    assert restore([text], "en") == [text]
