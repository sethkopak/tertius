"""Scripture references in Hindi, as Whisper writes Tertius's Hindi readings.

See `scripture.hindi_references`. Every heard form here is one Whisper
wrote, hearing the ten harness files read in Hindi (2026-11-01).
"""

from __future__ import annotations

import pytest

from tertius.scripture import hindi_references, mask, restore
from tertius.segment import _reference_spans


@pytest.mark.parametrize(
    "heard, citation",
    [
        ("सकता, इबरानियों के नाम पत्री अध्याय 13 वचन 6 जीवन", "Hebrews 13:6"),
        ("बह रहा है भजन सहीता अध्याय 23 वचन 5", "Psalm 23:5"),
        ("लें, रोमियो के नाम पत्री अध्याई 13, वचन 12, अंधकार", "Romans 13:12"),
        ("बढ़ें, पत्रस की दूसरी पत्री अध्याय एक वचन पांच, इसका", "2 Peter 1:5"),
        ("करें फिलिपियों के नाम पत्री अध्याय चार वचन चार 26", "Philippians 4:4"),
        # The chapter word split from the book's.
        ("नहीं जानते याकुब की पत्रिय ध्याय चार वचन तीन इसका", "James 4:3"),
        ("रहो फिलिप्यों के नाम पत्रिय ध्याय 4 वचन 4 इसाई", "Philippians 4:4"),
        # Numbers misheard: सात as साथ, बारह as बारा, आठ as आर्ट, तीन as टीन.
        ("है इबरानियों के नाम पत्री अध्याई 12 वचन साथ किसी", "Hebrews 12:7"),
        ("हैं इबलानियों के नाम पत्री अध्याई बारा वचन साथ 20", "Hebrews 12:7"),
        ("तीमुतियूज के नाम पहली पत्री अध्याय पांच, वचन आर्ट, विश्वास", "1 Timothy 5:8"),
        ("है, इबरानियों के नाम पत्री अध्याए 12 वचन टीन, इन", "Hebrews 12:3"),
        ("ले रोमियों के नाम पत्री अध्याय तेरह वचन बारा तीन", "Romans 13:12"),
        # The verse word misheard, or run onto its number.
        ("दीमुतियूस के नाम पहली पत्री अध्याई पांच बचन आठ 23", "1 Timothy 5:8"),
        ("रहे इबरानियों के नाम पत्री अध्याई बारा वचंतीन पांच अक्टूबर", "Hebrews 12:3"),
        ("२ पतरस की दूसरी पत्री अध्याय १ वचन ५", "2 Peter 1:5"),
    ],
)
def test_a_heard_reference_is_named_in_english(heard, citation):
    assert [found[2] for found in hindi_references(heard)] == [citation]


@pytest.mark.parametrize(
    "heard",
    [
        # `तैस` is as like 10 as 23.
        "परनत अधिक, भजन सभीता अध्याई, तैस वचन पांच,",
        # `तरीज` is like no number.
        "वैरा है भजन सहीता अध्याय तरीज वचन पांच",
        # No verse.
        "इबरानियों के नाम पत्री अध्याय यह इस तरह",
        # No book before it.
        "इस कहानी का अध्याय 12 वचन 7 है",
        # "Attention", not a chapter.
        "हम इस बात का ध्यान रखते हैं कि हमारा",
        "यहाँ कोई संदर्भ नहीं है",
    ],
)
def test_nothing_is_taken_for_a_reference_that_is_not_one(heard):
    assert hindi_references(heard) == []


def test_the_reference_is_masked_and_comes_back_in_english():
    heard = "कब से पानी बह रहा है भजन सहीता अध्याय 23 वचन 5 इसकी दो शाखाएँ हैं"
    masked, taken = mask(heard)
    assert taken == ["Psalm 23:5"]
    assert "अध्याय" not in masked
    assert restore(masked, taken, language="en").count("Psalm 23:5") == 1


def test_no_sentence_ends_inside_it():
    words = "प्रकाश के हथियार बहन लें रोमियो के नाम पत्री अध्याई 13 वचन 12 अंधकार के".split()
    assert _reference_spans(words) == [(5, 12)]


# The 22 books Wikidata has no Hindi name for, named from the IRV
# (tools/fetch_book_names.py, SUPPLEMENTS). Written by hand in the form the
# readings say them - none of these books is in the harness files, so no
# Whisper hearing of them exists yet.
@pytest.mark.parametrize(
    "heard, citation",
    [
        ("है एक शमूएल अध्याय तीन वचन सोलह इस", "1 Samuel 3:16"),
        ("है 1 शमूएल अध्याय 3 वचन 16", "1 Samuel 3:16"),
        ("दो शमूएल अध्याय पांच वचन एक", "2 Samuel 5:1"),
        ("एक राजाओं अध्याय पांच वचन एक", "1 Kings 5:1"),
        ("दो राजाओं अध्याय पांच वचन एक", "2 Kings 5:1"),
        ("2 इतिहास अध्याय सात वचन चौदह", "2 Chronicles 7:14"),
        ("लूका अध्याय 12 वचन 31", "Luke 12:31"),
        ("होशे अध्याय छह वचन छह", "Hosea 6:6"),
        ("विलापगीत अध्याय तीन वचन बाईस", "Lamentations 3:22"),
        ("नहेम्याह अध्याय आठ वचन दस", "Nehemiah 8:10"),
        ("मलाकी अध्याय तीन वचन छह", "Malachi 3:6"),
    ],
)
def test_a_book_named_from_the_irv_is_read(heard, citation):
    assert [found[2] for found in hindi_references(heard)] == [citation]


def test_a_numbered_book_without_its_number_is_left_alone():
    """`1 शमूएल` and `2 शमूएल` differ only by the number. Before, both folded
    to one sound and every Samuel came back as 2 Samuel."""
    assert hindi_references("शमूएल अध्याय पांच वचन एक") == []


def test_every_book_has_a_hindi_name_and_wikidata_wins():
    import sys
    from pathlib import Path

    from tertius.scripture import _table

    tools = Path(__file__).resolve().parents[1] / "tools"
    sys.path.insert(0, str(tools))
    try:
        import fetch_book_names
    finally:
        sys.path.remove(str(tools))

    table = _table()
    assert all(entry["labels"].get("hi") for entry in table.values())
    supplied = fetch_book_names.SUPPLEMENTS["hi"]["names"]
    # A supplement fills a gap and never replaces a Wikidata label.
    copy = {"books": {"Genesis": {"labels": {"hi": "Wikidata"}},
                      **{name: {"labels": {}} for name in supplied}}}
    fetch_book_names.SUPPLEMENTS["hi"]["names"]["Genesis"] = "IRV"
    try:
        fetch_book_names.supplement(copy)
    finally:
        del fetch_book_names.SUPPLEMENTS["hi"]["names"]["Genesis"]
    assert copy["books"]["Genesis"]["labels"]["hi"] == "Wikidata"
    assert "Genesis" not in copy["supplements"]["hi"]["books"]
    assert copy["books"]["Luke"]["labels"]["hi"] == "लूका"
