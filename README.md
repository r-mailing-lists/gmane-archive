# gmane-archive

Archives of R mailing lists read from [Gmane](https://gmane.io)'s news server, pooled into one repository and laid out like the other archives in [r-mailing-lists](https://github.com/r-mailing-lists).

Gmane has relayed mailing lists to newsgroups since 2002 and still receives them. Several lists about R have no other public archive left: their hosts were shut down, moved to a new address without their history, or never offered one. Gmane kept every message it received, as sent. This repository keeps a copy of the lists the R Mailing List Archives had no other source for.

| List | What it was | Where it lived |
|---|---|---|
| `rpy-list` | RPy, the Python interface to R | SourceForge |
| `stats-rosuda-devel` | Development of the RoSuDa software for R (rJava, JRI, JGR, Rserve, iPlots) | University of Augsburg |
| `r-lang` | R for linguists, psycholinguists and computational linguists | UC San Diego |
| `zelig` | The Zelig package | Harvard (Gary King's lists) |
| `matchit` | The MatchIt package | Harvard (Gary King's lists) |
| `whatif` | The WhatIf package | Harvard (Gary King's lists) |
| `dealsoftware` | The deal package, Bayesian networks in R | Yahoo Groups |
| `r-soc` | French users of R in the social sciences | CRU, then RENATER |
| `rpostgresql-dev` | Development of the RPostgreSQL package | Google Groups |

See [`lists.tsv`](lists.tsv) for message counts and date ranges.

## How it is collected

`tools/gmane.py` reads each list's newsgroup at `news.gmane.io` over NNTP, one article at a time with a pause between them. An article is the message as the list sent it, so it carries what a web archive often lacks: the real Message-ID and the In-Reply-To and References headers that say which message a reply answers.

It also carries every address the message passed through. The mbox keeps only the headers a Mailman text archive keeps (From, Date, Subject, Message-ID, In-Reply-To, References) and writes the sender, and every address in a subject or in the text, as Mailman's archives do: `user at example.org`. The daily run publishes nothing if a whole address turns up in any file. Message-IDs are shaped like addresses but name a message, not a person, so they are kept.

Gmane rewrote anything in In-Reply-To that looked like an address, `<id-HASH@public.gmane.org>`, which would leave those replies pointing at no message. `gmane.py ids` puts the original back when one of the list's own Message-IDs, or an unchanged entry in References, is the rewritten ID's start. The few with no match stay as Gmane wrote them, and the parser still threads them by References.

A message's text is its plain-text part in UTF-8. A text attachment follows it after Mailman's "next part" line, and any other attachment is named there, as Mailman's archive names one it took out.

Gmane also files a message under every list it was sent to, so a list here holds the cross-posts its members received, as its own archive would have.

## Structure

Each list has its own directory:

- `<list>/config.json` - list name, description, source, and its newsgroup at Gmane (`gmane_group`)
- `<list>/gmane.json` - the last article read
- `<list>/raw/` - one Mailman-style .mbox file per month. `r-lang/raw/from-ucsd.mbox` holds six messages of March and May 2007, from before Gmane carried the list, taken from the list's first archive at UC San Diego (`pidgin.ucsd.edu/pipermail/r-lang/`, which keeps 2007 to 2009)
- `<list>/processed/` - structured JSON from [rmail-parser](https://github.com/r-mailing-lists/rmail-parser), one file per month
- `<list>/meta.json` - list statistics

`lists.tsv` at the top level indexes all lists.

## Updating

The **Update Archive** workflow runs daily: it asks Gmane for each list's articles newer than the last one read, adds them to the end of their month's file, and re-parses. Locally:

``` bash
RMAIL_PARSER=/path/to/rmail-parser tools/update.sh
```

To add a list, create `<list>/config.json` with its newsgroup and run `tools/update.sh <list>`. `python3 tools/gmane_test.py` runs the tests, and `python3 tools/gmane.py check all` looks for whole addresses in every file, saying where but not what.
