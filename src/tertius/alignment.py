"""Put timestamps onto text you already have.

The job here is *not* to produce a transcript. You supply the real text - a
script, a book chapter, a prepared reading - and Tertius works out when each
piece of it is spoken, leaving your wording exactly as you wrote it.

How it works: the audio is transcribed with per-word timings, then your text is
aligned against that transcript with a plain sequence match on normalised words.
Whisper's wording will differ here and there; alignment tolerates that, because
it only needs enough anchor words to locate each chunk in time.

Text that is never spoken - title pages, page numbers, editor's notes - simply
finds no match and is kept without a timestamp rather than being forced onto one.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field

AUTO = "auto"
PARAGRAPH = "paragraph"
SENTENCE = "sentence"
GRANULARITIES = (AUTO, PARAGRAPH, SENTENCE)

# Enough of a sentence ending to split on, without pretending to be a real
# sentence tokeniser: . ! or ? plus any closing quotes, then whitespace, then
# something that starts a new sentence. Matched rather than used as a
# lookbehind, because the closing-quote part is variable width. Common
# abbreviations are protected below.
_SENTENCE_END = re.compile(r"[.!?][\"')\]]*\s+(?=[\"'(\[]?[A-Z0-9])")
_ABBREVIATIONS = (
    "mr.",
    "mrs.",
    "ms.",
    "dr.",
    "st.",
    "vs.",
    "etc.",
    "e.g.",
    "i.e.",
    "vol.",
    "no.",
    "fig.",
    "cf.",
)
_WORD = re.compile(r"[\w']+", re.UNICODE)


@dataclass
class Chunk:
    """One unit of the supplied text, and when it is spoken."""

    text: str
    words: list[str]  # normalised, for matching
    start: float | None = None
    end: float | None = None
    matched_words: int = 0

    @property
    def is_timed(self) -> bool:
        return self.start is not None and self.end is not None


@dataclass
class AlignmentResult:
    chunks: list[Chunk] = field(default_factory=list)
    granularity: str = SENTENCE

    @property
    def timed(self) -> list[Chunk]:
        return [c for c in self.chunks if c.is_timed]

    @property
    def unmatched(self) -> list[Chunk]:
        return [c for c in self.chunks if not c.is_timed]

    def summary(self) -> dict:
        return {
            "granularity": self.granularity,
            "chunks": len(self.chunks),
            "timed": len(self.timed),
            "unmatched": len(self.unmatched),
        }


def normalise(word: str) -> str:
    """Lowercase, strip accents and punctuation - what matching compares.

    This runs on Whisper's words too, and those arrive with their punctuation
    and leading space attached (" Hello,"), so anything that is not a letter,
    digit or apostrophe has to go or nothing would line up.
    """
    folded = unicodedata.normalize("NFKD", word)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = "".join(c for c in folded if c.isalnum() or c == "'")
    return folded.lower().strip("'")


def words_of(text: str) -> list[str]:
    return [w for w in (normalise(m.group()) for m in _WORD.finditer(text)) if w]


def split_paragraphs(text: str) -> list[str]:
    """Blank-line separated blocks, with single newlines left intact."""
    blocks = re.split(r"\n\s*\n+", text.strip())
    return [b.strip() for b in blocks if b.strip()]


def split_sentences(text: str) -> list[str]:
    """Sentence-ish splitting, protecting a handful of abbreviations."""
    sentences: list[str] = []
    for paragraph in split_paragraphs(text):
        flat = re.sub(r"\s*\n\s*", " ", paragraph)
        pieces: list[str] = []
        cursor = 0
        for boundary in _SENTENCE_END.finditer(flat):
            # Keep the terminator with the sentence it ends.
            pieces.append(flat[cursor : boundary.end()].strip())
            cursor = boundary.end()
        pieces.append(flat[cursor:].strip())

        # Re-join pieces that were split after a known abbreviation.
        merged: list[str] = []
        for piece in pieces:
            if merged and merged[-1].lower().endswith(_ABBREVIATIONS):
                merged[-1] = f"{merged[-1]} {piece}"
            else:
                merged.append(piece)
        sentences.extend(p.strip() for p in merged if p.strip())
    return sentences


def choose_granularity(text: str) -> str:
    """What `auto` decides.

    Paragraphs if the text actually has them and they are short enough to be a
    useful timestamp unit; otherwise sentences. A wall of text with no blank
    lines gets sentences, which is the only thing that would be useful there.
    """
    paragraphs = split_paragraphs(text)
    if len(paragraphs) < 2:
        return SENTENCE
    average_words = sum(len(words_of(p)) for p in paragraphs) / len(paragraphs)
    return PARAGRAPH if average_words <= 120 else SENTENCE


def chunk_text(text: str, granularity: str = AUTO) -> tuple[list[Chunk], str]:
    if granularity == AUTO:
        granularity = choose_granularity(text)
    if granularity == PARAGRAPH:
        pieces = split_paragraphs(text)
    elif granularity == SENTENCE:
        pieces = split_sentences(text)
    else:
        raise ValueError(f"unknown granularity: {granularity!r}")
    return [Chunk(text=p, words=words_of(p)) for p in pieces], granularity


def align(
    reference_text: str,
    spoken_words: list,
    granularity: str = AUTO,
) -> AlignmentResult:
    """Time each chunk of `reference_text` using timed `spoken_words`.

    `spoken_words` are the transcript's words; each needs `.word`, `.start` and
    `.end`. Chunks that match nothing keep their text and get no timestamp.
    """
    chunks, resolved = chunk_text(reference_text, granularity)
    result = AlignmentResult(chunks=chunks, granularity=resolved)
    if not chunks:
        return result

    spoken_tokens = [normalise(getattr(w, "word", "") or "") for w in spoken_words]
    spoken_tokens = [t for t in spoken_tokens]
    reference_tokens: list[str] = []
    owner: list[int] = []  # which chunk each reference token belongs to
    for index, chunk in enumerate(chunks):
        for word in chunk.words:
            reference_tokens.append(word)
            owner.append(index)

    if not reference_tokens or not spoken_tokens:
        return result

    matcher = difflib.SequenceMatcher(
        None, reference_tokens, spoken_tokens, autojunk=False
    )
    # For every chunk, collect the times of the spoken words it matched.
    starts: dict[int, float] = {}
    ends: dict[int, float] = {}
    counts: dict[int, int] = {}
    for ref_start, spoken_start, size in matcher.get_matching_blocks():
        for offset in range(size):
            chunk_index = owner[ref_start + offset]
            spoken = spoken_words[spoken_start + offset]
            start = getattr(spoken, "start", None)
            end = getattr(spoken, "end", None)
            if start is None or end is None:
                continue
            counts[chunk_index] = counts.get(chunk_index, 0) + 1
            if chunk_index not in starts or start < starts[chunk_index]:
                starts[chunk_index] = start
            if chunk_index not in ends or end > ends[chunk_index]:
                ends[chunk_index] = end

    for index, chunk in enumerate(chunks):
        if index in starts:
            chunk.start = starts[index]
            chunk.end = max(ends[index], starts[index])
            chunk.matched_words = counts.get(index, 0)

    _enforce_forward_order(result.chunks)
    return result


def _enforce_forward_order(chunks: list[Chunk]) -> None:
    """Stop a stray match sending a timestamp backwards.

    A repeated phrase can match far away from where it belongs. Timestamps that
    would move backwards are dropped rather than emitted wrong - saying nothing
    beats pointing at the wrong minute of audio.
    """
    latest = 0.0
    for chunk in chunks:
        if not chunk.is_timed:
            continue
        if chunk.start < latest - 0.5:  # small tolerance for overlap
            chunk.start = chunk.end = None
            chunk.matched_words = 0
            continue
        latest = max(latest, chunk.start)


def format_timestamp(seconds: float, separator: str = ",") -> str:
    if seconds is None or seconds < 0:
        seconds = 0.0
    millis = int(round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def render_timestamped_text(result: AlignmentResult) -> str:
    """The supplied text, unchanged, with a timestamp in front of each chunk.

    Unmatched chunks are kept verbatim and simply carry no timestamp.
    """
    lines: list[str] = []
    for chunk in result.chunks:
        if chunk.is_timed:
            lines.append(f"[{format_timestamp(chunk.start, '.')}] {chunk.text}")
        else:
            lines.append(chunk.text)
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def render_srt(result: AlignmentResult) -> str:
    """Subtitles carrying your wording, not Whisper's."""
    blocks = []
    for index, chunk in enumerate(result.timed, start=1):
        blocks.append(
            f"{index}\n"
            f"{format_timestamp(chunk.start)} --> {format_timestamp(chunk.end)}\n"
            f"{chunk.text}\n"
        )
    return "\n".join(blocks)
