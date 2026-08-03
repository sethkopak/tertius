"""Entry point: `python -m tertius` (or the `tertius` command)."""

from __future__ import annotations

import argparse
import logging
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from .app import create_app
from .config import LOG_FILENAME, default_output_dir


def configure_logging(output_dir: Path, verbose: bool = False) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    handlers = [
        logging.StreamHandler(),
        logging.FileHandler(output_dir / LOG_FILENAME, encoding="utf-8"),
    ]
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


def server_already_running(url: str, timeout: float = 1.5) -> bool:
    """Is a Tertius server already answering at `url`?

    Worth checking before binding: Windows lets a second process bind a port that
    is already in use, which would give you two job managers writing one state
    file. Elsewhere the bind just fails.
    """
    try:
        with urllib.request.urlopen(url + "api/status", timeout=timeout) as response:
            return getattr(response, "status", 200) == 200
    except (urllib.error.URLError, OSError):
        return False


def open_browser_when_ready(url: str, timeout: float = 30.0) -> bool:
    """Poll the status endpoint, then open a browser tab. Returns whether it opened.

    Runs on its own thread so it does not delay the server coming up, and never
    raises into the caller: failing to open a tab is a nuisance, not an error.
    """
    log = logging.getLogger("tertius")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "api/status", timeout=1) as response:
                response.read(1)
            break
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    else:
        log.warning("server did not answer within %.0fs; not opening a browser", timeout)
        return False
    try:
        return webbrowser.open(url)
    except Exception as exc:  # no browser association, headless box, ...
        log.warning("could not open a browser (%s) - open %s yourself", exc, url)
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tertius",
        description="Tertius - local offline batch transcription (faster-whisper + Flask)",
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address")
    parser.add_argument("--port", type=int, default=5005, help="port")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="where transcripts, the state file and the log are written",
    )
    parser.add_argument("--verbose", action="store_true", help="debug logging")
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="open the UI in your default browser once the server is up",
    )
    parser.add_argument(
        "--reuse-existing",
        action="store_true",
        help=(
            "if Tertius is already running on this port, show it instead of "
            "starting a second one"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else default_output_dir()
    )
    configure_logging(output_dir, args.verbose)
    log = logging.getLogger("tertius")
    url = f"http://{args.host}:{args.port}/"

    # Before touching the output directory: creating the app attaches to the state
    # file and resets in-progress entries, which would corrupt a job running in
    # another process.
    if args.reuse_existing and server_already_running(url):
        log.info("Tertius is already running at %s - showing that one", url)
        if args.open_browser:
            webbrowser.open(url)
        return 0

    app = create_app(output_dir)
    manager = app.config["JOB_MANAGER"]
    status = manager.status(include_files=False)
    log.info("output directory: %s", output_dir)

    # Say this at startup as well as in the UI: a new user is looking at this
    # window, and finding out mid-batch that the GPU was never usable is a bad
    # way to learn it.
    try:
        from .system import describe_system

        runtime = describe_system().get("cuda_runtime", {})
        state = runtime.get("state")
        if state == "missing":
            log.warning("GPU detected but unusable - %s", runtime.get("detail"))
        elif state == "ok":
            log.info("CUDA runtime libraries found; the GPU is available")
        elif state == "cpu_only":
            # Stated plainly, not as a warning: on a Mac this is the normal
            # state of affairs, not a problem waiting to be solved.
            log.info("%s", runtime.get("detail"))
    except Exception as exc:  # a capability probe must never stop the server
        log.debug("could not check the CUDA runtime: %s", exc)
    if status.get("can_resume"):
        summary = status["summary"]
        log.info(
            "found an unfinished job: %d pending of %d file(s) - resume from the UI",
            summary.get("pending", 0),
            summary.get("total", 0),
        )
    log.info("serving on %s", url)

    if args.open_browser:
        threading.Thread(
            target=open_browser_when_ready,
            args=(url,),
            name="browser-opener",
            daemon=True,
        ).start()

    # threaded=True so status polling stays responsive; the job itself lives on
    # its own worker thread either way. No reloader: it would fork the process
    # and orphan a running job.
    app.run(
        host=args.host,
        port=args.port,
        threaded=True,
        debug=False,
        use_reloader=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
