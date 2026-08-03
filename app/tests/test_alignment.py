"""Timestamping supplied text against a transcript."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from tertius.alignment import (
    AUTO,
    PARAGRAPH,
    SENTENCE,
    align,
    choose_granularity,
    chunk_text,
    normalise,
    render_srt,
    render_timestamped_text,
    split_paragraphs,
    split_sentences,
    words_of,
)


@dataclass
class SpokenWord:
    word: str
    start: float
    end: float


def spoken(text: str, start: float = 0.0, step: float = 1.0) -> list[SpokenWord]:
    """Turn a sentence into evenly spaced timed words."""
    words = text.split()
    return [
        SpokenWord(word=w, start=start + i * step, end=start + (i + 1) * step)
        for i, w in enumerate(words)
    ]


def test_normalise_strips_case_punctuation_and_accents():
    assert normalise("Hello,") == "hello"
    assert normalise("Café") == "cafe"
    assert normalise("'quoted'") == "quoted"
    assert words_of("The quick, brown fox!") == ["the", "quick", "brown", "fox"]


def test_split_paragraphs_on_blank_lines():
    text = "First para\nstill first.\n\n\nSecond para."
    assert split_paragraphs(text) == ["First para\nstill first.", "Second para."]


def test_split_sentences():
    text = "One thing happened. Then another! And a third? Yes."
    assert split_sentences(text) == [
        "One thing happened.",
        "Then another!",
        "And a third?",
        "Yes.",
    ]


def test_sentence_split_does_not_break_on_common_abbreviations():
    text = "Brother Russell wrote it. Mr. Smith agreed. The end."
    assert split_sentences(text) == [
        "Brother Russell wrote it.",
        "Mr. Smith agreed.",
        "The end.",
    ]


def test_auto_picks_paragraphs_when_the_text_has_them():
    text = "A short para here.\n\nAnother short para there."
    assert choose_granularity(text) == PARAGRAPH


def test_auto_picks_sentences_for_a_wall_of_text():
    text = "This is one long block. " * 30
    assert choose_granularity(text) == SENTENCE


def test_auto_picks_sentences_for_enormous_paragraphs():
    """A 'paragraph' of 300 words is useless as a timestamp unit."""
    giant = " ".join(["word"] * 300)
    assert choose_granularity(f"{giant}\n\n{giant}") == SENTENCE


def test_chunk_text_reports_what_it_chose():
    chunks, granularity = chunk_text("One. Two.", AUTO)
    assert granularity == SENTENCE
    assert [c.text for c in chunks] == ["One.", "Two."]


def test_alignment_timestamps_each_sentence():
    reference = "The cat sat down. The dog barked loudly."
    words = spoken("the cat sat down the dog barked loudly")  # 1s per word

    result = align(reference, words, SENTENCE)

    assert len(result.chunks) == 2
    first, second = result.chunks
    assert (first.start, first.end) == (0.0, 4.0)
    assert (second.start, second.end) == (4.0, 8.0)
    assert result.summary()["timed"] == 2


def test_your_wording_is_preserved_not_whispers():
    """The whole point: the output keeps the supplied text."""
    reference = "The Divine Plan of the Ages."
    words = spoken("the divine plan of the ages")  # whisper's version, lowercase

    result = align(reference, words, SENTENCE)

    assert result.chunks[0].text == "The Divine Plan of the Ages."
    assert result.chunks[0].is_timed


def test_alignment_survives_transcription_errors():
    """Whisper mishears words; enough anchors still place the chunk."""
    reference = "The quick brown fox jumps over the lazy dog."
    words = spoken("the quick brown box jumped over the lazy dog")

    result = align(reference, words, SENTENCE)

    assert result.chunks[0].is_timed
    assert result.chunks[0].matched_words >= 6


def test_text_that_is_never_spoken_is_kept_without_a_timestamp():
    """Title pages and page numbers should not be forced onto a time."""
    reference = (
        "Title Page\n\n"
        "Copyright 1916, all rights reserved\n\n"
        "The cat sat down on the mat."
    )
    words = spoken("the cat sat down on the mat")

    result = align(reference, words, PARAGRAPH)

    assert len(result.chunks) == 3
    assert result.chunks[2].is_timed
    assert not result.chunks[1].is_timed  # copyright line never spoken
    assert result.chunks[1].text.startswith("Copyright")  # but still there
    assert result.summary()["unmatched"] >= 1


def test_a_timestamp_never_runs_backwards():
    """A repeated phrase must not drag a later chunk back to minute one."""
    reference = "Alpha beta gamma. Delta epsilon zeta. Alpha beta gamma."
    words = spoken("alpha beta gamma delta epsilon zeta alpha beta gamma")

    result = align(reference, words, SENTENCE)

    times = [c.start for c in result.chunks if c.is_timed]
    assert times == sorted(times)


def test_empty_inputs_are_handled():
    assert align("", spoken("anything"), SENTENCE).chunks == []
    result = align("Some text here.", [], SENTENCE)
    assert len(result.chunks) == 1
    assert not result.chunks[0].is_timed


def test_rendered_text_keeps_every_chunk():
    reference = "Not spoken at all.\n\nThe cat sat down."
    words = spoken("the cat sat down")
    result = align(reference, words, PARAGRAPH)

    rendered = render_timestamped_text(result)

    assert "Not spoken at all." in rendered  # kept verbatim
    assert "[00:00:00.000] The cat sat down." in rendered
    # the unmatched chunk carries no timestamp marker
    assert "] Not spoken" not in rendered


def test_rendered_srt_only_contains_timed_chunks():
    reference = "Never spoken.\n\nThe cat sat down."
    words = spoken("the cat sat down")
    result = align(reference, words, PARAGRAPH)

    srt = render_srt(result)

    assert srt.startswith("1\n00:00:00,000 --> 00:00:04,000\nThe cat sat down.")
    assert "Never spoken." not in srt


def test_realistic_passage_with_front_matter():
    """Close to the actual use: a reading with unspoken front matter."""
    reference = (
        "Studies in the Scriptures\n\n"
        "Volume One, page 17\n\n"
        "The path of the just is as the shining light.\n\n"
        "Which shineth more and more unto the perfect day.\n"
    )
    words = spoken(
        "the path of the just is as the shining light "
        "which shineth more and more unto the perfect day"
    )

    result = align(reference, words, PARAGRAPH)
    summary = result.summary()

    assert summary["chunks"] == 4
    assert summary["timed"] == 2
    assert [c.text for c in result.unmatched] == [
        "Studies in the Scriptures",
        "Volume One, page 17",
    ]
    timed = result.timed
    assert timed[0].start < timed[1].start


@pytest.mark.parametrize("granularity", [AUTO, PARAGRAPH, SENTENCE])
def test_every_granularity_produces_output(granularity):
    reference = "One sentence here.\n\nAnother paragraph follows on."
    words = spoken("one sentence here another paragraph follows on")
    result = align(reference, words, granularity)
    assert result.chunks
    assert result.granularity in (PARAGRAPH, SENTENCE)
    assert render_timestamped_text(result).strip()
