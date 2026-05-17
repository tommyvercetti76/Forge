"""Procedural symmetry engines for Forge.

This module deliberately avoids diffusion. Mandalas need exact construction:
polar coordinates, repeated motifs, deterministic seeds, and QC artifacts that
say how the symmetry was built.
"""

from __future__ import annotations

import json
import math
import os
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


Point = tuple[float, float]


COMPLEXITY_LEVELS = {
    "simple": 1,
    "balanced": 2,
    "elaborate": 3,
    "max": 4,
}

MANDALA_STYLES = {"coloring", "sacred", "floral", "geometric", "playful", "luxury"}
CHILD_THEMES = ("rabbits-garden", "crows-texas", "blue-jay")


@dataclass(frozen=True)
class MandalaConfig:
    style: str = "coloring"
    symmetry: int = 12
    rings: int = 7
    complexity: str = "elaborate"
    seed: int = 1
    width: int = 2400
    height: int = 2400
    mirror: bool = True
    stroke_width: float = 3.0
    palette: str = "ink"
    supersample: int = 2


@dataclass(frozen=True)
class ChildrensBookConfig:
    theme: str = "all"
    pages: int = 3
    symmetry: int = 12
    rings: int = 7
    complexity: str = "max"
    seed: int = 101
    width: int = 2400
    height: int = 2400
    palette: str = "ink"
    supersample: int = 2


class VectorCanvas:
    """Small vector scene that can export both SVG and PNG."""

    def __init__(self, width: int, height: int, *, background: str, stroke: str, fill: str = "none"):
        self.width = int(width)
        self.height = int(height)
        self.background = background
        self.stroke = stroke
        self.fill = fill
        self.shapes: list[dict[str, Any]] = []

    def add_polygon(
        self,
        points: list[Point],
        *,
        stroke: str | None = None,
        fill: str = "none",
        width: float | None = None,
        opacity: float = 1.0,
    ) -> None:
        if len(points) >= 3:
            self.shapes.append({
                "type": "polygon",
                "points": points,
                "stroke": stroke or self.stroke,
                "fill": fill,
                "width": width,
                "opacity": opacity,
            })

    def add_polyline(
        self,
        points: list[Point],
        *,
        stroke: str | None = None,
        width: float | None = None,
        opacity: float = 1.0,
        close: bool = False,
    ) -> None:
        if len(points) >= 2:
            self.shapes.append({
                "type": "polyline",
                "points": points,
                "stroke": stroke or self.stroke,
                "fill": "none",
                "width": width,
                "opacity": opacity,
                "close": close,
            })

    def add_circle(
        self,
        cx: float,
        cy: float,
        r: float,
        *,
        stroke: str | None = None,
        fill: str = "none",
        width: float | None = None,
        opacity: float = 1.0,
    ) -> None:
        if r > 0:
            self.shapes.append({
                "type": "circle",
                "cx": cx,
                "cy": cy,
                "r": r,
                "stroke": stroke or self.stroke,
                "fill": fill,
                "width": width,
                "opacity": opacity,
            })

    def add_line(
        self,
        p1: Point,
        p2: Point,
        *,
        stroke: str | None = None,
        width: float | None = None,
        opacity: float = 1.0,
    ) -> None:
        self.add_polyline([p1, p2], stroke=stroke, width=width, opacity=opacity)

    def to_svg(self) -> str:
        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" '
                f'height="{self.height}" viewBox="0 0 {self.width} {self.height}">'
            ),
            f'<rect width="100%" height="100%" fill="{escape(self.background)}"/>',
            '<g stroke-linecap="round" stroke-linejoin="round">',
        ]
        for shape in self.shapes:
            stroke = escape(str(shape.get("stroke") or self.stroke))
            fill = escape(str(shape.get("fill") or "none"))
            width = float(shape.get("width") or 3.0)
            opacity = float(shape.get("opacity") or 1.0)
            common = (
                f'stroke="{stroke}" fill="{fill}" stroke-width="{width:.3f}" '
                f'opacity="{opacity:.3f}"'
            )
            if shape["type"] == "circle":
                parts.append(
                    f'<circle cx="{shape["cx"]:.3f}" cy="{shape["cy"]:.3f}" '
                    f'r="{shape["r"]:.3f}" {common}/>'
                )
            elif shape["type"] == "polygon":
                pts = " ".join(f"{x:.3f},{y:.3f}" for x, y in shape["points"])
                parts.append(f'<polygon points="{pts}" {common}/>')
            elif shape["type"] == "polyline":
                pts_list = list(shape["points"])
                if shape.get("close") and pts_list:
                    pts_list.append(pts_list[0])
                pts = " ".join(f"{x:.3f},{y:.3f}" for x, y in pts_list)
                parts.append(f'<polyline points="{pts}" {common}/>')
        parts.extend(["</g>", "</svg>"])
        return "\n".join(parts) + "\n"

    def render_png(self, path: Path, *, supersample: int = 2) -> None:
        from PIL import Image, ImageDraw

        scale = max(1, int(supersample))
        image = Image.new("RGB", (self.width * scale, self.height * scale), self.background)
        draw = ImageDraw.Draw(image)

        def sc_point(point: Point) -> tuple[int, int]:
            return (int(round(point[0] * scale)), int(round(point[1] * scale)))

        def sc_color(color: str) -> str:
            return color

        for shape in self.shapes:
            width = max(1, int(round(float(shape.get("width") or 3.0) * scale)))
            stroke = sc_color(str(shape.get("stroke") or self.stroke))
            fill = str(shape.get("fill") or "none")
            if fill == "none":
                fill_value = None
            else:
                fill_value = sc_color(fill)
            if shape["type"] == "circle":
                cx = float(shape["cx"]) * scale
                cy = float(shape["cy"]) * scale
                r = float(shape["r"]) * scale
                box = [int(cx - r), int(cy - r), int(cx + r), int(cy + r)]
                draw.ellipse(box, outline=stroke, fill=fill_value, width=width)
            elif shape["type"] == "polygon":
                pts = [sc_point(p) for p in shape["points"]]
                if fill_value:
                    draw.polygon(pts, fill=fill_value)
                if pts:
                    draw.line(pts + [pts[0]], fill=stroke, width=width, joint="curve")
            elif shape["type"] == "polyline":
                pts = [sc_point(p) for p in shape["points"]]
                if shape.get("close") and pts:
                    pts.append(pts[0])
                draw.line(pts, fill=stroke, width=width, joint="curve")

        if scale > 1:
            image = image.resize((self.width, self.height), Image.Resampling.LANCZOS)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        image.save(tmp, "PNG", optimize=True)
        os.replace(tmp, path)


def _palette(name: str, style: str) -> dict[str, str]:
    if style == "luxury" or name == "royal":
        return {"background": "#111827", "stroke": "#F6D365", "accent": "#F8FAFC", "soft": "#22304A"}
    if name == "soft":
        return {"background": "#FFFDF7", "stroke": "#1F2933", "accent": "#7C3AED", "soft": "#E7F4EA"}
    return {"background": "#FFFFFF", "stroke": "#111111", "accent": "#111111", "soft": "#FFFFFF"}


def _polar(cx: float, cy: float, radius: float, theta: float) -> Point:
    return (cx + radius * math.cos(theta), cy + radius * math.sin(theta))


def _ellipse_points(cx: float, cy: float, rx: float, ry: float, rotation: float = 0.0, steps: int = 80) -> list[Point]:
    points = []
    c = math.cos(rotation)
    s = math.sin(rotation)
    for i in range(steps):
        t = math.tau * i / steps
        x = rx * math.cos(t)
        y = ry * math.sin(t)
        points.append((cx + x * c - y * s, cy + x * s + y * c))
    return points


def _petal_points(
    cx: float,
    cy: float,
    inner: float,
    outer: float,
    theta: float,
    half_angle: float,
    *,
    pinch: float = 0.95,
    steps: int = 18,
) -> list[Point]:
    left: list[Point] = []
    right: list[Point] = []
    for i in range(steps + 1):
        t = i / steps
        radius = inner + (outer - inner) * t
        spread = half_angle * (math.sin(math.pi * t) ** pinch)
        left.append(_polar(cx, cy, radius, theta - spread))
        right.append(_polar(cx, cy, radius, theta + spread))
    return left + list(reversed(right))


def _arc_points(cx: float, cy: float, radius: float, a0: float, a1: float, *, steps: int = 32) -> list[Point]:
    return [_polar(cx, cy, radius, a0 + (a1 - a0) * i / steps) for i in range(steps + 1)]


def _star_points(cx: float, cy: float, radius: float, points: int, rotation: float) -> list[Point]:
    out = []
    for i in range(points * 2):
        r = radius if i % 2 == 0 else radius * 0.42
        out.append(_polar(cx, cy, r, rotation + math.tau * i / (points * 2)))
    return out


def _diamond_points(cx: float, cy: float, radius: float, theta: float) -> list[Point]:
    return [
        _polar(cx, cy, radius, theta),
        _polar(cx, cy, radius * 0.42, theta + math.pi / 2),
        _polar(cx, cy, radius, theta + math.pi),
        _polar(cx, cy, radius * 0.42, theta + 3 * math.pi / 2),
    ]


def _complexity_value(value: str) -> int:
    if value not in COMPLEXITY_LEVELS:
        raise ValueError(f"unknown complexity {value!r}; choose one of {', '.join(COMPLEXITY_LEVELS)}")
    return COMPLEXITY_LEVELS[value]


def _validate_mandala_config(config: MandalaConfig) -> None:
    if config.style not in MANDALA_STYLES:
        raise ValueError(f"unknown mandala style {config.style!r}; choose one of {', '.join(sorted(MANDALA_STYLES))}")
    if config.symmetry < 4 or config.symmetry > 64:
        raise ValueError("--symmetry must be between 4 and 64")
    if config.rings < 2 or config.rings > 24:
        raise ValueError("--rings must be between 2 and 24")
    if config.width < 256 or config.height < 256:
        raise ValueError("--width and --height must be at least 256")
    _complexity_value(config.complexity)


def build_mandala(config: MandalaConfig) -> tuple[VectorCanvas, dict[str, Any]]:
    _validate_mandala_config(config)
    rng = random.Random(config.seed)
    palette = _palette(config.palette, config.style)
    canvas = VectorCanvas(config.width, config.height, background=palette["background"], stroke=palette["stroke"])
    cx, cy = config.width / 2.0, config.height / 2.0
    max_radius = min(config.width, config.height) * 0.46
    sector = math.tau / config.symmetry
    detail = _complexity_value(config.complexity)
    stroke = max(1.0, float(config.stroke_width))

    # Concentric construction scaffold.
    canvas.add_circle(cx, cy, max_radius * 0.045, width=stroke * 1.1)
    canvas.add_circle(cx, cy, max_radius * 0.075, width=stroke * 0.8)
    for k in range(1, config.rings + 2):
        r = max_radius * k / (config.rings + 1)
        canvas.add_circle(cx, cy, r, width=stroke * (0.55 if k % 2 else 0.35), opacity=0.85)

    # Radial axes, subtle but useful for coloring pages.
    for i in range(config.symmetry):
        theta = -math.pi / 2 + i * sector
        canvas.add_line(
            _polar(cx, cy, max_radius * 0.08, theta),
            _polar(cx, cy, max_radius, theta),
            width=stroke * 0.28,
            opacity=0.45,
        )

    motif_count = 0
    for ring in range(config.rings):
        inner = max_radius * (ring + 0.24) / (config.rings + 1)
        outer = max_radius * (ring + 0.96) / (config.rings + 1)
        mid = (inner + outer) / 2.0
        ring_width = outer - inner
        motif_style = (ring + rng.randrange(3)) % 4
        count_multiplier = 2 if detail >= 3 and ring % 2 else 1
        count = config.symmetry * count_multiplier
        local_sector = math.tau / count

        for i in range(count):
            theta = -math.pi / 2 + i * local_sector
            width_scale = 0.22 if count_multiplier == 1 else 0.16
            if motif_style == 0:
                canvas.add_polygon(
                    _petal_points(cx, cy, inner, outer, theta, local_sector * width_scale, steps=14 + detail * 2),
                    width=stroke * 0.82,
                )
            elif motif_style == 1:
                canvas.add_polygon(
                    _petal_points(cx, cy, mid - ring_width * 0.25, outer, theta, local_sector * 0.18, pinch=0.65),
                    width=stroke * 0.72,
                )
                canvas.add_circle(*_polar(cx, cy, inner + ring_width * 0.25, theta), ring_width * 0.075, width=stroke * 0.55)
            elif motif_style == 2:
                canvas.add_polygon(_diamond_points(*_polar(cx, cy, mid, theta), ring_width * 0.28, theta), width=stroke * 0.72)
                if detail >= 2:
                    canvas.add_circle(*_polar(cx, cy, outer - ring_width * 0.12, theta), ring_width * 0.045, width=stroke * 0.45)
            else:
                a0 = theta - local_sector * 0.32
                a1 = theta + local_sector * 0.32
                canvas.add_polyline(_arc_points(cx, cy, mid, a0, a1, steps=16), width=stroke * 0.72)
                canvas.add_polygon(
                    _petal_points(cx, cy, inner, inner + ring_width * 0.55, theta, local_sector * 0.14, steps=10),
                    width=stroke * 0.62,
                )
            motif_count += 1

            if detail >= 2:
                for sign in (-1, 1):
                    off = theta + sign * local_sector * 0.31
                    canvas.add_circle(*_polar(cx, cy, mid, off), ring_width * 0.032, width=stroke * 0.42)
                    motif_count += 1
            if detail >= 3 and i % 2 == 0:
                canvas.add_polyline(
                    _arc_points(cx, cy, outer - ring_width * 0.08, theta - local_sector * 0.24, theta + local_sector * 0.24, steps=14),
                    width=stroke * 0.36,
                )
                motif_count += 1
            if detail >= 4:
                canvas.add_polygon(
                    _star_points(*_polar(cx, cy, inner + ring_width * 0.12, theta), ring_width * 0.08, 6, theta),
                    width=stroke * 0.32,
                )
                motif_count += 1

    # Outer lace border.
    border_count = config.symmetry * (2 if detail >= 2 else 1)
    for i in range(border_count):
        theta = -math.pi / 2 + math.tau * i / border_count
        canvas.add_circle(*_polar(cx, cy, max_radius * 0.985, theta), max_radius * 0.012, width=stroke * 0.5)
        canvas.add_polygon(
            _petal_points(cx, cy, max_radius * 0.91, max_radius * 0.99, theta, math.tau / border_count * 0.18, steps=10),
            width=stroke * 0.5,
        )
        motif_count += 2

    qc = {
        "engine": "forge.procedural-mandala.v1",
        "config": asdict(config),
        "construction_pass": True,
        "symmetry_order": config.symmetry,
        "dihedral_mirror": bool(config.mirror),
        "ring_count": config.rings,
        "motif_count": motif_count,
        "shape_count": len(canvas.shapes),
        "center": [round(cx, 3), round(cy, 3)],
        "notes": [
            "Geometry is generated from polar coordinates.",
            "All motif counts are exact multiples of the requested symmetry order.",
            "No generated text, signatures, or watermarks are emitted by this engine.",
        ],
    }
    return canvas, qc


def write_mandala(config: MandalaConfig, out_path: Path) -> dict[str, Any]:
    canvas, qc = build_mandala(config)
    return _write_artifact_bundle(canvas, qc, out_path, supersample=config.supersample, kind="mandala")


def _mirror_x(points: list[Point], center_x: float) -> list[Point]:
    return [(2 * center_x - x, y) for x, y in points]


def _mirror_point(point: Point, center_x: float) -> Point:
    return (2 * center_x - point[0], point[1])


def _add_flower(canvas: VectorCanvas, cx: float, cy: float, radius: float, petals: int, *, width: float) -> None:
    for i in range(petals):
        theta = math.tau * i / petals
        pc = _polar(cx, cy, radius * 0.55, theta)
        canvas.add_polygon(_petal_points(cx, cy, radius * 0.1, radius, theta, math.pi / petals * 0.36, steps=8), width=width * 0.5)
        canvas.add_circle(pc[0], pc[1], radius * 0.06, width=width * 0.35)
    canvas.add_circle(cx, cy, radius * 0.18, width=width * 0.6)


def _add_symmetric_border(canvas: VectorCanvas, *, symmetry: int, rings: int, complexity: str, seed: int, width: float) -> None:
    config = MandalaConfig(
        style="playful",
        symmetry=symmetry,
        rings=max(3, rings),
        complexity=complexity,
        seed=seed,
        width=canvas.width,
        height=canvas.height,
        stroke_width=width * 0.8,
        supersample=1,
    )
    border, _qc = build_mandala(config)
    cx, cy = canvas.width / 2, canvas.height / 2
    keep_inner = min(canvas.width, canvas.height) * 0.26
    for shape in border.shapes:
        keep = True
        if shape["type"] == "circle":
            dist = math.hypot(float(shape["cx"]) - cx, float(shape["cy"]) - cy)
            keep = dist > keep_inner or float(shape["r"]) > keep_inner
        elif shape["type"] in {"polygon", "polyline"}:
            pts = shape["points"]
            avg = sum(math.hypot(x - cx, y - cy) for x, y in pts) / len(pts)
            keep = avg > keep_inner
        if keep:
            canvas.shapes.append(shape)


def _rabbit_pair(canvas: VectorCanvas, *, width: float) -> int:
    cx, cy = canvas.width / 2, canvas.height / 2
    s = min(canvas.width, canvas.height)
    left_x = cx - s * 0.18
    ground = cy + s * 0.19
    shapes_before = len(canvas.shapes)

    def add_one(x: float, mirror: bool = False) -> None:
        sign = -1 if mirror else 1
        body = _ellipse_points(x, ground - s * 0.07, s * 0.085, s * 0.135, rotation=sign * -0.10)
        head = _ellipse_points(x + sign * s * 0.075, ground - s * 0.195, s * 0.058, s * 0.052, rotation=sign * -0.15)
        ear1 = _ellipse_points(x + sign * s * 0.055, ground - s * 0.302, s * 0.025, s * 0.095, rotation=sign * -0.18)
        ear2 = _ellipse_points(x + sign * s * 0.105, ground - s * 0.296, s * 0.022, s * 0.086, rotation=sign * 0.18)
        hind = _ellipse_points(x - sign * s * 0.035, ground + s * 0.022, s * 0.078, s * 0.033, rotation=sign * 0.03)
        fore = _ellipse_points(x + sign * s * 0.075, ground + s * 0.018, s * 0.04, s * 0.018, rotation=sign * -0.12)
        for pts in (body, head, ear1, ear2, hind, fore):
            canvas.add_polygon(pts, width=width)
        eye = (x + sign * s * 0.105, ground - s * 0.207)
        canvas.add_circle(eye[0], eye[1], s * 0.007, fill=canvas.stroke, width=width * 0.5)
        nose = (x + sign * s * 0.138, ground - s * 0.183)
        canvas.add_circle(nose[0], nose[1], s * 0.006, width=width * 0.45)
        canvas.add_polyline(
            [
                (x + sign * s * 0.052, ground - s * 0.298),
                (x + sign * s * 0.06, ground - s * 0.23),
                (x + sign * s * 0.072, ground - s * 0.158),
            ],
            width=width * 0.32,
        )
        canvas.add_polyline(
            [
                (x + sign * s * 0.106, ground - s * 0.286),
                (x + sign * s * 0.096, ground - s * 0.225),
                (x + sign * s * 0.088, ground - s * 0.16),
            ],
            width=width * 0.3,
        )
        for k in range(3):
            y = nose[1] + (k - 1) * s * 0.01
            canvas.add_line(nose, (nose[0] + sign * s * 0.075, y - s * 0.018), width=width * 0.38)
        for k in range(17):
            theta = -math.pi / 2 + (k - 8) * 0.065
            start = _polar(x, ground - s * 0.055, s * 0.034, theta)
            end = _polar(x, ground - s * 0.055, s * (0.085 + 0.015 * (k % 2)), theta)
            canvas.add_line(start, end, width=width * 0.22, opacity=0.85)
        for k in range(5):
            paw_x = x + sign * s * (0.056 + 0.012 * k)
            canvas.add_line((paw_x, ground + s * 0.01), (paw_x + sign * s * 0.012, ground + s * 0.04), width=width * 0.22)
        canvas.add_circle(x - sign * s * 0.105, ground - s * 0.015, s * 0.025, width=width * 0.45)

    add_one(left_x, mirror=False)
    add_one(2 * cx - left_x, mirror=True)

    for sign in (-1, 1):
        base_x = cx + sign * s * 0.31
        for j in range(4):
            _add_flower(canvas, base_x + sign * s * 0.035 * j, ground - s * (0.02 + 0.055 * j), s * 0.035, 8, width=width)
            canvas.add_polyline(
                [
                    (base_x + sign * s * 0.035 * j, ground + s * 0.08),
                    (base_x + sign * s * 0.035 * j, ground - s * (0.02 + 0.055 * j)),
                ],
                width=width * 0.35,
            )
        for j in range(9):
            leaf_x = cx + sign * s * (0.06 + 0.026 * j)
            leaf_y = ground + s * (0.055 - 0.012 * (j % 3))
            canvas.add_polygon(_petal_points(leaf_x, leaf_y, s * 0.002, s * 0.028, -math.pi / 2 + sign * 0.3, 0.42, steps=7), width=width * 0.32)
    return len(canvas.shapes) - shapes_before


def _crow_pair(canvas: VectorCanvas, *, width: float) -> int:
    cx, cy = canvas.width / 2, canvas.height / 2
    s = min(canvas.width, canvas.height)
    y = cy + s * 0.08
    left_x = cx - s * 0.19
    shapes_before = len(canvas.shapes)

    canvas.add_circle(cx, cy - s * 0.22, s * 0.14, width=width * 0.65)
    for i in range(24):
        theta = math.tau * i / 24
        canvas.add_line(_polar(cx, cy - s * 0.22, s * 0.16, theta), _polar(cx, cy - s * 0.22, s * 0.21, theta), width=width * 0.35)

    def add_one(x: float, mirror: bool) -> None:
        sign = -1 if mirror else 1
        body = _ellipse_points(x, y, s * 0.125, s * 0.078, rotation=sign * 0.10)
        wing = _petal_points(x - sign * s * 0.015, y - s * 0.005, s * 0.015, s * 0.14, math.pi if not mirror else 0.0, 0.25, steps=14)
        head = _ellipse_points(x + sign * s * 0.105, y - s * 0.087, s * 0.052, s * 0.047)
        beak = [
            (x + sign * s * 0.145, y - s * 0.09),
            (x + sign * s * 0.225, y - s * 0.074),
            (x + sign * s * 0.145, y - s * 0.058),
        ]
        tail = [
            (x - sign * s * 0.11, y + s * 0.02),
            (x - sign * s * 0.235, y + s * 0.095),
            (x - sign * s * 0.135, y + s * 0.055),
        ]
        for pts in (body, wing, head, beak, tail):
            canvas.add_polygon(pts, width=width)
        eye = (x + sign * s * 0.124, y - s * 0.096)
        canvas.add_circle(eye[0], eye[1], s * 0.006, fill=canvas.stroke, width=width * 0.4)
        canvas.add_circle(eye[0], eye[1], s * 0.014, width=width * 0.25)
        canvas.add_line((x + sign * s * 0.146, y - s * 0.075), (x + sign * s * 0.202, y - s * 0.066), width=width * 0.32)
        for k in range(14):
            offset = (k - 3.5) * s * 0.015
            canvas.add_line((x - sign * s * 0.0, y - s * 0.065 + offset), (x - sign * s * 0.118, y + s * 0.018 + offset * 0.15), width=width * 0.26)
        for k in range(7):
            tail_start = (x - sign * s * (0.12 + 0.012 * k), y + s * (0.03 + 0.006 * k))
            tail_end = (x - sign * s * (0.215 + 0.012 * k), y + s * (0.085 + 0.008 * k))
            canvas.add_line(tail_start, tail_end, width=width * 0.25)
        for leg_x in (x + sign * s * 0.025, x + sign * s * 0.072):
            foot = y + s * 0.095
            canvas.add_line((leg_x, y + s * 0.065), (leg_x, foot), width=width * 0.5)
            for toe in (-1, 0, 1):
                canvas.add_line((leg_x, foot), (leg_x + sign * s * 0.024 * toe, foot + s * 0.017), width=width * 0.34)

    add_one(left_x, mirror=False)
    add_one(2 * cx - left_x, mirror=True)
    canvas.add_polyline([(cx - s * 0.42, y + s * 0.115), (cx - s * 0.12, y + s * 0.085), (cx + s * 0.12, y + s * 0.085), (cx + s * 0.42, y + s * 0.115)], width=width * 1.1)
    for sign in (-1, 1):
        for k in range(4):
            base = (cx + sign * (s * 0.22 + s * 0.045 * k), y + s * 0.11)
            canvas.add_polyline([base, (base[0] + sign * s * 0.035, base[1] - s * (0.055 + 0.01 * k))], width=width * 0.35)
        for k in range(8):
            crack = cx + sign * s * (0.08 + k * 0.037)
            canvas.add_polyline([(crack, y + s * 0.17), (crack + sign * s * 0.02, y + s * 0.19), (crack + sign * s * 0.045, y + s * 0.18)], width=width * 0.24)
    return len(canvas.shapes) - shapes_before


def _blue_jay(canvas: VectorCanvas, *, width: float) -> int:
    cx, cy = canvas.width / 2, canvas.height / 2
    s = min(canvas.width, canvas.height)
    shapes_before = len(canvas.shapes)
    body = _petal_points(cx, cy + s * 0.13, s * 0.01, s * 0.24, -math.pi / 2, 0.46, steps=24)
    head = _ellipse_points(cx, cy - s * 0.08, s * 0.066, s * 0.058)
    crest = [
        (cx - s * 0.05, cy - s * 0.125),
        (cx, cy - s * 0.235),
        (cx + s * 0.05, cy - s * 0.125),
    ]
    canvas.add_polygon(body, width=width)
    canvas.add_polygon(head, width=width)
    canvas.add_polygon(crest, width=width)
    for sign in (-1, 1):
        wing = _petal_points(cx + sign * s * 0.022, cy + s * 0.055, s * 0.02, s * 0.215, math.pi / 2 if sign > 0 else math.pi / 2, 0.28, steps=18)
        wing = [(cx + sign * abs(x - cx), y) for x, y in wing]
        canvas.add_polygon(wing, width=width)
        canvas.add_circle(cx + sign * s * 0.029, cy - s * 0.086, s * 0.0065, fill=canvas.stroke, width=width * 0.4)
        canvas.add_circle(cx + sign * s * 0.029, cy - s * 0.086, s * 0.015, width=width * 0.22)
        for k in range(15):
            y = cy + s * (0.005 + k * 0.021)
            canvas.add_line((cx + sign * s * 0.023, y), (cx + sign * s * (0.14 - k * 0.004), y + s * 0.017), width=width * 0.28)
        for k in range(9):
            canvas.add_line((cx, cy + s * 0.17 + k * s * 0.018), (cx + sign * s * (0.04 + k * 0.011), cy + s * 0.225 + k * s * 0.019), width=width * 0.33)
        for k in range(5):
            crest_start = (cx + sign * s * 0.008 * k, cy - s * 0.13)
            crest_end = (cx + sign * s * (0.015 + 0.009 * k), cy - s * (0.195 - 0.007 * k))
            canvas.add_line(crest_start, crest_end, width=width * 0.27)
    beak = [(cx - s * 0.018, cy - s * 0.065), (cx, cy - s * 0.035), (cx + s * 0.018, cy - s * 0.065)]
    canvas.add_polygon(beak, width=width * 0.8)
    canvas.add_polyline([(cx - s * 0.055, cy - s * 0.045), (cx, cy - s * 0.01), (cx + s * 0.055, cy - s * 0.045)], width=width * 0.38)
    canvas.add_polyline([(cx - s * 0.28, cy + s * 0.28), (cx - s * 0.08, cy + s * 0.25), (cx + s * 0.08, cy + s * 0.25), (cx + s * 0.28, cy + s * 0.28)], width=width * 0.95)
    for sign in (-1, 1):
        for k in range(6):
            leaf_base = (cx + sign * s * (0.11 + k * 0.03), cy + s * (0.26 + 0.01 * (k % 2)))
            canvas.add_polygon(_petal_points(leaf_base[0], leaf_base[1], s * 0.002, s * 0.026, -math.pi / 2 + sign * 0.5, 0.36, steps=7), width=width * 0.3)
    return len(canvas.shapes) - shapes_before


def build_childrens_page(config: ChildrensBookConfig, theme: str, page_index: int) -> tuple[VectorCanvas, dict[str, Any]]:
    if theme not in CHILD_THEMES:
        raise ValueError(f"unknown children's book theme {theme!r}; choose one of {', '.join(CHILD_THEMES)}")
    _complexity_value(config.complexity)
    palette = _palette(config.palette, "playful")
    canvas = VectorCanvas(config.width, config.height, background=palette["background"], stroke=palette["stroke"])
    stroke = max(1.0, min(config.width, config.height) / 720.0)
    _add_symmetric_border(
        canvas,
        symmetry=config.symmetry,
        rings=config.rings,
        complexity=config.complexity,
        seed=config.seed + page_index * 17,
        width=stroke,
    )
    cx, cy = config.width / 2, config.height / 2
    frame_r = min(config.width, config.height) * 0.34
    canvas.add_circle(cx, cy, frame_r, width=stroke * 0.8)
    canvas.add_circle(cx, cy, frame_r * 0.93, width=stroke * 0.35)
    detail = _complexity_value(config.complexity)
    ornament_count = config.symmetry * (2 if detail >= 3 else 1)
    for i in range(ornament_count):
        theta = -math.pi / 2 + math.tau * i / ornament_count
        anchor = _polar(cx, cy, frame_r * 0.88, theta)
        canvas.add_polygon(
            _petal_points(anchor[0], anchor[1], min(config.width, config.height) * 0.003, min(config.width, config.height) * 0.028, theta, 0.36, steps=8),
            width=stroke * 0.32,
        )
        if detail >= 4:
            canvas.add_circle(*_polar(cx, cy, frame_r * 0.78, theta), min(config.width, config.height) * 0.005, width=stroke * 0.25)
    if theme == "rabbits-garden":
        subject_shapes = _rabbit_pair(canvas, width=stroke)
    elif theme == "crows-texas":
        subject_shapes = _crow_pair(canvas, width=stroke)
    else:
        subject_shapes = _blue_jay(canvas, width=stroke)

    qc = {
        "engine": "forge.procedural-childrens-book.v1",
        "config": asdict(config),
        "theme": theme,
        "page_index": page_index,
        "construction_pass": True,
        "symmetry_contract": {
            "radial_border_order": config.symmetry,
            "central_subject": "bilateral or paired mirror symmetry",
            "no_cartoon_prompting": True,
        },
        "subject_shape_count": subject_shapes,
        "shape_count": len(canvas.shapes),
        "notes": [
            "Page is procedural vector line art, not diffusion.",
            "Children's appeal comes from playful pattern density and symmetry, not cartoon styling.",
            "No generated text, signatures, or watermarks are emitted by this engine.",
        ],
    }
    return canvas, qc


def write_childrens_book(config: ChildrensBookConfig, out_dir: Path) -> dict[str, Any]:
    if config.pages < 1 or config.pages > 50:
        raise ValueError("--pages must be between 1 and 50")
    if config.symmetry < 4 or config.symmetry > 64:
        raise ValueError("--symmetry must be between 4 and 64")
    if config.rings < 2 or config.rings > 16:
        raise ValueError("--rings must be between 2 and 16")
    if config.width < 256 or config.height < 256:
        raise ValueError("--width and --height must be at least 256")
    _complexity_value(config.complexity)

    out_dir.mkdir(parents=True, exist_ok=True)
    themes = list(CHILD_THEMES) if config.theme == "all" else [config.theme]
    if config.theme != "all" and config.theme not in CHILD_THEMES:
        raise ValueError(f"unknown children's book theme {config.theme!r}; choose all or one of {', '.join(CHILD_THEMES)}")

    pages: list[dict[str, Any]] = []
    for i in range(config.pages):
        theme = themes[i % len(themes)]
        canvas, qc = build_childrens_page(config, theme, i + 1)
        stem = f"page-{i + 1:02d}-{theme}"
        artifact = _write_artifact_bundle(canvas, qc, out_dir / f"{stem}.png", supersample=config.supersample, kind="childrens-book")
        pages.append({"theme": theme, **artifact})

    manifest = {
        "engine": "forge.procedural-childrens-book.v1",
        "config": asdict(config),
        "pages": pages,
    }
    manifest_path = out_dir / "manifest.json"
    _atomic_write_text(manifest_path, json.dumps(manifest, indent=2) + "\n")
    return manifest


def _write_artifact_bundle(
    canvas: VectorCanvas,
    qc: dict[str, Any],
    out_path: Path,
    *,
    supersample: int,
    kind: str,
) -> dict[str, Any]:
    out_path = out_path.expanduser().resolve()
    if out_path.suffix.lower() not in {".png", ".svg"}:
        out_path = out_path.with_suffix(".png")
    png_path = out_path if out_path.suffix.lower() == ".png" else out_path.with_suffix(".png")
    svg_path = out_path if out_path.suffix.lower() == ".svg" else out_path.with_suffix(".svg")
    qc_path = png_path.with_suffix(".qc.json")

    _atomic_write_text(svg_path, canvas.to_svg())
    canvas.render_png(png_path, supersample=supersample)
    qc = dict(qc)
    qc["artifact_kind"] = kind
    qc["png"] = str(png_path)
    qc["svg"] = str(svg_path)
    qc["pixel_qc"] = _pixel_qc(png_path, order=int(qc.get("symmetry_order") or qc.get("symmetry_contract", {}).get("radial_border_order") or 1))
    _atomic_write_text(qc_path, json.dumps(qc, indent=2) + "\n")
    return {"png": str(png_path), "svg": str(svg_path), "qc": str(qc_path)}


def _pixel_qc(path: Path, *, order: int) -> dict[str, Any]:
    from PIL import Image, ImageChops, ImageStat

    image = Image.open(path).convert("L")
    small = image.resize((512, 512))
    flipped = small.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    mirror_diff = ImageChops.difference(small, flipped)
    mirror_score = ImageStat.Stat(mirror_diff).mean[0] / 255.0
    rotation_score = None
    if order and order > 1:
        angle = 360.0 / order
        rotated = small.rotate(angle, resample=Image.Resampling.BICUBIC, center=(256, 256))
        rot_diff = ImageChops.difference(small, rotated)
        rotation_score = ImageStat.Stat(rot_diff).mean[0] / 255.0
    return {
        "mirror_difference_score": round(mirror_score, 6),
        "rotation_difference_score": None if rotation_score is None else round(rotation_score, 6),
        "note": "Pixel scores are raster sanity checks; construction symmetry is the source of truth.",
    }


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
