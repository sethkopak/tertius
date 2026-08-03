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
