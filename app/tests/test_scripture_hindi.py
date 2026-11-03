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
