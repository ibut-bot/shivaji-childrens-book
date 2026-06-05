#!/usr/bin/env python3
"""Build the illustrated web page for a chapter.

  build_page.py ch01        -> writes pages/ch01.html (+ refreshes pages/index.html)
  build_page.py all         -> builds every chapter that has a markdown file

Layout (what the user asked for):
  * Reference images for the chapter's new cast/places/objects in a gallery at
    the START of the chapter.
  * The chapter prose, with each event illustration inserted inline right after
    the paragraph where that event happens (matched by its text anchor).

Images use the public Hetzner URLs, so the page is portable. No external libs.
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
from pathlib import Path

# Bumped every build; appended to image URLs so the browser never shows a stale
# cached image after we overwrite art at the same S3 key.
BUILD_VERSION = str(int(time.time()))


def bust(url: str) -> str:
    if not url:
        return url
    return url + ("&" if "?" in url else "?") + "v=" + BUILD_VERSION

ROOT = Path(__file__).resolve().parent.parent
CHAPTERS = ROOT / "chapters"
PAGES = ROOT / "docs"  # served by GitHub Pages (source: master /docs)
INDEX = ROOT / "reference" / "index.json"
EVENTS_DIR = ROOT / "reference" / "events"


# --------------------------------------------------------------------------- #
# tiny markdown -> html (handles just what our chapters use)
# --------------------------------------------------------------------------- #
def inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text)
    return text


def blocks(md: str):
    """Yield (kind, text) blocks separated by blank lines."""
    for raw in re.split(r"\n\s*\n", md.strip()):
        b = raw.strip()
        if not b:
            continue
        if b.startswith("# "):
            yield ("h1", b[2:].strip())
        elif b.startswith("### "):
            yield ("h3", b[4:].strip())
        elif b.startswith("## "):
            yield ("h2", b[3:].strip())
        elif set(b) == {"-"} and len(b) >= 3:
            yield ("hr", "")
        else:
            yield ("p", b)


# --------------------------------------------------------------------------- #
def figure_html(img_url: str, title: str, hero: bool = False) -> str:
    cls = "event hero" if hero else "event"
    return (f'<figure class="{cls}">'
            f'<img loading="lazy" src="{html.escape(bust(img_url))}" alt="{html.escape(title)}">'
            f'<figcaption>{html.escape(title)}</figcaption></figure>')


def ref_card(e: dict) -> str:
    img = e.get("image") or {}
    url = img.get("url", "")
    desc = e["visual_description"].split(".")[0] + "."
    return (f'<figure class="refcard">'
            f'<img loading="lazy" src="{html.escape(bust(url))}" alt="{html.escape(e["name"])}">'
            f'<figcaption><strong>{html.escape(e["name"])}</strong>'
            f'<span class="reftype">{html.escape(e["type"])}</span>'
            f'<span class="refdesc">{html.escape(desc)}</span></figcaption></figure>')


def chapter_title(stem: str) -> str:
    md = (CHAPTERS / f"{stem}.md").read_text()
    return next((t for k, t in blocks(md) if k == "h1"), stem)


def nav_html(chap: str, position: str) -> str:
    """Prev / Contents / Next navigation bar for a chapter page."""
    chaps = sorted(p.stem for p in CHAPTERS.glob("ch*.md"))
    i = chaps.index(chap)
    prev = chaps[i - 1] if i > 0 else None
    nxt = chaps[i + 1] if i < len(chaps) - 1 else None
    left = (f'<a class="nav-prev" href="{prev}.html">&larr; {html.escape(chapter_title(prev))}</a>'
            if prev else '<span class="nav-prev nav-disabled">&larr; Start</span>')
    right = (f'<a class="nav-next" href="{nxt}.html">{html.escape(chapter_title(nxt))} &rarr;</a>'
             if nxt else '<span class="nav-next nav-disabled">The End &rarr;</span>')
    mid = '<a class="nav-toc" href="index.html">Contents</a>'
    return f'<nav class="chapter-nav {position}">{left}{mid}{right}</nav>'


def build_chapter(chap: str) -> Path:
    md = (CHAPTERS / f"{chap}.md").read_text()
    idx = json.loads(INDEX.read_text())
    entities = idx["entities"]
    chap_num = int(re.sub(r"\D", "", chap))

    ev_path = EVENTS_DIR / f"{chap}.json"
    events = json.loads(ev_path.read_text())["events"] if ev_path.exists() else []
    pending = [e for e in events if e.get("image")]

    # reference gallery = entities introduced in this chapter, grouped by type
    intro = [e for e in entities.values() if e.get("first_chapter") == chap_num and e.get("image")]
    groups = {"character": [], "location": [], "object": []}
    for e in intro:
        groups.get(e["type"], []).append(e)

    title = next((t for k, t in blocks(md) if k == "h1"), chap)

    # --- render body, inserting event figures after their anchor paragraph
    body_parts = []
    used = set()
    for kind, text in blocks(md):
        if kind == "h1":
            continue  # title handled in header
        elif kind == "hr":
            body_parts.append('<hr class="scene">')
        elif kind == "h2":
            body_parts.append(f"<h2>{inline(text)}</h2>")
        elif kind == "h3":
            body_parts.append(f'<h3 class="endnote-h">{inline(text)}</h3>')
        else:
            body_parts.append(f"<p>{inline(text)}</p>")
            for e in pending:
                if e["slug"] in used:
                    continue
                if e["anchor"] in text:
                    body_parts.append(figure_html(e["image"]["url"], e["title"], e.get("hero", False)))
                    used.add(e["slug"])

    # any event whose anchor didn't match a paragraph (safety): append at end
    leftover = [e for e in pending if e["slug"] not in used]
    for e in leftover:
        body_parts.append(figure_html(e["image"]["url"], e["title"], e.get("hero", False)))

    # --- reference gallery html
    gallery = ""
    label = {"character": "Characters", "location": "Places", "object": "Objects"}
    if intro:
        sections = []
        for typ in ("character", "location", "object"):
            if groups[typ]:
                cards = "\n".join(ref_card(e) for e in groups[typ])
                sections.append(f'<h3>{label[typ]}</h3><div class="refgrid">{cards}</div>')
        gallery = (f'<section class="references"><h2>Who &amp; Where in this chapter</h2>'
                   f'{"".join(sections)}</section>')

    page = PAGE_TMPL.format(title=html.escape(title), gallery=gallery,
                            body="\n".join(body_parts),
                            nav_top=nav_html(chap, "top"), nav_bottom=nav_html(chap, "bottom"))
    PAGES.mkdir(exist_ok=True)
    out = PAGES / f"{chap}.html"
    out.write_text(page)
    return out


COVER_URL = "https://hel1.your-objectstorage.com/openclaw83/shivaji/cover/cover.png"


def build_index():
    chaps = sorted(p.stem for p in PAGES.glob("ch*.html"))
    items = "\n".join(
        f'<li><a href="{c}.html">Chapter {int(re.sub(r"[^0-9]", "", c))} — {html.escape(chapter_title(c)).split("— ",1)[-1]}</a></li>'
        for c in chaps)
    (PAGES / "index.html").write_text(INDEX_TMPL.format(items=items, cover=bust(COVER_URL)))


# --------------------------------------------------------------------------- #
PAGE_TMPL = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — The Boy of Shivneri</title>
<style>
  :root {{ --ink:#2b2118; --paper:#fbf6ec; --accent:#8a3a1f; --soft:#efe6d3; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--paper); color:var(--ink);
    font-family:Georgia,"Iowan Old Style",serif; line-height:1.7; }}
  .wrap {{ max-width:760px; margin:0 auto; padding:2.5rem 1.25rem 5rem; }}
  header.book {{ text-align:center; border-bottom:2px solid var(--soft); padding-bottom:1.5rem; margin-bottom:2rem; }}
  header.book .series {{ letter-spacing:.18em; text-transform:uppercase; font-size:.72rem; color:var(--accent); }}
  h1 {{ font-size:2.1rem; margin:.4rem 0 0; }}
  h2 {{ font-size:1.35rem; color:var(--accent); margin-top:2.5rem; }}
  p {{ margin:1.05rem 0; font-size:1.12rem; }}
  hr.scene {{ border:none; text-align:center; margin:2.2rem 0; }}
  hr.scene::before {{ content:"\\2767"; color:var(--accent); font-size:1.3rem; }}
  figure {{ margin:2rem 0; text-align:center; }}
  figure.event img {{ width:100%; max-width:560px; border-radius:10px;
    box-shadow:0 8px 26px rgba(60,40,20,.22); }}
  figure.event.hero img {{ max-width:100%; }}
  figcaption {{ font-size:.92rem; color:#7a6a55; font-style:italic; margin-top:.5rem; }}
  .references {{ background:var(--soft); border-radius:14px; padding:1.4rem 1.4rem .4rem;
    margin-bottom:2.5rem; }}
  .references h2 {{ margin-top:0; text-align:center; }}
  .references h3 {{ font-size:.82rem; letter-spacing:.12em; text-transform:uppercase;
    color:var(--accent); margin:1rem 0 .6rem; }}
  .refgrid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(210px,1fr)); gap:1.35rem; }}
  .refcard {{ margin:0; background:var(--paper); border-radius:12px; padding:.7rem;
    box-shadow:0 4px 14px rgba(60,40,20,.14); }}
  .refcard img {{ width:100%; border-radius:9px; aspect-ratio:1/1; object-fit:contain; background:var(--soft); }}
  .refcard figcaption {{ font-style:normal; text-align:left; margin-top:.6rem; font-size:.92rem; line-height:1.4; }}
  .refcard figcaption strong {{ font-size:1.02rem; }}
  .refcard .reftype {{ display:block; font-size:.68rem; text-transform:uppercase;
    letter-spacing:.08em; color:var(--accent); margin:.15rem 0; }}
  .refcard .refdesc {{ display:block; color:#6b5d49; }}
  .endnote-h {{ margin-top:2.5rem; color:var(--accent); border-top:2px solid var(--soft); padding-top:1.4rem; }}
  .chapter-nav {{ display:flex; align-items:center; gap:.6rem; margin:1.4rem 0;
    padding:.7rem 0; border-top:1px solid var(--soft); border-bottom:1px solid var(--soft); }}
  .chapter-nav.top {{ margin-top:0; }}
  .chapter-nav.bottom {{ margin-top:2.5rem; }}
  .chapter-nav > * {{ flex:1; font-size:.92rem; color:var(--accent); text-decoration:none; }}
  .chapter-nav a:hover {{ text-decoration:underline; }}
  .chapter-nav .nav-prev {{ text-align:left; }}
  .chapter-nav .nav-toc {{ text-align:center; font-weight:bold; }}
  .chapter-nav .nav-next {{ text-align:right; }}
  .chapter-nav .nav-disabled {{ color:#c9bca5; }}
</style>
</head>
<body>
<div class="wrap">
  {nav_top}
  <header class="book">
    <div class="series">Chhatrapati Shivaji &middot; Volume 1 &middot; The Boy of Shivneri</div>
    <h1>{title}</h1>
  </header>
  {gallery}
  <article>
  {body}
  </article>
  {nav_bottom}
</div>
</body>
</html>
"""

INDEX_TMPL = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Boy of Shivneri — Contents</title>
<style>
  body {{ background:#fbf6ec; color:#2b2118; font-family:Georgia,serif;
    max-width:640px; margin:0 auto; padding:3rem 1.25rem; line-height:1.7; }}
  .series {{ letter-spacing:.18em; text-transform:uppercase; font-size:.72rem; color:#8a3a1f; }}
  h1 {{ margin:.3rem 0 1.5rem; }}
  img.cover {{ display:block; width:100%; max-width:460px; margin:0 auto 2.2rem;
    border-radius:6px; box-shadow:0 10px 34px rgba(60,40,20,.28); }}
  h2.toc {{ text-align:center; color:#8a3a1f; font-size:.82rem; letter-spacing:.14em;
    text-transform:uppercase; border-top:1px solid #efe6d3; border-bottom:1px solid #efe6d3;
    padding:.6rem 0; margin:0 0 1.2rem; }}
  ul {{ list-style:none; padding:0; }}
  li {{ margin:.4rem 0; font-size:1.2rem; }}
  a {{ color:#8a3a1f; text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
</style></head>
<body>
  <img class="cover" src="{cover}" alt="The Boy of Shivneri — cover">
  <h2 class="toc">Contents</h2>
  <ul>{items}</ul>
</body></html>
"""


def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv:
        sys.exit("usage: build_page.py <chNN|all>")
    target = argv[0]
    if target == "all":
        for p in sorted(CHAPTERS.glob("ch*.md")):
            out = build_chapter(p.stem)
            print("built", out.relative_to(ROOT))
    else:
        out = build_chapter(target)
        print("built", out.relative_to(ROOT))
    build_index()
    print("built", (PAGES / "index.html").relative_to(ROOT))


if __name__ == "__main__":
    main()
