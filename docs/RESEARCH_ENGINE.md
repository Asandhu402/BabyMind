# Opt-in research and context card

In Chat, turn on **Deep research** before submitting a question of at most 500
characters. This explicitly sends the question and up to two model-generated
search queries to DuckDuckGo. BabyMind searches those queries concurrently,
selects up to six distinct results in round-robin order, and reads the pages
using its bounded public HTML/text reader. It gives excerpts from successfully
read pages to the configured model, asks for numbered citations, and shows a
server-generated source list and links in the response. The report and question
are saved in the encrypted conversation. The link buttons appear on the
immediate response; the saved text retains the URLs when reopened.

Search failures, unreadable sources, invalid plans, missing or unknown citation
numbers, model-generated URLs that were not fetched, and report truncation are
reported. If no page can be read, no sourced model report is generated. Citation
validation checks only that numbers refer to read pages; it **does not check
whether claims are supported or true**. Page text may be incomplete, stale,
misleading, or adversarial. This is bounded, single-depth research, not
GPT Researcher or a fact-checking guarantee. Only the first 1,200 characters of
each page are given to the model. The model may fail to follow the citation or
untrusted-data instructions. Search and fetch network timeouts apply, but a
whole-request deadline or cancellation is not implemented. Independent agents
or multi-model routing are not implemented.

The mode is off by default. It cannot be combined with collaborative chat or
attachments in the UI. It uses the current question, not earlier chat messages,
as the search query; avoid including private data. Search queries are visible to
the public search provider. Fetched pages and (if enabled) memory are sent to
the configured model; do not use a model endpoint you do not trust with them.
The search uses pinned public DNS and permits redirects only to the same search
host; page fetching retains BabyMind's public-address, redirect, response-size,
and content-type checks. This is not a complete defense against malicious
content or a network security audit.

## Research a selected text document

Attach one plain-text file (up to 12,000 bytes), enable **Research document**,
and submit a question of at most 500 characters. This mode performs no web
search and does not send the file to the search provider. It uses up to three
1,200-character excerpts ranked lexically against the question, with numbered
references giving filename, line range, and one-based character offsets. Long
lines can span multiple excerpts; those offsets identify the actual fragment.
The model only sees the selected excerpts and cannot inspect the rest. Omitted
content is reported. Citation-number validation does not establish that a
statement is supported, or that the document is trustworthy.

The uploaded text is sent to the configured model and processed as untrusted
content; only use a model provider you trust. The question and generated report
are saved in the encrypted conversation; the attachment itself is not stored as
a separate record, though the report or an explicitly saved memory can repeat
its contents. As with other memory, the local encryption key is accessible to
the local user. This is not a complete document-research system: the mode
supports a single small text attachment, not PDFs, office documents, multiple
files, OCR, semantic search, or independent research agents. The separate
optional Docling integration remains available for document conversion, but is
not connected to this mode.

## Context card

The Memory view has an optional, user-edited context card (up to 4,000
characters). It is encrypted in the existing memory database with the existing
local key. The card is only included in regular chat when **Use memory** is on,
and is explicitly labeled as untrusted context, not a system instruction. It
is not learned or updated automatically. The separate default-on learning
supervisor improves BabyMind's own source under verification and never infers,
writes or manages this card; see
[permanent autonomous learning](AUTONOMOUS_LEARNING.md). When deep research and
memory are both on, at most 300 characters of the card and two relevant saved
memories are included in the synthesis prompt; lexical memory search can fall
back to recent notes when nothing matches. These are not sent to the search
provider and are not source evidence. **Remember** remains opt-in. Clear all
memory also deletes the card. The key is accessible to the local user, so this
does not protect against a compromised account. As with all prompt-based
controls, malicious or mistaken context may still influence the model.

## Verification and scope

The new Python tests exercise planning fallback, parallel retrieval, deduplication,
partial failure, citation warnings, consent, encrypted persistence, and the
HTTP chat route with fake providers/search results. A separate live probe read a
public GitHub page through the existing page reader with a fixture search and
model. The DOM test exercises the actual chat and context-card code in jsdom;
it is not a real-browser or desktop test. No real model or public search
provider was available in this sandbox. The test host was Debian 12 x86-64 with
Python 3.11 (outside BabyMind's supported Python range), not Ubuntu 26.10. Run
the suite and real-model acceptance on a trusted Ubuntu 26.10 x86-64 machine
before claiming that target was tested:

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -q
npm ci && npm run test:ui
```

Real model/internet acceptance and sandbox tests must be run separately using
that machine's configured model and the existing scripts/security instructions.
This change does not add or upgrade any runtime dependency.

The document-research mode was tested with a scripted model and HTTP/DOM
fixtures on Debian 12 x86-64 and Python 3.11; real-model inference and Ubuntu
26.10 acceptance were not available for this change.
