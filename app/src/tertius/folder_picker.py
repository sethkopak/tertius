"""Native "choose a folder" dialog, run as a throwaway subprocess.

A browser cannot hand a web page a real folder path (it deliberately hides the
filesystem), but this server is local, so we can open the OS picker on the same
machine and read the path back.

The dialog is modal: it blocks its process until the user answers. That is why
this is a separate process rather than a call inside a request handler - a
wedged dialog must never be able to freeze the server. Run it standalone:

    python folder_picker.py [--file|--audio] [initial_directory]

Prints the chosen path to stdout, or nothing if the user cancelled.
"""

from __future__ import annotations

import sys

# Exit codes the server turns into an explanation the user can act on. The two
# ways this fails on Linux are different problems with different fixes, and
# "no folder picker available" tells you neither.
EXIT_NO_TKINTER = 3
EXIT_NO_DISPLAY = 4


def _dialog(pick, **options) -> str:
    import tkinter

    root = tkinter.Tk()
    root.withdraw()  # we only want the dialog, not an empty window
    root.attributes("-topmost", True)  # else it can hide behind the browser
    try:
        return pick(**options) or ""
    finally:
        root.destroy()


def pick_folder(initial_dir: str | None = None) -> str:
    """Open the OS folder chooser. Returns "" if the user cancels."""
    from tkinter import filedialog

    options = {"title": "Choose a folder of audio or video files"}
    if initial_dir:
        options["initialdir"] = initial_dir
    return _dialog(filedialog.askdirectory, **options)


def pick_text_file(initial_dir: str | None = None) -> str:
    """Open the OS file chooser for a .txt. Returns "" if the user cancels."""
    from tkinter import filedialog

    options = {
        "title": "Choose the text file for this recording",
        "filetypes": [("Text files", "*.txt"), ("All files", "*.*")],
    }
    if initial_dir:
        options["initialdir"] = initial_dir
    return _dialog(filedialog.askopenfilename, **options)


def pick_audio_file(initial_dir: str | None = None) -> str:
    """Open the OS file chooser for a voice clip. Returns "" if cancelled.

    The same extensions the rest of Tertius will decode, so that a clip which
    passes this dialog is one the model can actually be given - the alternative
    is a picker that happily accepts a `.wma` and a failure minutes later.
    """
    from tkinter import filedialog

    # This module is launched as a standalone script, not imported as part of
    # the package, so a relative import fails here - and would fail as an
    # ImportError, which `main` reads as "tkinter is missing" and reports as
    # the wrong problem entirely. The flat import is the one that works when
    # the file's own directory is on sys.path; the relative one is for when
    # something imports this properly. Neither working is survivable.
    try:
        from config import MEDIA_EXTENSIONS
    except ImportError:  # pragma: no cover - only when imported as a module
        try:
            from .config import MEDIA_EXTENSIONS
        except ImportError:
            MEDIA_EXTENSIONS = ()

    patterns = " ".join(sorted(f"*{ext}" for ext in MEDIA_EXTENSIONS))
    options = {
        "title": "Choose a recording of the voice to read in",
        "filetypes": (
            [("Audio and video", patterns), ("All files", "*.*")]
            if patterns
            else [("All files", "*.*")]
        ),
    }
    if initial_dir:
        options["initialdir"] = initial_dir
    return _dialog(filedialog.askopenfilename, **options)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    want_file = "--file" in argv
    want_audio = "--audio" in argv
    rest = [a for a in argv if a not in ("--file", "--audio")]
    initial = rest[0] if rest else None

    try:
        if want_audio:
            path = pick_audio_file(initial)
        elif want_file:
            path = pick_text_file(initial)
        else:
            path = pick_folder(initial)
    except ImportError:
        # tkinter is part of the standard library but is packaged separately on
        # most Linux distributions, so a perfectly good Python can be missing it.
        return EXIT_NO_TKINTER
    except Exception as exc:
        # Tk raises TclError for "no display name and no $DISPLAY", which is
        # what a headless box, a bare SSH session or WSL without an X server
        # looks like. Matched on the message because importing tkinter just to
        # name the exception class would defeat the ImportError branch above.
        if "display" in str(exc).lower():
            return EXIT_NO_DISPLAY
        raise

    if path:
        sys.stdout.write(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
