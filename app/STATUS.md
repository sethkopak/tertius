# Tertius — status

Last updated: 2026-09-19

## Where it stands

Working, and in real use. Built from `design/original-spec.md`, plus everything
requested since: the launcher, folder picker, model download progress, model
comparison + machine check, tooltips, light/dark theme, mirrored output folders,
timestamping of supplied text, the designed UI, macOS/Linux support,
translation, and reading text aloud.

**498 tests, all passing**, on Windows locally and on ubuntu/macOS/Windows in
CI. Whisper is mocked throughout, and so are the translator and the speech
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
7. **Find a Chinese speaker.** Russian has been confirmed by one; Chinese has
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
   been tried; if that holds on a GPU it changes the feature's economics.
10. Read something through the **UI**, not just through `speak_text_file`.

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

- **One venv holds one torch, and the two features want different builds.**
  Translating installs the CPU-only wheel on purpose (it only ever converts).
  Speaking runs the model and wants CUDA. Whichever installs first wins, and
  nothing fails - synthesis is simply twenty times slower with no explanation.
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
