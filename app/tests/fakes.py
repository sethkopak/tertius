"""Test doubles that stand in for the whisper model.

Nothing here downloads a model or decodes audio.
"""

from __future__ import annotations

import threading
from pathlib import Path

from tertius.transcribe import Segment, TranscriptionResult, write_outputs


class FakeTranscriber:
    """Duck-compatible with WhisperTranscriber, minus the model."""

    def __init__(self, options):
        self.options = options
        self.calls: list[str] = []
        self.warmed_up = False
        # Per-path behaviour hooks, set by tests.
        self.fail_paths: set[str] = set()
        self.block_paths: dict[str, threading.Event] = {}
        self.warmup_error: Exception | None = None

    def warmup(self) -> None:
        if self.warmup_error:
            raise self.warmup_error
        self.warmed_up = True

    def transcribe(self, path) -> TranscriptionResult:
        path = str(path)
        self.calls.append(path)
        gate = self.block_paths.get(path)
        if gate is not None:
            gate.wait(timeout=10)
        if path in self.fail_paths:
            raise RuntimeError("simulated decode failure")
        name = Path(path).stem
        return TranscriptionResult(
            segments=[
                Segment(0.0, 1.5, f"hello from {name}"),
                Segment(1.5, 3.0, "second segment"),
            ],
            language="en",
            duration=3.0,
        )

    def unload(self) -> None:
        pass


def fake_transcribe_file(tertius, source, output_dir):
    result = tertius.transcribe(source)
    outputs = write_outputs(
        Path(source), result, Path(output_dir), tertius.options.formats
    )
    return outputs, result


class FakeTranslator:
    """Duck-compatible with Translator, minus the 2 GB model.

    Translating is faked as an uppercase marker so a test can tell a translated
    file from a transcript by reading it, rather than by trusting the filename.
    """

    def __init__(self, model_key="m2m100-418M", device="auto", on_download_progress=None):
        self.model_key = model_key
        self.device = device
        self.on_download_progress = on_download_progress
        self.loaded = False
        self.calls: list[tuple[str, str]] = []
        # Every batch of texts the model was handed, so a test can prove it was
        # given whole sentences rather than timing-cut fragments.
        self.batches: list[list[str]] = []
        # Every (done, total) the translator reported.
        self.progress: list[tuple[int, int]] = []
        self.load_error: Exception | None = None
        self.prepare_error: Exception | None = None
        self.prepared = False
        self.fail_paths: set[str] = set()
        self.fail_always = False

    @property
    def family(self) -> str:
        return "t5" if self.model_key.startswith("madlad") else "m2m100"

    def prepare(self):
        if self.prepare_error:
            raise self.prepare_error
        self.prepared = True
        return None

    def load(self) -> None:
        if self.load_error:
            raise self.load_error
        self.loaded = True

    def translate(self, texts, target_language, source_language=None, on_progress=None):
        if self.fail_always:
            raise RuntimeError("simulated translation failure")
        self.calls.append((target_language, source_language))
        self.batches.append(list(texts))
        if on_progress is not None:
            # The real one reports per batch; one call at the end is enough to
            # prove the wiring without inventing a batching schedule here.
            self.progress.append((len(texts), len(texts)))
            on_progress(len(texts), len(texts))
        return [
            f"[{target_language}] {t.strip().upper()}" if t and t.strip() else t
            for t in texts
        ]

    def unload(self) -> None:
        self.loaded = False


def wait_until(predicate, timeout: float = 10.0, description: str = "condition"):
    """Poll until `predicate()` is truthy. Returns its value.

    Job startup does real work (checking whether the model is cached) before the
    first file, so tests must observe the worker's actual state rather than
    assume it got there instantly.
    """
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {description}")


def make_audio(directory: Path, *names: str) -> list[Path]:
    """Create placeholder media files (never actually decoded)."""
    directory.mkdir(parents=True, exist_ok=True)
    created = []
    for name in names:
        path = directory / name
        path.write_bytes(b"\x00fake audio")
        created.append(path)
    return created
