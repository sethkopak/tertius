# Prompt for Claude Code: Local Transcription App

Build a local, offline audio transcription app in Python using faster-whisper, with a Flask-based
web UI for managing a batch/resumable transcription queue.

## Core requirements

- Runs 100% locally — no API calls, no cloud services, no telemetry.
- Transcribes audio/video files (.mp3, .wav, .m4a, .mp4, .flac at minimum) using faster-whisper.
- Accepts a directory of files or individually uploaded/selected files; processes them as a batch/queue.
- Resumable: if the app or job is interrupted (browser closed, server restarted, process killed),
  restarting should skip files already transcribed and continue with the rest — not redo completed
  work or duplicate output.
  - Track progress in a state file (JSON or SQLite) in the output directory: which files are pending,
    in-progress, done, or failed, plus timestamps.
  - If a file was "in-progress" when interrupted, treat it as incomplete and re-transcribe it on
    resume (don't assume partial output is valid).
- One file failing (corrupt audio, unsupported format, etc.) should not stop the batch — log the
  error, mark that file as failed, and continue with the next.

## Web UI (Flask) — critical architecture requirement

- The transcription job MUST run in a background thread/process on the server, completely
  independent of any HTTP request or browser connection.
  - Starting a batch job kicks off background work and returns immediately.
  - Closing the browser tab, losing network connection, or the request timing out must NOT stop
    the job.
  - Reopening the browser (or opening a new tab) should reconnect to the current job state and
    show live progress — the UI polls a status endpoint rather than holding the job inside a
    request handler.
- UI should let the user:
  - Select/upload files or point to a folder of files.
  - Start a batch job.
  - See queue status: which files are pending/in-progress/done/failed, with a progress indicator.
  - Resume a previous interrupted job (detect existing state on startup and offer to resume).
  - View/download completed transcripts.
  - See per-file error messages for failed items.
- Keep the frontend simple (plain HTML/JS or a lightweight framework) — functionality over polish.

## Transcription options (exposed in UI and/or config)

- Model size (tiny/base/small/medium/large-v3) — default to small or base.
- Device (cpu/cuda/auto) and compute type (int8/float16, etc. — CTranslate2 params).
- Language (optional; auto-detect if not specified).
- Output format: at least .txt and .srt.

## Output

- One transcript file per input file, named to match (e.g. `lecture1.mp3` → `lecture1.txt`),
  written to a configurable output directory.
- End-of-batch summary: total files, completed, failed, skipped (already done).

## Project structure

- Reasonable Python project layout (pyproject.toml or requirements.txt, src/ module layout, clear
  entry point to launch the Flask server).
- Use faster-whisper's Python API directly (not shelling out).
- Logging to console and a log file — per-file start/end and errors.
- README covering: install, first-run model download behavior (faster-whisper downloads models on
  first use — note where they're cached), how to launch the app, how resume works, and any GPU
  setup notes if CUDA is used.

## Testing

- Tests for the state-tracking logic (mark done/failed/pending, resume skips correctly).
- Tests for the background job manager (job survives independent of "request" simulation, status
  endpoint reflects real state).
- Mock the actual whisper model call so tests don't need to download models or process real audio.

## Out of scope for this pass

- No live microphone transcription — file/batch only.
- No user auth/multi-user support — single local user.
