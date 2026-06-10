#!/usr/bin/env python3
"""Build the illustrated web book for the Shivaji series.

  build_page.py ch01        -> writes docs/ch01.html (+ refreshes the matter pages)
  build_page.py all         -> builds every chapter + all front/back matter

Reading flow (the "spine"):
  Cover (index.html) -> Dedication -> For Ansh -> Contents
    -> Chapter 1 ... Chapter 20
    -> Timeline -> Back cover

Chapter pages show a reference gallery for the chapter's new cast/places at the
top, and event illustrations inline after their text anchor. Images use public
Hetzner URLs so the site is portable. No external libs.
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

COVER_FRONT_URL = "https://hel1.your-objectstorage.com/openclaw83/shivaji/cover/cover-front.png"
COVER_BACK_URL = "https://hel1.your-objectstorage.com/openclaw83/shivaji/cover/cover.png"

# Front/back matter pages, in spine order. (chapters slot in between.)
FRONT_MATTER = [("index", "Cover"), ("dedication", "Dedication"),
                ("for-ansh", "For Ansh"), ("contents", "Contents")]
BACK_MATTER = [("timeline", "Timeline"), ("back-cover", "Back cover")]
MATTER_LABELS = {slug: label for slug, label in FRONT_MATTER + BACK_MATTER}


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


# --------------------------------------------------------------------------- #
# spine + navigation
# --------------------------------------------------------------------------- #
def spine() -> list[str]:
    chaps = sorted(p.stem for p in CHAPTERS.glob("ch*.md"))
    return [s for s, _ in FRONT_MATTER] + chaps + [s for s, _ in BACK_MATTER]


def label_for(slug: str) -> str:
    if slug in MATTER_LABELS:
        return MATTER_LABELS[slug]
    return chapter_title(slug)


def nav_html(slug: str, position: str) -> str:
    """Prev / Contents / Next bar, derived from the whole-book spine."""
    sp = spine()
    i = sp.index(slug)
    prev = sp[i - 1] if i > 0 else None
    nxt = sp[i + 1] if i < len(sp) - 1 else None
    left = (f'<a class="nav-prev" href="{prev}.html">&larr; {html.escape(label_for(prev))}</a>'
            if prev else '<span class="nav-prev nav-disabled">&larr; Cover</span>')
    right = (f'<a class="nav-next" href="{nxt}.html">{html.escape(label_for(nxt))} &rarr;</a>'
             if nxt else '<span class="nav-next nav-disabled">The End &rarr;</span>')
    mid = '<a class="nav-toc" href="contents.html">Contents</a>'
    return f'<nav class="chapter-nav {position}">{left}{mid}{right}</nav>'


# --------------------------------------------------------------------------- #
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


# --------------------------------------------------------------------------- #
# front / back matter pages
# --------------------------------------------------------------------------- #
def build_cover():
    (PAGES / "index.html").write_text(COVER_TMPL.replace("{cover}", bust(COVER_FRONT_URL)))


def build_dedication():
    (PAGES / "dedication.html").write_text(DEDICATION_TMPL)


def build_foransh():
    (PAGES / "for-ansh.html").write_text(FORANSH_TMPL)


def build_contents():
    chaps = sorted(p.stem for p in CHAPTERS.glob("ch*.md"))
    items = "\n".join(
        f'<li><a href="{c}.html">Chapter {int(re.sub(r"[^0-9]", "", c))} '
        f'<span class="ct">{html.escape(chapter_title(c)).split("— ", 1)[-1]}</span></a></li>'
        for c in chaps)
    first = chaps[0] if chaps else "ch01"
    (PAGES / "contents.html").write_text(
        CONTENTS_TMPL.replace("{items}", items)
                     .replace("{cover}", bust(COVER_FRONT_URL))
                     .replace("{first}", first))


def build_timeline():
    rows = "\n".join(
        f'<li><span class="yr">{html.escape(y)}</span>'
        f'<span class="ev">{inline(t)}{(" " + f"<a class=ch href={c}.html>({label_for(c).split(chr(8212))[0].strip()})</a>") if c else ""}</span></li>'
        for y, t, c in TIMELINE)
    (PAGES / "timeline.html").write_text(
        TIMELINE_TMPL.replace("{rows}", rows)
                     .replace("{nav_top}", nav_html("timeline", "top"))
                     .replace("{nav_bottom}", nav_html("timeline", "bottom")))


def build_backcover():
    (PAGES / "back-cover.html").write_text(
        BACKCOVER_TMPL.replace("{cover}", bust(COVER_BACK_URL))
                      .replace("{nav_top}", nav_html("back-cover", "top")))


def build_matter():
    build_cover()
    build_dedication()
    build_foransh()
    build_contents()
    build_timeline()
    build_backcover()


# --------------------------------------------------------------------------- #
# Timeline data (year, event, chapter-slug-or-None)
# --------------------------------------------------------------------------- #
TIMELINE = [
    ("1629", "Jijabai travels to the safety of Shivneri fort through a war-torn Deccan.", "ch01"),
    ("Feb 1630", "**Shivaji is born** inside Shivneri fort.", "ch01"),
    ("1636", "Shahaji enters Bijapur's service and is sent far south; Jijabai and Shivaji are settled at Pune.", "ch04"),
    ("late 1630s", "Pune, wrecked by war, is rebuilt and resettled under Jijabai and Dadoji Konddev.", "ch05"),
    ("1640s", "Shivaji trains under Dadoji and gathers his band of Maval companions in the hills.", "ch07"),
    ("1645", "The **oath of Swarajya** is sworn at the temple of Raireshwar.", "ch09"),
    ("1646", "Shivaji takes his first fort, **Torna**, at the age of sixteen.", "ch11"),
    ("1646–47", "Rajgad is built; Kondhana and Purandar are won by wit.", "ch12"),
    ("1647", "Dadoji Konddev dies; Shivaji takes full charge and raises his own royal seal.", "ch14"),
    ("1648", "Shahaji is arrested by treachery; Shivaji wins his first true battle at Purandar.", "ch15"),
    ("1649", "A daring letter to the Mughal prince helps free Shahaji.", "ch16"),
    ("1650–55", "The quiet years: Shivaji builds an army, forts, fair rule, and a network of spies.", "ch17"),
    ("Jan 1656", "Shivaji conquers the forest kingdom of **Javli** and first sees the great hill of Raigad.", "ch19"),
    ("1656", "**Pratapgad** is begun; Bijapur sends the giant general Afzal Khan. (End of Volume 1.)", "ch20"),
]


# --------------------------------------------------------------------------- #
# shared CSS (kept in sync across all pages)
# --------------------------------------------------------------------------- #
BASE_CSS = """
  :root { --ink:#2b2118; --paper:#fbf6ec; --accent:#8a3a1f; --soft:#efe6d3; --gold:#b6892f; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--paper); color:var(--ink);
    font-family:Georgia,"Iowan Old Style",serif; line-height:1.7; }
  a { color:var(--accent); text-decoration:none; }
  a:hover { text-decoration:underline; }
  .series { letter-spacing:.18em; text-transform:uppercase; font-size:.72rem; color:var(--accent); }
"""

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

# --- Front cover (index.html) -------------------------------------------------
COVER_TMPL = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Boy of Shivneri — Chhatrapati Shivaji, Volume 1</title>
<style>
""" + BASE_CSS + """
  .cover-wrap { min-height:100vh; display:flex; flex-direction:column; align-items:center;
    justify-content:center; text-align:center; padding:2rem 1.25rem 3rem;
    background:radial-gradient(circle at 50% 20%, #fff8ec, var(--paper)); }
  .cover-art { position:relative; max-width:460px; width:100%; }
  .cover-art img { width:100%; border-radius:10px;
    box-shadow:0 18px 50px rgba(60,40,20,.42); }
  .cover-series { margin-top:1.6rem; }
  h1.title { font-size:2.7rem; line-height:1.1; margin:.5rem 0 .2rem; color:var(--ink); }
  .subtitle { font-size:1.15rem; color:var(--accent); font-style:italic; }
  .open { display:inline-block; margin-top:1.8rem; padding:.7rem 1.6rem;
    border:2px solid var(--accent); border-radius:999px; font-size:1rem; color:var(--accent); }
  .open:hover { background:var(--accent); color:var(--paper); text-decoration:none; }
</style></head>
<body>
  <div class="cover-wrap">
    <div class="cover-art"><img src="{cover}" alt="The Boy of Shivneri — cover"></div>
    <div class="cover-series">
      <div class="series">Chhatrapati Shivaji &middot; Volume 1</div>
      <h1 class="title">The Boy of Shivneri</h1>
      <div class="subtitle">The childhood and rise of Shivaji Maharaj</div>
      <a class="open" href="dedication.html">Open the book &rarr;</a>
    </div>
  </div>
</body></html>
"""

# --- Dedication / heritage page ----------------------------------------------
DEDICATION_TMPL = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dedication — The Boy of Shivneri</title>
<style>
""" + BASE_CSS + """
  .center { min-height:100vh; display:flex; flex-direction:column; align-items:center;
    justify-content:center; text-align:center; padding:3rem 1.5rem; }
  .flourish { color:var(--gold); font-size:1.8rem; letter-spacing:.3em; margin-bottom:1.5rem; }
  .dedi { max-width:560px; font-size:1.5rem; line-height:1.6; color:var(--ink); }
  .dedi em { color:var(--accent); font-style:italic; }
  .more { margin-top:2.5rem; font-size:.95rem; }
  .more a { margin:0 .8rem; }
</style></head>
<body>
  <div class="center">
    <div class="flourish">&#10070; &#10070; &#10070;</div>
    <p class="dedi">This book is offered as a <em>heritage</em> to all Marathi children &mdash;
       in every corner of the world.<br><br>
       May you grow up knowing whose hills these were, and what one boy dared to dream upon them.</p>
    <p class="more">
      <a href="index.html">&larr; Cover</a>
      <a href="for-ansh.html">Continue &rarr;</a>
    </p>
  </div>
</body></html>
"""

# --- "For Ansh" page ----------------------------------------------------------
FORANSH_TMPL = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>For Ansh — The Boy of Shivneri</title>
<style>
""" + BASE_CSS + """
  .center { min-height:100vh; display:flex; flex-direction:column; align-items:center;
    justify-content:center; text-align:center; padding:3rem 1.5rem; }
  .for { font-size:1.1rem; letter-spacing:.35em; text-transform:uppercase; color:var(--accent); }
  .name { font-size:4.2rem; margin:.4rem 0 0; color:var(--ink); }
  .more { margin-top:3rem; font-size:.95rem; }
  .more a { margin:0 .8rem; }
</style></head>
<body>
  <div class="center">
    <div class="for">For</div>
    <h1 class="name">Ansh</h1>
    <p class="more">
      <a href="dedication.html">&larr; Back</a>
      <a href="contents.html">Contents &rarr;</a>
    </p>
  </div>
</body></html>
"""

# --- Contents (contents.html) ------------------------------------------------
CONTENTS_TMPL = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Contents — The Boy of Shivneri</title>
<style>
""" + BASE_CSS + """
  .wrap { max-width:640px; margin:0 auto; padding:3rem 1.25rem 5rem; }
  img.cover { display:block; width:100%; max-width:300px; margin:0 auto 1.8rem;
    border-radius:8px; box-shadow:0 10px 34px rgba(60,40,20,.30); }
  h1 { text-align:center; margin:.3rem 0 .2rem; font-size:1.9rem; }
  .subtitle { text-align:center; color:var(--accent); font-style:italic; margin-bottom:1.6rem; }
  h2.toc { text-align:center; color:var(--accent); font-size:.82rem; letter-spacing:.14em;
    text-transform:uppercase; border-top:1px solid var(--soft); border-bottom:1px solid var(--soft);
    padding:.6rem 0; margin:1.4rem 0 1.2rem; }
  ul { list-style:none; padding:0; }
  li { margin:.3rem 0; font-size:1.12rem; border-bottom:1px dotted #e0d4bd; padding:.35rem 0; }
  li a { display:flex; gap:.6rem; }
  li .ct { color:var(--ink); }
  .backmatter { margin-top:1.6rem; font-size:1rem; }
  .backmatter a { display:block; margin:.3rem 0; }
  .begin { display:block; text-align:center; margin:2rem 0 .5rem; padding:.7rem 1.6rem;
    border:2px solid var(--accent); border-radius:999px; }
  .begin:hover { background:var(--accent); color:var(--paper); text-decoration:none; }
  .topnav { text-align:center; margin-bottom:1.2rem; font-size:.92rem; }
  .topnav a { margin:0 .7rem; }
</style></head>
<body>
  <div class="wrap">
    <div class="topnav"><a href="for-ansh.html">&larr; For Ansh</a></div>
    <img class="cover" src="{cover}" alt="The Boy of Shivneri">
    <div class="series" style="text-align:center">Chhatrapati Shivaji &middot; Volume 1</div>
    <h1>The Boy of Shivneri</h1>
    <div class="subtitle">The childhood and rise of Shivaji Maharaj</div>
    <h2 class="toc">Contents</h2>
    <ul>{items}</ul>
    <div class="backmatter">
      <strong>At the back of the book</strong>
      <a href="timeline.html">&#9656; Timeline &mdash; 1629 to 1656</a>
    </div>
    <a class="begin" href="{first}.html">Begin the story &rarr;</a>
  </div>
</body></html>
"""

# --- Timeline (back matter) ---------------------------------------------------
TIMELINE_TMPL = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Timeline — The Boy of Shivneri</title>
<style>
""" + BASE_CSS + """
  .wrap { max-width:720px; margin:0 auto; padding:2.5rem 1.25rem 5rem; }
  header.book { text-align:center; border-bottom:2px solid var(--soft); padding-bottom:1.5rem; margin-bottom:2rem; }
  h1 { font-size:2.1rem; margin:.4rem 0 0; }
  .lede { text-align:center; color:#6b5d49; font-style:italic; max-width:560px; margin:.6rem auto 0; }
  ul.timeline { list-style:none; padding:0; margin:2rem 0 0; }
  ul.timeline li { display:flex; gap:1rem; padding:.9rem 0; border-bottom:1px dotted #e0d4bd; align-items:baseline; }
  ul.timeline .yr { flex:0 0 6.5rem; font-weight:bold; color:var(--accent); font-size:1rem; }
  ul.timeline .ev { flex:1; font-size:1.08rem; }
  ul.timeline .ch { font-size:.82rem; color:#9a7b3f; white-space:nowrap; }
  .chapter-nav { display:flex; align-items:center; gap:.6rem; margin:1.4rem 0;
    padding:.7rem 0; border-top:1px solid var(--soft); border-bottom:1px solid var(--soft); }
  .chapter-nav.top { margin-top:0; }
  .chapter-nav.bottom { margin-top:2.5rem; }
  .chapter-nav > * { flex:1; font-size:.92rem; color:var(--accent); }
  .chapter-nav .nav-prev { text-align:left; }
  .chapter-nav .nav-toc { text-align:center; font-weight:bold; }
  .chapter-nav .nav-next { text-align:right; }
  .chapter-nav .nav-disabled { color:#c9bca5; }
</style></head>
<body>
  <div class="wrap">
    {nav_top}
    <header class="book">
      <div class="series">Chhatrapati Shivaji &middot; Volume 1 &middot; The Boy of Shivneri</div>
      <h1>Timeline</h1>
      <p class="lede">The years of this book, from a mother's journey to a giant's challenge &mdash; 1629 to 1656.</p>
    </header>
    <ul class="timeline">{rows}</ul>
    {nav_bottom}
  </div>
</body></html>
"""

# --- Back cover ---------------------------------------------------------------
BACKCOVER_TMPL = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Boy of Shivneri</title>
<style>
""" + BASE_CSS + """
  .wrap { max-width:560px; margin:0 auto; padding:2.5rem 1.25rem 4rem; }
  .chapter-nav { display:flex; align-items:center; gap:.6rem; margin:0 0 2rem;
    padding:.7rem 0; border-bottom:1px solid var(--soft); }
  .chapter-nav > * { flex:1; font-size:.92rem; color:var(--accent); }
  .chapter-nav .nav-prev { text-align:left; }
  .chapter-nav .nav-toc { text-align:center; font-weight:bold; }
  .chapter-nav .nav-next { text-align:right; }
  .chapter-nav .nav-disabled { color:#c9bca5; }
  img.cover { display:block; width:100%; max-width:420px; margin:0 auto 2rem;
    border-radius:8px; box-shadow:0 12px 38px rgba(60,40,20,.34); }
  .blurb { text-align:center; font-size:1.12rem; }
  .blurb .big { font-size:1.35rem; color:var(--accent); font-style:italic; display:block; margin-bottom:1rem; }
  .next-up { margin-top:2.2rem; text-align:center; color:#6b5d49; font-size:.98rem; }
</style></head>
<body>
  <div class="wrap">
    {nav_top}
    <img class="cover" src="{cover}" alt="The Boy of Shivneri — back cover">
    <p class="blurb"><span class="big">A kingdom is not given. It is built &mdash; stone by stone,
      and choice by choice.</span>
      Born inside a mountain fortress while the Deccan burned, a boy grows up asking a dangerous question:
      whose land is this, really? This is the story of how Shivaji turned a child's wish into forts, into an
      army, into a free people&rsquo;s cause &mdash; <em>Swarajya.</em></p>
    <p class="next-up">The story continues in <strong>Volume 2 &mdash; The Mountain Lion.</strong></p>
  </div>
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
    build_matter()
    for name in ("index", "dedication", "for-ansh", "contents", "timeline", "back-cover"):
        print("built", (PAGES / f"{name}.html").relative_to(ROOT))


if __name__ == "__main__":
    main()
