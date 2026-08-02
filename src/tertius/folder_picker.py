"""Native "choose a folder" dialog, run as a throwaway subprocess.

A browser cannot hand a web page a real folder path (it deliberately hides the
filesystem), but this server is local, so we can open the OS picker on the same
machine and read the path back.

The dialog is modal: it blocks its process until the user answers. That is why
this is a separate process rather than a call inside a request handler - a
wedged dialog must never be able to freeze the server. Run it standalone:

    python folder_picker.py [initial_directory]

Prints the chosen path to stdout, or nothing if the user cancelled.
"""

from __future__ import annotations

import sys


def pick_folder(initial_dir: str | None = None) -> str:
    """Open the OS folder chooser. Returns "" if the user cancels."""
    import tkinter
    from tkinter import filedialog

    root = tkinter.Tk()
    root.withdraw()  # we only want the dialog, not an empty window
    root.attributes("-topmost", True)  # else it can hide behind the browser
    try:
        options = {"title": "Choose a folder of audio or video files"}
        if initial_dir:
            options["initialdir"] = initial_dir
        return filedialog.askdirectory(**options) or ""
    finally:
        root.destroy()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    path = pick_folder(argv[0] if argv else None)
    if path:
        sys.stdout.write(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
