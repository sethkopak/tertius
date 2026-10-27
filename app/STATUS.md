# Tertius — status

Last updated: 2026-10-27

## Where it stands

Working, and in real use. Built from `design/original-spec.md`, plus everything
requested since: the launcher, folder picker, model download progress, model
comparison + machine check, tooltips, light/dark theme, mirrored output folders,
timestamping of supplied text, the designed UI, macOS/Linux support,
translation, and reading text aloud.

**804 tests, all passing** on Windows locally (one skips, a librosa path).
The Hebrew work of 2026-10-26/27 (`0d8c778`..`604139a`) passed CI on all
eight jobs.
The 2026-10-24 same-sound spellings (`9b901fe`) passed CI on all eight jobs.
The 2026-10-21 evening changes (`642fe18`, `ef27871`, `ce33f3e`) passed CI on
all eight jobs.
The 2026-10-21 dot-reference fix (`e6a4ce2`) passed CI on all eight jobs.
The 2026-10-21 changes passed CI on all eight jobs.
The 2026-10-20 verse-number and dropped-clause changes passed CI on all eight jobs.
The Chinese round-trip changes (second 2026-10-19 entry) passed CI on all eight jobs.
Green in CI on all eight jobs for the first 2026-10-19 changes: 615-616 passed with
5-6 skipped. That is two more skips than before, and they are the two new T5
loader tests, which need torch and transformers, neither installed on the
runners. So the madlad fix is tested only on this machine.

> Corrected 2026-09-29. This said all 558 passed on ubuntu/macOS/Windows in CI
> too. CI had been **red on every platform since `5ef33ea` (2026-09-21)**, all
> seven jobs, on one test:
> `test_the_fetcher_asks_for_the_languages_the_translator_supports`. It
> compared the book-name fetcher's languages against the translator's, and the
> translator reads its list from a *converted* model's vocabulary - empty on a
> runner that has never converted one. It passed here because this machine
> has. It now skips when there is no vocabulary to compare with, and still
> checks the book count either way. Found when Tertius Online vendored the
> package and its CI went red with it.

Whisper is mocked throughout, and so are the translator and the speech
model — the suite downloads nothing, decodes no audio, generates no audio and
converts no checkpoints, which is what makes it safe to run on a hosted
runner.

Run it: double-click `Start Tertius.bat` (Windows), `Tertius.app` (macOS), or
run `./start-tertius.sh` (Linux).

Repo: `github.com/sethkopak/tertius`, **public, MIT**, branch `main`. That
is not just a licence change: a dependency that costs *you* one click costs
every stranger who clones it the same click, and they have no reason to
trust it. See *Diarization* below, where it decides the design. Translation
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
- **Reads a text file aloud** (2026-09-18), offline, in a voice sampled from a
  recording you supply. Three Chatterbox models, all MIT and none of them gated
  on the Hub. Writes a `.wav`, and an `.srt` whose timings are *measured*
  against the audio as it is generated rather than estimated — the one place
  here where a cue cannot have drifted from its recording. Style tags in the
  text (`[solemn]`, `[emphatic]`, …) change delivery from where they appear.
  Run for real on the GPU at **0.51x realtime** — slower than realtime, and
  about forty times dearer per minute than transcribing. **A Russian speaker
  has listened to a Russian reading and says it sounds good**; Chinese has been
  run and heard only by someone who does not speak it.
- **Speaks a translation, not just a text file** (2026-09-19). The stages are a
  pipeline - transcribe, then translate, then speak - so asking for Hebrew
  audio from an English recording is one job. The voice is sampled from the
  recording itself unless you name a clip.
- **Several languages in one run** (2026-09-20), with a separate, narrower list
  for what gets read aloud: the translator knows a hundred languages and the
  voice model twenty-three, and the two lists are kept in step in both
  directions. A second translation costs ~17s; a second *reading* costs another
  full pass, and speech dominates the bill.
- **Digits are spelled out before they are spoken** (2026-09-20). Chatterbox
  reads an Arabic numeral in English or not at all, so `66` becomes
  `שישים ושש` on the way to the model while the cues keep the digits.
  Working in 18 of the 23 speakable languages, tested by trying rather than by
  reading a table of what is advertised.
- **Scripture references are held back whole** (2026-09-20) and named from a
  table (2026-09-21) rather than translated. A model rewrites both halves of a
  citation: measured, 25 of 66 Russian book names came back as a different book
  - Job as "Work", Lamentations as "Please". The names come from Wikidata
  (CC0), shipped as data; a book the table cannot name stays in English rather
  than being guessed. **Fitted to the sentence** (2026-09-29): a full stop the
  model drops after a closing citation is put back, a Hebrew prefix is joined
  to the name (`בתהילים`), and a Russian name takes the case its preposition
  or verb governs (`в Псалтири`, `Сравнить Книгу Иова`).
- **Hebrew gets its vowel points back before it is spoken** (2026-09-21).
  Hebrew is written without vowels and Chatterbox guesses them, badly enough
  that the words change - `תהילים 66:8,9` was read as a non-word followed by
  "sixty-eight". The model class is vendored from a CC-BY-4.0 source rather
  than loaded with `trust_remote_code`, and runs on the CPU.

## 2026-10-27 (later) — the gated refill on Chinese: nothing to refill

Chinese was left out of the refill when it took 2.0% to 2.8% with invented
text in the gaps. Tried again with the loudness gate, on the same thirty
readings (`h_spoken3`, `--takes 3`), gap refill only - the slow-segment pass
and the three-word floor count words by spaces, which Chinese does not have:

- The main pass came back **byte-identical** to the 2.0% run in all thirty.
- It left 31 gaps. 30 were 0-9% speech-loud, so the gate skipped them; one,
  0723 take 1 at 27.4-32.7 s, was 44%, and its decode brought back nothing
  inside the gap.
- **2.0% (152/7569)**, as before, and no stretch of six or more characters
  lost in any file. Whisper is not skipping speech in these readings, so
  there is nothing for the refill to bring back.

So the gate would make the refill harmless for Chinese, but there's no
evidence that it helps. `REFILL_LANGUAGES` stays Hebrew and English. Whisper's
figures, not a listener's.

## 2026-10-27 — English transcription against the book: 1.61% to 1.16%

> **PyAV capped below 19** (`requirements.txt`, `pyproject.toml`). CI went red
> on the four Python 3.13/3.14 jobs at `e256419`: they installed PyAV 19.0.2,
> and faster-whisper 1.2.1 - the latest - opens every file with
> `av.open(..., metadata_errors="ignore")`, an argument PyAV 19 removed. So a
> fresh install today could not transcribe anything; the suite mocks Whisper
> and never noticed until the loudness test below decoded real audio. The
> 3.11 jobs got PyAV 18.1.0 and passed; this machine has 18.0.0.

All 375 Manna recordings transcribed with the app's settings and scored
against the book (366 have a page): the verse, the comment and the verse
again, both sides without scripture references, the title and "The text
again" (worded differently on purpose), the comments' source codes
(`Z.'95-107 R1807:4`) taken out wherever they are, digits spelled. Word
error rate. Every figure here is Whisper's against the printed text, so a
reader departing from the book counts as an error too.

**Before: 1.61% (928/57516)**, median file 0.7%, 142 files word-perfect,
19 runs of four or more book words missing. Most of those were whole verses,
the gap refill already on. They went a second way: **a segment whose
timestamps swallow what it does not write.** `The text again` ran 60.2-90.2 s
in an 83.8 s file, the verse after it gone (0421, 0428); opening segments of
13-18 s held one sentence, the title and verse before it gone (0513, 0725,
0730). No gap, so the refill never looked.

**Fixed: a segment of 6 s or more at under one word a second is decoded
again** (`transcribe._slow`; reading runs about 2.5 a second). 13 segments in
the 375 files, every one in a file missing text. Three decodes are tried -
the whole span, the part before what its text accounts for (at 2.5 words a
second), the part after - and the one with the most words replaces the
segment if it adds three or more. A partial decode keeps the old text on its
side, and drops pieces mostly made of the old text's words, since the
estimate can be short (0728 and 0828 came back doubled before that). Per
file, errors before and after:

| | 0409 | 0421 | 0424 | 0428 | 0504 | 0513 | 0628 | 0725 | 0728 | 0730 | 0819 | 0828 | 0908 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Before | 23 | 53 | 14 | 42 | 21 | 15 | 10 | 19 | 13 | 12 | 12 | 10 | 27 |
| After | 3 | 2 | 1 | 2 | 4 | 0 | 0 | 1 | 4 | 1 | 13 | 4 | 8 |

**After: 1.22% (700/57516)**, 144 files word-perfect, none over 10%, seven
runs of four or more missing. None of the seven has a gap or a slow segment
near it (0520, 0805, 0827, 1208 twice, 1213): likely the reading differs from
the book; not checked. Hebrew and English only, like the refill; the thirty
Hebrew readings scored exactly as before (567 letters) - it never fired
there. 3 tests.

**Three more openings, and the line moved to 1.3 words a second.** The
seven runs still missing, each stretch decoded again on its own and with
beam 1:
- **0520, 0827, 1213: in the audio.** The opening title and verse were
  inside a first segment of 13.5-17 s at about 1.2 words a second, just over
  the line. At 1.3 they came back: errors 7, 8, 9 to 1, 3, 2. One other
  segment in the 375 files runs between 1.0 and 1.3 (0608, 6.8 s), and
  decoding it again changed nothing. Hebrew's thirty readings: unchanged.
- **0805, 1208: the reader, not Whisper.** The book has "to them who are the
  called"; the reading says "to them that love God, the called". 1208's
  reader paraphrases. Neither decode hears the book's words.
Two of the recovered openings came back lowercase and unpunctuated (`manna
for may 20th a peculiar people...`), and 0520 doubles one word (`a A
peculiar`): the words are right, the look is not.

**Now 1.19% (682/57516)**, 144 files word-perfect, none over 10%, and the
four runs of four or more missing are the reader's.

**What the 1.19% is** (each differing stretch given one kind, at 1.22%):

| Kind | Share of words | |
|---|---|---|
| Other | 0.61% | below |
| Small words | 0.22% | `or` added 24 times, `the` and `a` dropped |
| Spacing | 0.20% | `every one`→`everyone` ×8, `corner stone`, `co operation` |
| Spelling | 0.11% | `fulfil`, `offence`, `acknowledgment`, `alway` |
| Runs missing | 0.08% | now the reader's only |

Without spacing, spelling and small words, **0.70%**, and "other" is mostly
not mishearing either: `text again` and spoken references the scorer did not
strip, the book's own words read another way (`viz` read "namely", `diaglott`,
the book's typo `mattthew`), and King James forms (`shewed`, `stablish`).
**One real thing in it: "Thank you" at the end of six transcripts**,
Whisper's text on the closing silence. The scripts are in a session
scratchpad.

**The closing "Thank you", and refills cased and gated.** Three changes,
each measured on all 375 recordings:
- **Text on the closing silence is dropped.** Eight transcripts ended in a
  segment nobody said - `Thank you.` six times, `We'll be right back.`,
  `Here we go.` - each starting within the last second of the audio, stamped
  30 s past its end, over audio at about a fiftieth of the speech's
  loudness. A segment starting within 1.5 s of the end and running more than
  a second past it is dropped (`_closing_filler`); 0719's real closing verse,
  1.4 s past the end, began 5.7 s before it and stays. Never fired on the
  Chinese or Hebrew readings; their scores are unchanged.
- **What is decoded again is prompted for punctuation, and decoded without
  too.** Whisper picks its style per decode: 0520's opening from 0.08 s came
  back `manna for may 20th a peculiar people...`, from 0.10 s cased. A
  punctuated prompt (`The following is a transcript, with punctuation.`)
  set it every time - but 0317's verse, decoded with the prompt, came back
  as its citation alone stretched over 20 s, every time, and whole without
  it. So each stretch is decoded both ways and the one with more words kept,
  the prompted one on a tie. (The reading's neighboring sentence as a prompt
  was tried first: Whisper left out whatever matched it.)
- **A gap is decoded again only if it holds speech.** Decoded both ways,
  0412's silent 1.7 s pause came back `Oh, my God.` and `That's the thing.`
  Speech-loud 0.1 s frames (over a third of the file's 75th-percentile
  loudness): the seven real recoveries, English and Hebrew, 46-70% of their
  gap; the invented ones 0-37%. A gap needs 40% (`SPEECH_SHARE`). The margin
  is thin - one invented Hebrew gap was 37% - but that one was also outside
  its gap in time, which the earlier check catches.

**Now 1.16% (665/57516)**, 146 files word-perfect, none over 10%; the only
runs of four or more missing are the reader's (0805, 1208). Hebrew's thirty
readings: 3.4% of letters, 1.9% by sound, as before.

**Whisper's main pass is not repeatable between runs.** 0317's verse was
heard in one full run of the 375 and skipped in the next, same code and
settings; and one full run against the next, unchanged files scored the
same except where a change touched them. Figures here are single full runs;
a difference of a few errors in one file is within that.

## 2026-10-26 — Hebrew, measured the way Chinese was

Goal: Hebrew listeners understand the Hebrew reading of an English Manna, and
the Hebrew translates back to English well. There is no Hebrew speaker, so
**every figure here is Whisper's (large-v3-turbo, as the app runs it), not a
person's.**

**The harness is now `tools/harness.py --lang zh|he`**; `zh_harness.py` is a
wrapper so the commands above still run. Rescored through it, the Chinese
runs come out exactly as recorded: 152/7569, 188/7569, 77/2523 raw. A new
`back` stage translates what Whisper heard into English with the app's
translator and scores it against the English transcript: chrF, scripture
references right, and whether the title's month survived.

**Hebrew scoring.** The reference is the translation in spoken form
(`numbers.spell`), as for Chinese. Both sides lose vowel points,
cantillation, geresh, punctuation and Latin, and final letters are folded
(ך→כ ...), since Whisper writes unpointed Hebrew and none of that is heard;
digits Whisper writes are spelled the same way the reading spells them.
- **letters**: letters heard wrong, spaces ignored, so a prefix written apart
  (`ב תהילים`) or joined is not an error. Decisions rest on this one.
- **skeleton**: also drops ו and י except word-initially, so full and short
  spellings (תהילים / תהלים) match. It merges הוא and היא too, so it is
  shown, not used to decide.
- **words**: word error rate, for reading; prefixes make it harsh.
- Three or more reference words heard not at all are listed as lost.
- Not counted: `תודה רבה` ("thank you very much") at the very end, Whisper's
  text after the last reference in 3 of 30 baseline readings; and the gender
  of a number word (`שנים עשר` / `שתים עשרה`, both twelve). Whisper writes
  most numbers as digits, which the scorer spells back feminine, so a chapter
  read masculine and heard exactly (`פרק 12`) was scored as two errors -
  that alone made the next run look worse (5.1%) than the baseline. `--raw`
  counts both.

**Baseline** (madlad, the code as of `430c726`, the ten files' transcripts
reused from the Chinese runs, three takes): **4.5% of letters misheard**
(729/16146; raw 4.6%, 752/16203), skeleton 4.6%, words 12.4%. Whisper detected Hebrew in
all 30.

| File | Letters | Take 1 | Take 2 | Take 3 |
|---|---|---|---|---|
| 0120 | 4.0% | 4.7% | 4.3% | 2.8% |
| 0226 | 3.0% | 3.4% | 2.2% | 3.6% |
| 0403 | 2.9% | 2.9% | 3.1% | 2.7% |
| 0510 | 4.7% | 4.0% | 4.8% | 5.3% |
| 0616 | 5.3% | 5.2% | 5.0% | 5.9% |
| 0723 | 8.4% | 4.1% | 3.7% | 17.5% |
| 0829 | 2.7% | 0.5% | 6.0% | 1.6% |
| 1005 | 4.1% | 3.5% | 4.5% | 4.3% |
| 1111 | 4.0% | 3.6% | 4.1% | 4.3% |
| 1218 | 4.1% | 3.4% | 3.8% | 5.0% |
| **All** | **4.5%** | 3.6% | 4.1% | 5.8% |

- **Two takes left text out.** 0723 take 3 dropped its opening reference and
  the whole sentence after it; 0829 take 2 dropped its closing
  `איגרת יעקב 4:3`. Listening back is Chinese only, so nothing retook them.
- **madlad's title is `מנה`** ("portion", "serving") in all ten files; Google
  writes `מן`. Heard as `מנה` 24 times, `מנע` 4.
- **"The text again"** came out four ways (`ההודעה שוב`, "the message
  again", in five files), and in 1005 madlad put **invented Biblical Hebrew**
  in its place: `חז"ל מסבירים את הפסוק כך: "וַיְהִי הָאֱלֹהִים אֲשֶׁר לֹא
  יָדַעְתִּי אֶת הַשָּׁמַיִם..."` - the Psalm 66 failure recorded on 2026-10-19,
  on another file.
- **`האיגרת`** ("the epistle") was heard as `ההיגרת`, `הגרת`, `היגרת` - the
  same sounds - and often as `ההגלת` ("the exile"). 0510's Psalm 23:5, spoken
  `עשרים ושלוש:חמש`, was heard `20 ו-35` and `20 ל-35`: the colon problem
  Chinese had.
- 0723's `אנחנו חוזרים מיד` ("We'll be right back") is in the English
  transcript, not invented by madlad.
- Retakes: 33 for an abrupt ending, 3 chunks still abrupt after three;
  Chatterbox forced EOS on token repetition 123 times.

**Back to English: chrF 45.4, references right 0 of 60, title month kept 5
of 30.** Whisper writes Hebrew here with almost no punctuation (there is no
Hebrew hint), so madlad gets a whole reading as one sentence; and it heard
`האיגרת אל העברים 12:7` as `ההגלת היא לעברין 12-7`, which came back as "The
exile is for transgressors 12-7". The title came back "Appointment for
January 20".

The readings are in a session scratchpad and are not kept.

**Fix A: dates and references read as Google writes them** (`numbers.py`).
`num2words` read `ל-1 בינואר` as `ל-אחת בינואר`, the feminine counting form
after a hyphen, and `העברים 12:7` as `שתים עשרה:שבע`, two numbers and no word
for the colon. Google, asked to write them in words, gave `לשלושה ביוני`,
`לראשון ביוני` (masculine; "first" as an ordinal) and `האיגרת אל העברים, פרק
י"ב, פסוק י"א`. So a date is now `לעשרים בינואר`, and a reference after a
book name from the table is `האיגרת אל העברים, פרק שנים עשר, פסוק שבעה` (a
list `פסוקים שמונה ותשעה`), numbers in masculine words, not Google's letter
numerals. A range keeps its old reading: Google kept its digits. 7 tests.

Read again from the baseline's own translations, same seeds, three takes:

| | Baseline | Fix A |
|---|---|---|
| Letters misheard | 4.5% (729/16146) | **4.2%** (700/16566) |
| Per take | 3.6 / 4.1 / 5.8% | 3.9 / 4.3 / 4.5% |
| References heard with the right chapter and verse | 41/60 | **47/60** |
| References left out | 2 | 2 |
| Back to English: chrF | 45.4 | 48.2 |
| Back: references right | 0/60 | 6/60 |
| Back: title month kept | 5/30 | 3/30 |

- **The references are the gain.** Whisper heard them as Google writes them,
  `ההיגרת אל העברים, פרק 12, פסוק 7`; 0510's Psalm 23:5, heard `20 ו-35` in
  the baseline, was right in 6 of 6. (Counted as chapter, then verse, in
  digits within a few characters; 1111's 1:5 is heard as words, `אחת חמש`,
  and is undercounted the same in both.)
- 0.3 points of letters is inside take-to-take noise. Six files improved,
  0510 was level, 0226 (3.0% to 4.1%) and 0616 (5.3% to 5.5%) did worse, and
  **1218 went 4.1% to 10.9%**: Chatterbox left out its opening reference in
  two takes and a sentence in the third, with no retake (nothing listens back
  to Hebrew). The baseline lost two references the same way, in 0723 and
  0829. The third 1218 take read the reference.
- Dates moved both ways: 0403's `לשלושה באפריל` was heard right 3 of 3
  (the baseline's `לשלוש` heard the month wrong twice, `באפלין`, `באפרין`);
  0510's `לעשרה במאי` was heard `להסערה` ("to the storm") once.

Kept.

**Fix B: the title and "The text again" from Google** (`fixed_lines.py`):
`מן ל-20 בינואר.` and `הטקסט שוב:`, the way the Chinese lines are done, so
madlad sees only the rest of the sentence. Month names after ב: six as Google
wrote them, six as madlad did. "The text again" now starts a Hebrew chunk too
(`STARTS_A_CHUNK`). 5 tests. Translated again, with fix A, three takes:

| | Baseline | Fix A | Fix A + B |
|---|---|---|---|
| Letters misheard | 4.5% | 4.2% | **4.0%** (661/16512) |
| Per take | 3.6 / 4.1 / 5.8% | 3.9 / 4.3 / 4.5% | 3.5 / 4.3 / 4.2% |
| References, chapter and verse heard | 41/60 | 47/60 | 43/60 |
| `הטקסט שוב` heard | - | - | 29/30 |
| Back: chrF / references / title month | 45.4 / 0 / 5 | 48.2 / 6 / 3 | 46.6 / 3 / 5 |

- **1005's invented Biblical Hebrew is gone**: madlad got only the verse,
  and translated it. Apart from the fixed lines, one other line of the ten
  translations changed (0226, a long sentence reworded; same English).
- Text was left out again: 0616 takes 2 and 3 each have one of its two
  references, and 0723 take 2 lost "The text again" with the start of its
  verse. References are worded the same in A and B, so 47/60 to 43/60 is
  drops and take-to-take noise, not the change.
- **The title is now heard as `מין`** ("kind", "sex") in 21 of 30, `מן` in 6.
  The diacritizer points it `מִן`, "from", and ignores points it is given
  (`מָן` in, `מִן` out). madlad's `מנה` ("portion") was at least heard as
  itself, 24 of 30. Fixed below.

Kept.

**The title's `מן` pointed as manna** (`hebrew.POINTED_AS`, `set_points`).
After the model runs, `מן` before `ל<day> ב<month>` is set to `מָן`; any
other `מן` ("from") is left as the model points it. The model sometimes drops
a vowel letter as it points (`תסבול` → `תִּסְבֹּל`), so the word is found by
aligning letters. The first chunk of each of the ten files, three takes each
way, same voice and seeds (700+), no retakes, Whisper large, first word heard:

| | `מן` | `מין` | Other |
|---|---|---|---|
| `מִן` (the model's) | 5/30 | 15/30 | `מי` 4, `מלעשרים` 2, ... |
| `מָן` | **12/30** | **0/30** | `מען` 4, `מה` 3, `זמן` 2, `מענה` 2, ... |

Most of the rest of `מָן` is a "man" sound written another way; "min" is
gone. 2 tests. The test script is in a session scratchpad. Not yet in a
ten-file run.

**A Hebrew hint for Whisper** (`transcribe.PUNCTUATION_HINTS["he"]`):
`להלן משפטים בעברית.` (Google's "The following are sentences in Hebrew.")
and the words every Manna reading has - `מן, הטקסט שוב, האיגרת, תהילים, פרק,
פסוק.` - and no book of the ten test files. Whisper had written 0120 with
two full stops; with the hint, eight. Fix B's thirty readings heard again,
nothing else changed:

| | Without | With the hint |
|---|---|---|
| Letters misheard | 4.0% (661/16512) | **3.4%** (560/16512) |
| Back: chrF | 46.6 | **49.1** |
| Back: references right | 3/60 | 7/60 |
| Back: title month kept | 5/30 | 8/30 |

- **Part of the gain is Whisper writing a hint word it half heard.** The
  title, read `מִן` in these readings, was written `מן` 19 times in 30 with
  the hint, 6 without. No hint word was heard more often than it was said
  (`מן` as a word: 30 said, 19 heard; `הטקסט שוב` 30/30; `פרק`, `פסוק` 59 of
  60 each).
- **Two apparent drops were Whisper's.** With the hint, 0723 take 2's
  `הטקסט שוב` and both of 0616 take 2's references were heard; without it,
  one reference had come back `פרק שני מסר` and the line not at all. So fix
  B's real drops were two: 0120 take 1 (`בהתחלה זה מאוד רך`) and 0616 take 3
  (a reference).
- References still come back wrong in English because the book names do:
  `ההגלת אל הרומאים` ("the exile") became "Emigrate to the Romans",
  "First Migration to Timothy". The English forms themselves (`Psalms,
  chapter 23, verse 5`) are read correctly by the reference finder.

**Listening back, for Hebrew** (`listen_back.py`). Whisper `base` and
`small` on the CPU over the same thirty whole readings, a stretch of 12 or
more letters unheard counting as left out:

| Listener | Letters misheard | Real drops found | False alarms | Time |
|---|---|---|---|---|
| `base` | 12-27% | 2 of 2 | 3 | 4 min |
| `small` | 6-18% | 2 of 2 | 1 | 12 min |

(Plus two takes where `base` lost its place in the whole file, which a
chunk does not do.) **Hebrew uses `small`**, Chinese keeps `base`; the
listener is per language now, and both are fetched at job start (`small`
is 464 MB on disk; since 2026-10-27 only the listeners a job's reading
languages need are fetched, every one when the job does not say). Text is
compared with points stripped, digits spelled and
final letters folded; a left-out `פרק` or `פסוק` earns the extra reference
takes. A `פרק`/`פסוק` count like Chinese's chapter check is not used: `small`
missed them in readings that had them all. 4 tests changed or added.

**Ten files with `מָן` and listening back** (fix B's translations, read
again). Listening back fired three times in thirty readings: 0616's
`האיגרת אל העברים, פרק שנים עשר, פסוק אחד עשר` left out (five takes, as a
reference earns) and a clause of 1005 (`ואז יחשבו שההתנהגות שלהם`), plus
the ordinary abrupt-ending retakes. Heard four ways:

| Heard by large-v3-turbo | Fix B readings | These readings |
|---|---|---|
| No hint | 4.0% | **3.9%** (640/16512) |
| Bare sentence `להלן משפטים בעברית.` | 3.9% | 4.7% |
| Sentence + words (the app's hint) | 3.4% | 4.6% |
| Back: chrF / refs / month, no hint | 46.6 / 3 / 5 | 48.1 / 6 / 5 |
| Back: chrF / refs / month, app's hint | 49.1 / 7 / 8 | **50.2 / 10 / 7** |

- **Unhinted, `מָן` and listening back together are level** with fix B
  (3.9% against 4.0%); what each does was measured directly (the title A/B
  above; the two catches here).
- **Any hint sometimes makes Whisper skip speech.** 0723 take 2 scored
  31.5% with either hint: three sentences gone from what was heard, though
  the reading is 67.4 s like its other takes (68.0, 68.7) and the unhinted
  listen heard them. The bare sentence also lost 0829's title once. The
  Chinese hint's first version did the same (2026-10-21).
- **Decided: the hint stays in the app; goal 1 is scored unhinted from
  here.** The hint only matters when Tertius transcribes Hebrew audio - the
  way back to English - and there it won on both sets, the skipped take
  included. A Hebrew listener is not hinted, so the listening score should
  not be either; the unhinted letter rates average 3.95% against 4.0% for
  the app's hint, no gain on that measure.

> Corrected 2026-10-27: **the hint is out of the app.** The skip is not the
> hint's wording. 0723 and 0829 heard again with the app's hint, with its
> words alone and with just `פרק, פסוק.`: every one lost the same three
> sentences of 0723's second take (31.5%), exactly as before - it is
> deterministic - and `פרק, פסוק.` also lost 0829's title. Only no hint
> heard them. With references now found (below), the hint's gain back to
> English is chrF 50.6 to 52.6 and 51 to 53 references; sentences silently
> gone from a transcript cost more than that.
- The first nine readings of this run (0120-0510) had no retakes at all,
  where earlier runs had about one a reading, which looked like listening
  back interfering. From 0616 on they came at the usual rate; one thing found on the way: running faster-whisper
  drops torch's CPU threads from 6 to 4 for the rest of the process. Not
  shown to change a reading.

**Hebrew references found in what Whisper heard** (`scripture.hebrew_references`,
for goal 2, as `chinese_references` is for Chinese). Tertius now reads a
reference `<book>, פרק <n>, פסוק <n>`, so that is what to look for: `פרק`, a
number (digits or words of either gender), `פסוק` (or `פסוג`, `בסוק`, `פסופ`,
`עסוק`, as Whisper also wrote it), a number. The book is whichever table name
is most like the last one to five words before `פרק`, letter for letter
(`ההגלת אל הרומאים` is Romans, `הגר את פטרוס השנייה` 2 Peter): it must score
0.85, or 0.65 and 0.1 ahead of the next book. The span is masked, and the
English citation goes back in after madlad. Over all 210 readings with the
new reference wording, **341 of 420 references found, 5 wrong** - the five are
`פרק 13, פסוק שני`, Whisper's "verse two" for twelve, kept as heard. Most
misses are a misheard number (`שלושה הסל`, `שני מסר`). The spellings it was
fitted to are Whisper's from these same readings, as the Chinese ones were.
14 tests.

Back to English, the listen-back run's thirty readings:

| | Without | With references found |
|---|---|---|
| App's hint: chrF / references / title month | 50.2 / 10 / 7 | **52.6 / 53 / 11** |
| No hint | 48.1 / 6 / 5 | 50.6 / 51 / 9 |

The miss that led to five words, not four: 0723's `ההיגרת הראשונה אל תימות
יוס` (Timothy split in two) was left to madlad, which wrote "Hosea 5:8".

**madlad against m2m100-1.2B, English into Hebrew, on text** (the comparison
2026-10-19 said had never been made). Both translated the ten transcripts
with every fix above; each Hebrew text was then translated straight back to
English by madlad - no reading, no listening - and scored by chrF:

| | chrF | Files ahead |
|---|---|---|
| madlad | 52.1 | 3 (0120, 0616, 1218) |
| **m2m100-1.2B** | **55.1** | 7 |

The judge is madlad, which if anything favors its own Hebrew. m2m100 looped
nowhere (no three words more than twice in a file, the second time being
"The text again") and wrote nothing like 1005's invented verse; that was
checked by the round trip, not by a reader.

**m2m100's Hebrew read and listened to** (every fix above, three takes,
madlad translating back):

| | madlad (listen-back run) | m2m100-1.2B |
|---|---|---|
| Letters misheard, no hint | **3.9%** (640/16512) | 4.0% (649/16074) |
| Letters misheard, app's hint | 4.6% | 4.1% |
| Back: chrF / references / title month, app's hint | 52.6 / 53 / 11 | 53.1 / 45 / 12 |
| **Back, no hint (the app now)** | **50.6 / 51 / 9** | 50.6 / 42 / 11 |

**madlad stays.** For a listener the two are level, 3.9% and 4.0%, inside
the noise, and m2m100 lost nothing; back to English they tie on chrF, and
m2m100's readings bring back fewer references right (42 against 51). Its
Hebrew keeps more of the English on text (chrF 55.1 against 52.1), which the
reading does not carry through. Listening back fired on one chunk of 0510
(`וגם השמחה תתפוצץ` left out, two takes in a row). The translator stays the
user's choice; nothing in the app routes Hebrew to a model of its own.

Readings are seeded, and nothing that makes a reading has changed since this
run (the narrower listener download and the hint's removal touch only what
is fetched and how Whisper listens), so this run stands as the final one
with every change in; it was not read again.

**What the 3.9% is** (the listen-back run, madlad, no hint: 640 of 16,512
letters). Aligned word by word as the scorer normalizes, each differing
stretch given one cause by how it sounds - letters modern Hebrew says alike
(א/ע/ה, ח/כ, ט/ת, ק/כ, ב/ו, ס/ש) and ו/י written or not count as the same
sound. Word alignment counts 662 letters, against the scorer's 640:

| Cause | Letters | Share | |
|---|---|---|---|
| Same sound, other spelling | 258 | 39% | `האיגרת`→`ההיגרת` ×14, `הכוס`→`הקוס` ×8, `מתמלאת`→`מתמלט` ×6. Read right; Whisper's spelling, not a listener's error. |
| Near sound | 226 | 34% | `פרק`→`ברק` ×5, `האיגרת`→`ההיגלת`, `הכחיש`→`הכיש`, `הטקסט`→`הטקס` |
| Different sound | 90 | 14% | the title `מָן` as `מעל` ×4, `בואו`→`פה` |
| Left out | 82 | 12% | two stretches; one Whisper's (below) |
| Added | 6 | 1% | |

- **ר heard as ל** is the one common swap of letters that sound different:
  21 of the 771 ר read (`העברים`→`העבלים`, `פטרוס`→`פטלוס`, `יקרי`→`יקלה`);
  the other common swaps are same-sound spellings (כ→ק 27, א→ה 22, ת→ט 14,
  ע→א 13). Whether Chatterbox's ר is wrong or Whisper mishears it is for a
  Hebrew speaker; no spelling can change how a ר is said.
- **Without the same-sound spellings, about 2.4%** (404 of 662 letters
  remain, scaled to the scorer's 640) - nearer what a listener would get
  wrong, as the Chinese 2.1% was once its same-sound 21 were set aside.
- **Left out: both stretches are Whisper's, not drops.** 0403 take 1 is
  40.0 s like its other takes (39.9, 40.9), and Whisper large missed the
  stretch with and without a hint. 0510 take 2 is 45.6 s like take 1
  (45.8), and the same audio heard with either hint has the clause
  (`ומכאן אנו מסוגלים...`); only the unhinted listen skipped it. So
  listening back was right not to fire, and Whisper large skips speech
  without a hint too, if less often.

> Corrected 2026-10-27: this first said 0510 take 2 was a real drop that
> `small` missed, from its being 42.6 s. That length is take 3's (`.t2`),
> which lost nothing.
- The title still costs: `מָן` heard `מעל` ("above") four times, `מענ` five
  (same sound, scored as spelling).
The script is in a session scratchpad.

**A sound figure in the harness** (`tools/harness.py`, Hebrew): the
skeleton, with the letters above that sound alike made one and א dropped
like ו and י. It leaves out Whisper's spelling, so it is closer to what a
listener gets wrong; it also cannot tell `מן` "man" from "min", which
unpointed Hebrew does not show. Every run, letters and sound:

| Run | Letters | Sound |
|---|---|---|
| Baseline (scored with its own code) | 4.5% | 2.7% (289/10722) |
| Fix A | 4.2% | 2.8% |
| Fix B | 4.0% | 2.5% |
| Now: madlad, listening back, no hint | 3.9% | **2.4%** (268/11100) |
| m2m100-1.2B | 4.0% | 2.5% |

By sound the fixes gain less than by letters: much of the letter gain was
the title and "The text again" now spelled as Whisper spells them.

**The title said three ways.** First chunk of each file, three takes each,
seeds 700+, no retakes, Whisper large, the first word heard. "man" is any
of `מן`, `מען`, `מאן`:

| | "man" | |
|---|---|---|
| `מָן` (as now) | 16/30 | `מן` 12 - as in the first A/B - `מען` 4, `מה` 3, `זמן` 2 |
| `מַן` | 17/30 | `מן` 12, `מען` 5, `מנה` 3, `מעל` 3 |
| `מָאן` | 16/30 | `מן` 11, `מען` 4, `מה` 3, `מעל` 3 |

No difference: the points are not what is misheard; a lone short syllable
opening the reading is. Nothing changed. The script is in a session
scratchpad.

**Speech Whisper jumped over, decoded again** (`transcribe.py`, Hebrew only).
Both stretches the 3.9% run lost were cut at the end of Whisper's first
30-second window: a segment ended at 26.0 s and the next began at 30.0 s
(0403), 26.1 and 32.2 s (0510). faster-whisper starts each window where the
last one ended when the model closes it early, so the speech between is
never decoded. On those two readings, with the app's settings changed one
at a time: VAD off, timestamps off, word timestamps - all still skipped;
beam 1 heard both (and 0723's skip under a hint, not the app's case now,
survived everything).

So every gap of more than 1.5 s between segments is decoded again on its
own (`clip_timestamps`). On real silence Whisper writes `תודה רבה.` - four
times in the thirty, VAD on or off - with timestamps running a full 30 s
past the gap, where both real recoveries ended inside it (26.0-29.1,
26.1-32.3); so a refilled segment is kept only if it ends within the gap
plus a second. The thirty readings, heard by the app's own code:

| | Letters | Sound | Stretches lost |
|---|---|---|---|
| Before | 3.88% (640/16512) | 2.41% | 2 |
| Refill | **3.43%** (567/16512) | **1.92%** | 0 |
| (beam 1, for comparison) | 3.50% | 2.02% | 0 |

The only text it put in was the two lost clauses. Beam 1 did as well, but
changes how every language is decoded; the refill touches only gaps.

**Not Chinese.** The 2.0% Chinese run heard the same way went to 2.8%
(215/7569): every Chinese gap decoded again came back invented, and inside
the gap - Whisper's YouTube outro (`请不吝点赞 订阅 转发 打赏支持明镜与点点栏目`),
`语言语言语言...`. So it runs for Hebrew only (`REFILL_LANGUAGES`); English
is unmeasured and unchanged. 5 tests.

**English too, with a three-word floor** (2026-10-27). The Manna book itself
is in the Bible_Study vault (`07 Books/Other/Devotional/Daily Heavenly
Manna`, one file a day), so English can be checked against what was read:
the verse, the comment, the verse again. Every sixth recording, 62 in all,
transcribed with the app's settings, runs of four or more book words
missing from the transcript:

| | Missing stretches | Words |
|---|---|---|
| Before | 7 | 104 |
| With the refill | **2** | **17** |

- **What was lost was whole verses.** 0113, 0424 and 1114 lost the verse
  repeated after "The text again", at 55-60 s - the end of Whisper's second
  window - and 0828 lost its opening title and verse (0-10 s). Decoding the
  gaps again brought each back word for word, and 0623's title (`Madna for
  June 23rd`), skipped too.
- It also wrote `for.` and `19. 19.` into two gaps, both inside them. So a
  refill is kept only at three words or more (`REFILL_MIN_WORDS`), which
  also stops Hebrew's `תודה רבה`; every real recovery, English or Hebrew,
  was four words or more. Hebrew's result above is unchanged by it.
- The two stretches left are both 1208, with no gap near either: not a
  window skip; likely the reading differs from the book there. Not checked.
- The 62-file run with the app's code counted what was missing, not what
  was added; that nothing invented gets in rests on the earlier run, whose
  gap decodes are the same calls.
`REFILL_LANGUAGES` is Hebrew and English; Chinese stays out. 3 tests more.

## 2026-10-24 — three more same-sound spellings, and 得着 left alone

The five candidates below, tried the way 白昼 was: every chunk holding one,
three takes as written and three spelled with a same-sound character, same
voice, seeds 700+, no retakes, heard back by Whisper large (2026-10-23).

| Word | As written | Spelled | |
|---|---|---|---|
| 渣滓 | 0/3 (扎值, 扎之) | 3/3 as 渣子 | Added |
| 哀哉 | 0/3 (哀胎, 爱胎, 嗨) | 2/3 as 哀灾 (miss 爱哉, a tone) | Added |
| 福祉 | 1/3 (扶持) | 2/3 as 福止 (miss 复制) | Added |
| 溢 | 18/18 | 18/18 as 益 | Not needed; the harness misses were Whisper's |
| 得着 | 得 7/9, 着 2/9 | 得 9/9, 着 4/9 as 德着 | Not added |

Now in `speech.SPOKEN_AS`: 渣滓→渣子, 哀哉→哀灾, 福祉→福止 (1 of 9 heard
right as written, 7 of 9 spelled). One chunk each, so three takes is all the
evidence.

**In the ten-file run** (`--takes 3`, 2026-10-24, transcripts and
translations reused from the 2.1% run): **2.0% (152/7569)**, from 2.1%
(162). Every take of the three words, Whisper large:

| Word | File | 2.1% run | Now |
|---|---|---|---|
| 福祉 | 0226 | 扶持 ×3 | 福祉 ×3 |
| 渣滓 | 0616 | 扎值 ×3 | 渣子 ×3 (same sound; still scored an error) |
| 哀哉 | 1005 | 爱胎, 哀胎, 爱泰 | 埃灾 ×2, 爱在 (a tone off) |

0226 went 3.0% to 2.5% and 1005 2.9% to 2.2%; 0616 stayed 2.9%. Five of
the other seven files scored exactly as before; 0510 (+1 character) and 0829
(-1) hold none of the words.

**得着 is two errors.** 德 fixes the 得. 着 (zháo) is read zhe either way,
heard 者 in every remaining miss; 2/9 against 4/9 is take-to-take noise. No
common character has its sound, so no same-sound spelling can fix it. Reading
another word (得到) would change what a listener hears, which no `SPOKEN_AS`
entry does yet: left for a Chinese speaker to judge. The scorer miscounted the
second 得着 in 0829 chunk 0 (before a full stop); the 得着 row is counted by
hand from all twelve takes' text.

## 2026-10-23 (later) — what the 2.1% is, splitting rejected, Chinese references kept

**The 162 misheard characters, by sound** (pypinyin against what Whisper
wrote, all 30 readings of the run below):

| Cause | Chars | |
|---|---|---|
| Tone only | 71 | Right syllable, other tone: 着/者 ×5, 腓立/菲利 ×4, 神/身 ×3, 善事/膳食, 士兵/事并. Some are Whisper choosing a word; context settles many for a person. |
| Different sound | 50 | Misread: 得→逮 ×4, 福祉→扶持 ×3, 渣滓→扎值 ×3, 然→拿, 哀哉→爱胎, 正确→煞雀. |
| Same sound, other character | 21 | Read right; Whisper chose 在/再, 膏/高, 事奉/侍奉, 义/异. Not a listener's error. |
| Left out | 12 | 5 are references (0616's 第十二章 once, 0510's 十 once). |
| Added | 8 | 3 are madlad's own 疲乏乏力 heard as 疲乏力. |

Clusters a fix could take: **得着** in 0829, read děi zhe for dé zháo (得→逮
×4, 着→者 ×5: most of the worst file); and four rare characters, 渣滓 (6),
福祉 (6), 哀哉 (5), 溢 (8 across its spellings), as `SPOKEN_AS` candidates
like 白昼. Tried 2026-10-24, above.

**Splitting long English sentences before madlad: rejected, without a
harness run.** 13 of the ten files' 108 sentences run 30 words or more, the
longest 96. Translated whole, madlad kept every clause of all 13. Split at
commas into pieces of up to 20 words, 4 of the 13 came back with scripture
invented for a fragment (`11:11 耶和华的使者来到他面前...`,
`主耶稣基督的话,是主的话,是主的话`) and one lost its clause. Up to 30 words
was worse: a piece of 0120 became a line of fiction
(`文龙看着她的眼睛...`). madlad needs the whole sentence; a reading of
invented text is not worth measuring.

**References in the Chinese-to-English direction** (goal 2). What Whisper
heard of the 30 readings, put through madlad into English:

| | References right (of 60) | Title kept (of 30) | chrF vs the English |
|---|---|---|---|
| Before | 41 | 21 | 53.8 |
| References protected | 59 | 18 | 53.5 |
| + the title and "The text again" named | **59** | **30** | **55.9** |

- Before, madlad wrote its own citations: `Hebrews, chapter 12, section 3`
  (1005, all three readings), `James, chapter IV, section 3`, 1 Timothy as
  `I Matthew 5:8`, and once a verse invented in place of one
  (`10:13 And he said unto them...`).
- `scripture.chinese_references` finds 第...章第...节 (and 篇, `2,12`,
  `13:12`, 和-lists and 至-ranges) after a book named **by sound**: Whisper
  wrote 菲利比书, 西伯来书, 贴萨罗尼加 and 十篇 for 詩篇, and every one sounds
  exactly like the table's Traditional name. An ending of three syllables or
  more that only one book's name has also counts (听摩太前书, 0723). Nothing
  looser: 腓立比書 and 腓利門書 are a syllable apart. It refuses a number
  that is not one (`第二三篇`, 0510's cut 二十三) rather than cite Psalm 3.
- The miss is 0616's reference the reading itself cut (希伯来书第十一节).
- **Protecting the reference cost the title** in three readings: with a
  placeholder in the opening sentence, madlad dropped `4月3日的玛纳`. So the
  title and 再读一遍经文 are now named from the table in this direction too
  (`fixed_lines`), from the spellings Whisper actually wrote (玛纳 45, 玛娜 7,
  妈哪 4, 马懒 2; 再度一遍经文 4 of 60).
- `pypinyin` (0.55.0, MIT, pure Python, checked on PyPI) does the sound.
  It is in the translate extra and installed by Download and prepare, but
  not required: without it Chinese references go to madlad as before, and
  an existing install is not told translation is unavailable. CI installs
  it; without it the 22 tests of this skip (checked).

English into Chinese is untouched: nothing here runs on a text with no
Chinese in it, so the reading and its 2.1% are unchanged.

## 2026-10-23 — a check for the reference itself: 2.5% to 2.1%

**Three takes per file: 2.1% misheard** (162 of 7,569), against 2.5% for the
same files, translations and seeds without it (the entry below).

| File | Mean | Take 1 | Take 2 | Take 3 |
|---|---|---|---|---|
| 0120 | 1.1% | 0.0% | 1.9% | 1.5% |
| 0226 | 3.0% | 2.3% | 4.3% | 2.3% |
| 0403 | 0.6% | 0.5% | 0.0% | 1.4% |
| 0510 | 3.0% | 2.8% | 2.8% | 3.3% |
| 0616 | 2.9% | 2.9% | 2.2% | 3.6% |
| 0723 | 0.9% | 0.3% | 1.0% | 1.3% |
| 0829 | 4.8% | 4.9% | 2.0% | 7.4% |
| 1005 | 2.9% | 3.3% | 1.7% | 3.7% |
| 1111 | 1.8% | 2.1% | 2.5% | 0.8% |
| 1218 | 0.9% | 0.8% | 2.0% | 0.0% |
| **All** | **2.1%** | 1.9% | 2.0% | 2.5% |

**Why the old check missed it.** `base`, the listener, hears the book name
wrong too: 希伯來書第十二章 came back as 西部来书. To `missing_text` that is
eight characters heard as four, a mishearing, not a gap.
`listen_back.missing_references` now counts each 第...章, 第...篇 and
第...节 in a chunk against what was heard, whatever its length, and any one
short is left out, which earns the chunk the two extra takes.

**Its first version cried wolf.** `base` writes 第12张 / 第13張 for 章 and
第二十三片 for Psalm's 篇, read correctly. In a first run (stopped part way)
it fired 29 times in five files, most of them false, and used all five
takes on 0510's Psalm 23:5 four times. Those same-sound characters now count
as heard (`_SAME_SOUND`). In the run above it fired on 7 chunks in 30
readings:
- **Five fixed on the next take**, and every one of those takes scored
  better than the same take without the check: 0120 take 1 1.9% to 0.0%,
  0226 take 3 5.9% to 2.3%, 0403 take 2 0.9% to 0.0%, 0616 take 1 6.1% to
  2.9%, 0723 take 3 2.3% to 1.3%.
- **Two used all five takes and kept the best.** 0510 take 1: both
  listeners heard 第二三篇, so Chatterbox likely did drop the 十; that take
  went 1.9% to 2.8%. 0616 take 3: the second reference still came out
  without 第十二章.
- **0616 now keeps 第十二章 in 5 of its 6 references, against 3 of 6.**
- Files where it never fired (0829, 1005, 1111, 1218) scored exactly as
  before, take for take.

Cost: 15 extra takes over 30 readings, a chunk's worth of speech each.
Other retakes: 5 for babble, 11 for an abrupt ending.

The run was stopped four times (low memory while the session sat idle, and
Seth's pauses) and resumed from the readings on disk; the last reading,
listening and scoring ran in the foreground.

## 2026-10-22 (evening) — three takes per file, and extra takes for a cut reference

**Three takes per file: 2.5% misheard** (188 of 7,569 characters). Same ten
files, the translations of the last run above, the code as it now stands.
`tools/zh_harness.py --takes 3` reads and hears each file three times, each
take seeded apart; the first take keeps the old seed and file names.

| File | Mean | Take 1 | Take 2 | Take 3 |
|---|---|---|---|---|
| 0120 | 1.7% | 1.9% | 1.9% | 1.5% |
| 0226 | 4.2% | 2.3% | 4.3% | 5.9% |
| 0403 | 0.8% | 0.5% | 0.9% | 0.9% |
| 0510 | 2.8% | 1.9% | 2.8% | 3.8% |
| 0616 | 3.9% | 6.1% | 2.2% | 3.6% |
| 0723 | 1.2% | 0.3% | 1.0% | 2.3% |
| 0829 | 4.8% | 4.9% | 2.0% | 7.4% |
| 1005 | 2.9% | 3.3% | 1.7% | 3.7% |
| 1111 | 1.8% | 2.1% | 2.5% | 0.8% |
| 1218 | 0.9% | 0.8% | 2.0% | 0.0% |
| **All** | **2.5%** | 2.4% | 2.1% | 2.9% |

- **The noise, measured.** Whole-run totals span 2.1-2.9% on unchanged
  text; single files swing by up to 5.4 points (0829: 2.0% to 7.4%). So the
  2.2-2.7% of the last four runs above were one level, as read, and a change
  worth less than about a point over ten files needs `--takes 3` to show.
- No take lost a stretch of six or more characters.

**Extra takes for a reference cut short (`SPEECH_REFERENCE_RETRIES = 2`):
never fired.** When listening back finds a chapter or verse among what was
left out (`listen_back.names_a_reference`), a chunk gets five takes instead of
three. In 30 readings it fired zero times, yet 0616 read 希伯來書 12:11 as
希伯来书第十一节, without 第十二章, in 3 of its 6 references. 第十二章 is four
characters, and listening back only counts a gap of six or more
(`MIN_MISSING_CHARS`), so the drop it was built for passes unseen. It is
committed because it is harmless and tested, but **it does nothing yet**;
catching a cut reference needs a check of the reference itself, not a lower
threshold for everything (shorter gaps are what `base` mishears anyway).

> Corrected 2026-10-23: the length was not the whole reason. With the
> Traditional 來書 the gap is six characters; it passed because `base`
> heard the book name wrong as well (西部来书), making it a mishearing to
> `missing_text`. Fixed by the check in the entry above.

Retakes that did fire: 3 for babble (all on the first or second take of a
chunk), 14 for an abrupt ending, 2 of which kept the least bad of three.

## 2026-10-22 (later) — the scorer stops counting its own artifacts

`tools/zh_harness.py` score no longer counts two things that were never a
listener's error, and **every figure from here on is on this footing**:
- **吗哪 heard as 玛纳 or 玛娜.** It is read as 玛哪 on purpose
  (`SPOKEN_AS`), so Whisper writing what it hears cost every title two
  characters.
- **A known Whisper hallucination at the very end of what was heard** -
  only the two seen here, 谢谢 and 请不吝点赞订阅转发打赏支持明镜与点点栏目 - unless
  the text itself ends that way.
`--raw` scores as before. It reproduced all nine recorded figures exactly,
so nothing else moved. Every run whose readings still exist, rescored:

| Run (same ten files) | Raw | **Now** |
|---|---|---|
| madlad, 2026-10-21 rerun | 3.4% | **3.2%** |
| madlad with the dot fix | 3.4% | **3.2%** |
| Qwen passage | 5.1% | **5.1%** |
| Qwen sentence | 4.7% | **4.1%** |
| Qwen strict prompt | 5.5% | **4.7%** |
| Fixed lines | 3.5% | **2.7%** |
| + colon chunking, babble check | 3.1% | **2.2%** |
| + 白昼/祷告/羊羔 substitutions | 3.3% | **2.5%** |
| + new chunk at 再读一遍经文 (the code now) | 4.1% | **2.6%** |

The 2026-10-21 baseline (5.5% raw) and its first fixes (3.2% raw) cannot be
rescored: those readings are gone. Read across: madlad 3.2% to 2.2-2.7%
with the day's changes. The last three runs differ by eight to ten
characters in 2,523, inside the take-to-take noise of a point or so per
file seen all day, so they are best read as one level, about 2.5%, not as
the last two changes making things worse. Both of those fixed something
specific that was measured directly (five of five words heard; 0510's
reference read).

**0616's skipped 第十二章: not the wording.** Both drops went from the first
第十 of 第十二章第十一节 to the second, so the guess was that the reading
jumps between the two. Both of 0616's reference chunks, three takes each,
same voice and seeds, no retakes: as today 5/6, with a pause
(第十二章，第十一节) 5/6, without 第 (十二章十一节) 5/6. The pause still
skipped once, the version without 第 lost the whole reference once, and
Chatterbox forced EOS in all 18 takes. Not supported; no wording change.
The miss rate moves between samples - 1 of 6 here, 2 of 4 the day before,
3 of 3 in one harness run - which is what a random failure looks like on
this few takes. Retakes are what catch it now, and in that harness run
three were not enough.

## 2026-10-22 — what the misheard characters are, and three Chatterbox gets wrong

**Every misheard character of the 3.1% run, sorted by cause.** A scratch
script aligns the reference and what was heard exactly as `zh_harness.score`
does (its total matches: 77/2523) and tags each span by sound with
`pypinyin` (MIT, checked on PyPI, installed with `--target` beside OpenCC,
not in the app):

| Cause | Chars | Share |
|---|---|---|
| Scorer artifacts | 22 | 29% |
| Same syllables, same tones (Whisper picked a homophone) | 6 | 8% |
| Same syllables, a tone differs | 23 | 30% |
| Near or different sound | 20 | 26% |
| Dropped (parts of references) | 5 | 6% |
| Added | 3 | 4% |

- **Scorer artifacts.** 吗哪 is read as 玛哪 on purpose (`SPOKEN_AS`) and
  Whisper writes 玛纳, so every title costs two characters - 20 in all. The
  other two are 谢谢, Whisper's usual hallucination on the silence at the end
  of 0120. Neither is anything a listener would get wrong. **Without them
  the run is about 2.2% (55/2523).**
- **Homophones** (膏→高, 在→再, 义→异): the reading was right; a person has
  context Whisper lacks.
- **A tone differs** (神→身, 显→贤, 士兵→事并, 疲乏→批发): Chatterbox or Whisper.
  Only listening can tell, and a Chinese speaker is the right judge.
- **Near or different sound**: mostly real mispronunciations, and three
  words were **never heard as written in any harness reading**, six runs of
  ten files across different translations and voices: 白昼 0 of 17, 祷告 0
  of 7, 羊羔 0 of 4 (counted once per reading; first written 20/7/5, which
  counted readings the dot-fix run reused). For comparison 罗马书 was heard
  right 11 of 12, 得着 9 of 13 (得 also reads
  děi, heard as 逮).
- **Dropped**: 第十二章 from 0616's closing reference, 十 from 0510's 二十三.
- **Added**: the 谢谢 above, and a 乏 from madlad's own doubled 疲乏乏力.

**A same-sound character fixes the three words.** Read the way 吗哪 already
is - Chatterbox given a common character with the same sound, the text left
alone - and listened to by the harness's Whisper. Every chunk of the 3.1% run
holding one of them, three takes each way, same voice and seeds, no retakes:

| Word | As it is | Read as | With it |
|---|---|---|---|
| 白昼 bái zhòu | 0/9 (白赠, 白电, 白赞, 白凳, 白蛋) | 白宙 | 7/9 (the two misses: 白肘, a tone off) |
| 祷告 dǎo gào | 0/3 | 导告 | 3/3 |
| 羊羔 yáng gāo | 0/3 | 羊高 | 3/3 |

**Now in `speech.SPOKEN_AS`** (`dae883b`), Simplified forms only (the
Traditional 白晝 and 禱告 never occurred, so were not measured). One test.
The test script is in a session scratchpad, not the repo.

**Ten-file run with them: 3.3% (82/2523), nothing lost** - against 3.1%
without. Same translations; the four files holding one of the words were
read again (0403, 0616, 0829, 1218), and the other six readings reused,
their chunks being unchanged (unchanged files scored identically last
time). **All five occurrences were heard right in context** - 白昼 3/3,
祷告 1/1, 羊羔 1/1 - where the 3.1% run heard none. 0403 went 2.3% to 1.4%,
1218 2.4% to 1.6%, 0829 stayed at 4.4%. The total rose because of **0616,
4.7% to 7.9%**: with its chunk text changed, the takes changed too, and
both Hebrews 12:11 references came out cut short (8 characters dropped).
Listening back heard it and retook, and three takes of three were still
short. So the words are fixed; the noise is a reference that Chatterbox
sometimes truncates whatever the change - the *Dropped* row above, and the
next thing worth looking at.

**References cut short: not the Traditional book names.** Every missing
stretch of 0616's reference began at 來, and the book names come from the
table in Traditional (希伯來書) inside Simplified prose. Tested: all 20
reference chunks of the ten files, two takes as written and two with each
book name read in Simplified (`numbers._BOOK_T2S`, via `SPOKEN_AS`), same
voice and seeds, no retakes, the whole reference sought in what the
harness's Whisper heard (toneless pinyin, digits as numerals): **35 of 40
both ways.** Ruled out.

The ten misses are not spread out:
- **0510's closing 詩篇第二十三篇第五节 was never read - 0 of 4**, either form;
  the verse before it was. The takes kept in the 3.1% and fixed-lines runs
  both logged Chatterbox **forcing EOS on token repetition** in that chunk.
  Psalms are the one book whose reference says 篇 twice (詩篇...第二十三篇), the
  likely repetition - a hypothesis, tested next and wrong.
- 0616's closing reference skipped 第十二章 in 2 of 4 (希伯来书第十一节).
- The other four were read with slips (集七节, 习普来书, an extra 第三章, one
  take of babble).
The test script is in a session scratchpad.

**Not the wording either.** 0510's last chunk, four takes each with the
reference read five ways - as today (`詩篇 第二十三篇第五节.`), with `。`, a
pause after 詩篇, a pause before the verse, and without 第 - same voice and
seeds, no retakes: heard 1/4, 0/4, 0/4, 0/4, 0/4, and **Chatterbox forced
EOS in all 20 takes**. Every wording still said 篇 twice, so that idea was
never really tested. What the takes did show: several stopped *before* the
verse, after 我又说你们要欢喜. The chunk is long and repeats itself (欢喜
three times, 溢出 twice in a few sentences), and the reference is the last
thing in it.

**Splitting the chunk at 再读一遍经文 fixes it.** The same chunk, four takes
whole and four split in two at 再读一遍经文, so the verse and its reference
are a chunk of their own; same voice and seeds, no retakes:

| | Reference heard | 你们要欢喜 heard | Forced EOS |
|---|---|---|---|
| Whole, as today | 0/4 | 4/4 | 4 of 4 chunks |
| Split | **4/4** | 4/4 | 6 of 8 chunks |

EOS still fires, but on the first part it cost nothing, and on the verse it
fired in 2 of 4 without losing the reference. Measured on this one chunk
only.

**Now in the app: 再读一遍经文 always starts a chunk** (`speech._pack`, via
`fixed_lines.STARTS_A_CHUNK`; 2 tests, 710 pass). Ten-file run: six files
gained a chunk and were read again (0120, 0226, 0510, 0829, 1005, 1218); the
other four, chunked identically, reused the substitutions run's readings.
- **Raw 4.1% (103/2523)** - but 20 of those characters are one Whisper
  hallucination at the end of 0120, 请不吝点赞订阅转发打赏支持明镜与点点栏目 ("please
  like, subscribe..."), its well-known YouTube-outro text on trailing
  silence; not read by Chatterbox. **Without it 3.3% (83/2523)**, level
  with the run before.
- **0510's closing Psalm 23:5 was heard** in the full run, where the run
  before missed it. Whole references heard: 17 of 20, against 16. The three
  short: 0510's *opening* reference (十 dropped from 二十三, as before) and
  0616's two (a separate case; its readings were reused).
- Per file, re-read: 0120 10.0% (2.6% without the hallucination; 3.3%
  before), 0226 3.1% (1.6%), 0510 3.3% (3.3%), 0829 4.9% (4.4%), 1005 4.0%
  (4.7%), 1218 1.6% (1.6%). Take-to-take noise of a point or so per file
  is normal here.
- The babble check caught a long babble in 0226 (发义义商是香港的一场...) and
  the retake was clean - its second real catch in two runs, still no false
  alarm seen.

## 2026-10-21 (evening) — fixed lines, babble, and a line Chatterbox dropped

Three changes to how Chinese is translated and read, after the Qwen trial
(next entry) settled on keeping madlad. All measured with the ten-file
harness, against madlad's 3.4% on the same transcripts.

**All three together: 3.1% misheard (77/2523), nothing lost** - the best of
the day (madlad 3.4%, fixed lines alone 3.5%). Same translations as the
fixed-lines run; only the reading changed. Per file: 0120 3.3%, 0226 1.6%,
0403 2.3%, 0510 3.3%, 0616 4.7%, 0723 1.0%, 0829 4.4%, 1005 4.7%, 1111 3.0%,
1218 2.4%. Three files changed, two of them for the better:
- **0616, 7.2% to 4.7%**: 再读一遍经文 now opens the last chunk with its verse
  and was read.
- **1218, 4.8% to 2.4%**: the babble check heard the repeated phrase
  (钢丝千倍如杨齐, the doubled 谦卑如羊羔), retook the chunk, and the retake was
  clean.
- **0403, 1.8% to 2.3%** (about one character): the colon change repacked
  it too, 再读一遍经文 moving into the last chunk with its verse; the line was
  heard either way.
The other seven scored exactly as before: their chunks did not change, and
the reading is seeded per file. **The babble check retook one chunk in ten
files, and that one was real** - no false alarms in this run. Three other
retakes were for missing references, as before (0510 twice, 0616 once).
(The run was stopped at 3 of 10 and resumed the next day; finished files
were kept.)

**1. The Manna title and "The text again" come from a table**
(`fixed_lines.py`, `642fe18`). Over the ten files madlad wrote the title
three ways - 曼纳, 吗哪, and twice 放款记录, "loan record" - and "The text
again" as 文本再次 or, once, 耶稣说 ("Jesus said"), which is not in the
English. English into Chinese, these are now `<month>月<day>日的吗哪` and
`再读一遍经文：` (Google's wording), and only the rest of the sentence reaches
the model when Whisper runs the line into the verse. "The text again" counts
only when punctuation or the end follows, so "The text again shows..." is
left alone. Every other language pair is unchanged. 21 tests.

Read and listened to: **3.5% misheard (89/2523)** - no overall change from
3.4%. The lines themselves were heard right: every title as
`<month>月<day>日的玛纳` (吗哪 read through `SPOKEN_AS`), and 再读一遍经文 in nine
files of ten. Files moved both ways: 0120 3.3% (madlad 2.2%), 0226 1.6%
(4.4%), 0403 1.8% (2.3%), 0510 3.3% (7.8%), 0616 7.2% (5.4%), 0723 1.0%
(1.3%), 0829 4.4% (4.5%), 1005 4.7% (1.4%), 1111 3.0% (1.7%), 1218 4.8%
(4.0%). Besides the twenty fixed lines, a few other sentences shifted by a
character with identical English; likely CTranslate2's batches now holding
different sentences, not checked.

**2. A line ending in a colon stays with what it introduces** (`speech.py`,
`ce33f3e`). 0616 lost 再读一遍经文 in all three takes: it fell at the end of a
chunk, its verse opening the next. Read alone that chunk dropped it two takes
in three ending in `：`, and two in three ending in `。` - so not the colon:
Chatterbox drops a short last sentence after a long one. A colon-ended unit
is now packed with the next one whenever the two fit the budget. Read that
way, the line was in three takes of three. 2 tests.

**3. Listening back catches added text as well as missing**
(`listen_back.py`, `ef27871`). `added_text` mirrors `missing_text`: six or
more heard characters with nothing in the chunk to match them. A take is
ranked by left-out plus added characters and retaken on either, within the
same retry budget. 5 tests.

Run over today's 40 finished readings with Whisper `base` on the CPU, as
listening back runs it (whole files, since chunk audio is not kept - a
weaker test of false alarms than per-chunk use):
- **Caught**: the 0403 babble (Qwen strict), and one nobody knew of -
  madlad's 1218 reads 谦卑如羊羔 twice (heard 谦卑如庚子，谦卑如养仙); the text has
  it once.
- **Probably false**: madlad 0120 and Qwen strict 1005, where only the CPU
  model heard the extra characters, not the GPU one the harness scores with.
  Not confirmed by listening.
- Qwen passage 0120: the CPU model lost its place in a long reading and both
  checks fired over most of the file - an artifact of whole-file listening.
A false alarm costs up to two more takes of that chunk, not quality: the
most faithful take is kept. Per chunk, in the ten-file run above, it fired
once, on real repeated text.

**Corrected**: the Qwen entry below said the "Jesus said" in Chinese to
English came from Whisper mishearing. It came from madlad, going into
Chinese.

## 2026-10-21 (later) — Qwen3-4B-Instruct-2507 as translator: tried, madlad stays

Nothing in the app has changed. Qwen runs from a scratch script outside the
repo that mirrors `Translator.translate`'s reference protection (bare
references named from the table, the rest masked as `@N@` and restored), so
the comparison with madlad is like for like.

**Running it.** `Qwen/Qwen3-4B-Instruct-2507` at revision `cdbee75f`,
Apache-2.0, 8.0 GB of bf16 safetensors. Loaded in 4-bit through
transformers' bitsandbytes support: NF4, float16 compute (Turing has no fast
bfloat16), greedy decoding. Two new packages, both checked on PyPI first:
`bitsandbytes==0.50.2` (MIT, a `py3-none-win_amd64` wheel, so no compiler)
and `accelerate==1.15.0` (Apache-2.0); pip added `psutil` with them. Installed
in `.venv` only, not yet in `requirements.txt`. **2.85 GiB peak on the GPU**,
loaded in 20 s, 14-23 s to translate one Manna file. madlad needs a converted
CTranslate2 model; Qwen needs none.

Download note: `hf.exe` in `.venv` exits 1 with no output from this shell
(likely the spaces in the path); `snapshot_download` from Python works. Xet
writes to disk in bursts, so a file sitting at 0 bytes is not a stall.

**madlad rerun as the baseline: 3.4% misheard, nothing lost** (3.2% last
session). The readings from last session were gone, so all four stages ran
again; the gap is run-to-run. Qwen is scored on these same ten transcripts.

**Two ways to call Qwen.** *Sentence*: one sentence per call, as madlad gets
them. *Passage*: the whole transcript in one call, one sentence per line,
references masked across it.

**English to Chinese, 0120, read side by side** (madlad / Qwen passage /
Google):
- The 96-word sentence: madlad keeps it as one; Qwen passage splits it into
  four; Google into three.
- "The text again": 文本再次 / 这段经文再次提醒我们 / 再读一遍经文.
- Qwen's slips: 儿女 for "sons", 责备 rather than 管教 in one line, and
  "Manna" as 每日灵粮 (Google: 灵粮).

**What the ten files showed before any listening:**
1. Sentence mode wrote `@0@` into sentences that had no reference, in the
   first try on 0120: the prompt mentioned placeholders on every call. Fixed
   in the script (the instruction is given only when the text holds one, and
   any placeholder left after restoring is removed); none leaked in the ten.
2. **Passage mode dropped a title line**: 0510 has no "Manna for May 10th".
   One file in ten; the other nine have it.
3. **Sentence mode added a clause that is not in the English.** 0829's
   transcript is already wrong ("Ye ask and receive, not because ye ask,
   amiss."), and every translator followed it. madlad: 你们求,就得着. Qwen
   sentence went further: 而是因为你们是凭着信心求, "but because you ask in
   faith". That is invented content, not a mistranslation.

The listening score cannot see 2 or 3: it compares the reading with the
translator's own Chinese, not with the English.

**Chinese to English** (input: what Whisper heard from madlad's readings).
Google, compared in Chrome on 0120 and 0829 (0510 was not run; the page
stopped updating):
- 0120: gave the verse in scripture wording, "God deals with you as with
  sons... (Hebrews 12:7)". madlad lost "Manna" ("20 For if you endure...").
- 0829: recovered "because you ask amiss (James 4:3)" from garbled Chinese.
  madlad ended on "Chapter 4 Chapter 4" and lost the reference.

**Qwen passage, ten files, listened to: 5.1% misheard (122/2409), and one
reference lost** - 0829's closing 雅各书第四章第三节 was never read. madlad on
the same transcripts: 3.4%, nothing lost. So on this measure Qwen's more
natural Chinese is *worse* for a listener, not better. Per file: 0120 1.4%
(madlad 2.2%), 0226 6.4%, 0403 5.1%, 0510 9.7%, 0616 5.2%, 0723 2.5%, 0829
8.1%, 1005 4.2%, 1111 5.1%, 1218 5.9%. Only 0120 beat madlad.

Some of the gap may be the reading, not the translation. Neither is
confirmed:
- **祂.** Qwen writes 祂 for God's "He" (9 times in the ten files); madlad
  never does. Twice in 0510 it was heard as 怨. 祂 and 他 are both tā, so
  reading it as 他 would be one `speech.SPOKEN_AS` entry. Two in nine is
  thin.
- **Line endings.** Qwen's passage output ends lines with two spaces and
  leaves blank lines, Markdown style. Whether that changes the reading's
  chunking, and so the lost 0829 reference, has not been checked.
- 0510's 头浇油 was heard as 投交友 both times it was read; madlad's wording
  of the same verse (用油膏我的头) was heard right.

**Qwen Chinese to English**, same input as Google and madlad (passage mode,
one call per file, 17-20 s each):
- 0120: kept "Manna" (madlad lost it), but did not recover the verse: "Who
  is the son of a father who disciplines?" inverts it. Google gave the
  scripture wording.
- 0510: recognized the verse and gave the KJV wording, "Thou anointest my
  head with oil". Google was not run on 0510.
- 0829: the closing verse came out close ("because you ask not in the right
  way"), but the opening one was **invented**: "do not think that you have a
  right to it". Google recovered "because you ask amiss" in both places.

Between madlad and Google, and it makes things up: that is the second time
today Qwen added content the input does not have.

**Qwen sentence, ten files, listened to: 4.7% misheard (114/2424), nothing
lost.** Per file: 0120 4.7%, 0226 5.9%, 0403 7.8%, 0510 8.3%, 0616 6.0%,
0723 2.2%, 0829 3.3%, 1005 5.1%, 1111 1.4%, 1218 3.4%. It beat madlad on
three files (0829, 1111, 1218). 祂 is in this text 7 times and was never
heard as 怨, so that cause is weaker than it looked.

**Result: as tried, Qwen3-4B does not beat madlad for a listener.** madlad
3.4% / nothing lost; Qwen sentence 4.7% / nothing lost; Qwen passage 5.1% /
one reference lost. Both Qwen modes also added content the English did not
have (0829), which madlad did not. What has *not* been tried: sampling
settings, Qwen's own reference rendering instead of the table's, or any other
model.

**A stricter prompt (sentence mode, nothing else changed): 5.5% misheard
(131/2366), nothing lost.** The same prompt plus: translate everything, add
nothing, do not fix a garbled sentence; and 他, never 祂. Per file: 0120
6.8%, 0226 4.9%, 0403 18.0%, 0510 6.1%, 0616 5.0%, 0723 3.8%, 0829 3.5%,
1005 4.6%, 1111 2.5%, 1218 2.6%. Before any listening, the Chinese showed:
- **A fabricated verse.** 0829 ends 4:3 你们求，就不得，是因你们妄求，不是为要
  得着，乃是为要显出你们的骄傲来; the second half is in neither the English nor
  和合本. Cause: the line was `James 4.3`, which was not masked (see the fix
  below), so the model got a bare citation and wrote a verse for it.
- **A wrong date.** 0510's title came out 10 月的吗哪, "Manna of October"; the
  English is "Manna for may 10th."
- **祂 anyway**, 6 times, despite "never 祂".
- "The text again" as 这段话再次呈现.

Chinese to English with the stricter prompt stopped inventing: 0829 follows
what is written and ends "because you ask with the wrong intention". The cost
was 0510's KJV wording ("You anointed my head"). 0120's verse was still
inverted.

**Chatterbox babbled in 0403, and nothing caught it.** Midway through the
reading Whisper heard 这里采万,依台万,台万,采万,采万,采万,采万 - nothing like
it is in the text - which alone is most of 0403's 18.0%. Without 0403 the run
is about 4.5% (97/2177), still above madlad. This is the "babbles on a short
chunk" problem from 2026-10-19, on a 51-second, four-chunk reading. Listening
back did not flag it because it only looks for text that is *missing*;
text that was *added* passes. Catching it needs the opposite check: heard
characters with no counterpart in the chunk.

**Fixed: references written with a dot** (`scripture.py`, `e6a4ce2`).
Whisper writes `James 4.3`; `numbers.py` already read the dot as
chapter:verse, but `find_references` knew only the colon, so the line went
to the translator unmasked. The dot now counts when there is no space either
side (`Hebrews 12. 7 of us did.` stays a sentence end and a number). Six
tests; 679 pass. Of the ten transcripts only 0829 has one.

**madlad rerun with the fix: 3.4% (84/2493), nothing lost - unchanged.** Same
transcripts; madlad translated all ten again, and only one line differed:
0829's closing 雅各书 4.3 (madlad's own) became 雅各書 4:3 (the table's). The
other nine translations were byte-identical, so their readings were reused;
0829 was read and heard again, and scored 4.5% as before. A listener heard
第四章第三节 either way, because `numbers.py` already read the dot. So for
madlad the fix changes nothing audible; it matters for a translator that,
like Qwen, does something worse with a bare citation.

**Split: madlad into Chinese, Qwen back to English?** Measured on all ten:
the Chinese Whisper heard from madlad's readings, translated to English by
madlad (the app's `Translator`, sentence by sentence), Qwen default and Qwen
strict (one call per file), and scored by chrF (character n-grams 1-6,
beta 2, written in the scratch script; checked: 100 identical, 45 a
paraphrase, 7 unrelated) against the original English transcript.

| chrF | mean | files better than madlad |
|---|---|---|
| madlad | 54.5 | |
| Qwen default | 52.8 | 4 of 10 |
| Qwen strict | 52.7 | 4 of 10 |

chrF rewards reusing the reference's characters, so a paraphrase ("You must
be joyful" for "Rejoice") costs Qwen. Read side by side, all thirty:
- **Qwen recovers scripture madlad mangles.** 0403: "Night is past, and day
  is at hand... the armor of light" against madlad's "the seventy days have
  come near" and "the white egg". 1005: "consider Him who... lest your hearts
  be weary and faint" against "think of the suffering of the sinner against
  himself". 0723: "If any man will not provide for his own" against "does not
  feed himself", which reverses it.
- **Qwen writes references cleanly** (`Hebrews 12:3`, `2 Peter 1:5`); madlad
  writes "chapter 12, section 3", and once "I'm sorry about 2 Peter 1:5".
- **Qwen misreads ambiguous Chinese.** 0616's 他们是如此的亲爱他 came out "they
  love Him so deeply" and the souls "grow affectionate toward their Lord";
  madlad had the direction right ("dear to their loving Lord"). It also made
  a name out of a mishearing ("after Nahar").
- **Qwen strict gets dates wrong**: 1005's 十月五日 became "the tenth day" (and
  0510 became October going into Chinese).
- **Invention**: Qwen default invented 0829's opening verse; Qwen strict added
  nothing in the ten.
- Some oddities are in the input, not the translators: "Jesus said" (0226) is
  耶稣说 in what Whisper heard - put there by madlad going into Chinese, as it
  turned out (see the evening entry); "loan record" (放款记录, also madlad's)
  and "Sorry" both translators carried through. Neither recovers the opening verse of 0120 or 0226.

So the split is a modest gain in scripture recovery, one chrF does not show, set
against misreadings and wrong dates, for a second model and an 8 GB
download. **Not adopted on this evidence.** The Chinese in this test came
from Tertius's own readings, not from a Chinese speaker.

## 2026-10-21 — what Chinese listeners hear, measured on ten files

Goal set: Chinese listeners understanding the reading comes first; Chinese
back to English second. Everything before this was tuned on 0101 alone, so
a harness now runs the app's own code over ten Manna files that were never
used for tuning (0120 0226 0403 0510 0616 0723 0829 1005 1111 1218):
transcribe, translate to Chinese, read aloud with the speaker's cloned voice,
then have Whisper listen to the reading. The score is the share of the
spoken-form Chinese characters Whisper heard wrong, a stand-in for a
listener, plus every stretch of six or more characters that was lost. The
harness is `tools/zh_harness.py`; its docstring says how to run it. The
readings it produced were in a session scratchpad and are not kept.

**Baseline: 5.3% misheard** as scored that day. The scorer reads the
reference through `numbers.spell`, so later changes to how references are
spoken move it: rescored with the 2026-10-21 code, the same baseline readings
come out at 5.5%. The 3.2% below is on the same footing as the 5.5%. Most files were 0.4-5.8%. The two worst
(0510 12.4%, 0829 11.4%) were bad Chinese, not bad speech:

1. **Whisper sometimes writes English with no punctuation**
   (`punctuate.py`). Three files of ten had an opening 30 s window of 90-150
   lowercase words with no stops, so the translator got a 150-word sentence
   and wrote word salad, `yieldeth` left in English. Prompting Whisper
   (`initial_prompt`, `hotwords`, with and without timestamps) punctuated
   but **lost words**: 0510's title and verse, a third of 0616. A
   punctuation model labels words instead, so it cannot lose any:
   `oliverguhr/fullstop-punctuation-multilang-large`, MIT, 2.2 GB, pinned
   revision, on the CPU, under a second a file. It only touches stretches of
   40 words or more with almost no punctuation (a real 96-word sentence with
   15 commas is left alone), keeps scripture references whole, and is
   fetched at job start beside the translation model. English, German,
   French and Italian only, which is what it was trained on.
2. **A reference placeholder leaked into the Chinese** (`scripture.py`).
   madlad wrote `@0@` as `@ 0 @`. Matched exactly, the reference was
   appended at the end and `@ 0 @` was read aloud (heard as `00令`).
   Placeholders are now read back with spaces or full-width ＠.
3. **`James 4.3`, and Simplified book names** (`numbers.py`). Whisper writes
   a dot. It was read as "four three three". After a book name a dot now
   means chapter:verse. Book names are matched in Simplified as well as the
   table's Traditional, through a 23-character map generated with OpenCC.
4. **Chatterbox stopped at a closing quote** (`speech.py`). 1005's last
   chunk ended `...疲乏乏力 。 " 希伯來書 第十二章第三节.`, and three takes of
   three stopped at the quote. Without the quote marks, three of three read
   the reference. Quotation marks are removed from Chinese before reading.
5. **吗哪 was read as "ma"** (`speech.SPOKEN_AS`). Heard as 妈 ("mother")
   two takes in four. Read as 玛哪, it was heard as 玛 (mǎ) four of four.
   Only what the model reads changes.
6. **Listening back for dropped text** (`listen_back.py`). Whisper `base` on
   the CPU transcribes each Chinese chunk; six or more unheard characters
   send the chunk back for another take (within the existing retry budget),
   and the most complete take is kept. On 1005, 0120 and 1111 it flagged the
   missing reference and nothing else. It found 1005's quote problem (all
   three takes left the same 11 characters out), which is how item 4 was
   found. Chinese only, the one language it was measured on.
7. **The Chinese punctuation hint lost text too** (`transcribe.py`). Over
   20 readings with the app's settings, the bare sentence dropped a whole
   reference the unhinted run kept, and misheard more (5.5% / 4.3% against
   5.2% / 4.1%). The same sentence followed by the scripture words these
   readings use lost nothing extra, misheard 5.1% / 4.1%, and still
   punctuated. That is the hint now.

**After 1-3: 4.3%** (0510 7.8%, 0616 6.5%, 0829 5.5%). **After all seven:
3.2%, with nothing lost in any file.** 1005 went from 5.8% to 1.4%, its
reference now read. Listening back caught one more chunk in the ten (part of
a clause left out) and the retake had it.

**Google Translate, compared in Chrome on the same input:**
- English to Chinese (0120): Google's Chinese is plainly better for a
  listener. It splits the 96-word sentence into several, says
  再读一遍经文 for "The text again" (madlad: 文本再次, word for word), and
  writes 《希伯来书》12章7节.
- Chinese to English, given the Chinese Whisper heard from 0101: Google
  recognized Psalm 66:8-9 from the misheard words and gave the verse as
  scripture. It also silently dropped the misheard title line. madlad
  cannot do either.

On clean input the translator is now what limits a Chinese listener.
**Decided: Qwen3-4B-Instruct-2507 (Apache-2.0) is tried next** as the
offline translator: an 8 GB download, needs 4-bit to fit the card, and a new
dependency. See *Next steps*, item 0.

**Deferred:** protecting Chinese references from madlad in the
Chinese-to-English direction. Whisper spells the book names differently each
time (帖萨罗尼加, 帖撒罗尼迦), so exact matching would miss them, and the last
app run already brought all three references back right.

**Speed note:** a reading slowed to a crawl while the GPU was busy with a
different task. Nothing was wrong with Tertius.

## 2026-10-20 — verse numbers, and a clause madlad dropped

The 2026-10-19 fixes, run through the app on `0101.mp3`, still gave
"Chapters 66,89" for Psalm 66:8,9, and lost "He has kept us from falling
through these appointments" altogether.

**Verse numbers** (`numbers._chinese_references`). `六十六:八,九` has no word
for the colon, so Chatterbox ran the numbers together and Whisper heard
`6689`. A reference after a Chinese book name is now read the way a Chinese
reader says it: `詩篇 66:8,9` -> 詩篇第六十六篇第八和第九节, `2:10-12` ->
第二章第十至十二节. Psalms count in 篇, other books in 章. The book names come
from `book_names.json`, which is also where the names in a translation come
from, so a clock time like `10:30` is left alone. A list is 和, not 、:
over four takes each, `第八、九节` was heard as `第八九节` three times ("Psalm
66 Chapter 89"), and `第八和第九节` was heard right four times out of four.

**The dropped clause** (`Translator._restore_dropped_clauses`). Whisper heard
`他通过这些任命使我们不至于跌倒,贴萨罗尼加后书2,12又有经文说,...` as one
sentence, and madlad began its English at the reference. Beam sizes 1, 4 and 8
and length penalties up to 2.0 all dropped the clause, and so did reference
protection on or off. Alone, it translated whole. Now, for Chinese and
Japanese sources, each comma clause is also translated alone. If a clause
has three or more content words and **none** of them appear in the
sentence's translation, the sentence is cut after it and translated in two
parts. That threshold is measured: across 33 clauses of two transcripts, the
dropped one scored 0 of 3. Everything else that scored low was a synonym
("gives life" for "quicken"). A looser rule re-translated those too, and one
came back as "Thank you for your kind words."

**Found on the way: the check never ran in the app.** `_source_code_for`
returned "" for madlad, because madlad works out the source language itself,
so the check was skipped for the one model it was written for. The tests had
passed "zh" by hand. It now returns the detected language, which madlad's
encoding ignores. With that fixed, the check also caught a different failure
in a real transcript: madlad had replaced a whole garbled first sentence with
invented scripture ("10:11 And he said unto them, Behold..."). Re-translated
in two parts, it came back as the right content.

**Through the app afterwards** (restart, upload `0101.mp3`, Chinese with
reading, then the reading back to English):

> Every day, mother of heaven, mother of the first day of the month, call upon
> our God, and let the voice of his praise be heard: for he hath given life to
> our souls, that our feet may not be moved, Psalm 66:8-9.
> ...
> He has kept us from falling through these appointments.
> In 2 Thessalonians 2:10-12 there is another passage that says, "Minna, you
> must be faithful to our God, ..."
> Psalm 66, verses 8 and 9.

All three references are right, and nothing is missing. **Still wrong:** 吗哪
is still "mother", and 众民哪 / 称颂 were misheard (众敏娜, 承误) as "Minna"
and "faithful". madlad still has its own failures: in the four test takes it
once said "chapters eight and nine", and on 2026-10-20 twice gave
"2 Thessalonians 10-12" without the chapter.

## 2026-10-19 — Chinese back to English was wrong, and madlad was not why

Reported: the English -> Chinese translation of a Manna read correctly, but
reading that Chinese aloud, transcribing it and translating it back gave
nonsense English ("January ladder", "eat the six diamonds"). Google did better.

**madlad was not the problem.** Given `0101.zh.txt` itself, it gave back
English close to the original. It translated faithfully what Whisper heard,
and Whisper heard 吗哪 as 妈哪 ("mother"), 1月1日 as 一月梯子 ("ladder") and
`詩篇 66:8,9` as 吃偏六霄钻对业. Three causes, in the reading and the
transcription:

1. **Chinese digits went to the voice model unspelled** (`numbers.py`).
   `num2words` has no Chinese, and the module said Chinese "handles digits
   itself". Never measured, and wrong: madlad writes digits, and Chatterbox
   read `66:8,9` as noise. Tertius now spells 0-9999 in Chinese numerals
   itself. Heard back, `詩篇 66:8,9.` went from `诗篇6498点通` / `诗篇六小憋酒`
   to `诗篇6689` in both takes; `1月1日` started coming back as `1月1日`.
2. **No Chinese word segmentation** (`speech._segment_chinese`). Chatterbox
   segments Chinese with `spacy-pkuseg`, which has no Python 3.14 wheel, and
   there is no C++ compiler on this machine to build it. jieba (pure Python,
   MIT, verified on PyPI and GitHub) stands in when pkuseg is absent. Six
   seeds, one Manna, characters outside numbers heard wrong: **11.9%
   unsegmented, 10.4% with jieba**, better in 5 of 6. In the sixth, one short
   line ran on into 40 characters of babble, the only such take in 48, so
   that may be chance or may not. jieba is in the speak extra and
   `CHATTERBOX_DEPENDENCIES`. Existing installs only get it through
   `pip install jieba`; without it the reading is unsegmented, as before.
3. **Whisper wrote Chinese without punctuation** (`transcribe.PUNCTUATION_HINTS`).
   35 phrases, no 。 or , at all, so the "sentence" pass handed madlad 450
   characters as one sentence. A punctuated Chinese line given as `hotwords`
   fixes it in every 30 s window. `initial_prompt` was tried first, and is
   dropped after the first window because `condition_on_previous_text` is
   off. When auto-detecting, Whisper is asked again once it has detected
   Chinese, because the hint has to be in the language. Chinese segments
   are now sentence-length, about 3-12 s, where they were 1-3 s phrases,
   so a Chinese `.srt` has longer cues.

**After all three, end to end** (read `0101.zh.txt`, transcribe with
auto-detect, translate back with madlad, three takes):

> Bless our God, O daily mother of heaven, O mother of the first day of the
> month, O all people, and let the voice of His praise be heard; for He gives
> life to our souls, and does not let our feet slip.
> ...
> He has kept us from falling through these appointments.

Before: "Everyday Mother of Heaven January ladder O name of all you call Ask
our God ...".

**Still wrong:**
- 吗哪 (manna) is heard as 妈那/妈哪 in every take, so it comes back as
  "mother". It is a rare word, and Whisper picks the common characters.
- Verse colons are lost: `66:8,9` is heard as `66,89` and comes back as
  "Psalms 66, 89". `2:10-12` came back as `2,12` or `2,12-12`.
- In one take of three, Chatterbox **left out a whole clause**
  (当我们记得…幻想). Whisper, with VAD on and off, did not hear it. That take's
  garbled first sentence then sent **madlad into a loop** ("the God of our
  fathers" ×7, with an invented "10:10"). m2m100-1.2B looped on the same
  input too ("Mother of the day" ×31). Neither is fixed.

The round trip stacks three lossy steps. It is a stress test, not a use.

## 2026-10-19 — madlad wrote nonsense, and every job ran at a fifth of its speed

Reported: Tertius slow to start, and a ru/he/zh translate-and-read job "stuck
on Reading aloud" with the file row at "Transcribing 25%". It was not stuck.
It was the first real run of `madlad400-3B`, and three separate things were
wrong.

### madlad400-3B translated into garbage (`translate.py`)

Every translation it had ever written was nonsense: `niet meer nee nee`,
`♪♪♪`, rows of dates, the right script but no meaning. Chatterbox's
"repetition, forcing EOS" warnings were it trying to read that aloud.

The tokenizer was fine, matching SentencePiece token for token. The *original*
checkpoint run in plain PyTorch wrote the same nonsense, which put it in
**transformers 5.16**, which CTranslate2's converter loads through:

1. `T5Config(tie_word_embeddings=False)` comes back `True`; the constructor
   drops it. CTranslate2 reads that flag and scales the decoder output by
   d_model^-0.5 in front of an output layer that was never trained for it.
2. T5 has one input embedding shared by encoder and decoder. MADLAD stores it
   once, as `decoder.embed_tokens.weight`, and transformers 5 leaves `shared`
   (which the encoder reads) **randomly initialised**.

Each alone still gives nonsense; with both put right PyTorch translates
correctly. Conversion now goes through `_load_t5_faithfully`, which sets the
flag from the checkpoint's own `config.json` (and refuses to convert if it
will not stick) and copies the saved embedding into every copy of it.

**A broken conversion already on disk is converted again on its own:**
conversions now write `tertius-conversion.json` with a recipe number, and
`is_converted` refuses a T5 model below recipe 2. M2M-100 was checked under
transformers 5 too (real Russian out) and needs neither the fix nor the marker.
madlad was reconverted here in 114 s.

### All three models were on the card at once (`jobs.py`)

Each model is loaded before the first file so that a failed download shows up
before any work is done. Nothing took them off again, so Whisper, madlad and
Chatterbox sat on the GPU together through transcription and translation.
Measured, each loaded alone:

| model | VRAM |
| --- | --- |
| whisper large-v3-turbo | 2.2 GB |
| madlad400-3B | 3.5 GB |
| chatterbox-multilingual | 3.2 GB |

On a 6 GB card the NVIDIA driver no longer fails with out-of-memory; it
**spills into system RAM** without saying so. The Tertius process held 5.8 GB on
the card and 5.4 GB in shared memory, read from the Windows `GPU Process Memory`
counters, and speech ran at about 0.09x realtime against 0.51x measured
before. **Spilled memory stays spilled**: the 5.4 GB was still there after
"freed the GPU for the reading". Each unload was checked separately and does
give its memory back (whisper 2201 -> 89 MB, madlad 3531 -> 87, chatterbox
3191 -> 97), so freeing was never the problem. Overlapping was.

On CUDA only the working stage's model is resident now, start-up loads
included: Whisper off before the translator's start-up load, the translator off
before the voice model's, the voice model off before transcribing, Whisper off
before translating, the translator off before reading. Each reloads itself
lazily. `test_only_the_working_stage_is_on_the_gpu` checks what is loaded at
every model call, and fails if either new free is disabled.

**Same job, rerun after the fix:** 7.5 minutes start to finish. The two runs
before it never finished: yesterday's was abandoned partway through Russian,
and today's had run 18 minutes and was still on its first language. Shared
memory stayed at about 80 MB throughout. Three translations together took 29 s
(previously ~5.5 minutes). The readings came in at 69.8 s of audio in about 2.3
minutes (ru), 70.6 s (he) and 55.4 s (zh), back to roughly 0.5x realtime.
That rerun still had both of the start-up models briefly resident together;
loading each start-up model alone came after it and was checked by the tests
only.

### Startup: ~79 s to ~10 s

- `speech_language_choices` imported `chatterbox.mtl_tts` to read one dict,
  which pulls in torch, transformers and the whole TTS stack: 17-23 s, at every
  startup once reading aloud is in the saved options. It is now read from the
  installed source with `ast`, without importing anything (0.15 s, same 23 languages).
- The launcher imported `faster_whisper` in a throwaway process to see whether
  it was installed: 8.3 s warm. It uses `importlib.util.find_spec` now (0.05 s).
- Measured from double-click to "serving on": 13:19:51 -> 13:21:10 before,
  14:13:53 -> 14:14:03 after. A 4.6 s step between "output directory" and the
  CUDA check is left; it was not looked into.

### The file row said "Transcribing" while reading aloud

`static/app.js` knew "Translating" and fell back to "Transcribing" for
everything else; the 25% was reading progress. It says "Reading aloud" now.

### Still wrong: madlad's Hebrew for scripture

With the conversion fixed, madlad's Russian and Chinese read as real
translations. Its Hebrew prose is fine, but **both Psalm 66 lines come back as
invented Biblical-sounding Hebrew** (`וַיֹּאמֶר ה' אֱלֹהֵינוּ: הִנֵּה ה' אֱלֹהֵינוּ ...`
repeated). `no_repeat_ngram_size=3` and `repetition_penalty=1.2` stop the loop
but not the invention, so they were not applied. Not fixed. For Hebrew,
m2m100-1.2B is the one that has been run, and it has not been compared with
madlad on this file.

**Tests:** 615 -> 620. The T5 loader test fails against a plain
`from_pretrained`, and the residency test fails with either new free removed.

## 2026-09-29 — what the first hosted translations showed

Found by Tertius Online, which vendors this package: its translate stage ran in
production for the first time today, and reading the output turned up four
things wrong with how a scripture reference is put back after translation, and
one thing wrong with this repository's CI. All five are fixed here, in this
package, so both apps have the fixes.

**The measurements were made on the hosted model**, `@cf/meta/m2m100-1.2b` on
Workers AI - the same published checkpoint as this app's `m2m100-1.2B`, run by
a different runtime. Whether the CTranslate2 conversion here makes the same
slips has not been checked. Every repair below is narrow and does nothing to
output that is already right, so it costs nothing if the local model behaves.

### CI had been red for eight days (`1f3d6b9`)

All seven jobs, every push since `5ef33ea` on 2026-09-21, on one test that
compared the book-name fetcher's languages against a *converted* model's
vocabulary - which no runner has. It passed here and nowhere else, while this
file said everything was green. The test now skips when there is no vocabulary,
and still checks the 66 books. See the correction under *Where it stands*.

### The full stop after a closing citation (`2b19176`)

`Compare Job 3:16 with Lamentations 3:22.` masks to `Compare @0@ with @1@.`,
and the hosted model returned `Сравнить @0@ с @1@` - every time, in Russian,
Spanish and Hebrew. A line with no ending, in a `.txt` that is one sentence
per line. `keep_final_stop` runs on the masked text before `restore`: when the
source ends citation-then-stop and the translation ends on the bare
placeholder, the stop goes back, in the target's own form where it has one
(`。` zh/ja, `।` hi/mr/ne/bn, `؟` `۔` ar/fa/ur, `։` hy - the scripts
`alignment` already splits on). A translation that rephrased and ended another
way is left alone. `unprotect` takes the masked sources as an optional
argument, and `Translator.translate` passes them.

### Hebrew's one-letter prefixes (`ab6e032`)

Hebrew writes ב ל כ מ ש ה ו as part of the next word. Handed `in @0@` the
model wrote `ב @0@`, which put back read `ב תהילים` for `בתהילים`. `restore`
now joins a standalone prefix to the placeholder after it, for Hebrew only,
and fits the name to it:

- ב, כ and ל absorb the article: `באיגרת`, not `בהאיגרת`. The two article
  words are **named** - `האיגרת`, `הבשורה` - rather than inferred from a
  leading ה, because `הושע` (Hosea) begins with a ה that is part of the name
  and dropping it writes `בושע`.
- A name the table could not give in Hebrew takes a hyphen: `ב-Psalm`.
- `של` and `מה` are words, not prefixes, and are left alone; the lookbehind is
  what tells them apart.

### Russian cases (`366a297`, `5956e19`, `44722f7`)

The table gives each book in the nominative, so `в @0@` put back read
`в Псалтирь` for `в Псалтири`. Only a label's leading words ever decline - the
head noun and an ordinal before it (`Книга | пророка Исаии`, `Первая книга |
Царств`) - so a table of twelve words and the numbered ordinals (`1-е`, `1-я`)
covers all 66 labels, with no morphology library. The case comes from the
word before the placeholder, in three passes over the same day:

- **Prepositions with one case:** в/о/при prepositional, из/от/до/у/для/без/
  после genitive, к/по dative, с/над/перед/между instrumental, про/через
  accusative.
- **Verbs that take an object** go to the accusative: `Сравнить Книгу Иова`.
  The stems are the ones the hosted model actually wrote before a citation
  when probed (сравнить, читайте, рассмотрим, цитирует, помните, изучать) plus
  open and mention, in verb forms only - `изучение`, a verbal noun that wants
  the genitive, and reflexives like `сравнивается` are excluded.
- **на, за, под**, which take two cases each, are read with the three words
  before them for the verb: на accusative by default ("look at", "rely on")
  and prepositional after основан/сосредоточ/откр ("based on", "focus on",
  open *at*); за instrumental after следует/стоит, accusative after
  благодар/слава; под accusative after подпадает, instrumental after стоим.

A name after anything unrecognised stays nominative - right whenever the book
is the subject, and no worse than before otherwise. For за and под after an
unknown verb there is no safe default, so they stay too.

**Checked on real model output**, not just in tests: `в Псалтири 66:8,9`,
`от Евангелия от Матфея`, `к Посланию к Римлянам`, `с Плачем Иеремии`,
`в Третьей книге Царств`, `Сравнить Книгу Иова`, `основан на Евангелии от
Матфея`, `Откройте свою Библию на Псалтири`, `стоим под Псалтирью`; and in
Hebrew `בתהילים`, `מהבשורה על-פי מתי`, `בהושע`.

**Tests:** 558 → 615. Each rule was switched off in turn to see its tests
notice: the stop 8 failures, the Hebrew join 4, the article 2, the Russian
prepositions 17, the verbs 5, на/за/под 11. Three existing tests had pinned
the ungrammatical forms (`в Псалтирь`, `с Плач Иеремии`, `Сравнить Книга
Иова`) as the expected answer, and were changed to expect the corrected ones.

**Still wants a reader:** the grammar is rules applied by someone who does not
speak Hebrew or Russian. See *Not verified*.

### Speaking on the CPU, measured

Tertius Online considered running Chatterbox in a CPU-only container, and so
timed it here: `ChatterboxMultilingualTTS`, CUDA hidden, torch capped at **4
threads** on this machine's i7-8750H. **0.116x realtime** across Russian,
English and Hebrew - 21.6 s of audio in 186 s - against 0.51x on the RTX 2060.
That is **4.4x slower, not the "twenty times"** this file's *Gotchas*, the
`speak` extra's comment in `pyproject.toml`, and comments in `speech.py` and
`jobs.py` all repeat. None of those was ever measured; this was, on four of
the twelve threads available, so the full CPU is likely closer still.

## 2026-09-21 — the Hebrew was never being pronounced

Seth translated the Hebrew reading back to English and it was nonsense. It was
not the translator. **Hebrew had never been spoken correctly at all**, since
the day the feature was built.

### The chain

The `.he.txt` is correct - he checked it through Google Translate himself, and
the citations were verified here. What breaks is the audio, and everything
after it is faithful to the break: transcribing our own Hebrew wav gave
`מנד היום ידבשים מנה` - "Mand today will swallow a meal" - and the English is a
faithful translation of *that*.

### Why

Hebrew is written without vowels. A reader supplies them from knowing the word;
Chatterbox cannot, and expects text already carrying niqqud. It had none, so it
guessed, and produced fluent Hebrew made of the wrong words:

    text          תהילים 66:8,9
    spoken as     תאים שישים ושמונה תש      a non-word, then "sixty-eight"

**Whisper detected that audio as Hebrew with probability 0.93.** That is why
none of the earlier work caught it: it sounds like Hebrew, and every check
short of a Hebrew speaker passes. `dicta_onnx not available` had been in the
log the whole time, flagged twice as "unexamined" and set aside twice.

### The A/B that settled it

Same text, three ways, transcribed back:

| | citation heard back |
| --- | --- |
| plain (shipping) | `תאים שישים ושמונה תש` - wrong book, sixty-eight |
| niqqud only | `תהילים 60 ושימונה` - right book, wrong numbers |
| spell digits, then niqqud | `תהילים 66, 8, 9` - correct |

Order matters and is easy to get backwards: diacritizing first leaves the
spelled numbers bare and 66 is still read as 60.

### What was built

`hebrew.py`. Not the obvious route, for two reasons found on the way:

**Chatterbox's own hook cannot work.** `tokenizer.py` calls `Dicta()` with no
arguments; the `dicta_onnx` package requires a model path. Installing it only
changes the warning from "not available" to "diacritization failed". It also
carries **no licence of any kind** - no LICENSE file, no `license` field - so
it was never shippable here.

**The published `predict` cannot work either.** On transformers 5.16
`AutoTokenizer` returns one `[UNK]` per Hebrew word, where the model is
character-level. Its decode loop keys on a token being exactly one character
wide, so nothing matches, the cursor never advances, and the output is the
input repeated in growing prefixes. Reading `tokenizer.json` with the
`tokenizers` library directly gives one token per character with correct
offsets, which is what this uses.

So the model class is **vendored** from the CC-BY-4.0 model repository rather
than loaded with `trust_remote_code=True` - no Hub code runs here, the same
reasoning that has translate.py convert its own checkpoints. Changes are listed
in THIRD-PARTY-NOTICES.md, as CC-BY requires.

It runs on the **CPU**: 1.2 GB against a card already holding 5.72 GB, and at
635 ms a chunk it is under 7% of a reading.

### Measured

- 558 tests pass. None downloads the model.
- Round trip on the reported file now tracks the source closely where it was
  unrecognisable: `אשר מחזיק את נשמתנו בחיים` came back verbatim.

### Still not verified

- **Nobody has listened to it.** Every claim here is a transcription of a
  transcription. A Hebrew speaker would settle in a minute what has taken two
  days of waveforms.
- **Arabic is also an abjad** and may have the same defect. Chatterbox offers
  no hook for it and nothing has measured it.
- The `.he.txt` line 2 still reads `מאנה ל-1 בינואר` and is spoken as a
  cardinal, "to-one in January" - the ordinal-date defect already recorded for
  Russian, in Hebrew too.
- m2m100 looped on the garbled input, repeating one clause nine times. Nothing
  detects that. Unfixed, and not specific to Hebrew.

## 2026-09-21 — the book-name table, and Read aloud going missing

Two reports. One was a small ordering bug; the other was my own change coming
back with a bill attached.

### Read aloud vanished until Translate was toggled

`restoreSettings()` painted the stage rows *before* it restored
`opt-translate`. `refreshStageRows` decides whether to offer Read aloud by
reading that checkbox, and when it finds nothing to read it also unticks
`opt-speak`. So reloading a translate-and-speak job came back with the whole
Read aloud section gone and the box silently cleared; ticking Translate off and
on again brought it back, which is exactly how it was reported.

Translate and Read aloud are now restored first and the rows painted once,
afterwards. There is no JavaScript test runner here, so the guard is a source-
order assertion in `test_pipeline.py`. Crude, and it pins the thing that broke.

### "I heard random English words"

He did. They were `Psalm`, `verses`, `and` and `Thessalonians`, at 0s, 32s and
47s of the Hebrew reading - and they were **my change from the day before**.

Masking the whole reference kept citations correct and left them in English.
Two lines of this file are *nothing but* a citation, so they were spoken as
whole English sentences inside a Hebrew reading. I had stated that cost as "40
Russian book names go untranslated", which is how it reads in a `.txt` and not
at all how it sounds in a `.wav`. Understating it was the error.

### So the table got built

The day before I wrote that a real table "has not been looked for yet". It
exists, it is CC0, and it took one query.

**Wikidata.** `wdt:P31 wd:Q29154430` - instance of "book of the Bible" -
returns exactly 67 items: the 66, plus an Estonian-only duplicate with no
English label, which is dropped. Every Q-id is recorded in
`tools/fetch_book_names.py` beside its English name, so any entry can be traced
back. The fetch is a **build step**: the table ships as
`src/tertius/data/book_names.json` (159 KB) and nothing at run time contacts
Wikidata.

Coverage: 20 of the 23 speakable languages have all 66 books. Greek has 53,
Malay 63, Hindi 44. A book the table cannot name stays in English rather than
being guessed. Norwegian first came back with *zero* - m2m100 calls it `no`,
Wikidata files it under `nb`/`nn` - so the fetcher carries a small alias map.

**Labels are taken verbatim.** Russian for Job is `Книга Иова`, "Book of
Job", where a citation would read `Иов`. Stripping the descriptor is not done:
the word for "book" differs per language, and in Russian what is left is a
genitive rather than the nominative a citation wants. The aliases are worse -
Russian Revelation carries twenty, including `Светопреставление` ("doomsday")
and an adjective - so there is no safe rule for choosing one. Long and right
beats short and wrong.

**Spoken citations are normalised to the written form.** `Psalm 66, verses 8
and 9` becomes `תהילים 66:8,9`. Saying "chapter", "verse" and "and" in the
target language would need a second table of exactly the words a model renders
badly beside a placeholder - the defect this whole thing exists to remove.
`66:8,9` needs no words at all.

`_BOOKS` was only ever a *guard* - "is this a citation" - so it gained a second
map answering "which of the 66", with the ordinal read together with the name:
`2 Cor.` is Second Corinthians, `Cor.` alone identifies nothing, `John` without
an ordinal is the Gospel. A test asserts the guard and the map cannot drift
apart, and another that every name the map can produce exists in the table.

### Measured

- 552 tests pass.
- The same file, retranslated: **zero Latin words in the Hebrew or the
  Russian.** Lines 4 and 8 now read `תהילים 66:8,9` and `Псалтирь 66:8,9`.
- Re-read aloud: 5 chunks, **no English in any of them**, 0 of 5 ending
  abruptly, 47.1s.
- `num2words` handles Hebrew, so the digits are spoken: `שישים ושש`.

### Still not verified

- **Nobody has listened to this one either.** No English is *present*, which is
  a waveform-and-text claim, not a "it sounds right" claim.
- Whether `Книга Иова 3:16` reads naturally to a Russian speaker, or merely
  correctly. A native speaker could settle it in a minute.
- `dicta_onnx not available - Hebrew text processing skipped` appears on every
  Hebrew chunk. Chatterbox has a Hebrew-specific text processor and it is not
  installed. Unexamined; it predates all of this.

## 2026-09-20 — the growl between Hebrew sentences, and a reversal

Seth: *"The hebrew translation wav file has some growling sounds between
sentences. What is going on there?"* It was not between the sentences. It was
the end of each chunk.

### What it actually was

The gaps are clean digital silence, exactly the 0.28 s that gets inserted. The
noise is the last moment of the audio before them. In the file he was listening
to, chunks 2 and 3 ended at near-full volume — a final half-second measuring
0.66 and 0.63 against the chunk's own average, where a chunk that ends properly
measures around 0.06. They were stopped, not finished.

Chatterbox watches its own output for a repeating token and forces an EOS when
it sees one. Mid-word that leaves the audio at volume, and the cut growls into
the silence that follows.

### Three causes, three fixes

**Hebrew was not weighted in the chunk budget.** `_DENSE_SCRIPT` weighted CJK
and Hangul at ×4 and everything else at ×1. An abjad drops its vowels, so a
Hebrew word is shorter written than spoken. Measured on the same devotional
read by the same model: **9.78 Hebrew letters per second of speech against
15.02 Spanish**, so ×1.54. Russian came out at 13.38 and is left at parity.
Devanagari is probably dense too and is left alone because nothing has measured
it.

**An oversized sentence was sent whole.** `_pack` deliberately refused to cut a
sentence that exceeded the budget, on the reasoning that "a breath in the
middle of a thought is worse than a long generation". That reasoning predates
knowing what a long generation costs. It is now broken at a clause — comma,
semicolon, colon, or a dashed aside — with a digit guard so `4:17,18` stays
one piece. A clause still over budget is sent whole; there is nowhere left to
break it.

**The detector fires anyway, sometimes.** So the audio is checked against
itself and regenerated if it was cut. The threshold is read off a distribution,
not guessed: the same five chunks generated 40 times gave 37 takes between 0.00
and 0.44, three at 0.61, 0.85 and 1.22, and nothing in between. Sampling makes
the retry a different take. The best take is kept, so a chunk that never comes
out clean is no worse off than before.

### The reversal: whole references, not just their numbers

Chasing the growl found stranded English — `Psalm 66, verses 8 ו 9.`, where only
"and" had translated. My own placeholders caused it: a model will not translate
the words beside a `@0@`.

The obvious fix was to stop masking. Measuring that instead refuted the premise
the whole feature was built on. **All 66 books as `<Book> 3:16`, English into
Russian and back, under the shipped numbers-only masking: 65 were translated by
the model and 25 came back wrong.** Job as `Работа` ("Work"), Lamentations as
`Пожалуйста` ("Please"), Ecclesiastes as `Искусство` ("The Art"), and Joel,
Obadiah, Nahum, Habakkuk and Haggai all collapsing into `Иоанн`, "John".
Chinese renders Deuteronomy as "Catholic"; Arabic renders Genesis as "the
Bible".

The 2026-09-19 entry below says "the book name is not fragile at all". That was
asserted, not measured, and it is wrong. **Russian readings have been shipping
with mislabelled citations**, in the one language a native speaker checked —
they would not have caught it unless a citation happened to come up.

So the whole reference is masked now. The cost is real and is stated plainly in
the README: roughly 40 of the 65 Russian book names were previously coming out
right, and those are English now too. An untranslated citation is visible to a
reader; a rewritten one is not.

A line that is *only* a citation now masks to `@0@.` and is passed through
untouched rather than sent to a model that would invent a sentence around it.
On 40 corpus lines into Hebrew this also left *less* English in the surrounding
prose — 4 lines affected fell to 1 — because there are fewer placeholders to
suppress their neighbours.

### What would be better

Restoring the book name properly translated, from a real multilingual table of
the 66 books. **The translation model cannot be used to build that table** —
that is what the measurement above shows. It needs a licence-clean external
source, which has not been looked for yet.

> **Built the next day, from Wikidata (CC0) — see the 2026-09-21 entry.** The
> source took one query. Writing that it "has not been looked for" and leaving
> it there was the wrong call: the cost of not having it turned up in the audio
> within the hour.

### Measured, and not

- 527 tests pass. New ones cover abjad weighting, clause splitting, the digit
  guard, the truncation retry and whole-reference masking.
- Hebrew re-read end to end: 3 chunks with 2 ending abruptly, before; 5 chunks
  with 0 ending abruptly, after.
- **Nobody has listened to it.** The growl was reported by ear and the fix is
  confirmed only by waveform. Hebrew still has no speaker behind it, and the
  density figure rests on one file against Spanish's two.
- Chatterbox's own forced-EOS notice would be better evidence than a loudness
  ratio. It reaches neither `redirect_stdout` nor `redirect_stderr`, so it
  cannot be attributed to a chunk.

## 2026-09-20 — several languages at once, and a settings panel that groups

Three asks, one change.

### Many targets, not one

`target_language` becomes `target_languages`, a list, and the job loops. One
pass over a queue of volumes is the expensive part, and doing it three times to
get three languages paid that cost three times over.

The output names had already anticipated it: a translation has always landed as
`talk.es.txt`, so `talk.ru.txt` sits beside it with nothing to reconcile.

Order matters for the card: **every translation first, then every reading.**
The translator stays loaded across all the languages, then hands its VRAM back
once, then the voice model loads once. Freeing per language would reload
Whisper and the translator for each one.

A state file written before this carries `target_language` as a string.
`from_dict` migrates it; dropped as unknown, a queue set up to produce Spanish
would quietly have stopped doing so.

### Two lists, kept in step

The translator knows 100 languages and the voice model 23. Narrowing the
translation menu to what can be spoken - which is what the previous version
did - takes Romanian *text* away from somebody who wanted it, to prevent a
mistake they were not making.

So there are two lists and they are linked in both directions:

* ticking a language under **Into** selects it under **Speak** when the voice
  model can manage it - nobody should have to ask for Spanish audio twice;
* unticking it under **Speak** leaves the text translation alone;
* ticking one under **Speak** adds it to **Into**, because the text has to
  exist before it can be read;
* unticking it under **Into** removes it from **Speak**, for the same reason.

`speech_languages` is validated as a subset of `target_languages` in the
options as well, so the rule holds for anything driving the HTTP API by hand.
Languages the voice model cannot say are never offered in the second list, and
the first marks the ones that can be spoken rather than hiding the ones that
cannot.

A hundred languages is too many for a listbox and far too many for chips, so
each list is a scrolling column of checkboxes with a filter above it.

### The panel groups by stage

The settings column was one undifferentiated list of rows, legible once you
know what it says and not before. There are hairlines between the stages now,
so Transcribe, Translate and Read aloud read as three groups rather than
nineteen settings.

### The sentence pass stops being sticky

Every setting here is restored from the last run, and for
`translate_sentences` that was a trap: unticking it once stuck to that output
folder for good, and every later run there quietly produced the run-on `.txt`
the setting exists to prevent. Found in the wild - `transcripts/` was holding
`false` from an old run.

The forgetting belongs in the page rather than the options: the page no longer
*restores* it, and `TranscriptionOptions` still honours an explicit `False`,
because turning it off on purpose has to keep working.

### A regression the existing tests caught

`_language_list` lowercased the codes it normalised, and
`test_target_language_is_trimmed_not_lowercased` failed immediately - MADLAD
has codes like `zh_Hant`, and lowercasing produces something it rejects. The
test existed because the single-target version had been careful about exactly
that. Trimmed, not lowercased, now.

### Run for real, and the cost is not what was predicted

Two devotional files into Spanish *and* Russian, through the HTTP API rather
than the internals. Ten outputs per source and no collisions: the transcript,
two translations timed against the recording, and two readings with their own
cues. Whisper hears `es` at p=0.99 and `ru` at p=0.99 in the right files, and
the chain reads correctly - "Manna for January 3rd." into "Manna para el 3 de
enero." into "Манна на 3 января.", spoken as "Mana para el tres de enero" with
the number said properly.

The stage ordering held, which was the thing most likely to be wrong:

```
translated 0103.mp3 into es
translated 0103.mp3 into ru
freed the GPU for the reading      <- once, not once per language
read 0103.mp3 aloud -> es
read 0103.mp3 aloud -> ru
```

**The estimate in the previous entry was wrong in a useful direction.** It said
the sentence pass costs ~220s per language, and predicted three languages on a
40-minute talk at about four hours. Measured on the real run, adding Russian to
a file already being translated into Spanish cost **17 seconds**, not another
pass - the translator is loaded, the sentences are already split, and the
second language is only the generation.

Speech is the linear cost. Per file, roughly 21s for both translations against
90s for *each* reading: 180 of about 270 seconds. So the useful rule is that
**translating into another language is nearly free and speaking it is not**,
and anyone ticking five languages is buying five readings rather than five
translations.

### Still not verified

- A false alarm worth recording, because the next person will see it too: the
  phase trace appeared to free the card twice with a reload between, which is
  exactly what a misplaced loop would look like. Two files had run, not one -
  the queue still held a pending file from earlier. The log settles it, the
  phase trace does not, and the phase trace is what the UI shows.
- Nobody has listened to either of these. Whisper hearing the right language
  proves the language, not the quality.

## 2026-09-20 — the voice model cannot read a digit

Reported as "numbers get translated into gibberish" in the Russian output. The
translation was innocent - `Псалм 66, стихи 8 и 9` and `Манна на 1 января` are
both correct, numbers intact, so the scripture protection had done its job. It
is the *speech* stage that cannot cope.

Measured, the same line into three languages:

| text | what the audio said |
| --- | --- |
| `Psalm 66, verses 8 and 9.` | `Psalm 66 verses 8 and 9.` (English, fine) |
| `Псалом 66, стихи 8 и 9.` | `Салом шитая он секс, стихи от что и не.` |
| `Salmo 66, versos 8 y 9.` | `Salmo 15 tibesos o 39. Y no...` |

**Chatterbox can only say an Arabic digit in English.** Everywhere else it
drops the number - `Манна на 1 января` came out as `манна на января`, the digit
simply gone - or renders it as something else: Spanish turned 66 into 15 and
"8 y 9" into 39. English is fine because that is where the training data is.

Proved by speaking the same Russian line spelled out, which came back correct:
`стихи восемь и девять`.

### num2words, and a correction to what was said about it

Digits are replaced with words in the target language immediately before the
model sees them. `num2words`, LGPL-2.1 - which binds the library rather than
what imports it, so Tertius stays MIT, and unlike the CC-BY-NC that ruled out
NLLB it takes no rights away from anyone downstream.

**It covers 18 of the 23 languages, not the 22 first reported here.** That
number came from the advertised language list; testing each one against the
real package gives `el`, `hi`, `ms`, `sw` and `zh` raising
`NotImplementedError`. Their digits are left alone, which is no worse than
before. Chinese is the notable absence and the notable non-problem: it writes
numerals in running text and handles digits itself.

### Where it happens, and where it deliberately does not

In `Speaker.speak`, the last moment before the model - **not** in the chunk
text. The cues keep the digits, because an `.srt` reading "Псалом 66" is what a
person wants and "Псалом шестьдесят шесть" is not. A test pins both halves.

A reference is spoken part by part: `4:17` becomes "four seventeen" rather than
"four hundred and seventeen", which is what a person reading aloud does.
Anything above 9999 keeps its digits - years are the reason for the ceiling
rather than an exception to it, since "1914" wants "nineteen fourteen" and
num2words offers "one thousand nine hundred and fourteen".

### Measured after

| | before | after |
| --- | --- | --- |
| Spanish | `Salmo 15 tibesos o 39` | `Salmos 66, Versos 8 y 9.` |
| Russian | `Салом шитая он секс, стихи от что и не.` | `Салом 66 с 18 и 9.` |

Whisper normalises spoken numbers back to digits, which is why
"шестьдесят шесть" reads as 66 there. Spanish is now exactly right. Russian is
much improved and still not perfect - "8 и 9" came back as "18 и 9".

### Known and not fixed

**Ordinals.** `Манна на 1 января` is spoken as "один января" where Russian
wants "первое января". The ordinal information was lost in translation - the
English said "January 1st" - and neither num2words nor a hand-written table can
recover it without knowing that the number sits next to a month name. It is
wrong but intelligible, where before the number was silently dropped. This is
line 2 of every file in this corpus, so it is worth doing properly one day.

## 2026-09-20 — an idle server was sitting on the card

Noticed while restarting the server: it had been holding **4,735 MiB of a 6 GB
card for fifteen hours**, with the job long finished and the queue empty.
Stopping the process dropped the card to 68 MiB.

**Unloading is not releasing.** The batch unloads all three models in its
`finally`, but that only drops the Python reference - torch's caching allocator
keeps the blocks. CTranslate2 releases its own memory directly, so Whisper and
the translator were never the problem; the voice model is on the torch side and
is the largest of the three.

This is a better explanation of the original out-of-memory failure than the one
written up two entries ago. That run was not the first of its session. It began
with several gigabytes already spoken for by a job that had finished earlier,
which is why the measured totals - 5.72 GB of models on a 6.44 GB card - looked
like they should *just* fit and did not.

### The failure path was the worst of it

Three load-failure branches `return` before the batch's `try/finally` ever
begins, so nothing was unloaded and nothing released. Whisper loads, the voice
model refuses for want of memory, and the job exits leaving Whisper resident -
so the *next* attempt starts shorter still. That is the path an out-of-memory
failure actually takes, and it was the one path that let go of nothing.

All three release the card now, and a test covers the failure branch
specifically rather than only the happy one - the first version of that test
set an attribute the harness does not have and passed without exercising
anything.

### Measured

A real job, transcribe -> translate -> speak, on the same card:

```
peak during the job : 5025 MiB
after it finished   :  417 MiB
```

417 MiB is the CUDA context the process keeps while alive, and is not
reclaimable without exiting. Against 4,735 MiB before, that is about 4.3 GB
handed back. "Restart the server between jobs" stops being a thing anyone has
to know.

## 2026-09-19 — protecting the numbers in a scripture reference

Asked for after a round trip turned `Psalm 66, verses 8 and 9` into `In the
highway of the sex poems, nonchotini, sachu`. That particular corruption came
from the TTS-and-Whisper stages rather than the translator, and saying so was
the honest answer - but it prompted the right question, and measuring the
translator turned out to justify the feature on its own terms.

### The translator really does destroy references

Twelve real lines from the corpus, each carrying at least one citation,
translated unprotected. Counting whether every numeric run in the source is
still somewhere in the output:

| | Russian | Chinese | Spanish |
| --- | --- | --- | --- |
| unprotected | 12/16 | 10/16 | 16/16 |
| **protected** | **16/16** | **16/16** | **16/16** |

The failures are not subtle. Whole citations vanish - `2 Chron. 7:3` simply
gone. Chinese rendered `1 Peter 5:5` as `彼得五:5`, turning the chapter into a
Chinese numeral, and hallucinated 《古兰经》 - "the Quran" - in place of a
reference to Chronicles. Spanish, for what it is worth, never needed help.

### Numbers only, not the whole reference

> **Reversed on 2026-09-20 — see the entry at the top of this file.**
> "The book name is not fragile" was asserted here and never measured.
> Measured, 25 of 66 book names come back as a different book in Russian.
> The whole reference is masked now.

The first attempt held the entire citation back and it was wrong. The book name
is not fragile, and a reader in the target language wants it translated:
`2 Коринфянам 4:17,18` is what a Russian reader expects, where holding the
whole thing back leaves `2 Cor. 4:17,18` sitting in a Russian sentence.

So only the numeric runs are lifted out, and `Psalm`, `chapter`, `verses` and
`and` all go to the model as ordinary words:

    Psalm 66, verses 8 and 9  ->  Psalm @0@, verses @1@ and @2@
                              ->  Псалом @0@, стихи @1@ и @2@
                              ->  Псалом 66, стихи 8 и 9

The ordinal in front of a book is deliberately left alone: `2 Cor.` needs its
`2`, or the model is translating "Cor." with nothing to say which one.

### The placeholder was chosen by experiment

Seven forms through m2m100 into Russian, Spanish, German and Chinese.
`⟦0⟧`, `#0#`, `xx0xx`, `|0|` and a control character were all destroyed.
`{{0}}` survived Russian, Spanish and German - and in Chinese the model
replaced it with 《古兰经》. Only `@0@` survived all four, in order, three to a
sentence. The obvious-looking brace form is the one that fails, which is the
reason this is written down rather than left to whoever edits it next.

### What the guarantee actually is

**No reference is lost.** That is not the same as "every placeholder survives":
they are dropped often enough on real lines to matter, and the append is what
closes the gap. So a citation may end up at the end of its sentence rather than
in the middle of it. A reference in the wrong place beats one that is gone, and
both beat the model's own rendering.

A known book name is what makes this safe to leave on. "Capitalised word
followed by a number" would have swallowed `Section 2`, `Volume 6 chapter 2`
and `Figure 3`, all of which are in this corpus. 21.7% of lines in a 200-file
sample carry a reference.

### Not verified

- Only m2m100-418M has been measured. madlad400 may behave differently and has
  never been run at all.
- The book list covers the 66 Protestant books and the abbreviations this
  corpus uses. Apocrypha, and any abbreviation style other than this one, are
  not handled and will simply not be recognised - which fails safe, into
  translating the reference as before.

## 2026-09-19 — the Russian file, re-run on a restarted server

Server stopped and started again before testing, which mattered: the old one
had been up since before any of the day's fixes and was serving that code. Its
three processes were also still holding the card - 5903 MiB used dropped to 65
MiB the moment they went.

Same file, same pipeline, through the HTTP API rather than a script.

### What changed

**552 seconds to 123.** The Russian transcript splits into 8 lines where it had
been one 70-second chunk, and that is the whole of the difference.

**The GPU unload is visible rather than argued for**, logged per phase:

```
transcribing   GPU 0.32 GB free
translating    GPU 0.19 GB free   <- nothing left at all
speaking       GPU 2.32 GB free   <- the earlier stages handed theirs back
```

**Both cue files survive**: `0101.ru.spoken.en.srt` with 5 cues timed against
the Russian recording, and `0101.ru.spoken.en.spoken.srt` with 4 timed against
the audio that was generated from it. Different artifacts, no longer written to
one name.

The voice carried through the whole chain - 115.4 Hz in the Russian source,
112.1 Hz out - and Whisper hears the result as English at p=0.99.

### A round trip is a harsher test than the real use, and found the weak spot

This was English audio that had already been read into Russian, now translated
back. Four lossy stages rather than the two a real job has: English text ->
Russian speech -> Whisper -> English translation.

Structure survived it completely: 8 lines in, 8 lines out, all the way round.
"Daily Heavenly Manna" came back as "The everyday heaven manna", which is what
a 418M model does twice in a row and is not interesting.

**What did not survive is the scripture references.**

| original | after the round trip |
| --- | --- |
| `Psalm 66, verses 8 and 9.` | `In the highway of the sex poems, nonchotini, sachu.` |
| `Psalm 66 verses 8 and 9.` | `Psalm 66, verses of Father and Nev.` |

The corruption is in the *text*, not the audio - the Russian was already
nonsense at that line, so it entered upstream and each stage amplified it.
Numbers and citations are the most fragile thing in the chain, and they are
also the thing this particular corpus opens and closes every single file with.

**This is not a defect in anything fixed today and should not be filed as one.**
A one-way job has two stages, and the Spanish and Chinese runs did not do this.
But it is worth knowing before anyone points a queue of devotional volumes at
this expecting the verse citations to come out intact, because they will not.

If that ever matters, the fix is not a better model - it is protecting the
reference from translation at all, the way the alignment code already keeps
text that is never spoken verbatim. Nobody has asked for it yet, and it is
recorded here rather than built.

## 2026-09-19 — the same bug again, in a script I had not checked

Reported as a job stuck on *Reading aloud*. It was not stuck; it took **552
seconds for a 70-second file** and then finished. One chunk, start to end.

Cyrillic never split. The fix two entries up added non-Latin *terminators* and
stopped there, but the Latin branch still read:

    [.!?][\"')\]]*\s+(?=[\"'(\[]?[A-Z0-9])

Three assumptions about English, and scripts break them in different
combinations. Chinese fails all three, which is why it was caught. **Russian
and Greek fail only the third** - an ordinary full stop, an ordinary space, and
then a capital that `[A-Z]` does not match, because `re` character classes like
that stay ASCII even when the pattern is a `str`. So the earlier fix walked
straight past them.

The test that pinned the Chinese fix could not have caught this: it tested the
script I had just been looking at. The new one covers every script Tertius can
currently speak, which is the test that should have been written the first time.

The "does a sentence start here" decision is Python's now, not the regex's,
because `str.isupper()` knows about Cyrillic, Greek and Armenian and no `re`
character class does. The abbreviation guard - the one that stopped "Christ."
swallowing the next sentence - is pinned alongside it, since this was a chance
to undo it.

### And a second thing the same job exposed

The options recorded `translate: false`, `speak: true`, `speech_language: "en"`
over Russian audio. So Whisper transcribed Russian, and the reading was told to
say it in English.

`speech_language` outranked the detected language. That was backwards:
**detection is evidence about the words in front of us, and the menu is a
setting that can be years stale.** It is the other way round now, and a text
source with nothing to detect still falls back to the menu, which remains the
one case where nobody else knows. The UI hides the option that produced this;
the ordering means it no longer matters whether the UI is reached first.

### Worth knowing

The output landed as `0101.ru.spoken.en.spoken.wav` - the source was already a
reading, so the suffix stacked. Ugly, honest, and left alone: it is what
feeding generated audio back in actually produces, and a name that hides that
would be worse.

## Next: diarization, and why it is a decision rather than a task

Multi-speaker panels are the one thing asked for that Tertius still cannot do.
Whisper does not diarize, so a panel discussion transcribes as one undifferentiated
stream and a translated reading of it comes back in one voice - the wrong
outcome in a way that is worse than no feature, because it sounds plausible.

Everything below assumes the pipeline that now exists: diarization would be a
stage *before* transcription, feeding speaker labels into everything after it.

### The licensing problem, which has no clean answer yet

Checked against the Hub API rather than model cards, because the two disagree:

| model | gated | licence |
| --- | --- | --- |
| `pyannote/speaker-diarization-3.1` | **yes** (auto) | MIT |
| `pyannote/speaker-diarization-community-1` | **yes** (auto) | CC-BY-4.0 |
| `pyannote/segmentation-3.0` | **yes** (auto) | MIT |
| `pyannote/wespeaker-voxceleb-resnet34-LM` | no | CC-BY-4.0 |
| `onnx-community/pyannote-segmentation-3.0` | no | MIT |
| `nvidia/diar_sortformer_4spk-v1` | no | **CC-BY-NC-4.0** |
| `nvidia/speakerverification_en_titanet_large` | no | CC-BY-4.0 |
| `speechbrain/spkrec-ecapa-voxceleb` | no | Apache-2.0 |

**The two obvious candidates fail on opposite axes.**

`pyannote` is the standard, is MIT, and is *gated* - every user needs a Hugging
Face account, has to accept terms on a web page, and has to put a token where
Tertius can find it. "Auto" approval means no human waits on it, not that no
account is needed. Its `config.yaml` cannot even be read without authenticating,
which is how this was confirmed.

`nvidia/diar_sortformer_4spk-v1` is ungated and is **CC-BY-NC-4.0**. That is
the NLLB decision again, word for word: shipping a default feature that forbids
commercial use to everyone downstream is worse than shipping a weaker one. It
is out for the same reason, and `test_nllb_is_not_offered` is the pattern for
making a future change argue with that.

Now that the repo is public this is sharper than it was. A gate cost Seth one
click. It costs every stranger who clones this the same click plus a token in
their environment, for a model they did not choose, in an app whose whole
selling point is that it runs offline and fetches nothing it did not name.

**There is a third route, and it is the interesting one.** The pyannote
*pipeline* is gated, but it is segmentation plus embeddings plus clustering,
and the embedding half - `pyannote/wespeaker-voxceleb-resnet34-LM`, from
pyannote's own organisation - is **not gated** and is CC-BY-4.0. Only the
segmentation half is, and there is an ungated MIT re-export of it under
`onnx-community`. Assembling the three steps here rather than calling the
packaged pipeline would be ungated end to end.

That is not free. It means owning the clustering, which is the part that
decides how many speakers there are - the hard part, and the part the packaged
pipeline exists to get right. And it means depending on a re-export rather than
the publisher, which is precisely the provenance argument `translate.py` was
built to avoid. `onnx-community` is a Hugging Face organisation rather than an
individual, which is better than the case that argument was written against,
but it is still not the people who trained the model.

### Decided (2026-09-19): assemble it ungated, and own the clustering

Seth's call. Tertius fetches nothing the user did not choose and needs no
account for anything; a gated model would be the first exception, and the first
one is the one that makes the second easy. Paying for that in code we have to
maintain is the trade being accepted deliberately.

**What that commits us to.**

The pipeline becomes three steps we own rather than one call we make:

1. **Segmentation** - who is speaking at each moment, as overlapping activity
   rather than a clean split. `pyannote/segmentation-3.0` is MIT and gated;
   `onnx-community/pyannote-segmentation-3.0` is MIT and not. Taking the
   re-export means depending on someone who is not the publisher, which is
   exactly what `translate.py` converts weights to avoid. It is a Hugging Face
   organisation rather than an individual, which is better than the case that
   argument was written against, and it is still a weaker claim than any other
   model here has. **Say so in the model table rather than burying it**, the
   way the speech models already say they are loaded as published rather than
   converted. If a first-party ungated export appears, switch to it.
2. **Embeddings** - a fingerprint per speech region.
   `pyannote/wespeaker-voxceleb-resnet34-LM` is CC-BY-4.0, ungated, from
   pyannote's own organisation, and needs no re-export.
   `speechbrain/spkrec-ecapa-voxceleb` is Apache-2.0 and ungated as a fallback
   if the first disappoints.
3. **Clustering** - ours. This is the part being taken on, and it is the part
   the packaged pipeline exists to get right.

**Clustering is the whole risk, so plan it honestly.**

Agglomerative clustering on cosine distance with a threshold is the standard
approach and is perhaps thirty lines. The thirty lines are not the problem.
The problem is that the threshold decides *how many people are in the room*,
and there is no threshold that is right for both a two-person interview and a
six-person panel recorded on one microphone. Get it wrong high and two people
merge into one voice; get it wrong low and one person is split across two, and
the reading gives them two different voices mid-sentence.

So:

- **Let the user say how many speakers there are**, and treat that as the
  common case rather than the escape hatch. Somebody queueing a panel knows how
  many people were on it. Asking is more honest than inferring, and it turns
  the hard problem into an easy one - with a known `k`, the clustering is
  ordinary and the threshold stops mattering.
- **Estimate only when they do not say**, and say that it was estimated. A
  guessed speaker count should appear in the UI as a guess, next to a control
  for correcting it, rather than silently deciding whose voice says what.
- **Make it visible before it is expensive.** The speaker split has to be
  reviewable before any GPU time goes into reading, and the tag preview panel
  is the obvious home - it already exists to catch this class of mistake, and
  it now names the language for the same reason.
- **Measure it against something.** The published pipeline is the benchmark
  even though we are not shipping it: run both over the same file, compare the
  turns, and record the difference. "Ours is worse than pyannote by this much"
  is a fact worth having written down before anybody relies on it. Accepting a
  gate for one comparison run on a development machine is not the same as
  shipping one.

**What would reverse this decision.** A first-party, ungated, permissively
licensed diarization pipeline appearing - at which point assembling it by hand
is just maintenance we no longer need. Worth re-checking whenever the models
are next reviewed, and the re-export dependency is the thing to check first.

### What the code would then need

Roughly in order of how much thought each needs, not how much typing.

1. **Rejoining prose per speaker.** `prose_sentences` in `translate.py` joins
   *every* segment into one blob before re-splitting it into sentences. With
   two speakers that silently welds the end of one person's sentence to the
   start of another's, and the translation then renders the join as though it
   were one thought. This is the subtlest thing on the list and the easiest to
   miss, because the output looks fine.

2. **A voice per chunk, not per file.** `speak_chunks` takes one `voice` for
   the whole reading and `SpokenChunk` has no speaker on it. Both need one, and
   chunk packing must stop at a speaker change the way it already stops at a
   style change - `_pack` currently only knows about the character budget.

3. **Sampling a voice per speaker.** `best_voice_window` already finds the
   densest ten seconds of speech in a recording by scoring segment timings; run
   it over one speaker's segments instead of all of them and it answers the
   right question unchanged. The warning it emits when the best window is
   mostly silence becomes more useful, not less: on a panel, the person who
   said four words will not clone well and the user should be told which one.

4. **Aligning turns to segments.** Diarization emits `(start, end, speaker)`;
   Whisper emits segments. Assign each segment the speaker it overlaps most.
   Cheap, and worth a test with a deliberately ambiguous overlap.

5. **A fourth model on a six-gigabyte card.** Already measured: whisper 2.23 GB
   + m2m100 0.27 GB + chatterbox 3.22 GB against 5.36 GB free. Diarization runs
   *before* transcription and is finished by the time anything else loads, so
   `_free_gpu_for_speech` generalises to it - but it does have to be unloaded,
   not merely left to the garbage collector, and nobody has measured what
   pyannote takes.

6. **Speaker in the output.** `segment` gains a `speaker` key in the `.json`.
   Adding a key does not need a `JSON_SHAPE_VERSION` bump by the rule already
   written in `config.py`; renaming or repurposing one does.

7. **What happens when it is wrong.** A misattributed segment is read in
   another person's voice, which is the failure this feature can produce that
   nothing else here can. There should be a way to see the speaker split before
   committing GPU time - the tag preview panel is the obvious home, since it
   already exists to catch exactly this class of mistake before a run.

### Not worth doing

Speaker *identification* - putting a name to a voice - is a different feature
with a different risk profile, and nothing has asked for it. Diarization only
needs to know that speaker A is not speaker B.

## 2026-09-19 — somebody listened

The line that had been open since the feature was written is closed, and only
half of it.

**Russian: verified by a Russian speaker.** Seth ran a Russian reading and had
someone who speaks the language listen to it. They said it sounds good. That is
the first time any claim here about how this *sounds* has come from a person
rather than from a waveform, a language detector or a pitch estimate.

**Chinese: unverified, and should stay that way in this file.** It was run, and
it sounds good to Seth - who does not speak Chinese. Whisper hearing the right
words back is evidence the words survived the pipeline; it is not evidence that
a Mandarin speaker would call it good Chinese, and neither is a non-speaker's
impression. The honest state is: plausible, unconfirmed.

The distinction matters more here than it would elsewhere, because the two
failure modes are invisible from outside the language. A reading can be fluent
and wrong, and everything this program knows how to measure - duration, pitch,
what a small Whisper model transcribes back - would report it as fine. Russian
now has a person behind it. Chinese has a machine and a guess.

What this does settle, for both:

- The voice sampled from the recording is good enough to be worth listening to,
  on real devotional material, with no clip chosen by hand.
- The chunking fix produced audio a speaker could follow. Before it, the
  Chinese was truncated garbage; a listener would not have got as far as an
  opinion.
- Nothing about the three-stage pipeline gets in the way of the result.

Still open: a Chinese speaker, and anyone at all on the other twenty-one
languages `chatterbox-multilingual` claims.

## 2026-09-19 — out of memory, and the bug that found

Reported as an error. It was two, and the second was the one actually ruining
the output.

### Three models do not fit on a 6 GB card

`CUDA out of memory. Tried to allocate 204.00 MiB` - raised *after* the
transcript and the translation had been written, which is the worst moment for
it: all the expensive work done and the only thing missing was the thing the
run was for. The file was marked done with `error: null`, because a failed
reading deliberately does not fail a file whose transcript is already correct,
so the reason survived only in a notice a restart would have erased. It was
still in the live server when this was looked at.

Measured rather than estimated, each loaded alone and read back from
`torch.cuda.memory_allocated`:

| model | VRAM |
| --- | --- |
| whisper large-v3-turbo | 2.23 GB |
| m2m100-418M | 0.27 GB |
| chatterbox-multilingual | **3.22 GB** |
| **total** | **5.72 GB** |

The card is 6.44 GB and had 5.36 GB free - a browser was holding the rest, and
the two processes the error named turned out to be Brave, not Tertius. Short by
0.36 GB. This is the line that sat in *Not verified* as "whether a voice model
fits on a GPU beside Whisper is unknown". It does not.

**Holding all three at once was never necessary: nothing transcribes while it
reads aloud.** The earlier stages hand their VRAM back before the reading and
reload themselves for the next file - `WhisperTranscriber.model` and
`Translator.translate` were already lazy, so this needed no new machinery. Only
when the work is on CUDA; on the CPU there is nothing to reclaim and a reload
would cost real time for nothing.

Proved on the same job that failed, with free VRAM logged at each phase:

```
[before]                GPU free 5.36 / 6.44 GB
[preparing_translation] GPU free 3.13          <- whisper loaded
[preparing_speech]      GPU free 2.86          <- translator loaded
[transcribing]          GPU free 0.00          <- nothing left at all
freed the GPU for the reading: WhisperTranscriber, Translator
[speaking]              GPU free 2.05
```

### The splitter had never seen a sentence that was not English

The run that then succeeded logged **1 chunk, 23.6s** for a 79-second source.
It was truncating, and the cause was three years older than any of this:

```python
_SENTENCE_END = re.compile(r"[.!?][\"')\]]*\s+(?=[\"'(\[]?[A-Z0-9])")
```

An ASCII terminator, whitespace after it, **and a following ASCII capital**.
Chinese has none of the three: an ideographic full stop, usually no space, and
no case at all. So the whole translation came back as one "sentence", became
one 326-character chunk, and Chatterbox forced EOS at step 591 and produced
garbled Mandarin. The same is true of Japanese, Korean, Greek, Arabic and
Devanagari - and of any *transcript* in those languages, where a `.txt` would
have been one enormous line. Invisible on the page; fatal read aloud.

Three things were wrong, not one:

1. **The terminators.** A second alternation with no following-capital
   requirement, because these scripts have no case. The reported file went from
   1 sentence to 10.
2. **The budget was script-blind.** 300 Latin characters is about 60 words and
   twenty seconds read aloud; 300 Han characters is nearer eighty. `spoken_length`
   weights a dense character as four, reasoned from speaking rate - a Han
   character is about a syllable, an English word about 1.3 syllables in six
   characters.
3. **The translator's own line breaks were being thrown away.** It writes one
   sentence per line, and `chunks_from_prose` was joining that back into a blob
   and re-splitting it. The lines are the sentence boundaries now, still packed
   to the budget rather than spoken one at a time.

Measured on the reported file: Chinese **1 chunk of 326 characters -> 4 of
55-123**. English is byte-identical at `[216, 190, 414, 185]`; a first attempt
at this regressed it to 8 chunks with a 0.7s pause between every sentence,
which is why that number is now pinned by a test.

### What it sounds like now

Same job, both fixes, `0101.mp3` into Chinese: **4 chunks, 53.3s** of audio
against the previous 23.6s. Transcribed back with Whisper it matches the
translation rather than wandering off it:

| | |
| --- | --- |
| translator wrote | 每日天堂曼娜。祝福我們的上帝,你們的人民,讓他的讚美的聲音被聽到 |
| the audio says | 每日天堂麦娜,祝福我们的上帝,你们的人民,让他的在美的声音被听到 |

Homophone slips are what `base` does to synthetic Chinese and are not evidence
of much. That it is the *same text* is - before the fix it was unrelated.

### Still not verified

- **Chinese has not been heard by anyone who speaks it.** Whisper hearing the
  right words back proves they survived the pipeline, not that the result is
  good Chinese. Russian has a speaker behind it; Chinese does not.
- The weight of 4 for dense scripts is reasoned, not measured. So is the
  300-character budget it is applied to.
- The terminator list covers the scripts Tertius can currently speak into. It
  is not a general sentence segmenter and does not pretend to be.
- Only `chatterbox-multilingual` has ever been loaded, so only its VRAM figure
  is real; turbo and nano are recorded as unknown rather than guessed.

## 2026-09-19 — three stages, not three modes

Reported: "the most recent job didn't work right". It had not. The options
recorded `speech_language: "zh"` over an English text file, and 46 seconds of
GPU later it produced English audio and reported success.

**The diagnosis was not user error.** Chatterbox does not translate -
`language_id` declares what the text *is in*. But the speech Language menu
offered 23 choices in exactly the place the translation feature offers its
"Into" menu, so it read as "speak it in this language". And the combination
that would actually have done the job was blocked: ticking Read aloud switched
Translate off, because speaking had been modelled as a mutually exclusive
*source kind*.

Translation was already a post-step on a transcription. Speaking should have
been the third one in the same chain from the start:

```
audio -> transcribe -> [translate] -> [speak]
 text ->               [translate] -> [speak]
```

### What that buys

**The bug becomes unrepresentable.** Once a reading follows a translation, the
speech language *is* the target - `resolved_speech_language()` derives it, and
`speech_language` is consulted only for a text file that nothing is translating,
the one case where nothing else knows the answer. A stale `zh` in the menu can
no longer reach the model.

**A target nothing can say is refused before the queue runs.** The translator
knows 100 languages and the voice model knows 23. Translating a whole queue
into Romanian and discovering at the last stage that nothing can pronounce it
is the failure the language menus have always existed to prevent, so the "Into"
menu narrows to the intersection when Read aloud is on - measured as exactly
Chatterbox's 23, since m2m100-418M covers all of them - and says why, because
a missing Romanian otherwise reads as a bug.

**The voice is sampled from the recording.** No clip to choose: the densest ten
seconds of speech in the file being transcribed, found from the segment timings
a transcription already produces. Word timings would be finer and are off by
default; ten seconds does not justify a slower pass. This is a direct fix for
what the reported job actually did - the clip it was given was 78.8s long, of
which Chatterbox uses the first ten, and **49% of those ten seconds was
near-silence**. It warns now when the best available window is still mostly
silence, so a poor clone points at the recording rather than at the feature.

**A queue written by the old version still runs.** `translate_text` and `speak`
both normalise to `MODE_TEXT` on load. Left alone they match no branch in the
worker, so the file would sit pending forever with nothing saying why.

### Verified end to end, on real material

`Daily Heavenly Manna/0103.mp3`, 51s of English, through one job:

- Whisper hears **Spanish** in the generated audio: `es`, p=0.99.
- The voice is the **original speaker's**: median F0 **115.9 Hz** against the
  source recording's **110.7 Hz**, IQR 102.6-132.3 against 101.3-137.7. Nothing
  was chosen by hand; the clip was cut from the recording itself.
- The chain reads correctly: *"Man of for January 3, pray without ceasing."*
  became *"El hombre del 3 de enero, ora sin cesar."*
- 343s in total for 51s of source, on the RTX 2060.

### A bug the real run found, that no test would have

The first run wrote `0103.es.srt` **twice** - and the second write destroyed the
first. The translation writes translated cues timed against the *original
recording*; the reading writes cues timed against the *generated audio*. Both
are legitimately "the Spanish subtitles for this file", both were written to
the same name, and the reading silently replaced the only cues that match real
speech.

Everything the reading produces carries `.spoken` now:
`0103.es.txt` and `0103.es.srt` are the translation, `0103.es.spoken.wav` and
`0103.es.spoken.srt` are the reading. Pinned by a test asserting both survive.

### Driven in the browser

The new panel was exercised for real, not just rendered: Read aloud stays
hidden until there is something to read, appears when Translate goes on, and
the speech Language row - the one that caused all this - does not appear at
all while translating. The Into menu came back with 23 entries and the note
explaining why. Switching the source to text brings the language question back,
because that is the one case where nothing else knows the answer.

Two bugs found by looking, neither reachable from a test:

1. **`paintDevice` was clearing the Source selection.** It swept
   `document.querySelectorAll('.seg')` - which now matches the Source chips too
   - and set `aria-checked="false"` on both, since neither has a `data-device`
   to match. Scoped to `[data-device]` now, and the Source painter uses
   `aria-checked` rather than a class the stylesheet never read.
2. **Two things numbered "1."** The page already labels its sections 1. Source
   / 2. Settings / 3. Run, so numbering the stages as well put two firsts on
   one screen. The stages are named rather than numbered now, with one line
   above them saying the order.

The Transcribe settings grey out for a text source. **Device** deliberately
does not: it is where the *voice* model runs too.

### Still not verified

- **Nobody has listened to the Spanish.** Whisper transcribing it back as
  Spanish proves it is Spanish, not that it is good Spanish or that it sounds
  like the man in the recording rather than merely sharing his pitch.
- That run also predates the sentence-splitting fix below, so its chunking was
  the Latin-only kind. Spanish was unaffected - it has ASCII terminators - but
  the figures in it are from the older code.
- Whisper's `base` model was used to keep the loop short; the English
  transcript has errors of its own ("Man of for January 3"), which the
  translation then faithfully carried.
- Multi-speaker panels remain out of scope: every diarization option is gated
  on Hugging Face.

## 2026-09-18 — speech, actually run

`chatterbox-multilingual` downloaded, loaded onto the GPU, and used. Audio
exists. What the fakes could not tell us, now known:

- **The API is what the source said it was.** `ChatterboxMultilingualTTS`
  took `language_id="en"` alongside `exaggeration`, `cfg_weight` and
  `temperature`, and `model.sr` really is 24000. That was read out of
  `mtl_tts.py` rather than exercised, and it held.
- **It runs on the GPU**, loaded on `cuda`, with torch 2.14.0+cu126.
- **It works against transformers 5.16.1** despite hard-pinning 5.2.0. A pin
  is not a tested floor.
- **Six chunks, 22.38s of audio, 1,074,284 bytes.** Measured: 24 kHz, mono,
  16-bit, peak 96.2% of full scale and not clipped. RMS 2490-4970 in every
  cue, so there is real speech in all six rather than silence or noise.
- **The measured `.srt` is measured.** Every gap between cues came out at
  exactly 0.70s - the paragraph figure, correct for a test file whose blocks
  are all separated by blank lines - and four of the five gaps are digitally
  silent, peak 0. (The fifth reads 1056, which is the JSON rounding cue times
  to 3dp and my analysis window catching a few frames of the neighbouring
  chunk. Not a defect in the audio.)
- **`styles_used` came back `['solemn', 'warm', 'urgent']`** - the two written
  tags plus `[angry]` resolved through the alias. `[inaudible]` and the
  misspelt `[emphatc]` were read out as words, exactly as the warnings said
  they would be.
- **`pkuseg not available - Chinese segmentation will be skipped`** appears at
  load and is harmless, which is what makes the `--no-deps` install viable.

### The number that matters: 0.51x realtime

22.38 seconds of audio took **43.6 seconds** to generate on the RTX 2060. That
is *slower than realtime*, and it is the single most useful thing this run
produced, because nothing anywhere had a figure for it.

For scale: a 40-minute reading is roughly 80 minutes of GPU time. Transcription
on this same card runs at ~22x realtime. Reading aloud is therefore about forty
times more expensive per minute of audio than transcribing it, and any UI
estimate built on the transcription figure would be wrong by that factor.

Model load was 326.9s, but most of that was the 3.2 GB download (4m52s); that
cost is paid once.

### Worth watching, not yet understood

`alignment_stream_analyzer` fired on **five of six chunks** with
`forcing EOS token, long_tail=True`, and on the sixth with
`Detected 2x repetition of token 6486`. That is Chatterbox's own safety net
cutting generation short. It may be entirely normal for short chunks, or it may
mean the 300-character budget and the style numbers are pushing it somewhere it
does not want to go. Nobody has listened yet, so there is no way to tell from
here whether those chunks are clipped.

### Still not verified

- **Nobody has listened to it.** Every claim above is from the waveform and
  the metadata. Whether it sounds like English, whether `[solemn]` sounds
  solemn, and whether the forced-EOS chunks are cut off mid-word are all open.
  The file is at `transcripts/first-reading/reading.wav`.
- **Voice cloning has still never been run.** This used the model's default
  voice; `audio_prompt_path` was never passed.
- Turbo and Nano have not been downloaded, so `[laugh]` has never reached a
  model that acts on it.
- Chinese is now *knowingly* degraded by skipping `spacy-pkuseg`. Untested.

### The install does not work as published

`pip install chatterbox-tts` **fails outright on this machine**, and would have
been wrong even if it had succeeded. See CHATTERBOX_DEPENDENCIES in speech.py;
the short version is three problems in one metadata file:

1. `spacy-pkuseg` publishes **no cp314 wheel in any version**, so pip builds it
   from source and dies on "Microsoft Visual C++ 14.0 or greater is required",
   having installed nothing. The code imports it inside a try/except and only
   loses Chinese segmentation without it.
2. `transformers==5.2.0` is a hard pin, and translation here runs on 5.16.1.
   Accepting it would have downgraded the library the translation adapters
   depend on, to fix a version chatterbox turns out not to need.
3. `gradio==6.8.0` is never imported by the library at all.

So the installer does the dependencies itself and then `--no-deps
chatterbox-tts`. Three tests pin that, including one asserting the bare form
never reappears.

## 2026-09-18 — reading text aloud

Built. Not run against a real model, and the rest of this entry should be read
with that in front of it: every claim below is about what the code does against
a fake, not about how anything sounds.

**Chatterbox, chosen on licence and on the gate.** `ResembleAI/chatterbox`,
`-turbo` and `-nano`: MIT code, MIT weights, and `gated: false` on all three,
checked against the Hub API rather than taken from a model card. IndexTTS-2 is
the better model for this — it is the only open one with real duration control,
which is what dubbing actually wants — and it ships under the *bilibili Model
Use License Agreement*, not a permissive licence. Three separate roundup
articles say it is Apache-2.0 or MIT. All three are wrong; the repository says
otherwise. That is the same trap NLLB-200 was, found the same way, and it is
the reason licences here get read at the source.

**These are not converted, and that is a real difference.** translate.py
converts the publisher's own checkpoint precisely so nothing depends on a
stranger's upload. CTranslate2 cannot run a TTS model, so that argument is
unavailable and the weights are loaded as published. What stands in for it is
that the repositories belong to Resemble AI rather than to an individual.
Written down rather than glossed.

**The style tags are named for delivery, not for feeling, on purpose.**
Chatterbox has no emotion conditioning — there is no input to it that means
"sad". It has `exaggeration`, `cfg_weight` and `temperature`. Everything
expressive comes from the reference clip. So the vocabulary is `neutral`,
`calm`, `gentle`, `solemn`, `warm`, `bright`, `emphatic`, `urgent`, and an
emotion word is accepted as an alias *and warned about*. Somebody who writes
`[angry]` and gets firm-but-calm speech back would fairly conclude the feature
was broken rather than that the tag was a lie.

**Styles are deltas from each model's baseline, not absolute numbers.** Turbo
and Nano default `exaggeration` and `cfg_weight` to 0.0; the multilingual model
defaults both to 0.5. A table of absolute numbers would make `[neutral]` mean
two different things depending on the model chosen, silently.

**Three kinds of bracket.** A style tag is ours and is stripped. `[laugh]`,
`[chuckle]` and `[cough]` are the model's own and pass through on Turbo and
Nano — and are *removed* on the multilingual model, which would read out the
word "laugh". Anything else stays exactly as written, because transcripts are
full of `[inaudible]` and a tag vocabulary that ate them would corrupt the very
files this feature exists to read. The publisher's model card says "and more"
without saying which, so only the three that are documented are passed through;
a guessed tag is read out as words.

### A bug the first preview found

Removing a tag flushed the text either side of it as two separate runs. One
sentence therefore became two calls to the model with a 0.28 s pause inserted
between them that nobody had written. Found by looking at the preview panel in
the browser, not by a test — `[laugh]` in the middle of a line is exactly the
case, and no test had one until this. Fixed by accumulating across a removal
and only breaking on a real style change, with a test pinning it both ways.
Runs of spaces are collapsed too, or the hole the bracket left behind reads as
a gap of its own.

### Confirmed on this machine, in the browser

Not a real reading — nothing has been generated — but the whole path up to the
model was driven for real: scan a folder of `.txt`, queue it, and the preview
panel showed six chunks with `[solemn]` held across a paragraph break,
`[inaudible]` and a misspelt `[emphatc]` surviving in the text with warnings,
`[angry]` resolved to `urgent` with the honest note about emotion, and
`[laugh]` removed. Light and dark, no console errors.

One cosmetic bug seen there and fixed: `warn-text` was only ever defined for
`.caption`, so the tag warnings rendered as ordinary body text — the wrong
outcome for the lines telling you a tag was misspelt.

### The torch collision, confirmed and then fixed

**Resolved 2026-09-18.** `torch 2.14.0+cu126` is now in the venv and the GPU
works: `is_available` True, RTX 2060 reported as `sm_75`, and a 512x512 matmul
actually run on it rather than merely promised. `torch_install_problem()`
returns None. The translation stack is untouched - transformers 5.16.1,
ctranslate2 4.8.1, and the converted `m2m100-418M` still on disk - and all 441
tests still pass. (`--force-reinstall` also rolled setuptools 83.0.0 back to
78.1.0, which broke nothing.)

Getting there cost two wrong commands, and both are worth keeping:

1. **`cu124` was a guess and has no cp314 wheels at all.** pip answers that
   with "No matching distribution found for torch", which reads as though
   torch did not exist. `cu126` was then checked against the index listing
   rather than assumed: it carries 2.14.0 - the same version as the CPU build,
   so nothing else shifted - for cp311/cp313/cp314 on win_amd64 and
   manylinux_2_28, and still builds sm_50 through sm_90, which is what covers
   a Turing card. The 13.x indexes have dropped some of those.
2. **Without `--force-reinstall`, pip did nothing and exited 0.** `torch` is
   satisfied by `2.14.0+cpu`; the local version after the `+` does not make it
   a different version. "Requirement already satisfied", no change, success
   exit code. The flag is pinned by a test now, as is the rule that the
   command names `sys.executable` rather than a bare `pip`.

### The torch collision, as first found

Speaking needs torch as its **runtime**; translating needs it only to convert a
model once and deliberately installs the **CPU-only** build. One virtual
environment holds one torch, so whichever installs first wins.

This machine has already lost that race. The check reported, on the real venv:

> There is an NVIDIA GPU here, but the installed torch (2.14.0+cpu) is a
> CPU-only build, so speaking will run on the CPU and be much slower.

The app says so in the voice-model panel and again when a model is prepared,
with the command. See the entry above for how that command was wrong twice
before it worked.

### Not verified

- **No model has ever been loaded, and no audio has ever been generated.** The
  API shape was read out of `mtl_tts.py` and `tts_turbo.py` at the version this
  was written against, not exercised. `generate()` taking `language_id` on the
  multilingual model and rejecting it on Turbo is the sort of thing only a real
  call proves.
- **Nobody has listened to anything.** The style numbers were chosen by reading
  the publisher's guidance. Whether `[emphatic]` sounds emphatic is unknown.
- The gaps between chunks (0.28 s, 0.7 s at a paragraph) are a guess at what
  reads as a breath rather than an edit.
- Whether a voice model fits on a GPU beside Whisper is unknown. Same as
  translation, and for the same reason: nothing has been tried.
- The 300-character chunk budget is a guess at where Chatterbox starts dropping
  clauses. Not measured.
- Voice cloning has never been done. Whether ten seconds of clean speech is
  enough, and what a bad clip does, is entirely unknown.

### The disclaimer

SECURITY.md has a new section, *Voice cloning: your responsibility, not the
tool's*, and the README points at it from the feature and from the licence.
Short version: use it only on voices you have the right to use and only
lawfully; every generated file carries Resemble AI's inaudible PerTh watermark
and Tertius will not help remove it; every generated `.json` says
`"kind": "speech"` so a reading can never be mistaken downstream for a
transcript of something somebody actually said.

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
- `madlad400-3b-mt` has now run on one file (2026-10-19), after the
  conversion fix. Russian and Chinese read as real translations, but no
  speaker has read them; its Hebrew invents scripture text. Its first-ever
  conversion was garbage and nothing noticed: see the 2026-10-19 entry. Both M2M-100 sizes have now been run.
- The 1.2B has now been run through the queue on a whole file (`V1_01.mp3`,
  38:12). Compared closely on three sentences; the other 203 have not been
  read.
- ~~Translation has only been run on the CPU.~~ **Answered.** It has been run
  on CUDA many times since, and the three models together measure 5.72 GB -
  whisper large-v3-turbo 2.23 + m2m100-418M 0.27 + chatterbox 3.22 - which does
  not leave room on a 6 GB card for anything else, so earlier stages are
  unloaded before speaking rather than held.
- The translated `.txt` is measurably less readable than the transcript, and
  the cause is structural rather than a bug. See *the fragment problem* below.
- Long-batch behaviour (17 files back to back) has not been run start to finish.
- Alignment has not been tried on a text that diverges heavily from the audio
  (abridged, reordered, or a different edition).
- The UI's narrow-window behaviour (below 1180px, and the collapsed rail below
  1000px) is written but unseen — the browser could not be given a small enough
  viewport to check it.
- **No reading in any language but Russian has been heard by someone who speaks
  it.** Russian was confirmed by a native speaker. Chinese was heard by someone
  who does not speak it. Hebrew, Spanish and the other nineteen have nobody
  behind them at all - and Hebrew is the cautionary case: it was being
  mispronounced badly enough to change the words, for three days, while every
  automated check passed. Whisper even detected the bad audio as Hebrew at
  p=0.93.
- **Arabic is an abjad like Hebrew** and may have the same missing-vowels
  defect. Chatterbox offers no diacritization hook for it, and nothing has
  measured it.
- **Ordinal dates are wrong in every language.** "January 1st" is spoken as the
  cardinal - `1 января`, `מאנה ל-אחת בינואר`. Known since the digits work and
  still unfixed.
- **A translation model can loop.** Fed the garbled transcript of a bad Hebrew
  reading, m2m100 repeated one clause nine times. Nothing detects or stops it,
  and it is not specific to Hebrew.
- The book-name table is used but unjudged: nobody has said whether
  `Книга Иова 3:16` reads naturally to a Russian speaker or merely correctly.
  Since 2026-09-29 the names are also declined and the Hebrew prefixes joined,
  by rules written by someone who speaks neither language - `в Псалтири`,
  `Сравнить Книгу Иова`, `בתהילים`, `באיגרת אל הרומאים` are each checked
  against a grammar, not against a reader. A wrong rule would be wrong on
  every reference, consistently.

## Next steps

0. ~~Try Qwen3-4B-Instruct-2507 as the translator.~~ Tried 2026-10-21 (the
   second entry that day): worse for a listener in every form tried (4.7-5.5%
   against madlad's 3.4%), and it invents content. **madlad stays.** Improving
   the Chinese from here, cheapest and most certain first:
   - ~~Fixed lines from a table.~~ Done (`642fe18`); no overall change
     (3.5%), the lines themselves heard right. See the evening entry.
     Checked on the ten harness files only; the other recordings are
     untranscribed.
   - ~~Catch babble.~~ Done (`ef27871`), and a line ending in a colon now
     stays with what follows it (`ce33f3e`). With all three: **3.1%**,
     nothing lost; the babble check fired once in ten files, on real text.
   - ~~Sort the misheard characters by cause.~~ Done 2026-10-22 (the 77 of
     the 3.1% run). Two follow-ups, each a decision:
     - ~~Add 白昼→白宙, 祷告→导告, 羊羔→羊高 to `speech.SPOKEN_AS`.~~ Done
       2026-10-22: 0/15 heard right as they were, 13/15 with them; 5/5 in
       context in the ten-file run (3.3%, the rise all from 0616's cut-short
       references).
     - ~~References cut short.~~ A new chunk at 再读一遍经文 (2026-10-22),
       and a listen-back check of each chapter and verse with two extra takes
       (2026-10-23): 0616 keeps 第十二章 in 5 of 6. 2.5% to 2.1%.
     - ~~Stop scoring 吗哪/玛纳 and trailing hallucinations.~~ Done
       2026-10-22; nine runs rescored, the code now at about 2.5%.
     - ~~Take-to-take noise.~~ `zh_harness.py --takes 3`; whole-run totals
       span 2.1-2.9% on unchanged text.
   - ~~Sort the 2.1% (162 characters) by cause.~~ Done 2026-10-23 (later).
     Candidates for `SPOKEN_AS`, each needing the 0-of-N test the last three
     had: 得着 (9 characters, 0829), 渣滓, 福祉, 哀哉, 溢.
   - ~~Test the five candidates.~~ Done 2026-10-24: 渣滓, 哀哉, 福祉 added;
     溢 not needed; 得着's 着 has no same-sound spelling (needs a Chinese
     speaker's say on 得到).
   - ~~Split long English sentences before madlad sees them.~~ Tried
     2026-10-23 (later): madlad invents scripture for a fragment. Not done.
   - **A Chinese speaker** (item 7). Whisper is a stand-in; every number
     above is about Whisper, not a person. None available yet (Seth,
     2026-10-23). **Chinese is on hold until there is one** (2026-10-24):
     what is left of the 2.0% is mostly tones and same-sound characters
     Whisper chose, with no cheap fix, and 得着→得到 needs a speaker's say.
     One measurement-only change remains: scoring a character that sounds
     right (渣子 for 渣滓) as heard.
   Still open alongside it:
   - ~~Protect Chinese references in the Chinese-to-English direction.~~
     Done 2026-10-23 (later), matched by sound: 41 to 59 of 60.
   - Listening back and quote removal are measured on Chinese only. Other
     languages may drop text the same way.
   - The punctuation restorer covers English, German, French and Italian
     only. Other source languages that Whisper leaves unpunctuated still reach
     the translator as one long sentence.
   - Chatterbox occasionally babbles or repeats a phrase (2026-10-19; 0403
     and 1218 on 2026-10-21). Listening back now looks for added text too,
     Chinese only; one firing in ten files, a real one, is all the
     false-alarm evidence so far.
1. Read a whole translated volume properly. `V1_01` has been checked closely on
   three sentences out of 206, and structurally on all of them; that is not the
   same as having read it.
2. Get this in front of a real Mac and a real Linux box. Everything in
   *Not verified* about those two stays open until someone does. Translation
   adds to what is riding on that: the installer shells out to pip, and the
   `.txt`-source scan has only run on Windows.
3. ~~Try `madlad400-3b-mt`.~~ Tried 2026-10-19; every translation was
   garbage until the conversion was fixed. Still open: have a speaker read its
   output, and compare its Hebrew against m2m100-1.2B on scripture.
4. ~~Run a translation on the GPU.~~ Done. What is still missing from the
   comparison table is a per-model throughput column; only m2m100-418M has been
   timed.
5. Decided (2026-08-03): this ships, as open source under MIT. The legal
   groundwork is in, and the translation models were chosen to keep it that way
   — see the 2026-09-01 entry on NLLB.
6. Packaging is still untouched — run-from-source only, no wheel, no installer.
   Strangers on macOS and Linux will arrive before either platform has been run
   by hand, which is the risk to weigh before publishing.
7. **Find a Hebrew speaker, then a Chinese one.** Hebrew is now the urgent
   one: it was mispronounced for three days and only a round trip caught it,
   and the fix is confirmed by waveform alone. Russian has been confirmed by
   one; Chinese has
   been run and sounds fine to someone who does not speak it, which is not the
   same claim and should not be written down as if it were. The other twenty-one
   languages the model claims have nobody behind them at all. The model has been run
   and the audio measured, but not heard. Until someone plays it, "it works"
   means "it produced a well-formed 22-second file", which is not the same
   claim. Check in particular the five chunks where the model forced an early
   EOS.
8. Clone a voice. Ten seconds of clean speech is what the publisher asks for
   and nothing here has tested that, or what a bad clip does.
9. Decide what to do about 0.51x realtime. A 40-minute reading is 80 minutes
   of GPU. `chatterbox-nano` claims 3x realtime on 8 CPU cores and has never
   been tried; if that holds on a GPU it changes the feature's economics. For
   scale, the multilingual model on four CPU threads measured 0.116x
   (2026-09-29) - a 40-minute reading in about 5.7 hours.
10. Read something through the **UI**, not just through `speak_text_file`.
11. Have a Hebrew reader (item 7) and the Russian speaker read the **scripture
   references** in a translation too, not just the prose: the prefixes and
   cases fitted to them on 2026-09-29 are rules, and nobody who speaks either
   language has seen the result.

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

- **An overfull GPU slows down instead of failing.** The NVIDIA driver on this
  machine spills VRAM into system RAM, so loading too much shows up as a job
  running several times slower, not as "CUDA out of memory". `nvidia-smi`
  only shows the card filling up. The `\GPU Process Memory(*)\Shared Usage`
  counter is what shows the spill. Spilled memory stays spilled after the
  model that caused it is freed.
- **transformers 5 loads `madlad400-3b-mt` wrong, silently** - see the
  2026-10-19 entry. Anything that loads a T5 checkpoint through transformers,
  including CTranslate2's converter, needs `_load_t5_faithfully`. If a
  converted model writes fluent-looking nonsense, run the original checkpoint
  in PyTorch before blaming the conversion or the runtime.
- **Profiling `create_app` against a real folder repoints the app.**
  `attach` records the folder as "where I was last". Set
  `TERTIUS_SESSION_FILE` to a scratch path first, the way the test suite does.

- **One venv holds one torch, and the two features want different builds.**
  Translating installs the CPU-only wheel on purpose (it only ever converts).
  Speaking runs the model and wants CUDA. Whichever installs first wins, and
  nothing fails - synthesis is simply several times slower with no
  explanation. (This said "twenty times", never measured; on four CPU threads
  it measured 0.116x realtime against the GPU's 0.51x, 2026-09-29 - about
  4.4x.)
  `speech.torch_install_problem()` exists to say so; this machine is already in
  that state with `2.14.0+cpu`.
- **A PyTorch CUDA index without a wheel for your Python says "No matching
  distribution found for torch".** Not "no CUDA build", not "wrong Python" -
  it reads exactly as though torch did not exist. `cu124` has no cp314 wheels
  at all, which is how a guessed index number cost a confusing failure on
  3.14. Check the index listing before naming one, and remember the CUDA
  indexes lag the CPU one: at the time of writing cp314 had 2.14.0 on cu126
  and cu130, but stopped at 2.11.0 on cu128 and 2.9.0 on cu129.
- **`pip install` in a terminal is not this venv.** Tertius runs from
  `app/.venv`, and a bare `pip` hits whatever is on PATH - installing
  gigabytes somewhere with no effect here, announcing "Defaulting to user
  installation" as it goes. Any install instruction this project prints names
  `sys.executable` explicitly now.
- **A roundup article is not a licence.** IndexTTS-2 is reported as Apache-2.0
  or MIT by several of them and ships under the bilibili Model Use License
  Agreement. Read the repository, and for a Hub model ask the API whether it is
  gated - a gated model means every user needs an account and a token, which is
  a different feature from the one you thought you were adding.

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
  src/tertius/       the app (transcribe.py, translate.py and speech.py
                     are the three models)
  tests/             the suite
  assets/            the T mark as .svg/.png/.ico/.icns, plus its generator
  design/            UI handoff and the original build spec
  .venv/             created on first run
```

See README.md for full documentation — install, launch, resume semantics, model
sizes, GPU notes, and the HTTP API.
