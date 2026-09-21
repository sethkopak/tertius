# Third-party notices

Tertius bundles and depends on work by other people. This file records what,
and under what terms.

## Fonts bundled in this repository

The web fonts in `app/src/tertius/static/fonts/` are served from disk rather
than fetched from Google Fonts at runtime, because an offline transcription
tool must not reach the network to render its own interface. Self-hosting them
means this repository redistributes them, and the SIL Open Font License
requires their copyright notices and licence to travel with every copy. That is
what this section is for.

Neither font has been modified. IBM Plex declares a Reserved Font Name, so a
modified version of it may not be distributed under the name "Plex"; Cardo's
notice declares no reserved name.

### IBM Plex

    Copyright (c) 2017 IBM Corp. with Reserved Font Name "Plex"

Licensed under the SIL Open Font License, Version 1.1, reproduced below.
Upstream: <https://github.com/IBM/plex>

Files: `ibm-plex-sans-*.woff2`, `ibm-plex-mono-*.woff2`

### Cardo

    Copyright (c) 2002-2011, David J. Perry (hospes02@scholarsfonts.net)

Licensed under the SIL Open Font License, Version 1.1, reproduced below.
Upstream: <https://github.com/google/fonts/tree/main/ofl/cardo>,
<http://www.scholarsfonts.net/cardofnt.html>

Files: `cardo-*.woff2`

### SIL Open Font License, Version 1.1

Applies to both fonts above. Verified byte-identical between the two upstream
copies (IBM's and Google Fonts' Cardo notice) apart from line endings, so it is
reproduced once here rather than twice.

```
-----------------------------------------------------------
SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007
-----------------------------------------------------------

PREAMBLE
The goals of the Open Font License (OFL) are to stimulate worldwide
development of collaborative font projects, to support the font creation
efforts of academic and linguistic communities, and to provide a free and
open framework in which fonts may be shared and improved in partnership
with others.

The OFL allows the licensed fonts to be used, studied, modified and
redistributed freely as long as they are not sold by themselves. The
fonts, including any derivative works, can be bundled, embedded, 
redistributed and/or sold with any software provided that any reserved
names are not used by derivative works. The fonts and derivatives,
however, cannot be released under any other type of license. The
requirement for fonts to remain under this license does not apply
to any document created using the fonts or their derivatives.

DEFINITIONS
"Font Software" refers to the set of files released by the Copyright
Holder(s) under this license and clearly marked as such. This may
include source files, build scripts and documentation.

"Reserved Font Name" refers to any names specified as such after the
copyright statement(s).

"Original Version" refers to the collection of Font Software components as
distributed by the Copyright Holder(s).

"Modified Version" refers to any derivative made by adding to, deleting,
or substituting -- in part or in whole -- any of the components of the
Original Version, by changing formats or by porting the Font Software to a
new environment.

"Author" refers to any designer, engineer, programmer, technical
writer or other person who contributed to the Font Software.

PERMISSION & CONDITIONS
Permission is hereby granted, free of charge, to any person obtaining
a copy of the Font Software, to use, study, copy, merge, embed, modify,
redistribute, and sell modified and unmodified copies of the Font
Software, subject to the following conditions:

1) Neither the Font Software nor any of its individual components,
in Original or Modified Versions, may be sold by itself.

2) Original or Modified Versions of the Font Software may be bundled,
redistributed and/or sold with any software, provided that each copy
contains the above copyright notice and this license. These can be
included either as stand-alone text files, human-readable headers or
in the appropriate machine-readable metadata fields within text or
binary files as long as those fields can be easily viewed by the user.

3) No Modified Version of the Font Software may use the Reserved Font
Name(s) unless explicit written permission is granted by the corresponding
Copyright Holder. This restriction only applies to the primary font name as
presented to the users.

4) The name(s) of the Copyright Holder(s) or the Author(s) of the Font
Software shall not be used to promote, endorse or advertise any
Modified Version, except to acknowledge the contribution(s) of the
Copyright Holder(s) and the Author(s) or with their explicit written
permission.

5) The Font Software, modified or unmodified, in part or in whole,
must be distributed entirely under this license, and must not be
distributed under any other license. The requirement for fonts to
remain under this license does not apply to any document created
using the Font Software.

TERMINATION
This license becomes null and void if any of the above conditions are
not met.

DISCLAIMER
THE FONT SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO ANY WARRANTIES OF
MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT
OF COPYRIGHT, PATENT, TRADEMARK, OR OTHER RIGHT. IN NO EVENT SHALL THE
COPYRIGHT HOLDER BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY,
INCLUDING ANY GENERAL, SPECIAL, INDIRECT, INCIDENTAL, OR CONSEQUENTIAL
DAMAGES, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF THE USE OR INABILITY TO USE THE FONT SOFTWARE OR FROM
OTHER DEALINGS IN THE FONT SOFTWARE.
```

## Runtime dependencies

These are installed by pip and are *not* redistributed in this repository, so
their licences are listed for information rather than obligation. Versions are
the ones verified in use; each project ships its own licence text.

| Package | Version verified | Licence |
| --- | --- | --- |
| Flask | 3.1.3 | BSD-3-Clause |
| faster-whisper | 1.2.1 | MIT |
| ctranslate2 | 4.8.1 | MIT |
| av | 18.0.0 | BSD-3-Clause |

### Translation (the `translate` extra, optional)

Installed only when translation is used, and not redistributed here either.

| Package | Version verified | Licence |
| --- | --- | --- |
| transformers | 5.16.1 | Apache-2.0 |
| sentencepiece | 0.2.2 | Apache-2.0 |
| torch | 2.14.0+cpu | BSD-3-Clause |

`torch` is installed from <https://download.pytorch.org/whl/cpu> rather than
PyPI. Conversion loads a checkpoint and writes it back out — it never runs the
model — so the CPU build is sufficient, and on Linux it avoids a bundled CUDA
runtime well over a gigabyte.

## Data bundled in this repository

### Bible book names (Wikidata)

`app/src/tertius/data/book_names.json` holds the names of the 66 books of the
Bible in every language the translator can reach. It is generated by
`app/tools/fetch_book_names.py`, which queries the Wikidata Query Service; the
script records the Wikidata item id for each book so every entry can be traced
back to its source.

| Source | Licence |
| --- | --- |
| [Wikidata](https://www.wikidata.org) | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |

Wikidata places its data in the public domain under CC0, which imposes no
conditions on reuse and does not affect Tertius' MIT licence. The attribution
here is given because it is right to say where the data came from, not because
CC0 requires it.

**This is the only network request Tertius makes that is not a model
download, and it is a build step.** The table ships as a file; nothing at run
time contacts Wikidata. Regenerating it is a deliberate act by whoever is
working on the code.

## Models

No model is part of this repository. Every one is downloaded from Hugging Face
at first use and carries its own terms from its publisher.

| Model | Publisher | Licence |
| --- | --- | --- |
| Whisper (all sizes) | OpenAI | MIT |
| m2m100_418M, m2m100_1.2B | Meta | MIT |
| madlad400-3b-mt | Google | Apache-2.0 |

Every translation model Tertius offers is permissively licensed and may be used
commercially. This is deliberate. NLLB-200 is a better model than any of them at
its size and is **not** offered, because it is CC-BY-NC-4.0: shipping it as a
default would have handed every user a feature they could not use commercially,
under a restriction its publisher sets and Tertius cannot lift.
