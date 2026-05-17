#!/usr/bin/env python3
"""make-thumbnail.py — local YouTube thumbnail generation.

Pipeline:
  1. mflux (FLUX.1-schnell on MLX) generates a 1280×720 background image
     from a text prompt. ~4 seconds per image on M-series.
  2. PIL overlays your headline text + optional subtext with high-contrast
     drop-shadow + brand color band.
  3. Saves to <output_dir>/<slug>.png at YouTube's required 1280×720 16:9.

Usage:
  python3 make-thumbnail.py \\
    --prompt "epic mountain sunset, cinematic light, vast wilderness" \\
    --text "WHY I QUIT MY JOB" \\
    --sub "and what I'm building next" \\
    --out ./thumbnails

Optional brainstorming with local Ollama (uses qwen3:8b by default):
  python3 make-thumbnail.py \\
    --topic "I built a desktop ML system in one weekend" \\
    --brainstorm \\
    --out ./thumbnails

Install once:
  uv tool install --with mflux mflux
  pip install pillow --break-system-packages
  (optional) brew-free Ollama: download from ollama.com, `ollama pull qwen3:8b`
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

THUMB_WIDTH = 1280
THUMB_HEIGHT = 720


def slugify(text: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return out[:60] or "thumb"


def generate_background(prompt: str, out_path: Path, steps: int = 4, seed: Optional[int] = None) -> None:
    """Call mflux to make a 1280×720 image from a prompt."""
    cmd = [
        "mflux-generate",
        "--model", "schnell",
        "--prompt", prompt,
        "--width", str(THUMB_WIDTH),
        "--height", str(THUMB_HEIGHT),
        "--steps", str(steps),
        "--guidance", "0.0",  # schnell uses 0 guidance
        "--output", str(out_path),
    ]
    if seed is not None:
        cmd.extend(["--seed", str(seed)])
    print(f"[mflux] {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def brainstorm_with_ollama(topic: str, n: int = 3, model: str = "qwen3:8b") -> list[dict]:
    """Ask local Ollama for catchy thumbnail text variants. Returns list of dicts."""
    system = (
        "You write YouTube thumbnail text. Return ONLY a JSON array of "
        f"{n} objects, each with keys 'headline' (3-6 words, ALL CAPS, "
        "hook-driven) and 'sub' (≤8 words, lowercase, intriguing). No prose."
    )
    payload = json.dumps({
        "model": model,
        "prompt": f"Topic: {topic}\nReturn JSON now.",
        "system": system,
        "stream": False,
        "options": {"temperature": 0.8},
    })
    try:
        r = subprocess.run(
            ["curl", "-s", "http://localhost:11434/api/generate", "-d", payload],
            capture_output=True, text=True, check=True, timeout=120,
        )
        raw = json.loads(r.stdout).get("response", "")
        # Extract first JSON array in response
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        return json.loads(m.group(0)) if m else []
    except Exception as e:
        print(f"[brainstorm] Ollama call failed: {e}", file=sys.stderr)
        return []


def overlay_text(
    bg_path: Path,
    out_path: Path,
    headline: str,
    sub: Optional[str] = None,
    accent: str = "#d4a937",  # admin's gold
) -> None:
    """Add high-contrast text overlay. Uses PIL with system fonts."""
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
    except ImportError:
        print("Need Pillow: pip install pillow --break-system-packages", file=sys.stderr)
        sys.exit(1)

    img = Image.open(bg_path).convert("RGBA")
    # Dim the bottom third for text contrast
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle([0, int(img.height * 0.55), img.width, img.height], fill=(0, 0, 0, 160))
    img = Image.alpha_composite(img, overlay)

    # System fonts (no install needed on macOS)
    def font(name: str, size: int):
        for path in (
            f"/System/Library/Fonts/Supplemental/{name}",
            f"/System/Library/Fonts/{name}",
        ):
            if Path(path).exists():
                return ImageFont.truetype(path, size)
        return ImageFont.load_default()

    headline_font = font("Impact.ttf", 110)
    sub_font = font("Helvetica.ttc", 38)

    draw = ImageDraw.Draw(img)

    # Headline with drop shadow
    hl_y = int(img.height * 0.62)
    for dx, dy in [(4, 4), (-4, 4), (4, -4), (-4, -4)]:  # outline
        draw.text((40 + dx, hl_y + dy), headline, font=headline_font, fill=(0, 0, 0, 255))
    draw.text((40, hl_y), headline, font=headline_font, fill=(255, 255, 255, 255))

    # Accent bar under headline
    bar_y = hl_y + 130
    draw.rectangle([40, bar_y, 280, bar_y + 8], fill=accent)

    # Subtext
    if sub:
        draw.text((40, bar_y + 22), sub, font=sub_font, fill=(255, 255, 255, 220))

    img.convert("RGB").save(out_path, "PNG", optimize=True)
    print(f"[done] {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Local YouTube thumbnail generator")
    ap.add_argument("--prompt", help="Image prompt for FLUX")
    ap.add_argument("--text", help="Headline text (3–6 words, will be UPPERCASED)")
    ap.add_argument("--sub", help="Optional subtext (1 line)")
    ap.add_argument("--topic", help="Video topic — used with --brainstorm")
    ap.add_argument("--brainstorm", action="store_true", help="Use local Ollama to suggest text + prompt")
    ap.add_argument("--out", default="./thumbnails", help="Output directory")
    ap.add_argument("--steps", type=int, default=4, help="FLUX steps (schnell=4)")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--accent", default="#d4a937", help="Accent bar hex color")
    args = ap.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.brainstorm:
        if not args.topic:
            ap.error("--brainstorm requires --topic")
        ideas = brainstorm_with_ollama(args.topic, n=3)
        if not ideas:
            print("Brainstorm produced no ideas. Falling back to --topic as prompt+headline.")
            ideas = [{"headline": args.topic.upper()[:60], "sub": ""}]
        for i, idea in enumerate(ideas, 1):
            print(f"  [{i}] {idea.get('headline')!r} / {idea.get('sub')!r}")
        chosen = ideas[0]
        headline = chosen.get("headline", "").upper()
        sub = chosen.get("sub", "")
        prompt = args.prompt or f"cinematic 16:9 thumbnail background for video about: {args.topic}, dramatic lighting, high contrast, no text"
    else:
        if not args.prompt or not args.text:
            ap.error("either --brainstorm --topic, or both --prompt and --text are required")
        prompt = args.prompt
        headline = args.text.upper()
        sub = args.sub or ""

    slug = slugify(headline or "thumb")
    bg = out_dir / f"{slug}-bg.png"
    final = out_dir / f"{slug}.png"

    generate_background(prompt, bg, steps=args.steps, seed=args.seed)
    overlay_text(bg, final, headline, sub, accent=args.accent)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"[error] subprocess failed: {e}", file=sys.stderr)
        sys.exit(e.returncode)
    except KeyboardInterrupt:
        print("\n[interrupted]", file=sys.stderr)
        sys.exit(130)

# Once you've used it a few times, common patterns:
#
#   # Single-shot with explicit prompt + text:
#   python3 make-thumbnail.py \
#     --prompt "mountain peak at golden hour, dramatic clouds, cinematic" \
#     --text "I CLIMBED THIS" --sub "and almost didn't come back" \
#     --out ./thumbnails
#
#   # Brainstorm headlines from a topic:
#   python3 make-thumbnail.py --brainstorm \
#     --topic "I built a paddle safety ML system in a weekend" \
#     --out ./thumbnails
#
#   # Variations of the same composition with different seeds:
#   for s in 1 2 3 4 5; do
#     python3 make-thumbnail.py --prompt "..." --text "..." --seed $s --out ./thumbnails
#   done
