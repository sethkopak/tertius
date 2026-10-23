"""References written in Chinese, found by sound and given back in English.

See `scripture.chinese_references`. The texts here are what Whisper heard of
Tertius's own Chinese readings of the ten harness files, 2026-10-22/23.
"""

from __future__ import annotations

import pytest

from tertius.scripture import chinese_references, mask, restore

# `pypinyin` belongs to the translate extra, not the base install. Without it
# `chinese_references` correctly finds nothing, so every assertion here would
# fail as though the feature were broken rather than absent.
try:  # noqa: SIM105 - the import is the test
    import pypinyin as _pypinyin  # noqa: F401
except Exception:  # pragma: no cover - only when the extra is not installed
    pytest.skip("pypinyin is part of the translate extra", allow_module_level=True)


def _found(text):
    return [(text[start:end], english) for start, end, english in chinese_references(text)]


@pytest.mark.parametrize(
    "heard, english",
    [
        ("希伯来书第十二章第三节", "Hebrews 12:3"),
        ("希伯来书第12章第11节", "Hebrews 12:11"),
        # Whisper's own spellings, each the sound of the table's name.
        ("西伯来书第十二章第七节", "Hebrews 12:7"),
        ("菲利比书第四章第四节", "Philippians 4:4"),
        ("腓立比书,第四章,第四节", "Philippians 4:4"),
        ("十篇第二十三篇第五节", "Psalm 23:5"),
        ("提摩太前书第五章第八节", "1 Timothy 5:8"),
        ("彼得后书第1章第5节", "2 Peter 1:5"),
        ("罗马书第13张第12节", "Romans 13:12"),
        ("《罗马书》第13章第12节", "Romans 13:12"),
        # 2026-10-19, the sentence madlad dropped a clause from.
        ("贴萨罗尼加后书2,12", "2 Thessalonians 2:12"),
        # How `numbers.spell` writes a list and a range.
        ("诗篇第六十六篇第八和第九节", "Psalm 66:8,9"),
        ("耶利米哀歌第三章第二十二至二十四节", "Lamentations 3:22-24"),
    ],
)
def test_a_reference_is_found_whatever_the_spelling(heard, english):
    assert _found(heard) == [(heard, english)]


def test_the_reference_is_found_inside_a_sentence():
    heard = "我的杯溢满了,十篇第二十三篇第五节,杯子溢满具有双重意义"
    assert _found(heard) == [("十篇第二十三篇第五节", "Psalm 23:5")]


def test_a_book_heard_with_its_first_syllable_wrong():
    """0723: 提摩太前书 heard as 听摩太前书. 摩太前书 is only ever 1 Timothy."""
    assert _found("比不信的人还坏,听摩太前书第五章第八节") == [
        ("摩太前书第五章第八节", "1 Timothy 5:8")
    ]


@pytest.mark.parametrize(
    "heard",
    [
        # 0510: the reading dropped the 十 of 二十三. Not Psalm 3.
        "诗篇第二三篇第五节",
        # 0616: the chapter cut from the reading; nothing to name it by.
        "希伯来书第十一节",
        # Numbered points in prose are not references.
        "第一,对真理的热心,第三,他勇敢地冒着生命危险",
        # A date is not a reference either.
        "10月5日的玛纳",
    ],
)
def test_what_is_not_a_whole_reference_is_left_alone(heard):
    assert _found(heard) == []


def test_two_books_one_syllable_apart_are_not_confused():
    """腓立比書 and 腓利門書 differ by one syllable; exact sound tells them apart."""
    assert _found("腓利门书第一章第六节") == [("腓利门书第一章第六节", "Philemon 1:6")]


def test_a_chinese_reference_is_masked_and_put_back_in_english():
    masked, taken = mask("你们要喜乐,腓立比书第四章第四节。")
    assert masked == "你们要喜乐,@0@。"
    assert taken == ["Philippians 4:4"]
    assert restore("Rejoice, @0@.", taken, language="en") == "Rejoice, Philippians 4:4."
