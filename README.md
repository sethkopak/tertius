# Tertius

Offline batch transcription of audio/video files using
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), with a small Flask UI
for a resumable queue.

Runs entirely on your machine: no API calls, no cloud services, no telemetry. The
only network access it ever makes is the one-time model download from Hugging Face
(see [Models](#models) — you can pre-download and then run air-gapped).

## Launch

Everything is in the launcher for your platform. It builds the virtual
environment and installs dependencies on first run, then starts the server and
opens the UI.

| Platform | What to do | Tested? |
| --- | --- | --- |
| **Windows** | Double-click **`Start Tertius.bat`** | Yes — this is the development machine |
| **macOS** | Double-click **`Tertius.app`** | **No — see below** |
| **Linux** | Run **`./start-tertius.sh`** | **No — see below** |

> **Only Windows has been run on real hardware.** There was no Mac or Linux
> machine available while the cross-platform support was written. The test
> suite passes on all three in CI, and the platform-specific decisions have
> tests, but nothing on macOS or Linux has transcribed a real file. Treat the
> first run on either as untested — and please report what breaks.

A console/Terminal window stays open while it runs — that window *is* the
server. Leave it open while transcribing; closing it (or Ctrl+C) stops the
server. Transcripts go to `transcripts/` next to the launcher.

The install step is skipped on later runs, so subsequent launches are quick.

### The icon

Your file manager shows the Tertius **T** on the launcher where the OS allows
it, which is not everywhere:

- **Linux** — the first run writes a `Tertius.desktop` entry beside the script,
  carrying the icon. Most file managers need you to mark it executable and
  click "Allow Launching" once. Because the entry stores absolute paths it is
  regenerated on every launch, so moving the folder fixes itself.
- **macOS** — `Tertius.app` carries its icon in the bundle. Nothing to do.
- **Windows** — a `.bat` file *cannot* have its own icon; Windows takes the
  icon from the file type and offers no per-file override. Instead the launcher
  writes a `Tertius.lnk` shortcut beside itself on every run (shortcuts store
  absolute paths, so it is rewritten rather than committed), and sets the
  folder's own icon via `desktop.ini`.

### Closed the tab by accident?

**Start Tertius again.** It notices the server is already running, re-opens the
tab, and exits without starting a second server. If a batch is mid-run it is
left strictly alone. Or bookmark
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

## Install

Nothing to do if you use a launcher — it sets this up on first run. Manually,
from the `app/` folder:

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
Python 3.14 with faster-whisper 1.2.1 / ctranslate2 4.8.1. ctranslate2 4.8.1
publishes wheels for Windows x86-64, Linux x86-64 and arm64, and macOS Intel and
Apple Silicon, on Python 3.9–3.14, so nothing needs building from source. If
`pip install faster-whisper` ever fails with "no matching distribution", your
Python is newer than the available `ctranslate2` wheels — drop back a minor
version.

**Linux also needs tkinter** for the *Browse* button, which is packaged
separately from Python on most distributions:

```bash
sudo apt install python3-tk        # Debian / Ubuntu
sudo dnf install python3-tkinter   # Fedora
brew install python-tk             # macOS, if you use Homebrew's Python
```

Without it everything still works — you paste the folder path into the box
instead of picking it, and Tertius says so rather than failing vaguely.

| Flag | Default | Meaning |
| --- | --- | --- |
| `--host` | `127.0.0.1` | Bind address. Localhost only by default — this app has no auth. |
| `--port` | `5005` | Port. |
| `--output-dir` | the folder you last used, else `transcripts/` beside the launcher (or `$TERTIUS_OUTPUT_DIR`) | Transcripts, state file, and log all live here. Each folder keeps its own queue. |
| `--open-browser` | off | Open the UI once the server answers. What the .bat uses. |
| `--reuse-existing` | off | If a server is already on this port, show it and exit instead of starting a second one. |
| `--verbose` | off | Debug logging. |

## Using it

The window is two columns: the setup rail on the left, and the status band over
the file queue on the right.

1. **Source** — point it at a folder. **Browse** opens a normal Windows folder
   picker and queues everything it finds; typing or pasting a path and pressing
   Enter does the same. Individual files can be dropped anywhere on the window
   (or chosen with *drop files here*), which copies them into
   `<output-dir>/_uploads/`.
2. **Settings** — model size (default `large-v3-turbo`), device, language,
   precision, output formats, and where transcripts are written. The **i** button
   beside the model menu opens a comparison table; see
   [Which model?](#which-model).
3. **Run** — press **Begin**. The request returns immediately; the work happens
   on a background worker thread. The button reads *Begin again* once part of the
   queue is already done, and always says how many files are still pending.
4. Watch the queue. The file being transcribed expands to show how far through it
   is, plus the last few words it has written. Finished transcripts open from the
   **Output** column; a failed file shows its error inline with a **Retry** link,
   and the batch carries on regardless.

Every button and field has a tooltip — hover if something is unclear. The
**Dark / Light** toggle beside the wordmark switches theme; it follows your
system preference on first run and your choice is remembered in that browser.

Recognised input extensions: `.mp3 .wav .m4a .mp4 .flac .ogg .opus .webm .mkv
.mov .aac .wma .avi`.

### What choosing a folder actually does

It finds every recognised audio/video file in that folder and adds **all of them**
to the queue — then transcribes the lot when you press *Begin*. It is not a
sample or a first-N.

**Include subfolders** (ticked by default) controls how deep it looks:

- **Ticked** — every subfolder, however deeply nested.
- **Unticked** — only files sitting directly in the folder you chose.

Non-media files are ignored either way, and so is the `_uploads` folder. Scanning
never starts transcription, and re-scanning the same folder is safe: files already
in the queue keep their status, and anything already transcribed is skipped rather
than redone.

With subfolders included, the output directory mirrors the source layout — see
[Folder structure is mirrored](#folder-structure-is-mirrored).

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

If anything is pending, the status band says so — the headline reads *Ready to
carry on*, and the Run button becomes **Begin again** with the outstanding count.
The console logs the same thing at startup.

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

**Tertius checks this for you at startup.** If it finds a CUDA GPU whose runtime
libraries are missing, it says so in the console and shows a banner in the UI with
the exact command to fix it — you should not have to hit the error to find out.
The model comparison table also judges against the memory that will really be
used, so a GPU that cannot run is not counted in your favour.

> **If you see `Library cublas64_12.dll is not found or cannot be loaded`:** your
> NVIDIA *driver* is installed but the CUDA *runtime libraries* are not. The
> driver is what makes a GPU show up; the runtime is what actually does the
> maths. Install them into the venv:
>
> ```bash
> app\.venv\Scripts\pip install nvidia-cublas-cu12 nvidia-cudnn-cu12   # Windows
> app/.venv/bin/pip install nvidia-cublas-cu12 nvidia-cudnn-cu12       # Linux
> ```
>
> That is about 1.2 GB, and it is also available as the `gpu` extra:
> `pip install -e ".[gpu]"`. The banner in the UI shows whichever command suits
> the machine you are on. Or just set **Device** to `cpu` and accept the slower
> run.
>
> Installing the packages is not sufficient on its own — they land inside
> `site-packages`, which no platform's library loader searches. Tertius wires
> them up at startup, differently per platform because the mechanisms differ:
> on Windows it prepends the packages' `bin` folders to `PATH` (`add_dll_directory`
> alone is not enough — CTranslate2 uses a plain `LoadLibrary`, which ignores it),
> and on Linux it opens each `.so` in `lib` with `RTLD_GLOBAL`, because
> `LD_LIBRARY_PATH` is read once at exec and cannot be changed from inside a
> running process.

### On a Mac

There is no CUDA on Apple hardware and CTranslate2 has no Metal backend, so
**transcription on a Mac runs on the CPU.** Tertius says this plainly at startup
rather than showing a "runtime libraries missing" banner you could never act on.

Use `int8` and a smaller model there. **No Mac throughput number is given here
because none has been measured** — the ~22x-realtime figure quoted elsewhere is
from an RTX 2060 and does not transfer.


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
here by design — the state file is durable, so relaunch, press **Begin again**,
and the interrupted file is transcribed again from scratch while finished work is
kept.

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

### Each output directory has its own queue

This matters more than it sounds. Change the output folder and you are looking
at a **different queue**, with its own history of what has been done.

**Anything still queued follows you.** Change the output folder with files
waiting and press Begin, and those files are transcribed into the new folder,
keeping their mode and matched text — the queue you are looking at never
vanishes out from under you.

**Tertius remembers the folder you last used** and returns to it on the next
launch, recorded in `app/.tertius-session.json`. Without that, every restart
dropped you back at the default folder — where a batch you had finished
elsewhere reappeared as a pile of pending files, and starting it would quietly
re-transcribe work that was already complete.

Pass `--output-dir` to override for one run, or set `TERTIUS_OUTPUT_DIR`. An
explicit `--output-dir` always wins and becomes the new remembered folder.

### Clearing the queue

**Clear queue**, above the file list, empties the queue after a confirmation
that spells out what goes — including how many files were already transcribed.
It only forgets the list: transcripts already written stay on disk, and your
settings are kept. Uploaded copies belonging to those entries are deleted, since
nothing will refer to them again. It is refused while a job is running.

## Timestamping text you already have

If you already have the words — a script, a chapter, a prepared reading — Tertius
can put timestamps on *your* text instead of writing its own transcript. Your
wording is kept exactly as written; only timings are added.

Tick **Timestamp my own text**, then pick how finely to timestamp:

| Option | What you get |
| --- | --- |
| **Auto** | Paragraphs if your text has them, sentences otherwise. |
| **Per Paragraph** | One timestamp per blank-line-separated block. |
| **Per Sentence** | One timestamp per sentence — more precise, more lines. |

**Text files are matched by name.** `VolA01.mp3` pairs with `VolA01.txt` sitting
beside it (case-insensitive). Near misses are not matched: `VolA01.mp3` will never
grab `VolA02.txt`.

You can see at a glance whether that worked. Under each file name the queue says
either *Timestamping VolA01.txt* or *No matching text file*, and an unmatched row
offers **transcribe it**, **skip it**, and **choose a text file…** for when the
names don't match.

## Where Tertius looks for text files

For each audio file it looks for a `.txt` with the same name, in this order:

1. **Beside the audio file** — the folder that audio actually lives in.
2. **The Text folder**, if you set one — searched recursively, so your texts can
   sit in their own tree.

The queue tells you where it looked: hover *No matching text file*, and the panel
above the queue lists the folders searched.

**Uploaded files are the catch.** A browser never tells the server where a file
came from, so dropping or choosing files copies the audio into
`<output-dir>/_uploads/`
and that becomes "beside the audio". Your original folder is unknown to Tertius.
So if you upload `V1_01.mp3` and its `V1_01.txt` is sitting next to the original,
it will not be found. Three ways round it:

- Point **Source** at the folder instead of uploading — then the audio stays
  where it is and the text beside it is found.
- Upload the `.txt` together with the audio; they land in `_uploads` side by side
  and pair by name.
- Set the **Text folder** to wherever your text files live.

Ticking or unticking **Timestamp my own text** re-evaluates whatever is already
queued, so the order you do things in doesn't matter.

**Text that isn't spoken is left alone.** Title pages, page numbers, copyright
lines and footnotes find no match in the audio, so they are kept exactly as
written with no timestamp rather than being forced onto a time. In a real run, a
reading with four front-matter blocks and a footnote produced 15 timed paragraphs
and 5 untimed ones, all text intact.

**If there's no matching text file**, Tertius says so rather than guessing. The
queue shows those files as **no text found**, and a banner lists them. For each
one you can:

- add the `.txt` beside the audio and press **Check again**, or
- set it to **transcribe** normally, or
- **skip** it entirely.

There are bulk buttons for the last two. A job will not start while any file is
still undecided — the whole point of asking is that it does not quietly do the
opposite of what you wanted.

Output goes to the normal `.txt` / `.srt` files: the `.txt` is your text with
`[HH:MM:SS.mmm]` in front of each timed chunk, and the `.srt` is subtitles
carrying your wording. If an output would land on the very text file you supplied,
it is written as `<name>.timestamped.txt` instead so your source can't be
overwritten.

Alignment works by transcribing the audio for word-level timings and matching your
text against it, so it tolerates the model mishearing a word here and there — it
only needs enough anchor words to place each chunk. A timestamp that would run
backwards (from a repeated phrase matching the wrong place) is dropped rather than
emitted wrong.

### Folder structure is mirrored

Scanning a folder reproduces its layout under the output directory:

```
D:\Audio\intro.mp3                    ->  transcripts\intro.txt
D:\Audio\Volume A\talk.mp3            ->  transcripts\Volume A\talk.txt
D:\Audio\Volume A\part 2\talk.mp3     ->  transcripts\Volume A\part 2\talk.txt
D:\Audio\Volume B\talk.mp3            ->  transcripts\Volume B\talk.txt
```

Each file remembers where it sat inside the folder you scanned, so same-named
files in different folders no longer overwrite each other — the three `talk.mp3`
files above produce three separate transcripts.

Files added any other way (uploads, or files outside the scanned folder) go
straight into the output directory with no subfolder, as before.

## HTTP API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/status` | Full job + queue state (what the UI polls). |
| `POST` | `/api/scan` | `{directory, recursive}` → media files found. |
| `POST` | `/api/queue` | `{files: [...], base_dir?}` → add to queue without starting. `base_dir` is the scanned folder, and makes the output mirror its structure. |
| `POST` | `/api/upload` | multipart `files` → save to `_uploads/` and queue. |
| `POST` | `/api/job/start` | `{files?, output_dir?, options?, retry_failed?}` → returns at once. |
| `POST` | `/api/job/resume` | Work the pending set from an interrupted run. |
| `POST` | `/api/job/cancel` | Stop after the current file. |
| `POST` | `/api/job/retry-failed` | Move `failed` back to `pending`. |
| `POST` | `/api/queue/remove` | `{path}` → drop a file from the queue (not while running). |
| `POST` | `/api/queue/mode` | `{path, mode, reference_text?}` → align / transcribe / skip one file. |
| `POST` | `/api/queue/rematch-text` | Look again for `.txt` files added after queueing. |
| `POST` | `/api/queue/decide-all` | `{mode}` → answer every outstanding "no text file" at once. |
| `GET` | `/api/transcript?name=…&download=1` | Fetch a transcript from the output dir. |
| `GET` | `/api/system?device=…&compute_type=…` | Machine capabilities + a verdict per model. |
| `POST` | `/api/browse-folder` | Open the OS folder picker on this machine, return the path. |

## Tests

```bash
cd app && pytest
```

269 tests. The whisper model is mocked throughout — the suite downloads nothing
and decodes no audio, which is also what makes it safe to run in CI. Coverage is
aimed at what is easy to get wrong: state tracking and resume semantics, the
job's independence from the HTTP request that started it, download-progress
aggregation, machine-suitability verdicts, and the per-platform branches.

CI runs the suite on ubuntu, macOS and Windows (`.github/workflows/tests.yml`).
That is the only cross-platform evidence there is, and it is worth being precise
about its limits: it proves the logic runs everywhere, **not** that audio decodes
on a Mac, that CUDA works on Linux, or that the folder picker opens.

## Layout

```
Start Tertius.bat    Windows launcher — double-click
Tertius.app/         macOS launcher — double-click (script inside, no compiler)
start-tertius.sh     Linux launcher
README.md
transcripts/         output, the resume state file, and the log
app/
  src/tertius/
    launcher.py      setup + takeover logic shared by all three launchers
    settings.py      what Tertius remembers between sessions
    config.py        options, validation, media-file scanning
    state.py         StateStore — atomic JSON state, status transitions
    transcribe.py    faster-whisper wrapper, model download + progress, txt/srt
    jobs.py          JobManager — the background worker, its phase and status
    system.py        RAM/GPU detection, model catalogue, per-machine verdicts
    folder_picker.py native folder dialog, run as its own process
    app.py           Flask routes (they queue and report; they never transcribe)
    __main__.py      CLI entry point, logging, browser opening
  tests/             state, jobs, HTTP, downloads, system advice, platforms
  assets/            the T mark as .svg/.png/.ico/.icns, plus its generator
  design/            UI design handoff and the original build spec
  .venv/             created on first run
```

The launchers sit at the top because they are the only thing most people need.
Everything the app is made of lives under `app/`.

## Not included

No live microphone transcription (file/batch only) and no auth or multi-user
support — this is a single-user local tool. Don't bind it to `0.0.0.0` on an
untrusted network: the scan and queue endpoints will read any path the server
process can read.
