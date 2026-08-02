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

from .config import (
    COMPUTE_TYPES,
    DEVICES,
    GRANULARITIES,
    MODEL_SIZES,
    OUTPUT_FORMATS,
    UPLOAD_DIRNAME,
    TranscriptionOptions,
    default_output_dir,
    is_media_file,
    scan_directory,
)
from .jobs import JobError, JobManager
from .system import assess_model, check_compute_type, describe_system
from .transcribe import is_model_cached

log = logging.getLogger(__name__)


def _error(message: str, code: int = 400):
    return jsonify({"error": message}), code


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
            granularities=GRANULARITIES,
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
        try:
            files = scan_directory(Path(directory), recursive=recursive)
        except NotADirectoryError as exc:
            return _error(str(exc), 404)
        except OSError as exc:
            return _error(f"could not read directory: {exc}", 400)
        return jsonify(
            {
                "directory": str(Path(directory).expanduser().resolve()),
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
            return _error(
                "no folder picker available on this machine - paste the path instead",
                503,
            )
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
        added = store.add_files(
            paths, base_dir=base_dir, match_reference_text=match_text
        )
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
        """Native file picker for choosing a .txt to pair with one audio file."""
        body = request.get_json(silent=True) or {}
        script = str(Path(__file__).with_name("folder_picker.py"))
        command = [sys.executable, script, "--file"]
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
            mimetype="text/plain",
            as_attachment=download,
            download_name=target.name,
        )

    return app
