"""Reading how long a media file is, without decoding it.

PyAV (already a faster-whisper dependency) reads the container header, which is
all a duration needs - no decode, no ffmpeg subprocess. Every failure here is
deliberately silent: the length is a nicety for the queue and the estimate, and
a file whose header will not parse must still queue and still transcribe.
"""

from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)


def probe_duration(path) -> float | None:
    """Length of a media file in seconds, or None if it cannot be read."""
    try:
        import av
    except ImportError:  # the model stack is not installed
        return None
    try:
        with av.open(str(path)) as container:
            if container.duration:
                return round(container.duration / av.time_base, 2)
            # Some containers (raw streams) carry the duration per stream only.
            for stream in container.streams.audio:
                if stream.duration and stream.time_base:
                    return round(float(stream.duration * stream.time_base), 2)
    except Exception:
        log.debug("could not read the length of %s", path, exc_info=True)
    return None


def fill_missing_durations(store, paths=None) -> int:
    """Probe every queued file that has no length yet. Returns how many gained one.

    Written back in one batch so a 500-file scan costs one state flush, not 500.
    """
    if store is None:
        return 0
    if paths is None:
        paths = [f["path"] for f in store.snapshot()["files"] if not f.get("duration")]
    found = {}
    for path in paths:
        entry = store.get(path)
        if entry is None or entry.get("duration"):
            continue
        seconds = probe_duration(path)
        if seconds:
            found[path] = seconds
    return store.set_durations(found) if found else 0


def probe_durations_in_background(store, paths=None) -> threading.Thread | None:
    """Same, off the request thread: queueing must never wait on a disk sweep."""
    if store is None:
        return None

    def work():
        try:
            fill_missing_durations(store, paths)
        except Exception:  # pragma: no cover - defensive; a probe is never fatal
            log.debug("duration probing failed", exc_info=True)

    thread = threading.Thread(target=work, name="duration-probe", daemon=True)
    thread.start()
    return thread
