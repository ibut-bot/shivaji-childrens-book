#!/usr/bin/env python3
"""Generate reference art and event art for the Shivaji series.

  refgen.py refs                 generate any missing reference images (index.json)
  refgen.py events ch01          generate any missing event images for a chapter
  refgen.py status               show what's generated / pending

Flags: --force (regenerate even if present), --only slug[,slug...].

Reference images are text-to-image. Event images are edit-image, conditioned on
the reference images of the entities they cite (refs), so characters/places stay
consistent. Idempotent: re-running only fills in what's missing. All images are
low quality / 1024x1024 per project setting (see imagine.py defaults).
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import imagine

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "reference" / "index.json"
EVENTS_DIR = ROOT / "reference" / "events"
CHAPTERS_DIR = ROOT / "chapters"

SUFFIX = (" No text, no words, no letters and no captions anywhere in the image. "
          "A single cohesive illustration. Use natural, balanced colour and lighting; "
          "AVOID an artificial uniform yellow or golden sheen / glow washed over the whole image.")
MAX_WORKERS = 4


def _load(p: Path) -> dict:
    return json.loads(p.read_text())


def _save(p: Path, data: dict) -> None:
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _parse_only(val: str | None) -> set[str] | None:
    return {s.strip() for s in val.split(",")} if val else None


# --------------------------------------------------------------------------- #
def cmd_refs(args):
    data = _load(INDEX)
    style = data["style"]
    only = _parse_only(args.only)
    todo = []
    for slug, e in data["entities"].items():
        if only and slug not in only:
            continue
        if e.get("image") and not args.force:
            continue
        todo.append(e)
    if not todo:
        print("Reference art: nothing to do (all present). Use --force to regenerate.")
        return

    print(f"Generating {len(todo)} reference image(s): {', '.join(e['slug'] for e in todo)}")

    def work(e):
        prompt = f"{style} {e['visual_description']} {e['ref_prompt']}{SUFFIX}"
        key = f"shivaji/reference/{e['type']}s/{e['slug']}.png"
        local = ROOT / "reference" / f"{e['type']}s" / f"{e['slug']}.png"
        # If a looked-up source image is provided (e.g. a documented historical
        # likeness), condition on it via edit-image so the result matches.
        sources = e.get("source_refs") or None
        mode = e.get("source_mode")
        if sources and mode == "costume":
            # Copy ONLY the headgear/costume from the source, NOT the person.
            prompt = (f"{style} {e['visual_description']} {e['ref_prompt']} "
                      f"Use the provided reference image ONLY to copy the exact TURBAN / HEADGEAR shape, style and colour "
                      f"and the clothing style and colours. Do NOT copy the reference person's face, age or build — the "
                      f"face, age, build and identity must follow the written description above (a clearly DIFFERENT, "
                      f"distinct person). Ignore any watermark or base/platform in the source.{SUFFIX}")
        elif sources:
            prompt = (f"{style} Redraw this person as {e['visual_description']} {e['ref_prompt']} "
                      f"Match the source image for the FACE, moustache/beard, and turban/headgear shape and colour, "
                      f"and the overall clothing style. Otherwise the written description takes PRIORITY — especially "
                      f"for weapons, shield, and footwear, which must follow the description even if the source differs. "
                      f"Ignore any watermark or base/platform in the source.{SUFFIX}")
        url = imagine.generate_and_store(key=key, prompt=prompt, refs=sources, local_copy=local)
        return e["slug"], key, url

    results = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(work, e): e["slug"] for e in todo}
        for fut in as_completed(futs):
            slug = futs[fut]
            try:
                slug, key, url = fut.result()
                results[slug] = {"s3_key": key, "url": url,
                                 "local": f"reference/{data['entities'][slug]['type']}s/{slug}.png"}
                print(f"  ✓ {slug}")
            except Exception as ex_err:
                print(f"  ✗ {slug}: {ex_err}")

    # write back (reload to avoid clobbering, then merge)
    data = _load(INDEX)
    for slug, img in results.items():
        data["entities"][slug]["image"] = img
    _save(INDEX, data)
    print(f"Updated {INDEX.relative_to(ROOT)} ({len(results)} image(s)).")


# --------------------------------------------------------------------------- #
def cmd_events(args):
    chap = args.chapter
    ev_path = EVENTS_DIR / f"{chap}.json"
    if not ev_path.exists():
        sys.exit(f"No event file: {ev_path}")
    idx = _load(INDEX)
    entities = idx["entities"]
    style = idx["style"]
    evdata = _load(ev_path)
    chap_md = (CHAPTERS_DIR / f"{chap}.md").read_text()
    only = _parse_only(args.only)

    # validate anchors + refs up front
    problems = []
    for e in evdata["events"]:
        if e["anchor"] not in chap_md:
            problems.append(f"anchor not found in {chap}.md for '{e['slug']}': {e['anchor'][:50]}...")
        for r in e["refs"]:
            if r not in entities:
                problems.append(f"event '{e['slug']}' cites unknown ref '{r}'")
            elif not entities[r].get("image"):
                problems.append(f"event '{e['slug']}' needs ref '{r}' but it has no image yet (run `refs` first)")
    if problems:
        print("Cannot generate events:")
        for p in problems:
            print("  -", p)
        sys.exit(1)

    todo = [e for e in evdata["events"]
            if (not e.get("image") or args.force) and (not only or e["slug"] in only)]
    if not todo:
        print("Event art: nothing to do (all present). Use --force to regenerate.")
        return
    print(f"Generating {len(todo)} event image(s): {', '.join(e['slug'] for e in todo)}")

    def work(e):
        ref_urls = [entities[r]["image"]["url"] for r in e["refs"]]
        ref_desc = " ".join(f"{entities[r]['name']}: {entities[r]['visual_description']}" for r in e["refs"])
        prompt = (f"{style} {e['scene_prompt']} "
                  f"Use the reference images for the costume design, named characters and places. "
                  f"Each NAMED character must match their reference image's FACE, age and FACIAL HAIR exactly "
                  f"(e.g. the teenage Shivaji always has his thin moustache and NO beard; do not change his features). "
                  f"IMPORTANT: when several soldiers or background people appear, give each one a DISTINCT "
                  f"face, age and build — vary their features; never repeat the same identical face. The "
                  f"Mavala reference defines the uniform/look, not a single repeated person. "
                  f"(Reference details — {ref_desc}){SUFFIX}")
        key = f"shivaji/events/{chap}/{e['slug']}.png"
        local = ROOT / "reference" / "events" / chap / f"{e['slug']}.png"
        url = imagine.generate_and_store(key=key, prompt=prompt, refs=ref_urls, local_copy=local)
        return e["slug"], key, url

    results = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(work, e): e["slug"] for e in todo}
        for fut in as_completed(futs):
            slug = futs[fut]
            try:
                slug, key, url = fut.result()
                results[slug] = {"s3_key": key, "url": url,
                                 "local": f"reference/events/{chap}/{slug}.png"}
                print(f"  ✓ {slug}")
            except Exception as ex_err:
                print(f"  ✗ {slug}: {ex_err}")

    evdata = _load(ev_path)
    for e in evdata["events"]:
        if e["slug"] in results:
            e["image"] = results[e["slug"]]
    _save(ev_path, evdata)
    print(f"Updated {ev_path.relative_to(ROOT)} ({len(results)} image(s)).")


# --------------------------------------------------------------------------- #
def cmd_status(args):
    idx = _load(INDEX)
    print("References:")
    for slug, e in idx["entities"].items():
        mark = "✓" if e.get("image") else "·"
        print(f"  {mark} {slug:22s} ({e['type']})")
    for ev_path in sorted(EVENTS_DIR.glob("*.json")):
        ev = _load(ev_path)
        print(f"\nEvents — {ev_path.stem}:")
        for e in ev["events"]:
            mark = "✓" if e.get("image") else "·"
            print(f"  {mark} {e['slug']:24s} -> refs: {', '.join(e['refs'])}")


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refs"); r.add_argument("--force", action="store_true"); r.add_argument("--only")
    r.set_defaults(fn=cmd_refs)
    e = sub.add_parser("events"); e.add_argument("chapter"); e.add_argument("--force", action="store_true"); e.add_argument("--only")
    e.set_defaults(fn=cmd_events)
    s = sub.add_parser("status"); s.set_defaults(fn=cmd_status)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
