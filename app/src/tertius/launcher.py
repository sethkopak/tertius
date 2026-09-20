"""Everything the double-click launchers do, in one place.

This used to be 130 lines of batch script. It is here instead because the logic
is not trivial - build a virtual environment, install into it, work out whether
an older server is running and whether it is safe to replace, wait for a port to
go quiet - and maintaining three copies of it in three shell dialects is how
they drift apart.

The per-OS wrappers (`Start Tertius.bat`, `start-tertius.sh`, `Tertius.app`)
are deliberately thin: find a Python, run this module, keep the window open if
it fails. Everything that could be got wrong lives here, where the tests are.

Run directly:

    python app/src/tertius/launcher.py [--port 5005] [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

# The packages the app cannot start without. Checked by import name, not by
# distribution name - `pip show` is slow and lies after a partial install.
REQUIRED_IMPORTS = ("flask", "faster_whisper")

DEFAULT_PORT = 5005
STATUS_TIMEOUT = 3.0
SHUTDOWN_WAIT = 10.0


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------

def app_dir() -> Path:
    """The `app/` folder - this file is `app/src/tertius/launcher.py`."""
    return Path(__file__).resolve().parents[2]


def project_dir() -> Path:
    """The folder holding the launchers, the README and `transcripts/`."""
    return app_dir().parent


def venv_dir() -> Path:
    return app_dir() / ".venv"


def remembered_output_dir() -> Path | None:
    """The output directory from the last session, for the banner only.

    Read here with plain json rather than by importing tertius.settings: this
    module runs as a standalone script under whatever Python is on PATH, before
    the virtual environment exists, so package-relative imports are not
    available. The server does its own resolution - this only decides what the
    launch message claims, and being wrong there is cosmetic.
    """
    session = app_dir() / ".tertius-session.json"
    try:
        with open(session, encoding="utf-8") as handle:
            value = json.load(handle).get("output_dir")
    except (OSError, ValueError, AttributeError):
        return None
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_dir() else None


def venv_python(venv: Path | None = None) -> Path:
    """The interpreter inside a virtual environment, per platform layout."""
    venv = venv or venv_dir()
    if sys.platform == "win32":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"


# --------------------------------------------------------------------------
# Environment bootstrap
# --------------------------------------------------------------------------

def has_requirements(python: Path) -> bool:
    """Can `python` import everything the app needs?"""
    code = "import " + ", ".join(REQUIRED_IMPORTS)
    try:
        done = subprocess.run(
            [str(python), "-c", code],
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def create_venv(venv: Path, say=print) -> bool:
    """Build the virtual environment. Returns whether it worked."""
    say("  No virtual environment yet - creating one. This happens once.")
    say("")
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv)],
            check=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        say(f"  ERROR: could not create the virtual environment: {exc}")
        return False
    return venv_python(venv).is_file()


def install_requirements(python: Path, say=print) -> bool:
    """Install `requirements.txt` into `python`'s environment."""
    say("  Installing dependencies - a few hundred MB, one time only...")
    say("")
    requirements = app_dir() / "requirements.txt"
    for command in (
        [str(python), "-m", "pip", "install", "--upgrade", "pip"],
        [str(python), "-m", "pip", "install", "-r", str(requirements)],
    ):
        try:
            subprocess.run(command, check=True, timeout=3600)
        except (OSError, subprocess.SubprocessError) as exc:
            say(f"  ERROR: {exc}")
            return False
    return has_requirements(python)


def ensure_environment(say=print) -> Path | None:
    """The interpreter to run the server with, or None if it could not be set up."""
    venv = venv_dir()
    python = venv_python(venv)
    if not python.is_file():
        if not create_venv(venv, say):
            say("  Is Python installed? Try running: python --version")
            return None
        python = venv_python(venv)
    if not has_requirements(python):
        if not install_requirements(python, say):
            say("  Dependencies failed to install. Scroll up for the reason.")
            return None
        say("")
    return python


# --------------------------------------------------------------------------
# Is something already on this port?
# --------------------------------------------------------------------------

def probe(url: str, timeout: float = STATUS_TIMEOUT) -> dict | None:
    """Ask a possible Tertius for its status. None means nothing answered."""
    try:
        with urllib.request.urlopen(url + "api/status", timeout=timeout) as response:
            return json.load(response)
    except (urllib.error.URLError, OSError, ValueError):
        return None


def stop_existing(url: str, say=print) -> bool:
    """Ask an idle server to stop, and wait for the port to go quiet.

    An already-running server was started from the code as it was *then*.
    Templates are held in memory but the stylesheet and script are read off disk
    per request, so reconnecting to an old server after an update serves last
    week's page with this week's script, and the page breaks.
    """
    request = urllib.request.Request(
        url + "api/job/force-stop",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(request, timeout=5).read()
    except (urllib.error.URLError, OSError):
        pass  # it may already be going down; the wait below is what decides

    deadline = time.time() + SHUTDOWN_WAIT
    while time.time() < deadline:
        if probe(url, timeout=2) is None:
            return True
        time.sleep(1)
    say("  ERROR: the old Tertius would not stop.")
    say("  Close its window - the one titled Tertius - and run this again.")
    return False


def handle_existing(url: str, say=print) -> str:
    """What to do about whatever is on the port.

    Returns "launch" (nothing there, or the old one has gone), "reuse" (busy,
    leave it strictly alone) or "blocked" (it would not stop).
    """
    status = probe(url)
    if status is None:
        return "launch"

    if status.get("running"):
        say("  Tertius is already running, and is part-way through a batch.")
        say("  Opening its tab rather than interrupting the work.")
        say("")
        say("  If you have just updated Tertius, close this window, let the")
        say("  batch finish, then launch again - that start picks up the new")
        say("  version.")
        say("")
        return "reuse"

    say("  An older Tertius is still running. Restarting it so this launch")
    say("  uses the current version.")
    say("")
    say("  Nothing is lost - it has no batch in flight, and the queue is kept")
    say("  in the state file on disk.")
    say("")
    return "launch" if stop_existing(url, say) else "blocked"


# --------------------------------------------------------------------------
# Windows desktop niceties
# --------------------------------------------------------------------------

def refresh_windows_shortcut(say=print) -> Path | None:
    """Write `Tertius.lnk` next to the launcher, carrying the T logo.

    A .bat file cannot have its own icon - Windows takes the icon from the file
    *type*, and there is no per-file override. A shortcut can, so we keep one
    beside the .bat. Shortcuts store absolute paths and break when the folder
    moves, which is why this is rewritten on every launch rather than committed.

    Never fatal: a missing icon is cosmetic.
    """
    if sys.platform != "win32":
        return None
    target = project_dir() / "Start Tertius.bat"
    link = project_dir() / "Tertius.lnk"
    icon = app_dir() / "assets" / "tertius.ico"
    if not target.is_file() or not icon.is_file():
        return None

    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{link}'); "
        f"$s.TargetPath = '{target}'; "
        f"$s.WorkingDirectory = '{project_dir()}'; "
        f"$s.IconLocation = '{icon},0'; "
        "$s.Description = 'Tertius - local, offline transcription'; "
        "$s.Save()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        say(f"  (could not refresh the shortcut icon: {exc})")
        return None
    return link if link.is_file() else None


def apply_windows_folder_icon(say=print) -> bool:
    """Give the project folder the T logo in Explorer, via desktop.ini.

    Cosmetic, and quietly skipped if anything refuses: the icon is a nicety and
    must never be the reason a launch fails.
    """
    if sys.platform != "win32":
        return False
    icon = app_dir() / "assets" / "tertius.ico"
    if not icon.is_file():
        return False
    ini = project_dir() / "desktop.ini"
    # newline="" so the explicit \r\n is written as-is. Text mode would
    # translate it again and put a blank line between every entry.
    wanted = (
        "[.ShellClassInfo]\r\n"
        f"IconResource={icon},0\r\n"
        "ConfirmFileOp=0\r\n"
    )

    def attrib(*flags: str) -> None:
        subprocess.run(
            ["attrib", *flags, str(ini)],
            capture_output=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    try:
        if ini.is_file():
            # Nothing to do if it already says the right thing, which is every
            # launch after the first. Worth checking rather than rewriting
            # blindly: the rewrite is the step that fails, so not needing it is
            # the fix for the ordinary case.
            try:
                # `open(..., newline="")` rather than `Path.read_text(newline=)`:
                # that argument arrived in 3.13 and this supports 3.11, where it
                # is a TypeError - and not one the handler below would catch, so
                # it would have taken the whole launcher down rather than
                # printing the cosmetic line this function exists to print.
                with open(ini, encoding="utf-8", newline="") as handle:
                    if handle.read() == wanted:
                        return True
            except OSError:
                pass  # unreadable; fall through and try to replace it

            # Explorer only honours a *hidden and system* desktop.ini, so the
            # first run marks it as both - and Windows then refuses to open it
            # for writing, CreateFile failing with ACCESS_DENIED on a file
            # carrying either attribute. This was setting the very flags that
            # made its own next run fail, and printed "Permission denied" on
            # every launch after the first for seven weeks.
            #
            # Harmless while the folder stays put, because what is on disk is
            # already right. Not harmless once it moves: IconResource is an
            # absolute path, so a moved folder needs this rewrite and silently
            # was not getting it.
            attrib("-h", "-s")

        with open(ini, "w", encoding="utf-8", newline="") as handle:
            handle.write(wanted)
        # Explorer only reads desktop.ini from a folder marked system or
        # read-only, and only honours a hidden+system desktop.ini.
        attrib("+h", "+s")
        subprocess.run(
            ["attrib", "+r", str(project_dir())],
            capture_output=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        say(f"  (could not set the folder icon: {exc})")
        return False
    return True


# --------------------------------------------------------------------------
# Linux desktop entry
# --------------------------------------------------------------------------

def refresh_linux_desktop_entry(say=print) -> Path | None:
    """Write `Tertius.desktop` next to the launcher, carrying the T logo.

    Generated rather than committed for the same reason as the Windows
    shortcut: `Icon=` and `Exec=` both need absolute paths, so the file is only
    ever correct for one folder on one machine.

    That does mean a fresh clone has no desktop entry until something has run
    once - the first launch has to be `./start-tertius.sh` from a terminal.
    After that the icon is there.

    Most file managers also require the entry to be executable and explicitly
    trusted ("Allow Launching" in GNOME) before they will show the icon.
    """
    if not sys.platform.startswith("linux"):
        return None

    icon = app_dir() / "assets" / "tertius-512.png"
    script = project_dir() / "start-tertius.sh"
    entry = project_dir() / "Tertius.desktop"
    if not icon.is_file() or not script.is_file():
        return None

    try:
        entry.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Tertius\n"
            "GenericName=Offline transcription\n"
            "Comment=Local, offline batch transcription. "
            "Nothing leaves this machine.\n"
            f"Icon={icon}\n"
            f"Exec={script}\n"
            f"Path={project_dir()}\n"
            "Terminal=true\n"
            "Categories=AudioVideo;Audio;Utility;\n"
            "Keywords=transcription;subtitles;whisper;audio;srt;\n",
            encoding="utf-8",
        )
        entry.chmod(0o755)
        script.chmod(0o755)
    except OSError as exc:
        say(f"  (could not write the desktop entry: {exc})")
        return None
    return entry


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tertius-launcher",
        description="Set up the environment if needed, then start Tertius.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--output-dir",
        default=None,
        help="defaults to `transcripts/` beside the launcher",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="do not open a browser tab",
    )
    return parser


def banner(say=print) -> None:
    say("")
    say("  Tertius")
    say("  -------")
    say("  Local, offline transcription.")
    say("")


def main(argv: list[str] | None = None, say=print) -> int:
    args = build_parser().parse_args(argv)
    url = f"http://{args.host}:{args.port}/"
    output_dir = (
        Path(args.output_dir).expanduser()
        if args.output_dir
        else remembered_output_dir() or project_dir() / "transcripts"
    )

    banner(say)

    decision = handle_existing(url, say)
    if decision == "blocked":
        return 1
    if decision == "reuse":
        if not args.no_browser:
            webbrowser.open(url)
        return 0

    python = ensure_environment(say)
    if python is None:
        return 1

    refresh_windows_shortcut(say)
    apply_windows_folder_icon(say)
    refresh_linux_desktop_entry(say)

    say(f"  Transcripts go to: {output_dir}")
    say(f"  Opening {url} in your browser...")
    say("")
    say("  Leave this window open while transcribing.")
    say("  Closing it (or pressing Ctrl+C) stops Tertius.")
    say("  Lost the tab? Just start Tertius again.")
    say("")

    command = [
        str(python),
        "-m",
        "tertius",
        "--host",
        args.host,
        "--port",
        str(args.port),
        # Still passed as a backstop against two launches racing each other: on
        # Windows a second process can bind a port already in use, which would
        # leave two servers writing one state file.
        "--reuse-existing",
    ]
    # --output-dir is passed only when it was actually asked for. Sending it on
    # every launch is what made the server forget which folder you were working
    # in: each output directory keeps its own queue, so snapping back to the
    # default made a finished batch reappear as pending work.
    if args.output_dir:
        command += ["--output-dir", str(output_dir)]
    if not args.no_browser:
        command.append("--open-browser")

    environment = dict(os.environ)
    source = app_dir() / "src"
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        f"{source}{os.pathsep}{existing}" if existing else str(source)
    )

    try:
        return subprocess.run(command, env=environment).returncode
    except KeyboardInterrupt:
        return 0
    except OSError as exc:
        say(f"  ERROR: could not start Tertius: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
