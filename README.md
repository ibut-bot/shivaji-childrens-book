# Shivaji — an illustrated children's book series

A middle-grade (ages 8–12) illustrated chapter-book series about the life of
**Chhatrapati Shivaji Maharaj**. Narrative prose with AI-generated illustrations,
published as simple web pages.

## 📖 Read it

**→ https://ibut-bot.github.io/shivaji-childrens-book/**

Volume 1 — *The Boy of Shivneri* (Chapters 1–7 so far).

## How it works

- `chapters/` — the prose, one Markdown file per chapter.
- `reference/index.json` — a registry of every recurring **character, location,
  and object**, with a locked visual description and its generated reference image.
- `reference/events/chNN.json` — the key illustrated moments in each chapter, each
  anchored to a phrase in the text and listing which references it reuses.
- `tools/`
  - `imagine.py` — generates art with **fal.ai `gpt-image-2`** (low quality,
    1024×1024) and uploads it to **Hetzner Object Storage** (S3-compatible).
  - `refgen.py` — idempotently generates reference art (text-to-image) and event
    art (image-to-image, conditioned on the cited references for consistency).
  - `build_page.py` — renders each chapter to `docs/chNN.html`, with a reference
    gallery at the top and event illustrations placed inline at their text anchors.
- `docs/` — the static site served by GitHub Pages. Images load from the public
  Hetzner bucket, so the pages render anywhere.

## A note on history vs. story

From Chapter 4 onward the factual spine of each chapter is **documented history
only**; famous **legends** (e.g. the golden plough of Pune) are still told but are
**clearly labelled as legend** in the text and in a per-chapter "What We Know" note.
Chapters 1–3 are earlier, more dramatised storytelling. See `style-guide.md`.

## Running the pipeline

Requires a `.env` (not committed) with `FAL_API_KEY` and Hetzner credentials.

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r tools/requirements.txt
./.venv/bin/python tools/refgen.py refs           # generate any missing references
./.venv/bin/python tools/refgen.py events ch07     # generate a chapter's event art
./.venv/bin/python tools/build_page.py all         # rebuild the web pages
```

*Illustrations are AI-generated. Historical figures are depicted respectfully; the
series is about character and the protection of ordinary people, not community.*
