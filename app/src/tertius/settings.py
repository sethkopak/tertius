"""What Tertius remembers between sessions.

Only one thing so far: the output directory you last chose. That matters more
than it sounds. Each output directory keeps its own queue, so a server that
comes back up pointing somewhere else does not show "your" queue - it shows a
different, probably empty or stale one, and a finished batch can look like 99
files waiting to be transcribed again.

Deliberately tiny and deliberately not authoritative: if this file is missing,
unreadable, or names a folder that has since gone, Tertius falls back to its
default and carries on. Losing a preference is a nuisance; failing to start
over one would be a bug.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

SESSION_FILENAME = ".tertius-session.json"


def session_file() -> Path:
    """Where the remembered settings live.

    Beside the code in `app/` rather than in the output directory - the whole
    point is to know which output directory to use *before* attaching to one.
    `TERTIUS_SESSION_FILE` overrides it, which is how the tests keep out of the
    real one.
    """
    override = os.environ.get("TERTIUS_SESSION_FILE")
    if override:
        return Path(override).expanduser()
    # This file is app/src/tertius/settings.py, so app/ is three levels up.
    return Path(__file__).resolve().parents[2] / SESSION_FILENAME


def _read() -> dict:
    try:
        with open(session_file(), encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(data: dict) -> bool:
    path = session_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2)
    except OSError as exc:
        log.debug("could not write %s: %s", path, exc)
        return False
    return True


def remembered_output_dir() -> Path | None:
    """The output directory last chosen, if it still exists.

    A folder that has been deleted or is on a drive that is not plugged in is
    treated as not remembered, rather than handed back to be failed on later.
    """
    value = _read().get("output_dir")
    if not value:
        return None
    try:
        path = Path(value).expanduser()
    except (TypeError, ValueError):
        return None
    if not path.is_dir():
        log.info("last output directory is gone, using the default: %s", path)
        return None
    return path.resolve()


def remember_output_dir(path: str | os.PathLike) -> bool:
    """Record the output directory the user has chosen."""
    resolved = str(Path(path).expanduser().resolve())
    data = _read()
    if data.get("output_dir") == resolved:
        return True  # nothing to do; do not rewrite the file on every request
    data["output_dir"] = resolved
    return _write(data)
