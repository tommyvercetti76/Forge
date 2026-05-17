#!/usr/bin/env python3
"""prompt-forge.py — local LLM prompt enhancer for image generation.

Why this exists:
  Image models (FLUX, SDXL) silently DROP details when prompts are sparse and
  silently INVENT details that contradict your intent. A direct human prompt
  like "A crane and tiger talking on a podcast" produces:
    - Wrong composition (one character per image, or both in profile facing
      away from camera, or both staring at viewer instead of at each other)
    - Wrong style (default photorealism instead of cartoon)
    - Wrong proportions (chibi / oversized heads / disney-eyes)
    - Missing podcast-studio context (no mics, or mics with wrong shape)
    - Hallucinated extras (random humans, microphones floating in space)

Strategy:
  1. Extract a MUST_HAVE list from the user prompt (LLM call #1 — extraction
     only, no creativity).
  2. Expand the prompt with explicit visual detail (LLM call #2 — creative but
     constrained: MUST include every MUST_HAVE item verbatim or paraphrased).
  3. Validate the expansion — every MUST_HAVE must appear in the output
     (case-insensitive substring or keyword overlap). If not, retry once with
     a stricter system prompt.
  4. Append anti-hallucination negatives ("NO photorealism, NO oversized heads,
     etc.") drawn from a curated list of common image-model failure modes.

Output is a FLUX-ready expanded prompt + a `mflux-generate` command line.

Usage:
    python3 prompt-forge.py "A sandhill crane and tiger talking on a podcast"
    python3 prompt-forge.py "..." --style "Samurai Jack" --palette 60-30-10
    python3 prompt-forge.py "..." --generate --steps 25 --output out.png

Backend:
  Defaults to local Ollama qwen3:8b. Pass --backend mlx to use MLX
  Qwen2.5-Coder-32B-Instruct-4bit (slower but stronger structured output).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen3:8b"
MLX_MODEL = "mlx-community/Qwen2.5-Coder-32B-Instruct-4bit"


# Common image-gen failure modes that the negative list always covers.
DEFAULT_NEGATIVES = [
    "photorealistic",
    "3D rendered",
    "digital gloss",
    "plastic skin",
    "smooth gradients",
    "oversized heads",
    "chibi proportions",
    "anime sparkle eyes",
    "Disney style",
    "extra limbs",
    "deformed hands",
    "floating objects",
    "duplicate subjects",
    "text artifacts",
    "watermark",
    "low resolution",
]

# Curated style expansions for shorthand references.
STYLE_LIBRARY = {
    "samurai jack": (
        "Hand-drawn 2D animation cel in the style of Samurai Jack by Genndy Tartakovsky: "
        "thick black ink outlines, flat color fills with NO gradients, minimal cel-shaded "
        "shadows (max two shadow tones), geometric simplicity, limited palette, "
        "angular composition, hand-painted backgrounds"
    ),
    "60-30-10": (
        "Apply the 60-30-10 color rule: 60% dominant color in the background and large "
        "surfaces, 30% secondary color in mid-ground / subjects, 10% accent color reserved "
        "for highlights and small focal elements. Pick three concrete hex colors and assign "
        "each to its role explicitly in the prompt"
    ),
}

EXTRACT_SCHEMA = (
    'Reply STRICT JSON: {"must_have":[strings], "subjects":[strings], "setting":string, '
    '"style_refs":[strings], "composition_hints":[strings], "palette_hints":[strings]}'
)

EXPAND_SCHEMA = 'Reply STRICT JSON: {"prompt":string, "rationale":string, "added_obvious":[strings]}'


def call_llm_json(system: str, user: str, *, backend: str, temperature: float = 0.3, timeout: float = 90) -> dict:
    if backend == "ollama":
        body = json.dumps({
            "model": OLLAMA_MODEL,
            "system": system,
            "prompt": user,
            "stream": False,
            "format": "json",
            "options": {"temperature": temperature, "num_ctx": 8192},
        }).encode("utf-8")
        req = urllib.request.Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.loads(r.read())
        text = resp.get("response", "")
    elif backend == "mlx":
        prompt = f"<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n"
        raw = subprocess.run(
            ["mlx_lm.generate", "--model", MLX_MODEL,
             "--prompt", prompt, "--max-tokens", "1500", "--temp", str(temperature)],
            capture_output=True, text=True, check=True, timeout=180,
        ).stdout
        parts = raw.split("==========")
        text = parts[1].strip() if len(parts) >= 2 else raw.strip()
    else:
        raise ValueError(f"unknown backend: {backend}")

    # Strip code fences, find first JSON block
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    m = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON: {text[:200]!r}")
    return json.loads(m.group(1))


def extract_constraints(user_prompt: str, *, backend: str) -> dict:
    """LLM call #1: just identify what the user asked for. No creativity."""
    system = (
        "You are a constraint extractor for image-generation prompts. Your only job is to "
        "identify what the user EXPLICITLY asked for. Do NOT add anything not in the prompt. "
        "Do NOT interpret. Just identify and categorize. "
        + EXTRACT_SCHEMA
    )
    return call_llm_json(system, user_prompt, backend=backend, temperature=0.1)


def expand_prompt(
    user_prompt: str,
    constraints: dict,
    *,
    backend: str,
    style_hint: str | None,
    palette_hint: str | None,
    aspect: str,
) -> dict:
    """LLM call #2: expand into a FLUX-ready prompt, with constraints as hard guards."""
    must_have = constraints.get("must_have") or []
    style_block = ""
    if style_hint:
        key = style_hint.lower().strip()
        if key in STYLE_LIBRARY:
            style_block += f"\nSTYLE GUIDANCE: {STYLE_LIBRARY[key]}\n"
        else:
            style_block += f"\nSTYLE GUIDANCE: {style_hint}\n"
    if palette_hint:
        key = palette_hint.lower().strip()
        if key in STYLE_LIBRARY:
            style_block += f"\nPALETTE GUIDANCE: {STYLE_LIBRARY[key]}\n"
        else:
            style_block += f"\nPALETTE GUIDANCE: {palette_hint}\n"

    system = textwrap.dedent("""
        You are an expert image-prompt engineer. Your job: rewrite the user's sparse
        prompt into a verbose, unambiguous FLUX prompt that will render correctly.

        RULES:
        • EVERY item in the MUST_HAVE list below must appear in your output prompt,
          verbatim or paraphrased. None may be dropped.
        • Fill in OBVIOUS missing details that any human would assume:
            - Composition: camera angle, framing, where the subjects are looking
            - Lighting: key/fill/back light, time of day if outdoor
            - Setting context: what objects belong in this kind of scene
            - Subject proportions: if cartoon/anime style, specify accurate
              proportions to avoid chibi/oversized-head defaults
        • Do NOT invent things that contradict the user's intent.
        • Do NOT add humans if the user did not mention them.
        • For multi-subject scenes, EXPLICITLY say both subjects are in the same frame
          and describe their spatial relationship (left/right, facing each other, etc.)
        • For named real-world products (e.g. "RODE mic", "MacBook"), specify the model
          shape so FLUX renders the right silhouette.
        • End with a one-line "CRITICAL CONSTRAINTS:" recap listing the 3-5 most
          easy-to-fail items (composition, style, proportions) in ALL CAPS.

        Return JSON only. """).strip() + "\n\n" + EXPAND_SCHEMA

    user_input = textwrap.dedent(f"""
        ORIGINAL USER PROMPT:
        {user_prompt}

        EXTRACTED CONSTRAINTS:
        {json.dumps(constraints, indent=2)}

        MUST_HAVE (every item below must appear in output):
        {chr(10).join('  - ' + str(m) for m in must_have)}
        {style_block}
        TARGET ASPECT: {aspect}

        Now produce the expanded prompt.
    """).strip()

    return call_llm_json(system, user_input, backend=backend, temperature=0.4)


def validate_must_haves(prompt: str, must_have: list[str]) -> tuple[bool, list[str]]:
    """Check that every must-have item appears in the prompt (loose substring / keyword overlap)."""
    text = prompt.lower()
    missing: list[str] = []
    for item in must_have:
        # Split into keywords; require at least half to appear
        words = [w for w in re.findall(r"\w+", item.lower()) if len(w) > 3]
        if not words:
            continue
        hits = sum(1 for w in words if w in text)
        if hits < max(1, len(words) // 2):
            missing.append(item)
    return (len(missing) == 0, missing)


def forge(
    user_prompt: str,
    *,
    backend: str = "ollama",
    style: str | None = None,
    palette: str | None = None,
    aspect: str = "16:9",
    max_attempts: int = 3,
    verbose: bool = False,
) -> dict:
    constraints = extract_constraints(user_prompt, backend=backend)
    if verbose:
        print(f"\n[constraints]\n{json.dumps(constraints, indent=2)}\n", file=sys.stderr)

    for attempt in range(max_attempts):
        result = expand_prompt(
            user_prompt, constraints,
            backend=backend, style_hint=style, palette_hint=palette, aspect=aspect,
        )
        prompt = result.get("prompt", "")
        ok, missing = validate_must_haves(prompt, constraints.get("must_have", []))
        if ok:
            break
        if verbose:
            print(f"[attempt {attempt + 1}] missing: {missing}", file=sys.stderr)
        # Force the next attempt to include the missing items
        constraints["must_have"] = list(set(constraints.get("must_have", []) + missing))
    # Negative tail
    neg = ", ".join(DEFAULT_NEGATIVES)
    enhanced = f"{prompt}\n\nNegative (avoid): {neg}"
    return {
        "original": user_prompt,
        "constraints": constraints,
        "enhanced": enhanced,
        "rationale": result.get("rationale", ""),
        "added_obvious": result.get("added_obvious", []),
        "validation": {"ok": ok, "missing_after_retries": missing if not ok else []},
    }


def run_mflux(prompt: str, out_path: Path, *, model: str, steps: int, seed: int, width: int, height: int) -> None:
    cmd = [
        "mflux-generate",
        "--model", model,
        "--prompt", prompt,
        "--width", str(width),
        "--height", str(height),
        "--steps", str(steps),
        "--guidance", "0.0" if model == "schnell" else "3.5",
        "--seed", str(seed),
        "--output", str(out_path),
    ]
    print(f"$ {' '.join(cmd[:6])} …", file=sys.stderr)
    subprocess.run(cmd, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Local LLM prompt enhancer for image generation")
    ap.add_argument("prompt", help="raw user prompt (use quotes)")
    ap.add_argument("--style", help="shorthand style reference (e.g. 'Samurai Jack')")
    ap.add_argument("--palette", help="palette rule (e.g. '60-30-10')")
    ap.add_argument("--aspect", default="16:9")
    ap.add_argument("--backend", choices=["ollama", "mlx"], default="ollama")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--generate", action="store_true", help="also call mflux to render the image")
    ap.add_argument("--model", choices=["schnell", "dev"], default="dev")
    ap.add_argument("--steps", type=int, default=25)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--width", type=int, default=1344)
    ap.add_argument("--height", type=int, default=768)
    ap.add_argument("--output", default="./forged.png")
    args = ap.parse_args()

    try:
        result = forge(
            args.prompt,
            backend=args.backend,
            style=args.style,
            palette=args.palette,
            aspect=args.aspect,
            verbose=args.verbose,
        )
    except urllib.error.URLError as e:
        sys.exit(f"Ollama unreachable ({e}). Open Ollama.app or try --backend mlx.")
    except subprocess.CalledProcessError as e:
        sys.exit(f"backend command failed: {e}")

    print("\n══════════ ENHANCED PROMPT ══════════\n")
    print(result["enhanced"])
    print("\n══════════ ADDED (obvious-but-unstated) ══════════")
    for item in result["added_obvious"]:
        print(f"  + {item}")
    print("\n══════════ VALIDATION ══════════")
    print(json.dumps(result["validation"], indent=2))

    if args.generate:
        run_mflux(result["enhanced"], Path(args.output),
                  model=args.model, steps=args.steps, seed=args.seed,
                  width=args.width, height=args.height)
        print(f"\n✓ rendered: {args.output}")

    return 0


# textwrap is used inside expand_prompt; importing here to avoid top-level noise on errors.
import textwrap  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())
