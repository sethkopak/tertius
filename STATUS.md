# Tertius — status

Last updated: 2026-08-01

## Where it stands

Built in one session from `transcription-app-claude-code-prompt.md`. Everything the
prompt asked for is implemented, plus the additions requested during the build
(launcher, folder picker, model download progress, model comparison + system
check, tooltips, light/dark theme, the Tertius name).

**113 tests, all passing.** Whisper is mocked throughout — the suite downloads
nothing and decodes no audio.

Run it: double-click `Start Tertius.bat`.

Repo: `github.com/sethkopak/tertius` (private), branch `main`.

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
- **Double-launch.** Second run of the launcher reuses the running server rather
  than starting a second one.
- **UI in the browser.** Scan → queue → start → live polling → completed with
  per-file download links. Model table, theme toggle, and download panel all
  checked visually. No console errors.

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

To use the GPU on this machine:
`.venv\Scripts\pip install nvidia-cublas-cu12 nvidia-cudnn-cu12` (~1.2 GB).
Tertius registers those packages' DLL directories at startup, which Windows does
not do by itself.

## Not verified — read this before trusting it

- **No real speech has ever been transcribed.** The only audio used was a
  synthetic 220 Hz tone, which correctly produced an empty transcript. Accuracy
  is completely unproven.
- **The default model has never run.** `large-v3-turbo` (1.51 GB) has not been
  downloaded. Only `tiny`, `base`, and `small` are cached.
- **The GPU path has never been exercised.** Every run so far was CPU, despite
  the RTX 2060 being present and detected.
- Windows only so far.

## Next steps

1. **Transcribe real speech** and judge the output. Biggest untested thing.
2. **Run the default turbo model once** and try `device: cuda` on the RTX 2060.
   Expect the first run to pause ~1.5 GB worth of download.
3. Decide what this is: personal tool, or something that ships.

## Ideas not built

- Whisper can also *translate* to English (`task="translate"`); Tertius only
  transcribes. The library supports it — it is just not exposed.
- Language is a free-text code box. A dropdown of the 100 supported languages
  with real names would be friendlier.
- No live microphone input; file/batch only, as the original spec required.

## Gotchas worth remembering

- **PowerShell corrupts UTF-8 text files.** `Get-Content -Raw` decodes as cp1252
  in PS 5.1, so read-modify-write double-encodes every em-dash, ellipsis and
  symbol, and adds a BOM. It silently mangled the templates during a rename in
  this project. Use Python or an editor for text rewrites.
- **Windows allows a second bind to a port already in use.** Two servers on 5005
  will happily share (and corrupt) one state file. `--reuse-existing` guards the
  launcher path; do not start two by hand against one output directory.
- **cmd does not process `^` escapes inside quoted arguments.** A `^|` inside a
  `powershell -Command "..."` string reaches PowerShell literally and kills it
  with no visible error.
- **`huggingface_hub` progress bars lie about totals.** Overlapping bars roughly
  double the byte count, and a bar's `total` can be set after construction. Use
  the ratio for the percentage, not the byte figures.
- Each launch shows as two `python.exe` processes (venv redirector). Relevant
  when counting processes to check whether a second server started.
- `faster-whisper` / `ctranslate2` install fine on Python 3.14.

## Layout

See README.md for full documentation — install, launch, resume semantics, model
sizes, GPU notes, and the HTTP API.
