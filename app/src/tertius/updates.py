"""Check GitHub for a newer release, and install one over this copy.

An update is a **published GitHub Release**, not a commit. Pushing to `main`
is how work in progress gets shared; publishing a release is the deliberate
act of saying "this is ready for people". The release notes are the changelog
the dialog shows, so they are written for a user, not as commit subjects.

Nothing here runs unless the user clicks: there is no check at startup and no
check in the background. Both requests go to GitHub and carry nothing of the
user's - see SECURITY.md.

Installing replaces the code in place, from the release's source zip:

- Only files that are *in* the release are written. Everything else in the
  folder - `app/.venv`, `transcripts/`, the remembered session, the shortcut -
  is never in a release, so it is never touched.
- The whole release is unpacked and checked before anything is replaced, and
  a failure part-way through puts back every file it had already changed.

A git checkout is updated with git instead, from the same button: copying a
zip over a working tree would make every file look modified. The release tag
is fetched from GitHub itself - not from `origin`, which may be a fork - and
the checkout fast-forwards to it. It refuses rather than merges: uncommitted
changes to tracked files, a detached HEAD, or local commits the release does
not have all stop it, with the reason, before anything moves. Untracked files
do not, because a fast-forward never touches them.

Files a release *removes* are left where they are. Nothing imports a module
nobody names, and deleting from someone's folder on the strength of a file
list is a worse failure than a stale file.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

from . import __version__

log = logging.getLogger(__name__)

REPO = "sethkopak/tertius"
GIT_URL = f"https://github.com/{REPO}.git"
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
ZIPBALL_URL = f"https://api.github.com/repos/{REPO}/zipball/{{tag}}"

# What the server exits with to ask the launcher for a fresh start on the new
# code. 75 is EX_TEMPFAIL: "try again", which is what it means here.
RESTART_EXIT_CODE = 75
# Set by the launcher on the server it starts. Without it nothing is waiting
# to start the new version, so the server says so instead of exiting.
LAUNCHER_ENV = "TERTIUS_LAUNCHER"

TIMEOUT = 20
# The release zip is under 2 MB today. A cap stops a wrong redirect from
# filling the disk; it is not a guess at how big a release may grow.
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024
# How many releases' notes the dialog shows. Someone a long way behind does
# not need every one to decide whether to update.
MAX_RELEASES_SHOWN = 10
MAX_NOTES_CHARS = 4000

STAGING_DIRNAME = ".update-staging"
# Never written, whatever a zip contains. None of these are in a release; this
# is what keeps a malformed one from reaching them anyway.
PROTECTED_PARTS = {".git", ".venv", STAGING_DIRNAME}


class UpdateError(RuntimeError):
    """Something the user should be told, in words they can act on."""


def install_dir() -> Path:
    """The folder holding the launchers - this file is app/src/tertius/updates.py."""
    return Path(__file__).resolve().parents[3]


def is_git_checkout(root: Path | None = None) -> bool:
    return ((root or install_dir()) / ".git").exists()


def can_restart() -> bool:
    """Is a launcher waiting to start the new version when this one exits?"""
    return os.environ.get(LAUNCHER_ENV) == "1"


def parse_version(text: str | None) -> tuple[int, int, int] | None:
    """`v1.2.3` or `1.2` -> (1, 2, 3) / (1, 2, 0). None for anything else.

    Strict on purpose: a tag that does not read as a version is skipped
    rather than ordered by a guess.
    """
    match = re.fullmatch(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", (text or "").strip())
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())  # type: ignore[return-value]


# --------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------

def _request(url: str) -> urllib.request.Request:
    # GitHub's API refuses requests with no User-Agent.
    return urllib.request.Request(
        url,
        headers={
            "User-Agent": f"Tertius/{__version__}",
            "Accept": "application/vnd.github+json",
        },
    )


def _network_error(exc: Exception) -> UpdateError:
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 403:
            return UpdateError(
                "GitHub refused the request - it allows 60 checks an hour from "
                "one address. Try again later."
            )
        return UpdateError(f"GitHub answered {exc.code} {exc.reason}.")
    reason = getattr(exc, "reason", exc)
    return UpdateError(
        f"Could not reach GitHub ({reason}). Check the internet connection; "
        "a network that inspects HTTPS traffic can also cause this."
    )


def fetch_releases() -> list[dict]:
    """The repository's releases, newest first, as GitHub returns them."""
    try:
        with urllib.request.urlopen(_request(RELEASES_URL), timeout=TIMEOUT) as response:
            data = json.load(response)
    except (urllib.error.URLError, OSError) as exc:
        raise _network_error(exc) from exc
    except ValueError as exc:
        raise UpdateError("GitHub sent something that is not a list of releases.") from exc
    if not isinstance(data, list):
        raise UpdateError("GitHub sent something that is not a list of releases.")
    return data


def download(url: str, target: Path) -> None:
    try:
        with urllib.request.urlopen(_request(url), timeout=TIMEOUT) as response:
            written = 0
            with open(target, "wb") as handle:
                while chunk := response.read(1024 * 1024):
                    written += len(chunk)
                    if written > MAX_DOWNLOAD_BYTES:
                        raise UpdateError("The download was far larger than a release should be.")
                    handle.write(chunk)
    except (urllib.error.URLError, OSError) as exc:
        raise _network_error(exc) from exc


# --------------------------------------------------------------------------
# Checking
# --------------------------------------------------------------------------

def _newer_releases(releases: list[dict], current: str) -> list[dict]:
    here = parse_version(current) or (0, 0, 0)
    newer = []
    for release in releases:
        if not isinstance(release, dict) or release.get("draft") or release.get("prerelease"):
            continue
        version = parse_version(release.get("tag_name"))
        if version is None or version <= here:
            continue
        newer.append((version, release))
    newer.sort(key=lambda pair: pair[0], reverse=True)
    return [release for _, release in newer]


def _summarize(release: dict) -> dict:
    notes = (release.get("body") or "").strip()
    truncated = len(notes) > MAX_NOTES_CHARS
    if truncated:
        notes = notes[:MAX_NOTES_CHARS].rstrip() + "\n..."
    return {
        "tag": release.get("tag_name"),
        "name": (release.get("name") or "").strip() or release.get("tag_name"),
        "published": release.get("published_at"),
        "notes": notes,
        "truncated": truncated,
        "url": release.get("html_url"),
    }


def check(current: str = __version__, releases: list[dict] | None = None) -> dict:
    """What the dialog needs: is there something newer, and what changed."""
    if releases is None:
        releases = fetch_releases()
    newer = _newer_releases(releases, current)
    return {
        "current": current,
        "latest": newer[0]["tag_name"] if newer else None,
        "update_available": bool(newer),
        "any_published": any(
            isinstance(r, dict) and not r.get("draft") and not r.get("prerelease")
            for r in releases
        ),
        "releases": [_summarize(r) for r in newer[:MAX_RELEASES_SHOWN]],
        "more_releases": max(0, len(newer) - MAX_RELEASES_SHOWN),
        "git_checkout": is_git_checkout(),
        # Said before the click, so the button is not offered only to fail.
        "blocked": git_blocker() if newer and is_git_checkout() else None,
        "can_restart": can_restart(),
    }


# --------------------------------------------------------------------------
# Git checkouts
# --------------------------------------------------------------------------

def _git(root: Path, *args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            # Never stop to ask for a password: there is no terminal to ask in.
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as exc:
        raise UpdateError(
            "This copy of Tertius is a git checkout, but git is not installed "
            "or not on PATH, so it cannot be updated from here."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise UpdateError(f"git {args[0]} took too long and was stopped.") from exc


def git_blocker(root: Path | None = None) -> str | None:
    """Why this checkout cannot be fast-forwarded, or None if it can be tried.

    Only what can be known without the network. Whether the release contains
    HEAD is only known once its tag has been fetched, and is checked then.
    """
    root = root or install_dir()
    try:
        changed = _git(root, "status", "--porcelain", "--untracked-files=no")
        branch = _git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    except UpdateError as exc:
        return str(exc)
    if changed.returncode != 0:
        return f"git could not read this checkout: {changed.stderr.strip()}"
    names = [line[3:] for line in changed.stdout.splitlines() if line.strip()]
    if names:
        shown = ", ".join(names[:5]) + (f" and {len(names) - 5} more" if len(names) > 5 else "")
        return (
            f"This checkout has uncommitted changes ({shown}). Updating would "
            "overwrite them, so commit or stash them first."
        )
    if branch.returncode != 0:
        return "This checkout is not on a branch (detached HEAD), so there is nothing to update."
    return None


def apply_git(tag: str, root: Path, current: str = __version__, source: str = GIT_URL) -> dict:
    """Fast-forward a git checkout to release `tag`, or refuse and say why."""
    blocker = git_blocker(root)
    if blocker:
        raise UpdateError(blocker)

    ref = f"refs/tags/{tag}"
    fetched = _git(root, "fetch", "--quiet", "--no-tags", source, f"+{ref}:{ref}", timeout=300)
    if fetched.returncode != 0:
        raise UpdateError(f"Could not fetch {tag} from GitHub: {fetched.stderr.strip()}")

    if _git(root, "merge-base", "--is-ancestor", "HEAD", ref).returncode != 0:
        raise UpdateError(
            f"This checkout has commits that {tag} does not, so it cannot simply "
            "move forward to it. Update it with git yourself."
        )
    shown = _git(root, "show", f"{ref}:app/src/tertius/__init__.py")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', shown.stdout, re.MULTILINE)
    inside = match.group(1) if match else None
    if parse_version(inside) != parse_version(tag):
        raise UpdateError(
            f"Release {tag} contains version {inside or 'unknown'}, not {tag}. "
            "Not installing it; this needs fixing on GitHub."
        )

    changed = _git(root, "diff", "--name-only", "HEAD", ref).stdout.split("\n")
    merged = _git(root, "merge", "--ff-only", "--quiet", ref, timeout=300)
    if merged.returncode != 0:
        raise UpdateError(f"git could not move to {tag}: {merged.stderr.strip()}")
    count = sum(1 for name in changed if name.strip())
    log.info("fast-forwarded the checkout to %s over %s: %d file(s) changed", tag, current, count)
    return {"installed": tag, "previous": current, "changed": count}


# --------------------------------------------------------------------------
# Installing
# --------------------------------------------------------------------------

def _member_path(name: str) -> PurePosixPath | None:
    """A zip entry's path below the archive's top folder, or None to skip it.

    GitHub's zips put everything under one `owner-repo-sha/` folder. Anything
    that would land outside the install - absolute, `..`, a drive letter - is
    refused outright rather than skipped: a release that contains one is not
    a release to install any part of.
    """
    parts = PurePosixPath(name.replace("\\", "/")).parts
    if len(parts) < 2:
        return None  # the top folder itself
    rest = parts[1:]
    if name.startswith("/") or any(p in ("", "..") or ":" in p for p in rest):
        raise UpdateError(f"The release contains an unsafe path ({name}); not installing it.")
    if PROTECTED_PARTS.intersection(rest):
        return None
    return PurePosixPath(*rest)


def _unpack(archive: Path, into: Path) -> dict[PurePosixPath, int]:
    """Extract to `into`; returns each file's Unix mode, where the zip has one."""
    modes: dict[PurePosixPath, int] = {}
    try:
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                relative = _member_path(info.filename)
                if relative is None or info.is_dir():
                    continue
                target = into.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(info) as source, open(target, "wb") as sink:
                    shutil.copyfileobj(source, sink)
                mode = (info.external_attr >> 16) & 0o777
                if mode:
                    modes[relative] = mode
    except zipfile.BadZipFile as exc:
        raise UpdateError("The download is not a readable zip file.") from exc
    return modes


def _packaged_version(unpacked: Path) -> str | None:
    init = unpacked / "app" / "src" / "tertius" / "__init__.py"
    try:
        text = init.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    return match.group(1) if match else None


def _verify(unpacked: Path, tag: str) -> None:
    """Refuse anything that is not recognisably a Tertius of the promised version."""
    for needed in ("app/src/tertius/launcher.py", "app/requirements.txt"):
        if not (unpacked / needed).is_file():
            raise UpdateError(f"The release has no {needed}, so it is not a Tertius to install.")
    inside = _packaged_version(unpacked)
    # A tag that disagrees with the code would install, report the old
    # number, and offer the same update again on every check, forever.
    if parse_version(inside) != parse_version(tag):
        raise UpdateError(
            f"Release {tag} contains version {inside or 'unknown'}, not {tag}. "
            "Not installing it; this needs fixing on GitHub."
        )


def _same_bytes(a: Path, b: Path) -> bool:
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        return hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest()
    except OSError:
        return False


def _install(unpacked: Path, root: Path, backup: Path, modes: dict[PurePosixPath, int]) -> int:
    """Move every changed file into place; on any failure undo all of them."""
    replaced: list[Path] = []
    created: list[Path] = []
    try:
        for staged in sorted(p for p in unpacked.rglob("*") if p.is_file()):
            relative = PurePosixPath(staged.relative_to(unpacked).as_posix())
            target = root.joinpath(*relative.parts)
            if target.is_file() and _same_bytes(staged, target):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                saved = backup.joinpath(*relative.parts)
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
                replaced.append(relative)
            else:
                created.append(relative)
            # Same filesystem - staging sits inside the install - so this is
            # an atomic rename, never a half-written file.
            os.replace(staged, target)
            if sys.platform != "win32" and relative in modes:
                target.chmod(modes[relative])
    except Exception:
        for relative in created:
            root.joinpath(*relative.parts).unlink(missing_ok=True)
        for relative in replaced:
            os.replace(backup.joinpath(*relative.parts), root.joinpath(*relative.parts))
        raise
    return len(replaced) + len(created)


def apply(
    tag: str,
    root: Path | None = None,
    current: str = __version__,
    releases: list[dict] | None = None,
    fetch=download,
) -> dict:
    """Download release `tag` and install it over this copy."""
    root = root or install_dir()
    # The tag is looked up again rather than trusted from the request: only a
    # published, newer release of this repository is ever installed.
    if releases is None:
        releases = fetch_releases()
    if not any(r.get("tag_name") == tag for r in _newer_releases(releases, current)):
        raise UpdateError(f"{tag} is not a published release newer than {current}.")
    if is_git_checkout(root):
        return apply_git(tag, root, current)

    staging = root / "app" / STAGING_DIRNAME
    shutil.rmtree(staging, ignore_errors=True)
    unpacked, backup = staging / "files", staging / "backup"
    unpacked.mkdir(parents=True)
    try:
        archive = staging / "release.zip"
        fetch(ZIPBALL_URL.format(tag=urllib.parse.quote(tag, safe="")), archive)
        modes = _unpack(archive, unpacked)
        _verify(unpacked, tag)
        changed = _install(unpacked, root, backup, modes)
    except OSError as exc:
        raise UpdateError(f"Could not install the update: {exc}. Nothing was changed.") from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    log.info("installed %s over %s: %d file(s) changed", tag, current, changed)
    return {"installed": tag, "previous": current, "changed": changed}
