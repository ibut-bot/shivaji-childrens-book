#!/usr/bin/env python3
"""Core image pipeline for the Shivaji book series.

Generates art with fal.ai GPT-Image-1 (low quality, 1024x1024 by default) and
uploads the result to Hetzner Object Storage (S3-compatible) with a public-read
ACL, returning a stable public URL.

Two generation modes:
  * text_to_image  -> brand-new reference art (characters, locations, objects)
  * edit_image     -> event art, conditioned on reference images for consistency

Usable as a library (import) or a small CLI for one-off testing.
"""
from __future__ import annotations

import argparse
import mimetypes
import os
import sys
import time
from pathlib import Path

import boto3
import requests
from botocore.client import Config

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

# --- gpt-image-2 defaults (user's instruction: low effort, lowest 1024 resolution)
DEFAULT_QUALITY = "low"
DEFAULT_SIZE = "square_hd"  # gpt-image-2 preset == 1024x1024

T2I_MODEL = "fal-ai/gpt-image-2"
EDIT_MODEL = "fal-ai/gpt-image-2/edit"
QUEUE_BASE = "https://queue.fal.run"


def load_env() -> dict:
    """Minimal .env loader (no external dep). Returns the parsed dict and also
    populates os.environ for anything not already set."""
    env: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    # environment overrides file
    for k, v in os.environ.items():
        if k in env or k in ("FAL_API_KEY", "FAL_KEY") or k.startswith("HETZNER_"):
            env.setdefault(k, v)
    return env


_ENV = load_env()


def _fal_key() -> str:
    key = _ENV.get("FAL_API_KEY") or _ENV.get("FAL_KEY") or os.environ.get("FAL_KEY")
    if not key:
        raise RuntimeError("FAL_API_KEY not set in .env")
    return key


# --------------------------------------------------------------------------- #
# fal generation (queue API)
# --------------------------------------------------------------------------- #
def _fal_submit(model: str, payload: dict) -> dict:
    headers = {"Authorization": f"Key {_fal_key()}", "Content-Type": "application/json"}
    r = requests.post(f"{QUEUE_BASE}/{model}", json=payload, headers=headers, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"fal submit failed {r.status_code}: {r.text[:500]}")
    return r.json()


def _fal_poll(submit_resp: dict, timeout: int = 300, interval: float = 3.0) -> dict:
    headers = {"Authorization": f"Key {_fal_key()}"}
    status_url = submit_resp["status_url"]
    response_url = submit_resp["response_url"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = requests.get(status_url, headers=headers, timeout=60).json()
        status = s.get("status")
        if status == "COMPLETED":
            return requests.get(response_url, headers=headers, timeout=60).json()
        if status in ("FAILED", "ERROR"):
            raise RuntimeError(f"fal job failed: {s}")
        time.sleep(interval)
    raise TimeoutError(f"fal job timed out after {timeout}s")


def _run(model: str, payload: dict) -> str:
    """Run a fal job and return the URL of the first generated image."""
    result = _fal_poll(_fal_submit(model, payload))
    images = result.get("images") or []
    if not images:
        raise RuntimeError(f"no images in fal response: {str(result)[:500]}")
    return images[0]["url"]


def text_to_image(prompt: str, *, size: str = DEFAULT_SIZE,
                  quality: str = DEFAULT_QUALITY) -> str:
    return _run(T2I_MODEL, {
        "prompt": prompt,
        "image_size": size,
        "quality": quality,
        "num_images": 1,
        "output_format": "png",
    })


def edit_image(prompt: str, image_urls: list[str], *, size: str = DEFAULT_SIZE,
               quality: str = DEFAULT_QUALITY) -> str:
    return _run(EDIT_MODEL, {
        "prompt": prompt,
        "image_urls": image_urls,
        "image_size": size,
        "quality": quality,
        "num_images": 1,
        "output_format": "png",
    })


# --------------------------------------------------------------------------- #
# Hetzner Object Storage
# --------------------------------------------------------------------------- #
def _s3():
    return boto3.client(
        "s3",
        endpoint_url=_ENV["HETZNER_ENDPOINT_URL"],
        aws_access_key_id=_ENV["HETZNER_ACCESS_KEY"],
        aws_secret_access_key=_ENV["HETZNER_SECRET_KEY"],
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def public_url(key: str) -> str:
    endpoint = _ENV["HETZNER_ENDPOINT_URL"].rstrip("/")
    bucket = _ENV["HETZNER_BUCKET_NAME"]
    return f"{endpoint}/{bucket}/{key}"


def upload_bytes(data: bytes, key: str, content_type: str = "image/png") -> str:
    _s3().put_object(
        Bucket=_ENV["HETZNER_BUCKET_NAME"],
        Key=key,
        Body=data,
        ContentType=content_type,
        ACL="public-read",
    )
    return public_url(key)


def fetch_bytes(url: str) -> bytes:
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    return r.content


def generate_and_store(*, key: str, prompt: str, refs: list[str] | None = None,
                       size: str = DEFAULT_SIZE, quality: str = DEFAULT_QUALITY,
                       local_copy: Path | None = None) -> str:
    """Generate (t2i if no refs, else edit), upload to Hetzner, return public URL.
    Optionally save a local copy next to the JSON for offline preview."""
    if refs:
        fal_url = edit_image(prompt, refs, size=size, quality=quality)
    else:
        fal_url = text_to_image(prompt, size=size, quality=quality)
    data = fetch_bytes(fal_url)
    if local_copy:
        local_copy.parent.mkdir(parents=True, exist_ok=True)
        local_copy.write_bytes(data)
    ctype = mimetypes.guess_type(key)[0] or "image/png"
    return upload_bytes(data, key, ctype)


# --------------------------------------------------------------------------- #
# CLI (for testing the path end to end)
# --------------------------------------------------------------------------- #
def _main(argv=None):
    p = argparse.ArgumentParser(description="fal gpt-image-1 -> Hetzner S3")
    p.add_argument("mode", choices=["t2i", "edit", "ping-s3"])
    p.add_argument("--prompt")
    p.add_argument("--ref", action="append", default=[], help="reference image URL (repeatable)")
    p.add_argument("--key", help="S3 object key")
    p.add_argument("--out", help="local copy path")
    p.add_argument("--size", default=DEFAULT_SIZE)
    p.add_argument("--quality", default=DEFAULT_QUALITY)
    args = p.parse_args(argv)

    if args.mode == "ping-s3":
        url = upload_bytes(b"ok", "shivaji/_healthcheck.txt", "text/plain")
        print("uploaded:", url)
        print("readback:", requests.get(url, timeout=30).text)
        return

    if not args.prompt or not args.key:
        p.error("--prompt and --key are required for t2i/edit")
    url = generate_and_store(
        key=args.key, prompt=args.prompt, refs=args.ref if args.mode == "edit" else None,
        size=args.size, quality=args.quality,
        local_copy=Path(args.out) if args.out else None,
    )
    print(url)


if __name__ == "__main__":
    _main()
