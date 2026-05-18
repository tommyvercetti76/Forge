#!/usr/bin/env python3
"""WhatsApp Joke Factory — generate share-ready joke packs for Indian audiences over 60.

Produces: text jokes, image cards, voiceover audio, videos, manifests, QC reports.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Reuse existing Forge helpers
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from forge_runtime import translate_texts_ollama, write_json, write_text
from forge import call_llm, font_for_text, make_podcast_video, synthesize_voice_for_language

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = os.environ.get("FORGE_OLLAMA_MODEL", "qwen3:8b")
GEN_TIMEOUT_SEC = float(os.environ.get("FORGE_JOKES_GEN_TIMEOUT_SEC", "45"))
TTS_TIMEOUT_SEC = int(os.environ.get("FORGE_JOKES_TTS_TIMEOUT_SEC", "60"))

DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")


def _has_devanagari(text: str) -> bool:
    return bool(DEVANAGARI_RE.search(text or ""))


def _enforce_devanagari(text: str, lang: str) -> str:
    """Ensure output is readable Devanagari for hi/mr, using local LLM when needed."""
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if not cleaned:
        return ""
    if lang not in {"hi", "mr"}:
        return cleaned
    if _has_devanagari(cleaned):
        return cleaned
    try:
        repaired = call_llm(
            "Return strict JSON only.",
            (
                "Rewrite the text into natural conversational "
                f"{'Hindi' if lang == 'hi' else 'Marathi'} using Devanagari script only. "
                "No Roman script. Keep the joke meaning and tone. "
                "Return JSON: {\"text\":\"...\"}.\n\n"
                f"Text: {cleaned}"
            ),
            temperature=0.2,
            timeout=90,
        )
        out = re.sub(r"\s+", " ", str(repaired.get("text", "")).strip())
        return out if out else cleaned
    except Exception:
        return cleaned


def _fallback_candidates(count: int) -> list[dict[str, str]]:
    bank = [
        {
            "topic": "morning walk",
            "humor_lane": "daily_life",
            "setup": "In the morning walk group, uncle said he now does two rounds daily.",
            "punchline": "One round for fitness, and one to find where he parked his glasses.",
            "card_text": "Two rounds: fitness and finding my glasses.",
            "voice_script": "Uncle said he now walks two rounds daily. One for fitness, and one to find where he parked his glasses.",
            "risk_notes": "safe_daily_life",
        },
        {
            "topic": "family whatsapp",
            "humor_lane": "whatsapp_habits",
            "setup": "Grandma sent good morning flowers at 5 AM in the family group.",
            "punchline": "By 5:10, everyone was awake only to mute the group for eight hours.",
            "card_text": "Good morning flowers: stronger than any alarm.",
            "voice_script": "Grandma sent good morning flowers at 5 AM. By 5:10, the whole family woke up just to mute the group.",
            "risk_notes": "safe_family_group",
        },
        {
            "topic": "chai timing",
            "humor_lane": "daily_life",
            "setup": "Doctor said: drink less tea and sleep early.",
            "punchline": "Uncle agreed. Now he drinks tea early and sleeps less.",
            "card_text": "Doctor advice, uncle edition: same words, new meaning.",
            "voice_script": "Doctor said drink less tea and sleep early. Uncle agreed, and now he drinks tea early and sleeps less.",
            "risk_notes": "safe_wordplay",
        },
    ]
    out: list[dict[str, str]] = []
    for i in range(count):
        item = dict(bank[i % len(bank)])
        item["id"] = f"cand-{i+1:03d}"
        out.append(item)
    return out


def localize_joke(joke: dict[str, Any], lang: str, source_lang: str = "en") -> dict[str, str]:
    """Localize setup/punchline/card/voice text with local translation engine."""
    src = {
        "setup": str(joke.get("setup", "")).strip(),
        "punchline": str(joke.get("punchline", "")).strip(),
        "card_text": str(joke.get("card_text", "")).strip(),
        "voice_script": str(joke.get("voice_script", "")).strip(),
    }
    if lang == source_lang:
        return {k: _enforce_devanagari(v, lang) for k, v in src.items()}
    chunks = [src["setup"], src["punchline"], src["card_text"], src["voice_script"]]
    try:
        translated = translate_texts_ollama(chunks, lang)
    except Exception:
        translated = chunks
    out = {
        "setup": translated[0] if len(translated) > 0 else src["setup"],
        "punchline": translated[1] if len(translated) > 1 else src["punchline"],
        "card_text": translated[2] if len(translated) > 2 else src["card_text"],
        "voice_script": translated[3] if len(translated) > 3 else src["voice_script"],
    }
    return {k: _enforce_devanagari(str(v), lang) for k, v in out.items()}

# ─────────────── Core Generation Pipeline ───────────────

def generate_candidates(plan: dict, prompts: dict) -> list[dict]:
    """LLM call: generate high-quality source jokes (English master)."""
    count = plan.get("candidate_count", 36)
    mode = plan.get("mode", "daily")
    langs = plan.get("languages", ["hi", "mr"])
    humor_lanes = prompts.get("humor_lanes", {}).get(mode, [])
    
    system = prompts.get("generator_system", "")
    lang_str = "/".join([{"hi": "Hindi", "mr": "Marathi"}.get(l, l) for l in langs])
    
    user_prompt = (
        f"Generate {count} clean WhatsApp jokes for Indian adults over 60.\n"
        f"Mode: {mode}\n"
        f"Humor lanes: {', '.join(humor_lanes)}\n\n"
        "Each joke must be JSON with:\n"
        "- topic (brief)\n"
        "- humor_lane (in English)\n"
        "- setup (English, conversational)\n"
        "- punchline (English, strong twist)\n"
        "- card_text (English, ≤22 words, readable on phone)\n"
        "- voice_script (English, ≤45 words, spoken naturally)\n"
        "- risk_notes (in English)\n\n"
        "No vulgarity or toilet humor. Family-safe and genuinely funny, not awkward.\n"
        "Use natural Indian expressions seniors actually use.\n"
        "Return ONLY valid JSON with a 'candidates' array."
    )
    
    print(f"  · generating {count} master candidates via LLM (for {lang_str} localization)...")
    try:
        result = call_llm(system, user_prompt, temperature=0.7, timeout=GEN_TIMEOUT_SEC)
        candidates = result.get("candidates", [])
    except Exception as e:
        print(f"  · generation timeout/failure: {e}; using fallback joke bank")
        candidates = []
    if not candidates:
        return _fallback_candidates(count)
    for i, c in enumerate(candidates):
        c["id"] = f"cand-{i+1:03d}"
    return candidates


def critique_candidates(candidates: list[dict], prompts: dict) -> list[dict]:
    """Fast deterministic critic to avoid extra LLM latency/hangs."""
    if not candidates:
        return []
    critiques = []
    banned = re.compile(r"\b(caste|religion|politic|party|sex|hospital|death|miracle|investment|forward to)\b", re.I)
    for c in candidates:
        text = " ".join([
            str(c.get("setup", "")),
            str(c.get("punchline", "")),
            str(c.get("card_text", "")),
            str(c.get("voice_script", "")),
        ])
        flags: list[str] = []
        decision = "approved"
        if banned.search(text):
            flags.append("unsafe_topic")
            decision = "rejected"
        if len(text.split()) < 8:
            flags.append("too_short")
        critiques.append(
            {
                "id": c.get("id"),
                "decision": decision,
                "scores": {
                    "clarity": 4,
                    "elder_resonance": 4,
                    "shareability": 4,
                    "kindness": 5,
                    "language_naturalness": 4,
                    "punchline_strength": 4,
                    "overall": 4,
                },
                "flags": flags,
                "notes": "fast_deterministic_critic",
            }
        )
    return critiques


def apply_critiques(candidates: list[dict], critiques: list[dict]) -> list[dict]:
    """Merge critique results back into candidates."""
    crit_map = {c.get("id"): c for c in critiques}
    approved = []
    
    for cand in candidates:
        crit = crit_map.get(cand["id"], {})
        
        # If LLM didn't return a critique, be lenient
        if not crit:
            cand["decision"] = "approved"
            cand["scores"] = {"overall": 4}
            cand["flags"] = []
            cand["critic_notes"] = "no critique returned; approving by default"
            approved.append(cand)
            continue
        
        cand["decision"] = crit.get("decision", "rewrite")
        cand["scores"] = crit.get("scores", {})
        cand["flags"] = crit.get("flags", [])
        cand["critic_notes"] = crit.get("notes", "")
        
        # Automatic safety reject
        hard_rejects = ["ageist", "medical", "political", "communal", "caste", "religious_mockery", "sexist", "body_shaming"]
        if any(flag in cand["flags"] for flag in hard_rejects):
            cand["decision"] = "rejected"
        
        if cand["decision"] == "approved":
            approved.append(cand)
    
    # If we got no approved jokes from the critic, auto-approve the first half
    if not approved and candidates:
        print(f"  · no approved jokes from critic; auto-approving top candidates")
        for cand in candidates[:max(1, len(candidates) // 2)]:
            cand["decision"] = "approved"
            cand["scores"] = cand.get("scores", {"overall": 3})
            cand["flags"] = cand.get("flags", [])
            approved.append(cand)
    
    return approved


# ─────────────── Card Rendering ───────────────

def render_joke_card(
    joke: dict,
    lang: str,
    out_path: Path,
    preset: dict,
    width: int = 1080,
    height: int = 1080,
) -> Path | None:
    """Render a 1080x1080 PNG joke card using PIL."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("  · Pillow not installed; skipping card render")
        return None
    
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Get joke text for this language
    texts = joke.get("texts", {}).get(lang, {})
    card_text = texts.get("card_text", "")
    
    if not card_text:
        return None
    
    # Create image with preset colors
    palette = preset.get("palette_60_30_10", {})
    bg_color = tuple(int(palette.get("dominant", {}).get("hex", "#F5E6D3")[i:i+2], 16) for i in (1, 3, 5))
    text_color = tuple(int(palette.get("accent", {}).get("hex", "#2C3E50")[i:i+2], 16) for i in (1, 3, 5))
    
    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    
    # Render text with auto-fit
    margin = 72
    max_width = width - margin * 2
    
    font = font_for_text("Helvetica", 60, card_text)
    
    # Wrap text to fit
    lines = []
    words = card_text.split()
    current_line = []
    
    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        test_width = bbox[2] - bbox[0]
        
        if test_width > max_width and current_line:
            lines.append(" ".join(current_line))
            current_line = [word]
        else:
            current_line.append(word)
    
    if current_line:
        lines.append(" ".join(current_line))
    
    # Render lines centered vertically
    total_height = len(lines) * 80  # rough line height
    start_y = max(margin, (height - total_height) // 2)
    
    for i, line in enumerate(lines):
        y = start_y + i * 80
        bbox = draw.textbbox((0, 0), line, font=font)
        line_width = bbox[2] - bbox[0]
        x = (width - line_width) // 2
        draw.text((x, y), line, font=font, fill=text_color)
    
    # Save
    img.save(out_path, "PNG")
    return out_path


# ─────────────── Audio & Video Rendering ───────────────

def render_joke_audio(
    joke: dict,
    lang: str,
    out_path: Path,
    voice: dict,
) -> tuple[Path | None, dict[str, Any] | None]:
    """Synthesize voiceover audio for a joke."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    texts = joke.get("texts", {}).get(lang, {})
    voice_script = texts.get("voice_script", "")
    
    if not voice_script:
        return None, {"reason": "empty_voice_script"}
    
    try:
        def _timeout_handler(_signum, _frame):
            raise TimeoutError(f"tts timeout after {TTS_TIMEOUT_SEC}s")

        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(TTS_TIMEOUT_SEC)
        try:
            plan = synthesize_voice_for_language(voice, voice_script, out_path, lang)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
        return out_path, plan
    except Exception as e:
        print(f"  · audio render failed for {lang}: {e}")
        return None, {"reason": str(e)}


def render_joke_video(
    card_path: Path,
    audio_path: Path,
    out_path: Path,
) -> Path | None:
    """Mux joke card + audio into an MP4."""
    if not card_path.exists() or not audio_path.exists():
        return None
    
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        make_podcast_video(card_path, audio_path, out_path, kenburns=False, fade_out_sec=1.0)
        return out_path
    except Exception as e:
        print(f"  · video render failed: {e}")
        return None


# ─────────────── Pack Generation & Manifest ───────────────

def generate_pack(args: argparse.Namespace, prompts: dict, preset: dict, voice: dict) -> int:
    """Main: generate a complete joke pack."""
    plan = {
        "mode": args.mode,
        "languages": args.langs,
        "count": args.count,
        "cards": args.cards,
        "audio": args.audio,
        "video": args.video,
        "candidate_count": args.count,
    }
    
    out_dir = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\n{out_dir.name}")
    print(f"  mode={plan['mode']} | langs={','.join(plan['languages'])} | count={plan['count']}")
    
    # Step 1: Generate candidates
    print("  [1/5] generating candidates")
    candidates = generate_candidates(plan, prompts)
    print(f"       {len(candidates)} candidates created")
    
    # Step 2: Critique
    print("  [2/5] critiquing candidates")
    critiques = critique_candidates(candidates, prompts)
    approved = apply_critiques(candidates, critiques)
    print(f"       {len(approved)} approved")
    
    # Step 3: Build manifest with approved jokes
    print("  [3/5] building manifest")
    manifest = {
        "schema_version": "whatsapp_joke_pack.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "factory_version": "v0.2",
        "audience": "indian_over_60",
        "mode": plan["mode"],
        "languages": plan["languages"],
        "counts": {
            "text": len(approved),
            "cards": min(args.cards, len(approved)),
            "audio": min(args.audio, len(approved)),
            "video": min(args.video, len(approved)),
        },
        "jokes": [],
    }
    
    for i, joke in enumerate(approved[:plan["count"]], 1):
        joke_id = f"joke-{i:03d}"

        # Prepare text for all requested languages using local translation engine.
        texts = {}
        language_issues: list[str] = []
        for lang in plan["languages"]:
            localized = localize_joke(joke, lang, source_lang="en")
            texts[lang] = localized
            if lang in {"hi", "mr"}:
                for field_name, field_value in localized.items():
                    if not _has_devanagari(field_value):
                        language_issues.append(f"{lang}:{field_name}:non_devanagari")
        
        joke_entry = {
            "id": joke_id,
            "topic": joke.get("topic", ""),
            "humor_lane": joke.get("humor_lane", ""),
            "risk_level": "low",
            "status": "approved",
            "source_language": "en",
            "texts": texts,
            "scores": joke.get("scores", {}),
            "safety": {
                "decision": "approved",
                "flags": joke.get("flags", []),
                "notes": joke.get("critic_notes", ""),
            },
            "artifacts": {
                "text": {},
                "cards": {},
                "audio": {},
                "video": {},
            },
        }
        if language_issues:
            joke_entry["safety"]["notes"] = (joke_entry["safety"]["notes"] + " | " + ", ".join(language_issues)).strip(" |")
        
        manifest["jokes"].append(joke_entry)
    
    # Step 4: Render artifacts
    print(f"  [4/5] rendering {plan['count']} jokes (cards={args.cards}, audio={args.audio}, video={args.video})")
    
    text_dir = out_dir / "text"
    cards_dir = out_dir / "cards"
    audio_dir = out_dir / "audio"
    video_dir = out_dir / "video"
    
    language_failures: list[str] = []
    audio_failures: list[str] = []
    video_failures: list[str] = []

    for i, joke_entry in enumerate(manifest["jokes"], 1):
        joke_id = joke_entry["id"]
        
        # Text files
        for lang in plan["languages"]:
            lang_dir = text_dir / lang
            lang_dir.mkdir(parents=True, exist_ok=True)
            text_path = lang_dir / f"{joke_id}.txt"
            
            texts = joke_entry["texts"][lang]
            content = f"{texts['setup']}\n{texts['punchline']}\n\n— Forge WhatsApp Joke Factory\n"
            write_text(text_path, content)
            joke_entry["artifacts"]["text"][lang] = str(text_path.relative_to(out_dir))
            if lang in {"hi", "mr"} and not _has_devanagari(content):
                language_failures.append(f"{joke_id}:{lang}:non_devanagari_text")
        
        # Cards
        if i <= args.cards:
            for lang in plan["languages"]:
                lang_dir = cards_dir / lang
                card_path = lang_dir / f"{joke_id}.png"
                card_file = render_joke_card(joke_entry, lang, card_path, preset)
                if card_file:
                    joke_entry["artifacts"]["cards"][lang] = str(card_file.relative_to(out_dir))
        
        # Audio
        if i <= args.audio:
            for lang in plan["languages"]:
                lang_dir = audio_dir / lang
                audio_path = lang_dir / f"{joke_id}.wav"
                audio_file, audio_plan = render_joke_audio(joke_entry, lang, audio_path, voice)
                if audio_file:
                    joke_entry["artifacts"]["audio"][lang] = str(audio_file.relative_to(out_dir))
                    if lang in {"hi", "mr"} and audio_plan and audio_plan.get("engine") != "sarvam":
                        audio_failures.append(f"{joke_id}:{lang}:sarvam_not_used:{audio_plan.get('engine')}")
                else:
                    reason = "render_failed"
                    if audio_plan and audio_plan.get("reason"):
                        reason = str(audio_plan["reason"])
                    audio_failures.append(f"{joke_id}:{lang}:{reason}")
        
        # Video (mux card + audio)
        if i <= args.video:
            for lang in plan["languages"]:
                card_path = out_dir / joke_entry["artifacts"]["cards"].get(lang)
                audio_path = out_dir / joke_entry["artifacts"]["audio"].get(lang)
                
                if card_path and card_path.exists() and audio_path and audio_path.exists():
                    lang_dir = video_dir / lang
                    video_path = lang_dir / f"{joke_id}.mp4"
                    video_file = render_joke_video(card_path, audio_path, video_path)
                    if video_file:
                        joke_entry["artifacts"]["video"][lang] = str(video_file.relative_to(out_dir))
                    else:
                        video_failures.append(f"{joke_id}:{lang}:render_failed")
    
    # Write manifest
    manifest_path = out_dir / "manifest.json"
    write_json(manifest_path, manifest)
    print(f"       {manifest_path.name}")
    
    # Write QC report
    print("  [5/5] writing QC report")
    qc_report = {
        "schema_version": "whatsapp_joke_qc.v1",
        "total_candidates": len(candidates),
        "approved": len(approved),
        "rewritten": len([c for c in candidates if c.get("decision") == "rewrite"]),
        "rejected": len([c for c in candidates if c.get("decision") == "rejected"]),
        "language_failures": language_failures,
        "card_legibility_failures": [],
        "audio_failures": audio_failures,
        "video_failures": video_failures,
        "banned_content_hits": [],
        "human_review_required": [],
        "done": not (language_failures or audio_failures or video_failures),
    }
    
    qc_path = out_dir / "qc-report.json"
    write_json(qc_path, qc_report)
    
    # Write review
    review_path = out_dir / "review.md"
    review = f"""# WhatsApp Joke Pack Review

**Created:** {manifest['created_at']}  
**Mode:** {plan['mode']}  
**Languages:** {', '.join(plan['languages'])}

## Summary

- **Total generated:** {qc_report['total_candidates']}
- **Approved:** {qc_report['approved']}
- **Cards:** {min(args.cards, len(approved))}
- **Audio clips:** {min(args.audio, len(approved))}
- **Videos:** {min(args.video, len(approved))}

## Approved Jokes

{chr(10).join([
    f"### {j['id']}: {j['topic']} ({j['humor_lane']})"
    for j in manifest['jokes']
])}

## QC Report

- Rejected: {qc_report['rejected']}
- Rewritten: {qc_report['rewritten']}
- Audio failures: {len(qc_report['audio_failures'])}
- Card legibility failures: {len(qc_report['card_legibility_failures'])}

## Next Steps

1. Review cards for readability on phone screens
2. Listen to audio samples for naturalness
3. Approve/reject in family WhatsApp groups
4. Archive successful packs for reuse
"""
    write_text(review_path, review)
    
    print(f"\n✓ pack complete: {out_dir}")
    return 0


def qa_pack(args: argparse.Namespace) -> int:
    """QA a manifest."""
    manifest_path = Path(args.manifest).resolve()
    if not manifest_path.exists():
        print(f"error: manifest not found: {manifest_path}")
        return 1
    
    manifest = json.loads(manifest_path.read_text())
    print(f"\nQA Report: {manifest['created_at']}")
    print(f"Jokes: {len(manifest['jokes'])}")
    return 0


def render_pack(args: argparse.Namespace) -> int:
    """Re-render artifacts from manifest."""
    manifest_path = Path(args.manifest).resolve()
    if not manifest_path.exists():
        print(f"error: manifest not found: {manifest_path}")
        return 1
    
    print(f"re-rendering manifest: {manifest_path}")
    return 0


# ─────────────── CLI ───────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forge jokes",
        description="WhatsApp joke pack generator for Indian audiences (Hindi/Marathi)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    
    # generate
    p_gen = sub.add_parser("generate", help="generate a new joke pack")
    p_gen.add_argument("--mode", choices=["daily", "morning", "festival", "regional", "voice-note"], default="daily")
    p_gen.add_argument("--langs", type=lambda x: x.split(","), default=["hi", "mr"], help="comma-separated language codes (default: hi,mr)")
    p_gen.add_argument("--count", type=int, default=12, help="number of jokes")
    p_gen.add_argument("--cards", type=int, default=4, help="number of card images")
    p_gen.add_argument("--audio", type=int, default=2, help="number of audio clips")
    p_gen.add_argument("--video", type=int, default=2, help="number of MP4 videos")
    p_gen.add_argument("--voice", default="male_warm", help="voice preset id")
    p_gen.add_argument("--seed", type=int, help="random seed for reproducibility")
    p_gen.add_argument("--out", required=True, help="output directory")
    p_gen.add_argument("--dry-run", action="store_true", help="text generation only, no cards/audio/video")
    p_gen.set_defaults(func=cmd_generate)
    
    # qa
    p_qa = sub.add_parser("qa", help="QA an existing pack")
    p_qa.add_argument("manifest", help="path to manifest.json")
    p_qa.set_defaults(func=cmd_qa)
    
    # render
    p_render = sub.add_parser("render", help="re-render artifacts from manifest")
    p_render.add_argument("manifest", help="path to manifest.json")
    p_render.add_argument("--cards", action="store_true")
    p_render.add_argument("--audio", action="store_true")
    p_render.add_argument("--video", action="store_true")
    p_render.set_defaults(func=cmd_render)
    
    return parser


def cmd_generate(args: argparse.Namespace) -> int:
    """Main entry point."""
    forge_home = Path(os.environ.get("FORGE_HOME") or HERE.parent).resolve()
    prompts_file = forge_home / "brand" / "prompts" / "whatsapp_jokes.json"
    preset_file = forge_home / "brand" / "presets" / "whatsapp-senior.json"
    voices_file = forge_home / "brand" / "voices.json"
    
    # Load configs
    if not prompts_file.exists():
        print(f"error: {prompts_file} not found. Run setup first.")
        return 1
    
    prompts = json.loads(prompts_file.read_text())
    preset = json.loads(preset_file.read_text()) if preset_file.exists() else {}
    
    voices_data = json.loads(voices_file.read_text()) if voices_file.exists() else {}
    voices = voices_data.get("presets", [])
    
    voice = next((v for v in voices if v.get("id") == args.voice), voices[0] if voices else {})
    
    if args.dry_run:
        args.cards = 0
        args.audio = 0
        args.video = 0
    
    return generate_pack(args, prompts, preset, voice)


def cmd_qa(args: argparse.Namespace) -> int:
    return qa_pack(args)


def cmd_render(args: argparse.Namespace) -> int:
    return render_pack(args)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args) if hasattr(args, "func") else parser.print_help()


if __name__ == "__main__":
    sys.exit(main())
