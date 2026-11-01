"""The harness's count of references heard back right (`tools/harness.py`)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from harness import references  # noqa: E402


@pytest.mark.parametrize(
    "text, expected",
    [
        # As madlad wrote Hindi back into English (2026-11-01).
        ("Hebrews chapter twelve verse seven.", ["Hebrews 12:7"]),
        ("to the Hebrews, chapter twelve, verse seven.", ["Hebrews 12:7"]),
        ("Psalm chapter twenty-three verses five", ["Psalms 23:5"]),
        # Read already, and kept: rewritten, the comma lost it (he_lb, 10/60 to 2/60).
        ("Promise to the Hebrews, chapter 12, verse 7. A", ["Hebrews 12:7"]),
        ("Romans 13:12", ["Romans 13:12"]),
        ("I Timothy 6:6", ["1 Timothy 6:6"]),
        # No book, no reference.
        ("In chapter three verse two of it", []),
    ],
)
def test_references_in_digits_or_words(text, expected):
    assert references(text) == expected
