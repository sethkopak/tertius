# Handoff: Tertius — UI & Identity Redesign

## Overview

Tertius is an **offline audio transcription app** (faster-whisper under the hood) that runs
locally in a browser tab. Users point it at a folder of audio, choose a model and output
formats, and it transcribes the batch on-device. The audience is Bible students transcribing
sermons, people transcribing audiobooks, and anyone who needs transcription that never leaves
their machine.

This handoff replaces the existing basic UI with a designed one. The visual direction is
**classical/inscriptional but modern and clean** — the feeling of a Greek scriptorium expressed
through typography, ruled lines, and restraint rather than through ornament. There is
**no religious iconography of any kind** — no crosses, no scrolls, no doves. That constraint is
deliberate; please preserve it.

Both **dark mode and light mode** are specified in full.

## About the Design Files

The files in this bundle are **design references created in HTML** — prototypes that show the
intended look, structure, and behavior. They are **not production code to copy directly.**

`Tertius.dc.html` is a design-tool document, not an app. It contains several iterations of the
design laid out side by side on a canvas. **Only "Turn 4" (the top section, options `4a`, `4b`,
`4c`) is the approved design.** Turns 1–3 below it are earlier explorations kept for history —
ignore them, or read them only to understand how the direction was arrived at.

Your task is to **recreate the Turn 4 designs in the existing Tertius codebase**, using whatever
framework and patterns it already uses. Do not port the HTML wholesale; rebuild the UI natively.
The markup in the reference uses inline styles throughout because of how the design tool works —
in the real app, use the codebase's normal styling approach (CSS modules, Tailwind, styled
components, plain CSS — whatever is already there).

## Fidelity

**High-fidelity.** Colors, typography, spacing, and states are final. Match them closely.
Every hex value, font size, and dimension in this document is intentional.

Where the reference and this README disagree, **this README wins** — it resolves a few small
inconsistencies left in the prototype.

---

## Layout

One screen. Two columns, full viewport height, no page scroll on the shell — only the file
queue scrolls.

```
┌─────────────────────────────────────────────────────────────────────┐
│  ┌──────────────────┐  ┌────────────────────────────────────────┐  │
│  │  SETUP RAIL      │  │  STATUS BAND                           │  │
│  │  fixed 352px     │  │  ────────────────────────────────────  │  │
│  │                  │  │  QUEUE HEADER ROW                      │  │
│  │  · brand + theme │  │  ────────────────────────────────────  │  │
│  │  · 1 Source      │  │  QUEUE                                 │  │
│  │  · 2 Settings    │  │   (scrolls; active row is expanded)    │  │
│  │  · 3 Run         │  │                                        │  │
│  │  · (spacer)      │  │                                        │  │
│  │  · version foot  │  │                                        │  │
│  └──────────────────┘  └────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

- Outer shell: `display: flex`, 1px border in the mode's border color, `border-radius: 6px`
  (if the app is windowed/inset) or full-bleed with no radius if it fills the tab.
- **Left rail**: `width: 352px; flex: none;` right border 1px. Sections stack top-to-bottom;
  the version footer is pushed down with `margin-top: auto`.
- **Right column**: `flex: 1`, `display: flex; flex-direction: column`. Status band is fixed at
  the top; the queue below it is the scroll container.
- Reference prototypes are drawn at 1180px wide. The design is fluid — the rail is fixed, the
  queue column absorbs all extra width.
- Minimum usable width ~1000px. Below that see *Responsive* at the end.

---

## Typography

Two families, three roles. **Never mix them within a single line.**

| Role | Family | Usage |
|---|---|---|
| Display | **Cardo** (400, 700) | Wordmark, status headline, section labels, the live transcript excerpt, primary button label |
| Interface | **IBM Plex Sans** (400, 500, 600) | Every control, label, description, error message, secondary button |
| Data | **IBM Plex Mono** (400, 500) | File names, durations, counts, paths, column headers, version string |

All three are on Google Fonts. Cardo was chosen over Cinzel/Cormorant/Marcellus specifically
because it has a **full polytonic Greek character set** — if Greek text ever appears in the
interface, it will render correctly in the same face.

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cardo:wght@400;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
```

For a fully offline app, **self-host these** — download the woff2 files and ship them with the
app rather than fetching from Google. An offline-first tool should not make network requests
for fonts. Fallback stacks: `Cardo, Georgia, serif` · `'IBM Plex Sans', system-ui, sans-serif` ·
`'IBM Plex Mono', ui-monospace, monospace`.

### Type scale

| Token | Size | Weight | Tracking | Family | Used for |
|---|---|---|---|---|---|
| `display-lg` | 25px | 400 | 0.02em | Cardo | Status headline ("Transcribing") |
| `wordmark` | 20px | 400 | 0.19em | Cardo | TERTIUS, uppercase |
| `excerpt` | 15px | 400 | 0 | Cardo | Live transcript line, `line-height: 1.65` |
| `section` | 13px | 400 | 0.22em | Cardo | SOURCE / SETTINGS / RUN, uppercase |
| `numeral` | 14px | 400 | 0 | Cardo | Step numerals |
| `button-lg` | 16px | 400 | 0.13em | Cardo | Primary run button, uppercase |
| `body` | 13px | 400 | 0 | Plex Sans | Default UI text |
| `body-sm` | 12px | 400 | 0 | Plex Sans | Labels, states, secondary |
| `caption` | 11px | 400 | 0 | Plex Sans | Reassurance/help text, `line-height: 1.6` |
| `data` | 13px | 400 | 0 | Plex Mono | File names |
| `data-sm` | 12px | 400 | 0 | Plex Mono | Durations, counts |
| `data-xs` | 11px | 400 | 0 | Plex Mono | Paths |
| `overline` | 10px | 400 | 0.14em | Plex Mono | Column headers, footer — uppercase |

---

## Design Tokens

### Dark mode (default)

| Token | Hex | Use |
|---|---|---|
| `bg` | `#12100E` | App background, queue column |
| `bg-raised` | `#171411` | Left rail, active queue row, cards |
| `bg-sunken` | `#0F0D0B` | Input fields |
| `border` | `#2E2822` | Structural borders (rail edge, band bottom) |
| `border-subtle` | `#221E1A` | Section dividers inside the rail |
| `border-row` | `#1C1916` | Queue row separators |
| `border-control` | `#3A332C` | Secondary button borders |
| `text` | `#EDE7DE` | Primary text |
| `text-2` | `#9C9187` | Secondary text, values |
| `text-3` | `#6E655C` | Labels, muted |
| `text-4` | `#4F4740` | Disabled, em-dashes, overlines |
| `accent` | `#C8794E` | Brand, active state, progress, primary button |
| `accent-mute` | `rgba(200,121,78,.42)` | Secondary rule in the logo |
| `success` | `#6FA396` | Done |
| `danger` | `#B5544B` | Failed |
| `danger-bg` | `rgba(181,84,75,.05)` | Failed row background |
| `paused` | `#7A6E60` | Paused dot |
| `paused-bar` | `#4F4740` | Paused progress fill |

### Light mode

| Token | Hex | Use |
|---|---|---|
| `bg` | `#FBF8F2` | App background, queue column |
| `bg-raised` | `#F4F0E8` | Left rail, active queue row |
| `bg-sunken` | `#FBF8F2` | Input fields (border carries them) |
| `border` | `#DED7C9` | Structural borders |
| `border-subtle` | `#E1DACB` | Section dividers |
| `border-row` | `#E7E1D5` | Queue row separators |
| `border-control` | `#C9C0AE` | Secondary button borders |
| `text` | `#221E19` | Primary text |
| `text-2` | `#6B6259` | Secondary text |
| `text-3` | `#8A8175` | Labels, muted |
| `text-4` | `#A79E90` | Disabled, em-dashes |
| `accent` | `#A85A32` | Brand, active state, progress, primary button |
| `accent-mute` | `rgba(168,90,50,.38)` | Secondary rule in the logo |
| `success` | `#3E7A6E` | Done |
| `danger` | `#9C463D` | Failed |
| `danger-bg` | `rgba(181,84,75,.06)` | Failed row background |
| `on-accent` | `#FBF8F2` | Text on accent-filled buttons |

Note the accent **darkens** in light mode (`#C8794E` → `#A85A32`) to hold contrast on parchment.
Success and danger shift too. Every semantic color has both values; don't reuse a dark-mode hex
on light.

### Other tokens

- Radius: `3px` (badges) · `4px` (inputs, buttons, chips) · `6px` (outer shell, panels) ·
  `9px / 14px / 19px` (app icon at 40 / 64 / 88px) · `50%` (status dot)
- Spacing scale in use: `5, 6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 26, 28, 32, 36, 40`
- Rail section padding: `20px 22px`
- Queue row padding: `14px 26px` (`16px 26px` for the expanded active row)
- Status band padding: `22px 26px 20px`
- **No shadows anywhere.** Depth comes from background steps and 1px borders only. This is
  deliberate — shadows read as "web app" and break the inscribed feeling.

---

## Component Specs

### 1. Brand block (top of rail)

`padding: 20px 22px 18px`, bottom border `border`, `display: flex; align-items: center; gap: 13px`.

- **Logo mark** 32×32 (see *Logo* below)
- **Stack**: `TERTIUS` in Cardo 20px / 0.19em / uppercase, then `OFFLINE TRANSCRIPTION` in
  Plex Mono 10px / 0.12em / uppercase / `text-3`. `gap: 3px`.
- **Theme toggle** pushed right with `margin-left: auto`. Two segments, `padding: 5px 9px`,
  11px, in a 1px `border` container with `border-radius: 4px; overflow: hidden`. Active segment:
  `#2E2822` bg / `text` fg (dark) or `#E7E0D2` bg / `text` fg (light). Inactive: `text-3`.

### 2. Section headers (Source / Settings / Run)

`display: flex; align-items: center; gap: 9px`:
numeral in Cardo 14px `accent` → label in Cardo 13px / 0.22em / uppercase / `text-2` →
`flex: 1` hairline rule in `border-subtle`.

**Numerals**: the design supports two modes, controlled by one setting.
- Greek: `Αʹ` `Βʹ` `Γʹ` (alpha/beta/gamma with keraia, U+0374)
- Arabic: `1.` `2.` `3.`

The current default is **Arabic**. Expose the Greek option somewhere quiet in preferences if you
like, or hardcode Arabic — but keep them as a single switch, never mixed.

### 3. Source section

- Path row: `display: flex; gap: 8px`. Field is `flex: 1`, `padding: 8px 10px`, `bg-sunken`,
  1px `border`, radius 4, Plex Mono 12px `text-2`, with `white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis`. **Browse** button: `padding: 8px 12px`, 1px `border-control`,
  radius 4, 12px.
- Options row: `display: flex; align-items: center; gap: 16px`, 12px `text-2`.
  Checkbox is a 14×14 `accent` square, radius 3, with a 10px checkmark in `bg` (dark) /
  `on-accent` (light). Trailing hint: `or drop files here` where "drop files here" is an
  accent-colored link with a 40%-opacity underline.
- The whole rail is also a **drop target** — see *Interactions*.

### 4. Settings section

A two-column grid: `grid-template-columns: 78px 1fr; gap: 10px 12px; align-items: center`,
12px. Left column labels in `text-3`.

- **Model** and **Language**: select-styled rows — `padding: 7px 10px`, `bg-sunken`,
  1px `border`, radius 4, `display: flex; justify-content: space-between` with a `⌄` chevron in
  `text-3`. Use a real `<select>` styled to match, not a custom dropdown.
- **Device**: three equal segments (`auto` / `cpu` / `cuda`), `display: flex; gap: 6px`, each
  `flex: 1`, `padding: 6px 0`, centered, radius 4. Selected: 1px `accent` border + `text`.
  Unselected: 1px `border` + `text-3`. Disable `cuda` when unavailable rather than hiding it.
- **Write**: four multi-select chips (`.txt` `.srt` `.vtt` `.json`), `gap: 6px`,
  `padding: 6px 11px`, Plex Mono, radius 4. Same selected/unselected treatment as Device.
  At least one must stay selected.
- **Output**: read-only path row, Plex Mono 11px, ellipsised from the left if possible
  (`…\Documents\Tertius\out`).

### 5. Run section

State-dependent:

- **Idle** → one full-width primary button: `padding: 12px 0`, `accent` fill, `bg` text (dark) /
  `on-accent` (light), radius 4, Cardo 16px / 0.13em / uppercase. Label carries the count:
  `BEGIN — 12 FILES`. Disabled when the queue is empty (`opacity: .4`, no pointer events).
- **Running / Paused** → two equal secondary buttons side by side, `gap: 8px`,
  `padding: 11px 0`, 1px `border-control`, radius 4, 13px. `Pause` (or `Resume`) in `text`,
  `Cancel` in `text-2`.
- **Finished** → one primary button, `BEGIN AGAIN`.

Below the buttons, always: `caption` in `text-3`, `line-height: 1.6`.
Idle: *"Nothing leaves this machine. Estimated 2 h 05 m on this hardware."*
Running: *"Nothing leaves this machine. You may close the tab; the scribe keeps working."*
This line is the app's core promise — keep it visible in every state.

### 6. Rail footer

`margin-top: auto`, `padding: 14px 22px`, top border `border-subtle`,
`display: flex; justify-content: space-between`, `overline` in `text-4`:
engine name left (`faster-whisper`), app version right (`v0.9.2`).

### 7. Status band

The single most important element — it carries the whole job. `padding: 22px 26px 20px`,
bottom border `border`.

Row 1 (`display: flex; align-items: baseline; gap: 12px`):
1. **Status dot** — 7×7, `border-radius: 50%`
2. **Headline** — Cardo 25px
3. **Counter** — Plex Mono 13px `text-2`
4. **Right slot** — `margin-left: auto`: either metadata in Plex Mono 12px `text-3`, or a button

Row 2 (`margin-top: 16px`): **progress bar**, 3px tall, `border-subtle` track, radius 2,
`overflow: hidden`, accent fill. Width animates with `transition: width 400ms ease-out`.

Row 3 (`margin-top: 14px`, running/idle only): **stat strip**, `display: flex; gap: 26px`, 12px.
Each stat is a `text-3` label followed by a `text` value in Plex Mono.

#### The five states

| State | Dot | Headline | Counter | Right slot | Bar |
|---|---|---|---|---|---|
| **Idle** | 1px `text-4` ring, hollow | `Ready to write` | `12 files gathered` | `6 h 42 m of audio` | empty track |
| **Running** | `accent`, pulsing | `Transcribing` | `5 of 12` | `≈ 18 min remaining · 3.1× realtime` | `accent`, animating |
| **Paused** | `paused` solid | `Paused` in `text-2` | `5 of 12 · stopped at 41:20 mark` | **Resume** button, 1px accent border, accent text, `padding: 6px 14px`, radius 4, 12px | `paused-bar` fill, frozen |
| **Complete** | `success` | `The batch is finished` | `12 of 12 · 2 h 04 m elapsed` | **Open output folder**, accent fill | full `success` |
| **Complete w/ failures** | `danger` | `Finished with one failure` | `11 written · 1 unreadable` | **Retry failed**, 1px `border-control` | split: `success` to the success %, `danger` for the rest |

Pulse animation, running state only:
```css
@keyframes pulse { 0%, 100% { opacity: 1 } 50% { opacity: .45 } }
/* animation: pulse 1.6s ease-in-out infinite; */
```
Respect `prefers-reduced-motion: reduce` — drop the pulse and the bar transition.

Headline copy is **sentence case and slightly formal** — "The batch is finished", not
"Complete!". Never exclamation marks, never cute. Pluralize honestly:
"Finished with one failure" / "Finished with 3 failures".

On **Complete**, the stat strip is replaced by a fuller summary row:
Elapsed · Audio · Average · Words, same visual treatment.

### 8. Queue

**Column header** — `padding: 14px 26px 10px`, `display: flex; gap: 22px`, bottom border
`border-subtle`, `overline` in `text-4`:
`File` (`flex: 1`) · `Length` (120px) · `State` (130px) · `Output` (96px).
All rows use these exact widths so the columns line up.

**Standard row** — `padding: 14px 26px`, `display: flex; align-items: center; gap: 22px`,
bottom border `border-row`.
- File name: Plex Mono 13px. `text-2` for done/queued rows, `text-3` for not-yet-reached rows.
- Length: Plex Mono 12px `text-3`.
- State: 12px. `Waiting` / `Queued` in `text-3` · `Done · 11:02` in `success` (the time is how
  long transcription took, not the audio length) · `Skipped · exists` in `text-3` with the whole
  row at `opacity: .55` · `Failed` in `danger`.
- Output: `display: flex; gap: 8px`, Plex Mono 12px accent links (`txt`, `srt`, …), one per
  written format; clicking opens that file. `—` in `text-4` when there's no output.

**Active row** (the file currently being transcribed) — expanded:
`padding: 16px 26px`, `bg-raised`, **2px left border in `accent`**,
`display: flex; flex-direction: column; gap: 11px`. Three stacked parts:

1. The standard row content, with State reading `Transcribing 62%` in `accent`.
2. **Waveform** — `display: flex; align-items: center; gap: 2px; height: 30px`. ~60 bars,
   3px wide, radius 2, heights 4–28px. Bars left of the playhead are `accent`; bars right of it
   are `#332C26` (dark) / `border` (light). Generate from the actual decoded audio if you have
   it; a deterministic pseudo-random envelope keyed off the file is an acceptable stand-in.
   This is a **progress indicator**, not a player — it is not clickable.
3. **Live excerpt** — Cardo 15px, `text-2`, `line-height: 1.65`, wrapped in curly quotes,
   showing the last ~30 words emitted. This is what makes the app feel alive; keep it. Give it
   a fixed 2–3 line height so rows below don't jump as text streams in.

**Failed row** — `align-items: flex-start`, `danger-bg` background. The File cell becomes a
column (`gap: 5px`): file name in `text`, then the error message in 12px `danger` with an
inline **Retry** in `text-2` underlined with `border-control`. Error copy names the actual
cause: *"Unreadable audio stream — codec not supported."*

**Ordering**: the active row sits at the top of the queue, completed above/below in completion
order, pending in queue order at the bottom. In the idle state, show the plain list in queue
order with a `…and six more.` line in italic `text-4` if truncated.

---

## Logo

A **tau standing on two ruling lines** — the guide lines a scribe scored into a page before
writing a word. It is a letterform and a piece of page furniture at once. It is not a cross:
the crossbar sits at the very top of the stem, the second rule is a separate, lighter, inset
element, and the proportions are those of a Greek Τ.

### Construction, on a 100-unit square

| Element | x | y | w | h | Fill |
|---|---|---|---|---|---|
| Crossbar | 0 | 9 | 100 | 9 | `accent` |
| Second rule | 12 | 29 | 76 | 9 | `accent-mute` |
| Stem | 42 | 9 | 16 | 91 | `accent` |

The second rule is shorter, inset 12u on each side, and lighter (42% accent in dark, 38% in
light) so it reads as *ruling* rather than as a second stroke of the letter.

### SVG

```svg
<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Tertius">
  <rect x="0"  y="9"  width="100" height="9"  fill="currentColor"/>
  <rect x="12" y="29" width="76"  height="9"  fill="currentColor" opacity="0.42"/>
  <rect x="42" y="9"  width="16"  height="91" fill="currentColor"/>
</svg>
```

Reduced form for ≤ 24px — drop the second rule entirely:

```svg
<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Tertius">
  <rect x="0"  y="9" width="100" height="9"  fill="currentColor"/>
  <rect x="42" y="9" width="16"  height="91" fill="currentColor"/>
</svg>
```

Ship both; swap at 24px. The favicon and any 16px use gets the reduced form.

### Rules

- **Clear space** on all sides = the stem width (16u). Nothing intrudes.
- **Minimum sizes**: 24px for the full mark, 16px for the reduced mark.
- **Colorways**: accent on `bg-raised` · accent on parchment · `bg` knocked out of an accent
  tile (app icon) · single-color `text` · single-color black. Never on a photo, never gradient,
  never outlined, never rotated, never restretched — the 16:91 stem ratio is fixed.
- **App icon**: accent tile with the mark in `bg`, mark occupying ~55% of the tile, corner
  radius ≈ 21% of the tile (19px at 88px, 14px at 64px, 9px at 40px). At 512 and 1024 the tile
  is `#C8794E` with the mark in `#12100E`; the second rule becomes `rgba(18,16,14,.45)`.
- **Favicon**: reduced mark, accent on transparent, 32 and 16.

### Lockups

- **Horizontal** (default, used in the rail): mark at 32–36px, `gap: 13–14px`, then a stack of
  `TERTIUS` (Cardo, 0.19em, uppercase) over the mono overline. Baselines are not aligned — the
  mark is vertically centered against the whole stack.
- **Stacked** (splash / about): mark 40px centered above `TERTIUS` in Cardo 15px / 0.24em,
  `gap: 9px`.
- Tagline, where one is wanted: **The scribe who wrote it down** — Plex Mono, 9–10px, 0.22em,
  uppercase, `text-3`. Optional; drop it below 200px lockup width.

---

## Interactions & Behavior

**Hover** — the design has no hover state in the reference (it's a static mock), so define:
- Buttons and chips: border steps to `text-3` (dark) / `text-2` (light), 120ms ease.
- Queue rows: background to `bg-raised` at 50% opacity. The active and failed rows don't change.
- Links (`txt`, `srt`, `Retry`, `drop files here`): lighten one step, underline to full opacity.
- Never move anything on hover — no lift, no scale.

**Focus** — every interactive element needs a visible keyboard focus ring: 2px `accent` outline
with 2px offset. Do not remove outlines. The whole app must be operable from the keyboard.

**Drag & drop** — the entire window accepts audio files. While dragging over it, show a 2px
dashed `accent` inset border on the queue column and change the idle headline to
`Release to add`. Rejected file types get a brief `danger` flash on the drop area.

**Starting a run** — the Run section swaps to Pause/Cancel, the band moves to Running, the first
queued row becomes the active row. No modal, no confirmation.

**Pausing** — finishes the current *segment*, not the current file, then freezes. The band's
counter records the mark it stopped at so Resume is honest about where it picks up.

**Cancelling** — this one *does* confirm, since partial work is lost. Inline confirmation in the
Run section, not a modal: *"Cancel the remaining 7 files?"* with `Cancel run` / `Keep going`.

**Completion** — no toast, no sound. The band changing to `The batch is finished` is the
notification. If the tab is backgrounded, update the document title to `✓ Tertius — finished`.

**Errors** — never block the batch. A failed file goes red in place, the run continues, and the
final band reports the count. Retry re-queues that one file at the end.

**Transitions** — progress bar width 400ms ease-out; row state changes 150ms; theme switch is
instant (no cross-fade, it looks cheap). Nothing else animates.

**Persistence** — remember theme, last source folder, model, device, output formats, and output
folder between sessions. Restore an interrupted run's completed-file list on relaunch so the
user isn't asked to redo finished work.

---

## State Management

```
theme            : 'dark' | 'light'          — persisted, default 'dark',
                                               initialised from prefers-color-scheme on first run
numerals         : 'arabic' | 'greek'        — persisted, default 'arabic'
sourcePath       : string
includeSubfolders: boolean                    — default true
model            : string                     — default 'large-v3-turbo'
device           : 'auto' | 'cpu' | 'cuda'    — default 'auto'
language         : string | 'auto'            — default 'auto'
formats          : Set<'txt'|'srt'|'vtt'|'json'>  — default {txt, srt}, min 1
outputPath       : string
skipExisting     : boolean                    — default true

runState         : 'idle' | 'running' | 'paused' | 'complete'
queue            : QueueItem[]
activeId         : string | null

QueueItem {
  id, fileName, path,
  durationSec,
  status: 'queued' | 'running' | 'done' | 'failed' | 'skipped',
  progress: 0..1,
  elapsedSec,            // set on done
  errorMessage,          // set on failed
  outputs: string[],     // written file paths
  waveform: number[],    // 60 normalised amplitudes
  excerpt: string        // last emitted text, running only
}
```

Derived for the band: counts by status, overall progress (weight by **duration**, not file
count — a 72-minute audiobook chapter is not one twelfth of the work), ETA from a rolling
realtime-factor average of completed files, total audio duration, total words.

Transitions: `idle →(begin)→ running →(pause)→ paused →(resume)→ running`;
`running →(last file settles)→ complete`; `paused|running →(cancel, confirmed)→ idle`;
`complete →(begin again)→ running`.

Progress and excerpt updates arrive continuously from the transcription worker — throttle
renders to ~10/sec so the excerpt doesn't thrash.

---

## Accessibility

- Contrast: all specified pairings meet WCAG AA for their size. Do not lighten `text-3` further
  on dark or you'll lose it.
- The status dot is decorative — status must also be conveyed in text (it is, in the headline).
  Same for queue rows: never color-only.
- Status band changes should fire an `aria-live="polite"` announcement.
- The progress bar needs `role="progressbar"` with `aria-valuenow`.
- Waveform is decorative: `aria-hidden="true"`.
- Honor `prefers-reduced-motion`.

---

## Responsive

Desktop-first; this is a local tool in a browser tab.

- **≥ 1180px** — as designed.
- **1000–1180px** — rail stays 352px, queue column compresses. Drop the `Length` column first,
  then shorten the band's right-slot metadata.
- **< 1000px** — rail collapses to a full-width block above the queue, sections becoming a
  single row of summarised values with an `Edit setup` link (there's a sketch of this collapsed
  bar in the earlier `1b` exploration in the reference file). Low priority.

---

## Assets

No images, photographs, or icon fonts. Everything is type, rules, and the one SVG mark, all of
which are specified above. The `⌄` chevron and `✓` checkmark are text characters — swap them for
1px-stroke SVG paths if they render inconsistently across platforms.

---

## Files

- `Tertius.dc.html` — the design reference. **Turn 4 (`4a`, `4b`, `4c`) at the top of the
  document is the approved design.** Turns 3, 2, 1 below it are prior explorations; ignore them.
  - `4a` — dark mode, running state, full app
  - `4b` — light mode, finished-with-one-failure state, full app
  - `4c` — logo construction grid, icon sizes, lockups
  - `2c` (earlier turn) — all five status-band states stacked, including **paused**, which is
    the only place that state is drawn. Worth a look; its typography is one iteration old
    (Cinzel instead of Cardo) but the layout and colors are current.
- `support.js` — runtime needed to open the reference in a browser. Not part of the design.
- `screenshots/`
  - `4a-dark-transcribing.png` — **approved** dark mode, running
  - `4b-light-finished.png` — **approved** light mode, finished with one failure
  - `4c-logo-and-icons.png` — **approved** logo construction, icon sizes, lockups
  - `2c-status-band-all-states.png` — all five band states incl. paused *(typography one
    iteration old — Cinzel, not Cardo; layout and colors are current)*
  - `2a-dark-idle.png` — idle state, full app *(same caveat: Cinzel, not Cardo)*

To view: open `Tertius.dc.html` in a browser with both files in the same folder.
