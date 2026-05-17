"""Shared infrastructure for Forge style engines.

A style engine is a domain expert. It owns:
  * grouped sub-configs (Cinematography + Subject + Atmosphere + Material, NOT a
    flat bag of knobs)
  * enum banks where each value carries metadata (description, implies,
    conflicts_with, masters) — NOT bare strings
  * domain invariants (validated rules, NOT just lookup tables)
  * 3-5 named master citations as the genre fingerprint
  * a `build(config) → Directive` that emits a dense FLUX prompt + negatives +
    palette + runtime + audit trail
  * a `to_synthetic_preset()` adapter so the directive can also feed the
    existing JSON-preset flux_generate path without modification

What's deliberately NOT here: any geometry helpers, palette interpolation, or
diffusion/rendering. That's domain code; each engine owns it if it needs it.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field, fields, is_dataclass
from typing import Any, Callable, ClassVar


# ────────────────────────────────────────────────────────────────────────────
# EnumValue + EnumBank — metadata-bearing enumerated knobs.
# ────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EnumValue:
    """One value in an enumerated knob.

    `description` is the expansion text (~30-50 tokens) baked into the FLUX
    prompt when this value is chosen.
    `implies` lists `knob=value` strings that other knobs should match when
    this is chosen — checked as soft warnings, not hard fails.
    `conflicts_with` lists `knob=value` strings that *cannot* coexist with
    this one — hard fail.
    `masters` names canonical works that exemplify this value — used in the
    final assembled prompt as a stylistic fingerprint.
    """
    key: str
    description: str
    implies: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()
    masters: tuple[str, ...] = ()


class EnumBank:
    """Typed enumeration with metadata + validation."""

    def __init__(self, name: str, values: list[EnumValue]):
        self.name = name
        self.values: dict[str, EnumValue] = {v.key: v for v in values}
        if len(self.values) != len(values):
            dupes = [v.key for v in values if list(self._key_freq(values)).count(v.key) > 1]
            raise ValueError(f"duplicate keys in EnumBank {name}: {dupes}")

    @staticmethod
    def _key_freq(values: list[EnumValue]) -> list[str]:
        return [v.key for v in values]

    def validate(self, key: str) -> EnumValue:
        if key not in self.values:
            raise ValueError(
                f"unknown {self.name}={key!r}; choose one of "
                f"{', '.join(sorted(self.values))}"
            )
        return self.values[key]

    def keys(self) -> list[str]:
        return sorted(self.values)

    def __getitem__(self, key: str) -> EnumValue:
        return self.validate(key)

    def __contains__(self, key: str) -> bool:
        return key in self.values

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "values": {
                k: {
                    "description": v.description,
                    "implies": list(v.implies),
                    "conflicts_with": list(v.conflicts_with),
                    "masters": list(v.masters),
                }
                for k, v in self.values.items()
            },
        }


# ────────────────────────────────────────────────────────────────────────────
# Directive — the output package of a build().
# ────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Directive:
    """Everything FLUX needs + everything the brand layer needs.

    `positive` is the full assembled prompt; `flux_generate` can use it as-is.
    `negatives` is the engine-specific negative list; the global master primer
    adds its own at render time so this list stays domain-focused.
    `palette_60_30_10` and `runtime` mirror the JSON preset shape so the
    `to_synthetic_preset()` adapter can shim the directive into the existing
    preset path with no changes downstream.
    `audit` records which knob expanded into which phrase — reproducible and
    inspectable, like mandala_engine.py's QC manifest.
    """
    engine: str
    positive: str
    negatives: tuple[str, ...]
    palette_60_30_10: dict[str, dict[str, str]]
    runtime: dict[str, Any]
    seed: int
    audit: dict[str, Any]
    config: dict[str, Any]
    masters: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "positive": self.positive,
            "negatives": list(self.negatives),
            "palette_60_30_10": self.palette_60_30_10,
            "runtime": self.runtime,
            "seed": self.seed,
            "audit": self.audit,
            "config": self.config,
            "masters": list(self.masters),
        }

    def to_synthetic_preset(self) -> dict[str, Any]:
        """Adapt the directive into a JSON-preset-compatible dict so the existing
        flux_generate path (which reads `flux.positive_prefix`, `flux.negatives`,
        etc.) consumes it without modification.

        The full `positive` ends up in `positive_prefix` (one block); the engine
        is its own prefix+suffix. The master primer still merges in downstream.
        """
        return {
            "id": f"engine:{self.engine}",
            "name": self.engine.title(),
            "description": f"Synthetic preset emitted by {self.engine} engine.",
            "use_for": "engine-driven generation",
            "typography": {
                "display_family": "Impact",
                "body_family": "Helvetica",
                "weights": ["bold"],
                "scale": {"title_max_chars": 24, "title_px": 132, "sub_px": 38, "caption_px": 22},
            },
            "palette_60_30_10": self.palette_60_30_10,
            "composition": {
                "thumbnail": {
                    "headline_anchor": "bottom-center",
                    "headline_color": "#FFFFFF",
                    "headline_outline": "#000000",
                    "headline_outline_px": 5,
                    "accent_bar_role": "accent",
                    "accent_bar_width_px": 300,
                    "accent_bar_height_px": 6,
                    "dim_band": {"opacity": 0.65, "vertical_start": 0.66},
                },
                "video_overlay": {
                    "hook_anchor": "center", "moment_anchor": "bottom-left",
                    "moment_accent_left_bar_px": 10, "cta_anchor": "bottom-right",
                },
            },
            "flux": {
                "positive_prefix": self.positive,
                "positive_suffix": "",
                "negatives": list(self.negatives),
                "guidance": self.runtime.get("guidance", 4.0),
                "steps": self.runtime.get("steps", 25),
                "model": self.runtime.get("model", "dev"),
            },
            "prompt_rules": {"always_add": []},
        }


# ────────────────────────────────────────────────────────────────────────────
# Engine base class.
# ────────────────────────────────────────────────────────────────────────────


class Engine(ABC):
    """Base class for a domain-expert style engine.

    Subclasses define:
      * `name` — short id used in the registry and CLI
      * `config_cls` — frozen dataclass type (often a nested composition of
        Cinematography/Subject/Atmosphere sub-configs)
      * `masters` — 3-5 lines of "Artist — Work — Technique" citations that
        give the engine its visual fingerprint; baked into the final prompt
      * `palette_60_30_10`, `default_runtime`
      * a `build(config) → Directive` method that:
        - validates every enum knob
        - runs domain invariants (raise ValueError on violation)
        - composes the dense prompt
        - returns a fully-populated Directive
    """
    name: ClassVar[str]
    config_cls: ClassVar[type]
    masters: ClassVar[tuple[str, ...]]
    palette_60_30_10: ClassVar[dict[str, dict[str, str]]]
    default_runtime: ClassVar[dict[str, Any]]
    engine_negatives: ClassVar[tuple[str, ...]] = ()

    @classmethod
    @abstractmethod
    def build(cls, config: Any) -> Directive: ...

    @classmethod
    def describe(cls) -> dict[str, Any]:
        """Return the engine's vocabulary so the CLI/wizard can render
        --help-style discovery output."""
        cfg = cls.config_cls
        return {
            "name": cls.name,
            "config_schema": _describe_dataclass(cfg),
            "vocabulary": cls._gather_vocab(),
            "masters": list(cls.masters),
            "engine_negatives": list(cls.engine_negatives),
            "palette_60_30_10": cls.palette_60_30_10,
            "default_runtime": cls.default_runtime,
        }

    @classmethod
    def _gather_vocab(cls) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for attr in dir(cls):
            obj = getattr(cls, attr, None)
            if isinstance(obj, EnumBank):
                out[obj.name] = obj.describe()["values"]
        return out


def _describe_dataclass(cls: type) -> dict[str, Any]:
    """Recursively describe a (possibly-nested) dataclass for the CLI."""
    if not is_dataclass(cls):
        return {"type": cls.__name__}
    schema: dict[str, Any] = {}
    for f in fields(cls):
        if is_dataclass(f.type):
            schema[f.name] = {"type": "group", "schema": _describe_dataclass(f.type)}
        else:
            t = getattr(f.type, "__name__", str(f.type))
            schema[f.name] = {"type": t, "default": _format_default(f)}
    return schema


def _format_default(f) -> Any:
    from dataclasses import MISSING, is_dataclass
    raw: Any
    if f.default is not MISSING:
        raw = f.default
    elif f.default_factory is not MISSING:  # type: ignore[misc]
        try:
            raw = f.default_factory()  # type: ignore[misc]
        except Exception:
            return "<factory>"
    else:
        return "<required>"
    # Convert dataclass instances → dict so they're JSON-serializable in describe()
    if is_dataclass(raw):
        return asdict(raw)
    return raw


# ────────────────────────────────────────────────────────────────────────────
# Subject normalization — shared utility.
# ────────────────────────────────────────────────────────────────────────────


def normalize_subject(subject: str, *, max_chars: int = 220) -> str:
    """Trim and bound the free-text subject so it can't blow the prompt budget."""
    s = re.sub(r"\s+", " ", subject or "").strip()
    if not s:
        raise ValueError("subject is required")
    return s[:max_chars]


# ────────────────────────────────────────────────────────────────────────────
# Invariant helpers — small reusable validators.
# ────────────────────────────────────────────────────────────────────────────


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def assemble_masters_line(masters: tuple[str, ...]) -> str:
    """Render the master-citations block. Engines call this in their build()."""
    if not masters:
        return ""
    body = "; ".join(masters)
    return f"FINGERPRINT — render in the visual register of: {body}."
