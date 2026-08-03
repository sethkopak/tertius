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
- Secrets or transcript content leaving the machine. Tertius makes exactly one
  network request on purpose: downloading a model from Hugging Face the first
  time it is used. Anything else is a bug worth reporting.

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
  it will happily spend hours on what you give it.
- Vulnerabilities in `faster-whisper`, `ctranslate2`, `av`, or Flask — report
  those upstream. Tell me anyway if Tertius uses them in a way that makes an
  upstream issue worse.

## Supported versions

The tip of `main`. There are no release branches and no backports; this project
does not ship versioned releases yet.
