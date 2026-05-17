"""Forge style engines — four domain-expert FLUX prompt builders.

Each engine owns ONE visual genre in depth: grouped sub-configs, enum banks
with metadata (description + implies + conflicts_with + masters), encoded
domain invariants, and 3-5 master citations baked into the final prompt as
the genre's stylistic fingerprint.

This is the OPPOSITE of "one big config dict with random knobs". Each engine
thinks like its genre.

Registry:
    noir-cinema           NoirCinematographyEngine
    wildlife-photo        WildlifePhotorealismEngine
    impressionist         ImpressionistPaintingEngine
    indian-classical      IndianClassicalEngine

Public surface:
    list_engines() → list[str]
    get_engine(name) → Engine class
    describe_engine(name) → dict
    build(name, **kwargs) → Directive
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from typing import Any, ClassVar

from _engine_base import (
    Directive, Engine, EnumBank, EnumValue,
    assemble_masters_line, normalize_subject, require,
)


# ════════════════════════════════════════════════════════════════════════════
# NoirCinematographyEngine — true cinematography model, not "dark images"
# ════════════════════════════════════════════════════════════════════════════


_NOIR_SUBGENRE = EnumBank("subgenre", [
    EnumValue(
        "classic-1940s",
        "Classic 1940s-50s American film noir: period wardrobe (fedora, trench coat, "
        "pillbox hat, pencil skirts), period cars (1948 Lincoln Continental, "
        "Packard, DeSoto), bakelite telephones, single-bulb practical fixtures, "
        "monochrome chemical-silver photographic look, hard high-contrast lighting.",
        masters=("John Alton, The Big Combo (1955)", "Wilder, Double Indemnity (1944)", "Welles, The Third Man (1949)"),
    ),
    EnumValue(
        "neo-noir-1970s",
        "1970s neo-noir: naturalistic Eastman color stock with desaturated palette, "
        "Polaroid-warm but never bright, period cars (Lincoln Mark IV, Chevy Nova), "
        "polyester wide-collar shirts, ambient practical lighting, more grain than "
        "the 1940s, less dramatic contrast but more dread.",
        masters=("Polanski, Chinatown (1974)", "Altman, The Long Goodbye (1973)", "Schrader, Taxi Driver (1976)"),
    ),
    EnumValue(
        "nordic-modern",
        "Contemporary Nordic noir: cold blue-cyan grading, overcast diffuse light, "
        "modern-but-restrained wardrobe (technical fabrics, dark wool), Scandinavian "
        "minimalist interiors (pale wood, concrete, glass), low natural daylight from "
        "high latitudes, ambient depression as visual character.",
        masters=("Nicolaj Arcel, The Girl with the Dragon Tattoo (2009)", "The Bridge series", "Tomas Alfredson, Let the Right One In (2008)"),
    ),
    EnumValue(
        "tech-noir",
        "Blade-Runner tech-noir: neon practical sources in mid-aughts cyberpunk palette "
        "(magenta + cyan + sodium-yellow + deep navy), constant rain on neon-lit "
        "pavement, technological props (transparent OLED displays, retro-future "
        "interfaces), volumetric light shafts through urban smog.",
        masters=("Ridley Scott, Blade Runner (1982)", "Denis Villeneuve, Blade Runner 2049 (2017)", "Mamoru Oshii, Ghost in the Shell (1995)"),
    ),
    EnumValue(
        "pulp-comic",
        "Pure ink-and-paper comic noir: hand-drawn linework over flat ink fills, "
        "monochrome with optional ONE saturated color element (Sin City's blood-red, "
        "Mignola's lapis-blue), heavy black masses occupying 60%+ of the frame, "
        "weathered surface stipple, NOT photo-realistic, painted feel.",
        masters=("Frank Miller, Sin City vol.1 (1991)", "Mike Mignola, Hellboy", "Sean Murphy, White Knight"),
    ),
])

_NOIR_KEY_LIGHT = EnumBank("key_light", [
    EnumValue(
        "rim-only",
        "Single hard rim light from one side (left OR right, never both), opposite half "
        "of the subject in deep ink-shadow, the silhouette contour traced as a bright "
        "edge against darkness. Fill ratio approaches infinity (no fill light at all).",
        masters=("Alton's signature The Big Combo lighting",),
    ),
    EnumValue(
        "venetian-blind",
        "Horizontal slats of light from a Venetian-blind source cast diagonally across "
        "subject's face and torso in alternating bands of bright and shadow. The "
        "shadow lines are the signature of 1940s noir — they MUST be sharp-edged "
        "diagonals, never parallel to the frame.",
        masters=("Welles, The Stranger (1946)", "Tourneur, Out of the Past (1947)"),
        conflicts_with=("subgenre=tech-noir",),
    ),
    EnumValue(
        "bare-bulb",
        "Single bare incandescent bulb in frame or just out of frame, the light source "
        "itself visible or implied, hard shadow falling away from it, the bulb a "
        "diegetic source rather than a movie-light. The light is yellow-warm, the "
        "shadows take a cool cast by contrast.",
        masters=("Alton, T-Men interrogation rooms", "Polanski, Chinatown morgue scene"),
    ),
    EnumValue(
        "neon-practical",
        "Neon sign in or adjacent to frame as primary key light, the sign's color "
        "(red, magenta, ice-blue) saturating the subject, rim light from opposite "
        "direction often in complementary color. Visible reflection on wet pavement "
        "or glass. The neon itself appears as a hard shape in the frame.",
        masters=("Blade Runner, the Spinner-on-rooftop scene", "Refn, Drive (2011)"),
        implies=("weather=wet-pavement",),
    ),
    EnumValue(
        "candle-shrine",
        "Cluster of candle-flame practical sources from below frame, warm orange "
        "wash from below casting upward shadows under brow and chin, the rest of "
        "the scene receding to deep umber. Often religious or memorial in context. "
        "Soft falloff because of multiple small sources.",
        masters=("Kubrick, Barry Lyndon (1975) candle scenes",),
    ),
    EnumValue(
        "streetlamp-cone",
        "High-angle sodium-vapor streetlamp cone from above-camera, subject mid-cone, "
        "edge of cone falling off to the periphery. Visible cone shape from "
        "atmospheric particulate. Wet pavement below catches specular reflection of "
        "the lamp.",
        implies=("time_of_day=midnight",),
    ),
    EnumValue(
        "no-fill",
        "Whatever the key source is, the fill ratio is functionally zero — the shadow "
        "side of the subject reads as fully black. This is the hardest noir lighting "
        "and the rarest because it requires careful subject placement.",
        masters=("Alton's interrogation scenes",),
    ),
])

_NOIR_ATMOSPHERIC_MEDIUM = EnumBank("atmospheric_medium", [
    EnumValue(
        "rain",
        "Rain falling diagonally through every light cone, droplets streaking and "
        "catching every rim source. Wet sheen on every horizontal surface. Sound of "
        "rain implied by the visual density of the streaks.",
    ),
    EnumValue(
        "smoke-haze",
        "Cigarette smoke + ambient particulate filling the air, light cones visible as "
        "solid shafts, the air itself a glowing visible medium. Background subjects "
        "softened by intervening haze.",
    ),
    EnumValue(
        "wet-pavement",
        "No active precipitation but every horizontal surface is wet from a recent "
        "rain. Specular reflections of every light source double the visual count of "
        "fixtures. Subject's reflection visible in puddles.",
    ),
    EnumValue(
        "fog-low",
        "Dense low fog at knee-height blanketing the foreground, light cones visible "
        "from above the fog, subjects' lower halves obscured. Reduces middle distance "
        "to silhouettes.",
    ),
    EnumValue(
        "dry-cold",
        "No precipitation, no fog, just dry winter cold with visible breath plumes "
        "from the subject. Clear hard light, no atmospheric softening.",
    ),
    EnumValue(
        "smog-industrial",
        "Industrial sodium-tinted smog hanging low in the frame, the air smelling of "
        "metal and exhaust. Distant lights diffused by intervening haze. Sky never "
        "shows true black — always a sodium-yellow underglow.",
    ),
])

_NOIR_POSE = EnumBank("pose", [
    EnumValue(
        "weight-on-one-foot",
        "Subject stands with weight planted on one foot, opposite shoulder lower, hip "
        "cocked. Hands engaged (lighting a cigarette, on a lapel, in a pocket). "
        "Never both feet square to camera — that's a school-photo pose, not a noir "
        "frame.",
    ),
    EnumValue(
        "leaning-against",
        "Subject leans shoulder or back against a wall, doorframe, lamppost, or car. "
        "Contact surface bears actual weight, posture relaxed-but-not-slack. The "
        "architecture becomes a character.",
    ),
    EnumValue(
        "lighting-cigarette",
        "Subject in the act of lighting a cigarette: cupped hand around match or "
        "lighter, head bowed to the flame, the small light becoming a key source on "
        "the face from below.",
    ),
    EnumValue(
        "back-to-camera",
        "Subject's back to the camera, looking into the depth of the frame. The "
        "figure becomes a silhouette against whatever is in front of them. Identity "
        "deferred — we know them only by posture and outline.",
        conflicts_with=("accent_color=eye-glow",),
    ),
    EnumValue(
        "walking-away",
        "Subject mid-stride, walking away from camera into the receding distance. "
        "Weight transfer visible in shoulder/hip rotation. Frame extends past them "
        "into the depth of the scene.",
    ),
    EnumValue(
        "shoulder-foreground",
        "Out-of-focus shoulder of another figure in the foreground left or right "
        "third, the subject visible past it in the remaining frame. Compositional "
        "OTS without showing the second person's face.",
    ),
])

_NOIR_CAMERA = EnumBank("camera", [
    EnumValue(
        "low-angle",
        "Low-angle camera looking up at the subject from below their eye-line. The "
        "subject becomes tall against the architecture or sky. Conveys stature, "
        "threat, or moral height. Common in Welles + Wong-Kar-Wai.",
    ),
    EnumValue(
        "overhead",
        "High-angle camera looking down on the subject. The figure is diminished "
        "against the geometry of the floor, alley, or stairwell. Conveys "
        "vulnerability or surveillance.",
    ),
    EnumValue(
        "dutch-tilt",
        "Camera tilted off-axis (10-20 degrees) so verticals lean. Conveys "
        "psychological unease without ambient cause. Signature 1940s noir + Carol "
        "Reed's The Third Man.",
        masters=("Reed, The Third Man (1949)",),
    ),
    EnumValue(
        "deep-focus",
        "Lens stopped down to f/8 or beyond, foreground AND background both sharp. "
        "Two planes of action visible simultaneously. Welles + Toland's signature.",
        masters=("Welles + Toland, Citizen Kane (1941)",),
    ),
    EnumValue(
        "medium-eye-level",
        "Standard eye-level medium framing, no rhetorical angle. Subject occupies "
        "central frame at waist-up. Used when the scene's drama is character not "
        "geometry.",
    ),
])

_NOIR_ACCENT = EnumBank("accent_color", [
    EnumValue(
        "blood-red",
        "Single saturated blood-red focal element (a tie, a glove, a wound, a sign) "
        "as the only chromatic punctuation against an otherwise monochrome frame.",
        masters=("Sin City vol.1 — Hartigan's daughter's red dress",),
    ),
    EnumValue(
        "sodium-yellow",
        "Single sodium-yellow focal element (a streetlamp, a phone booth, a match "
        "flame) — warmth in an otherwise cold palette.",
    ),
    EnumValue(
        "ice-blue",
        "Single ice-blue focal element (a neon sign, a TV screen, a digital "
        "interface) — cold tech-noir punctuation against warmer surroundings.",
        implies=("subgenre=tech-noir",),
    ),
    EnumValue(
        "bone-white",
        "Single bone-white focal element (a shirt collar, a letter, a cigarette "
        "ember) — the brightest point in an otherwise dark frame.",
    ),
    EnumValue(
        "eye-glow",
        "Subject's eyes reflect the key light as small but intense focal points. "
        "Requires the eyes to be visible (back-to-camera pose conflicts).",
        conflicts_with=("pose=back-to-camera",),
    ),
    EnumValue(
        "none",
        "Pure monochrome, no color punctuation at all. Hard noir, harder commitment.",
    ),
])


@dataclass(frozen=True)
class NoirSubjectConfig:
    subject: str
    pose: str = "weight-on-one-foot"
    wear_level: str = "weathered"  # weathered | scarred | clean-but-tired | blood-marked

@dataclass(frozen=True)
class NoirCinematographyConfig:
    subgenre: str = "classic-1940s"
    key_light: str = "rim-only"
    atmospheric_medium: str = "rain"
    camera: str = "low-angle"
    grain: str = "heavy"  # heavy | moderate | fine | clean

@dataclass(frozen=True)
class NoirAccentConfig:
    accent_color: str = "blood-red"
    time_of_day: str = "midnight"  # midnight | predawn | dusk | overcast-noon

@dataclass(frozen=True)
class NoirConfig:
    subject: NoirSubjectConfig
    cinematography: NoirCinematographyConfig = field(default_factory=NoirCinematographyConfig)
    accent: NoirAccentConfig = field(default_factory=NoirAccentConfig)
    seed: int = 1


class NoirCinematographyEngine(Engine):
    name: ClassVar[str] = "noir-cinema"
    config_cls: ClassVar[type] = NoirConfig
    masters: ClassVar[tuple[str, ...]] = (
        "John Alton — The Big Combo (1955): bare-bulb cinematography, infinite fill ratio",
        "Frank Miller + Robert Rodriguez — Sin City vol.1 (1991/2005): pure black-and-white with one saturated accent",
        "Roger Deakins — Blade Runner 2049 (2017): neon-practical sources in volumetric smog",
        "Carol Reed + Robert Krasker — The Third Man (1949): Dutch-angle + sewer-light cinematography",
        "Roman Polanski + John A. Alonzo — Chinatown (1974): neo-noir naturalism in period light",
    )
    palette_60_30_10 = {
        "dominant":  {"hex": "#080808", "role": "deep black shadows holding 60% of frame"},
        "secondary": {"hex": "#E8E4DA", "role": "off-white highlight on subject, rim-light edge"},
        "accent":    {"hex": "#9A2222", "role": "single accent (blood-red default)"},
    }
    default_runtime = {"model": "dev", "steps": 28, "guidance": 4.5}
    engine_negatives: ClassVar[tuple[str, ...]] = (
        "bright daylight bleed", "smiling face", "centered square-on pose",
        "modern brand aesthetic", "cheerful palette", "soft fill light",
        "smooth digital cartoon shading", "pastel color grading",
        "anime stylization", "Disney proportions",
    )
    # Curated LoRAs per brand/loras/README.md.
    default_lora_stack: ClassVar[tuple[tuple[str, float], ...]] = (
        ("film-noir/flux-lora-film-noir.safetensors", 0.85),
        ("add-details/add-details.safetensors", 0.50),
    )
    SUBGENRE = _NOIR_SUBGENRE
    KEY_LIGHT = _NOIR_KEY_LIGHT
    ATMOSPHERIC_MEDIUM = _NOIR_ATMOSPHERIC_MEDIUM
    POSE = _NOIR_POSE
    CAMERA = _NOIR_CAMERA
    ACCENT = _NOIR_ACCENT

    @classmethod
    def build(cls, config: NoirConfig) -> Directive:
        cinem = config.cinematography
        accent = config.accent
        subject = config.subject

        sub_genre  = cls.SUBGENRE.validate(cinem.subgenre)
        key_light  = cls.KEY_LIGHT.validate(cinem.key_light)
        medium     = cls.ATMOSPHERIC_MEDIUM.validate(cinem.atmospheric_medium)
        pose       = cls.POSE.validate(subject.pose)
        camera     = cls.CAMERA.validate(cinem.camera)
        acc        = cls.ACCENT.validate(accent.accent_color)
        require(subject.wear_level in ("weathered", "scarred", "clean-but-tired", "blood-marked"),
                f"unknown wear_level={subject.wear_level!r}")
        require(cinem.grain in ("heavy", "moderate", "fine", "clean"),
                f"unknown grain={cinem.grain!r}")
        require(accent.time_of_day in ("midnight", "predawn", "dusk", "overcast-noon"),
                f"unknown time_of_day={accent.time_of_day!r}")

        # Domain invariants — encode rules the genre demands.
        # 1. eye-glow accent requires the eyes to be visible → not compatible with back-to-camera.
        for chk in (key_light, pose, acc):
            for conflict in chk.conflicts_with:
                k, v = conflict.split("=")
                # check the named knob equals the forbidden value
                actual = {
                    "subgenre": cinem.subgenre, "key_light": cinem.key_light,
                    "atmospheric_medium": cinem.atmospheric_medium,
                    "pose": subject.pose, "accent_color": accent.accent_color,
                }.get(k)
                if actual == v:
                    raise ValueError(
                        f"invariant violation: {chk.key} conflicts with {k}={v}. "
                        f"In noir, eye-glow accents require visible eyes; back-to-camera hides them. "
                        f"Pick a different accent or pose."
                    )

        clean_subject = normalize_subject(subject.subject)

        audit = {
            "subgenre": sub_genre.description,
            "key_light": key_light.description,
            "atmospheric_medium": medium.description,
            "pose": pose.description,
            "camera": camera.description,
            "accent_color": acc.description,
            "wear_level": subject.wear_level,
            "grain": cinem.grain,
            "time_of_day": accent.time_of_day,
        }

        prompt = "\n\n".join([
            f"GENRE: noir cinematography — sub-genre = {sub_genre.key}. "
            f"{sub_genre.description}",

            assemble_masters_line(cls.masters),

            f"SUBJECT: {clean_subject}.",

            f"POSE: {pose.description}",

            f"CINEMATOGRAPHY — KEY LIGHT: {key_light.description}",
            f"CINEMATOGRAPHY — ATMOSPHERIC MEDIUM: {medium.description}",
            f"CINEMATOGRAPHY — CAMERA: {camera.description}",
            f"TIME OF DAY: {accent.time_of_day}.",

            f"SURFACE WEAR: subject's clothing and skin show '{subject.wear_level}' wear — "
            "specific marks (scuffed leather, creased fabric, healed scars), nothing fresh-from-store.",

            f"GRAIN: {cinem.grain} film grain through every shadow region, "
            "the grain itself a textural element, not a post-process overlay.",

            f"COLOR ACCENT: {acc.description}",

            "PALETTE — strict: 60% deep black (#080808), 30% off-white (#E8E4DA), "
            "10% the accent color above. No other chroma in frame.",

            "RENDER: hard chiaroscuro, no plastic gloss, no smooth digital cartoon "
            "shading, no soft gradient bloom. Frame should read as a single still "
            "from a finished cinematographer's reel — every shadow placed deliberately, "
            "every contour earned, not interpolated.",
        ])

        return Directive(
            engine=cls.name,
            positive=prompt,
            negatives=tuple(cls.engine_negatives),
            palette_60_30_10=dict(cls.palette_60_30_10),
            runtime=dict(cls.default_runtime),
            seed=int(config.seed),
            audit=audit,
            config=_config_to_dict(config),
            masters=cls.masters,
        )


# ════════════════════════════════════════════════════════════════════════════
# WildlifePhotorealismEngine — lens + anatomy + light science
# ════════════════════════════════════════════════════════════════════════════


_WILD_LENS = EnumBank("lens", [
    EnumValue(
        "85mm-portrait",
        "85mm prime portrait lens equivalent: gentle compression, subject-isolating "
        "shallow depth-of-field at f/1.4-f/2.0, smooth out-of-focus background fall-off. "
        "Best for habituated subjects at intimate distance (zoo birds, dogs, kittens).",
    ),
    EnumValue(
        "200-400mm-medium",
        "200-400mm telephoto zoom equivalent: workhorse wildlife range. Moderate "
        "compression, manageable depth of field, allows close subject without "
        "intrusion. Standard for medium animals (foxes, raptors, primates).",
    ),
    EnumValue(
        "500mm-long",
        "500mm telephoto prime equivalent: heavy compression, very shallow depth of "
        "field, subject pops sharply against creamy bokeh. The wildlife photographer's "
        "default — used for skittish or distant subjects (deer, snow leopards, "
        "perching songbirds).",
    ),
    EnumValue(
        "800mm-extreme",
        "800mm super-telephoto equivalent: extreme compression, background reduced "
        "to color wash, subject extracted from the field. Used for very distant or "
        "very dangerous subjects (lions on the move, eagles in flight).",
    ),
    EnumValue(
        "16-35mm-environmental",
        "16-35mm ultra-wide environmental lens: subject in habitat, environment "
        "occupying 70%+ of the frame, deep depth of field showing landscape. Used "
        "when the story is the animal IN its place (a wolf at the edge of the pack, "
        "a polar bear on melting ice).",
    ),
])

_WILD_LIGHT = EnumBank("light", [
    EnumValue(
        "golden-hour-low",
        "Within 45 minutes of sunrise or sunset, sun within 10° of the horizon. "
        "Low-angle warm orange-gold key light from camera-side or backlit. Long "
        "soft shadows. The most flattering light for fur and feather texture.",
    ),
    EnumValue(
        "blue-hour",
        "20-40 minutes before sunrise or after sunset, no direct sun, ambient sky "
        "is cool blue-cyan diffuse. Soft directional ambient, no harsh shadow, "
        "exposure long enough to render motion subtly. Atmospheric and quiet.",
    ),
    EnumValue(
        "overcast-soft",
        "Heavy overcast diffuse light, full hemisphere is the soft source. No "
        "shadows, perfect detail in fur/feather. Color rendition slightly cool. "
        "Workhorse light for technical detail work.",
    ),
    EnumValue(
        "harsh-noon",
        "Direct overhead sun, hard shadows under brow/chin/belly, high contrast. "
        "Used deliberately for graphic/intense subjects (a hunting cat in the open, "
        "raptor at zenith). Often paired with desaturation in grade.",
    ),
    EnumValue(
        "backlit-rim",
        "Subject backlit by low sun, rim-light tracing the entire outline (fur halo "
        "on mammals, translucent feather edge on birds). Subject's body in cool "
        "shadow, edge in saturated warm light. The most dramatic wildlife light.",
    ),
    EnumValue(
        "dappled-forest",
        "Subject in forest understory, light arriving through canopy in dappled "
        "patches. Subject partly illuminated, partly in shadow. Used for forest "
        "species (tigers in shadow, primates in canopy, deer at woodland edge).",
    ),
])

_WILD_BEHAVIOR = EnumBank("behavior", [
    EnumValue(
        "alert-watching",
        "Subject still, head up, eyes fixed on something off-frame. Body tense, "
        "weight evenly distributed, ears (if mammal) pricked toward the focus of "
        "attention. The moment before fight, flight, or freeze.",
    ),
    EnumValue(
        "resting",
        "Subject at rest, body weight settled, eyes half-closed or surveying lazily. "
        "Limbs tucked or extended in repose. Specific to species (cats curled, deer "
        "couched with legs folded under, birds with one foot tucked).",
    ),
    EnumValue(
        "feeding",
        "Subject actively eating: head down to ground (grazers), beak or jaw "
        "engaged with prey/forage, body lowered or angled toward food. Captures "
        "the everyday rhythm of the species' life.",
    ),
    EnumValue(
        "in-flight",
        "Bird mid-flight: wings in a specific position (full extension on downbeat, "
        "tucked on upbeat, glide configuration), body streamlined, feet tucked or "
        "extended for landing. NEVER the doubled-wing 'frozen-mid-flap' AI artifact.",
        conflicts_with=("lens=85mm-portrait",),
    ),
    EnumValue(
        "grooming",
        "Subject engaged in grooming: bird preening with beak through feathers, "
        "mammal licking fur or rubbing against substrate. Intimate, slow, the "
        "behaviors that define species-specific care routines.",
    ),
    EnumValue(
        "in-motion",
        "Subject mid-stride, walking or running, weight transferring. Specific to "
        "species locomotion (cat's controlled smoothness, deer's springy bounce, "
        "ungulate ambling gait).",
    ),
])

_WILD_HABITAT = EnumBank("habitat", [
    EnumValue("forest-edge",     "Subject at forest edge or in understory, mottled green/brown background."),
    EnumValue("savanna",         "Open savanna with dry grass, scattered acacia, low horizon line."),
    EnumValue("tundra-arctic",   "Arctic tundra, snow + bare rock + occasional moss, low watery light."),
    EnumValue("wetland",         "Wetland reeds/marsh, mirror-like water surface in foreground or midground."),
    EnumValue("branch-perch",    "Subject perched on a specific branch with foliage backdrop blurred by long lens."),
    EnumValue("mountain-cliff",  "High-elevation rocky cliff, lichen-mottled stone, low sparse vegetation."),
    EnumValue("garden-domestic", "Domestic garden setting (flower beds, low fence) — semi-controlled habitat."),
])

_WILD_ANATOMY_HINT = EnumBank("anatomy_hint", [
    EnumValue(
        "bird",
        "Avian anatomy specifics: zygodactyl toes for woodpeckers/parrots (2 forward, "
        "2 back), anisodactyl toes for songbirds (3 forward 1 back), correct feather "
        "tract topology, beak proportional and species-correct, eye placement on "
        "the side of the head (not forward-facing).",
    ),
    EnumValue(
        "mammal-feline",
        "Feline anatomy: 5 toes front feet, 4 toes rear, retracted claws unless in "
        "the act of striking, whisker placement on muzzle and above eye, eye with "
        "vertical slit pupil in bright light, round in dim, tail length species-correct.",
    ),
    EnumValue(
        "mammal-canine",
        "Canine anatomy: 4 toes both front and rear (no thumbs), non-retracting claws, "
        "fixed forward-facing eyes with round pupils, ear position species-correct "
        "(erect, semi-erect, pendulous).",
    ),
    EnumValue(
        "mammal-rodent",
        "Rodent anatomy: 4 toes front feet 5 toes rear, prominent incisors (chisel "
        "shape), large side-set eyes, tail length and hair coverage species-correct "
        "(naked for rats, furred for squirrels, ringed for raccoons).",
    ),
    EnumValue(
        "mammal-ungulate",
        "Ungulate anatomy: cloven (two-toed) hooves on deer/sheep/goats, single-toed on "
        "horses, dewclaws above on deer. Limb proportions long compared to body. "
        "Eyes large and laterally-placed.",
    ),
])


@dataclass(frozen=True)
class WildlifeSubjectConfig:
    subject: str                            # e.g. "snow leopard on a ledge", "blue jay on hawthorn"
    species_class: str = "mammal-feline"    # used to pick anatomy_hint
    behavior: str = "alert-watching"

@dataclass(frozen=True)
class WildlifeOpticsConfig:
    lens: str = "500mm-long"
    light: str = "golden-hour-low"
    habitat: str = "forest-edge"

@dataclass(frozen=True)
class WildlifeConfig:
    subject: WildlifeSubjectConfig
    optics: WildlifeOpticsConfig = field(default_factory=WildlifeOpticsConfig)
    seed: int = 1


class WildlifePhotorealismEngine(Engine):
    name: ClassVar[str] = "wildlife-photo"
    config_cls: ClassVar[type] = WildlifeConfig
    masters: ClassVar[tuple[str, ...]] = (
        "Frans Lanting — large-format wildlife in habitat (LIFE: A Journey Through Time)",
        "Tim Flach — studio-lit large-format animal portraits (Endangered, More Than Human)",
        "Marsel van Oosten — long-lens behavioral wildlife with golden-hour rim light",
        "Sebastião Salgado — Genesis (2013): wildlife as documentary record",
        "Vincent Munier — boreal wildlife with environmental scale (snow leopards, Tibet)",
    )
    palette_60_30_10 = {
        "dominant":  {"hex": "#3D3528", "role": "warm brown habitat tones, 60% of frame"},
        "secondary": {"hex": "#A88E6E", "role": "subject's body coloration, hairlight-warm midtone"},
        "accent":    {"hex": "#D5A04C", "role": "single golden-hour-warm focal accent (eye highlight, rim glow, feather edge)"},
    }
    default_runtime = {"model": "dev", "steps": 30, "guidance": 3.5}
    engine_negatives: ClassVar[tuple[str, ...]] = (
        "fused toes", "extra toes", "extra fingers on paws",
        "doll-eye plastic catch-light", "uncanny anthropomorphic face",
        "cartoon proportions", "Disney-cute eyes", "anime stylization",
        "studio strobe-flat lighting", "photoshopped HDR halos",
        "bird beak open with no purpose", "watermark", "stock photo logo",
    )
    # Curated LoRAs per brand/loras/README.md — the verified-best stack for
    # photo-realism. flux-RealismLora is the most-downloaded FLUX LoRA (15k+).
    default_lora_stack: ClassVar[tuple[tuple[str, float], ...]] = (
        ("realism-xlabs/lora.safetensors", 0.80),
        ("add-details/add-details.safetensors", 0.50),
    )
    LENS = _WILD_LENS
    LIGHT = _WILD_LIGHT
    BEHAVIOR = _WILD_BEHAVIOR
    HABITAT = _WILD_HABITAT
    ANATOMY_HINT = _WILD_ANATOMY_HINT

    @classmethod
    def build(cls, config: WildlifeConfig) -> Directive:
        sub = config.subject
        op = config.optics

        lens = cls.LENS.validate(op.lens)
        light = cls.LIGHT.validate(op.light)
        behavior = cls.BEHAVIOR.validate(sub.behavior)
        habitat = cls.HABITAT.validate(op.habitat)
        anatomy = cls.ANATOMY_HINT.validate(sub.species_class)

        # Invariants
        for chk in (lens, behavior):
            for conflict in chk.conflicts_with:
                k, v = conflict.split("=")
                actual = {"lens": op.lens, "behavior": sub.behavior}.get(k)
                if actual == v:
                    raise ValueError(
                        f"invariant: {chk.key} conflicts with {k}={v}. "
                        f"A 85mm portrait lens cannot capture in-flight birds — "
                        f"use a 500mm-long or 800mm-extreme lens for flight."
                    )

        clean_subject = normalize_subject(sub.subject)

        audit = {
            "lens": lens.description,
            "light": light.description,
            "behavior": behavior.description,
            "habitat": habitat.description,
            "anatomy_hint": anatomy.description,
        }

        prompt = "\n\n".join([
            "GENRE: wildlife photorealism — single still frame from a published "
            "wildlife photographer's portfolio. NOT a digital painting, NOT a "
            "3D render. The image must read as captured-by-lens.",

            assemble_masters_line(cls.masters),

            f"SUBJECT: {clean_subject}.",

            f"OPTICS — LENS: {lens.description}",
            f"OPTICS — LIGHT: {light.description}",
            f"HABITAT: {habitat.description}",

            f"BEHAVIOR: {behavior.description}",

            f"ANATOMY — STRICT REQUIREMENT: {anatomy.description}",

            "PALETTE: 60% warm-earth habitat tones, 30% subject-body midtones, "
            "10% golden-hour-warm focal accent (eye catch-light, feather/fur rim glow). "
            "No saturated unnatural color.",

            "RENDER: physical-camera realism — visible film grain or sensor "
            "structure, accurate depth-of-field falloff (sharp at focal plane, "
            "smoothly increasing blur with distance), natural color science, "
            "imperfect details (matted fur tuft, single misaligned feather, "
            "a leaf out of place). Avoid HDR-bloom, plastic feather sheen, "
            "uncanny doll-eyes, and impossible symmetric framing.",
        ])

        return Directive(
            engine=cls.name,
            positive=prompt,
            negatives=tuple(cls.engine_negatives),
            palette_60_30_10=dict(cls.palette_60_30_10),
            runtime=dict(cls.default_runtime),
            seed=int(config.seed),
            audit=audit,
            config=_config_to_dict(config),
            masters=cls.masters,
        )


# ════════════════════════════════════════════════════════════════════════════
# ImpressionistPaintingEngine — period-aware Van Gogh + colleagues
# ════════════════════════════════════════════════════════════════════════════


_IMP_MASTER = EnumBank("master", [
    EnumValue(
        "van-gogh",
        "Vincent van Gogh signature methods: impasto brushwork (visibly raised paint), "
        "directional brushstroke aligned to form (radial for stars, vertical for "
        "cypresses, horizontal for fields), chromatic-rather-than-tonal modeling "
        "(complementary color pairs replacing light/shadow), unmodified paint "
        "straight from tube.",
        masters=("Wheatfield with Crows (1890)", "The Starry Night (1889)", "Cypresses (1889)", "Sunflowers (1888)"),
    ),
    EnumValue(
        "monet",
        "Claude Monet signature methods: broken-color daubs creating optical mixing, "
        "rapidly applied wet-into-wet, atmospheric perspective via color shift "
        "(violet shadows, pink highlights), same subject in multiple light "
        "conditions, the painting is OF the light not of the subject.",
        masters=("Haystacks series (1890-91)", "Water Lilies (1899-1926)", "Impression Sunrise (1872)"),
    ),
    EnumValue(
        "cezanne",
        "Paul Cézanne signature methods: constructive brushstrokes built up in small "
        "facets, color modulation defining form (no traditional chiaroscuro), "
        "flattened picture plane, equal density across the canvas, the world "
        "treated as geometric volumes.",
        masters=("Mont Sainte-Victoire series (1880s-90s)", "The Card Players (1890-95)", "The Bathers (1900-06)"),
    ),
    EnumValue(
        "seurat",
        "Georges Seurat divisionist/pointillist method: tiny separated dots of pure "
        "complementary color, optical mixing only in the viewer's eye, science-based "
        "color theory (Chevreul), figures static and architectural rather than "
        "kinetic.",
        masters=("A Sunday on La Grande Jatte (1884-86)", "Bathers at Asnières (1884)"),
    ),
])

_IMP_VAN_GOGH_PERIOD = EnumBank("vg_period", [
    EnumValue(
        "dutch-dark",
        "Dutch period (1881-85): dark earthen palette (umber, ochre, deep green, "
        "black), peasant subjects, lamplit interiors, heavy chiaroscuro, "
        "pre-impressionist tonal modeling. The Potato Eaters era.",
        masters=("The Potato Eaters (1885)",),
    ),
    EnumValue(
        "paris-impressionist",
        "Paris period (1886-88): brightened palette under impressionist influence, "
        "broken color, urban subjects, café scenes, self-portraits in modern dress, "
        "the bridge between Dutch tonal and Arles chromatic.",
        masters=("Self-Portraits in Paris (1886-87)",),
    ),
    EnumValue(
        "arles-vibrant",
        "Arles period (Feb 1888 – May 1889): peak chromatic, complementary color "
        "pairs (blue-orange, yellow-violet, red-green), heavy impasto, southern "
        "French light + yellow + blue + green. Sunflowers, Bedroom at Arles, "
        "Night Café.",
        masters=("Sunflowers (1888)", "The Bedroom (1888)", "The Night Café (1888)"),
    ),
    EnumValue(
        "saint-remy-swirl",
        "Saint-Rémy period (May 1889 – May 1890): signature swirling-stroke "
        "compositions, asylum-window subjects, olive groves, Cypresses, Starry "
        "Night. Sky becomes a kinetic field. The peak of the iconic style.",
        masters=("The Starry Night (1889)", "Cypresses (1889)", "Olive Trees (1889)"),
    ),
    EnumValue(
        "auvers-final",
        "Auvers-sur-Oise period (May-July 1890): broader looser strokes, double "
        "horizontal canvases, wheatfields, churches, the final months before death. "
        "Slightly less density, more horizon, sense of vastness.",
        masters=("Wheatfield with Crows (July 1890)", "Church at Auvers (1890)"),
    ),
])

_IMP_BRUSH = EnumBank("brush", [
    EnumValue(
        "impasto-thick",
        "Paint applied so thickly it stands proud of the canvas, palette-knife or "
        "loaded brush, each stroke a visible ridge, sculptural physicality, "
        "shadows form between strokes regardless of color.",
    ),
    EnumValue(
        "divisionist",
        "Tiny separated dots or short hatched strokes of pure complementary color, "
        "no mixed-on-palette greys, optical mixing in the eye only, scientific "
        "color theory applied.",
    ),
    EnumValue(
        "broken-color",
        "Short, separated strokes of mixed hue applied wet-on-wet but not blended, "
        "colors remain distinct on the canvas, vibrating against each other rather "
        "than producing a smooth mix.",
    ),
    EnumValue(
        "directional-stroke",
        "Each region of the painting has its own brushstroke direction following the "
        "form: vertical for trees/figures, radial for suns/flames, horizontal for "
        "fields/water, swirling for sky/wind.",
    ),
])

_IMP_PALETTE_MODE = EnumBank("palette_mode", [
    EnumValue(
        "chromatic-complementary",
        "Color pairs from opposite sides of the wheel placed adjacent to each other: "
        "blue+orange, yellow+violet, red+green. Used INSTEAD of light/dark modeling. "
        "No mixed grey or black.",
    ),
    EnumValue(
        "high-key-bright",
        "Light-end of value range, bright sky, sun-soaked, sense of summer noon. "
        "Yellows and pale blues dominate. Sparing use of dark accents.",
    ),
    EnumValue(
        "tonal-dark",
        "Dutch-tonal mode: limited palette of earth tones (umber, ochre, deep green, "
        "muted red), chiaroscuro modeling. Pre-chromatic Van Gogh approach.",
    ),
])

_IMP_SUBJECT_TREATMENT = EnumBank("subject_treatment", [
    EnumValue("cypress-flame",        "Cypress trees painted as upward-swirling flame shapes, dark green flame against contrasting sky."),
    EnumValue("starry-swirl",         "Sky composed of swirling concentric strokes around radiant stars or moon, sky kinetic rather than static."),
    EnumValue("sunflower-heavy",      "Sunflowers rendered with impasto-thick yellow, individual petals modeled as raised paint, vase or pot solidly geometric."),
    EnumValue("wheatfield-impasto",   "Wheatfield composed of short vertical strokes in yellow-ochre, sky horizon line dividing the frame, crows or church in middle distance."),
    EnumValue("café-interior-night", "Cafe interior at night, gas-lamp warm yellow against deep blue-green walls, isolated patrons, color-as-emotional-violence."),
    EnumValue("portrait-direct",     "Direct portrait subject, eyes meeting viewer, painted with chromatic modeling (warm-cool color pairs replacing light-dark)."),
])


@dataclass(frozen=True)
class ImpSubjectConfig:
    subject: str
    treatment: str = "starry-swirl"

@dataclass(frozen=True)
class ImpTechniqueConfig:
    master: str = "van-gogh"
    vg_period: str = "saint-remy-swirl"  # only used when master=van-gogh
    brush: str = "directional-stroke"
    palette_mode: str = "chromatic-complementary"

@dataclass(frozen=True)
class ImpressionistConfig:
    subject: ImpSubjectConfig
    technique: ImpTechniqueConfig = field(default_factory=ImpTechniqueConfig)
    seed: int = 1


class ImpressionistPaintingEngine(Engine):
    name: ClassVar[str] = "impressionist"
    config_cls: ClassVar[type] = ImpressionistConfig
    masters: ClassVar[tuple[str, ...]] = (
        "Vincent van Gogh — The Starry Night (1889), Cypresses (1889): swirling-stroke saint-rémy style",
        "Claude Monet — Haystacks series (1890-91): same subject through changing light",
        "Paul Cézanne — Mont Sainte-Victoire (1880s-90s): constructive faceted brushwork",
        "Georges Seurat — La Grande Jatte (1884-86): divisionist optical mixing",
        "Berthe Morisot — The Cradle (1872): broken color in intimate domestic subjects",
    )
    palette_60_30_10 = {
        "dominant":  {"hex": "#1E3A5F", "role": "deep-blue field for sky/water (Van Gogh chromatic dominant)"},
        "secondary": {"hex": "#E8C547", "role": "complementary yellow — star-glow, sunflower, field"},
        "accent":    {"hex": "#3D5B2E", "role": "olive-green or cypress-dark vertical accent"},
    }
    default_runtime = {"model": "dev", "steps": 30, "guidance": 4.0}
    engine_negatives: ClassVar[tuple[str, ...]] = (
        "smooth digital gradient", "photo-realism creep", "modern HDR color grade",
        "Instagram filter aesthetic", "vector art clean lines", "anime line art",
        "watercolor wash (different medium)", "uniform brushwork direction",
        "single-color flat fill", "3D rendered look",
    )
    # Only Van Gogh has a curated FLUX LoRA — the engine's own master citations
    # plus this LoRA push toward authentic post-impressionist register.
    default_lora_stack: ClassVar[tuple[tuple[str, float], ...]] = (
        ("van-gogh/lora.safetensors", 0.85),
    )
    MASTER = _IMP_MASTER
    VG_PERIOD = _IMP_VAN_GOGH_PERIOD
    BRUSH = _IMP_BRUSH
    PALETTE_MODE = _IMP_PALETTE_MODE
    SUBJECT_TREATMENT = _IMP_SUBJECT_TREATMENT

    @classmethod
    def build(cls, config: ImpressionistConfig) -> Directive:
        sub = config.subject
        tech = config.technique
        master = cls.MASTER.validate(tech.master)
        brush = cls.BRUSH.validate(tech.brush)
        palette_mode = cls.PALETTE_MODE.validate(tech.palette_mode)
        treatment = cls.SUBJECT_TREATMENT.validate(sub.treatment)

        # Period only meaningful for Van Gogh
        period = None
        if tech.master == "van-gogh":
            period = cls.VG_PERIOD.validate(tech.vg_period)
            # invariant: Dutch-dark period is tonal, can't be paired with chromatic-complementary
            if tech.vg_period == "dutch-dark" and tech.palette_mode == "chromatic-complementary":
                raise ValueError(
                    "invariant: Van Gogh Dutch-dark period predates chromatic-complementary "
                    "method. Use palette_mode=tonal-dark with vg_period=dutch-dark, or pick "
                    "arles-vibrant/saint-remy-swirl/auvers-final for chromatic complementary."
                )

        clean_subject = normalize_subject(sub.subject)

        audit = {
            "master": master.description,
            "vg_period": period.description if period else "(non-Van-Gogh master)",
            "brush": brush.description,
            "palette_mode": palette_mode.description,
            "subject_treatment": treatment.description,
        }

        prompt_parts = [
            f"GENRE: post-impressionist oil painting in the manner of {master.key}. "
            f"{master.description}",

            assemble_masters_line(cls.masters),
        ]
        if period:
            prompt_parts.append(f"PERIOD: {period.description}")
        prompt_parts.extend([
            f"SUBJECT: {clean_subject}.",
            f"SUBJECT TREATMENT: {treatment.description}",
            f"BRUSHWORK: {brush.description}",
            f"PALETTE LOGIC: {palette_mode.description}",
            "PALETTE — concrete: 60% deep-blue field (#1E3A5F), 30% complementary "
            "yellow (#E8C547), 10% olive-green vertical accent (#3D5B2E). Adjust as "
            "the subject demands but maintain a strict triad.",

            "RENDER: the image MUST read as oil-on-canvas, not as a digital image. "
            "Visible brush strokes EVERYWHERE — not as decoration but as the actual "
            "construction method. NO smooth digital gradients, NO photo-realism, "
            "NO Instagram filter look. Canvas weave subtly visible in shadow regions.",
        ])
        prompt = "\n\n".join(prompt_parts)

        return Directive(
            engine=cls.name,
            positive=prompt,
            negatives=tuple(cls.engine_negatives),
            palette_60_30_10=dict(cls.palette_60_30_10),
            runtime=dict(cls.default_runtime),
            seed=int(config.seed),
            audit=audit,
            config=_config_to_dict(config),
            masters=cls.masters,
        )


# ════════════════════════════════════════════════════════════════════════════
# IndianClassicalEngine — tradition-aware iconographic illustration
# ════════════════════════════════════════════════════════════════════════════


_IC_TRADITION = EnumBank("tradition", [
    EnumValue(
        "tanjore",
        "Tanjore tradition (Thanjavur, Tamil Nadu, 16th-19th c.): hieratic centered "
        "composition, generous use of 22-carat gold leaf for jewelry/halos/borders, "
        "rich red+green+gold palette, figures with rounded faces and almond eyes, "
        "decorative inset semi-precious stones (in original works simulated visually).",
        masters=("traditional Tanjore deity paintings",),
    ),
    EnumValue(
        "madhubani",
        "Madhubani / Mithila folk tradition (Bihar): VERY LARGE characteristic eyes "
        "(white sclera + oversized round black pupils that dominate every face), "
        "thick black ink outline around every form (every shape carries a DOUBLE-LINE "
        "border with parallel inner contour), every interior region densely filled "
        "with one of a finite vocabulary of fill-patterns (dot-clusters, fish-scale "
        "rows, chevrons, leaf-veins, small floral rosettes), flat saturated color "
        "blocks (NO shading, NO gradient) using a 6-7-color palette of red + yellow + "
        "green + blue + orange + black on cream/white paper ground. Figural subjects "
        "wear elaborate jewelry (kundalas, multi-strand pearl/bead malas, tilak/bindi, "
        "tall conical mukutas with stacked color-registers), garments with deeply "
        "decorated border patterns. Background uses peepal-leaf clusters and floral/"
        "geometric border bands on the canvas edges. Compositions are FLAT (no "
        "perspective), figures arranged side-by-side in friezes.",
        masters=("Sita Devi (Padma Shri 1981)", "Ganga Devi", "Bharti Dayal", "Mahasundari Devi"),
    ),
    EnumValue(
        "pahari-miniature",
        "Pahari miniature (Punjab Hills, 17th-19th c.): delicate refined linework, "
        "subtle naturalistic landscape, jewel-tone palette, Sanskrit poetry-based "
        "narrative subjects (Krishna's leelas, Ramayana), small-scale intimate "
        "intensity. Basohli school for boldness, Kangra school for grace.",
        masters=("Basohli school", "Kangra school",),
    ),
    EnumValue(
        "ravi-varma-oleograph",
        "Raja Ravi Varma realist oleograph tradition (late 19th c.): European "
        "academic realism applied to Hindu deity/mythology subjects, anatomically "
        "naturalistic figures, classical contrapposto pose, soft modeling, "
        "rich saris/dhotis with realistic drape, naturalistic landscape backgrounds.",
        masters=("Raja Ravi Varma — Damayanti and the Swan, Lady in the Moonlight",),
    ),
    EnumValue(
        "warli",
        "Warli tribal tradition (Maharashtra, Thane/Palghar): MONOCHROME white "
        "rice-paste pigment on brown earth-ochre ground — ONLY two colors, no "
        "additional palette. Human figures built from primitive geometry: TWO "
        "TRIANGLES joined at apex for the torso (point up + point down), a SMALL "
        "ROUND HEAD on top, thin stick limbs — NO facial detail at all (no eyes, "
        "no nose, no mouth), the figures are silhouette-rhythmic. Animals (cow, "
        "dog, deer, peacock) in matching stick-figure form. Compositional "
        "vocabulary: tree of life with dense leaf-clusters, tarpa (circular ring) "
        "dance, bullock cart, wedding chauk (sacred square), spirals, peacock-with-"
        "circular-eye-feather. Dense pattern fills made by repeating small marks "
        "(dots, hatches, tiny triangles). Composition is grid-organized or "
        "symmetric around a central sacred square (chauk). NO perspective, NO "
        "shading, NO color beyond the white pigment.",
        masters=("traditional Warli wall painting (Maharashtra)", "Jivya Soma Mashe (Padma Shri 2011)"),
    ),
])

_IC_MUDRA = EnumBank("mudra", [
    EnumValue(
        "abhaya",
        "Abhaya mudra (gesture of fearlessness/protection): right hand raised, palm "
        "facing outward at shoulder height, fingers extended upward. Conveys divine "
        "protection.",
    ),
    EnumValue(
        "varada",
        "Varada mudra (gesture of giving/blessing): hand extended downward, palm "
        "facing outward, fingers pointing toward ground. Conveys generosity, granting "
        "of wishes.",
    ),
    EnumValue(
        "dhyana",
        "Dhyana mudra (meditation): both hands resting in lap, palms upward, right "
        "over left. Conveys concentration and meditative state.",
    ),
    EnumValue(
        "vitarka",
        "Vitarka mudra (teaching): thumb and index finger touching forming a circle, "
        "other fingers extended upward. Conveys exposition of dharma.",
    ),
    EnumValue(
        "anjali",
        "Anjali mudra (salutation): both palms pressed together at chest. Conveys "
        "respect, devotion, greeting.",
    ),
    EnumValue(
        "tribhanga-flute",
        "Tribhanga pose holding flute (Krishna): three-bend body posture (head/torso/"
        "legs each angled), flute held to mouth with both hands, weight on left foot, "
        "right leg crossed over. Iconic Krishna stance.",
    ),
])

_IC_GROUND = EnumBank("ground", [
    EnumValue("temple-interior",     "Temple interior with stone columns, oil-lamp glow, garlanded shrine in background."),
    EnumValue("forest-grove",        "Sacred forest grove with kadamba/peepal trees, dappled sunlight, occasional peacock or cow at edge."),
    EnumValue("river-bank-yamuna",   "Yamuna river bank at dawn or dusk, lotus pond foreground, blue water meeting saffron sky."),
    EnumValue("cosmic-water",        "Ocean of cosmic waters with serpent Shesha or floating lotus pedestal, no horizon, mythological setting."),
    EnumValue("celestial-sky",       "Celestial sky with apsaras, vimanas, swirling clouds, gods visible in middle distance — Vaikuntha or Kailash."),
    EnumValue("village-pastoral",    "Village pastoral with thatched huts, grazing cows, women with water-pots, festival activity in middle ground."),
    EnumValue("madhubani-paper",     "Cream/white paper ground bordered by stacked geometric+floral decorative bands; peepal-leaf and dot-cluster motifs filling negative space behind the figures. Used for Madhubani."),
    EnumValue("warli-mud-wall",      "Brown earth-ochre wall ground (the geru-coated mud wall surface), entire scene painted in white rice-paste pigment only; surface texture lightly visible under the paint. Used for Warli."),
    EnumValue("warli-tarpa-circle",  "Brown earth ground with a central sacred-square chauk and a concentric tarpa-dance ring of stick-figure dancers around it, dense white pattern fills on the edges (zigzag, dot-clusters, peacock-feather circles). Used for Warli festival/dance subjects."),
])

_IC_COMPOSITION = EnumBank("composition", [
    EnumValue(
        "hieratic-centered",
        "Subject deity centered, large in frame (occupies 60%+ of vertical axis), "
        "attendants/devotees smaller at sides or below, sacred geometry implicit "
        "in the placement. Classical icon composition.",
    ),
    EnumValue(
        "narrative-multi-figure",
        "Multiple figures arranged in a narrative scene (Krishna with gopis, Rama "
        "with vanaras, etc.), each figure scaled by importance, scene unfolding "
        "across the frame in readable sequence.",
    ),
    EnumValue(
        "lyric-intimate",
        "Two-figure intimate composition (lover + beloved, parent + child, "
        "devotee + deity), close visual distance, gestures and eye-contact carrying "
        "the narrative, landscape supportive not dominant.",
    ),
    EnumValue(
        "cosmic-cosmic",
        "Vast cosmological composition — deity as universe-containing, multiple "
        "scales visible in one frame (galaxies, mountains, oceans, beings all "
        "rendered at their proper scales).",
    ),
])


@dataclass(frozen=True)
class ICSubjectConfig:
    subject: str                            # e.g. "Krishna playing flute by the Yamuna at dawn"
    mudra: str = "tribhanga-flute"
    composition: str = "lyric-intimate"

@dataclass(frozen=True)
class ICStyleConfig:
    tradition: str = "ravi-varma-oleograph"
    ground: str = "river-bank-yamuna"

@dataclass(frozen=True)
class IndianClassicalConfig:
    subject: ICSubjectConfig
    style: ICStyleConfig = field(default_factory=ICStyleConfig)
    seed: int = 1


class IndianClassicalEngine(Engine):
    name: ClassVar[str] = "indian-classical"
    config_cls: ClassVar[type] = IndianClassicalConfig
    masters: ClassVar[tuple[str, ...]] = (
        "Raja Ravi Varma — Lady in the Moonlight (1889), Damayanti and the Swan: European realism applied to Indian subjects",
        "traditional Tanjore school — devotional panels with 22-carat gold leaf, semi-precious stone inlay",
        "Pahari Kangra school — Bhagavata Purana series, lyric pastoral Krishna leelas",
        "Sita Devi (Madhubani, Padma Shri 1981) — folk-tradition narrative scenes",
        "Nandalal Bose — modern bridge of Bengali school + traditional iconography",
    )
    palette_60_30_10 = {
        "dominant":  {"hex": "#1E5A7E", "role": "Krishna/Vishnu blue or temple-deep-blue, 60% of frame"},
        "secondary": {"hex": "#D4A04C", "role": "saffron/marigold/gold-leaf complement, jewelry + garment + halo"},
        "accent":    {"hex": "#9C2A2A", "role": "deep-red sindoor / kumkum / lotus / ceremonial cloth"},
    }
    default_runtime = {"model": "dev", "steps": 30, "guidance": 4.0}
    engine_negatives: ClassVar[tuple[str, ...]] = (
        "plastic-doll skin", "Disney-cute proportions", "anime stylization",
        "3D rendered look", "Western cartoon aesthetic", "chibi proportions",
        "modern brand poster style", "studio strobe lighting", "neon glow",
        "smooth digital airbrush", "rainbow chromatic aberration",
        "incorrect iconography", "non-period costume",
    )
    # Closest curated match — no Pahari/Tanjore-specific FLUX LoRA exists yet.
    # Indo-Realism pulls toward Indian visual idiom even though it's not
    # tradition-specific. See BRAND-LORA.md for training a per-tradition LoRA.
    default_lora_stack: ClassVar[tuple[tuple[str, float], ...]] = (
        ("indo-realism/lora.safetensors", 0.70),
    )
    TRADITION = _IC_TRADITION
    MUDRA = _IC_MUDRA
    GROUND = _IC_GROUND
    COMPOSITION = _IC_COMPOSITION

    @classmethod
    def build(cls, config: IndianClassicalConfig) -> Directive:
        sub = config.subject
        st = config.style
        tradition = cls.TRADITION.validate(st.tradition)
        mudra = cls.MUDRA.validate(sub.mudra)
        ground = cls.GROUND.validate(st.ground)
        comp = cls.COMPOSITION.validate(sub.composition)

        # Invariant: Warli tradition uses simple geometric figures — no detailed mudra
        if st.tradition == "warli" and sub.mudra != "anjali":
            # Warli stylistically incompatible with detailed mudras
            raise ValueError(
                "invariant: Warli tradition uses geometric stick-figure forms — "
                "detailed mudras (other than the simplest anjali) cannot be rendered "
                "in this style. Either pick a different tradition or use mudra=anjali."
            )

        clean_subject = normalize_subject(sub.subject)

        audit = {
            "tradition": tradition.description,
            "mudra": mudra.description,
            "ground": ground.description,
            "composition": comp.description,
        }

        prompt = "\n\n".join([
            f"GENRE: classical Indian devotional illustration in the {tradition.key} "
            f"tradition. {tradition.description}",

            assemble_masters_line(cls.masters),

            f"SUBJECT: {clean_subject}.",

            f"ICONOGRAPHY — MUDRA / POSE: {mudra.description}",
            f"GROUND / SETTING: {ground.description}",
            f"COMPOSITION: {comp.description}",

            "PALETTE: 60% deep-blue Krishna/Vishnu/temple blue (#1E5A7E), 30% "
            "saffron-gold marigold complement (#D4A04C), 10% deep-red sindoor/lotus "
            "accent (#9C2A2A). Traditional triad — DO NOT add Western pastels, neon, "
            "or modern brand colors.",

            "RENDER NOTES: must respect ICONOGRAPHIC CONVENTION — correct mudra "
            "fingers, correct attribute objects (flute for Krishna, conch+discus "
            "for Vishnu, trident for Shiva, etc.), correct jewelry (kundalas, "
            "haaras, mukutas, kankana), correct fabric drape (dhoti/sari with "
            "specific period-correct fold patterns). NO plastic-doll skin, NO "
            "Western cartoon cute eyes, NO 3D-render look. The image should feel "
            "like it could hang in a household puja room — sacred, not novelty.",
        ])

        return Directive(
            engine=cls.name,
            positive=prompt,
            negatives=tuple(cls.engine_negatives),
            palette_60_30_10=dict(cls.palette_60_30_10),
            runtime=dict(cls.default_runtime),
            seed=int(config.seed),
            audit=audit,
            config=_config_to_dict(config),
            masters=cls.masters,
        )


# ════════════════════════════════════════════════════════════════════════════
# ChildrensColoringBookEngine — narrative line-art for kids
# ════════════════════════════════════════════════════════════════════════════
#
# Design intent (from user spec): single-page B&W line-art with master-grade
# children's-book sensibility. The engine encodes:
#   * picture-book tradition (Mo Willems / Boynton / Carle / Potter / Miyazaki)
#   * age-appropriate complexity (toddler / kids / pre-teen)
#   * narrative moment (a specific story-beat, not a generic pose)
#   * closed-shape line-art discipline (fillable regions for coloring)
# It is NOT a generic "cartoon" engine — every page is a finished spread from
# a published children's title.


_CB_TRADITION = EnumBank("tradition", [
    EnumValue(
        "mo-willems-minimal",
        "Mo Willems Elephant-and-Piggie tradition: extreme economy of line — 12 to 20 "
        "ink strokes total, two-dot eyes carrying the entire emotional load, mouth "
        "as a small shape (curve, oval, zigzag), no shading, no texture, body forms "
        "as smooth closed curves, generous white space around the figures. The page "
        "reads instantly to a 4-year-old; the comedy and warmth live entirely in "
        "the eye-spacing and mouth-shape.",
        masters=("Mo Willems — Elephant & Piggie series (2007-2017)", "Don't Let the Pigeon Drive the Bus (2003)"),
    ),
    EnumValue(
        "sandra-boynton-whimsical",
        "Sandra Boynton tradition: chunky rounded cartoon animals (hippo, chicken, "
        "cow, pig), oversized heads on small bodies, dot or bean-shaped eyes, simple "
        "smiling mouth lines, gentle silliness with rhythmic compositional repetition. "
        "Closed outline shapes with NO interior shading, generous fillable bellies "
        "and ears. Pages read aloud well in rhyming books.",
        masters=("Sandra Boynton — Moo, Baa, La La La! (1982)", "The Going to Bed Book (1982)"),
    ),
    EnumValue(
        "eric-carle-bold",
        "Eric Carle Very-Hungry-Caterpillar tradition: bold thick black outlines "
        "(coloring-book equivalent of his collaged tissue-paper edges), simple "
        "geometric body shapes (oval body, circular head, segmented forms for "
        "insects), large fillable color fields (in the book they are tissue-paper "
        "textured, in the line-art version they remain pristine fillable regions). "
        "Limit of about 8-12 named objects per spread.",
        masters=("Eric Carle — The Very Hungry Caterpillar (1969)", "Brown Bear, Brown Bear, What Do You See? (1967)", "The Grouchy Ladybug (1977)"),
    ),
    EnumValue(
        "beatrix-potter-naturalistic",
        "Beatrix Potter Peter-Rabbit tradition: anatomically naturalistic small "
        "mammals (rabbits with correct ear/whisker placement, squirrels with bushy "
        "tails, mice with rounded haunches) in human-domestic clothing (waistcoat, "
        "bonnet, apron), countryside cottage/garden settings with naturalistic "
        "vegetation (foxglove, cabbages, hedgerow). Slightly more line-density "
        "than Carle/Boynton but still all closed shapes and fillable.",
        masters=("Beatrix Potter — The Tale of Peter Rabbit (1902)", "The Tale of Squirrel Nutkin (1903)", "The Tailor of Gloucester (1903)"),
    ),
    EnumValue(
        "miyazaki-storyboard",
        "Hayao Miyazaki storyboard line-tradition: clean confident pen-line, "
        "environmental detail rendered in restrained line (cloud-edges, leaf-clusters, "
        "wood-grain hint) rather than shading, characters with expressive but "
        "grounded faces (NOT chibi, NOT manga-style giant eyes), spirits and "
        "creatures plausibly inhabiting the scene. Higher detail-count than the "
        "younger-age traditions but still age-9+ readable.",
        masters=("Hayao Miyazaki — My Neighbor Totoro (1988) storyboards", "Spirited Away (2001) production sketches", "Howl's Moving Castle (2004) layouts"),
    ),
    EnumValue(
        "hanna-barbera-flat-cartoon",
        "Hanna-Barbera 1957-1970s flat cel-animation tradition translated to line art: "
        "uniform medium-weight black outlines around every form (no thick-to-thin "
        "modulation), bodies built from smooth simple geometric shapes (oval torsos, "
        "pill-shaped limbs, circular heads), CHARACTERISTIC HB EYES — a white oval "
        "or circle for each eye containing a single round black pupil (NOT two-dot "
        "Mo Willems minimal, NOT manga giant-eye sparkle), mouths drawn as a simple "
        "curve or oval, eyebrows as small detached strokes above the eyes, hair "
        "rendered as a few large flowing shapes rather than individual strands. "
        "Backgrounds are flat silhouettes (trees as trunk-rectangle + canopy-oval, "
        "houses as box + triangle roof), every shape closed and fillable. The page "
        "should read instantly as 'a still from a Hanna-Barbera Saturday-morning "
        "cartoon, but as a coloring page'.",
        masters=("Hanna-Barbera — The Flintstones (1960-66)", "Yogi Bear (1958-62)", "The Jetsons (1962-63)", "Top Cat (1961-62)", "Huckleberry Hound (1958-62)"),
    ),
])

_CB_AGE_RANGE = EnumBank("age_range", [
    EnumValue(
        "toddler-3-5",
        "Ages 3-5: maximum 3-5 main shapes per page, line weight equivalent to "
        "1.5-2mm ink (very thick), each fillable region at least 30mm equivalent "
        "across (toddler-grip crayons can't cover small areas), no overlapping "
        "outlines that would confuse 'inside vs outside', generous (>50%) white "
        "background per page. Subject should be a single character + one or two "
        "anchor objects, no busy environment.",
    ),
    EnumValue(
        "kids-6-9",
        "Ages 6-9: 6-10 main elements per page, line weight equivalent to 1mm ink "
        "(medium), fillable regions between 8mm and 30mm equivalent, named "
        "supporting characters allowed (a friend, a pet, a sibling), a recognizable "
        "setting beyond the character (a meadow, a treehouse, a kitchen). Plot-beats "
        "can be subtle — eye contact between two characters carries narrative.",
    ),
    EnumValue(
        "pre-teen-10-12",
        "Ages 10-12: 12-20 main elements, line weight equivalent to 0.5mm ink "
        "(fine), some hatch-clusters allowed at the edges of forms (texture hints, "
        "NEVER interior shading), more layered scenes (foreground / midground / "
        "background visible), reading-ready narrative (the picture tells a story-"
        "beat that can stand alone on the page).",
    ),
])

_CB_CHARACTER_ARCHETYPE = EnumBank("character_archetype", [
    EnumValue(
        "friendly-dragon",
        "Friendly dragon: rounded snout (NOT pointed/predatory), small rounded "
        "horns (no spikes), soft belly, expressive forward-facing eyes (children's-"
        "book non-threatening), tiny rounded teeth or none visible, often colored "
        "in pastels in the source-book — line-art shows the dragon as a fillable "
        "outline a child WANTS to color.",
    ),
    EnumValue(
        "curious-bear-cub",
        "Curious bear cub: rounded body and head, small round ears, sitting or "
        "standing on hind legs, paws holding something or reaching for something, "
        "eyes wide and inquisitive, NEVER baring teeth, NEVER snarling.",
    ),
    EnumValue(
        "brave-rabbit",
        "Brave rabbit: long upright ears, large hind feet, twitching nose hint, "
        "often in waistcoat or apron (Potter influence), expression alert but "
        "gentle, ears pricked but not flattened (which would mean fear in real "
        "rabbits).",
    ),
    EnumValue(
        "wise-owl",
        "Wise owl: rounded body, large forward-facing eyes (the only predator "
        "shape children always read as friendly), ear-tufts optional, often "
        "wearing tiny spectacles, perched on a branch or book.",
    ),
    EnumValue(
        "whimsical-fox",
        "Whimsical fox: pointed but rounded snout (NOT sharp), bushy tail with "
        "white tip, alert triangular ears, slightly mischievous expression, "
        "NEVER predatory, often dressed in scarf or coat.",
    ),
    EnumValue(
        "gentle-giant",
        "Gentle giant (a big-but-soft creature — could be a yeti, totoro-like "
        "spirit, mountain troll-friend): large rounded body, small kind eyes, "
        "small mouth, hands much smaller than body suggesting careful gentleness, "
        "stands or sits in friendly posture next to small child or animal.",
    ),
    EnumValue(
        "adventurous-child",
        "Adventurous child: 5-8 year old appearance, simple clothing (overalls / "
        "dress / shorts and tee), open friendly face with simple two-dot eyes "
        "and small mouth, hair as a few simple curves (not detailed strands), "
        "carrying or pointing at something narrative.",
    ),
    EnumValue(
        "helpful-elephant",
        "Helpful elephant: rounded body, gently curling trunk (NOT raised in alarm), "
        "small kind eyes, large fan-shaped ears, often holding an object with trunk "
        "tip, posture peaceful.",
    ),
    EnumValue(
        "mischievous-mouse",
        "Mischievous mouse: small rounded body, large rounded ears, long thin tail, "
        "twinkling expression, often partly hidden behind something or peeking "
        "around a corner — the page invites the child to find the mouse.",
    ),
    EnumValue(
        "elderly-marathi-couple",
        "Elderly Marathi couple, ~70: Aajoba (grandpa) — silver hair, round glasses, "
        "gentle smile, cotton kurta + loose trousers, chappal sandals. Aaji (grandma) "
        "— silver hair in low bun, small bindi on forehead, cotton sari with pallu "
        "over left shoulder, mangalsutra, simple bangles, chappals. Both kind, "
        "rounded faces, simple eyes, small smiles.",
    ),
    EnumValue(
        "songbird-flock",
        "A flock of small Texas backyard birds: 4-6 HOUSE SPARROWS (small, round, "
        "short conical beak), 1-2 HOUSE FINCHES (similar size, slightly slimmer), "
        "optional 1 AMERICAN CROW (much larger, jet-black, blockier). Perched on "
        "fence/feeder/ground, anisodactyl feet, side-set eye, beak proportional.",
    ),
    EnumValue(
        "blue-jay-with-finches",
        "ONE BLUE JAY (clearly central, pointed crest raised on top of head, blue "
        "body with black necklace-band at throat, white wing-bars, sturdy beak, "
        "noticeably larger than sparrows) plus 2-3 small house sparrows or house "
        "finches at perch or ground level. The Jay's crest is the species ID — "
        "draw it obviously.",
    ),
    EnumValue(
        "cottontail-rabbit-and-kit",
        "Eastern Cottontail rabbit + baby kit: adult has long upright ears, large "
        "hind legs, signature white cotton-puff tail, side-set eyes. Kit is clearly "
        "smaller with shorter ears, still big eyes. NATURAL non-anthropomorphic "
        "posture (sitting on haunches or mid-hop). NO cartoon clothing, NO teeth.",
    ),
])

_CB_PROPS = EnumBank("props", [
    EnumValue("balloon",        "Single round balloon on a string, large fillable circle (sphere outline)."),
    EnumValue("teacup-and-saucer", "Teacup with handle on saucer with steam-curls rising — simple closed-shape steam swirls."),
    EnumValue("picnic-basket",  "Wicker picnic basket with handle, weave shown as simple crosshatch on the OUTSIDE only, contents (apple, sandwich) peeking out."),
    EnumValue("storybook-open", "Open storybook with two simple page-shapes and a couple of tiny line-suggestions of text."),
    EnumValue("paper-boat",     "Origami paper boat shape with simple folded triangles, sitting on water or held in hand."),
    EnumValue("flower-bouquet", "Small bouquet of 3-5 large rounded flowers (daisies / tulips), each flower-head a simple fillable shape."),
    EnumValue("lantern-glowing","Paper lantern with handle, simple geometric form (sphere / cylinder), no light rays drawn (line-art only — colorist supplies glow)."),
    EnumValue("kite-and-string","Diamond-shaped kite with bow-tail and long string snaking down to the character's hand."),
    EnumValue(
        "steel-thali-of-seed",
        "Round Indian steel thali (flat metal plate) held in two hands, brimming "
        "with bird-seed grains drawn as small simple ovals or dots. The thali's "
        "rim shown as a clean outline. A traditional Marathi household object "
        "used here for feeding garden birds.",
    ),
    EnumValue(
        "bird-feeder-tube",
        "Cylindrical tube bird-feeder hanging by a simple curved hook from a "
        "tree branch — vertical tube with two or three small perches sticking "
        "out near the base, a small dome cap on top. Inside, simple dot-patterns "
        "suggest seed. A common Texas backyard fixture.",
    ),
    EnumValue(
        "chai-cup-and-saucer",
        "Small Indian-style chai cup (cutting-chai size, no handle OR a tiny "
        "loop handle) on a small saucer, gentle steam curling up in a couple of "
        "simple loops. Held in one hand or resting on a side table.",
    ),
    EnumValue(
        "rocking-chair-side",
        "Wooden rocking chair shown in side profile: simple seat + back + two "
        "curved rocker rails on the ground, perhaps a folded shawl draped over "
        "the back. The chair is a stable supporting element, not the focus.",
    ),
    EnumValue("no-prop",        "No prop — character is the entire focus."),
])

_CB_SETTING = EnumBank("setting", [
    EnumValue(
        "enchanted-forest",
        "Enchanted forest: 3-5 stylized trees (tall trunk + canopy as a simple "
        "rounded cloud-shape), a few mushrooms with rounded caps, occasional "
        "flower or fern at base, fillable canopy regions, no overwhelming foliage.",
    ),
    EnumValue(
        "cozy-cottage-interior",
        "Cozy cottage interior: simple wood-plank floor (a few horizontal lines), "
        "rounded fireplace OR window with curtains, a chair or table, soft "
        "rounded shapes throughout, no clutter.",
    ),
    EnumValue(
        "magical-meadow",
        "Magical meadow: low rolling hill-line, scattered large flowers (3-7), "
        "a few clouds in the upper third drawn as rounded shapes, sun (simple "
        "circle, optionally with simple straight or wavy rays — NO realistic "
        "light effect), occasional butterfly.",
    ),
    EnumValue(
        "by-the-pond",
        "By a pond: pond shape as a rounded oval / kidney-shape, a few large "
        "lily-pads (rounded with notch), reeds at edge (3-5 vertical lines with "
        "leaf tips), perhaps a frog or fish-silhouette hinted just under the surface.",
    ),
    EnumValue(
        "treehouse-platform",
        "Treehouse platform: a large central tree trunk, wooden platform with "
        "simple plank-lines, a rope-ladder hanging down, a small house-shape on "
        "top with triangular roof, leaves around the platform.",
    ),
    EnumValue(
        "starry-night-rooftop",
        "Starry night rooftop: a few rooftops in simplified geometry, large "
        "moon (simple circle, with simple crater suggestion if pre-teen age), "
        "scattered stars (5-pointed shapes), one or two clouds in foreground "
        "softening the moon.",
    ),
    EnumValue(
        "village-square",
        "Village square: 3-5 simplified house-shapes in background (triangle roof "
        "+ square wall + door + window), cobble-hint on ground (sparse rounded "
        "shapes), occasional lamppost or tree, no crowd.",
    ),
    EnumValue(
        "mountain-cave",
        "Mountain cave entrance: arched cave opening, a few rocks at the mouth, "
        "mountain silhouette behind (simple triangular peak), occasional small "
        "plant. Cave interior remains lighter (not heavily blacked-in) so child "
        "can color it.",
    ),
    EnumValue(
        "texas-backyard-patio",
        "Texas suburban backyard OUTDOORS: wide spreading LIVE OAK tree (stout "
        "trunk + broad low canopy), wooden patio deck in foreground, horizontal-"
        "plank wooden fence at back, scattered bluebonnet wildflowers along edge, "
        "a hanging tube bird-feeder on a branch, open sky with simple rounded "
        "clouds. Outdoor scene — NOT an indoor room.",
    ),
])

_CB_TIME_OF_DAY = EnumBank("time_of_day", [
    EnumValue("morning",      "Morning: rising-sun shape on the horizon, a few birds as M-shaped silhouettes high in the frame."),
    EnumValue("midday",       "Midday: sun high in frame, small fluffy clouds, no shadows drawn (line-art convention)."),
    EnumValue("golden-hour",  "Golden hour: low sun (large circle near horizon), longer suggestive ground-lines (without rendering shadow as filled-in)."),
    EnumValue("dusk",         "Dusk: low sun, a few stars beginning, simple horizon line, soft cloud shapes."),
    EnumValue("night-moonlit","Night under moon: large moon, scattered stars, simple cloud silhouettes — NO dark fill, NO blacked-in sky (pages stay colorable)."),
    EnumValue("no-time",      "No time-of-day cue — focus is on character + setting, sky neutral."),
])

_CB_NARRATIVE_MOMENT = EnumBank("narrative_moment", [
    EnumValue(
        "first-meeting",
        "First meeting: two characters in the scene seeing each other for the "
        "first time, eye-contact between them, body language curious-but-cautious. "
        "The page is the inciting moment of a friendship.",
    ),
    EnumValue(
        "shared-secret",
        "Shared secret: two characters close together, one leaning to whisper or "
        "show something to the other, the second character's expression curious "
        "or surprised. Intimate two-character composition.",
    ),
    EnumValue(
        "problem-discovered",
        "Problem discovered: character has just noticed something — a missing "
        "item, a stuck creature, a broken bridge. Posture shows the noticing "
        "(reaching forward, leaning to look, hand to mouth in surprise).",
    ),
    EnumValue(
        "decision-to-help",
        "Decision-to-help: character mid-step toward the problem, expression "
        "determined-and-gentle, body language committed. The page captures the "
        "moment of moral decision.",
    ),
    EnumValue(
        "big-leap",
        "Big leap: character mid-action — jumping, climbing, reaching, the "
        "single most physical beat of the story. Body in mid-motion (one foot "
        "off the ground), expression brave.",
    ),
    EnumValue(
        "triumph-celebration",
        "Triumph: character has just succeeded — arms raised, friends gathered "
        "around, expression joyful. Group composition, eye-contact among multiple "
        "characters, shared moment.",
    ),
    EnumValue(
        "quiet-rest",
        "Quiet rest: after-adventure stillness — character sitting, leaning "
        "against tree or pillow, eyes half-closed or looking thoughtfully into "
        "distance. Page invites the child reader to slow down.",
    ),
    EnumValue(
        "bedtime-blessing",
        "Bedtime blessing: tucking-in moment — child or creature in bed, a "
        "loving figure leaning to kiss forehead, lamp or moon overhead. Closing "
        "spread of a goodnight book.",
    ),
    EnumValue(
        "wildlife-visit",
        "Wildlife visit: human character(s) feeding or peacefully observing "
        "wild animal visitors (birds at a feeder, rabbit in a yard, squirrel "
        "at a branch). Body language gentle, slow, attentive — the moment of "
        "shared peace between the human and the wild creature. Eye-contact "
        "between human and animal optional, but the human's attention is "
        "clearly on the animal.",
    ),
])

_CB_EMOTION = EnumBank("emotion", [
    EnumValue("curious",            "Curious: head tilted slightly, eyes wide, mouth small open or slightly puckered."),
    EnumValue("joyful",             "Joyful: eyes upturned-crescents OR wide-and-shining, mouth in a wide open smile."),
    EnumValue("worried-but-brave",  "Worried-but-brave: eyebrows raised inner edge, mouth small and set, body posture leaning forward."),
    EnumValue("gentle",             "Gentle: eyes half-lidded soft, mouth in a small closed smile, body posture soft and unhurried."),
    EnumValue("triumphant",         "Triumphant: arms raised or hands on hips, mouth wide in laughter, eyes bright."),
    EnumValue("sleepy-content",     "Sleepy-content: eyes nearly closed, small soft smile, body relaxed."),
    EnumValue("determined",         "Determined: eyebrows lowered slightly, mouth set, eyes fixed forward, body forward-leaning."),
    EnumValue("surprised-delighted","Surprised-delighted: eyes round and wide, mouth in a small 'O', hands raised to mouth or cheeks."),
])

_CB_LAYOUT = EnumBank("layout", [
    EnumValue(
        "centered-portrait",
        "Centered portrait: subject occupies the central 60% of the frame, "
        "vertical arrangement, simple supporting elements at periphery. "
        "Maximum colorability — clear figure, large fillable shapes around it.",
    ),
    EnumValue(
        "environmental-wide",
        "Environmental-wide: subject occupies 25-40% of frame, setting fills "
        "the rest. Sense of place dominates. Used when the setting itself is "
        "a character (the enchanted forest, the starry rooftop).",
    ),
    EnumValue(
        "close-detail",
        "Close-detail: head-and-shoulders or hand-and-object close-up. Used "
        "for emotional beats (a tear, a held flower, two characters touching "
        "noses). Background simplified to a few suggestion-lines.",
    ),
    EnumValue(
        "two-figure-balance",
        "Two-figure balance: two characters arranged with visual weight balanced "
        "(left and right, OR foreground and background), neither dominant. Used "
        "for friendship, dialogue, shared-discovery beats.",
    ),
    EnumValue(
        "vignette-rounded",
        "Vignette-rounded: the entire scene contained within a soft rounded "
        "frame (oval or rectangle with rounded corners), white space outside "
        "the vignette. Storybook-spread feel.",
    ),
])

_CB_FRAMING = EnumBank("framing", [
    EnumValue("extreme-wide",  "Extreme wide framing: subject small in frame, entire setting visible, sense of scale."),
    EnumValue("wide",          "Wide framing: subject full-body visible, setting around them in midground."),
    EnumValue("medium",        "Medium framing: subject from waist or hip up, setting hinted at edges."),
    EnumValue("close-up",      "Close-up framing: head-and-shoulders only, expression dominant."),
])

_CB_DENSITY = EnumBank("environmental_density", [
    EnumValue(
        "sparse",
        "Sparse: 3-5 named elements total in the scene, generous white space, "
        "any single page reads in 2 seconds. Toddler-appropriate.",
    ),
    EnumValue(
        "balanced",
        "Balanced: 7-12 named elements, foreground + midground visible, some "
        "background hint. Kids-appropriate.",
    ),
    EnumValue(
        "rich",
        "Rich: 15-25 named elements, multiple layered planes, hidden details "
        "for re-reading. Pre-teen-appropriate.",
    ),
])


@dataclass(frozen=True)
class CBSubjectConfig:
    subject: str                                  # free text describing the central scene
    character_archetype: str = "curious-bear-cub"
    emotion: str = "curious"
    props: str = "no-prop"

@dataclass(frozen=True)
class CBSceneConfig:
    setting: str = "magical-meadow"
    time_of_day: str = "no-time"
    environmental_density: str = "balanced"

@dataclass(frozen=True)
class CBNarrativeConfig:
    moment: str = "first-meeting"
    story_beat: str = ""                          # optional one-line free text continuing the moment

@dataclass(frozen=True)
class CBCompositionConfig:
    layout: str = "centered-portrait"
    framing: str = "medium"
    character_count: int = 1                      # 1-4 expected; >4 → warning, allowed for triumph beats

@dataclass(frozen=True)
class CBStyleConfig:
    tradition: str = "mo-willems-minimal"
    age_range: str = "kids-6-9"

@dataclass(frozen=True)
class ChildrensColoringBookConfig:
    subject: CBSubjectConfig
    scene: CBSceneConfig = field(default_factory=CBSceneConfig)
    narrative: CBNarrativeConfig = field(default_factory=CBNarrativeConfig)
    composition: CBCompositionConfig = field(default_factory=CBCompositionConfig)
    style: CBStyleConfig = field(default_factory=CBStyleConfig)
    seed: int = 1


class ChildrensColoringBookEngine(Engine):
    name: ClassVar[str] = "childrens-coloring-book"
    config_cls: ClassVar[type] = ChildrensColoringBookConfig
    masters: ClassVar[tuple[str, ...]] = (
        "Mo Willems — Elephant & Piggie series (2007-2017): minimalist line, maximum emotion through 2-dot eyes",
        "Sandra Boynton — Moo, Baa, La La La! (1982): chunky whimsical animals, rhythmic compositional repetition",
        "Eric Carle — The Very Hungry Caterpillar (1969): bold thick outlines, large fillable color fields",
        "Beatrix Potter — The Tale of Peter Rabbit (1902): anatomically naturalistic small mammals in countryside dress",
        "Hayao Miyazaki — My Neighbor Totoro (1988) storyboards: clean confident pen-line, restrained environmental detail",
    )
    palette_60_30_10 = {
        "dominant":  {"hex": "#FFFFFF", "role": "pure white paper / fillable region — 95% of pixels"},
        "secondary": {"hex": "#000000", "role": "black ink outline — closed, continuous, age-appropriate weight"},
        "accent":    {"hex": "#000000", "role": "no chromatic accent (line art); accent only via colorist's hand"},
    }
    default_runtime = {"model": "dev", "steps": 32, "guidance": 5.5}
    # Two strong Coloring-Book LoRAs in our curation — picking prithivMLmods
    # (the more-downloaded, conservative one). The engine's prompt already
    # contains "coloring book page" so the trigger phrase is honoured.
    default_lora_stack: ClassVar[tuple[tuple[str, float], ...]] = (
        ("coloring-book-prithiv/lora.safetensors", 0.80),
    )
    engine_negatives: ClassVar[tuple[str, ...]] = (
        "photorealism", "photographic detail", "complex shading", "gradient fill",
        "shaded interior", "crosshatched interior fill", "rendered shadow",
        "colored", "color illustration", "RGB fill", "saturated tone",
        "filled-in regions", "grey fill", "tonal modeling",
        "scary expression", "snarling", "bared teeth", "sharp fanged teeth",
        "menacing posture", "predatory glare", "wide-open mouth showing tongue and teeth",
        "gore", "blood", "violence", "weapon", "knife", "fire-as-threat",
        "anatomically wrong limbs", "extra fingers", "fused fingers", "extra toes",
        "AI glow", "halation glow", "soft focus haze", "milky highlight glow",
        "watercolor smudge", "ink wash", "ink bleed",
        "watermark", "signature", "artist tag", "text overlay", "page number",
        "rough sketch", "scribble", "messy broken lines", "discontinuous outlines",
        "thin spider-web lines", "wavering uncertain line",
        "manga giant chibi eyes", "anime stylization",
        "Disney-3D plastic look", "Pixar volumetric render",
        "horror tone", "creepypasta", "uncanny smile",
    )
    TRADITION = _CB_TRADITION
    AGE_RANGE = _CB_AGE_RANGE
    CHARACTER_ARCHETYPE = _CB_CHARACTER_ARCHETYPE
    PROPS = _CB_PROPS
    SETTING = _CB_SETTING
    TIME_OF_DAY = _CB_TIME_OF_DAY
    NARRATIVE_MOMENT = _CB_NARRATIVE_MOMENT
    EMOTION = _CB_EMOTION
    LAYOUT = _CB_LAYOUT
    FRAMING = _CB_FRAMING
    DENSITY = _CB_DENSITY

    @classmethod
    def build(cls, config: ChildrensColoringBookConfig) -> Directive:
        sub = config.subject
        scn = config.scene
        nar = config.narrative
        cmp = config.composition
        st = config.style

        tradition = cls.TRADITION.validate(st.tradition)
        age = cls.AGE_RANGE.validate(st.age_range)
        archetype = cls.CHARACTER_ARCHETYPE.validate(sub.character_archetype)
        emotion = cls.EMOTION.validate(sub.emotion)
        props = cls.PROPS.validate(sub.props)
        setting = cls.SETTING.validate(scn.setting)
        tod = cls.TIME_OF_DAY.validate(scn.time_of_day)
        density = cls.DENSITY.validate(scn.environmental_density)
        moment = cls.NARRATIVE_MOMENT.validate(nar.moment)
        layout = cls.LAYOUT.validate(cmp.layout)
        framing = cls.FRAMING.validate(cmp.framing)

        require(1 <= cmp.character_count <= 6,
                f"character_count must be 1-6 (got {cmp.character_count}). "
                f"Coloring-book pages with >6 named figures become unreadable for the target age.")

        # Domain invariants — encoded rules the genre demands.
        # 1. Toddler-age pages must NOT be rich-density.
        if st.age_range == "toddler-3-5" and scn.environmental_density == "rich":
            raise ValueError(
                "invariant: age_range=toddler-3-5 cannot use environmental_density=rich. "
                "Toddler pages need sparse compositions (3-5 elements). Use density=sparse, "
                "or raise age_range to kids-6-9 / pre-teen-10-12."
            )
        # 2. Toddler-age cannot use the high-detail Miyazaki tradition.
        if st.age_range == "toddler-3-5" and st.tradition == "miyazaki-storyboard":
            raise ValueError(
                "invariant: age_range=toddler-3-5 cannot use tradition=miyazaki-storyboard. "
                "Miyazaki line-density is age-9+. For toddlers use mo-willems-minimal, "
                "sandra-boynton-whimsical, or eric-carle-bold."
            )
        # 3. The two-character beats need at least 2 characters.
        if nar.moment in ("first-meeting", "shared-secret", "bedtime-blessing") and cmp.character_count < 2:
            raise ValueError(
                f"invariant: narrative_moment={nar.moment!r} requires character_count >= 2. "
                f"Increase character_count or pick a single-character moment "
                f"(problem-discovered / decision-to-help / big-leap / quiet-rest)."
            )
        # 4. Triumph-celebration is a group beat — soft check, allow 1+ but suggest >=3.
        #    (No raise; suggestion lives in the prompt body.)

        clean_subject = normalize_subject(sub.subject)

        audit = {
            "tradition": tradition.description,
            "age_range": age.description,
            "character_archetype": archetype.description,
            "emotion": emotion.description,
            "props": props.description,
            "setting": setting.description,
            "time_of_day": tod.description,
            "environmental_density": density.description,
            "narrative_moment": moment.description,
            "layout": layout.description,
            "framing": framing.description,
            "character_count": cmp.character_count,
            "story_beat": nar.story_beat or "(none)",
        }

        # Compose the dense prompt.
        story_beat_line = (
            f"STORY BEAT: {nar.story_beat.strip()}." if nar.story_beat.strip() else ""
        )

        # T5-XXL budget — keep total prompt under ~2200 chars (~550 tokens).
        # Subject + composition come FIRST so they never get truncated; style and
        # rendering rules come after.
        prop_line = f" Holding/with: {props.description}" if props.key != "no-prop" else ""
        story_beat_line = f" {nar.story_beat.strip()}" if nar.story_beat.strip() else ""
        plural = "" if cmp.character_count == 1 else "s"

        # Trim the tradition description to its first ~400 chars so the page-art
        # rules + subject still fit in the T5 window.
        tradition_short = tradition.description
        if len(tradition_short) > 420:
            tradition_short = tradition_short[:420].rsplit(". ", 1)[0] + "."

        # T5-XXL budget — keep total prompt under ~2200 chars (~550 tokens).
        # Lead with the line-art directive (FLUX otherwise colorizes scenes with
        # human characters + rich settings), then the subject, then style detail.
        prompt_parts = [
            "COLORING BOOK PAGE — black ink line drawing on a pure white page. "
            "NO COLOR anywhere. NO shading, NO gradient, NO grey, NO interior fill. "
            "Every region is a closed fillable outline a child colors inside. "
            "Single-color black ink only. White background edge-to-edge.",

            f"SCENE TO DRAW: {clean_subject}.{story_beat_line}",

            f"CHARACTER DETAIL: {archetype.description}",

            f"EMOTION: {emotion.description}{prop_line}",

            f"SETTING: {setting.description} Time: {tod.description}",

            f"COMPOSITION: {layout.description} {framing.description} "
            f"Exactly {cmp.character_count} named figure{plural} in the scene. "
            f"Density: {density.description}",

            f"DRAWING STYLE: {tradition.key} — {tradition_short}",

            "LINE-ART RULES: closed continuous outlines; uniform line weight "
            f"({age.key}-appropriate); PURE WHITE backgrounds (no grey/black fill); "
            "texture only as sparse edge marks (NEVER interior hatching); "
            "simple eyes — NEVER manga giant-eye sparkle, NEVER realistic irises; "
            "no fangs, no snarls, no predatory expression. NO photorealism, "
            "NO 3D-render, NO AI-glow halo, NO watercolor wash. ABSOLUTELY MONOCHROME.",

            "PAGE FORMAT: white background edge-to-edge, ~10% margin, NO frame, "
            "NO border, NO watermark, NO text overlay, NO page number.",
        ]
        prompt = "\n\n".join(p for p in prompt_parts if p)

        return Directive(
            engine=cls.name,
            positive=prompt,
            negatives=tuple(cls.engine_negatives),
            palette_60_30_10=dict(cls.palette_60_30_10),
            runtime=dict(cls.default_runtime),
            seed=int(config.seed),
            audit=audit,
            config=_config_to_dict(config),
            masters=cls.masters,
        )


# ════════════════════════════════════════════════════════════════════════════
# MandalaArtEngine — FLUX-driven SUBJECT mandalas ("make a mandala whale")
# ════════════════════════════════════════════════════════════════════════════
#
# Different from `forge mandala` (procedural polar geometry, no subject).
# This engine lets you say `--subject "whale"` and get a coloring-book-grade
# mandala where the subject is the central organizing element — its body
# filled with intricate symmetric line-patterns, or its silhouette built
# from radially-arranged motifs.


_MA_TRADITION = EnumBank("tradition", [
    EnumValue(
        "zentangle-organic",
        "Zentangle method (Maria Thomas + Rick Roberts, 2003-present): dense "
        "organic micro-pattern fills inside every closed shape. Each region of "
        "the subject is filled with a DIFFERENT repeating pattern — dots, "
        "stripes, scales, swirls, leaf-veins, brickwork, fish-scales, "
        "honeycomb, crosshatch. The pattern fills are CLOSED-LINE only "
        "(decorative line work bounded inside outlines, NOT shaded fills).",
        masters=("Maria Thomas + Rick Roberts — Zentangle (2003-)", "Johanna Basford — Secret Garden (2013), Lost Ocean (2015)"),
    ),
    EnumValue(
        "sacred-geometry",
        "Sacred-geometry tradition: precise compass-and-straightedge composition, "
        "interlocking circles (Flower of Life, Seed of Life), interlocking "
        "triangles (Sri Yantra style), hexagons + dodecagons, golden-ratio "
        "spiral motifs, exact rotational symmetry, mathematical precision over "
        "organic flow.",
        masters=("Sri Yantra (ancient Vedic)", "Flower of Life (cross-cultural sacred-geometry tradition)", "Metatron's Cube"),
    ),
    EnumValue(
        "henna-mehndi",
        "Indian/Middle-Eastern henna-mehndi decorative vocabulary: paisley "
        "(mango-shape) motifs, lotus rosettes, vine + leaf curls, peacock "
        "feather fans, jali (lattice) infill, dense flowing organic line. "
        "Bridal-grade complexity in places, breathing room elsewhere.",
        masters=("traditional Rajasthani + Punjabi mehndi designs", "Moroccan + Persian henna traditions"),
    ),
    EnumValue(
        "madhubani-mandala",
        "Madhubani / Mithila folk tradition translated to mandala: double-line "
        "border around every shape, geometric + floral fill patterns (cross-hatch, "
        "dot-clusters, leaf-veins) inside the outlines, classic Madhubani motifs "
        "(fish, lotus, sun, bird, snake) arranged symmetrically. Folk-art "
        "naivete with technical density.",
        masters=("Sita Devi (Padma Shri 1981)", "Ganga Devi", "Bharti Dayal"),
    ),
    EnumValue(
        "floral-art-nouveau",
        "Alphonse Mucha + Vienna Secession art-nouveau botanical: flowing "
        "tendril-line decoration, hair-as-vine motifs, decorative botanical "
        "framing (lily, rose, ivy, wisteria), Mucha-style halo behind the "
        "subject, ornamental but never crowded. The subject is enthroned by "
        "the decoration.",
        masters=("Alphonse Mucha — Job (1896), The Seasons (1896)", "Gustav Klimt — Tree of Life (1909)"),
    ),
])

_MA_TREATMENT = EnumBank("treatment", [
    EnumValue(
        "subject-silhouette-filled",
        "The subject is a clear silhouette / outline, and the INTERIOR of that "
        "outline is filled with intricate mandala patterns. Outside the subject's "
        "outline: white space OR a simple radial background. Best for clear "
        "animal subjects (whale, lion, elephant, owl).",
    ),
    EnumValue(
        "subject-at-center-rings",
        "The subject sits at the exact center of the canvas; concentric "
        "decorative mandala rings build OUTWARD from it. The subject itself is "
        "rendered cleanly (not pattern-filled); the mandala is the frame. Best "
        "for symbolic singular subjects (lotus, eye, sun, tree).",
    ),
    EnumValue(
        "subject-radial-composed",
        "Multiple instances of the subject (or its motifs) arranged in a "
        "rotationally-symmetric pattern around a central axis — like petals on "
        "a flower. The subject becomes the unit-tile of the mandala. Best for "
        "small repeatable motifs (butterfly, fish, leaf, bird).",
    ),
    EnumValue(
        "subject-emerging-mandala",
        "The subject GROWS OUT of the mandala — for example, a tree's roots are "
        "the central mandala and its branches form the outer rings; or a "
        "phoenix rises from a flame-mandala base. Subject and mandala are one "
        "organic whole.",
    ),
])

_MA_SYMMETRY = EnumBank("symmetry", [
    EnumValue(
        "bilateral",
        "Bilateral (left-right mirror) symmetry only. Best when the subject is "
        "an animal or figure that naturally reads bilaterally (whale, owl, "
        "elephant, lion head, dragon).",
    ),
    EnumValue(
        "4-fold-rotational",
        "4-fold rotational symmetry — composition rotates around the center "
        "every 90°. Common for cross-pattern mandalas and quadripartite designs.",
    ),
    EnumValue(
        "6-fold-rotational",
        "6-fold rotational symmetry (every 60°). Snowflake / star-of-david / "
        "honeycomb logic.",
    ),
    EnumValue(
        "8-fold-rotational",
        "8-fold rotational symmetry (every 45°). The classical Indian + "
        "Tibetan mandala count.",
    ),
    EnumValue(
        "12-fold-rotational",
        "12-fold rotational symmetry (every 30°). Common for floral mandalas "
        "and clock-face arrangements.",
    ),
    EnumValue(
        "16-fold-rotational",
        "16-fold rotational symmetry (every 22.5°). High-density mandala "
        "register.",
    ),
    EnumValue(
        "kaleidoscope",
        "Full dihedral kaleidoscope — radial PLUS reflective mirror symmetry. "
        "The whole image folds onto itself any way you slice it.",
    ),
])

_MA_COMPLEXITY = EnumBank("complexity", [
    EnumValue(
        "medium-adult",
        "Medium complexity: ~30-60 distinct closed regions. Balance between "
        "detail and colorability. Pleasant for an adult coloring session of "
        "30-60 minutes.",
    ),
    EnumValue(
        "high-meditation",
        "High complexity: ~80-150 closed regions, dense pattern-fill. A "
        "meditation-grade coloring page that takes 2-4 hours. Adult coloring "
        "book bestseller density.",
    ),
    EnumValue(
        "extreme-zentangle",
        "Extreme zentangle complexity: 200+ closed regions, every interior "
        "filled with a distinct micro-pattern. Professional adult coloring "
        "book grade; takes a full evening to color one page.",
    ),
])

_MA_BORDER = EnumBank("border", [
    EnumValue(
        "concentric-rings",
        "Multiple concentric circular borders around the central mandala, each "
        "ring carrying a different repeating motif (dot-band, vine-band, "
        "geometric-band). The outermost ring is the largest decorative band.",
    ),
    EnumValue(
        "outer-frame-square",
        "A square outer frame around the circular mandala, with corner-motifs "
        "filling the four corner spaces between circle and square (often "
        "floral or geometric).",
    ),
    EnumValue(
        "freeform-bleed",
        "No formal outer border — the mandala bleeds toward the canvas edges "
        "with motifs softening to white space at the periphery. Loose feel.",
    ),
    EnumValue(
        "hexagonal-frame",
        "A hexagonal outer frame (sacred-geometry style) containing the inner "
        "circular composition.",
    ),
])


@dataclass(frozen=True)
class MASubjectConfig:
    subject: str                              # e.g. "whale", "lion head", "lotus", "tree of life"
    treatment: str = "subject-silhouette-filled"

@dataclass(frozen=True)
class MAStyleConfig:
    tradition: str = "zentangle-organic"
    complexity: str = "high-meditation"
    symmetry: str = "bilateral"

@dataclass(frozen=True)
class MACompositionConfig:
    border: str = "concentric-rings"

@dataclass(frozen=True)
class MandalaArtConfig:
    subject: MASubjectConfig
    style: MAStyleConfig = field(default_factory=MAStyleConfig)
    composition: MACompositionConfig = field(default_factory=MACompositionConfig)
    seed: int = 1


class MandalaArtEngine(Engine):
    name: ClassVar[str] = "mandala-art"
    config_cls: ClassVar[type] = MandalaArtConfig
    masters: ClassVar[tuple[str, ...]] = (
        "Johanna Basford — Secret Garden (2013), Lost Ocean (2015): pioneered the modern subject-mandala adult coloring genre",
        "Maria Thomas + Rick Roberts — Zentangle method (2003-): organic micro-pattern fill discipline",
        "Sri Yantra (Vedic) + Flower of Life: sacred-geometry exact-symmetry tradition",
        "Alphonse Mucha — Job (1896): art-nouveau floral framing of a central subject",
        "Sita Devi (Madhubani / Mithila, Padma Shri 1981): folk-mandala narrative motif tradition",
    )
    palette_60_30_10 = {
        "dominant":  {"hex": "#FFFFFF", "role": "pure white paper / fillable region — 90% of pixels"},
        "secondary": {"hex": "#000000", "role": "black ink line — fine, precise, closed continuous outlines"},
        "accent":    {"hex": "#000000", "role": "no chromatic accent (line art); accent via colorist's hand"},
    }
    default_runtime = {"model": "dev", "steps": 36, "guidance": 7.5}
    engine_negatives: ClassVar[tuple[str, ...]] = (
        # Color / shading killers
        "color", "colored", "color illustration", "RGB fill", "saturated tone",
        "grey fill", "tonal shading", "gradient", "interior shading",
        "photorealism", "photographic detail", "rendered shadow",
        "3D rendered", "Disney plastic", "Pixar volumetric",
        "anime stylization", "manga giant chibi eyes",
        "AI glow", "halation glow", "soft focus haze", "milky highlight",
        "watercolor wash", "ink wash bleed",
        # Page-format killers
        "watermark", "signature", "artist tag", "text overlay", "page number",
        "scribbled rough sketch", "messy uncertain line",
        "menacing expression on subject", "predatory teeth", "scary",
        "gore", "blood", "violence",
        # Ornamental-design failure modes (from the design primer)
        "uniform pattern density across entire body", "every inch filled equally",
        "no breathing zones", "no whitespace", "claustrophobic over-rendered",
        "pattern spilling outside silhouette", "ornament overwhelming anatomy",
        "subject unrecognizable under patterns", "jagged silhouette edge",
        "tiny silhouette protrusions from edge decoration",
        "robotic mirror symmetry", "rigid pattern grid",
        "ten competing focal points", "no visual hierarchy",
        "decorated eye", "eye crowded by patterns", "patterns colliding with eye",
        "tangent line collisions", "trapped tiny spaces",
        "ultra-thin disappearing lines", "microscopic unreadable regions",
        "all regions the same size", "all tiny regions",
        "patterns ignoring anatomy direction", "patterns running cross-grain",
        "anxious busy chaotic feel",
    )
    TRADITION = _MA_TRADITION
    TREATMENT = _MA_TREATMENT
    SYMMETRY = _MA_SYMMETRY
    COMPLEXITY = _MA_COMPLEXITY
    BORDER = _MA_BORDER

    @classmethod
    def build(cls, config: MandalaArtConfig) -> Directive:
        sub = config.subject
        st = config.style
        cmp = config.composition

        tradition = cls.TRADITION.validate(st.tradition)
        treatment = cls.TREATMENT.validate(sub.treatment)
        symmetry = cls.SYMMETRY.validate(st.symmetry)
        complexity = cls.COMPLEXITY.validate(st.complexity)
        border = cls.BORDER.validate(cmp.border)

        # Invariant: subject-radial-composed needs rotational symmetry, not bilateral.
        if sub.treatment == "subject-radial-composed" and st.symmetry == "bilateral":
            raise ValueError(
                "invariant: treatment=subject-radial-composed needs rotational symmetry "
                "(4-/6-/8-/12-/16-fold-rotational or kaleidoscope). Bilateral mirrors "
                "the subject left-right but doesn't repeat it around the center. "
                "Pick a rotational symmetry, OR change treatment to "
                "subject-silhouette-filled / subject-at-center-rings."
            )
        # Invariant: sacred-geometry tradition reads best with rotational symmetry, not bilateral.
        if st.tradition == "sacred-geometry" and st.symmetry == "bilateral":
            raise ValueError(
                "invariant: sacred-geometry tradition is rotational by construction "
                "(Sri Yantra, Flower of Life, etc.) — pair with 6-/8-/12-fold-rotational "
                "or kaleidoscope, not bilateral."
            )

        clean_subject = normalize_subject(sub.subject, max_chars=120)

        audit = {
            "tradition": tradition.description,
            "treatment": treatment.description,
            "symmetry": symmetry.description,
            "complexity": complexity.description,
            "border": border.description,
        }

        # T5-XXL prompt budget — lead with B&W framing, subject, primary rule,
        # then the design-primer principles (60/30/10, hierarchy, breathing zones).
        # All critical guidance lands inside the first ~2000 chars.
        tradition_short = tradition.description
        if len(tradition_short) > 280:
            tradition_short = tradition_short[:280].rsplit(". ", 1)[0] + "."

        prompt_parts = [
            "ORNAMENTAL COLORING-BOOK MANDALA PAGE — black ink line art on pure "
            "white paper. NO color, NO shading, NO grey, NO gradient fills. "
            "Decorative pattern is line-only, bounded inside closed outlines.",

            f"CENTRAL SUBJECT: {clean_subject}.",

            f"PRIMARY RULE: the viewer must read '{clean_subject}' FIRST, then "
            "'beautiful ornament' second. The subject's silhouette and anatomy "
            "are SACRED — patterns SUPPORT them, never overwhelm. At 150px "
            f"thumbnail the image must still read instantly as {clean_subject}.",

            f"TREATMENT: {treatment.description}",

            "DENSITY — BE SPATIAL: leave AT LEAST 60% of the canvas as PURE "
            "WHITE PAPER. Specifically: the subject's BELLY / LOWER UNDERSIDE "
            "stays MOSTLY WHITE (only a few sparse flow-lines, NO pattern fill). "
            "The background AROUND the subject stays WHITE PAPER. Ornament "
            "concentrates in roughly 30% of the canvas (head sides, upper "
            "flanks, supporting flow-ribbons). HERO detail concentrates in only "
            "10% (forehead, eye area, tail tip, fin tips). DO NOT fill the "
            "belly with patterns. DO NOT cover the whole subject with uniform "
            "ornamentation.",

            "5-LEVEL VISUAL HIERARCHY (each level a FINER line than the one "
            "above): L1 outer silhouette — thickest, smooth, unbroken contour; "
            "L2 major anatomical divisions (head / body / fins / tail) — medium "
            "weight; L3 large ornamental ribbons that flow ALONG anatomy — "
            "medium; L4 pattern regions — thinner; L5 micro-texture — finest, "
            "ONLY in focal zones. Most failed mandalas start at L5 everywhere.",

            "BREATHING ZONES (mandatory): large unornamented or low-density "
            "regions, especially on the belly and lower torso, are part of the "
            "design — NOT unfinished. They create luxury, focus, calm.",

            "FOCAL POINTS — exactly THREE: ONE primary (subject's eye / head / "
            "forehead) plus TWO secondary (tail decoration + front fin, or the "
            "subject's equivalents). NEVER ten competing focal points.",

            "PATTERN FLOW: every pattern stroke follows the subject's natural "
            "anatomical curves — hydrodynamic for fish/whales, radiating for "
            "lions/owls, growth-direction for plants. NO rigid grids, NO random "
            "angular fragmentation, NO patterns running cross-grain to the form.",

            "PATTERN VOCABULARY: 3-5 systems MAX (e.g., scales + flowing "
            "ribbons + spirals + dots + wave geometry). Repetition + rhythm. "
            "Never random pattern mixing.",

            "EYE: clean shape, readable pupil, generous clear space around it. "
            "Patterns DO NOT crowd or collide with the eye. The eye carries the "
            "subject's intelligence — gentle, aware, ancient.",

            "REGION SIZES: 10-20% small + 50-60% medium + 20-30% large fillable "
            "regions. Large regions let the colorist breathe and complete "
            "satisfyingly.",

            "EMOTIONAL TONE: calm, sacred, intelligent, graceful, timeless. "
            "The subject should feel like a wise ancient being CARRYING sacred "
            "patterns — never a pattern sheet shaped like a subject. NOT "
            "chaotic, NOT anxious, NOT over-rendered.",

            f"SYMMETRY: {symmetry.description} Overall balance is mandatory; "
            "organic asymmetric variation within the symmetry is welcomed — "
            "natural forms are never robotic-mirror-perfect.",

            f"COMPLEXITY TIER: {complexity.description}",

            f"DECORATIVE TRADITION: {tradition.key} — {tradition_short}",

            f"OUTER BORDER / FRAME: {border.description}",

            "LINE DISCIPLINE: VARIED line weights (thickest at silhouette, "
            "finest at micro-detail). Technical-pen ink feel, clean closed "
            "outlines, no broken or wandering strokes. NO photorealism, NO 3D "
            "render, NO AI-glow halo, NO watercolor wash. Absolutely monochrome "
            "black line on white paper.",

            "PAGE FORMAT: pure white background edge-to-edge, ~8% margin, NO "
            "outer frame beyond the mandala's own border, NO watermark, NO "
            "text, NO page number, NO signature.",
        ]
        prompt = "\n\n".join(prompt_parts)

        return Directive(
            engine=cls.name,
            positive=prompt,
            negatives=tuple(cls.engine_negatives),
            palette_60_30_10=dict(cls.palette_60_30_10),
            runtime=dict(cls.default_runtime),
            seed=int(config.seed),
            audit=audit,
            config=_config_to_dict(config),
            masters=cls.masters,
        )


# ════════════════════════════════════════════════════════════════════════════
# Registry + entry points
# ════════════════════════════════════════════════════════════════════════════


def _config_to_dict(config: Any) -> dict[str, Any]:
    """Recursively convert nested dataclass configs to a JSON-safe dict."""
    from dataclasses import is_dataclass
    if is_dataclass(config):
        return asdict(config)
    return dict(config) if hasattr(config, "__iter__") else config


ENGINES: dict[str, type[Engine]] = {
    NoirCinematographyEngine.name: NoirCinematographyEngine,
    WildlifePhotorealismEngine.name: WildlifePhotorealismEngine,
    ImpressionistPaintingEngine.name: ImpressionistPaintingEngine,
    IndianClassicalEngine.name: IndianClassicalEngine,
    ChildrensColoringBookEngine.name: ChildrensColoringBookEngine,
    MandalaArtEngine.name: MandalaArtEngine,
}


def list_engines() -> list[str]:
    return sorted(ENGINES)


def get_engine(name: str) -> type[Engine]:
    if name not in ENGINES:
        raise ValueError(
            f"unknown engine {name!r}; choose one of {', '.join(list_engines())}"
        )
    return ENGINES[name]


def describe_engine(name: str) -> dict[str, Any]:
    return get_engine(name).describe()


def build(name: str, config: Any) -> Directive:
    """Build a Directive from a pre-constructed config dataclass."""
    return get_engine(name).build(config)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        for n in list_engines():
            print(n)
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "describe":
        if len(sys.argv) < 3:
            print("usage: style_engines.py describe <engine>", file=sys.stderr); sys.exit(2)
        print(json.dumps(describe_engine(sys.argv[2]), indent=2, ensure_ascii=False))
        sys.exit(0)
    # Demo build with sensible defaults.
    eng = get_engine(cmd)
    cfg = eng.config_cls.__init__.__doc__  # noqa
    raise SystemExit(
        "Demo build requires constructing the config dataclass programmatically "
        "(nested dataclasses don't have a single-arg path). Use the Python API."
    )
