"""Scripture references in Arabic, as Whisper writes Tertius's Arabic readings.

See `scripture.arabic_references`. Every heard form here is one Whisper
wrote, hearing the ten harness files read in Arabic (2026-10-28/29).
"""

from __future__ import annotations

import pytest

from tertius.scripture import arabic_references, mask, restore


@pytest.mark.parametrize(
    "heard, citation",
    [
        ("يغمر سفر المزامير الإصحاح 23 الآية 5", "Psalm 23:5"),
        ("خطأ رسالة يعقوب الإصحاح أربعة الآية ثلاثة فلنتعلم", "James 4:3"),
        ("النور الرسالة إلى أهل روما الإصحاح 13 الآية 12 إن أعمال", "Romans 13:12"),
        ("الرسالة إلى العبرانيين، الإصحاح 12، الآية 3، وللأسف", "Hebrews 12:3"),
        # Misheard books.
        ("الرسالة إلى الأبرانيين الإصحاح أثنى عشر الآية سبعة", "Hebrews 12:7"),
        ("يفيد صفر المزامير الإصحاح ثلاثة وعشرون الآية 5", "Psalm 23:5"),
        ("رسالة بترسي الثانية الإصحاح واحد الآية خمسة أحد الصعوبات", "2 Peter 1:5"),
        ("فرحوا الرسالة إلى أهرف البي الإصحاح أربعة الآية أربعة", "Philippians 4:4"),
        # Timothy heard as two words.
        ("الرسالة الأولى إلى تيمو ثاوس الإصحاح خمسة الآية ثمانية ويشمل", "1 Timothy 5:8"),
        # The chapter and verse words misheard.
        ("الرسالة إلى العبرانيين أذي صحاح 12 الآية 7", "Hebrews 12:7"),
        ("سفر المزامير الإسحاحي 23 الآية 5", "Psalm 23:5"),
        ("الرسالة إلى الأبرانيين الإصحاق 13 الآية 6", "Hebrews 13:6"),
        ("الرسالة إلى الأبرانيين الإصحاح 13 آية 6", "Hebrews 13:6"),
        # Two verses, and a number with a free-standing "and".
        ("سفر المزامير الإصحاح 66 الآيتان 8 و9", "Psalm 66:8"),
        ("سفر المزامير الإصحاح ثلاثة و عشرون الآية خمسة", "Psalm 23:5"),
        ("سفر المزامير الإصحاح مئة وتسعة عشر الآية 105", "Psalm 119:105"),
    ],
)
def test_a_heard_reference_is_named_in_english(heard, citation):
    assert [found[2] for found in arabic_references(heard)] == [citation]


@pytest.mark.parametrize(
    "heard",
    [
        # No number after the chapter word.
        "رسالة يعقوب الإصحاح الكبير الآية ثلاثة",
        # No book before it.
        "هذا هو الإصحاح 12 الآية 7 من القصة",
        # Isaac, not a chapter.
        "وولد إسحاق 3 أبناء",
        "لا يوجد هنا أي مرجع",
    ],
)
def test_nothing_is_taken_for_a_reference_that_is_not_one(heard):
    assert arabic_references(heard) == []


def test_the_reference_is_masked_and_comes_back_in_english():
    heard = "أنت تضع زيتا على رأسي سفر المزامير الإصحاح 23 الآية 5 إن امتلاء"
    masked, taken = mask(heard)
    assert taken == ["Psalm 23:5"]
    assert "الإصحاح" not in masked
    assert restore(masked, taken, language="en").count("Psalm 23:5") == 1
