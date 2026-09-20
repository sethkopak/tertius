# Tertius

Offline batch transcription of audio/video files using
[faster-whisper](https://github.com/SYSTRAN/faster-whisper), with a small Flask UI
for a resumable queue. It can also **translate** what it transcribes — or a `.txt`
you already have — into any of a hundred languages, still without leaving the
machine.

Runs entirely on your machine: no API calls, no cloud services, no telemetry. Its
only network access is fetching models the first time you use them — Whisper from
Hugging Face (see [Models](#models)), and, if you translate, a translation model
plus the libraries needed to convert it (see [Translating](#translating)). Once
they are on disk you can run air-gapped.

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

Tertius needs **Python 3.11 or newer** — that is the floor CI actually exercises
(3.11 and 3.13 on all three platforms, plus 3.14 on Windows). Older versions are
not claimed because none has ever been run.

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
   [Which model?](#which-model). **Translate the transcript** adds a second
   language alongside the original, with its own model menu and **i** button;
   see [Translating](#translating).
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

Output formats: `.txt`, `.srt`, `.json` — pick any combination under **Write**.

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

With translation on, the translated files land beside them, tagged with the
target language. Nothing is replaced:

```
lecture1.mp3  ->  lecture1.txt      lecture1.es.txt
                  lecture1.srt      lecture1.es.srt
```

`.txt` is **one sentence per line**. Whisper's own segments are cut for timing
rather than for reading — they run on, break mid-sentence, and sometimes hold
three sentences at once — so the text is rejoined and re-split on sentence ends.
No word is changed, only where the lines fall.

`.srt` is standard numbered subtitles with `HH:MM:SS,mmm` timings, and is *not*
reflowed: its lines are timing units and have to stay matched to their cues.

`.json` is the transcript as data — every segment with `start`, `end` and
`text`, plus the detected language and the audio duration. Times are seconds as
floats, which is what anything downstream wants; the `.srt` already covers the
clock-format case. It is off by default; tick `.json` under **Write**.

```json
{
  "version": 1,
  "kind": "transcription",
  "source": "talk.wav",
  "language": "en",
  "duration": 9.423,
  "segments": [
    { "id": 0, "start": 0.0, "end": 2.16, "text": "The first study examines the plan." }
  ]
}
```

Timestamping supplied text writes a different shape, because it has different
things to say: your chunks in order, each with `timed: true|false`. Text that is
never spoken keeps its place with a null start — the `.srt` can only carry cues
that have times, so it is the `.json` that tells you the whole document.

```json
{
  "version": 1,
  "kind": "alignment",
  "granularity": "sentence",
  "summary": { "granularity": "sentence", "chunks": 2, "timed": 1, "unmatched": 1 },
  "chunks": [
    { "id": 0, "start": null, "end": null, "timed": false, "text": "A title page" }
  ]
}
```

Both files open with the same two keys, so a reader can tell what it has before
it reads any of it. `kind` says which of the two shapes this is — they both
arrive as `.json` beside the audio and the extension cannot distinguish them.
`version` is bumped whenever a key is renamed, removed, or changes meaning; a
newly *added* key does not bump it, so code keyed on the existing ones keeps
working. If you build anything on this output, check `version` and refuse a
number you do not know rather than misreading the file.

Timestamped supplied text is untouched by this too — that feature keeps your
wording *and* your layout exactly as you wrote it.

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

## Translating

Tertius can write the transcript in another language as well as the original.
Both files are produced: `lecture1.txt` stays exactly as transcribed, and the
translation lands beside it as `lecture1.es.txt`. A bad translation costs you
nothing you already had.

Tick **Translate the transcript**, choose a translator and a target language,
and run as normal.

### Whisper cannot do this on its own

Whisper has a `translate` task, and it only ever produces **English** — any
language in, English out. That is not what "translate this into Spanish" means,
so translation here is a second model, run after transcription, on the same
CTranslate2 runtime faster-whisper already uses. Still offline; still nothing
leaving the machine once the model is on disk.

### The models

| Model | Download | On disk | Languages | Licence |
| --- | --- | --- | --- | --- |
| `m2m100-418M` (default) | 1.8 GB | 477 MB | 100 | MIT |
| `m2m100-1.2B` | 4.6 GB | 1.2 GB | 100 | MIT |
| `madlad400-3B` | 11.0 GB | — | 400+ | Apache-2.0 |

The **i** button beside the translator menu opens the same comparison table,
with measured on-disk sizes for whichever you have already prepared.

Weights are downloaded from the publisher — `facebook/…`, `google/…` — and
converted to CTranslate2 format **here, on your machine**. Ready-made
conversions of all of these exist on Hugging Face and would have been simpler
to use, but they are individual accounts with no signature and nothing tying
their `model.bin` to the weights it claims to be. Converting from the original
costs one `torch` install and nothing afterwards.

**NLLB-200 is not offered.** It is better than any of these at its size and it
is CC-BY-NC-4.0 — non-commercial. Tertius is MIT, and a default feature that
quietly forbids commercial use to everyone downstream is worse than a slightly
weaker model. Every model above may be used commercially.

### Download and prepare

The target-language menu is read from the converted model's own vocabulary, so
it can never offer a code the model would reject — which means there is nothing
to choose from until the model exists. Press **Download and prepare** once per
model. It:

1. installs `torch`, `transformers` and `sentencepiece` if they are missing
   (about 150 MB, from the CPU-only PyTorch index — conversion never runs the
   model, so a CUDA build would buy nothing);
2. downloads the publisher's weights;
3. converts them to int8.

It refuses to install anything outside a virtual environment, and nothing else
in Tertius ever installs anything — a transcription-only run never touches pip.
You can also do it yourself with `pip install -e app[translate]`.

### Whole sentences, or segments

**Translate the .txt as whole sentences** is on by default, and is worth
understanding.

Whisper cuts segments for timing, not for meaning. Measured on a 38-minute
talk: 71% of segments begin mid-sentence, 78% end without a full stop, and 54%
are fragments at both ends. Handing those to a translator one at a time gives
it "the doubt and gloom intensified by" with no subject and no end.

So the `.txt` is translated as rejoined sentences. The `.srt` cannot be — its
timings belong to segments, and only a segment has them — so it is always
translated segment by segment, and **every cue keeps the timing that was
actually measured**.

The cost is a second pass over the file. On that same talk: 12s for the segment
pass, 221s for the sentence pass. Turning the setting off is four times faster
and gives a `.txt` that reads badly (116 run-on lines where the English had
206 sentences). The `.srt` is byte-identical either way, and a run that writes
no `.txt` never pays for the second pass at all.

### Translating text with no audio

Tick **Translate text files, not audio** and Tertius scans for `.txt` instead
of media. Those files go straight to the translator — Whisper is never loaded —
and the paragraph and sentence shape of the original is preserved. No `.srt` is
written however the format chips are set: there are no timings, and invented
cues would be worse than none.

This is a separate scan rather than an extra extension on the media list,
because the same `.txt` means two different things depending on why it was
picked up. Found beside an audio file it is reference text to be *timestamped*
(see [Timestamping text you already have](#timestamping-text-you-already-have));
scanned as a source it is text to be *translated*.

### What to expect

`m2m100-418M` is the default because it is a third of the disk and half the
wait, and it is genuinely the smallest one worth using. It is also small enough
to show. On real material it rendered "gloom" as *glume* — jokes — in every
attempt, fragments and whole sentences alike, and invented non-words for
"doubt". `m2m100-1.2B` fixed both, along with noun gender and register. If the
output is not good enough, that is the first thing to change.

Honest limits, as of the last time this was written:

- Only the two M2M-100 models have been run. `madlad400-3B` is a different
  architecture entirely and **has never been tried**.
- Translation has only ever run on the **CPU**. Whether a model fits on a GPU
  beside Whisper is unknown, which is why the comparison table has no verdict
  column.

## Reading text aloud

Three stages, and you pick which of them run:

```
audio → transcribe → [translate] → [read aloud]
 text →              [translate] → [read aloud]
```

So an English talk becomes Spanish audio in one job — **in the voice of whoever
was talking**, because Tertius samples the speaker out of the recording it is
already transcribing.

Pick the **Source** (audio or text), then tick the stages you want. Read aloud
appears once there is something for it to read: a translation to speak, or a
text file that is already in a language.

Whisper is never loaded for a text source — there is nothing to decode.

> **Before you point this at anyone's voice but your own**, read
> [Voice cloning: your responsibility, not the tool's](SECURITY.md#voice-cloning-your-responsibility-not-the-tools).
> It is short, and it is the part of this program that can hurt somebody.

### What it writes

For `0103.mp3` translated into Spanish and read aloud:

| File | What it is |
| --- | --- |
| `0103.txt` / `0103.srt` | the transcript, timed against the recording |
| `0103.es.txt` / `0103.es.srt` | the translation, timed against the same recording |
| `0103.es.spoken.wav` | the Spanish audio |
| `0103.es.spoken.srt` | cues timed against **that** audio |

The `.spoken` is load-bearing. Without it the reading's `.srt` is written to
the name the translation's `.srt` already has and silently replaces it — two
different things that both honestly answer to "the Spanish subtitles". One is
timed to real speech, the other to generated speech, and losing the first is
losing the only cues that match anything anybody said.

### The language is derived, not chosen

**Chatterbox does not translate.** Its language setting says what the text it
is being handed *is in*; told `zh` over English words it reads the English.
That cost a real job once — 46 seconds of GPU, a "completed" status, and
English audio for someone who had asked for Chinese.

So it is not a free choice any more:

- **Translating?** The speaking language is the target. Necessarily — the
  words about to be spoken are the ones the translator just produced.
- **Transcribing without translating?** Whatever the transcript is in.
- **A text file with no translation?** The one case where nothing else knows,
  and the only case where Tertius asks.

With Read aloud on, the **Into** menu narrows to the languages the voice model
can actually say — 23 of them — because translating a whole queue into Romanian
and only then finding nothing can pronounce it is the failure these menus exist
to prevent. The note under the menu says so, or the missing Romanian looks like
a bug.

### The voice

Leave **Voice clip** empty and Tertius cuts a reference out of the recording
itself: the densest ten seconds of actual speech in it, found from the segment
timings the transcription already produced.

That is not a convenience. Chatterbox conditions on roughly the first ten
seconds of whatever reference it is handed, so handing it a whole talk hands it
the talk's *opening* ten seconds — an introduction, a hymn, a pause. Measured
on one real devotional file: **49% of its first ten seconds was near-silence**,
and that was the half the model was cloning from. Tertius says so in the log
when the best window it can find is still mostly silence.

Set the field to override with a clip of your own; about ten seconds of clean
speech is what the publisher asks for. For a text file with no audio behind it,
empty means the model's own default voice.

### The models

Three, all from Resemble AI, all **MIT**, and none of them gated on Hugging
Face — you do not need an account or an access token for any of them.

| Model | Download | Languages | `[laugh]` tags | Notes |
| --- | --- | --- | --- | --- |
| `chatterbox-multilingual` | ~3.2 GB | 23 | no | The default. The only one that speaks anything but English. |
| `chatterbox-turbo` | ~4.0 GB | English | yes | Faster, and the only one that can be told to laugh. |
| `chatterbox-nano` | ~3.0 GB | English | yes | Smallest. The publisher reports 3× realtime on 8 CPU cores. |

The 23 are `ar da de el en es fi fr he hi it ja ko ms nl no pl pt ru sv sw tr
zh`, read out of the package itself rather than a table kept here, so the menu
can never offer one the model would reject.

Better models exist and are deliberately absent, the same way NLLB-200 is
absent from [Translating](#translating). **IndexTTS-2** is the only open model
with real duration control, which is exactly what dubbing wants, and it ships
under the bilibili Model Use License Agreement rather than a permissive
licence. **XTTS-v2** is CPML and forbids commercial use outright. Tertius is
MIT and gets handed to strangers; a default that quietly removes their rights
is not a default.

One real difference from the translation models: **these are loaded as the
publisher shipped them, not converted here.** CTranslate2 cannot run them —
they are a torch stack end to end — so the argument that protects the
translation path (convert the publisher's own weights, never trust a stranger's
upload) does not apply. What stands in for it is that the repositories belong
to Resemble AI, the organisation that wrote the model.

### Voice cloning

Leave **Voice clip** empty and you get the model's own default voice. Point it
at a recording — about ten seconds of clean speech is what the publisher asks
for — and it reads in that voice instead.

**Everything expressive comes from the clip.** A voice sampled from someone
reading gently reads gently; one sampled from someone reading briskly reads
briskly. This matters more than it sounds, and the next section is why.

### Style tags

Write a tag on its own in square brackets and everything after it is delivered
that way, until the next tag:

```
[solemn]
In the beginning was the Word, and the Word was with God.

[warm] And the light shineth in darkness.

[emphatic] And the darkness comprehended it not.
```

The eight styles are `neutral`, `calm`, `gentle`, `solemn`, `warm`, `bright`,
`emphatic`, `urgent`. A tag holds across paragraph breaks and is only ended by
another tag; the **Default style** menu sets what applies before the first one.

**These are delivery, not emotion, and the distinction is not pedantry.**
Chatterbox has no emotion conditioning — there is no input to it that means
"sad". What it exposes is how hard a line is pushed and how loosely it holds to
the reference clip. So the tags are named for what they actually do. Emotion
words are accepted as aliases (`[angry]` → `urgent`, `[excited]` → `bright`,
`[sad]` → `solemn`, and a few more) and Tertius tells you it did that, because
somebody who writes `[angry]` and gets firm-but-calm speech back would fairly
conclude the feature was broken rather than that the tag was a lie. If you want
anger, sample a clip of someone angry.

Three kinds of bracket, treated differently:

- **A style tag** is Tertius's. It changes delivery and is removed from what
  gets spoken.
- **`[laugh]`, `[chuckle]`, `[cough]`** are the model's own, and are passed
  through untouched on `chatterbox-turbo` and `chatterbox-nano`. The
  multilingual model does not understand them, so there they are removed —
  left in, it would read out the word "laugh".
- **Anything else in brackets stays exactly as you wrote it.** Transcripts are
  full of `[inaudible]` and `[crosstalk]`, and a tag vocabulary that ate them
  would corrupt the very files this feature exists to read. Tertius reports
  them instead, once each, so a misspelt `[emphatc]` is visible rather than
  silently read out.

Scanning a folder pops open **What your tags did** — the text split into the
calls that would be made, with the delivery each would get. Nothing is
generated to produce it, so it is instant, and it is the cheapest moment to
discover a typo.

### What it writes

A `.wav` always, 16-bit mono at the model's own sample rate, streamed to disk
as it is generated rather than held in memory — a forty-minute reading is a
hundred-odd megabytes of samples.

An `.srt` and a `.json` if those format chips are set. **These timings are
measured, not estimated**: each chunk's audio is timed as it is written, so the
subtitles describe the recording that came out beside them, exactly. It is the
one place in this whole program where a cue cannot have drifted from its audio.

No `.txt` is written. The text is the input; a near-copy of it in the output
folder would be one more file to tell apart from the one you wrote.

The `.json` has `"kind": "speech"` and records the model, the voice clip, the
styles used, and every warning — so nothing downstream can mistake a reading
for a transcript of something somebody actually said.

### The torch problem, and it is a real one

Speaking needs `torch` as its **runtime**, and on a GPU it is perhaps twenty
times faster than on a CPU. Translating needs `torch` too, but only to *convert*
a model once, so it deliberately installs the **CPU-only** build — a 126 MB
download instead of 2.5 GB.

One virtual environment holds one torch, so whichever feature installs first
decides. **If you translated before you ever read anything aloud, you have the
CPU build in front of a perfectly good GPU.** Tertius detects exactly this and
says so, in the voice-model panel and again when a model is prepared, with the
command that fixes it:

```bash
# from the repository root, and note it is the venv's own Python - a bare
# `pip install` hits whichever Python is on PATH and does nothing for Tertius
app/.venv/Scripts/python.exe -m pip install --force-reinstall \
  --index-url https://download.pytorch.org/whl/cu126 torch
```

`--force-reinstall` is not optional. pip counts `torch` as already satisfied by
`2.14.0+cpu`, because the part after the `+` is a local version identifier and
does not make it a different version. Leave the flag off and pip prints
*Requirement already satisfied*, changes nothing, and exits 0 — so it looks
like it worked.

The index is `cu126` and not something newer on purpose: it carries the same
torch version as the CPU build, so nothing else in the environment shifts, and
it still builds for every GPU architecture back to Maxwell. Check that the
index you use actually has a wheel for your Python — one that does not says
`No matching distribution found for torch`, which reads as though torch itself
were missing.

### It has to fit on the card

Three models, measured on a 6 GB RTX 2060:

| model | VRAM |
| --- | --- |
| whisper `large-v3-turbo` | 2.23 GB |
| `m2m100-418M` | 0.27 GB |
| `chatterbox-multilingual` | **3.22 GB** |

That is 5.72 GB of models, and a browser can be holding a gigabyte of the card
already. Tertius therefore takes the transcriber and the translator off the GPU
before a reading starts and reloads them for the next file — nothing
transcribes while it reads aloud, so holding all three was never necessary. It
costs a model load per file and buys a feature that otherwise cannot run at all
on a small card.

If it still runs out, the message says so and what to do: close whatever else
is using the GPU, choose a smaller Whisper model, or set **Device** to `cpu`
for a slower run that always fits.

The card is also released when a job ends, including when one fails partway.
Unloading a model only drops the reference; torch keeps the memory, so without
this an idle server sat on several gigabytes until it was restarted — measured
at 4,735 MiB fifteen hours after a job finished, which then made the *next* job
fail for want of room.

### Numbers are spelled out before they are spoken

The voice model can only say an Arabic digit in English. In Russian it drops
the number — `Манна на 1 января` came out as `манна на января` — and in Spanish
it says a different one: `Salmo 66, versos 8 y 9` became `Salmo 15 tibesos o
39`.

So digits become words in the target language immediately before the model sees
them, via [num2words](https://github.com/savoirfairelinux/num2words) (LGPL-2.1,
which binds the library rather than what imports it). It covers 18 of the 23
languages; `el`, `hi`, `ms`, `sw` and `zh` keep their digits, which is no worse
than before, and Chinese handles them itself anyway.

**The subtitles keep the digits.** Only the model gets the words, so an `.srt`
still reads `Псалом 66` rather than `Псалом шестьдесят шесть`.

One known gap: an ordinal that was lost in translation stays lost. `January
1st` becomes `1 января` becomes "один января", where Russian wants "первое".
Wrong but intelligible, against a number that used to vanish entirely.

### Languages that do not end sentences with a full stop

Chinese, Japanese, Korean, Greek, Arabic and Hindi are split on their own
terminators, and a character that carries a whole word counts for more of the
chunk budget than a letter does — 300 Han characters is about eighty seconds
read aloud where 300 Latin characters is about twenty.

Both had to be fixed before Chinese worked at all. The splitter wanted an ASCII
terminator followed by an ASCII capital, so a Chinese translation arrived as a
single "sentence", became one oversized chunk, and came back truncated. It was
invisible in the `.txt` and only showed up when something read it aloud.

### Several languages at once

**Into** takes as many languages as you like — the job translates into each of
them in one pass over the queue, which is the expensive part. Files are already
named by language (`talk.es.txt`, `talk.ru.txt`), so they sit beside each other
with nothing to reconcile.

**Speak** is a second, separate list. The translator knows a hundred languages
and the voice model twenty-three, and wanting Romanian *text* is not the same
as being unable to have it — so the translation list is never narrowed. The two
are kept in step instead:

- ticking a language under **Into** selects it under **Speak** if it can be spoken
- unticking it under **Speak** leaves the text translation alone
- ticking one under **Speak** adds it to **Into**, since the text has to exist first
- unticking it under **Into** removes it from **Speak**

Measured on a real two-language run: **translating into another language is
nearly free, and speaking it is not.** Adding Russian to a file already being
translated into Spanish cost 17 seconds, because the translator is loaded and
the sentences are already split. Each *reading*, though, is about half realtime
on its own — 180 of the 270 seconds that file took. Ticking five languages buys
five readings rather than five translations.

### Scripture references keep their numbers

A translation model destroys verse citations. Measured across twelve real lines
of this corpus, unprotected, every numeric run survived in only 12 of 16 cases
into Russian and 10 of 16 into Chinese — whole citations vanish, and Chinese
turned `1 Peter 5:5` into `彼得五:5` and replaced a reference to Chronicles with
《古兰经》, "the Quran".

So the **numbers** are lifted out before the model sees them and put back
afterwards, while the words around them translate normally:

    Psalm 66, verses 8 and 9  →  Псалом 66, стихи 8 и 9

Only the numbers, not the whole reference: the book name is not fragile and a
reader in the target language wants it translated. With this on, every numeric
run survived in all three languages tested. A placeholder the model drops has
its reference appended rather than lost, so a citation may move to the end of
its sentence — which beats being gone, and both beat the model's rendering.

Recognition needs a known book name, so `Section 2`, `Volume 6 chapter 2` and
`Figure 3` are left alone. Anything it does not recognise is simply translated
as before.

### What has actually been heard

A Russian speaker has listened to a Russian reading and says it sounds good.
That is the only claim here about how any of this *sounds* that comes from a
person rather than from a waveform.

Chinese has been run and sounds fine to someone who does not speak Chinese,
which is a weaker claim and is kept separate on purpose: a reading can be
fluent and wrong, and duration, pitch and a back-transcription would all report
it as fine. The other twenty-one languages have nobody behind them.

### Honest limits

As of the last time this was written:

- **Not one line of this has met a real model.** Everything below is what the
  code does against a fake; no audio has been generated, no voice has been
  cloned, and nobody has listened to any of it.
- **The style numbers are a considered starting point and nothing more.** They
  were chosen by reading the publisher's guidance, not by listening.
- Whether a voice model fits on a GPU beside Whisper is unknown, which is why
  the comparison table has no verdict column — the same reason the translation
  one has none.
- The gaps between chunks (0.28 s, and 0.7 s at a paragraph) are a guess at
  what reads as a breath rather than an edit.

## HTTP API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/status` | Full job + queue state (what the UI polls). |
| `POST` | `/api/scan` | `{directory, recursive, kind?}` → source files found. `kind` is `media` (default), `text` or `speech`. |
| `POST` | `/api/queue` | `{files: [...], base_dir?, kind?}` → add to queue without starting. `base_dir` is the scanned folder, and makes the output mirror its structure. `kind: "speech"` marks queued `.txt` to be read aloud rather than translated. |
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
| `GET` | `/api/translation/models` | The translation models: download size, whether prepared, measured size on disk, languages, licence. |
| `GET` | `/api/translation/languages?model=…` | What that model translates into, read from its converted vocabulary. Empty until it is prepared. |
| `POST` | `/api/translation/prepare` | `{model}` → install what is needed, download and convert. Returns at once; watch `/api/status`. |
| `GET` | `/api/speech/models` | The voice models: download size, whether already on disk, languages, licence, whether they act on `[laugh]`. |
| `GET` | `/api/speech/languages?model=…` | What that model can read, plus the style vocabulary and its aliases. Answerable before anything is downloaded. |
| `POST` | `/api/speech/prepare` | `{model}` → install what is needed and download the weights. Returns at once; watch `/api/status`. |
| `POST` | `/api/speech/preview` | `{text\|path, model?, style?}` → the chunks and delivery a reading would use, and any warnings. Generates no audio. |
| `POST` | `/api/browse-folder` | Open the OS folder picker on this machine, return the path. |

## Tests

```bash
cd app && pytest
```

382 tests. The whisper model is mocked throughout, and so is the translator —
the suite downloads nothing, decodes no audio and converts no checkpoints, which
is also what makes it safe to run in CI. Coverage is aimed at what is easy to
get wrong: state tracking and resume semantics, the job's independence from the
HTTP request that started it, download-progress aggregation,
machine-suitability verdicts, the per-platform branches, and — for translation —
the exact tokens each model family needs, since getting those wrong produces a
confident translation into the wrong language rather than an error.

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
LICENSE              MIT
THIRD-PARTY-NOTICES.md   bundled fonts (OFL 1.1) and dependency licences
SECURITY.md          how to report something exploitable
transcripts/         output, the resume state file, and the log
app/
  src/tertius/
    launcher.py      setup + takeover logic shared by all three launchers
    settings.py      what Tertius remembers between sessions
    config.py        options, validation, media-file scanning
    state.py         StateStore — atomic JSON state, status transitions
    transcribe.py    faster-whisper wrapper, model download + progress, txt/srt
    translate.py     CTranslate2 translation: convert, load, the two adapters
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
support — this is a single-user local tool. Reading text aloud does **not**
remove the watermark Chatterbox applies to everything it generates, and no
option to do so will be added. Whisper's English-only `translate`
task is not exposed either; [Translating](#translating) covers that case with a
model that can also do the other ninety-nine languages. Don't bind it to `0.0.0.0` on an
untrusted network: the scan and queue endpoints will read any path the server
process can read.

Found something exploitable? [SECURITY.md](SECURITY.md) says where to send it
and what counts.

## License

MIT — see [LICENSE](LICENSE).

The interface fonts bundled under `app/src/tertius/static/fonts/` are not mine:
IBM Plex and Cardo, both under the SIL Open Font License 1.1, self-hosted so the
app never fetches them over the network. Their notices are in
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md), along with the licences of the
runtime dependencies.

Whisper models are downloaded from Hugging Face on first use and are not part of
this repository; each carries its own terms from its publisher. The same goes
for the translation and voice models — every one of them was chosen to be
permissively licensed (MIT or Apache-2.0) so that nothing Tertius does by
default takes a right away from whoever it is handed to.

The MIT licence gives you this software without warranty and without indemnity.
It does not give you permission to break the law with it: if you clone a voice,
[SECURITY.md](SECURITY.md#voice-cloning-your-responsibility-not-the-tools) says
whose responsibility that is, and it is not this project's.
