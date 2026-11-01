"""What the page says about the language Whisper detected."""

from __future__ import annotations

import pytest

from .fakes import fake_transcribe_file, make_audio


def _heard_as(language):
    def transcribe(tertius, source, output_dir):
        outputs, result = fake_transcribe_file(tertius, source, output_dir)
        result.language = language
        return outputs, result

    return transcribe


@pytest.mark.parametrize(
    "chosen, detected, said",
    [(None, "ur", True), ("ur", "ur", False), (None, "hi", False), (None, "en", False)],
)
def test_urdu_left_to_auto_detect_is_pointed_out(api, tmp_path, chosen, detected, said):
    """Whisper took both Hindi readings it was given for Urdu (2026-10-30)."""
    api.manager._transcribe_fn = _heard_as(detected)
    api.manager.attach(api.output_dir)
    api.manager.store.add_files(make_audio(tmp_path / "audio", "talk.mp3"))
    api.manager.start(output_dir=api.output_dir, options={"language": chosen})
    api.wait_done()

    notice = api.manager.status()["notice"] or ""
    assert ("set the language to Hindi" in notice) == said
    if said:
        assert notice.startswith("talk.mp3 was heard as Urdu")
