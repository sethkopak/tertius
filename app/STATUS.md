# Tertius — status

Last updated: 2026-08-03

## Where it stands

Working, and in real use. Built from `design/original-spec.md`, plus everything
requested since: the launcher, folder picker, model download progress, model
comparison + machine check, tooltips, light/dark theme, mirrored output folders,
timestamping of supplied text, the designed UI, and macOS/Linux support.

**298 tests, all passing**, on Windows locally and on ubuntu/macOS/Windows in
CI. Whisper is mocked throughout — the suite downloads nothing and decodes no
audio, which is what makes it safe to run on a hosted runner.

Run it: double-click `Start Tertius.bat` (Windows), `Tertius.app` (macOS), or
run `./start-tertius.sh` (Linux).

Repo: `github.com/sethkopak/tertius` (private), branch `main`.

**Windows is the only platform anyone has actually run this on.** See
[Not verified](#not-verified--read-this-before-trusting-it).

## What it does now

- **Transcribe** a queue of audio/video files, resumably, on the GPU.
- **Timestamp text you already have** instead of writing a fresh transcript.
  A `.txt` is paired with each audio file by name; your wording is kept exactly
  and only timings are added, at Auto / Per Paragraph / Per Sentence granularity.
  Text that is never spoken (title pages, page numbers, footnotes) is kept
  verbatim without a timestamp. Confirmed working on real material 2026-08-02.
- **Output mirrors the source folders**, so same-named files in different folders
  no longer overwrite each other.
- Tells you what it is doing: model download progress, which device it is really
  using, where it looked for text files, and why a GPU is unusable.
- **Shows the work as it happens.** The file being transcribed reports how far
  through it is and the last words it wrote; the status band carries the whole
  job in one line, weighted by audio length rather than file count.
- **A designed interface** (2026-08-03), rebuilt from the Tertius UI handoff:
  two columns, Cardo and IBM Plex self-hosted so nothing is fetched at runtime,
  full dark and light parchment palettes, no shadows anywhere.
- **Language is a menu now**, built from Whisper's own list of codes so it can
  never offer one the model would reject, with names resolved by the browser's
  `Intl.DisplayNames` rather than a hand-written table that could go stale.
- **Runs on macOS and Linux** (2026-08-03), from source, with a double-clickable
  launcher on each. On a Mac that means the CPU: there is no CUDA on Apple
  hardware and CTranslate2 has no Metal backend, and Tertius says so plainly
  rather than offering a fix that could never apply.
- **Comes back to the folder you were working in.** Each output directory keeps
  its own queue, so returning to the wrong one makes finished work look
  unfinished. The last-used folder is remembered in `app/.tertius-session.json`.
- **Clear queue**, with a confirmation that says how many files go and how many
  of them were already transcribed. Housekeeping to match: uploaded copies no
  longer needed are removed at startup, and with the queue when it is cleared.
- **Three output formats.** `.txt` one sentence per line — Whisper's segments
  are cut for timing, not for reading, so they are rejoined and re-split on
  sentence ends without a word changing. `.srt` unchanged, its lines being
  timing units. `.json` the transcript as data, off by default, stamped with a
  `version` and a `kind` so a reader can tell which shape it has.
- **The queue follows you** when the output folder changes. Each folder keeps
  its own history, but files you have lined up are what you are pointing at.

## Verified by actually running it

Not just by tests:

- **Resume across a hard kill.** Killed the server with `Stop-Process -Force`
  while a file was mid-transcription, restarted: the interrupted file was reset
  to pending and re-transcribed, the finished one skipped, the untouched one ran.
- **Real transcription with the real model.** `tiny` on CPU against a generated
  WAV: downloaded, decoded, transcribed, wrote output, completed.
- **Folder picker.** Dialog opens (window class `#32770`, correct title), cancel
  returns `cancelled: true`, and the server keeps answering requests while it is
  open.
- **Download progress against the real Hugging Face stack.** 0% → 10.5% → 24.1%
  → 99.9% for an uncached model.
- **Double-launch.** A second run of the launcher never starts a second server:
  it takes over an idle one and steps aside for a busy one. All three branches
  run and checked (2026-08-03).
- **UI in the browser.** Scan → queue → start → live polling → completed with
  per-file download links. Model table, theme toggle, and download panel all
  checked visually. No console errors.
- **The designed UI, against real speech** (2026-08-03). Windows SAPI generated
  the test audio, so the excerpt and waveform were driven by real transcription,
  not a fixture: idle, running, stopped-with-resume, finished, and
  finished-with-one-failure all seen in both themes. Also checked against the
  real `transcripts/` state file, where a run predating word counts simply omits
  the Words stat rather than showing a zero.
- **Drag-and-drop onto the window** (2026-08-03). Reported working by Seth after
  an actual drag, not through the file picker. Windows only, like everything
  else in this list.

## 2026-08-02 — GPU incident, fixed

First real use (17 files, ~38 min each) hit
`RuntimeError: Library cublas64_12.dll is not found or cannot be loaded`, then
**hung**. Root cause: the NVIDIA driver is installed but the CUDA runtime
libraries are not, so `get_cuda_device_count()` reported 1 device and `auto`
chose the GPU. Confirmed on this machine — no `cublas64_12.dll` anywhere.

Three separate defects, all fixed and verified against the real failure:

1. **`auto` trusted a device count instead of proving the GPU works.** Loading a
   model on CUDA succeeds even with no runtime libraries; only the first encode
   fails. Now a one-second dummy transcription runs at job start. `auto` falls
   back to the CPU and says why; explicit `cuda` fails with the fix instructions.
2. **A failed CUDA call poisons the process.** Reproduced directly: after one
   CUDA failure, the *next* CUDA attempt deadlocked for 10 minutes rather than
   raising. That is what wedged file 2 in the original incident. The first
   failure is now remembered process-wide and the GPU is never retried.
3. **Cancel lied.** It is checked between files, so a wedged native call meant
   "CANCELLING" forever with no explanation. It now reports how long it has been
   waiting and, after 20s, offers **Force stop** (kills the server; safe because
   state is durable and Resume redoes the interrupted file).

Also: three consecutive identical failures now stop the batch instead of failing
all 17 files one at a time.

Fixed by installing `nvidia-cublas-cu12` + `nvidia-cudnn-cu12` (~1.2 GB) into the
venv. One wrinkle worth remembering: `os.add_dll_directory()` was **not** enough
to make CTranslate2 find them — it only affects loads that opt into
`LOAD_LIBRARY_SEARCH_USER_DIRS`, and CTranslate2 uses a plain `LoadLibrary`.
Prepending those folders to `PATH` is what actually works.

Tertius now detects all of this at startup: a CUDA GPU with missing runtime
libraries produces a console warning and a UI banner with the fix, and the model
comparison table judges against the memory that will really be used.

## Proven on real work (2026-08-02)

The three biggest gaps are now closed, all in one run:

- **Real speech, real model, real GPU.** `V1_00.mp3` (22.6 min of narration)
  transcribed with `large-v3-turbo` on the RTX 2060 in **about 60 seconds** —
  roughly 22x faster than realtime. Output reads correctly, including proper
  nouns and punctuation; SRT timings line up.
- CUDA runtime libraries installed (`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`,
  ~1.2 GB) and the GPU verified end-to-end through the server.
- `large-v3-turbo` downloads and runs; float16 on the 6 GB card is comfortable.

## 2026-08-02 — text timestamping, and two bugs it exposed

Supplied-text timestamping went in and Seth confirmed it works on real material.
Getting there turned up two defects worth recording:

1. **Uploads never ran the text matching.** `add_files()` was called without the
   flag, so an uploaded file was always mode `transcribe`, silently. Worse,
   `.txt` uploads were rejected and deleted, so supplying text that way was
   impossible. Both fixed; `.txt` now uploads and pairs by name.
2. **"No text found" gave no clue why.** The cause was that a browser never
   sends a file's original location, so `Upload & queue` copies audio into
   `_uploads/` and *that* becomes "beside the audio" — the user's text file next
   to the original was unreachable. Fixed with an optional **Text folder**
   (searched recursively) and by reporting the exact folders searched in the UI.

Both are the same underlying lesson: a feature that silently does the wrong thing
is worse than one that fails loudly.

## 2026-08-03 — one report, two bugs

Reported as: add a file, press Begin, the file leaves the queue, the queue reads
empty, Begin greys out. Add it again and it runs. Reproducing it first turned
out to matter, because it was two unrelated defects arriving in one click.

**The queue vanishing.** `start()` attached to whatever output directory was
requested whenever it differed from the attached one. Each directory has its own
state file, so that landed on the target folder's empty queue, found nothing
pending, and errored — with the files gone from the screen. Queued files now
come along, copied whole so a matched text file and the mirrored subfolder
survive, arriving as pending, and never overwriting an entry the target folder
has already finished.

**The swallowed click.** `renderRun` rebuilt the whole controls box, Begin
included, on every poll. A press spanning a tick puts mousedown on one element
and mouseup on its replacement, and the browser then fires no click at all.
Idle polling is every two seconds, so the window is wide open. It now compares a
signature of what it would draw and leaves the DOM alone when nothing changed.

Worth keeping: **rebuilding a control on a timer silently eats clicks**, and the
symptom — "I pressed it and nothing happened, so I pressed it again" — reads
like a mis-click rather than a bug.

## 2026-08-03 — readable transcripts, and a third format

`.txt` is now one sentence per line. Whisper's segments are cut for timing, not
for reading: they run on, break mid-sentence, and sometimes carry three
sentences at once. They are rejoined and re-split using the sentence splitter
the alignment feature already had, so `Dr.` and `Vol. 2` do not become line
breaks. No word changes, only where the lines fall. `.srt` is deliberately left
alone — its lines are timing units — and so is timestamped supplied text, which
promises your wording *and* your layout back unchanged.

`.json` was added as a third format, off by default. Fresh transcriptions get
every segment with its times plus the detected language and duration. Supplied
text gets a different shape on purpose: your chunks in order, each marked timed
or not, because the `.srt` can only carry cues that have times and a title page
that is never spoken has none.

Adding a format turned up three things that were already waiting:

1. A recording called `transcription_state.mp3` would have written its `.json`
   straight over the queue's own state file, part-way through the run using it.
2. The page seeded its selected-formats set from *every* chip on the row, so a
   new format would have switched itself on for everyone with no saved
   settings.
3. Supplied text was read as plain `utf-8`, so a BOM — which Notepad and
   PowerShell both write — survived as an invisible character glued to the first
   word, appeared in the output, and stopped that chunk matching the audio.

Also fixed: "Timestamp my own text" arrived pre-ticked, because
`use_reference_text` persists in the state file from whenever it was last run.
It now follows the queue in front of you rather than the saved flag.

## 2026-08-03 — the queue that looked unfinished

A 99-file batch finished at 06:07 into `Bible Study App\Transcripts` — the
output folder chosen in the UI. The server was restarted three times that
morning during other work. Each restart came back showing **99 files pending**.

Nothing was lost: 99 `.txt`, 99 `.srt` and a 99-done state file were in that
folder the whole time. But a new batch was started against the stale queue and
re-transcribed two files before it was stopped.

The cause was one line. The launcher passed `--output-dir <app>\transcripts` on
*every* start, and each output directory keeps its own queue — so every restart
snapped back to the default folder, which held a never-run copy of the same 99
files. The old `.bat` had hardcoded the same flag; it had simply never been
noticed, because the server had never been restarted this often in one session.

Fixed by making the flag optional and the resolution explicit: an explicit
`--output-dir`, else the folder last used, else the default. The choice is
recorded by `JobManager.attach`, which every route that changes the directory
already goes through, so there is one place to get right rather than four.

That also exposed something the always-passed flag had been hiding:
`default_output_dir()` was `cwd/transcripts`, so starting the server from any
other working directory would have silently attached to a different queue. It
is anchored to the install location now.

The lesson is the same one as the GPU incident above, in a different costume:
this was a *silent* wrong answer. Nothing errored, nothing logged a warning —
the app confidently displayed a finished batch as unfinished work, and the only
way to notice was to know what the number should have been.

**Clear queue** shipped alongside it, since the incident left a stale 99-file
queue that could only be cleared by deleting the state file by hand.

## 2026-08-03 — macOS and Linux

The app's logic was already portable — `pathlib` throughout, `sys.platform`
branches already present. The Windows coupling was in three places: a 130-line
`.bat` launcher with no equivalent, CUDA wiring that returned early on anything
but Windows, and a library glob that only looked in `bin`.

The launcher logic moved into `launcher.py`, with three thin wrappers that only
find a Python and hand over. CUDA now works the way each platform actually
loads libraries: Windows keeps the `PATH` trick, Linux opens each `.so` with
`RTLD_GLOBAL` because `LD_LIBRARY_PATH` is read at exec and cannot be changed
in-process. macOS is reported as CPU-only in its own right.

**CI paid for itself on the first run.** Five of eight jobs failed, and one was
a real defect a Windows machine could not have found: `Path.glob("*.txt")` is
case-insensitive on Windows and case-sensitive everywhere else, so text pairing
worked here and silently would not have on Linux. The test asserting that exact
behaviour was green locally.

## 2026-08-03 — the designed UI, and the launcher bug it exposed

The UI was rebuilt from the *Tertius — UI & Identity Redesign* handoff (kept in
`app/design/handoff/`). Two columns: a fixed 352px setup rail, and
a status band over the file queue. Cardo and IBM Plex are self-hosted as woff2 —
an offline tool must not fetch fonts from Google at runtime.

Three things had to become real in the backend before the design could be honest
rather than decorative:

1. **Progress through a file.** The transcriber now takes an `on_segment`
   callback, so the active row shows a true percentage, a waveform playhead, and
   the last words written. Offered by signature check, so an older three-argument
   transcribe function is never handed a callback it does not want.
2. **File lengths.** `media.py` reads durations from the container header with
   PyAV — no decode, no ffmpeg — on a background thread. That is the Length
   column, the total-audio figure, and progress weighted by *audio* rather than
   file count.
3. **Word counts**, recorded on completion, for the finished-batch summary.

Where the design assumed a capability the app does not have, the app won:
two format chips rather than four (only `.txt` and `.srt` are written), no
*Pause* (the engine cancels between files; the resulting state borrows the
paused visual language and offers Resume), and no idle time estimate, because
nothing stores a realtime factor from a previous run.

**The launcher was serving a broken app.** `--reuse-existing` reconnected to a
server started *before* the redesign. Python holds the templates in memory but
reads the stylesheet and script off disk on every request — so the browser got
old markup with the new script, which threw on the first element that no longer
existed and stopped dead. Nothing was wrong with the app; the launcher just
never asked whether the server it was reusing was current.

The launcher now probes the port first: idle Tertius → stop it and start
fresh (the queue lives in the state file, so nothing is lost); busy Tertius →
open its tab and say plainly that an update needs a relaunch after the batch;
nothing there → start normally.

## 2026-08-03 — the `.json` says what it is

The `.json` carried data but nothing *about* the data. Two problems, both only
visible from the outside:

1. Two different shapes are written — a fresh transcription's `segments`, and
   supplied text's `chunks` — and both land as a `.json` beside the audio. The
   extension cannot tell them apart; a reader had to guess from which keys it
   found.
2. Nothing said the shape might change. Anything built on it would have broken
   silently the first time a key was renamed, with no way to detect it.

Both payloads now open with `version` (currently `1`) and `kind`
(`transcription` / `alignment`), first keys, so a reader meets them before
reading anything else. The rule for the number: bump when a key is renamed,
removed, or changes meaning; adding a key does not bump, since code keyed on
the old ones still works.

The version lives in `config.py`, not in either renderer. Two writers stamping
their own copy is exactly the drift this key exists to catch, and it is why
`alignment.py` — otherwise free of internal imports — now takes one from
`config` (which imports nothing but the standard library, so it stays
cycle-free).

Written up in the README with a sample of each shape, including the advice to
refuse an unknown `version` rather than misread the file.

## 2026-08-03 — made publishable

Decided to release this as open source under MIT. An audit of what publishing
would actually mean turned up two things that had to be fixed first, both about
other people's rights rather than about the code:

1. **No licence at all.** Without one, a public repo is not open source — it is
   source-visible under default copyright, and nobody may legally use, modify or
   redistribute it. `LICENSE` now carries MIT, taken verbatim from SPDX's
   canonical text.
2. **Fourteen bundled font files with none of their notices.** The interface
   fonts are self-hosted so an offline tool never fetches its own UI over the
   network — good for the app, but it makes publishing an act of font
   redistribution, and OFL 1.1 requires each copy to carry the copyright notice
   and licence. Nothing in the repo named either holder.
   `THIRD-PARTY-NOTICES.md` now does, with the OFL reproduced verbatim.

Both licence texts were fetched from upstream and copied byte-for-byte rather
than retyped. Worth knowing for next time: a web search got Cardo's copyright
wrong (it said 2004-2010 with a reserved font name). The notice Google Fonts
actually ships — which is where these files came from — reads
`Copyright (c) 2002-2011, David J. Perry`, and Cardo declares **no** reserved
font name. Only IBM Plex does. Checking the source rather than the summary is
the difference between a correct notice and a wrong one.

Also, and separately:

- `requires-python` said `>=3.9`, which no test had ever backed — CI runs 3.11,
  3.13 and 3.14. Raised to `>=3.11`, the floor actually exercised, and the
  README now states it. The `3.9-3.14` figure still in the install notes is
  about ctranslate2's wheel coverage, not Tertius's own floor.
- `SECURITY.md` added: reports go through GitHub's private advisories rather
  than an email address, with the threat model spelled out — the boundary is
  the machine, and binding to `0.0.0.0` is a documented consequence rather than
  a vulnerability.

## 2026-08-03 — the transcript that stopped having sentences

Reported as: the `.txt` stops separating sentences at line 133 and puts the rest
of the talk on one line. It was not the splitter. Whisper stopped emitting
punctuation at **00:14:45** of a 38-minute talk, and the splitter did the only
thing it can with punctuation-free input.

The `.srt` from the same run is the proof, since that format is left alone:
cue 520 is `gates?`, and the 2,197 cues after it — 23 of the 38 minutes — are one
or two words each, no punctuation, no capitals. The words stayed right; only the
formatting collapsed.

`transcribe()` never passed `condition_on_previous_text`, so faster-whisper's
default of `True` applied: each 30-second window is prompted with the previous
window's text. One unpunctuated window becomes the prompt for the next, and the
model keeps being told that is the house style. It never recovers.
`prompt_reset_on_temperature` cannot rescue it, because the model is not failing
its confidence checks — it is confidently producing correctly-worded text in the
wrong shape.

Re-run on the GPU with only that flag changed, on the same file:

| | segments | mean words/segment | punctuation survives to |
|---|---|---|---|
| conditioning on (was) | 2,717 | 1.4 | 14.8 min of 38.1 |
| conditioning off (now) | 499 | 7.8 | 37.5 min of 38.1 |

The baseline reproduced the original failure exactly — same segment, same
`gates?`, same 885.5s — so it is deterministic, not an unlucky roll. Accuracy
improved as well, not just layout: the collapsed run dropped "of heaven" from
"the keys of the kingdom of heaven" and wrote "Bragnot" for "Bragnat".

Off by default now. The cost is consistency of rare proper nouns across a long
file, which is much the smaller loss. It is a real tradeoff rather than a free
win, so it is a field on `TranscriptionOptions` and can be turned back on.

**It was never one file.** Scanning all 99 volume transcripts for the same
signature found it nearly everywhere: `V4_07.txt` had 419 of 723 lines without
terminal punctuation, `V2_06.txt` a single 3,472-character line, `V4_05.txt`
collapsed at line 16 of 167. The whole corpus was transcribed with these
defaults, so the whole corpus had it. Volumes A-F and Tabernacle Shadows are
being re-transcribed.

The lesson is the one this project keeps relearning in new costumes: nothing
errored. A library default that is right for short clips is wrong for a
38-minute talk, and the app inherited it without ever stating a choice.

## Not verified — read this before trusting it

- Only one transcript and one aligned output have been read closely. Accuracy
  across a whole volume, and on harder audio, is still unassessed.
- **Nothing has ever been run on a Mac or a Linux machine.** There wasn't one.
  The cross-platform support was written, and merged, without a single line of
  it executing on the hardware it is for. What exists instead is a CI matrix
  (ubuntu/macOS/Windows × 3.11/3.13, plus Windows 3.14) and tests pinning each
  platform branch — which proves the logic runs, and nothing more. Specifically
  unverified there: real audio decode, CUDA on Linux, the tkinter folder picker,
  whether `Tertius.app` double-clicks, whether the generated `.desktop` entry
  works, whether `tertius.icns` even looks right, and any Mac throughput figure.
  The ~22x realtime number below is from an RTX 2060 and does not transfer.
- Long-batch behaviour (17 files back to back) has not been run start to finish.
- Alignment has not been tried on a text that diverges heavily from the audio
  (abridged, reordered, or a different edition).
- The UI's narrow-window behaviour (below 1180px, and the collapsed rail below
  1000px) is written but unseen — the browser could not be given a small enough
  viewport to check it.

## Next steps

1. Run a full volume through and read a few outputs properly.
2. Get this in front of a real Mac and a real Linux box. Everything in
   *Not verified* about those two stays open until someone does.
3. Decided (2026-08-03): this ships, as open source under MIT. The legal
   groundwork is in; what is left before flipping the repo public is below.
4. Packaging is still untouched — run-from-source only, no wheel, no installer.
   Strangers on macOS and Linux will arrive before either platform has been run
   by hand, which is the risk to weigh before publishing.

## Ideas not built

- Whisper can also *translate* to English (`task="translate"`); Tertius only
  transcribes. The library supports it — it is just not exposed.
- Alignment reports how many chunks went untimed in the log, but the UI does not
  show it per file. Worth surfacing if a text ever aligns badly.
- No live microphone input; file/batch only, as the original spec required.

## Gotchas worth remembering

- **PowerShell corrupts UTF-8 text files. Do not use it to rewrite text here.**
  `Get-Content -Raw` decodes as cp1252 in PS 5.1, so read-modify-write
  double-encodes every em-dash, ellipsis and symbol, and `Set-Content -Encoding
  utf8` adds a BOM. It has now silently damaged files twice in this project —
  the templates during a rename, and a stray BOM dropped mid-README. Use Python
  or an editor for any text rewrite.
- **Windows allows a second bind to a port already in use.** Two servers on 5005
  will happily share (and corrupt) one state file. `--reuse-existing` guards the
  launcher path; do not start two by hand against one output directory.
- **A long-running server serves old HTML with new CSS and JS.** Templates are
  compiled once and held in memory; `static/` is read from disk per request. So
  reconnecting to a server that predates a UI change gets last week's markup and
  this week's script, and the page breaks in a way that looks like the app is
  broken. After changing anything in `templates/` or `static/`, restart the
  server — the launcher now does this for you when it finds an idle one.
- **cmd does not process `^` escapes inside quoted arguments.** A `^|` inside a
  `powershell -Command "..."` string reaches PowerShell literally and kills it
  with no visible error.
- **`huggingface_hub` progress bars lie about totals.** Overlapping bars roughly
  double the byte count, and a bar's `total` can be set after construction. Use
  the ratio for the percentage, not the byte figures.
- Each launch shows as two `python.exe` processes (venv redirector). Relevant
  when counting processes to check whether a second server started.
- `faster-whisper` / `ctranslate2` install fine on Python 3.14.
- **`Path.glob` is case-insensitive on Windows and case-sensitive elsewhere.**
  Any extension filter written as a glob (`*.txt`) is therefore a silent
  platform behaviour change — the file is simply not found, with no error. It
  cost a real bug: text pairing compared the stem case-insensitively while the
  extension quietly wasn't, so `talk.TXT` paired here and would not have on
  Linux. Filter on `suffix.lower()` in code instead.
- **Git stores shell scripts with CRLF when you develop on Windows**, and a
  CRLF shebang makes the kernel report `/bin/sh\r` as a missing interpreter for
  a file that plainly exists. `.gitattributes` pins `*.sh`, `*.command`,
  `.desktop` and the `.app` executable to LF, and `*.bat` to CRLF.
- **Do not monkeypatch `os.name` in tests.** `pathlib` picks its flavour from
  it, so stubbing it to exercise another platform's branch makes `Path` raise
  `UnsupportedOperation` underneath. Platform branches are keyed off
  `sys.platform`, which nothing else depends on.
- **Rebuilding a DOM control on a poll timer silently eats clicks.** A press
  spanning the rebuild puts mousedown on one element and mouseup on its
  replacement, and no click event fires. Compare a signature of what would be
  drawn and skip the rebuild when nothing changed.
- **Deriving "what is selected" from "what exists" is a bug waiting.** The
  format chips seeded their selected-set from every chip present, so adding
  `.json` would have switched it on for everyone without saved settings.
- **Anything writing `<stem>.<fmt>` into the output directory can collide with
  Tertius's own files** — `transcription_state.json`, `tertius.log`. Only
  reachable once `.json` became an output format, and it would have corrupted
  the state file mid-run. Both write paths go through one guard now.
- **Read supplied text as `utf-8-sig`, not `utf-8`.** Notepad and PowerShell
  both write a BOM; read as plain utf-8 it survives as an invisible character
  glued to the first word, which then shows up in the output *and* stops that
  chunk matching the audio. Files without a BOM are unaffected.
- **`condition_on_previous_text` defaults to `True` in faster-whisper, and on a
  long recording that is a trap.** Each 30s window is prompted with the previous
  window's text, so one unpunctuated window teaches the model to keep going that
  way, for the rest of the file. It cost 23 minutes of a 38-minute talk, and
  quietly damaged 99 transcripts before anyone read far enough down one to
  notice. Nothing errors; the words stay correct and only the shape goes. Any
  library default tuned for short clips deserves this suspicion.
- **A Windows venv cannot be moved** — `pyvenv.cfg` and the `Scripts` shims hold
  absolute paths. Relocating means deleting and recreating. The model cache is
  unaffected; it lives in `~/.cache/huggingface/hub`, outside the app folder.
- **Each output directory keeps its own queue.** Changing the output folder
  switches you to a different state file with a different history. The failure
  mode is expensive rather than cosmetic: a server that comes back up pointing
  elsewhere shows a finished batch as pending, and pressing Begin redoes it.
  Anything that resets the output directory on restart is a data-costing bug.
- **A `.bat` file cannot carry its own icon.** Windows takes the icon from the
  file type and offers no per-file override, so the launcher writes a `.lnk`
  and a `desktop.ini` folder icon instead. `desktop.ini` also needs an
  *absolute* `IconResource` path — a relative one is ignored, confirmed by
  asking `SHGetFileInfo` what Windows resolves for a test folder.

## Layout

Restructured 2026-08-03: the launchers, `README.md` and `transcripts/` are the
top level, because they are the only things most people need. Everything the
app is made of lives under `app/`.

```
Start Tertius.bat    Windows launcher
Tertius.app/         macOS launcher (a shell script in a bundle, no compiler)
start-tertius.sh     Linux launcher
LICENSE              MIT
THIRD-PARTY-NOTICES.md   bundled fonts (OFL 1.1) and dependency licences
SECURITY.md          how to report something exploitable
transcripts/         output, the resume state file, and the log
app/
  src/tertius/       the app
  tests/             the suite
  assets/            the T mark as .svg/.png/.ico/.icns, plus its generator
  design/            UI handoff and the original build spec
  .venv/             created on first run
```

See README.md for full documentation — install, launch, resume semantics, model
sizes, GPU notes, and the HTTP API.
