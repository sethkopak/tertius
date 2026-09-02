# Tertius — status

Last updated: 2026-09-02

## Where it stands

Working, and in real use. Built from `design/original-spec.md`, plus everything
requested since: the launcher, folder picker, model download progress, model
comparison + machine check, tooltips, light/dark theme, mirrored output folders,
timestamping of supplied text, the designed UI, macOS/Linux support, and
translation.

**382 tests, all passing**, on Windows locally and on ubuntu/macOS/Windows in
CI. Whisper is mocked throughout, and so is the translator — the suite
downloads nothing, decodes no audio and converts no checkpoints, which is what
makes it safe to run on a hosted runner.

Run it: double-click `Start Tertius.bat` (Windows), `Tertius.app` (macOS), or
run `./start-tertius.sh` (Linux).

Repo: `github.com/sethkopak/tertius` (private), branch `main`. Translation
merged and pushed 2026-09-02 (`cb52c5e`, `4fb26e7`).

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
- **Translates the transcript** (2026-09-01) into any language the chosen
  model knows, offline, as a second pass after transcription. Three models to
  pick from: `m2m100-418M` (MIT, 100 languages), `m2m100-1.2B` (MIT), and
  `madlad400-3b-mt` (Apache-2.0, 400+). The original-language files are always
  written too - a translation lands beside them as `talk.es.txt`.
- **Translates plain text with no audio at all** (2026-09-01). Scan a folder
  for `.txt` instead of media and the files go straight to the translator;
  Whisper is never loaded. Paragraph and sentence shape is preserved, and no
  `.srt` is written, there being no timings to write.
- **The queue follows you** when the output folder changes. Each folder keeps
  its own history, but files you have lined up are what you are pointing at.

## 2026-09-01 — translation, actually run

`m2m100-418M` downloaded, converted, loaded and used. What the fakes could not
tell us, now known:

- **The install works.** `torch-2.14.0+cpu-cp314-cp314-win_amd64.whl`, 125.9 MB
  from the CPU index, into the venv, with `transformers` 5.16.1 and
  `sentencepiece` behind it.
- **The conversion works**, and int8 does what it was chosen for: 1.94 GB of
  float32 weights become a 490 MB `model.bin`. Thirteen seconds once the
  weights are cached.
- **`lang_code_to_token` exists** on the real `M2M100Tokenizer` instance, 100
  entries, exactly as the adapter assumed. It is *not* on the class, which is
  worth knowing before checking for it the wrong way.
- **The language codes land in `shared_vocabulary.json`** in the `__xx__` shape
  the regex expects. 100 read back, and the menu in the browser fills with all
  of them.
- **The output is real Spanish, French and German.** "The meeting will begin at
  nine o'clock tomorrow morning." became "La reunión comenzará a las nueve de la
  mañana." and "Das Treffen beginnt morgen um neun Uhr morgens."

Two bugs it found, neither of which any of the 36 tests could have:

1. **`config.json` was in the copy list, and CTranslate2 writes its own.** The
   converter stopped with "already exists in the model directory" - *after* the
   entire 1.9 GB download, which is the worst possible moment to fail. Only
   tokenizer files may ride along now, and `CONVERTER_WRITES` names the ones
   that must not, with a test over every family's pattern list.
2. **`AutoTokenizer` cannot read a converted directory.** `config.json` there is
   CTranslate2's runtime config rather than a transformers model config, and
   M2M-100's `tokenizer_config.json` names no `tokenizer_class` to fall back on.
   The family now names its tokenizer class outright. This had not been reached
   yet when the first bug stopped the run - it was found by reading, not by
   failing.

The scratch-directory design held: the failed conversion left nothing behind,
and the retry needed no re-download.

One thing to be honest about: **`m2m100-418M` is a small model and it shows.**
"Bring the blue notebook and a pen." came back as "trae el boletín azul y una
pena" - bulletin, and sorrow. Long sentences with context are good; short ones
are a coin toss. That matters more here than it would elsewhere, because
segments are translated one at a time to keep the timings honest, and a Whisper
segment is often short. `m2m100-1.2B` is the answer if the output is not good
enough, and it is one menu choice away.

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
- **Translation, on a real model** (2026-09-01). `m2m100-418M` converted and
  run on the CPU; 100 languages read out of the converted vocabulary and
  seen filling the menu in the browser; English translated into Spanish,
  French and German and read back. See the entry above for the two bugs
  this found that the tests could not.
- **A translation job, end to end through the server** (2026-09-01). Not the
  library in isolation: `create_app`, scan, queue, `/api/job/start`, the
  JobManager's worker thread, and the files on disk afterwards. A text source
  into Romanian, `.txt` and `.json` both written, paragraph breaks intact.
  Whisper was never loaded, as intended for an all-text queue.
- **A whole audio file transcribed and translated** (2026-09-01). `V1_01.mp3`,
  38:12, into Romanian: **64 seconds** for both, on the real converted
  `m2m100-418M`. 465 cues in `.srt` and 465 in `.ro.srt`, **every cue timing
  identical**, no segment left in English, and the source-language files
  untouched. The per-segment design does what it was for.
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

Two short stretches still collapse in the repaired output — 249 characters
mid-file and the last 366 at the very end — so the failure is an attractor the
flag makes rare rather than impossible. No words are lost in either; only the
punctuation goes.

**Alignment turned out to be immune, and the corpus never needed redoing.**
The first read of this said all 99 volume transcripts had the same signature,
on the strength of a scan counting lines without terminal punctuation. That
scan was measuring the wrong thing. Every one of those 99 is an *alignment*
output — Russell's own published text with timings added — and its line breaks
are chunk boundaries, not sentence ends. Lines without a full stop are what
that format normally looks like.

Re-aligning `V1_02.mp3` both ways settled it: 2,414 words against 2,416, and
**7 of 30 chunks untimed either way**. Alignment consumes only the word stream,
and the collapse costs punctuation, capitals and segmentation — never the
words. Segment count moved (169 to 235) and nothing downstream cared.

So the blast radius is fresh transcription only. In this output directory that
was one file, the Elbert talk, since everything else was supplied text.

Two lessons, and the second is the more expensive:

1. Nothing errored. A library default that is right for short clips is wrong
   for a 38-minute talk, and the app inherited it without ever stating a choice.
2. **A proxy metric found a real bug and then invented a fake one.** "Lines
   with no terminal punctuation" is a fair signal in a transcript and a
   meaningless one in aligned text, and reading one number across both formats
   nearly cost 99 files of Russell's text — they were queued for re-transcription
   as fresh audio, which would have replaced his wording with Whisper's. Three
   were overwritten before the check that caught it; a backup taken first is why
   that sentence ends here. Check what a format *is* before measuring it.

## 2026-09-01 — translation

Asked for: translate audio or text into another language, text out. Built as a
second model run after transcription, so it applies equally to a fresh
transcript and to timestamped supplied text without touching either path.

Three things had to be settled first, and all three changed the answer.

1. **Whisper's own `translate` task only ever produces English.** That is the
   whole of it - any language in, English out. It sat under *Ideas not built*
   as though it were this feature; it is not, and it is still not exposed.
2. **NLLB-200 is CC-BY-NC-4.0.** It is the best model in this size class and
   was the obvious pick. Tertius is MIT and about to be public, and a default
   feature that forbids commercial use to everyone downstream is not something
   to ship quietly. Converting the weights ourselves would not have changed the
   licence - that restriction is Meta's. Dropped for permissively licensed
   models: M2M-100 is MIT, MADLAD-400 is Apache-2.0. `test_nllb_is_not_offered`
   exists so a future change has to argue with the reason.
3. **We convert the publisher's weights rather than downloading a conversion.**
   Ready-made CTranslate2 builds of all of these exist on the Hub and would
   have saved the whole conversion path. They are individual accounts with no
   signature and nothing tying their `model.bin` to the weights it claims to
   be - and Tertius points every user it gets at whatever it names. Seth's call.

How it works. `translate.py` wraps `ctranslate2.Translator` the way
`transcribe.py` wraps `WhisperModel`: lazily loaded, reused across the batch,
unloaded at the end, and honouring the same process-wide "CUDA is broken here"
memory, so a machine whose GPU already failed a transcription does not go and
wedge itself again on the translation. First use downloads the publisher's
weights and converts to int8 into `tertius-translation/` beside the Hugging
Face cache, via a scratch directory that is only moved into place once the
conversion is complete.

The two model families disagree about how to be told a target language, which
is what the adapters hide. M2M-100 puts a source-language token in front of the
input and forces the target token as the first output token; MADLAD is a T5 and
takes the target in the input text as a `<2es>` prefix, with nothing forced.
Get it wrong and neither model errors - they translate into the wrong language
or echo the source back. Both have a test pinning the exact tokens.

Decisions worth remembering:

- **Segments are translated one for one**, so the timings stay the ones that
  were actually measured. Translating the transcript whole would read a little
  better, but there would be no honest way left to say when any of it was said.
- **The source-language files are never replaced.** A bad translation costs you
  nothing you already had.
- **A failed translation does not fail the file.** The transcript is real work
  and is already on disk; marking it failed would send a resume back to redo a
  transcription that was fine - an hour thrown away on a 40-minute recording
  for a tokenizer error. It is reported, and three in a row still stop the
  batch, the same rule transcription already had.
- **The target-language menu is read from the converted model's vocabulary**,
  not a table kept here by hand, for the same reason the Whisper menu is read
  from Whisper. It is empty until the model is converted, and the UI says what
  the first run will cost rather than inventing a list.
- **Word timings are dropped** from a translated result. They describe the
  source words, which the translation has replaced.
- `.json` gains a third `kind`, `translation`, carrying the model and repo it
  came from. A translated file must not be mistaken for a transcript of what
  was actually said.

`transformers` and `sentencepiece` are new run-time dependencies (M2M-100 ships
no `tokenizer.json` and no fast tokenizer class, so `tokenizers` alone cannot
read it); `torch` is needed only to convert. All three are the `translate`
extra, so a machine that only transcribes pays for none of them.

## 2026-09-01 — the language menu nothing could fill

Reported straight after the above: "I cannot choose a language." It was a
deadlock, designed in, and the browser said so plainly - the target-language
menu held exactly one option, the placeholder.

- The menu is filled from the *converted* model's vocabulary.
- Nothing converted a model except starting a job.
- A job would not start without a target language.

So the menu could never be filled and translation could never be used. The
reasoning behind it was sound - a hand-written language table goes stale, and
the Whisper menu is read from Whisper for exactly that reason - but it made the
list unavailable at the one moment it was needed.

Fixed with an explicit **Download and prepare** step: a button, an endpoint,
and `Translator.prepare()`, which downloads and converts without loading the
model onto a device. Until a model is ready the "Into" menu is disabled and
says why, rather than sitting there empty and inert. This is better than the
implicit version anyway - a 1.9 GB download now happens because someone asked
for it, instead of hiding inside Begin.

Worth remembering: **checking this in a browser found it in about a minute.**
The 36 tests behind the feature all passed, because every one of them was
written from the same wrong picture of how a model becomes ready.

## 2026-09-01 — text in, no audio

The other half of the original request, built after the audio half. A `.txt`
can now be a source in its own right.

- `scan_directory(kind="text")` is a **separate scan**, not an extra extension
  on the media list. The same `.txt` means two different things depending on
  why it was picked up: found beside an audio file it is reference text to be
  timestamped, and scanning for both at once would make that ambiguous.
- A queued `.txt` gets its own mode, `translate_text`. There is no audio to
  transcribe and nothing to align against; translating it is the only thing to
  do with it.
- **Whisper is not loaded for a queue that is all text.** Otherwise a text-only
  job would download gigabytes to sit idle, and would fail outright on a machine
  whose GPU is broken but which was never going to be asked to decode anything.
- Paragraphs and sentences are preserved. A translated file arriving as one
  wall of text has lost something the original had.
- **No `.srt`**, however the format chips are set. There are no timings, and
  invented cues would be worse than none.
- A text file queued with translation switched off fails with a message saying
  so, rather than being silently skipped.

## 2026-09-01 — Tertius installs its own translation libraries

"Can't download and prepare a model without torch." Correct, and the answer
was not to bundle torch: the wheel that is right depends on the machine
(platform, architecture, Python version), it is a large binary per combination,
and redistributing it carries obligations the repo does not want. **Download
and prepare** now installs it instead, which is the same thing from the user's
side.

A number in the entry above was wrong and is worth correcting, because it
shaped the advice given: **torch on Windows is 122 MB, not the ~2.5 GB claimed
twice.** That figure is the Linux CUDA build. The whole translation extra here
is about 150 MB:

| Wheel | Size |
| --- | --- |
| torch 2.13.0 (cp314, win_amd64) | 122.3 MB |
| transformers 5.16.1 | 12.1 MB |
| sympy, networkx, sentencepiece, safetensors | ~10 MB |

Decisions:

- **torch comes from `download.pytorch.org/whl/cpu`**, in its own pip call.
  Conversion loads a checkpoint and writes it back out; it never runs the
  model, so a CUDA build buys nothing - and on Linux the default PyPI wheel
  carries a bundled CUDA runtime well over a gigabyte. The index has cp3xx
  wheels for Windows and for Linux x86_64 and aarch64; macOS resolves from
  PyPI, whose macOS wheels are CPU-only anyway. The other packages are not on
  that index, which is the other reason the call cannot be shared.
- **It refuses to install outside a virtual environment.** Quietly putting
  120 MB of torch into somebody's system Python because they clicked a button
  in a transcription app is not a thing to do; there it prints the command
  instead.
- **Only Download and prepare may install anything.** A transcription-only run
  never reaches for pip, and there is a test each way.
- pip's output is surfaced line by line under its own phase, so several minutes
  of installing does not look like a hang - the same reason the model download
  has a phase.

There is precedent for all of this: the launcher already builds the virtual
environment and pip-installs `requirements.txt` on first launch. This is the
same bargain, not a new one.

## 2026-09-01 — the fragment problem

The first real run worked, and measuring it turned up a design cost that had
not been thought through.

`V1_01.mp3` into Romanian: 465 cues out, every timing identical to the English,
nothing left untranslated. But the two `.txt` files do not read alike.

| | English | Romanian |
| --- | --- | --- |
| sentences in `.txt` | 204 | 116 |
| median line length | 129 chars | 204 chars |
| words | 6,104 | 5,836 |

Nothing is lost - the word counts are a normal ratio for a translation. The
translated `.txt` is simply worse to read, and here is why.

**Whisper segments are cut for timing, not for meaning.** Measured on this
file: **71%** of segments begin mid-sentence, **78%** end without a full stop,
and **54%** are fragments at both ends. Translating segment by segment means
the model is handed a fragment more than half the time - "doubt and gloom
intensified by", with no subject and no end - and asked to render it alone.

Two consequences, both visible in the output:

1. **Quality.** "the doubt and gloom intensified by" came back as "îndoielile și
   glumele intensificate de" - *glume* is jokes. A model given the whole
   sentence would not make that mistake. This is the same failure as "bring the
   blue notebook" becoming "trae el boletín azul" in the first CPU test, and it
   is not simply the model being small: it is the model being starved.
2. **Readability.** `segments_to_txt` rejoins segments and re-splits on
   sentence ends. That works on a transcript, whose punctuation is continuous
   across the segment cuts. It does not work on independently translated
   fragments, whose punctuation no longer lines up with sentence boundaries -
   hence 116 lines where there should be about 204.

**Built, and measured.** The `.txt` is now translated as rejoined sentences;
the `.srt` and `.json` are still translated per segment, because their timings
are the point and only a segment has them.

What it actually bought, on this same file:

| | fragments | sentences | English |
| --- | --- | --- | --- |
| `.txt` sentences | 116 | **206** | 204 |
| translation time | 12s | **221s** | - |

Two corrections to the paragraph this replaced, both of which were wrong:

- **"About twelve seconds more" was badly wrong.** The sentence pass takes
  **221 seconds** against 12 for the segment pass - sentences are longer than
  fragments, so there is far more to generate. A 64-second run becomes about
  285. Still eight times realtime, but four and a half times the cost.
- **"A model given the whole sentence would not make that mistake" was also
  wrong.** *gloom* still comes back as *glume*, jokes - and the new rendering,
  "Doiciunea", is not a Romanian word at all. Grammar and word choice did
  improve elsewhere ("clipate dintr-o ziară" became "sculptate dintr-un
  jurnal"), but vocabulary errors of that kind are the 418M model being small,
  not the model being starved. The answer to those is `m2m100-1.2B`.

So the sentence pass is a decisive structural win, a partial quality win, and
expensive. That is a trade worth making on one file and worth refusing on a
queue of ninety, so it is a setting - **Translate the .txt as whole sentences**,
on by default, because an unreadable `.txt` is the thing `.txt` exists to
avoid. It never touches the `.srt`, and a run writing no `.txt` never pays for
it whatever it is set to.

### A bug found on the way, older than any of this

`split_sentences` merged on `endswith(_ABBREVIATIONS)`, so any word *ending* in
one counted: "last.", "first." and - in scripture, constantly - "Christ." each
had the following sentence glued onto them. Two occurrences in `V1_01`. It is
matched on the last whole word now, with tests both directions, and it affects
plain transcripts as much as translations - every `.txt` this project has ever
written has had it.

## 2026-09-01 — 418M against 1.2B, on real sentences

`m2m100-1.2B` downloaded (4.96 GB), converted (1.2 GB on disk against 477 MB
for the 418M) and run against the same five sentences from `V1_01.txt`, both
models in one process so the comparison is fair.

**The 1.2B fixes the errors that started this.**

> "The doubt and gloom intensified by the clashing creeds of the various
> schools had not yet been dispelled…"
>
> - 418M: "Cuvântul **îndoielilor şi glumei** intensificate de credinţele
>   conflictuale… nu a fost încă **scos**…"
> - 1.2B: "**Îndoiala şi întunericul** intensificate de **crezurile**
>   conflictuale… nu **fuseseră** încă **risipite**…"

*gloom* is **întunericul** at last, after failing as *glume* - jokes - in every
418M attempt. *creeds* becomes *crezurile* rather than *credinţele*, *dispelled*
becomes *risipite* rather than *scos*, and the pluperfect "fuseseră" carries
"had not yet been" correctly. The 418M also invented a leading "Cuvântul".

The rest, in short:

| | 418M | 1.2B |
| --- | --- | --- |
| "clipped from a journal" | *sculptate* (carved) | *tăiate* (cut) |
| "in its increasing light" | *lumina **sa*** | *lumina **ei** crescândă* |
| "unto the perfect day" | *ziua perfectă* | *ziua desăvârşită* |
| "wholly enslaved by" | *sclavi de* | *sclavizate de* |

The possessive is the telling one: *lumina* is feminine, so *ei* is right and
*sa* is wrong. And *desăvârşită* is the register this material is written in.

Nothing regressed that was already right. The two sentences the 418M handled
well came back equal or slightly better.

**The cost.** 30.1s against 12.6s for five sentences - roughly 2.4x. On the
38-minute file the sentence pass would go from 221s to about 530s, so a full
run lands near ten minutes rather than five. Still four times realtime. Load
time is not the difference: the 1.2B loaded in 6.9s against the 418M's 20.2s,
which is disk cache, not size.

**For this material, use the 1.2B.** The 418M is the right default for a
stranger downloading Tertius for the first time - a third the disk, half the
wait - but on scripture, where "gloom" and "doubt" recur, it is not good enough
and the bigger model plainly is.

## 2026-09-01 — the queue said Transcribing while it was translating

Reported during the 1.2B run: "There is no indication that the translation is
happening." Two separate faults behind one symptom, and the second is the one
that mattered.

1. **The state column was hard-coded.** `stateCell` labelled every in-progress
   file "Transcribing" and ignored the phase, so a file being translated read
   *Transcribing 100%* - the transcription percentage, finished and frozen -
   for however many minutes the translation took. The status band above it had
   said "Translating" since the feature was built; the queue row never did.
2. **There was no translation progress to show.** `translate()` was one
   `translate_batch` call over every segment, so nothing existed to report
   between start and finish. Fixing the label alone would have produced
   *Translating* with no number and no movement, which is barely better.

Both fixed. Batching moved out of CTranslate2's `max_batch_size` and into an
explicit loop, so there is somewhere to report from between batches - the work
is identical either way. `on_progress(done, total)` threads from `Translator`
through `translated_result` and `translated_prose` to the JobManager, which
writes the same `active.progress` transcription uses.

The counting is worth a note. **Both passes report against one total**, and the
progress is reset to zero when translating starts rather than continuing from
the transcription's 100%. Segments and sentences cost different amounts each,
so it is not a time estimate - but a bar that restarts half way looks broken,
and one that goes backwards looks worse. The excerpt is deliberately left
alone: it is the last thing *transcribed*, and half a translated sentence in
its place would say less.

Worth noticing that this is the third time this session that something was
fine in tests and wrong on screen. The status band had a translation phase from
the day it was written, and the queue row - the thing actually being looked at -
did not.

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
- `madlad400-3b-mt` is still untried, and it is the whole of the T5 adapter -
  a different tokenizer, a different way of naming the target, and not one line
  of it has met a real model. Both M2M-100 sizes have now been run.
- The 1.2B has now been run through the queue on a whole file (`V1_01.mp3`,
  38:12). Compared closely on three sentences; the other 203 have not been
  read.
- Translation has only been run on the CPU. It has never been loaded onto
  the GPU, and whether it fits in 6 GB beside Whisper is still unknown.
- The translated `.txt` is measurably less readable than the transcript, and
  the cause is structural rather than a bug. See *the fragment problem* below.
- Long-batch behaviour (17 files back to back) has not been run start to finish.
- Alignment has not been tried on a text that diverges heavily from the audio
  (abridged, reordered, or a different edition).
- The UI's narrow-window behaviour (below 1180px, and the collapsed rail below
  1000px) is written but unseen — the browser could not be given a small enough
  viewport to check it.

## Next steps

1. Read a whole translated volume properly. `V1_01` has been checked closely on
   three sentences out of 206, and structurally on all of them; that is not the
   same as having read it.
2. Get this in front of a real Mac and a real Linux box. Everything in
   *Not verified* about those two stays open until someone does. Translation
   adds to what is riding on that: the installer shells out to pip, and the
   `.txt`-source scan has only run on Windows.
3. Try `madlad400-3b-mt`. It is the whole of the T5 adapter — a different
   tokenizer and a different way of naming the target language — and not one
   line of it has met a real model. 400+ languages is the reason to care.
4. Run a translation on the GPU. Everything so far has been CPU, which is why
   the translation comparison table has no "on this machine" column: there is
   nothing honest to put in it yet.
5. Decided (2026-08-03): this ships, as open source under MIT. The legal
   groundwork is in, and the translation models were chosen to keep it that way
   — see the 2026-09-01 entry on NLLB.
6. Packaging is still untouched — run-from-source only, no wheel, no installer.
   Strangers on macOS and Linux will arrive before either platform has been run
   by hand, which is the risk to weigh before publishing.

## Ideas not built

- Whisper can also *translate* to English (`task="translate"`), and that is
  still not exposed. Now a choice rather than an omission: it only ever
  produces English, and the translation feature covers that case with a model
  that can also do the other 99 languages. Worth revisiting only as a speed
  shortcut for English targets, which would mean a second code path.
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
- **Two processes preparing the same translation model look like a hang.**
  `huggingface_hub` locks the files it is fetching, so the second process sits
  at `Fetching 7 files: 0%` with no bytes and no explanation until the first
  finishes. It blocks rather than corrupting anything, which is the safe
  failure, but nothing says so. Seen for real on 2026-09-01: a script and the
  server were both told to fetch `m2m100_418M`. If a prepare appears stuck at
  zero, look for another Python holding the same download before believing it.
- **Windows allows a second bind to a port already in use.** Two servers on 5005
  will happily share (and corrupt) one state file. `--reuse-existing` guards the
  launcher path; do not start two by hand against one output directory.
- **A long-running server serves old *code*, not just old HTML.** The
  template point below is the visible half; the whole Python process is from
  whenever it started. On 2026-09-01 a server started at 14:09 kept failing
  translation with a tokenizer error that had been fixed at 14:33 - the fix was
  on disk, in the same venv, and provably working from a fresh interpreter. Two
  restarts were needed in one afternoon for this. If a fix does not take,
  compare the server's start time against the file's mtime before debugging the
  code.
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
  way, for the rest of the file. It cost 23 minutes of a 38-minute talk before
  anyone read far enough down to notice. Nothing errors; the words stay correct
  and only the shape goes. Any library default tuned for short clips deserves
  this suspicion. Alignment is unaffected — it reads only the word stream.
- **Aligned output and transcript output cannot be measured with the same
  ruler.** A transcript's lines are sentences, so a line with no full stop is a
  symptom. Aligned text's lines are chunks, so the same line is normal. One scan
  applied to both reported 99 healthy files as damaged and queued them to be
  re-transcribed from audio — which discards the supplied text that is the whole
  point of aligning. Check `kind` in the `.json`, or the timestamp prefix in the
  `.txt`, before drawing conclusions from a shape.
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
  src/tertius/       the app (transcribe.py and translate.py are the two models)
  tests/             the suite
  assets/            the T mark as .svg/.png/.ico/.icns, plus its generator
  design/            UI handoff and the original build spec
  .venv/             created on first run
```

See README.md for full documentation — install, launch, resume semantics, model
sizes, GPU notes, and the HTTP API.
