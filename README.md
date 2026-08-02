# Tertius

Offline batch transcription of audio/video files using
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), with a small Flask UI
for a resumable queue.

Runs entirely on your machine: no API calls, no cloud services, no telemetry. The
only network access it ever makes is the one-time model download from Hugging Face
(see [Models](#models) — you can pre-download and then run air-gapped).

## Install

Nothing to do if you use `Start Tertius.bat` — it sets this up on first run.
Manually:

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Or install the package itself (gives you the `tertius` command):

```bash
pip install -e ".[dev]"
```

`faster-whisper` pulls in `ctranslate2` and `av` (prebuilt wheels for both). Audio
decoding goes through `av`, so no separate FFmpeg install is required. Verified on
Python 3.14 with faster-whisper 1.2.1 / ctranslate2 4.8.1. If `pip install
faster-whisper` ever fails with "no matching distribution", your Python is newer
than the available `ctranslate2` wheels — drop back a minor version.

## Launch

**Double-click `Start Tertius.bat`.** It creates the virtual environment and
installs dependencies if they're missing (first run only), starts the server, and
opens the UI in your browser.

A console window stays open while it runs — that window *is* the server. Leave it
open while transcribing; closing it (or Ctrl+C) stops the server. Transcripts go to
`transcripts\` next to the .bat. To change the port or output folder, edit the two
settings at the top of the file.

The install step is skipped on later runs, so subsequent launches are quick.

### Closed the tab by accident?

**Double-click `Start Tertius.bat` again.** It notices the server is already
running, re-opens the tab, and exits without starting a second server. The console
window just flashes; the original one keeps running. Or bookmark
<http://127.0.0.1:5005> and open it whenever you like — the page reconnects to
whatever the job is doing, including a batch that is mid-run.

This matters beyond convenience: on Windows a second process *can* bind a port
that is already in use, so without that check you would end up with two servers
sharing one state file. If you start the server by hand, pass `--reuse-existing`
to get the same protection, and never point two servers at one output directory.

From a terminal instead:

```bash
python -m tertius --output-dir "D:/transcripts" --open-browser
# or, if installed:
tertius --output-dir "D:/transcripts"
```

Then open <http://127.0.0.1:5005>.

| Flag | Default | Meaning |
| --- | --- | --- |
| `--host` | `127.0.0.1` | Bind address. Localhost only by default — this app has no auth. |
| `--port` | `5005` | Port. |
| `--output-dir` | `./transcripts` (or `$TERTIUS_OUTPUT_DIR`) | Transcripts, state file, and log all live here. |
| `--open-browser` | off | Open the UI once the server answers. What the .bat uses. |
| `--reuse-existing` | off | If a server is already on this port, show it and exit instead of starting a second one. |
| `--verbose` | off | Debug logging. |

## Using it

1. **Add files** — either point it at a folder (**Browse…** opens a normal Windows
   folder picker, or paste the path yourself) and hit *Scan & queue*, or upload
   individual files, which are copied into `<output-dir>/_uploads/`.
2. **Options** — model size (default `large-v3-turbo`), device, compute type,
   language, output formats. The **i** button next to the model dropdown opens a
   comparison table; see [Which model?](#which-model).
3. **Start batch.** The request returns immediately; the work happens on a
   background worker thread.
4. Watch the queue table. Completed transcripts are downloadable from the UI;
   failed files show their error message inline and can be re-queued with
   *Retry failed*.

Every button and field has a tooltip — hover if something is unclear. The
**☀ Light / ☾ Dark** button in the top right switches theme; dark is the default
and your choice is remembered in that browser.

Recognised input extensions: `.mp3 .wav .m4a .mp4 .flac .ogg .opus .webm .mkv
.mov .aac .wma .avi`.

### What "Scan & queue" actually does

It finds every recognised audio/video file in that folder and adds **all of them**
to the queue — then transcribes the lot when you press *Start batch*. It is not a
sample or a first-N.

**Include subfolders** (ticked by default) controls how deep it looks:

- **Ticked** — every subfolder, however deeply nested.
- **Unticked** — only files sitting directly in the folder you chose.

Non-media files are ignored either way, and so is the `_uploads` folder. Scanning
never starts transcription, and re-scanning the same folder is safe: files already
in the queue keep their status, and anything already transcribed is skipped rather
than redone.

## The job is independent of your browser

The transcription job lives on a worker thread owned by the server process, not
inside a request handler. That means:

- Closing the tab, losing the network, or a request timing out does not stop it.
- Reopening the page (or opening a second tab) reconnects to the *same* job: the
  UI holds no state of its own, it just polls `GET /api/status` every 1–2s.
- The job keeps running until it finishes, you cancel it, or the server process
  exits.

Cancelling is graceful: the file being transcribed finishes, the rest stay
pending, and you can resume later.

## How resume works

Every state change is written immediately to `<output-dir>/transcription_state.json`
(temp file + atomic replace, so a `kill -9` mid-write cannot corrupt it). Each file
is `pending`, `in_progress`, `done`, `failed`, or `skipped`, with timestamps,
error text, and the transcripts it produced.

On startup the server reads that file and:

- **`done` files are never redone** — they are counted as "already done (skipped)"
  in the batch summary.
- **`in_progress` files are reset to `pending`.** A file that was mid-transcription
  when the process died is *not* assumed to have valid output; it is transcribed
  again from scratch. (Transcripts are written temp-then-replace, so a partial file
  never lands under the real name either.)
- **`failed` files stay failed** so you can see what went wrong. *Retry failed*
  puts them back in the queue.

If anything is pending, the UI shows a **"Unfinished job found"** banner with a
*Resume* button, and the console logs the same thing at startup.

One file failing never stops the batch: the error is logged, that file is marked
`failed`, and the run continues with the next file. A *model* failure (bad model
name, no CUDA device) is different — it is reported as a job-level error and the
files stay pending, so you can fix the setting and resume.

## Models

**No model weights ship with this app** — the project contains no `.bin` files and
nothing is bundled into the venv. faster-whisper downloads a model from Hugging
Face **the first time you actually use it**, then caches it forever.

Only the model you select is fetched, not all of them. Picking a different size in
the UI later triggers one more download for that size.

Cache location:

- Windows: `C:\Users\<you>\.cache\huggingface\hub`
- macOS / Linux: `~/.cache/huggingface/hub`

Override with the `HF_HOME` environment variable.

The default is **`large-v3-turbo`** — large-v3 accuracy at roughly small-model
speed. faster-whisper resolves it to `mobiuslabsgmbh/faster-whisper-large-v3-turbo`
and its files total **1.51 GB** (`model.bin` is 1,543 MB of that). Sizes for the
others: `tiny` ~75 MB, `base` ~145 MB, `small` ~485 MB, `medium` ~1.5 GB,
`large-v2` / `large-v3` ~3 GB. Drop to `small` or `base` if you're CPU-only and
want speed over accuracy.

faster-whisper also accepts `turbo` and `large` as aliases for `large-v3-turbo`
and `large-v3`. They aren't offered in the dropdown — two entries for identical
weights only makes the list confusing — but they're still honoured if one arrives
from an older state file or a direct API call.

**What the first run looks like:** the download happens when you press *Start
batch*, before any file is transcribed. The UI shows a **"Downloading model…"**
panel with a percentage bar and the expected size, so a long first run is
obviously a download and not a hang. Transcription starts on its own the moment it
finishes. This happens once per model size.

(The percentage comes from `huggingface_hub`'s own progress bars. It runs
overlapping bars whose byte totals roughly double-count, so the panel shows the
percentage alongside the *measured* download size rather than that inflated
figure.)

### Which model?

The **i** button beside the model dropdown opens a comparison table: download
size, whether it is already on disk, relative speed, what to expect from the
transcript, and a verdict for **your** machine.

Tertius reads real numbers to produce that verdict — total RAM, CPU cores, and
(via CTranslate2 and `nvidia-smi`) whether there is a CUDA GPU, which one, and how
much VRAM it has. A model needs roughly its own size plus about 1 GB of working
room; past ~60% of the memory it will run in you get **Tight**, past ~90%
**Too big**. `auto` is resolved first, so the check looks at VRAM when the job
will land on the GPU and RAM when it will not. It also warns when a compute type
is not supported on the device you picked (for example `float16` on CPU, which
CTranslate2 cannot do) and when `cuda` is selected on a machine with no CUDA GPU.

These are estimates meant to prevent nasty surprises, not guarantees.

Once cached, set `HF_HUB_OFFLINE=1` to run with no network access at all. To
pre-download without transcribing anything:

```bash
.venv\Scripts\python -c "from faster_whisper import WhisperModel; WhisperModel('large-v3-turbo')"
```

## GPU (CUDA)

> **If you see `Library cublas64_12.dll is not found or cannot be loaded`:** your
> NVIDIA *driver* is installed but the CUDA *runtime libraries* are not. The
> driver is what makes a GPU show up; the runtime is what actually does the
> maths. Install them into the venv:
>
> ```bash
> .venv\Scripts\pip install nvidia-cublas-cu12 nvidia-cudnn-cu12
> ```
>
> That is about 1.2 GB. Tertius adds those packages' `bin` folders to Windows'
> DLL search path at startup, which Windows does not do on its own — installing
> them without that leaves the libraries present and still "not found". Or just
> set **Device** to `cpu` and accept the slower run.


Set **Device** to `cuda` and **Compute** to `float16` (or `int8_float16` on smaller
cards). On CPU, use `int8` for a large speedup at a small accuracy cost.

**`auto` proves the GPU works before using it.** A CUDA device merely *existing*
is not enough — loading a model on CUDA succeeds even when the runtime libraries
are missing, and the failure only appears on the first encode. So Tertius runs a
one-second dummy transcription at job start:

- `auto` — if that fails, it quietly rebuilds on the CPU and tells you why in the
  Run panel. The batch still runs.
- `cuda` — if that fails, the job stops with the error and the fix, rather than
  silently taking ten times longer on the CPU than you expected.

Once a CUDA operation has failed, Tertius will not touch the GPU again for the
life of the process. That is not caution for its own sake: after a failed CUDA
call, CTranslate2 can *deadlock* on the next one instead of raising, which is
unrecoverable from Python.

If the model fails to load, the UI shows the error and nothing is marked failed.

## When Cancel won't take

Cancel is cooperative and is checked *between* files, so it can take a while on a
long file. If a file wedges inside the model's native code, Cancel can never land
at all — Python cannot interrupt a native call.

After 20 seconds of waiting, Tertius stops pretending: it explains the situation
and shows a **Force stop** button, which kills the server outright. That is safe
here by design — the state file is durable, so relaunch, press **Resume**, and the
interrupted file is transcribed again from scratch while finished work is kept.

Relatedly, if three files in a row fail with the *same* error, the batch stops
instead of grinding through the rest of the queue to fail every one of them. The
remaining files stay pending.

## Output

One transcript per input file per format, named after the source, in the output
directory:

```
lecture1.mp3  ->  lecture1.txt
                  lecture1.srt
```

`.txt` is one line per segment. `.srt` is standard numbered subtitles with
`HH:MM:SS,mmm` timings.

Also in the output directory: `transcription_state.json` (the queue), and
`tertius.log` (per-file start/end plus errors, mirrored to the console).

Note: two source files with the same stem in different folders (`a/talk.mp3` and
`b/talk.mp3`) write to the same transcript name. Use separate output directories
for those.

## HTTP API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/status` | Full job + queue state (what the UI polls). |
| `POST` | `/api/scan` | `{directory, recursive}` → media files found. |
| `POST` | `/api/queue` | `{files: [...]}` → add to queue without starting. |
| `POST` | `/api/upload` | multipart `files` → save to `_uploads/` and queue. |
| `POST` | `/api/job/start` | `{files?, output_dir?, options?, retry_failed?}` → returns at once. |
| `POST` | `/api/job/resume` | Work the pending set from an interrupted run. |
| `POST` | `/api/job/cancel` | Stop after the current file. |
| `POST` | `/api/job/retry-failed` | Move `failed` back to `pending`. |
| `POST` | `/api/queue/remove` | `{path}` → drop a file from the queue (not while running). |
| `GET` | `/api/transcript?name=…&download=1` | Fetch a transcript from the output dir. |
| `GET` | `/api/system?device=…&compute_type=…` | Machine capabilities + a verdict per model. |
| `POST` | `/api/browse-folder` | Open the OS folder picker on this machine, return the path. |

## Tests

```bash
pytest
```

111 tests. The whisper model is mocked throughout — the suite downloads nothing
and decodes no audio. Coverage is aimed at what is easy to get wrong: state
tracking and resume semantics, the job's independence from the HTTP request that
started it, download-progress aggregation, and machine-suitability verdicts.

## Layout

```
Start Tertius.bat   double-click launcher (setup + run + open browser)
src/tertius/
  config.py        options, validation, media-file scanning
  state.py         StateStore — atomic JSON state, status transitions
  transcribe.py    faster-whisper wrapper, model download + progress, txt/srt output
  jobs.py          JobManager — the background worker, its phase and status
  system.py        RAM/GPU detection, model catalogue, per-machine verdicts
  folder_picker.py native folder dialog, run as its own process
  app.py           Flask routes (they queue and report; they never transcribe)
  __main__.py      CLI entry point, logging, browser opening
tests/             state, jobs, HTTP, downloads, system advice, output formats
```

## Not included

No live microphone transcription (file/batch only) and no auth or multi-user
support — this is a single-user local tool. Don't bind it to `0.0.0.0` on an
untrusted network: the scan and queue endpoints will read any path the server
process can read.
