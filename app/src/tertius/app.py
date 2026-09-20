"""Flask app: thin HTTP shell around the background JobManager.

No route ever performs transcription. Routes queue work, read status, or serve
files; the worker thread does everything else.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from . import __version__
from .config import (
    COMPUTE_TYPES,
    DEFAULT_SPEECH_STYLE,
    DEVICES,
    GRANULARITIES,
    MODEL_SIZES,
    OUTPUT_FORMATS,
    PARALINGUISTIC_TAGS,
    SPEECH_MODEL_NAMES,
    SPEECH_MODELS,
    SPEECH_STYLE_ALIASES,
    SPEECH_STYLE_NAMES,
    TRANSLATION_MODEL_SIZES,
    TRANSLATION_MODELS,
    UPLOAD_DIRNAME,
    TranscriptionOptions,
    default_output_dir,
    is_media_file,
    language_choices,
    scan_directory,
)
from . import folder_picker
from .jobs import JobError, JobManager
from .media import probe_durations_in_background
from .system import assess_model, check_compute_type, describe_system
from .transcribe import is_model_cached

log = logging.getLogger(__name__)


def _error(message: str, code: int = 400):
    return jsonify({"error": message}), code


def _picker_failure(returncode: int) -> str:
    """Turn the picker's exit code into something the user can act on.

    Both of these are ordinary on Linux and neither is the app's fault, so the
    message names the actual cause and the fix instead of shrugging.
    """
    if returncode == folder_picker.EXIT_NO_TKINTER:
        return (
            "This Python has no tkinter, so the folder picker cannot open. "
            "Install it (Debian/Ubuntu: sudo apt install python3-tk, "
            "Fedora: sudo dnf install python3-tkinter, macOS: brew install "
            "python-tk) or just paste the folder path into the box."
        )
    if returncode == folder_picker.EXIT_NO_DISPLAY:
        return (
            "There is no desktop session to open a window on - Tertius looks "
            "to be running headless, over SSH, or in WSL without an X server. "
            "Paste the folder path into the box instead."
        )
    return "no folder picker available on this machine - paste the path instead"


def create_app(output_dir: str | Path | None = None, manager: JobManager | None = None):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024 * 1024  # 8 GiB uploads

    manager = manager or JobManager()
    out = Path(output_dir or default_output_dir()).expanduser().resolve()
    manager.attach(out)
    app.config["JOB_MANAGER"] = manager

    def upload_dir() -> Path:
        target = (manager.output_dir or out) / UPLOAD_DIRNAME
        target.mkdir(parents=True, exist_ok=True)
        return target

    # ------------------------------------------------------------------- page

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            model_sizes=MODEL_SIZES,
            devices=DEVICES,
            compute_types=COMPUTE_TYPES,
            formats=OUTPUT_FORMATS,
            # Which chips start pressed. Without this the page seeded the set
            # from every chip on the row, so adding a format silently switched
            # it on for everyone with no saved settings.
            default_formats=TranscriptionOptions().formats,
            granularities=GRANULARITIES,
            languages=language_choices(),
            translation_models=TRANSLATION_MODEL_SIZES,
            translation_catalog=TRANSLATION_MODELS,
            default_translation_model=TranscriptionOptions().translation_model,
            speech_models=SPEECH_MODEL_NAMES,
            speech_catalog=SPEECH_MODELS,
            default_speech_model=TranscriptionOptions().speech_model,
            speech_styles=SPEECH_STYLE_NAMES,
            default_speech_style=DEFAULT_SPEECH_STYLE,
            app_version=__version__,
            default_output_dir=str(manager.output_dir or out),
        )

    # ------------------------------------------------------------------- API

    @app.get("/api/status")
    def api_status():
        return jsonify(manager.status())

    @app.post("/api/scan")
    def api_scan():
        body = request.get_json(silent=True) or {}
        directory = (body.get("directory") or "").strip()
        if not directory:
            return _error("directory is required")
        recursive = bool(body.get("recursive", True))
        # `kind="text"` queues `.txt` files as sources in their own right, with
        # no audio. See scan_directory for why it is a separate scan.
        kind = (body.get("kind") or "media").strip().lower()
        try:
            files = scan_directory(Path(directory), recursive=recursive, kind=kind)
        except ValueError as exc:
            return _error(str(exc), 400)
        except NotADirectoryError as exc:
            return _error(str(exc), 404)
        except OSError as exc:
            return _error(f"could not read directory: {exc}", 400)
        return jsonify(
            {
                "directory": str(Path(directory).expanduser().resolve()),
                "kind": kind,
                "count": len(files),
                "files": [str(f) for f in files],
            }
        )

    @app.get("/api/system")
    def api_system():
        """Machine capabilities plus a per-model verdict for it."""
        info = describe_system()
        device = request.args.get("device", "auto")
        compute_type = request.args.get("compute_type", "default")
        models = []
        for name in MODEL_SIZES:
            try:
                cached = is_model_cached(name)
            except Exception:
                cached = None
            models.append(assess_model(name, device, info, cached=cached))
        return jsonify(
            {
                "system": info,
                "models": models,
                "compute_warning": check_compute_type(compute_type, device, info),
            }
        )

    @app.get("/api/translation/models")
    def api_translation_models():
        """The translation models, for the comparison table behind the i button.

        No "on this machine" verdict, unlike the Whisper table. Translation has
        only ever been run on the CPU here, so any judgement about whether one
        of these fits alongside Whisper on a GPU would be invented. What is
        reported is what is known: the download, whether it is prepared, and
        how big it turned out once converted.
        """
        from .translate import converted_size, is_converted

        models = []
        for name, entry in TRANSLATION_MODELS.items():
            try:
                ready = is_converted(name)
                disk = converted_size(name) if ready else None
            except Exception:
                ready, disk = False, None
            models.append(
                {
                    "model": name,
                    "repo": entry["repo"],
                    "license": entry["license"],
                    "languages": entry["languages"],
                    "download_bytes": entry["download_bytes"],
                    "speed": entry["speed"],
                    "quality": entry["quality"],
                    "ready": ready,
                    "disk_bytes": disk,
                }
            )
        return jsonify({"models": models})

    @app.get("/api/translation/languages")
    def api_translation_languages():
        """What the chosen translation model can translate into, and its cost.

        The language list is empty until the model has been converted, because
        the codes are read out of the converted vocabulary rather than a table
        kept here by hand. `ready` is what the UI needs to say "this will
        download 1.9 GB first" instead of appearing to hang on Begin.
        """
        from .translate import is_converted, supported_target_languages

        name = request.args.get("model") or TranscriptionOptions().translation_model
        if name not in TRANSLATION_MODELS:
            return _error(f"unknown translation model: {name}", 404)
        entry = TRANSLATION_MODELS[name]
        try:
            ready = is_converted(name)
        except Exception:
            ready = False
        languages = list(supported_target_languages(name)) if ready else []

        # Which of these the voice model can also *say*, rather than a
        # narrowed list. The two sets are genuinely different sizes - a hundred
        # languages against twenty-three - and wanting Romanian text is not the
        # same as being unable to have Romanian text at all. The page offers
        # both lists and keeps them in step; this only has to say which is
        # which.
        speech_model = request.args.get(
            "speech_model", TranscriptionOptions().speech_model
        )
        spoken: list[str] = []
        if speech_model in SPEECH_MODELS:
            from .speech import speech_language_choices

            spoken = [
                code
                for code in speech_language_choices(speech_model)
                if not languages or code in languages
            ]

        return jsonify(
            {
                "model": name,
                "ready": ready,
                "languages": languages,
                "speakable": spoken,
                "speech_model": speech_model,
                "download_bytes": entry["download_bytes"],
                "license": entry["license"],
                "language_count": entry["languages"],
            }
        )

    @app.post("/api/translation/prepare")
    def api_translation_prepare():
        """Make a translation model ready, so its languages can be listed."""
        body = request.get_json(silent=True) or {}
        name = body.get("model") or TranscriptionOptions().translation_model
        try:
            return jsonify(manager.prepare_translation(name))
        except JobError as exc:
            return _error(str(exc), 409)

    @app.get("/api/speech/models")
    def api_speech_models():
        """The speech models, for the comparison table behind the i button.

        No "on this machine" verdict, for the same reason the translation table
        has none: nothing here has been run on a GPU yet, so any judgement
        about whether one of these fits beside Whisper would be invented. What
        is reported is what is known - the download, and whether it is already
        on disk.
        """
        from .speech import is_downloaded, torch_install_problem

        models = []
        for name, entry in SPEECH_MODELS.items():
            try:
                ready = is_downloaded(name)
            except Exception:
                ready = False
            models.append(
                {
                    "model": name,
                    "repo": entry["repo"],
                    "license": entry["license"],
                    "languages": entry["languages"],
                    "download_bytes": entry["download_bytes"],
                    "speed": entry["speed"],
                    "quality": entry["quality"],
                    "paralinguistic": bool(entry.get("paralinguistic")),
                    "vram_bytes": entry.get("vram_bytes"),
                    "ready": ready,
                }
            )
        try:
            problem = torch_install_problem()
        except Exception:
            problem = None
        return jsonify({"models": models, "torch_problem": problem})

    @app.get("/api/speech/languages")
    def api_speech_languages():
        """What the chosen speech model can read, and what the styles are.

        Unlike the translation menu this can be answered before anything is
        downloaded: the list is a constant in the package rather than something
        read out of a converted vocabulary.
        """
        from .speech import is_downloaded, speech_language_choices

        name = request.args.get("model") or TranscriptionOptions().speech_model
        if name not in SPEECH_MODELS:
            return _error(f"unknown speech model: {name}", 404)
        entry = SPEECH_MODELS[name]
        try:
            ready = is_downloaded(name)
        except Exception:
            ready = False
        return jsonify(
            {
                "model": name,
                "ready": ready,
                "languages": list(speech_language_choices(name)),
                "styles": list(SPEECH_STYLE_NAMES),
                "aliases": dict(SPEECH_STYLE_ALIASES),
                "paralinguistic": sorted(PARALINGUISTIC_TAGS)
                if entry.get("paralinguistic")
                else [],
                "download_bytes": entry["download_bytes"],
                "license": entry["license"],
            }
        )

    @app.post("/api/speech/prepare")
    def api_speech_prepare():
        """Install what speaking needs and fetch the weights."""
        body = request.get_json(silent=True) or {}
        name = body.get("model") or TranscriptionOptions().speech_model
        try:
            return jsonify(manager.prepare_speech(name))
        except JobError as exc:
            return _error(str(exc), 409)

    @app.post("/api/speech/preview")
    def api_speech_preview():
        """Show what a text file's tags did, without generating any audio.

        The whole point: style tags are invisible until something is read
        aloud, and finding out that `[emphatic]` was spelt `[emphatc]` after
        forty minutes of synthesis is the failure this exists to prevent.
        Parsing needs no model and no weights, so the answer is instant.
        """
        from .speech import parse_script

        body = request.get_json(silent=True) or {}
        name = body.get("model") or TranscriptionOptions().speech_model
        if name not in SPEECH_MODELS:
            return _error(f"unknown speech model: {name}", 404)
        style = (body.get("style") or DEFAULT_SPEECH_STYLE).strip().lower()

        text = body.get("text")
        if text is None:
            path = (body.get("path") or "").strip()
            if not path:
                return _error("text or path is required")
            source = Path(path).expanduser()
            if not source.is_file():
                return _error(f"file not found: {path}", 404)
            try:
                text = source.read_text(encoding="utf-8-sig")
            except OSError as exc:
                return _error(f"could not read {source.name}: {exc}", 400)

        try:
            script = parse_script(text, name, style)
        except ValueError as exc:
            return _error(str(exc))
        return jsonify(
            {
                "model": name,
                "chunks": [
                    {
                        "text": chunk.text,
                        "style": chunk.style,
                        "params": chunk.params,
                        "starts_paragraph": chunk.starts_paragraph,
                    }
                    for chunk in script.chunks
                ],
                "count": len(script.chunks),
                "characters": script.characters,
                "styles_used": script.styles_used,
                "warnings": script.warnings,
            }
        )

    @app.post("/api/browse-folder")
    def api_browse_folder():
        """Open the OS folder picker on this machine and return the chosen path.

        Runs as a subprocess: the dialog is modal and would otherwise block the
        server for as long as it stayed open.
        """
        body = request.get_json(silent=True) or {}
        script = str(Path(__file__).with_name("folder_picker.py"))
        command = [sys.executable, script]
        initial = (body.get("initial") or "").strip()
        if initial:
            command.append(initial)
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            finished = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=600,
                creationflags=creation_flags,
            )
        except subprocess.TimeoutExpired:
            return _error("the folder picker was left open too long", 504)
        except OSError as exc:
            return _error(f"could not start the folder picker: {exc}", 503)
        if finished.returncode != 0:
            log.warning("folder picker failed: %s", finished.stderr.strip())
            return _error(_picker_failure(finished.returncode), 503)
        chosen = finished.stdout.strip()
        if not chosen:
            return jsonify({"cancelled": True, "path": None})
        return jsonify({"cancelled": False, "path": str(Path(chosen))})

    @app.post("/api/queue")
    def api_queue():
        """Add files to the queue without starting the job."""
        body = request.get_json(silent=True) or {}
        paths = body.get("files") or []
        if not isinstance(paths, list) or not paths:
            return _error("files must be a non-empty list")
        store = manager.store
        if store is None:
            return _error("no output directory attached", 409)
        missing = [p for p in paths if not Path(p).expanduser().is_file()]
        if missing:
            return _error(f"file(s) not found: {', '.join(missing[:5])}", 404)
        # base_dir is the folder that was scanned; it lets the output directory
        # mirror the source layout.
        base_dir = (body.get("base_dir") or "").strip() or None
        if base_dir and not Path(base_dir).expanduser().is_dir():
            return _error(f"not a directory: {base_dir}", 400)
        match_text = bool(body.get("match_reference_text"))
        # Nothing about the stages is recorded at queue time any more. A `.txt`
        # is a text source; whether it gets translated, read aloud, or both is
        # decided by the options when the job runs - which is what lets it be
        # both, and that combination is the whole point.
        added = store.add_files(
            paths, base_dir=base_dir, match_reference_text=match_text
        )
        # Lengths fill in behind the queue: the files appear at once, and the
        # Length column and the estimate catch up a moment later.
        probe_durations_in_background(store, added)
        status = manager.status()
        return jsonify(
            {
                "added": len(added),
                "matched_text": sum(
                    1 for f in status["files"] if f.get("mode") == "align"
                ),
                "needs_choice": len(store.files_needing_a_decision()),
                "status": status,
            }
        )

    @app.post("/api/queue/mode")
    def api_queue_mode():
        """Set one file to align / transcribe / skip, or attach a text file."""
        body = request.get_json(silent=True) or {}
        store = manager.store
        if store is None:
            return _error("no output directory attached", 409)
        if manager.is_running():
            return _error("cannot change the queue while a job is running", 409)
        path = body.get("path")
        mode = body.get("mode")
        reference = (body.get("reference_text") or "").strip() or None
        if not path or not mode:
            return _error("path and mode are required")
        if store.get(path) is None:
            return _error("file is not in the queue", 404)
        if reference and not Path(reference).expanduser().is_file():
            return _error(f"text file not found: {reference}", 404)
        try:
            entry = store.set_mode(path, mode, reference_text=reference)
        except ValueError as exc:
            return _error(str(exc))
        return jsonify({"file": entry, "status": manager.status()})

    @app.post("/api/queue/rematch-text")
    def api_queue_rematch_text():
        """Look again for text files, after some have been added."""
        store = manager.store
        if store is None:
            return _error("no output directory attached", 409)
        found = store.rematch_reference_texts()
        return jsonify({"matched": found, "status": manager.status()})

    @app.post("/api/queue/decide-all")
    def api_queue_decide_all():
        """Answer every outstanding "no text file" question in one go."""
        body = request.get_json(silent=True) or {}
        mode = body.get("mode")
        store = manager.store
        if store is None:
            return _error("no output directory attached", 409)
        if mode not in ("transcribe", "skip"):
            return _error("mode must be transcribe or skip")
        changed = 0
        for path in store.files_needing_a_decision():
            store.set_mode(path, mode)
            changed += 1
        return jsonify({"changed": changed, "status": manager.status()})

    @app.post("/api/upload")
    def api_upload():
        uploaded = request.files.getlist("files")
        if not uploaded:
            return _error("no files uploaded")
        store = manager.store
        if store is None:
            return _error("no output directory attached", 409)

        # .txt files are kept, not rejected: uploading a recording together with
        # its text is the obvious way to use the timestamping feature, and the
        # two land side by side in _uploads/ so name matching finds them.
        match_text = str(request.form.get("match_reference_text", "")).lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        saved: list[str] = []
        texts: list[str] = []
        rejected: list[str] = []
        for item in uploaded:
            name = Path(item.filename or "").name
            if not name:
                continue
            target = upload_dir() / name
            item.save(str(target))
            if is_media_file(target):
                saved.append(str(target))
            elif target.suffix.lower() == ".txt":
                texts.append(str(target))
            else:
                rejected.append(name)
                target.unlink(missing_ok=True)

        # Save every file before matching, so order of upload does not matter.
        if saved:
            store.add_files(saved, match_reference_text=match_text)
            probe_durations_in_background(store, saved)
        status = manager.status()
        return jsonify(
            {
                "saved": saved,
                "texts": texts,
                "rejected": rejected,
                "matched_text": sum(
                    1 for f in status["files"] if f.get("mode") == "align"
                ),
                "needs_choice": len(store.files_needing_a_decision()),
                "status": status,
            }
        )

    @app.post("/api/queue/reference-mode")
    def api_queue_reference_mode():
        """Turn text-timestamping on or off for everything already queued.

        Without this, ticking the box after queueing did nothing, and the queue
        sat there saying "transcribe" with no explanation.
        """
        body = request.get_json(silent=True) or {}
        store = manager.store
        if store is None:
            return _error("no output directory attached", 409)
        if manager.is_running():
            return _error("cannot change the queue while a job is running", 409)
        enabled = bool(body.get("enabled"))
        if "reference_dir" in body:
            directory = (body.get("reference_dir") or "").strip() or None
            if directory and not Path(directory).expanduser().is_dir():
                return _error(f"not a directory: {directory}", 404)
            store.set_reference_dir(directory)
        matched, undecided, reverted = store.apply_reference_mode(enabled)
        return jsonify(
            {
                "matched": matched,
                "needs_choice": undecided,
                "reverted": reverted,
                "reference_dir": store.reference_dir,
                "status": manager.status(),
            }
        )

    @app.post("/api/browse-text-file")
    def api_browse_text_file():
        """Native file picker: a `.txt` to pair with a recording, or a voice clip."""
        body = request.get_json(silent=True) or {}
        script = str(Path(__file__).with_name("folder_picker.py"))
        # `kind="audio"` picks a voice clip to read in rather than a text file
        # to pair with a recording. One route because the two differ only in
        # which extensions the dialog offers.
        kind = (body.get("kind") or "text").strip().lower()
        command = [sys.executable, script, "--audio" if kind == "audio" else "--file"]
        initial = (body.get("initial") or "").strip()
        if initial:
            command.append(initial)
        try:
            finished = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=600,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            return _error("the file picker was left open too long", 504)
        except OSError as exc:
            return _error(f"could not start the file picker: {exc}", 503)
        if finished.returncode != 0:
            log.warning("file picker failed: %s", finished.stderr.strip())
            return _error(
                "no file picker available on this machine - paste the path instead",
                503,
            )
        chosen = finished.stdout.strip()
        if not chosen:
            return jsonify({"cancelled": True, "path": None})
        return jsonify({"cancelled": False, "path": str(Path(chosen))})

    @app.post("/api/job/start")
    def api_job_start():
        body = request.get_json(silent=True) or {}
        try:
            options = TranscriptionOptions.from_dict(body.get("options"))
        except (TypeError, ValueError) as exc:
            return _error(f"invalid options: {exc}")
        target = body.get("output_dir") or str(manager.output_dir or out)
        try:
            status = manager.start(
                files=body.get("files") or None,
                output_dir=target,
                options=options,
                retry_failed=bool(body.get("retry_failed")),
            )
        except JobError as exc:
            return _error(str(exc), 409)
        except OSError as exc:
            return _error(f"could not use output directory: {exc}", 400)
        return jsonify(status)

    @app.post("/api/job/resume")
    def api_job_resume():
        body = request.get_json(silent=True) or {}
        try:
            status = manager.resume(body.get("output_dir") or None)
        except JobError as exc:
            return _error(str(exc), 409)
        return jsonify(status)

    @app.post("/api/job/cancel")
    def api_job_cancel():
        manager.cancel()
        return jsonify(manager.status())

    @app.post("/api/job/force-stop")
    def api_job_force_stop():
        """Kill the server outright.

        The last resort when a file is wedged inside the model's native code,
        where a cooperative cancel can never land. Safe precisely because the
        state file is durable: on the next launch the in-progress file is reset
        to pending and re-transcribed, and finished work is kept.
        """
        log.warning("force stop requested - exiting the process")

        def bail_out():
            time.sleep(0.4)  # let this response reach the browser first
            os._exit(1)

        threading.Thread(target=bail_out, daemon=True).start()
        return jsonify(
            {
                "stopping": True,
                "message": (
                    "Tertius is shutting down. Nothing finished is lost - "
                    "relaunch it and press Resume to carry on."
                ),
            }
        )

    @app.post("/api/job/retry-failed")
    def api_job_retry_failed():
        store = manager.store
        if store is None:
            return _error("no output directory attached", 409)
        if manager.is_running():
            return _error("a job is already running", 409)
        retried = store.retry_failed()
        return jsonify({"retried": len(retried), "status": manager.status()})

    @app.post("/api/queue/retry")
    def api_queue_retry():
        """Put one failed file back in the queue, leaving the others alone."""
        body = request.get_json(silent=True) or {}
        path = body.get("path")
        store = manager.store
        if not path or store is None:
            return _error("path is required")
        entry = store.get(path)
        if entry is None:
            return _error("file is not in the queue", 404)
        if entry.get("status") != "failed":
            return _error("only a failed file can be retried", 409)
        store.mark_pending(path)
        return jsonify({"status": manager.status()})

    @app.post("/api/queue/remove")
    def api_queue_remove():
        body = request.get_json(silent=True) or {}
        path = body.get("path")
        store = manager.store
        if not path or store is None:
            return _error("path is required")
        if manager.is_running():
            return _error("cannot edit the queue while a job is running", 409)
        return jsonify({"removed": store.remove_file(path), "status": manager.status()})

    @app.post("/api/queue/clear")
    def api_queue_clear():
        """Empty the queue.

        Refused while a job is running, like every other queue edit - pulling
        the list out from under the worker mid-batch is not something the user
        can have meant. Transcripts already written are untouched; this only
        forgets what was lined up.

        Uploaded copies belonging to those entries are cleared too. Nothing else
        will ever refer to them, and leaving them would mean the state file's
        one link to gigabytes on disk had just been deleted.
        """
        store = manager.store
        if store is None:
            return _error("no output directory attached", 409)
        if manager.is_running():
            return _error("cannot clear the queue while a job is running", 409)
        cleared = store.clear()
        removed, reclaimed = store.purge_uploads()
        log.info(
            "queue cleared: %d entr(ies), %d uploaded file(s) removed", cleared, removed
        )
        return jsonify(
            {
                "cleared": cleared,
                "uploads_removed": removed,
                "bytes_reclaimed": reclaimed,
                "status": manager.status(),
            }
        )

    @app.post("/api/open-output")
    def api_open_output():
        """Show the output folder in the desktop file manager.

        The app runs in a browser tab but on the user's own machine, so the
        finished-batch button can genuinely open Explorer/Finder rather than
        printing a path to be copied by hand.
        """
        target = manager.output_dir
        if target is None:
            return _error("no output directory attached", 409)
        try:
            target.mkdir(parents=True, exist_ok=True)
            if sys.platform == "win32":
                os.startfile(str(target))  # noqa: S606 - a folder, on this machine
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except OSError as exc:
            return _error(f"could not open {target}: {exc}", 503)
        return jsonify({"opened": str(target)})

    @app.get("/api/transcript")
    def api_transcript():
        """Serve a transcript from the output directory (and nowhere else)."""
        name = request.args.get("name", "")
        download = request.args.get("download") == "1"
        base = manager.output_dir
        if base is None:
            return _error("no output directory attached", 409)
        target = (base / name).resolve()
        if base not in target.parents and target.parent != base:
            return _error("path outside the output directory", 403)
        if not target.is_file():
            return _error("transcript not found", 404)
        return send_file(
            str(target),
            # Served as text/plain so the browser shows a transcript rather than
            # offering to save it. JSON is the exception: sending it as plain
            # text loses the viewer's formatting and folding.
            mimetype=(
                "application/json"
                if target.suffix.lower() == ".json"
                else "text/plain"
            ),
            as_attachment=download,
            download_name=target.name,
        )

    return app
