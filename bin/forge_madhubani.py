#!/usr/bin/env python3
"""forge_madhubani — the Madhubani tee catalog driver.

The catalog plan lives at docs/catalog/CATALOG_PLAN.md. The workflow
(render → review → retry-once → master/flag) is at docs/catalog/WORKFLOW.md.
The 12 distilled principles are at
generated/madhubani_animals/_learning/PRINCIPLES.md.

This script is the deterministic interface to the catalog. It reads the
machine-readable schemas under brand/madhubani/, builds correct engine
configs, and routes to `forge engine render minimalist-tshirt` so all
the engine rules (COLOR FLOOR / ANATOMY FIRST / NO SIGNATURE /
SEVEN ZONES / etc.) fire automatically. No prompt-writing by hand.

Commands
--------
  forge_madhubani list animals
  forge_madhubani list poses
  forge_madhubani show <animal_slug>

  forge_madhubani render <animal_slug> [pose_slug] [--retry] [--register R]
  forge_madhubani render <animal_slug> --all-poses [--register R]

  forge_madhubani promote <animal_slug> <pose_slug> [--from-version v1]
  forge_madhubani flag    <animal_slug> <pose_slug> --notes "..."
  forge_madhubani card    <animal_slug>

  forge_madhubani chat "<natural-language request>"

Run with no args for usage. Every command is offline; nothing leaves
your machine.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from madhubani_qc import score_madhubani_png
import engine_qc

# --- Paths ---------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent          # Forge/
SCHEMA_DIR = ROOT / "brand" / "madhubani"
GEN_DIR = ROOT / "generated" / "madhubani_animals"
ATTEMPTS_DIR = GEN_DIR / "attempts"
MASTERED_DIR = GEN_DIR / "mastered"
FLAGGED_DIR = GEN_DIR / "flagged"
DOCS_DIR = ROOT / "docs" / "catalog"
LEARNING_DIR = GEN_DIR / "_learning"

FORGE_BIN = ROOT / "bin" / "forge.py"
CLI_DISPLAY = "bin/forge_madhubani.py"

# Forge's Ollama integration matches this URL (overridable env var).
OLLAMA_URL = os.environ.get("FORGE_OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL_DEFAULT = os.environ.get("FORGE_MAD_OLLAMA_MODEL", "llama3.1:8b")
MADHUBANI_DEFAULT_STEPS = int(os.environ.get("FORGE_MADHUBANI_STEPS", "14"))
MADHUBANI_FINAL_STEPS = int(os.environ.get("FORGE_MADHUBANI_FINAL_STEPS", "24"))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _append_workflow_event(action: str, payload: dict[str, Any]) -> Path:
    """Append a durable workflow event so every action updates the catalog state."""
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    path = GEN_DIR / "workflow-events.jsonl"
    event = {
        "ts": now_iso(),
        "action": action,
        "payload": payload,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return path


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _qc_path_for_png(path: Path) -> Path:
    return path.with_suffix(".qc.json")


def _write_auto_qc(png_path: Path, animal: dict, pose_slug: str) -> dict[str, Any]:
    qc = score_madhubani_png(
        png_path,
        palette_path=SCHEMA_DIR / "palette.json",
        expected_body_fill=animal.get("body_fill_color"),
        body_type=animal.get("body_type"),
        decoration_density=animal.get("decoration_density"),
        required_decoration_zones=animal.get("required_decoration_zones"),
    )
    qc.update({
        "animal_slug": animal["slug"],
        "pose": pose_slug,
        "body_type": animal.get("body_type"),
        "decoration_density_target": animal.get("decoration_density"),
        "quality_lift_contract": "9 of 9 Madhubani rubric checks (incl. pattern_density + decoration_zone_presence Phase-B) are machine-gated before promotion",
    })
    qc_path = _qc_path_for_png(png_path)
    _atomic_write_json(qc_path, qc)
    status = "PASS" if qc["auto_qc_pass"] else "REVIEW"
    print(f"   QC {status}: {qc['pass_count']}/{qc['auto_check_count']} auto checks → {_display(qc_path)}")
    # Q1 trust layer — write blockers.json sibling iff any check failed.
    # Stale blockers files are removed by engine_qc when the new QC passes.
    blockers_path, blockers = engine_qc.write_blockers_json(png_path, qc)
    if blockers and blockers_path:
        print(f"   BLOCKED: {engine_qc.summarize(blockers)} → {_display(blockers_path)}")
    return qc


# --- Schema loading ------------------------------------------------------


def _load_json(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def load_animals() -> dict:
    return _load_json(SCHEMA_DIR / "animals.json")


def load_poses() -> dict:
    return _load_json(SCHEMA_DIR / "poses.json")


def load_masters() -> dict:
    return _load_json(SCHEMA_DIR / "masters.json")


def load_palette() -> dict:
    return _load_json(SCHEMA_DIR / "palette.json")


def find_animal(slug: str) -> dict:
    """Return the animal record for a slug, or raise SystemExit if not found."""
    animals = load_animals()
    for entry in animals.get("animals", []):
        if isinstance(entry, dict) and entry.get("slug") == slug:
            return entry
    available = [e.get("slug", "?") for e in animals.get("animals", []) if isinstance(e, dict)]
    sys.exit(
        f"Unknown animal slug: {slug!r}.\n"
        f"Available in brand/madhubani/animals.json: {', '.join(available)}\n"
        f"Add a new entry to animals.json to enable a new animal."
    )


def find_pose(pose_slug: str) -> dict:
    poses = load_poses().get("poses", [])
    for entry in poses:
        if entry.get("slug") == pose_slug:
            return entry
    available = [e.get("slug") for e in poses]
    sys.exit(f"Unknown pose slug: {pose_slug!r}. Available: {', '.join(available)}")


def find_body_type(body_type_key: str) -> dict:
    bts = load_animals().get("body_types", {})
    if body_type_key not in bts:
        sys.exit(f"Unknown body_type: {body_type_key!r}. Update brand/madhubani/animals.json body_types.")
    return bts[body_type_key]


# --- Subject string assembly --------------------------------------------


@dataclass(frozen=True)
class RenderPlan:
    animal_slug: str
    animal: dict
    pose: dict
    body_type: dict
    register: str
    seed: int
    out_path: Path
    config_string: str
    subject_string: str


def _eye_character_clause(pose_slug: str, eye_intent: str) -> str:
    """Build a per-pose eye character clause, varying the negative reminders
    by pose so the FACE & EXPRESSION rule lands with species + pose specificity."""
    base = f"almond eye carrying {eye_intent.upper()}"
    negatives = {
        "standing-alert":   "(alert intensity, not blank stare, not surprise, not cartoon)",
        "seated-rest":      "(peaceful intelligent rest, not asleep, not blank, not cartoon)",
        "signature-action": "(intense purposeful gaze, not angry cartoon, not blank)",
        "frontal-portrait": "(sacred ceremonial gaze, the gravity of a temple icon, calm timeless dignity, NEVER round cartoon eyes, NEVER surprised, NEVER blank)",
    }
    return f"{base} {negatives.get(pose_slug, '(calm folk-icon presence, never cartoon)')}"


def _body_anatomy_clause(body_type_key: str, animal: dict) -> str:
    """Build a body-type-aware anatomy clause."""
    rules = find_body_type(body_type_key).get("anatomy_rules", [])
    if not rules:
        return ""
    return ", ".join(rules)


def _ground_mark_clause(pose_slug: str, animal: dict) -> str:
    """Per-pose ground anchor."""
    body_type = animal.get("body_type", "")
    if pose_slug == "frontal-portrait":
        return ("no ground line (frontal portrait floats); a decorative aura halo of "
                "dots and small petals radiates outward from the head in cream and saffron")
    if pose_slug == "signature-action":
        return ("dotted Mithila ground line of dust or motion dots rendered as small "
                "ornamental folk dots and short lines beneath the action")
    if body_type == "serpent":
        return "small decorative platform of folk dots beneath the coiled base, clean negative space in all four corners"
    if body_type == "bird":
        return "small dotted ground line below the feet with paired peepal-leaf accents"
    # Default for quadrupeds / primates / armored
    return "dotted Mithila ground line below the feet"


def _pose_action_clause(pose_slug: str, animal: dict) -> str:
    """Per-pose action phrasing, customized by:
       1. Body-type overrides in poses.json (cetacean, serpent, bird, primate)
       2. Animal-specific signature_action / rest_pose_for_species
       3. Fallback: generic mammalian phrasings
    """
    # Body-type override takes priority — cetaceans don't have a side-profile
    # "standing", serpents don't have legs, birds need a perch, etc.
    body_type = animal.get("body_type", "")
    overrides = load_poses().get("body_type_overrides", {})
    bt_overrides = overrides.get(body_type, {})
    if pose_slug in bt_overrides:
        clause = bt_overrides[pose_slug]
        # For seated-rest and signature-action, splice in the animal's
        # per-species detail when available, so e.g. tiger's "crouched
        # ready to leap" still surfaces.
        if pose_slug == "signature-action" and animal.get("signature_action"):
            return f"{clause} — specifically: {animal['signature_action']}"
        if pose_slug == "seated-rest" and animal.get("rest_pose_for_species"):
            return f"{clause} — specifically: {animal['rest_pose_for_species']}"
        return clause

    # Generic mammalian defaults
    if pose_slug == "standing-alert":
        return "STANDING ALERT in complete full-body side profile facing right"
    if pose_slug == "seated-rest":
        species_pose = animal.get("rest_pose_for_species") or "in calm seated rest pose"
        return f"{species_pose} in side profile facing right"
    if pose_slug == "signature-action":
        sig = animal.get("signature_action") or "in characteristic action pose"
        return f"{sig} in dynamic side profile facing right"
    if pose_slug == "frontal-portrait":
        return ("FRONTAL PORTRAIT head-and-shoulders facing the viewer directly "
                "(full frontal symmetric composition, both eyes visible looking forward)")
    return ""


def build_subject_string(animal: dict, pose: dict, register: str) -> str:
    """Generate a complete subject string for the (animal, pose, register) tuple,
    drawing from animals.json / poses.json / palette.json. This replaces the
    hand-written subject strings in the old per-animal shell scripts.
    """
    pose_slug = pose["slug"]
    body_type = animal.get("body_type", "")
    body_color = animal.get("body_fill_color_name", "deep-indigo")
    body_hex   = animal.get("body_fill_color", "#1a2952")

    register_clause = ""
    texture_clause = ""  # texture shift #5 removed v1.1 — was destabilizing prompt
    if register == "madhubani-master-painter":
        register_clause = " painted in the master-painter register (flat folk-icon, never naturalistic illustration)"

    # Species-specific anatomy guard, when the animal record provides one
    # (added v1.1 after rhino kept rendering with 2 horns).
    anatomy_guard = (animal.get("anatomy_must_include") or "").strip()
    anatomy_guard_clause = f"SPECIES ANATOMY: {anatomy_guard}" if anatomy_guard else ""

    # N1-rev2 (2026-05-20) — species_render_name lets us anchor the species
    # in a folk-art register where FLUX.2 keeps pulling toward photorealism.
    # When set, it replaces display_name in the rendered subject ONLY.
    # display_name stays canonical everywhere else (manifests, QC, files).
    species_in_subject = animal.get("species_render_name") or animal["display_name"]
    parts = [
        f"single centered {species_in_subject} {_pose_action_clause(pose_slug, animal)}",
        f"premium Madhubani Mithila folk-art icon{register_clause}",
        anatomy_guard_clause,
        _body_anatomy_clause(body_type, animal),
        animal.get("signature_features", "").strip().rstrip("."),
        _eye_character_clause(pose_slug, pose.get("eye_character_intent", "calm folk-icon presence")),
        "mouth closed",
        # A1.5 — pre-trained species color OVERRIDE.
        # The bare "body filled with X" phrase loses to FLUX's pre-trained
        # species signal for high-pull species (tiger=orange, lion=tan,
        # parrot=green). Use hard language + explicit anti-natural-color
        # framing so the model treats the folk fill as non-negotiable.
        (
            f"BODY FILL OVERRIDE (CRITICAL — this OVERRIDES the model's "
            f"pretrained species-natural color): the entire body silhouette "
            f"MUST be flat-filled with saturated {body_color} ({body_hex}) "
            f"as the dominant base color — this is a Madhubani folk-art "
            f"convention, NOT a naturalistic species render. DO NOT use "
            f"natural species coloring (no natural tiger orange, no realistic "
            f"lion tan, no realistic peacock blue body, no national-geographic-"
            f"style fur/feather/skin tones). The {body_color} fill is the "
            f"canvas; multi-color folk panels go ON TOP of it"
            f"{texture_clause}"
        ),
        ("decorated INSIDE with seven distinct zones of hand-drawn multi-color "
         "Madhubani ornament — tikka medallion on forehead, leaf-vein panel at ear, "
         "dot-band at neck, large ornamental panel on back, vine motif at shoulder, "
         "vermillion floral medallion at hip, rhythmic stripe anklets at every joint"),
        "body BETWEEN zones remains a clean saturated color field (NOT all-over pattern)",
        "bold hand-drawn double-contour keylines with weight variation",
        _ground_mark_clause(pose_slug, animal),
        "8-12 small ornamental flourishes scattered tastefully in negative space",
        "modern Indian streetwear",
        # Phase-A (2026-05-20) — per-species REQUIRED decoration zones from
        # animals.json. These name-and-shame the specific zones the rendered
        # output must show. Previously the engine asked for "seven distinct
        # zones" generically; that landed about half the time. The per-
        # species spec is stricter and species-aware.
        _required_decoration_zones_clause(animal),
        # Phase-A — per-species anatomical count constraints. Fixes the
        # two-tongues-cobra class of hallucination: explicit per-feature
        # count + per-feature anti-pattern wording.
        _anatomical_counts_clause(animal),
        # Phase-A — per-species decoration density target (ornate / maximal /
        # balanced / minimal). Drives how MUCH of the body silhouette is
        # patterned vs left as flat color field.
        _decoration_density_clause(animal),
    ]
    return ", ".join(p for p in parts if p)


def _required_decoration_zones_clause(animal: dict) -> str:
    """Phase-A: surface required_decoration_zones from animals.json as a
    loud mandatory clause in the prompt. Each listed zone must be visibly
    present in the rendered output."""
    zones = animal.get("required_decoration_zones") or []
    if not zones:
        return ""
    bulleted = "; ".join(zones)
    return (
        f"MANDATORY DECORATION ZONES (ALL must be visibly present in the rendered output — failure on any one means the design is incomplete): "
        f"{bulleted}"
    )


def _anatomical_counts_clause(animal: dict) -> str:
    """Phase-A: surface anatomical_count_constraints from animals.json as a
    strict per-feature count clause. Fixes the two-tongues cobra class of
    hallucination by being explicit about COUNTS and anti-patterns."""
    constraints = animal.get("anatomical_count_constraints") or {}
    if not constraints:
        return ""
    items = "; ".join(f"{k}: {v}" for k, v in constraints.items())
    return (
        f"ANATOMICAL COUNTS (strict — these specific feature-count rules MUST be satisfied for the species identity to read correctly): "
        f"{items}"
    )


def _decoration_density_clause(animal: dict) -> str:
    """Phase-A: per-species decoration density target. Maps the density enum
    to an explicit prose description of how much of the body silhouette is
    decorated vs left as flat color field."""
    density = (animal.get("decoration_density") or "ornate").lower()
    descriptions = {
        "minimal": (
            "DECORATION DENSITY: minimal — body silhouette is mostly flat folk color; "
            "at most one or two small interior accents; the focus is on the clean "
            "outline + flat fill, in the Kachni line-school spirit"
        ),
        "balanced": (
            "DECORATION DENSITY: balanced — 3-4 distinct interior decoration zones "
            "with multi-color folk panels; the body between zones stays as clean flat "
            "color field; the 'tasteful merch mark' sweet spot"
        ),
        "ornate": (
            "DECORATION DENSITY: ornate — 5-7 distinct interior decoration zones across "
            "the body silhouette; saddle blanket + leg anklets + neck collar + forehead "
            "tikka + body-zone medallions; classic full Madhubani density; the body is "
            "ornately patterned but anatomy remains clearly readable"
        ),
        "maximal": (
            "DECORATION DENSITY: maximal — the body silhouette is ALMOST ENTIRELY "
            "covered in multi-color folk patterns (8+ distinct ornament zones; very "
            "little flat-color body field visible between zones); the maximum Madhubani "
            "density appropriate to species like peacock where the tail/plumage IS the "
            "primary visual statement"
        ),
    }
    return descriptions.get(density, descriptions["ornate"])


def build_config_string(register: str) -> str:
    """The engine config string. All Madhubani renders use the same config
    except for the register choice."""
    return ",".join([
        "subject.motif=madhubani-folk-icon",
        f"style.tradition={register}",
        "style.detail=maximal-but-printable",
        "style.symmetry=handmade-balanced",
        "style.accents=micro-folk-dots",
        "production.output=print-art",
        "production.ink=vibrant-folk",
        "production.shirt_color=cream-or-black",
        "composition.placement=center-chest",
        "composition.layout=single-mark",
        "composition.background=no-background",
        "composition.border=none",
    ])


def compute_seed(animal: dict, pose: dict, retry: bool, series_lock: bool = False) -> int:
    """Per-animal seed block + per-pose offset + optional retry offset.

    When series_lock=True (the A3 visual-bible mode), the per-pose offset is
    dropped so all four poses of one animal share the same noise vector.
    Pose differentiation then comes from the pose-specific subject string
    only — the animal's "personality" (eye character, palette micro-choices,
    framing micro-choices that FLUX makes from the noise seed) stays
    consistent across the catalog row. Retry offset still fires so retry
    runs land in v2/ with a distinct (but still series-locked) seed.

    Spec lives in brand/madhubani/poses.json seed_allocation."""
    base = int(animal.get("seed_block_start", 8000))
    offsets = load_poses()["seed_allocation"]["ordinal_offset_in_block"]
    offset = 0 if series_lock else int(offsets.get(pose["slug"], 0))
    if retry:
        offset += int(offsets.get("retry-offset", 50))
    return base + offset


# --- Render planning + execution ----------------------------------------


def plan_render(animal_slug: str, pose_slug: str, register: str, retry: bool, version: str | None = None, series_lock: bool = False) -> RenderPlan:
    animal = find_animal(animal_slug)
    pose = find_pose(pose_slug)
    body_type = find_body_type(animal["body_type"])

    if version is None:
        version = "v2" if retry else "v1"

    seed = compute_seed(animal, pose, retry, series_lock=series_lock)
    out_dir = ATTEMPTS_DIR / animal_slug / version
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{pose['ordinal']:02d}_{animal_slug}_{pose_slug}.png"

    return RenderPlan(
        animal_slug=animal_slug,
        animal=animal,
        pose=pose,
        body_type=body_type,
        register=register,
        seed=seed,
        out_path=out_file,
        config_string=build_config_string(register),
        subject_string=build_subject_string(animal, pose, register),
    )


def execute_render(
    plan: RenderPlan,
    steps: int = MADHUBANI_DEFAULT_STEPS,
    dry_run: bool = False,
    metal_slots: int | None = None,
) -> int:
    """Run `forge.py engine render minimalist-tshirt` for a single pose.

    Routes via --profile madhubani so the FLUX.2-klein-4b base model is used
    (empirically validated 2026-05-20 against FLUX.1-dev — see PROFILES["madhubani"]
    docstring in forge.py). The dispatcher in forge.py:mflux_cli_for() picks
    the mflux-generate-flux2 binary based on the profile's flux_model.

    Lane-1 (2026-05-20): when the animal has a `style_reference_path` set in
    animals.json, pass it through as `--style-reference` to forge engine
    render. This makes FLUX.2 condition on the existing corpus (legacy v3
    renders or pass_examples) — visual style transfer that locks the
    Madhubani folk-icon register much harder than prompt-only iteration can.
    """
    cmd = [
        sys.executable, str(FORGE_BIN),
        "engine", "render", "minimalist-tshirt",
        "--subject", plan.subject_string,
        "--config", plan.config_string,
        "--profile", "madhubani",
        "--seed", str(plan.seed),
        "--steps", str(steps),
        "--out", str(plan.out_path),
    ]
    # Pass the style reference through if the animal has one declared. The
    # reference path in animals.json is relative to repo root; resolve it
    # absolute for the child process.
    ref_rel = plan.animal.get("style_reference_path")
    ref_strength = plan.animal.get("style_reference_strength")
    if ref_rel:
        ref_abs = ROOT / ref_rel
        if ref_abs.exists():
            cmd.extend(["--style-reference", str(ref_abs)])
            if ref_strength is not None:
                cmd.extend(["--style-reference-strength", str(ref_strength)])
            print(f"   style-ref: {ref_rel} (strength={ref_strength})")
        else:
            print(f"   ! style_reference_path declared but file missing: {ref_rel}; skipping")
    print(f"\n── [{plan.pose['ordinal']}/4] {plan.animal_slug} — {plan.pose['slug']}  (seed={plan.seed}, register={plan.register}, steps={steps})")
    if dry_run:
        print(f"   [dry-run] would run: {' '.join(cmd[:6])} ...")
        print(f"   [dry-run] subject: {plan.subject_string[:160]}...")
        return 0
    env = os.environ.copy()
    if metal_slots and metal_slots > 1 and not env.get("FORGE_METAL_SLOTS") and not env.get("FORGE_FLUX_PARALLEL_JOBS"):
        env["FORGE_METAL_SLOTS"] = str(metal_slots)
    rc = subprocess.call(cmd, env=env)
    if rc == 0:
        print(f"   ✓ {plan.out_path.relative_to(ROOT)}")
    else:
        print(f"   ✗ render failed (rc={rc})")
    return rc


def render_set(animal_slug: str, register: str, only_pose: str | None = None,
               retry: bool = False, steps: int = MADHUBANI_DEFAULT_STEPS,
               dry_run: bool = False, jobs: int = 1, series_lock: bool = False) -> int:
    """Render a full 4-pose set (or one pose) for an animal.

    When series_lock=True, all poses share the animal's base seed (A3 visual-
    bible mode) — same noise vector, pose differentiated by prompt only."""
    poses = load_poses()["poses"]
    if only_pose:
        poses = [p for p in poses if p["slug"] == only_pose]
        if not poses:
            sys.exit(f"Pose {only_pose!r} not found.")
    version = "v2" if retry else "v1"
    jobs = max(1, min(int(jobs or 1), len(poses)))
    started = datetime.now(timezone.utc)
    expected_speedup = 0.0
    if len(poses) > 1 and jobs > 1:
        sequential_waves = len(poses)
        parallel_waves = (len(poses) + jobs - 1) // jobs
        expected_speedup = round((1 - (parallel_waves / sequential_waves)) * 100, 1)
    print(f"\n═══ Rendering {animal_slug} × {len(poses)} pose(s) in {register} register ═══")
    if jobs > 1:
        print(f"   parallel jobs: {jobs} (requests FORGE_METAL_SLOTS={jobs} for child renders if unset; runtime still caps by memory)")
    if series_lock:
        print(f"   series-lock: ON — all poses share the same base seed for visual-bible consistency")
    failures = 0
    plans = [plan_render(animal_slug, pose["slug"], register, retry, version=version, series_lock=series_lock) for pose in poses]
    result_by_pose: dict[str, dict[str, Any]] = {}

    def run_plan(plan: RenderPlan) -> dict[str, Any]:
        rc = execute_render(plan, steps=steps, dry_run=dry_run, metal_slots=jobs)
        qc: dict[str, Any] | None = None
        qc_path: str | None = None
        if rc == 0 and not dry_run and plan.out_path.exists():
            try:
                qc = _write_auto_qc(plan.out_path, plan.animal, plan.pose["slug"])
                qc_path = str(_qc_path_for_png(plan.out_path))
            except Exception as exc:
                qc = {
                    "auto_qc_pass": False,
                    "score": 0.0,
                    "pass_count": 0,
                    "auto_check_count": 7,
                    "error": str(exc),
                }
                print(f"   QC ERROR: {plan.pose['slug']} — {exc}")
        return {"plan": plan, "returncode": rc, "qc": qc, "qc_path": qc_path}

    if jobs > 1 and not dry_run and len(plans) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
            future_map = {pool.submit(run_plan, plan): plan for plan in plans}
            for future in concurrent.futures.as_completed(future_map):
                result = future.result()
                result_by_pose[result["plan"].pose["slug"]] = result
    else:
        for plan in plans:
            result = run_plan(plan)
            result_by_pose[plan.pose["slug"]] = result

    pose_records: list[dict[str, Any]] = []
    for plan in plans:
        result = result_by_pose[plan.pose["slug"]]
        rc = int(result["returncode"])
        qc = result.get("qc")
        if rc != 0:
            failures += 1
        pose_blockers = engine_qc.derive_blockers(qc) if qc else []
        # publishable here is the strict reading; --force / promote --force can
        # still override at promotion time. Dry-run never claims publishability.
        publishable = (
            not dry_run
            and rc == 0
            and bool(qc and qc.get("auto_qc_pass"))
            and not pose_blockers
        )
        pose_records.append({
            "pose": plan.pose["slug"],
            "ordinal": plan.pose["ordinal"],
            "seed": plan.seed,
            "returncode": rc,
            "status": "DRY_RUN" if dry_run else ("PASS" if rc == 0 else "FAIL"),
            "out_path": str(plan.out_path),
            "directive_json": str(plan.out_path.with_suffix(plan.out_path.suffix + ".directive.json")),
            "transparent_png": str(plan.out_path.with_name(plan.out_path.stem + ".transparent.png")),
            "auto_qc_json": result.get("qc_path"),
            "auto_qc_score": qc.get("score") if qc else None,
            "auto_qc_pass": qc.get("auto_qc_pass") if qc else None,
            "auto_qc_pass_count": qc.get("pass_count") if qc else None,
            "publishable": publishable,
            "blockers": [b["check"] for b in pose_blockers],
            "subject_string": plan.subject_string,
            "config_string": plan.config_string,
        })
    qc_scores = [float(p["auto_qc_score"]) for p in pose_records if p["auto_qc_score"] is not None]
    qc_pass_count = sum(1 for p in pose_records if p["auto_qc_pass"] is True)
    publishable_count = sum(1 for p in pose_records if p.get("publishable") is True)
    blocked_count = sum(1 for p in pose_records if p.get("blockers"))
    finished = datetime.now(timezone.utc)
    manifest_dir = ATTEMPTS_DIR / animal_slug / version
    manifest = {
        "schema": "forge.madhubani_render_set.v1",
        "created_at": started.isoformat(timespec="seconds"),
        "finished_at": finished.isoformat(timespec="seconds"),
        "elapsed_seconds": round((finished - started).total_seconds(), 3),
        "animal_slug": animal_slug,
        "register": register,
        "version": version,
        "retry": retry,
        "steps": steps,
        "jobs": jobs,
        "series_lock": series_lock,
        "expected_parallel_wall_clock_reduction_pct": expected_speedup,
        "dry_run": dry_run,
        "pose_count": len(poses),
        "success_count": len(poses) - failures,
        "failure_count": failures,
        "auto_qc_pass_count": qc_pass_count,
        "auto_qc_mean_score": round(sum(qc_scores) / len(qc_scores), 2) if qc_scores else None,
        "publishable_count": publishable_count,
        "blocked_count": blocked_count,
        "auto_qc_contract": "7/7 rubric checks machine-scored; promotion blocks failed auto-QC unless --force",
        "publishability_contract": "publishable iff returncode==0 AND auto_qc_pass AND blockers==[]; promote --force overrides at promotion time only",
        "status": "DRY_RUN" if dry_run else ("PASS" if failures == 0 else "PARTIAL_FAIL"),
        "poses": pose_records,
        "next_actions": [
            f"{CLI_DISPLAY} promote {animal_slug} <pose> --from-version {version}",
            f"{CLI_DISPLAY} flag {animal_slug} <pose> --from-version {version} --notes \"...\"",
            f"{CLI_DISPLAY} card {animal_slug}",
        ],
    }
    manifest_path = manifest_dir / "render-manifest.json"
    _atomic_write_json(manifest_path, manifest)
    event_log = _append_workflow_event("render_set", {
        "animal_slug": animal_slug,
        "register": register,
        "version": version,
        "status": manifest["status"],
        "manifest": str(manifest_path),
        "jobs": jobs,
        "auto_qc_pass_count": qc_pass_count,
        "auto_qc_mean_score": manifest["auto_qc_mean_score"],
    })
    print(f"\n═══ Done: {len(poses) - failures}/{len(poses)} succeeded ═══")
    print(f"   Outputs: {ATTEMPTS_DIR / animal_slug}")
    print(f"   Manifest: {_display(manifest_path)}")
    print(f"   Workflow log: {_display(event_log)}")
    print(f"   Next: review per docs/catalog/WORKFLOW.md, then promote/flag with:")
    print(f"     {CLI_DISPLAY} promote {animal_slug} <pose> --from-version {version}")
    print(f"     {CLI_DISPLAY} flag    {animal_slug} <pose> --from-version {version} --notes \"...\"")
    return failures


# --- Promote / flag operations ------------------------------------------


def promote_pose(animal_slug: str, pose_slug: str, from_version: str = "v1", force: bool = False) -> None:
    """Copy a passing pose from attempts/{slug}/{v}/ → mastered/{slug}/{pose}/."""
    animal = find_animal(animal_slug)
    pose = find_pose(pose_slug)
    src_png = ATTEMPTS_DIR / animal_slug / from_version / f"{pose['ordinal']:02d}_{animal_slug}_{pose_slug}.png"
    if not src_png.exists():
        sys.exit(f"Source not found: {src_png}")
    qc_path = _qc_path_for_png(src_png)
    if qc_path.exists():
        qc = json.loads(qc_path.read_text(encoding="utf-8"))
    else:
        qc = _write_auto_qc(src_png, animal, pose_slug)
    if not qc.get("auto_qc_pass") and not force:
        failed = [
            name for name, check in (qc.get("checks") or {}).items()
            if isinstance(check, dict) and not check.get("pass")
        ]
        sys.exit(
            f"Auto-QC blocked promotion for {animal_slug}/{pose_slug}: "
            f"{qc.get('pass_count', 0)}/{qc.get('auto_check_count', 7)} checks passed; "
            f"failed={failed}. Use `--force` only after human review."
        )
    dst = MASTERED_DIR / animal_slug / pose_slug
    dst.mkdir(parents=True, exist_ok=True)
    for suffix in (".png", ".png.directive.json", ".transparent.png", ".qc.json"):
        src = src_png.with_suffix(src_png.suffix) if suffix == ".png" else src_png.with_name(src_png.name + suffix.replace(".png", "") if suffix != ".png" else src_png.name)
        # Robust path construction:
        if suffix == ".png":
            src = ATTEMPTS_DIR / animal_slug / from_version / f"{pose['ordinal']:02d}_{animal_slug}_{pose_slug}.png"
            dst_file = dst / "print-1280.png"
        elif suffix == ".png.directive.json":
            src = ATTEMPTS_DIR / animal_slug / from_version / f"{pose['ordinal']:02d}_{animal_slug}_{pose_slug}.png.directive.json"
            dst_file = dst / "directive.json"
        elif suffix == ".transparent.png":
            src = ATTEMPTS_DIR / animal_slug / from_version / f"{pose['ordinal']:02d}_{animal_slug}_{pose_slug}.transparent.png"
            dst_file = dst / "transparent-1280.png"
        elif suffix == ".qc.json":
            src = _qc_path_for_png(src_png)
            dst_file = dst / "auto-qc.json"
        else:
            continue
        if src.exists():
            dst_file.write_bytes(src.read_bytes())
            print(f"   ✓ {dst_file.relative_to(ROOT)}")
        else:
            print(f"   - (skipped, not found: {src.name})")
    # A4: when --force overrides failed checks, surface which checks were
    # overridden so the workflow log carries the why, not just the fact.
    overridden_blockers = engine_qc.derive_blockers(qc) if (force and not qc.get("auto_qc_pass")) else []
    event_log = _append_workflow_event("promote_pose", {
        "animal_slug": animal_slug,
        "pose": pose_slug,
        "from_version": from_version,
        "destination": str(dst),
        "auto_qc_score": qc.get("score"),
        "auto_qc_pass": qc.get("auto_qc_pass"),
        "force": force,
        "overridden_blockers": [b["check"] for b in overridden_blockers],
        "overridden_blockers_detail": overridden_blockers,
    })
    if overridden_blockers:
        names = ", ".join(b["check"] for b in overridden_blockers)
        print(f"   ! force-promoted despite blockers: {names}")
    print(f"\n✓ Promoted {animal_slug}/{pose_slug} from {from_version}")
    print(f"   Workflow log: {_display(event_log)}")
    print(f"   Next: run `card {animal_slug}` to regenerate ARTIST_CARD.md with this pose marked MASTERED.")


def flag_pose(animal_slug: str, pose_slug: str, notes: str, from_version: str = "v1") -> None:
    """Park a non-passing pose in flagged/{slug}/{pose}/ with notes."""
    pose = find_pose(pose_slug)
    src_png = ATTEMPTS_DIR / animal_slug / from_version / f"{pose['ordinal']:02d}_{animal_slug}_{pose_slug}.png"
    if not src_png.exists():
        sys.exit(f"Source not found: {src_png}")
    dst = FLAGGED_DIR / animal_slug / pose_slug
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "best-attempt.png").write_bytes(src_png.read_bytes())
    drv = src_png.with_suffix(src_png.suffix + ".directive.json")
    if drv.exists():
        (dst / "directive.json").write_bytes(drv.read_bytes())
    qc = _qc_path_for_png(src_png)
    if qc.exists():
        (dst / "auto-qc.json").write_bytes(qc.read_bytes())
    (dst / "FLAG_NOTES.md").write_text(
        f"# Flag: {animal_slug} / {pose_slug}\n\n"
        f"**Date:** {date.today().isoformat()}\n"
        f"**From version:** {from_version}\n\n"
        f"## Notes\n\n{notes}\n\n"
        f"## Revisit when\n\n"
        f"- Engine has been updated to address the failure mode noted above\n"
        f"- A LoRA pass has been trained on the catalog\n"
        f"- The pose template in brand/madhubani/poses.json has been revised\n"
    )
    event_log = _append_workflow_event("flag_pose", {
        "animal_slug": animal_slug,
        "pose": pose_slug,
        "from_version": from_version,
        "destination": str(dst),
        "notes": notes,
    })
    print(f"\n⚑ Flagged {animal_slug}/{pose_slug}")
    print(f"   Notes recorded in {dst.relative_to(ROOT)}/FLAG_NOTES.md")
    print(f"   Workflow log: {_display(event_log)}")


# --- Artist card generator ----------------------------------------------


def generate_artist_card(animal_slug: str) -> Path:
    """Auto-generate ARTIST_CARD.md for a mastered set, pulling provenance
    from directive.json files + masters.json + animals.json."""
    animal = find_animal(animal_slug)
    masters = load_masters()
    poses = {p["slug"]: p for p in load_poses()["poses"]}

    mastered_dir = MASTERED_DIR / animal_slug
    if not mastered_dir.exists():
        sys.exit(f"No mastered/{animal_slug}/ directory yet. Promote at least one pose first.")

    flagged_dir = FLAGGED_DIR / animal_slug

    # Collect mastered + flagged poses
    pose_outcomes = []
    for pose_slug, pose in poses.items():
        m = mastered_dir / pose_slug
        f = flagged_dir / pose_slug
        if m.exists():
            drv_file = m / "directive.json"
            drv = json.loads(drv_file.read_text()) if drv_file.exists() else {}
            pose_outcomes.append({
                "pose": pose,
                "status": "MASTERED",
                "seed": drv.get("seed"),
                "register": drv.get("config", {}).get("style", {}).get("tradition", "unknown"),
            })
        elif f.exists():
            pose_outcomes.append({
                "pose": pose,
                "status": "FLAGGED",
                "notes_file": str((f / "FLAG_NOTES.md").relative_to(ROOT)),
            })
        else:
            pose_outcomes.append({"pose": pose, "status": "PENDING"})

    citations = "\n".join(
        f"- **{c['name']}** ({c.get('lifespan', '')}) — {c['what_we_draw_from']}"
        for c in masters["cited_influences"]
    )

    pose_section = "\n\n".join(
        f"### Pose {p['pose']['ordinal']:02d} — {p['pose']['display_name']}"
        + (f"  *(seed {p.get('seed')})*" if p.get('seed') else "")
        + f"\n**Status:** {p['status']}"
        + (f"\n**Register:** `{p['register']}`" if p.get('register') else "")
        + (f"\n**Eye character intent:** {p['pose']['eye_character_intent']}")
        + (f"\n**Flag notes:** see [{p['notes_file']}](../../../{p['notes_file']})" if p.get('notes_file') else "")
        for p in pose_outcomes
    )

    out = mastered_dir / "ARTIST_CARD.md"
    out.write_text(f"""# {animal['display_name']} — Madhubani-Inspired Tee Series

*Forge catalog · Animal · {animal['slug']} · Auto-generated {date.today().isoformat()}*

## About this set

Four poses of the {animal['display_name']} (*{animal['binomial']}*) rendered
in the Madhubani folk-art tradition. The set is designed to function as
either four standalone tees or as a coherent capsule.

## Tradition acknowledged

**{masters['tradition']}** — {masters['region']}. {masters['gi_status']}

> {masters['honest_framing']}

Support practitioners directly via: {', '.join(o['name'] + ' (' + o['url'] + ')' for o in masters['support_organizations'])}

## Stylistic influences cited

{citations}

## Methodology

- **Model:** FLUX.1-dev via mflux on Apple Silicon (local, offline)
- **Engine:** MinimalistTShirtEngine — bin/style_engines.py
- **Render parameters:** 24 steps, guidance 5.5, 1280×1280 base
- **Process:** Set-at-a-time workflow per docs/catalog/WORKFLOW.md
- **Generated by:** bin/forge_madhubani.py (deterministic schema-driven CLI)
- **Reproducibility:** Every directive.json is preserved in mastered/{animal['slug']}/{{pose}}/

## Per-pose outcomes

{pose_section}

## Conservation note

{animal.get('display_name', 'This species')} is classified as
**{animal.get('iucn_status', 'see IUCN')}** by the IUCN.
{animal.get('conservation_note', '')}
""")
    event_log = _append_workflow_event("artist_card", {
        "animal_slug": animal_slug,
        "card": str(out),
    })
    print(f"\n✓ Generated {out.relative_to(ROOT)}")
    print(f"   Workflow log: {_display(event_log)}")
    return out


# --- list / show commands -----------------------------------------------


def cmd_list(what: str) -> None:
    if what == "animals":
        for entry in load_animals().get("animals", []):
            if isinstance(entry, dict) and "slug" in entry:
                print(f"  {entry['slug']:<24} {entry['display_name']:<40} ({entry['body_type']}, seed_block={entry['seed_block_start']})")
        return
    if what == "poses":
        for p in load_poses()["poses"]:
            print(f"  {p['slug']:<20} {p['display_name']:<24} role={p['role']:<18}  eye='{p['eye_character_intent']}'")
        return
    sys.exit(f"Unknown list target: {what!r}. Choices: animals, poses")


def cmd_show(slug: str) -> None:
    a = find_animal(slug)
    print(json.dumps(a, indent=2))


# --- Ollama natural-language router -------------------------------------


def _load_system_prompt() -> str:
    """Build the LLM system prompt from the on-disk teaching corpus.
    The model gets: SKILL.md (workflow + 12 principles + register guide)
    + a compact animal/pose summary it can route against.

    DESIGN NOTE: this routing supports BOTH catalog animals (which have
    pre-registered schemas in animals.json) AND freeform creative
    requests for ANY animal not yet in the catalog. The catalog is the
    storefront-product side; the chat path is the creative-tool side.
    Both share the same engine and rule stack."""
    skill_md = (DOCS_DIR / "SKILL.md").read_text()

    animals_summary = "\n".join(
        f"- {a['slug']} ({a['display_name']}, body_type={a['body_type']})"
        for a in load_animals().get("animals", [])
        if isinstance(a, dict) and "slug" in a
    )
    poses_summary = "\n".join(
        f"- {p['slug']} ({p['display_name']}, {p['role']})"
        for p in load_poses()["poses"]
    )
    body_types = list(load_animals().get("body_types", {}).keys())

    return f"""{skill_md}

---

## YOUR JOB AS THE ROUTING LLM

The user will send a natural-language request for a Madhubani-inspired
tee design. Your job is to interpret it and respond with ONE JSON object
(no explanation, no markdown, no preamble — JUST the JSON) selecting
the parameters that will produce the best render.

You support TWO modes:

### MODE A — Catalog animal (animal IS in the list below)

When the user's request mentions one of the catalog animals, route to
the schema entry. The catalog has rich metadata that produces
consistent series-quality renders.

Output:
{{
  "animal": "<catalog-slug>",
  "pose": "<pose-slug>",
  "register": "madhubani-master-painter",
  "reasoning": "one sentence"
}}

### MODE B — Freeform animal (animal NOT in the catalog list)

When the user asks for an animal that ISN'T in the catalog (whale shark,
octopus, dragon, fox, axolotl, anything), DO NOT reject the request.
Instead, generate the metadata the catalog would have had if the animal
were already there, AND include a "subject_override" if the user's
prompt is already detailed enough to use verbatim.

Output:
{{
  "animal": "<kebab-slug-you-invent>",
  "display_name": "<Title Case Common Name>",
  "binomial": "<Latin name if you know it, otherwise empty string>",
  "body_type": "<one of: {', '.join(body_types)}>",
  "body_fill_color_hex": "<one of: #1a2952 indigo, #5a3a1f walnut, #1f4a3f forest-teal — pick what fits the animal>",
  "body_fill_color_name": "<deep-indigo, walnut-brown, or forest-teal>",
  "signature_features": "<one-line description of the animal's iconic visual features for a folk-art render>",
  "signature_action": "<one-line: what the animal does in its signature-action pose>",
  "rest_pose_for_species": "<one-line: how this animal naturally rests>",
  "pose": "<pose-slug>",
  "register": "madhubani-master-painter",
  "subject_override": "<OPTIONAL: if the user's prompt is already a detailed Madhubani subject string (300+ chars of rich description), put it here verbatim and the engine will use it. Otherwise omit this field and we'll build the subject from the template.>",
  "reasoning": "one sentence"
}}

The freeform mode UNLOCKS the user's creativity. Don't be restrictive.
Whale sharks, otters, butterflies, dragons — all welcome. The engine's
universal rules (ANATOMY FIRST, COLOR FLOOR, SEVEN ZONES, NO SIGNATURE,
etc.) fire regardless of which mode, so freeform animals still get the
full Madhubani treatment.

## CATALOG ANIMALS AVAILABLE

{animals_summary}

## POSES AVAILABLE

{poses_summary}

## REGISTERS AVAILABLE

- `madhubani-contemporary` — mass-market polish, vector-clean
- `madhubani-master-painter` — premium register, hand-drawn line weight, composed palette, character-bearing eyes (DEFAULT for one-off creative requests)

## BODY TYPES AVAILABLE (use one for freeform animal body_type)

{', '.join(body_types)}

## OUTPUT FORMAT (STRICT)

Respond with EXACTLY one JSON object — Mode A shape if catalog animal,
Mode B shape if freeform. No markdown, no commentary, no preamble.
"""


def _ollama_chat(system: str, user: str, model: str, temperature: float = 0.2, timeout: float = 120) -> str:
    """Call local Ollama /api/generate. Matches the pattern used in
    bin/forge_runtime.py:translate_texts_ollama for consistency."""
    body = json.dumps({
        "model": model,
        "system": system,
        "prompt": user,
        "stream": False,
        "format": "json",   # ask Ollama for structured JSON output
        "options": {"temperature": temperature, "num_ctx": 8192},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload.get("response", "")
    except urllib.error.URLError as e:
        sys.exit(
            f"\n✗ Could not reach Ollama at {OLLAMA_URL}\n"
            f"  Error: {e}\n\n"
            f"  Is Ollama running? Try: `ollama serve` in another terminal.\n"
            f"  Is the model installed? Try: `ollama pull {model}`\n"
            f"  Override Ollama URL with: FORGE_OLLAMA_URL=http://...:11434\n"
            f"  Override model with:      FORGE_MAD_OLLAMA_MODEL=qwen2.5:14b (etc.)"
        )


def cmd_chat(user_request: str, model: str, dry_run: bool = False, steps: int = MADHUBANI_DEFAULT_STEPS,
             all_poses: bool = False, pose_override: Optional[str] = None,
             register_override: Optional[str] = None) -> None:
    """Natural-language entry point. Local Ollama interprets the request
    against the SKILL.md corpus and either (Mode A) routes to a catalog
    animal entry or (Mode B) generates a freeform render for any animal
    the user asks for. Freeform is the default for animals not in the
    catalog — the catalog is for production storefront work; chat is
    creative-tool work and should not feel restrictive.

    Overrides:
      - all_poses=True       → render all 4 poses regardless of Ollama's pick
      - pose_override=<slug> → use this pose, override Ollama
      - register_override=…  → use this register, override Ollama
    """
    system = _load_system_prompt()
    print(f"\n💬  You: {user_request}")
    print(f"🧠  Asking local Ollama ({model}) at {OLLAMA_URL}...")
    raw = _ollama_chat(system, user_request, model=model)

    try:
        decision = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(f"\n✗ Ollama did not return valid JSON. Raw output:\n{raw}")

    if "error" in decision:
        # Should be rare now (Mode B handles "not in catalog" gracefully);
        # surfaces only if Ollama genuinely couldn't parse the user request.
        print(f"\n✗ Routing rejected the request: {decision['error']}")
        return

    animal_slug = decision.get("animal", "").strip()
    pose_slug = decision.get("pose", "standing-alert").strip()
    register = decision.get("register", "madhubani-master-painter").strip()

    # Apply user overrides BEFORE validation — user knows their intent
    # better than Ollama does for these specific knobs.
    if pose_override:
        pose_slug = pose_override.strip()
        print(f"   (user override: pose → {pose_slug})")
    if register_override:
        register = register_override.strip()
        print(f"   (user override: register → {register})")

    if register not in {"madhubani-contemporary", "madhubani-master-painter"}:
        register = "madhubani-master-painter"  # fallback

    # Validate pose; fall back to standing-alert if anything's hallucinated/typo'd.
    try:
        find_pose(pose_slug)
    except SystemExit:
        print(f"   (pose {pose_slug!r} unknown, falling back to standing-alert)")
        pose_slug = "standing-alert"

    print(f"\n🤖  Ollama decided:")
    print(f"   animal:    {animal_slug}")
    print(f"   pose:      {pose_slug}{' (will render ALL 4 poses)' if all_poses else ''}")
    print(f"   register:  {register}")
    print(f"   reasoning: {decision.get('reasoning')}")

    # Detect catalog membership
    try:
        find_animal(animal_slug)
        in_catalog = True
    except SystemExit:
        in_catalog = False

    subject_override = (decision.get("subject_override") or "").strip()
    has_rich_override = len(subject_override) >= 150

    # Mode A: catalog animal AND user didn't write a detailed prompt
    # → use the schema-driven templates (consistent catalog quality)
    if in_catalog and not has_rich_override:
        print(f"   mode:      A (catalog animal, schema-driven template)")
        print("\n──────────────────────────────────────────────")
        render_set(
            animal_slug=animal_slug,
            register=register,
            only_pose=None if all_poses else pose_slug,
            retry=False,
            steps=steps,
            dry_run=dry_run,
        )
        return

    # Mode A-prime: catalog animal BUT user wrote a detailed prompt
    # → honor their words verbatim, render via freeform path so
    # their prompt isn't overwritten by the template
    if in_catalog and has_rich_override:
        print(f"   mode:      A' (catalog animal, but USING USER'S DETAILED PROMPT VERBATIM)")
        catalog_record = find_animal(animal_slug)
        transient = dict(catalog_record)
        transient["_originating_user_request"] = user_request
        transient["_freeform"] = False  # it IS in the catalog
        print("\n──────────────────────────────────────────────")
        _render_freeform_poses(
            animal=transient,
            pose_slugs=_pose_slugs_for(all_poses, pose_slug),
            register=register,
            subject_override=subject_override,
            steps=steps,
            dry_run=dry_run,
        )
        return

    # Mode B: freeform — Ollama-generated metadata, render right now.
    print(f"   mode:      B (freeform, animal not in catalog)")
    transient_animal = _synthesize_transient_animal(animal_slug, decision, user_request)
    subject_override = decision.get("subject_override") or ""
    print(f"   body_type: {transient_animal['body_type']}")
    print(f"   body_fill: {transient_animal['body_fill_color']} ({transient_animal['body_fill_color_name']})")
    if subject_override:
        print(f"   subject:   USING USER'S PROMPT VERBATIM ({len(subject_override)} chars)")
    else:
        print(f"   subject:   building from template + Ollama-supplied features")

    print("\n──────────────────────────────────────────────")
    _render_freeform_poses(
        animal=transient_animal,
        pose_slugs=_pose_slugs_for(all_poses, pose_slug),
        register=register,
        subject_override=subject_override.strip() or None,
        steps=steps,
        dry_run=dry_run,
    )


def _pose_slugs_for(all_poses: bool, single_pose: str) -> list[str]:
    """Resolve the pose-scope choice into the list of pose slugs to render."""
    if all_poses:
        return [p["slug"] for p in load_poses()["poses"]]
    return [single_pose]


def _render_freeform_poses(animal: dict, pose_slugs: list[str], register: str,
                            subject_override: Optional[str], steps: int, dry_run: bool) -> int:
    """Iterate _render_freeform across N poses. Returns failure count."""
    print(f"\n═══ Rendering {animal['display_name']} × {len(pose_slugs)} pose(s) (register: {register}) ═══")
    failures = 0
    for slug in pose_slugs:
        rc = _render_freeform(
            animal=animal, pose_slug=slug, register=register,
            subject_override=subject_override, steps=steps, dry_run=dry_run,
        )
        if rc != 0:
            failures += 1
    print(f"\n═══ Done: {len(pose_slugs) - failures}/{len(pose_slugs)} succeeded ═══")
    return failures


def _synthesize_transient_animal(slug: str, decision: dict, user_request: str) -> dict:
    """Build an animal record on the fly for Mode B (freeform) renders.
    Fills in defaults for any field Ollama omitted, so the engine still
    has everything it needs."""
    body_type = decision.get("body_type", "lean-quadruped")
    body_types = load_animals().get("body_types", {})
    if body_type not in body_types:
        body_type = "lean-quadruped"  # safe default

    body_fill_hex = decision.get("body_fill_color_hex", "#1a2952")
    if body_fill_hex not in {"#1a2952", "#5a3a1f", "#1f4a3f"}:
        body_fill_hex = "#1a2952"  # palette anchor fallback

    name_map = {"#1a2952": "deep-indigo", "#5a3a1f": "walnut-brown", "#1f4a3f": "forest-teal"}
    body_fill_name = decision.get("body_fill_color_name") or name_map[body_fill_hex]

    display_name = decision.get("display_name") or slug.replace("-", " ").title()
    stable_seed_bucket = int(hashlib.sha256(slug.encode("utf-8")).hexdigest()[:8], 16) % 900
    return {
        "slug": slug,
        "display_name": display_name,
        "binomial": decision.get("binomial", ""),
        "series": "freeform",
        "body_type": body_type,
        "body_fill_color": body_fill_hex,
        "body_fill_color_name": body_fill_name,
        "signature_features": decision.get("signature_features", f"iconic visual features of a {display_name}"),
        "signature_action": decision.get("signature_action", "in characteristic action pose"),
        "rest_pose_for_species": decision.get("rest_pose_for_species", "in calm seated rest pose"),
        "iucn_status": "unknown",
        "conservation_note": "",
        "seed_block_start": 11000 + stable_seed_bucket * 10,
        "_freeform": True,
        "_originating_user_request": user_request,
    }


def _render_freeform(animal: dict, pose_slug: str, register: str,
                     subject_override: Optional[str], steps: int, dry_run: bool) -> int:
    """Render path for a freeform (non-catalog) animal. Outputs to
    generated/madhubani_animals/freeform/{slug}/v1/ so they don't pollute
    the catalog attempts/ tree."""
    pose = find_pose(pose_slug)
    out_dir = GEN_DIR / "freeform" / animal["slug"] / "v1"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{pose['ordinal']:02d}_{animal['slug']}_{pose_slug}.png"

    # Build subject string — either the user's own prompt (if Ollama
    # passed it through as override) or our normal template.
    if subject_override and len(subject_override) > 150:
        # User wrote a detailed prompt; use it as-is, just guarantee
        # the engine's vibrant-folk anchor words are present so the
        # engine rules fire correctly.
        subject_string = subject_override
        if "Madhubani" not in subject_string:
            subject_string = "premium Madhubani Mithila folk-art icon, " + subject_string
    else:
        subject_string = build_subject_string(animal, pose, register)

    # Anti-illustration anchor for FREEFORM animals (not in the catalog).
    # FLUX has training-data exposure to "Madhubani peacock", "Madhubani
    # elephant" etc., but ZERO exposure to "Madhubani whale-shark" or
    # "Madhubani octopus". For unknown subjects the model defaults to
    # wildlife illustration / naturalistic render, which kills folk-art
    # character. We prepend a hard anchor to remind the model that the
    # subject must be translated INTO the folk-icon idiom — not rendered
    # as it naturally looks in life.
    if animal.get("_freeform"):
        subject_string = (
            "FOLK-ICON TRANSLATION REQUIRED: this is a Madhubani folk-art icon "
            f"for a t-shirt print, NOT a naturalistic wildlife illustration of a "
            f"{animal['display_name']}. Even though {animal['display_name']} is "
            "not a traditional Madhubani subject, render it AS IF a Mithila folk "
            "master had been asked to paint one for the first time: flat saturated "
            "color body fill, double-contour black keylines, hand-drawn folk "
            "ornament zones, almond eye, NO photographic style, NO realistic "
            "wildlife rendering, NO scenery, NO ocean/sky/water background, NO "
            "frame or border around the figure. The image must read as Madhubani "
            "folk-art at first glance, with the species recognizable as a "
            "secondary read. THEN: "
        ) + subject_string

    seed = compute_seed(animal, pose, retry=False)
    config_string = build_config_string(register)

    cmd = [
        sys.executable, str(FORGE_BIN),
        "engine", "render", "minimalist-tshirt",
        "--subject", subject_string,
        "--config", config_string,
        "--seed", str(seed),
        "--steps", str(steps),
        "--out", str(out_file),
    ]
    print(f"\n── freeform render: {animal['display_name']} / {pose_slug} (seed={seed}, steps={steps})")
    if dry_run:
        print(f"   [dry-run] subject: {subject_string[:180]}...")
        _append_workflow_event("freeform_render_dry_run", {
            "animal_slug": animal["slug"],
            "pose": pose_slug,
            "seed": seed,
            "out_path": str(out_file),
        })
        return 0
    rc = subprocess.call(cmd)
    if rc == 0:
        print(f"   ✓ {out_file}")
        qc = _write_auto_qc(out_file, animal, pose_slug)
        # Drop a small JSON sidecar with the originating user request,
        # so freeform renders carry the same provenance discipline as
        # the catalog (just at a per-render granularity, not per-set).
        sidecar = out_file.with_suffix(".freeform.json")
        sidecar.write_text(json.dumps({
            "originating_user_request": animal.get("_originating_user_request", ""),
            "ollama_synthesized_animal": {k: v for k, v in animal.items() if not k.startswith("_")},
            "subject_string": subject_string,
            "seed": seed,
            "steps": steps,
            "register": register,
            "pose": pose_slug,
            "auto_qc_json": str(_qc_path_for_png(out_file)),
            "auto_qc_score": qc.get("score"),
            "auto_qc_pass": qc.get("auto_qc_pass"),
        }, indent=2))
        print(f"   ✓ {sidecar.name}")
        _append_workflow_event("freeform_render", {
            "animal_slug": animal["slug"],
            "pose": pose_slug,
            "seed": seed,
            "out_path": str(out_file),
            "sidecar": str(sidecar),
            "status": "PASS",
            "auto_qc_score": qc.get("score"),
            "auto_qc_pass": qc.get("auto_qc_pass"),
        })
    else:
        print(f"   ✗ render failed (rc={rc})")
        _append_workflow_event("freeform_render", {
            "animal_slug": animal["slug"],
            "pose": pose_slug,
            "seed": seed,
            "out_path": str(out_file),
            "status": "FAIL",
            "returncode": rc,
        })
    return rc


# --- argparse entry point -----------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(
        prog="forge_madhubani",
        description="Madhubani tee catalog driver — schema-fed, offline, the engine fires automatically.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # list
    p_list = sub.add_parser("list", help="List animals or poses from the schema")
    p_list.add_argument("what", choices=["animals", "poses"])

    # show
    p_show = sub.add_parser("show", help="Show full record for one animal slug")
    p_show.add_argument("slug")

    # render
    p_render = sub.add_parser("render", help="Render a set (or one pose) for an animal")
    p_render.add_argument("animal_slug")
    p_render.add_argument("pose_slug", nargs="?", default=None,
                          help="If omitted, renders all 4 poses; if --all-poses also implies all")
    p_render.add_argument("--all-poses", action="store_true",
                          help="Render all 4 poses (the default when pose_slug is omitted)")
    p_render.add_argument("--retry", action="store_true",
                          help="Use retry seed offset and write to v2/ instead of v1/")
    p_render.add_argument("--register", default="madhubani-master-painter",
                          choices=["madhubani-contemporary", "madhubani-master-painter"])
    p_render.add_argument("--steps", type=int, default=MADHUBANI_DEFAULT_STEPS,
                          help=f"FLUX steps (default {MADHUBANI_DEFAULT_STEPS}; use {MADHUBANI_FINAL_STEPS} for final-quality passes)")
    p_render.add_argument("--jobs", type=int, default=int(os.environ.get("FORGE_MADHUBANI_JOBS", "1")),
                          help="Parallel pose renders for a set; child renders request matching Metal slots and runtime caps by memory")
    p_render.add_argument("--dry-run", action="store_true",
                          help="Print what would be rendered without calling FLUX")
    p_render.add_argument("--series-seed", action="store_true", dest="series_seed",
                          help="Visual-bible mode: lock the SAME base seed across all 4 poses so one animal renders as one consistent character with pose-text differentiating actual stance. Default OFF preserves per-pose seed offsets.")

    # promote
    p_prom = sub.add_parser("promote", help="Copy a passing pose from attempts/ → mastered/")
    p_prom.add_argument("animal_slug")
    p_prom.add_argument("pose_slug")
    p_prom.add_argument("--from-version", default="v1")
    p_prom.add_argument("--force", action="store_true",
                        help="allow promotion despite failed auto-QC after human review")

    # flag
    p_flag = sub.add_parser("flag", help="Park a failing pose in flagged/ with notes")
    p_flag.add_argument("animal_slug")
    p_flag.add_argument("pose_slug")
    p_flag.add_argument("--notes", required=True)
    p_flag.add_argument("--from-version", default="v1")

    # card
    p_card = sub.add_parser("card", help="Generate ARTIST_CARD.md for a mastered set")
    p_card.add_argument("animal_slug")

    # chat
    p_chat = sub.add_parser("chat", help="Natural-language request via local Ollama")
    p_chat.add_argument("request", help="Your natural-language design request")
    p_chat.add_argument("--model", default=OLLAMA_MODEL_DEFAULT,
                        help=f"Ollama model name (default: {OLLAMA_MODEL_DEFAULT}, env: FORGE_MAD_OLLAMA_MODEL)")
    p_chat.add_argument("--steps", type=int, default=MADHUBANI_DEFAULT_STEPS,
                        help=f"FLUX steps (default {MADHUBANI_DEFAULT_STEPS}; use {MADHUBANI_FINAL_STEPS} for final-quality passes)")
    p_chat.add_argument("--dry-run", action="store_true")
    p_chat.add_argument("--all-poses", action="store_true",
                        help="Render all 4 poses; overrides Ollama's single-pose pick")
    p_chat.add_argument("--pose", dest="pose_override", default=None,
                        help="Override Ollama's pose choice (e.g. standing-alert, signature-action)")
    p_chat.add_argument("--register", dest="register_override", default=None,
                        choices=["madhubani-contemporary", "madhubani-master-painter"],
                        help="Override Ollama's register choice")

    args = p.parse_args()

    if args.cmd == "list":
        cmd_list(args.what); return 0
    if args.cmd == "show":
        cmd_show(args.slug); return 0
    if args.cmd == "render":
        return render_set(
            animal_slug=args.animal_slug,
            register=args.register,
            only_pose=None if (args.all_poses or args.pose_slug is None) else args.pose_slug,
            retry=args.retry,
            steps=args.steps,
            dry_run=args.dry_run,
            jobs=args.jobs,
            series_lock=getattr(args, "series_seed", False),
        )
    if args.cmd == "promote":
        promote_pose(args.animal_slug, args.pose_slug, from_version=args.from_version, force=args.force); return 0
    if args.cmd == "flag":
        flag_pose(args.animal_slug, args.pose_slug, notes=args.notes, from_version=args.from_version); return 0
    if args.cmd == "card":
        generate_artist_card(args.animal_slug); return 0
    if args.cmd == "chat":
        cmd_chat(args.request, model=args.model, dry_run=args.dry_run, steps=args.steps,
                 all_poses=args.all_poses, pose_override=args.pose_override,
                 register_override=args.register_override); return 0

    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
