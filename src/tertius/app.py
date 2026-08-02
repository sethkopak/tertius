"""Flask app: thin HTTP shell around the background JobManager.

No route ever performs transcription. Routes queue work, read status, or serve
files; the worker thread does everything else.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from .config import (
    COMPUTE_TYPES,
    DEVICES,
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
        added = store.add_files(paths)
        return jsonify({"added": len(added), "status": manager.status()})

    @app.post("/api/upload")
    def api_upload():
        uploaded = request.files.getlist("files")
        if not uploaded:
            return _error("no files uploaded")
        store = manager.store
        if store is None:
            return _error("no output directory attached", 409)
        saved: list[str] = []
        rejected: list[str] = []
        for item in uploaded:
            name = Path(item.filename or "").name
            if not name:
                continue
            target = upload_dir() / name
            item.save(str(target))
            if is_media_file(target):
                saved.append(str(target))
            else:
                rejected.append(name)
                target.unlink(missing_ok=True)
        if saved:
            store.add_files(saved)
        return jsonify(
            {"saved": saved, "rejected": rejected, "status": manager.status()}
        )

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
