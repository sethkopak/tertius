"""Scripture references in Hebrew, as Whisper writes Tertius's Hebrew readings.

See `scripture.hebrew_references`. Every heard form here is one Whisper
wrote, hearing the ten harness files read in Hebrew (2026-10-26).
"""

from __future__ import annotations

import pytest

from tertius.scripture import hebrew_references, mask, restore


@pytest.mark.parametrize(
    "heard, citation",
    [
        ("הקוס שלי מתמלט, תהילים, פרק 23, פסוק 5.", "Psalm 23:5"),
        ("לא נכון. איגרת יעקב, פרק ארבעה, פסוק שלושה.", "James 4:3"),
        ("שריון האור. ההגלת אל הרומאים, פרק 13, פסוק 12", "Romans 13:12"),
        ("יעשה לי. ההיגרת אל העברים, פרק שלושה עשר, פסוק שישה.", "Hebrews 13:6"),
        ("כוח הגר את פטרוס השנייה פרק אחד פסוק חמישה", "2 Peter 1:5"),
        ("מכופר. ההיגרת הלשונה את טימוטיוס, פרק 5, פסוק 8.", "1 Timothy 5:8"),
        # Timothy heard as two words: five words name the book.
        ("מיד. ההיגרת הראשונה אל תימות יוס, פרק 5, פסוק 8.", "1 Timothy 5:8"),
        # Hebrews misheard as one word close to תהילים: still Hebrews.
        ("במחשבותיכם. ההיגרת אל העבלים, פרק 12, פסוק 3", "Hebrews 12:3"),
        # `פסוק` misheard.
        ("מאניש. היגרת אל העברים, פרק 12, פסוג 7.", "Hebrews 12:7"),
        ("בתהילים, פרק שישים ושישה, פסוקים שמונה ותשעה.", "Psalm 66:8,9"),
    ],
)
def test_a_heard_reference_is_named_in_english(heard, citation):
    assert [found[2] for found in hebrew_references(heard)] == [citation]


@pytest.mark.parametrize(
    "heard",
    [
        # The number is not one.
        "לא נכון. איגרת יעקב, פרק הבאה, פסוק שלושה.",
        # No book before it.
        "זה פרק 12, פסוק 7 של הסיפור.",
        "אין כאן שום הפניה.",
    ],
)
def test_nothing_is_taken_for_a_reference_that_is_not_one(heard):
    assert hebrew_references(heard) == []


def test_the_reference_is_masked_and_comes_back_in_english():
    heard = "אתה מרח את ראשי בשמן. תהילים, פרק 23, פסוק 5. ועוד"
    masked, taken = mask(heard)
    assert masked == "אתה מרח את ראשי בשמן. @0@. ועוד"
    assert taken == ["Psalm 23:5"]
    assert restore("You anoint my head. @0@. And", taken, language="en") == (
        "You anoint my head. Psalm 23:5. And"
    )
