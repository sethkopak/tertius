# Security

## Reporting a vulnerability

Report privately through GitHub: **Security → Report a vulnerability** on
<https://github.com/sethkopak/tertius>. That opens a private advisory only the
maintainer can see. Please don't open a public issue for something exploitable.

This is a personal project maintained by one person, so there is no response
SLA. Expect acknowledgement within a couple of weeks. If a report is valid and
I cannot fix it quickly, I would rather say so in the README than leave people
guessing.

## What Tertius is, so reports can be aimed properly

Tertius is a **single-user tool that runs on your own machine.** It starts a
Flask server bound to `127.0.0.1` and you drive it from a browser tab on that
same machine. It has no accounts, no authentication, and no multi-user support.

The security boundary is therefore *the machine*. Anything that can already run
code as your user can already do everything Tertius can do.

## In scope

- Escaping the output directory — reading or writing a file outside it through
  the HTTP API (`/api/transcript` and the upload endpoint are the paths that
  handle names from the browser).
- Anything reachable from a **web page you merely visit** while Tertius is
  running, since a local server is reachable from any origin the browser
  loads. Cross-origin requests that change state or exfiltrate transcripts are
  the interesting case here.
- Code execution triggered by the *content* of a media or text file you
  transcribe.
- Secrets or transcript content leaving the machine. Tertius makes network
  requests on purpose in exactly five places, all of them fetches and none of
  them carrying your content:
  1. downloading a Whisper model from Hugging Face the first time it is used;
  2. downloading a translation model from Hugging Face, if you translate;
  3. installing `torch`, `transformers` and `sentencepiece` from PyPI and the
     PyTorch CPU index, if you translate and they are missing;
  4. downloading a voice model from Hugging Face, and installing
     `chatterbox-tts` and `torch` from PyPI and a PyTorch index, if you read
     text aloud;
  5. downloading the Hebrew diacritization model from Hugging Face, the first
     time you read Hebrew aloud.

  This list said "three" while listing four, for some weeks. It is five now
  and the count is worth checking against the list whenever either changes.

  A sixth exists and is **not** run by the app: `app/tools/fetch_book_names.py`
  queries Wikidata to regenerate the bundled table of Bible book names. It is a
  build step, run deliberately by whoever is working on the code, and the table
  ships as a file. Transcribing, translating and reading aloud never contact
  Wikidata.

  Anything else — anything that *sends* rather than fetches — is a bug worth
  reporting. In particular, **no audio you supply as a voice clip ever leaves
  the machine.** The model runs locally; the clip is read off your disk and
  handed to it in memory.
- **Reaching `/api/translation/prepare` or `/api/speech/prepare` from a page
  you merely visit.** These are the two endpoints that install software, so
  they are worth aiming at. What
  limits it today: the package names and index URLs are fixed in the source and
  not taken from the request, the model name is checked against a fixed
  catalogue, and it refuses to install outside a virtual environment. If you
  find a way to make either of them install something not on that list, or to
  run outside a venv, that is very much in scope.

## Voice cloning: your responsibility, not the tool's

Tertius can read a text file aloud in a voice sampled from a recording you
supply. That is a synthetic voice saying words the person never said, and it is
the one thing in this program that can be used to hurt somebody.

**Use it only on voices you have the right to use, and only for purposes that
are lawful where you are.** Concretely, do not use it to impersonate anyone, to
make a real person appear to say something they did not say, to defraud, to
harass, or to evade identity checks that rely on a voice. Several jurisdictions
regulate synthetic voice directly — biometric and voice-likeness statutes,
election and deepfake laws, right-of-publicity claims — and in many places
consent from the person whose voice it is, is required, not merely polite.

The maintainer cannot see what you generate and cannot police it. Complying
with the law where you are is yours to do. The MIT licence this ships under
gives you the software without warranty and without indemnity; it does not give
you permission to break the law with it.

Two things are worth knowing about what Tertius produces:

- **Every generated file carries an inaudible watermark.** Chatterbox applies
  Resemble AI's PerTh watermarker to everything it generates, and Tertius does
  not remove it or offer to. Helping you strip it is not a feature that will be
  added; a request to add one is not a bug report.
- **Every generated `.json` says what it is.** Its `kind` is `speech` and it
  names the model, the voice clip and the styles used. That is there so a
  reading can never be mistaken downstream for a transcript of something
  somebody actually said.

Reports of *misuse by someone else* are not security vulnerabilities and there
is nothing this project can do about them. A flaw that makes misuse easier —
say, an output path that lets a reading overwrite a real transcript — is.

## Out of scope

- **Binding to a non-loopback address.** `--host` exists, defaults to
  `127.0.0.1`, and is documented as having no auth. Pointing it at `0.0.0.0`
  on an untrusted network hands the machine to that network; the README says
  so under *Not included*. That is a documented consequence, not a
  vulnerability.
- Attacks requiring an attacker who already has local code execution or
  filesystem access as your user.
- The queue reading any path your own user can read. Choosing an input folder
  is the entire point of the app.
- Denial of service by feeding it enormous files. It is a batch transcriber;
  it will happily spend hours on what you give it. The same goes for triggering
  a large model download: it costs bandwidth and disk, and the models it can be
  asked for are a fixed list.
- Vulnerabilities in `faster-whisper`, `ctranslate2`, `av`, `transformers`,
  `torch`, or Flask — report those upstream. Tell me anyway if Tertius uses them in a way that makes an
  upstream issue worse.

## Supported versions

The tip of `main`. There are no release branches and no backports; this project
does not ship versioned releases yet.
