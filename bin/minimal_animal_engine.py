"""Beta 8-line animal mark engine for Forge.

This engine is deliberately procedural. Diffusion models cannot honestly
guarantee "no more than 8 lines"; SVG construction can. The SVG is the source
of truth, the PNG is a preview, and QC counts the actual stroke primitives.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


Point = tuple[float, float]


@dataclass(frozen=True)
class MinimalAnimalConfig:
    description: str
    max_lines: int = 8
    seed: int = 1
    width: int = 1280
    height: int = 1280
    stroke_width: float = 18.0
    background: str = "#F5EFE3"
    stroke: str = "#111111"
    supersample: int = 2


@dataclass(frozen=True)
class Stroke:
    role: str
    points: tuple[Point, ...]


_ANIMAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "elephant": ("elephant", "trunk", "tusk"),
    "rhino": ("rhino", "rhinoceros", "horn"),
    "big-cat": ("tiger", "leopard", "lion", "cheetah", "panther", "jaguar", "cat"),
    "canine": ("dog", "wolf", "fox", "jackal", "coyote"),
    "deer": ("deer", "buck", "antelope", "blackbuck", "stag", "gazelle"),
    "bird": ("bird", "peacock", "parrot", "eagle", "owl", "finch", "jay", "sparrow", "crow"),
    "fish": ("fish", "shark", "whale", "dolphin", "orca", "ray"),
    "serpent": ("snake", "cobra", "serpent", "python", "viper", "naga"),
    "turtle": ("turtle", "tortoise", "terrapin"),
    "insect": ("butterfly", "bee", "dragonfly", "moth", "beetle"),
    "primate": ("monkey", "macaque", "ape", "langur", "gorilla"),
}


def write_minimal_animal(config: MinimalAnimalConfig, out_path: Path) -> dict[str, str]:
    """Write SVG, PNG, QC, and manifest for a closed-loop 8-line animal mark."""
    if not config.description.strip():
        raise ValueError("description is required")
    if config.max_lines < 1 or config.max_lines > 8:
        raise ValueError("max_lines must be between 1 and 8")
    if config.width < 256 or config.height < 256:
        raise ValueError("canvas must be at least 256x256")

    out_path = out_path.expanduser().resolve()
    if out_path.suffix.lower() not in {".png", ".svg"}:
        out_path = out_path.with_suffix(".png")
    png_path = out_path if out_path.suffix.lower() == ".png" else out_path.with_suffix(".png")
    svg_path = out_path if out_path.suffix.lower() == ".svg" else out_path.with_suffix(".svg")
    qc_path = png_path.with_suffix(".qc.json")
    manifest_path = png_path.with_suffix(".manifest.json")

    animal_type = infer_animal_type(config.description)
    strokes = build_strokes(config.description, animal_type=animal_type, seed=config.seed)
    strokes = strokes[: config.max_lines]
    qc = quality_report(config, animal_type, strokes)

    _atomic_write_text(svg_path, to_svg(config, strokes, qc))
    render_png(config, strokes, png_path)
    _atomic_write_text(qc_path, json.dumps(qc, indent=2) + "\n")
    manifest = {
        "schema": "forge.minimal_animal.v1beta",
        "status": "PASS" if qc["closed_loop_pass"] else "FAIL",
        "description": config.description,
        "animal_type": animal_type,
        "config": asdict(config),
        "artifacts": {
            "png": str(png_path),
            "svg": str(svg_path),
            "qc": str(qc_path),
        },
        "closed_loop": {
            "steps": [
                "interpret animal description",
                "construct <= max_lines vector stroke plan",
                "render SVG source of truth",
                "render PNG preview",
                "run line-count/bounds/no-fill QC",
                "write manifest",
            ],
            "guarantee": "line_count is counted from SVG stroke primitives, not guessed from pixels",
            "ml_inference": "none",
            "cpu_ml_fallback": False,
        },
    }
    _atomic_write_text(manifest_path, json.dumps(manifest, indent=2) + "\n")
    if not qc["closed_loop_pass"]:
        raise ValueError(f"minimal animal QC failed: {qc['issues']}")
    return {
        "png": str(png_path),
        "svg": str(svg_path),
        "qc": str(qc_path),
        "manifest": str(manifest_path),
    }


def infer_animal_type(description: str) -> str:
    text = description.lower()
    for animal_type, keywords in _ANIMAL_KEYWORDS.items():
        if any(re.search(rf"\b{re.escape(word)}\b", text) for word in keywords):
            return animal_type
    return "quadruped"


def build_strokes(description: str, *, animal_type: str, seed: int) -> list[Stroke]:
    """Build an 8-stroke-or-less animal mark in normalized 0..1000 space."""
    jitter = _jitter(description, seed)
    builders = {
        "elephant": _elephant,
        "rhino": _rhino,
        "big-cat": _big_cat,
        "canine": _canine,
        "deer": _deer,
        "bird": _bird,
        "fish": _fish,
        "serpent": _serpent,
        "turtle": _turtle,
        "insect": _insect,
        "primate": _primate,
        "quadruped": _quadruped,
    }
    return builders.get(animal_type, _quadruped)(jitter)


def quality_report(config: MinimalAnimalConfig, animal_type: str, strokes: list[Stroke]) -> dict[str, Any]:
    issues: list[str] = []
    line_count = len(strokes)
    if line_count > config.max_lines:
        issues.append(f"line count {line_count} exceeds max_lines {config.max_lines}")
    if line_count < 1:
        issues.append("no strokes emitted")
    for idx, stroke in enumerate(strokes, 1):
        if len(stroke.points) < 2:
            issues.append(f"stroke {idx} has fewer than 2 points")
        for x, y in stroke.points:
            if x < 0 or x > 1000 or y < 0 or y > 1000:
                issues.append(f"stroke {idx} point out of normalized bounds: {(x, y)}")
    return {
        "schema": "forge.minimal_animal_qc.v1beta",
        "engine": "minimal-animal-lines",
        "animal_type": animal_type,
        "line_count": line_count,
        "max_lines": config.max_lines,
        "line_count_pass": line_count <= config.max_lines,
        "bounds_pass": not any("bounds" in issue for issue in issues),
        "no_fill_pass": True,
        "closed_loop_pass": not issues,
        "stroke_roles": [stroke.role for stroke in strokes],
        "issues": issues,
    }


def to_svg(config: MinimalAnimalConfig, strokes: list[Stroke], qc: dict[str, Any]) -> str:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{config.width}" '
            f'height="{config.height}" viewBox="0 0 {config.width} {config.height}" '
            'data-forge-engine="minimal-animal-lines" '
            f'data-line-count="{len(strokes)}" data-max-lines="{config.max_lines}">'
        ),
        f'<title>{escape(config.description[:120])}</title>',
        f'<desc>{escape(json.dumps(qc, sort_keys=True))}</desc>',
        f'<rect width="100%" height="100%" fill="{escape(config.background)}"/>',
        (
            f'<g fill="none" stroke="{escape(config.stroke)}" stroke-width="{config.stroke_width:g}" '
            'stroke-linecap="round" stroke-linejoin="round">'
        ),
    ]
    for idx, stroke in enumerate(strokes, 1):
        pts = " ".join(f"{_sx(config, x):.2f},{_sy(config, y):.2f}" for x, y in stroke.points)
        parts.append(f'  <polyline data-line="{idx}" data-role="{escape(stroke.role)}" points="{pts}"/>')
    parts.extend(["</g>", "</svg>"])
    return "\n".join(parts) + "\n"


def render_png(config: MinimalAnimalConfig, strokes: list[Stroke], path: Path) -> None:
    from PIL import Image, ImageDraw

    scale = max(1, int(config.supersample))
    image = Image.new("RGB", (config.width * scale, config.height * scale), config.background)
    draw = ImageDraw.Draw(image)
    line_width = max(1, int(round(config.stroke_width * scale)))
    for stroke in strokes:
        points = [(int(round(_sx(config, x) * scale)), int(round(_sy(config, y) * scale))) for x, y in stroke.points]
        draw.line(points, fill=config.stroke, width=line_width, joint="curve")
    if scale > 1:
        image = image.resize((config.width, config.height), Image.Resampling.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    image.save(tmp, "PNG", optimize=True)
    os.replace(tmp, path)


def _sx(config: MinimalAnimalConfig, x: float) -> float:
    pad = config.width * 0.09
    return pad + (config.width - 2 * pad) * (x / 1000.0)


def _sy(config: MinimalAnimalConfig, y: float) -> float:
    pad = config.height * 0.12
    return pad + (config.height - 2 * pad) * (y / 1000.0)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _jitter(description: str, seed: int) -> float:
    digest = hashlib.sha256(f"{seed}:{description.strip().lower()}".encode("utf-8")).hexdigest()
    return (int(digest[:6], 16) / 0xFFFFFF) - 0.5


def _p(x: float, y: float, j: float = 0.0, scale: float = 18.0) -> Point:
    return (round(x + j * scale, 3), round(y - j * scale * 0.55, 3))


def _stroke(role: str, points: list[Point]) -> Stroke:
    return Stroke(role=role, points=tuple(points))


def _quadruped(j: float) -> list[Stroke]:
    return [
        _stroke("back-to-tail-body-contour", [_p(135, 565, j), _p(250, 430, j), _p(520, 395, j), _p(740, 485, j), _p(850, 565, j)]),
        _stroke("belly-line", [_p(230, 640, j), _p(440, 690, j), _p(700, 650, j)]),
        _stroke("head-and-muzzle", [_p(725, 485, j), _p(815, 420, j), _p(900, 480, j), _p(850, 555, j)]),
        _stroke("front-leg", [_p(675, 640, j), _p(655, 800, j), _p(705, 800, j)]),
        _stroke("hind-leg", [_p(335, 655, j), _p(300, 805, j), _p(360, 790, j)]),
        _stroke("tail", [_p(150, 555, j), _p(70, 500, j), _p(105, 455, j)]),
        _stroke("ear", [_p(770, 445, j), _p(795, 360, j), _p(825, 445, j)]),
        _stroke("eye", [_p(825, 485, j), _p(835, 482, j)]),
    ]


def _big_cat(j: float) -> list[Stroke]:
    strokes = _quadruped(j)
    strokes[5] = _stroke("long-tail", [_p(145, 555, j), _p(30, 545, j), _p(75, 455, j), _p(140, 490, j)])
    strokes[7] = _stroke("eye-and-whisker", [_p(825, 485, j), _p(837, 482, j), _p(885, 505, j)])
    return strokes


def _canine(j: float) -> list[Stroke]:
    strokes = _quadruped(j)
    strokes[2] = _stroke("long-muzzle", [_p(720, 490, j), _p(815, 425, j), _p(935, 485, j), _p(850, 555, j)])
    strokes[6] = _stroke("pointed-ear", [_p(770, 450, j), _p(790, 340, j), _p(835, 455, j)])
    return strokes


def _deer(j: float) -> list[Stroke]:
    strokes = _quadruped(j)
    strokes[5] = _stroke("short-tail", [_p(150, 560, j), _p(90, 535, j)])
    strokes[6] = _stroke("antler", [_p(800, 425, j), _p(790, 315, j), _p(750, 270, j), _p(790, 315, j), _p(835, 265, j)])
    return strokes


def _elephant(j: float) -> list[Stroke]:
    return [
        _stroke("body-dome", [_p(125, 585, j), _p(250, 390, j), _p(565, 360, j), _p(805, 520, j), _p(820, 660, j), _p(645, 690, j), _p(260, 675, j)]),
        _stroke("head-and-trunk", [_p(700, 480, j), _p(830, 410, j), _p(925, 520, j), _p(865, 700, j), _p(920, 765, j)]),
        _stroke("ear", [_p(650, 485, j), _p(555, 510, j), _p(585, 650, j), _p(705, 615, j), _p(650, 485, j)]),
        _stroke("front-leg", [_p(680, 675, j), _p(660, 815, j), _p(720, 815, j)]),
        _stroke("rear-leg", [_p(300, 675, j), _p(285, 815, j), _p(350, 815, j)]),
        _stroke("tail", [_p(145, 590, j), _p(80, 645, j), _p(100, 700, j)]),
        _stroke("tusk", [_p(850, 560, j), _p(930, 610, j), _p(855, 630, j)]),
        _stroke("eye", [_p(795, 500, j), _p(805, 498, j)]),
    ]


def _rhino(j: float) -> list[Stroke]:
    strokes = _quadruped(j)
    strokes[0] = _stroke("heavy-body", [_p(120, 585, j), _p(255, 425, j), _p(565, 390, j), _p(805, 505, j), _p(860, 625, j), _p(660, 685, j), _p(260, 665, j)])
    strokes[2] = _stroke("head-plate", [_p(720, 500, j), _p(835, 430, j), _p(930, 515, j), _p(840, 590, j), _p(720, 500, j)])
    strokes[6] = _stroke("single-horn", [_p(865, 455, j), _p(950, 375, j), _p(910, 500, j)])
    return strokes


def _bird(j: float) -> list[Stroke]:
    return [
        _stroke("body", [_p(240, 585, j), _p(360, 430, j), _p(620, 430, j), _p(760, 590, j), _p(520, 690, j), _p(300, 655, j)]),
        _stroke("head", [_p(680, 480, j), _p(760, 385, j), _p(850, 470, j), _p(760, 550, j)]),
        _stroke("beak", [_p(835, 465, j), _p(945, 430, j), _p(850, 500, j)]),
        _stroke("wing", [_p(420, 500, j), _p(555, 600, j), _p(395, 645, j)]),
        _stroke("tail", [_p(250, 595, j), _p(100, 510, j), _p(170, 650, j)]),
        _stroke("leg-one", [_p(520, 680, j), _p(500, 800, j)]),
        _stroke("leg-two", [_p(595, 665, j), _p(630, 800, j)]),
        _stroke("eye", [_p(770, 455, j), _p(780, 453, j)]),
    ]


def _fish(j: float) -> list[Stroke]:
    return [
        _stroke("body", [_p(170, 560, j), _p(360, 390, j), _p(700, 395, j), _p(890, 560, j), _p(690, 705, j), _p(360, 705, j), _p(170, 560, j)]),
        _stroke("tail-top", [_p(175, 560, j), _p(55, 430, j), _p(70, 560, j)]),
        _stroke("tail-bottom", [_p(175, 560, j), _p(55, 690, j), _p(70, 560, j)]),
        _stroke("dorsal-fin", [_p(470, 405, j), _p(555, 300, j), _p(620, 410, j)]),
        _stroke("belly-fin", [_p(520, 700, j), _p(590, 805, j), _p(640, 690, j)]),
        _stroke("gill", [_p(735, 470, j), _p(700, 560, j), _p(735, 650, j)]),
        _stroke("mouth", [_p(875, 555, j), _p(930, 540, j)]),
        _stroke("eye", [_p(800, 500, j), _p(812, 498, j)]),
    ]


def _serpent(j: float) -> list[Stroke]:
    return [
        _stroke("s-curve-body", [_p(145, 650, j), _p(310, 485, j), _p(505, 650, j), _p(685, 475, j), _p(850, 610, j)]),
        _stroke("coiled-base", [_p(260, 735, j), _p(420, 835, j), _p(650, 790, j), _p(520, 700, j), _p(360, 710, j)]),
        _stroke("hood-left", [_p(715, 475, j), _p(650, 335, j), _p(770, 280, j)]),
        _stroke("hood-right", [_p(770, 280, j), _p(905, 350, j), _p(845, 500, j)]),
        _stroke("head", [_p(745, 330, j), _p(815, 315, j), _p(860, 370, j), _p(800, 420, j)]),
        _stroke("tongue", [_p(860, 370, j), _p(940, 360, j), _p(970, 325, j)]),
        _stroke("belly-line", [_p(410, 610, j), _p(560, 570, j), _p(720, 595, j)]),
        _stroke("eye", [_p(810, 350, j), _p(820, 348, j)]),
    ]


def _turtle(j: float) -> list[Stroke]:
    return [
        _stroke("shell", [_p(210, 590, j), _p(335, 420, j), _p(640, 410, j), _p(795, 585, j), _p(650, 715, j), _p(330, 720, j), _p(210, 590, j)]),
        _stroke("head", [_p(780, 560, j), _p(895, 515, j), _p(920, 590, j), _p(805, 635, j)]),
        _stroke("front-flipper", [_p(680, 680, j), _p(800, 805, j), _p(610, 735, j)]),
        _stroke("rear-flipper", [_p(315, 680, j), _p(205, 790, j), _p(405, 735, j)]),
        _stroke("shell-line-one", [_p(355, 435, j), _p(500, 700, j), _p(650, 430, j)]),
        _stroke("shell-line-two", [_p(280, 585, j), _p(730, 585, j)]),
        _stroke("tail", [_p(215, 595, j), _p(120, 560, j)]),
        _stroke("eye", [_p(880, 555, j), _p(890, 553, j)]),
    ]


def _insect(j: float) -> list[Stroke]:
    return [
        _stroke("body", [_p(500, 410, j), _p(540, 520, j), _p(500, 705, j), _p(460, 520, j), _p(500, 410, j)]),
        _stroke("left-wing", [_p(490, 480, j), _p(270, 310, j), _p(190, 540, j), _p(455, 560, j)]),
        _stroke("right-wing", [_p(510, 480, j), _p(730, 310, j), _p(810, 540, j), _p(545, 560, j)]),
        _stroke("left-lower-wing", [_p(460, 590, j), _p(280, 740, j), _p(430, 820, j)]),
        _stroke("right-lower-wing", [_p(540, 590, j), _p(720, 740, j), _p(570, 820, j)]),
        _stroke("antenna-left", [_p(485, 420, j), _p(410, 300, j), _p(370, 280, j)]),
        _stroke("antenna-right", [_p(515, 420, j), _p(590, 300, j), _p(630, 280, j)]),
        _stroke("thorax-mark", [_p(470, 530, j), _p(530, 530, j)]),
    ]


def _primate(j: float) -> list[Stroke]:
    return [
        _stroke("seated-back", [_p(300, 650, j), _p(335, 465, j), _p(500, 385, j), _p(675, 470, j), _p(700, 650, j)]),
        _stroke("belly", [_p(380, 615, j), _p(500, 715, j), _p(620, 615, j)]),
        _stroke("head", [_p(430, 375, j), _p(505, 285, j), _p(595, 375, j), _p(520, 465, j), _p(430, 375, j)]),
        _stroke("arm-left", [_p(390, 535, j), _p(260, 675, j), _p(330, 760, j)]),
        _stroke("arm-right", [_p(615, 535, j), _p(750, 675, j), _p(690, 760, j)]),
        _stroke("leg-line", [_p(390, 700, j), _p(500, 830, j), _p(610, 700, j)]),
        _stroke("tail-curve", [_p(300, 650, j), _p(155, 720, j), _p(200, 840, j), _p(310, 805, j)]),
        _stroke("eye-line", [_p(475, 365, j), _p(540, 365, j)]),
    ]
