#!/usr/bin/env python3
"""Product mockup compositing helpers for Forge.

This module keeps mockups deterministic and local: a transparent print-art PNG
goes onto one or more product templates using a small JSON placement manifest.
It intentionally avoids PSD/Smart Object parsing so Forge can batch storefront
images without Photoshop, cloud APIs, or fragile template scripts.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import urllib.request
from urllib.error import URLError
from base64 import b64encode
from dataclasses import dataclass
from html import escape
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".svg"}


TSHIRT_COLOR_VARIANTS: list[tuple[str, str]] = [
    ("white", "#F8F8F4"),
    ("natural cream", "#EFE3C8"),
    ("ivory", "#F5EFE3"),
    ("ash", "#D7D4CC"),
    ("heather grey", "#AFAFA8"),
    ("graphite", "#4B4A46"),
    ("black", "#101010"),
    ("charcoal", "#252525"),
    ("navy", "#14213D"),
    ("indigo", "#203A6B"),
    ("royal blue", "#2254A5"),
    ("steel blue", "#557A95"),
    ("denim", "#466B88"),
    ("sky blue", "#86B7D7"),
    ("ice blue", "#D8E9F1"),
    ("teal", "#1E6F6A"),
    ("turquoise", "#2BA7A0"),
    ("seafoam", "#A8D7C5"),
    ("forest green", "#1F4A3F"),
    ("emerald", "#16724F"),
    ("kelly green", "#24824B"),
    ("olive", "#626B3D"),
    ("sage", "#A9B89B"),
    ("mint", "#BFE3C2"),
    ("lime", "#BFD46F"),
    ("maroon", "#5A182A"),
    ("burgundy", "#6C2335"),
    ("cranberry", "#9A2E45"),
    ("red", "#B83232"),
    ("coral", "#E06A58"),
    ("salmon", "#E9967A"),
    ("pink", "#E7A8BC"),
    ("hot pink", "#D94382"),
    ("lavender", "#B9A4D8"),
    ("purple", "#5C3B82"),
    ("plum", "#4E254E"),
    ("eggplant", "#39243B"),
    ("orange", "#D96E28"),
    ("burnt orange", "#A65324"),
    ("rust", "#8D3F24"),
    ("terracotta", "#B7654A"),
    ("gold", "#D4A62A"),
    ("mustard", "#B9902F"),
    ("sand", "#D7C4A2"),
    ("tan", "#B99A72"),
    ("stone", "#B9B1A4"),
    ("mocha", "#6B5545"),
    ("brown", "#5A3A1F"),
    ("chocolate", "#342017"),
    ("peach", "#F1B18F"),
]

CURATED_OPEN_SVG_COMMONS_SOURCES = [
    {
        "id": "wikimedia-tshirt-silhouette",
        "title": "T-shirt silhouette.svg",
        "product": "tshirt",
        "download_url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/T-shirt%20silhouette.svg",
        "source_url": "https://commons.wikimedia.org/wiki/File:T-shirt_silhouette.svg",
        "author": "Naberacka",
        "publisher": "Wikimedia Commons",
        "license": "CC0 1.0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "credit": "T-shirt silhouette.svg by Naberacka via Wikimedia Commons, CC0 1.0.",
        "placement": {"x": 0.30, "y": 0.34, "width": 0.40, "height": 0.32},
    },
    {
        "id": "wikimedia-t-shirt",
        "title": "T-Shirt.svg",
        "product": "tshirt",
        "download_url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/T-Shirt.svg",
        "source_url": "https://commons.wikimedia.org/wiki/File:T-Shirt.svg",
        "author": "Superwikifan / ChristianGlaeser",
        "publisher": "Wikimedia Commons",
        "license": "CC BY-SA 3.0 / GFDL",
        "license_url": "https://creativecommons.org/licenses/by-sa/3.0/",
        "credit": "T-Shirt.svg by Superwikifan/ChristianGlaeser via Wikimedia Commons, CC BY-SA 3.0 / GFDL.",
        "placement": {"x": 0.31, "y": 0.34, "width": 0.38, "height": 0.32},
    },
    {
        "id": "wikimedia-crat-tshirt",
        "title": "Crat T-shirt.svg",
        "product": "tshirt",
        "download_url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Crat%20T-shirt.svg",
        "source_url": "https://commons.wikimedia.org/wiki/File:Crat_T-shirt.svg",
        "author": "Extraordinary Machine / Chenzw",
        "publisher": "Wikimedia Commons",
        "license": "Public Domain",
        "license_url": "https://commons.wikimedia.org/wiki/Template:PD-self",
        "credit": "Crat T-shirt.svg by Extraordinary Machine/Chenzw via Wikimedia Commons, Public Domain.",
        "placement": {"x": 0.31, "y": 0.34, "width": 0.38, "height": 0.32},
    },
    {
        "id": "wikimedia-bag",
        "title": "Bag.svg",
        "product": "bag",
        "download_url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Bag.svg",
        "source_url": "https://commons.wikimedia.org/wiki/File:Bag.svg",
        "author": "Snipre",
        "publisher": "Wikimedia Commons",
        "license": "Public Domain",
        "license_url": "https://commons.wikimedia.org/wiki/Template:PD-self",
        "credit": "Bag.svg by Snipre via Wikimedia Commons, Public Domain.",
        "placement": {"x": 0.28, "y": 0.30, "width": 0.44, "height": 0.42},
    },
    {
        "id": "wikimedia-mobile-phone",
        "title": "Mobile Phone.svg",
        "product": "phone-case",
        "download_url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Mobile%20Phone.svg",
        "source_url": "https://commons.wikimedia.org/wiki/File:Mobile_Phone.svg",
        "author": "Roman Tworkowski",
        "publisher": "Wikimedia Commons",
        "license": "Public Domain",
        "license_url": "https://commons.wikimedia.org/wiki/Template:PD-self",
        "credit": "Mobile Phone.svg by Roman Tworkowski via Wikimedia Commons, Public Domain.",
        "placement": {"x": 0.28, "y": 0.25, "width": 0.44, "height": 0.50},
    },
    {
        "id": "wikimedia-bottle",
        "title": "Bottle.svg",
        "product": "bottle",
        "download_url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Bottle.svg",
        "source_url": "https://commons.wikimedia.org/wiki/File:Bottle.svg",
        "author": "Dhanesh95",
        "publisher": "Wikimedia Commons",
        "license": "CC0 1.0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "credit": "Bottle.svg by Dhanesh95 via Wikimedia Commons, CC0 1.0.",
        "placement": {"x": 0.34, "y": 0.34, "width": 0.32, "height": 0.28},
    },
    {
        "id": "wikimedia-root-beer-mug",
        "title": "Root beer mug.svg",
        "product": "mug",
        "download_url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Root%20beer%20mug.svg",
        "source_url": "https://commons.wikimedia.org/wiki/File:Root_beer_mug.svg",
        "author": "Nicubunu / AuroraANovaUma",
        "publisher": "Wikimedia Commons / Open Clip Art",
        "license": "CC0 1.0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "credit": "Root beer mug.svg by Nicubunu/AuroraANovaUma via Wikimedia Commons/Open Clip Art, CC0 1.0.",
        "placement": {"x": 0.26, "y": 0.32, "width": 0.42, "height": 0.36},
    },
    {
        "id": "wikimedia-champagne-bottle",
        "title": "Champagne bottle.svg",
        "product": "bottle",
        "download_url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Champagne%20bottle.svg",
        "source_url": "https://commons.wikimedia.org/wiki/File:Champagne_bottle.svg",
        "author": "remi_inconnu",
        "publisher": "Wikimedia Commons / Open Clip Art",
        "license": "CC0 1.0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "credit": "Champagne bottle.svg by remi_inconnu via Wikimedia Commons/Open Clip Art, CC0 1.0.",
        "placement": {"x": 0.30, "y": 0.42, "width": 0.40, "height": 0.18},
    },
    {
        "id": "wikimedia-basic-notebook",
        "title": "Basic Notebook.svg",
        "product": "notebook",
        "download_url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Basic%20Notebook.svg",
        "source_url": "https://commons.wikimedia.org/wiki/File:Basic_Notebook.svg",
        "author": "Joseph El-Khouri",
        "publisher": "Wikimedia Commons",
        "license": "CC BY 3.0 US",
        "license_url": "https://creativecommons.org/licenses/by/3.0/us/",
        "credit": "Basic Notebook.svg by Joseph El-Khouri via Wikimedia Commons, CC BY 3.0 US.",
        "placement": {"x": 0.20, "y": 0.18, "width": 0.60, "height": 0.62},
    },
    {
        "id": "wikimedia-telephone",
        "title": "Telephone.svg",
        "product": "phone",
        "download_url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Telephone.svg",
        "source_url": "https://commons.wikimedia.org/wiki/File:Telephone.svg",
        "author": "John Dorwin",
        "publisher": "Wikimedia Commons",
        "license": "Public Domain",
        "license_url": "https://commons.wikimedia.org/wiki/Template:PD-self",
        "credit": "Telephone.svg by John Dorwin via Wikimedia Commons, Public Domain.",
        "placement": {"x": 0.28, "y": 0.30, "width": 0.44, "height": 0.40},
    },
]


CURATED_OPEN_SVG_SOURCES: list[dict[str, Any]] = [
    {
        "id": "freesvg-blank-tshirt",
        "title": "Blank T-Shirt",
        "product": "tshirt",
        "download_url": "https://freesvg.org/download/58727",
        "source_url": "https://freesvg.org/blank-t-shirt",
        "author": "OpenClipart",
        "publisher": "FreeSVG.org",
        "license": "Public Domain / CC0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "credit": "Blank T-Shirt, published by OpenClipart on FreeSVG.org, Public Domain / CC0.",
        "placement": {"x": 0.32, "y": 0.34, "width": 0.36, "height": 0.32},
    },
    {
        "id": "freesvg-xl-blank-tshirt-template",
        "title": "XL-size Blank T-shirt Template",
        "product": "tshirt",
        "download_url": "https://freesvg.org/download/85579",
        "source_url": "https://freesvg.org/xl-size-blank-t-shirt-template",
        "author": "OpenClipart",
        "publisher": "FreeSVG.org",
        "license": "Public Domain / CC0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "credit": "XL-size Blank T-shirt Template, published by OpenClipart on FreeSVG.org, Public Domain / CC0.",
        "placement": {"x": 0.31, "y": 0.32, "width": 0.38, "height": 0.34},
    },
    {
        "id": "wikimedia-shirt-outline",
        "title": "Shirt outline.svg",
        "product": "tshirt",
        "download_url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Shirt%20outline.svg",
        "source_url": "https://commons.wikimedia.org/wiki/File:Shirt_outline.svg",
        "author": "DraftSaturn15",
        "publisher": "Wikimedia Commons",
        "license": "Public Domain - simple geometry / PD shape",
        "license_url": "https://commons.wikimedia.org/wiki/Template:PD-shape",
        "credit": "Shirt outline.svg by DraftSaturn15 via Wikimedia Commons, Public Domain (simple geometry).",
        "placement": {"x": 0.32, "y": 0.34, "width": 0.36, "height": 0.32},
    },
    {
        "id": "svgrepo-t-shirt",
        "title": "T Shirt SVG Vector",
        "product": "tshirt",
        "download_url": "https://www.svgrepo.com/download/34467/t-shirt.svg",
        "source_url": "https://www.svgrepo.com/svg/34467/t-shirt",
        "author": "SVG Repo",
        "publisher": "SVG Repo",
        "license": "CC0 License",
        "license_url": "https://www.svgrepo.com/page/licensing/",
        "credit": "T Shirt SVG Vector from SVG Repo, CC0 License.",
        "placement": {"x": 0.31, "y": 0.34, "width": 0.38, "height": 0.32},
    },
    {
        "id": "svgrepo-hoodie",
        "title": "Hoodie SVG Vector",
        "product": "hoodie",
        "download_url": "https://www.svgrepo.com/download/195105/hoodie.svg",
        "source_url": "https://www.svgrepo.com/svg/195105/hoodie",
        "author": "SVG Repo",
        "publisher": "SVG Repo",
        "license": "CC0 License",
        "license_url": "https://www.svgrepo.com/page/licensing/",
        "credit": "Hoodie SVG Vector from SVG Repo, CC0 License.",
        "placement": {"x": 0.32, "y": 0.36, "width": 0.36, "height": 0.26},
    },
    {
        "id": "svgrepo-hoodie-sweatshirt",
        "title": "Hoodie Sweatshirt SVG Vector",
        "product": "hoodie",
        "download_url": "https://www.svgrepo.com/download/275044/hoodie-sweatshirt.svg",
        "source_url": "https://www.svgrepo.com/svg/275044/hoodie-sweatshirt",
        "author": "SVG Repo",
        "publisher": "SVG Repo",
        "license": "CC0 License",
        "license_url": "https://www.svgrepo.com/page/licensing/",
        "credit": "Hoodie Sweatshirt SVG Vector from SVG Repo, CC0 License.",
        "placement": {"x": 0.32, "y": 0.36, "width": 0.36, "height": 0.26},
    },
    {
        "id": "freesvg-tote-bag",
        "title": "tote bag",
        "product": "tote-bag",
        "download_url": "https://freesvg.org/download/132460",
        "source_url": "https://freesvg.org/johnny-automatic-tote-bag",
        "author": "OpenClipart",
        "publisher": "FreeSVG.org",
        "license": "Public Domain / CC0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "credit": "tote bag, published by OpenClipart on FreeSVG.org, Public Domain / CC0.",
        "placement": {"x": 0.30, "y": 0.38, "width": 0.40, "height": 0.36},
    },
    {
        "id": "svgrepo-tote-bag",
        "title": "Tote Bag SVG Vector",
        "product": "tote-bag",
        "download_url": "https://www.svgrepo.com/download/485104/tote-bag.svg",
        "source_url": "https://www.svgrepo.com/svg/485104/tote-bag",
        "author": "SVG Repo",
        "publisher": "SVG Repo",
        "license": "CC0 License",
        "license_url": "https://www.svgrepo.com/page/licensing/",
        "credit": "Tote Bag SVG Vector from SVG Repo, CC0 License.",
        "placement": {"x": 0.30, "y": 0.38, "width": 0.40, "height": 0.36},
    },
    {
        "id": "wikimedia-white-paper-bag",
        "title": "White paper bag.svg",
        "product": "paper-bag",
        "download_url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/White%20paper%20bag.svg",
        "source_url": "https://commons.wikimedia.org/wiki/File:White_paper_bag.svg",
        "author": "Marsupilami",
        "publisher": "Wikimedia Commons",
        "license": "Public Domain",
        "license_url": "https://commons.wikimedia.org/wiki/Template:PD-user",
        "credit": "White paper bag.svg by Marsupilami via Wikimedia Commons, Public Domain.",
        "placement": {"x": 0.30, "y": 0.34, "width": 0.40, "height": 0.36},
    },
    {
        "id": "svgrepo-mug",
        "title": "Mug SVG Vector",
        "product": "mug",
        "download_url": "https://www.svgrepo.com/download/462077/mug.svg",
        "source_url": "https://www.svgrepo.com/svg/462077/mug",
        "author": "SVG Repo",
        "publisher": "SVG Repo",
        "license": "CC0 License",
        "license_url": "https://www.svgrepo.com/page/licensing/",
        "credit": "Mug SVG Vector from SVG Repo, CC0 License.",
        "placement": {"x": 0.28, "y": 0.38, "width": 0.32, "height": 0.28},
    },
    {
        "id": "wikimedia-coffee-mug-flat",
        "title": "Coffee Mug Flat.svg",
        "product": "mug",
        "download_url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Coffee%20Mug%20Flat.svg",
        "source_url": "https://commons.wikimedia.org/wiki/File:Coffee_Mug_Flat.svg",
        "author": "gnokii",
        "publisher": "Wikimedia Commons / Open Clip Art",
        "license": "CC0 1.0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "credit": "Coffee Mug Flat.svg by gnokii via Wikimedia Commons/Open Clip Art, CC0 1.0.",
        "placement": {"x": 0.26, "y": 0.36, "width": 0.34, "height": 0.30},
    },
    {
        "id": "svgrepo-phone-case",
        "title": "Phone Case SVG Vector",
        "product": "phone-case",
        "download_url": "https://www.svgrepo.com/download/6293/phone-case.svg",
        "source_url": "https://www.svgrepo.com/svg/6293/phone-case",
        "author": "SVG Repo",
        "publisher": "SVG Repo",
        "license": "CC0 License",
        "license_url": "https://www.svgrepo.com/page/licensing/",
        "credit": "Phone Case SVG Vector from SVG Repo, CC0 License.",
        "placement": {"x": 0.28, "y": 0.24, "width": 0.44, "height": 0.52},
    },
    {
        "id": "svgrepo-poster",
        "title": "Poster SVG Vector",
        "product": "poster",
        "download_url": "https://www.svgrepo.com/download/31107/poster.svg",
        "source_url": "https://www.svgrepo.com/svg/31107/poster",
        "author": "SVG Repo",
        "publisher": "SVG Repo",
        "license": "CC0 License",
        "license_url": "https://www.svgrepo.com/page/licensing/",
        "credit": "Poster SVG Vector from SVG Repo, CC0 License.",
        "placement": {"x": 0.20, "y": 0.18, "width": 0.60, "height": 0.64},
    },
    {
        "id": "wikimedia-cards-blank",
        "title": "Cards-Blank.svg",
        "product": "card",
        "download_url": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Cards-Blank.svg",
        "source_url": "https://commons.wikimedia.org/wiki/File:Cards-Blank.svg",
        "author": "WDGraham",
        "publisher": "Wikimedia Commons",
        "license": "Public Domain - ineligible",
        "license_url": "https://commons.wikimedia.org/wiki/Template:PD-ineligible",
        "credit": "Cards-Blank.svg by WDGraham via Wikimedia Commons, Public Domain (ineligible).",
        "placement": {"x": 0.20, "y": 0.18, "width": 0.60, "height": 0.64},
    },
    {
        "id": "svgrepo-cap-hat",
        "title": "Cap Hat SVG Vector",
        "product": "cap",
        "download_url": "https://www.svgrepo.com/download/384559/cap-hat.svg",
        "source_url": "https://www.svgrepo.com/svg/384559/cap-hat",
        "author": "SVG Repo",
        "publisher": "SVG Repo",
        "license": "CC0 License",
        "license_url": "https://www.svgrepo.com/page/licensing/",
        "credit": "Cap Hat SVG Vector from SVG Repo, CC0 License.",
        "placement": {"x": 0.28, "y": 0.36, "width": 0.44, "height": 0.22},
    },
    {
        "id": "svgrepo-open-notebook",
        "title": "Open Notebook SVG Vector",
        "product": "notebook",
        "download_url": "https://www.svgrepo.com/download/58676/open-notebook.svg",
        "source_url": "https://www.svgrepo.com/svg/58676/open-notebook",
        "author": "SVG Repo",
        "publisher": "SVG Repo",
        "license": "CC0 License",
        "license_url": "https://www.svgrepo.com/page/licensing/",
        "credit": "Open Notebook SVG Vector from SVG Repo, CC0 License.",
        "placement": {"x": 0.19, "y": 0.20, "width": 0.62, "height": 0.60},
    },
]

CURATED_OPEN_SVG_SOURCES.extend(CURATED_OPEN_SVG_COMMONS_SOURCES)


def _mdi_source(icon: str, title: str, product: str, placement: dict[str, float] | None = None) -> dict[str, Any]:
    return {
        "id": f"mdi-{icon}",
        "title": title,
        "product": product,
        "download_url": f"https://api.iconify.design/mdi/{icon}.svg?color=%23444444&box=1",
        "source_url": f"https://pictogrammers.com/library/mdi/icon/{icon}/",
        "author": "Pictogrammers",
        "publisher": "Pictogrammers / Iconify API",
        "license": "Apache License 2.0",
        "license_url": "https://pictogrammers.com/docs/general/license/",
        "credit": f"{title} from Material Design Icons by Pictogrammers, Apache License 2.0.",
        "placement": placement or {"x": 0.28, "y": 0.28, "width": 0.44, "height": 0.44},
    }


CURATED_OPEN_SVG_SOURCES.extend([
    _mdi_source("tshirt-v", "V-neck T-shirt icon", "tshirt", {"x": 0.30, "y": 0.34, "width": 0.40, "height": 0.32}),
    _mdi_source("tshirt-v-outline", "V-neck T-shirt outline icon", "tshirt", {"x": 0.30, "y": 0.34, "width": 0.40, "height": 0.32}),
    _mdi_source("tshirt-crew", "Crew-neck T-shirt icon", "tshirt", {"x": 0.30, "y": 0.34, "width": 0.40, "height": 0.32}),
    _mdi_source("tshirt-crew-outline", "Crew-neck T-shirt outline icon", "tshirt", {"x": 0.30, "y": 0.34, "width": 0.40, "height": 0.32}),
    _mdi_source("hanger", "Hanger icon", "apparel"),
    _mdi_source("sunglasses", "Sunglasses icon", "accessory"),
    _mdi_source("glasses", "Glasses icon", "accessory"),
    _mdi_source("hat-fedora", "Hat icon", "cap"),
    _mdi_source("tie", "Tie icon", "apparel"),
    _mdi_source("shoe-sneaker", "Sneaker icon", "shoe"),
    _mdi_source("shoe-formal", "Formal shoe icon", "shoe"),
    _mdi_source("shoe-print", "Shoe print icon", "shoe"),
    _mdi_source("bag-checked", "Checked bag icon", "bag"),
    _mdi_source("bag-carry-on", "Carry-on bag icon", "bag"),
    _mdi_source("bag-personal", "Personal bag icon", "bag"),
    _mdi_source("bag-personal-outline", "Personal bag outline icon", "bag"),
    _mdi_source("bag-personal-tag", "Tagged personal bag icon", "bag"),
    _mdi_source("bag-personal-tag-outline", "Tagged personal bag outline icon", "bag"),
    _mdi_source("bag-suitcase", "Suitcase bag icon", "bag"),
    _mdi_source("bag-suitcase-outline", "Suitcase bag outline icon", "bag"),
    _mdi_source("briefcase", "Briefcase icon", "bag"),
    _mdi_source("briefcase-outline", "Briefcase outline icon", "bag"),
    _mdi_source("glass-mug", "Glass mug icon", "mug", {"x": 0.24, "y": 0.34, "width": 0.42, "height": 0.34}),
    _mdi_source("glass-mug-variant", "Glass mug variant icon", "mug", {"x": 0.24, "y": 0.34, "width": 0.42, "height": 0.34}),
    _mdi_source("cup", "Cup icon", "cup", {"x": 0.24, "y": 0.34, "width": 0.42, "height": 0.34}),
    _mdi_source("cup-outline", "Cup outline icon", "cup", {"x": 0.24, "y": 0.34, "width": 0.42, "height": 0.34}),
    _mdi_source("cup-water", "Water cup icon", "cup", {"x": 0.24, "y": 0.34, "width": 0.42, "height": 0.34}),
    _mdi_source("bottle-soda", "Soda bottle icon", "bottle", {"x": 0.32, "y": 0.34, "width": 0.36, "height": 0.28}),
    _mdi_source("bottle-soda-outline", "Soda bottle outline icon", "bottle", {"x": 0.32, "y": 0.34, "width": 0.36, "height": 0.28}),
    _mdi_source("bottle-tonic", "Tonic bottle icon", "bottle", {"x": 0.32, "y": 0.34, "width": 0.36, "height": 0.28}),
    _mdi_source("bottle-tonic-outline", "Tonic bottle outline icon", "bottle", {"x": 0.32, "y": 0.34, "width": 0.36, "height": 0.28}),
    _mdi_source("water-bottle", "Water bottle icon", "bottle", {"x": 0.32, "y": 0.34, "width": 0.36, "height": 0.28}),
    _mdi_source("water-bottle-outline", "Water bottle outline icon", "bottle", {"x": 0.32, "y": 0.34, "width": 0.36, "height": 0.28}),
    _mdi_source("phone", "Phone icon", "phone-case", {"x": 0.24, "y": 0.20, "width": 0.52, "height": 0.56}),
    _mdi_source("phone-outline", "Phone outline icon", "phone-case", {"x": 0.24, "y": 0.20, "width": 0.52, "height": 0.56}),
    _mdi_source("cellphone", "Cellphone icon", "phone-case", {"x": 0.24, "y": 0.20, "width": 0.52, "height": 0.56}),
    _mdi_source("cellphone-iphone", "iPhone-style cellphone icon", "phone-case", {"x": 0.24, "y": 0.20, "width": 0.52, "height": 0.56}),
    _mdi_source("tablet", "Tablet icon", "tablet", {"x": 0.22, "y": 0.20, "width": 0.56, "height": 0.56}),
    _mdi_source("tablet-cellphone", "Tablet and cellphone icon", "tablet", {"x": 0.22, "y": 0.20, "width": 0.56, "height": 0.56}),
    _mdi_source("laptop", "Laptop icon", "laptop", {"x": 0.22, "y": 0.20, "width": 0.56, "height": 0.42}),
    _mdi_source("monitor", "Monitor icon", "monitor", {"x": 0.22, "y": 0.20, "width": 0.56, "height": 0.42}),
    _mdi_source("watch", "Watch icon", "watch", {"x": 0.28, "y": 0.30, "width": 0.44, "height": 0.36}),
    _mdi_source("watch-variant", "Watch variant icon", "watch", {"x": 0.28, "y": 0.30, "width": 0.44, "height": 0.36}),
    _mdi_source("notebook", "Notebook icon", "notebook", {"x": 0.20, "y": 0.18, "width": 0.60, "height": 0.62}),
    _mdi_source("notebook-outline", "Notebook outline icon", "notebook", {"x": 0.20, "y": 0.18, "width": 0.60, "height": 0.62}),
    _mdi_source("book-open-page-variant", "Open book page icon", "book", {"x": 0.20, "y": 0.18, "width": 0.60, "height": 0.62}),
    _mdi_source("book-open-variant", "Open book icon", "book", {"x": 0.20, "y": 0.18, "width": 0.60, "height": 0.62}),
    _mdi_source("clipboard-outline", "Clipboard outline icon", "clipboard", {"x": 0.20, "y": 0.18, "width": 0.60, "height": 0.62}),
    _mdi_source("file-outline", "Document outline icon", "document", {"x": 0.20, "y": 0.18, "width": 0.60, "height": 0.62}),
    _mdi_source("image-frame", "Image frame icon", "poster", {"x": 0.18, "y": 0.18, "width": 0.64, "height": 0.64}),
    _mdi_source("shopping", "Shopping bag icon", "bag"),
    _mdi_source("shopping-outline", "Shopping bag outline icon", "bag"),
])


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "item"


def github_blob_to_raw(url: str) -> str:
    """Convert a GitHub blob URL to a raw file URL when possible."""
    match = re.match(r"^https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)$", url)
    if not match:
        return url
    owner, repo, ref, path = match.groups()
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"


def parse_box(value: str) -> dict[str, float]:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if len(parts) != 4:
        raise ValueError("box must be x,y,width,height")
    x, y, width, height = [float(part) for part in parts]
    return {"x": x, "y": y, "width": width, "height": height}


@dataclass(frozen=True)
class Placement:
    x: float
    y: float
    width: float
    height: float

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "Placement":
        return cls(
            x=float(value["x"]),
            y=float(value["y"]),
            width=float(value["width"]),
            height=float(value["height"]),
        )

    def to_pixels(self, canvas: tuple[int, int]) -> tuple[int, int, int, int]:
        canvas_w, canvas_h = canvas
        values = [self.x, self.y, self.width, self.height]
        if all(0 <= item <= 1 for item in values):
            x = int(round(self.x * canvas_w))
            y = int(round(self.y * canvas_h))
            width = int(round(self.width * canvas_w))
            height = int(round(self.height * canvas_h))
        else:
            x = int(round(self.x))
            y = int(round(self.y))
            width = int(round(self.width))
            height = int(round(self.height))
        if width <= 0 or height <= 0:
            raise ValueError("placement width and height must be positive")
        return x, y, width, height

    def to_json(self) -> dict[str, float]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class TemplateSpec:
    id: str
    file: Path
    placement: Placement
    product: str = "tshirt"
    variant: str = ""
    color: str = ""
    attribution: dict[str, Any] | None = None

    @classmethod
    def from_mapping(cls, value: dict[str, Any], *, base_dir: Path) -> "TemplateSpec":
        file_value = Path(str(value["file"]))
        file_path = file_value if file_value.is_absolute() else base_dir / file_value
        placement = Placement.from_mapping(value["placement"])
        return cls(
            id=str(value.get("id") or slugify(file_path.stem)),
            file=file_path,
            placement=placement,
            product=str(value.get("product") or "tshirt"),
            variant=str(value.get("variant") or ""),
            color=str(value.get("color") or ""),
            attribution=value.get("attribution") if isinstance(value.get("attribution"), dict) else None,
        )

    def to_json(self, *, base_dir: Path | None = None) -> dict[str, Any]:
        file_value = self.file
        if base_dir is not None:
            try:
                file_text = str(file_value.resolve().relative_to(base_dir.resolve()))
            except ValueError:
                file_text = str(file_value)
        else:
            file_text = str(file_value)
        return {
            "id": self.id,
            "file": file_text,
            "product": self.product,
            "variant": self.variant,
            "color": self.color,
            "placement": self.placement.to_json(),
            **({"attribution": self.attribution} if self.attribution else {}),
        }


def load_template_manifest(path: Path) -> list[TemplateSpec]:
    data = json.loads(path.read_text(encoding="utf-8"))
    templates = data.get("templates")
    if not isinstance(templates, list) or not templates:
        raise ValueError(f"template manifest has no templates: {path}")
    return [TemplateSpec.from_mapping(item, base_dir=path.parent) for item in templates]


def write_template_manifest(path: Path, templates: Iterable[TemplateSpec], *, source: str) -> None:
    template_list = list(templates)
    payload = {
        "version": 1,
        "source": source,
        "generated_at": int(time.time()),
        "templates": [template.to_json(base_dir=path.parent) for template in template_list],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _require_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError as exc:
        raise SystemExit("mockups require Pillow: pip install Pillow") from exc
    return Image, ImageDraw, ImageFilter


def render_blank_tshirt_template(path: Path, *, color: str, width: int = 1600, height: int = 2000) -> None:
    """Render a clean front-facing blank tee template."""
    Image, ImageDraw, ImageFilter = _require_pillow()
    scale = 2
    w, h = width * scale, height * scale
    bg = "#ECE8DF"
    shirt = color

    image = Image.new("RGBA", (w, h), bg)
    mask = Image.new("L", (w, h), 0)
    draw = ImageDraw.Draw(mask)

    def pt(x: float, y: float) -> tuple[int, int]:
        return int(round(x * scale)), int(round(y * scale))

    left_sleeve = [pt(470, 405), pt(265, 620), pt(382, 915), pt(565, 725), pt(555, 455)]
    right_sleeve = [pt(1130, 405), pt(1335, 620), pt(1218, 915), pt(1035, 725), pt(1045, 455)]
    body = [pt(505, 405), pt(1095, 405), pt(1165, 1645), pt(435, 1645)]
    draw.polygon(left_sleeve, fill=255)
    draw.polygon(right_sleeve, fill=255)
    draw.rounded_rectangle((pt(468, 390), pt(1132, 1660)), radius=80 * scale, fill=255)
    draw.polygon(body, fill=255)
    draw.ellipse((pt(660, 320), pt(940, 565)), fill=0)
    draw.rectangle((pt(640, 315), pt(960, 410)), fill=0)

    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shadow_alpha = mask.filter(ImageFilter.GaussianBlur(24 * scale))
    shadow.putalpha(shadow_alpha.point(lambda px: int(px * 0.16)))
    image.alpha_composite(shadow, (0, 18 * scale))

    shirt_layer = Image.new("RGBA", (w, h), shirt)
    shirt_layer.putalpha(mask)
    image = Image.alpha_composite(image, shirt_layer)

    shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shade_alpha = Image.new("L", (w, h), 0)
    shade_draw = ImageDraw.Draw(shade_alpha)
    shade_draw.polygon(left_sleeve, fill=22)
    shade_draw.polygon(right_sleeve, fill=22)
    shade_draw.rectangle((pt(468, 410), pt(545, 1635)), fill=16)
    shade_draw.rectangle((pt(1055, 410), pt(1132, 1635)), fill=16)
    shade_alpha = Image.composite(shade_alpha, Image.new("L", (w, h), 0), mask)
    shade.putalpha(shade_alpha)
    image = Image.alpha_composite(image, shade)

    highlight = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    highlight_alpha = Image.new("L", (w, h), 0)
    highlight_draw = ImageDraw.Draw(highlight_alpha)
    highlight_draw.ellipse((pt(530, 455), pt(1070, 1520)), fill=18)
    highlight_alpha = Image.composite(highlight_alpha, Image.new("L", (w, h), 0), mask)
    highlight.putalpha(highlight_alpha)
    image = Image.alpha_composite(image, highlight)

    line = ImageDraw.Draw(image)
    outline = (0, 0, 0, 42)
    line.line(left_sleeve + [left_sleeve[0]], fill=outline, width=3 * scale, joint="curve")
    line.line(right_sleeve + [right_sleeve[0]], fill=outline, width=3 * scale, joint="curve")
    line.arc((pt(670, 325), pt(930, 560)), start=20, end=160, fill=(0, 0, 0, 55), width=8 * scale)

    image = image.resize((width, height), getattr(Image, "Resampling", Image).LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path, quality=94)


def generate_tshirt_template_set(out_dir: Path, *, count: int = 50, width: int = 1600, height: int = 2000) -> Path:
    if count < 1:
        raise ValueError("count must be at least 1")
    selected = TSHIRT_COLOR_VARIANTS[: min(count, len(TSHIRT_COLOR_VARIANTS))]
    templates: list[TemplateSpec] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    placement = Placement(x=0.33, y=0.35, width=0.34, height=0.34)
    for name, color in selected:
        slug = slugify(name)
        file_path = out_dir / f"tshirt-front-{slug}.png"
        render_blank_tshirt_template(file_path, color=color, width=width, height=height)
        templates.append(
            TemplateSpec(
                id=f"tshirt-front-{slug}",
                file=file_path,
                placement=placement,
                product="tshirt",
                variant=name,
                color=color,
            )
        )
    manifest_path = out_dir / "templates.json"
    write_template_manifest(manifest_path, templates, source="forge-builtin-tshirt-front")
    return manifest_path


def _trim_transparency(image: Any) -> Any:
    if image.mode != "RGBA":
        return image
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        return image
    if bbox == (0, 0, image.width, image.height):
        return image
    return image.crop(bbox)


def _clean_svg_bytes(payload: bytes, *, source_url: str) -> str:
    text = payload.decode("utf-8", errors="replace").strip()
    if "<svg" not in text[:500].lower():
        raise ValueError(f"download did not look like SVG: {source_url}")
    return text


def _download_bytes(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ForgeMockupDownloader/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except Exception as urllib_error:
        curl = shutil.which("curl") or "/usr/bin/curl"
        if not Path(curl).exists():
            raise urllib_error
        result = subprocess.run(
            [
                curl,
                "-sS",
                "-L",
                "--fail",
                "--retry",
                "3",
                "--retry-delay",
                "1",
                "-A",
                "ForgeMockupDownloader/1.0",
                url,
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            raise URLError(result.stderr.decode("utf-8", errors="replace").strip()) from urllib_error
        return result.stdout


def download_open_svg_set(
    out_dir: Path,
    *,
    limit: int | None = None,
    source_ids: Iterable[str] | None = None,
) -> Path:
    """Download curated open-license SVG product templates with attribution."""
    wanted = set(source_ids or [])
    if wanted:
        sources = [src for src in CURATED_OPEN_SVG_SOURCES if src["id"] in wanted]
    else:
        # Default to sources with reliable direct SVG redirects. Other curated
        # entries are kept for explicit use, but may be blocked by site
        # challenges or non-direct download flows.
        iconify_sources = [
            src for src in CURATED_OPEN_SVG_SOURCES
            if str(src.get("download_url", "")).startswith("https://api.iconify.design/")
        ]
        commons_sources = [
            src for src in CURATED_OPEN_SVG_SOURCES
            if str(src.get("download_url", "")).startswith("https://commons.wikimedia.org/")
        ]
        sources = iconify_sources + commons_sources
    if not sources:
        raise ValueError("no open SVG sources selected")

    asset_dir = out_dir / "assets"
    attr_dir = out_dir / "attribution"
    asset_dir.mkdir(parents=True, exist_ok=True)
    attr_dir.mkdir(parents=True, exist_ok=True)
    retrieved_at = time.strftime("%Y-%m-%d")
    templates: list[TemplateSpec] = []
    failures: list[dict[str, str]] = []

    for source in sources:
        if limit is not None and len(templates) >= limit:
            break
        file_path = asset_dir / f"{source['id']}.svg"
        try:
            svg_text = _clean_svg_bytes(
                _download_bytes(str(source["download_url"])),
                source_url=str(source["download_url"]),
            )
        except Exception as exc:
            failures.append({
                "id": str(source["id"]),
                "title": str(source["title"]),
                "download_url": str(source["download_url"]),
                "error": str(exc),
            })
            continue
        svg_text = svg_text.replace("\r\n", "\n")
        file_path.write_text(svg_text + ("\n" if not svg_text.endswith("\n") else ""), encoding="utf-8")
        attribution = {
            "id": source["id"],
            "title": source["title"],
            "author": source["author"],
            "publisher": source["publisher"],
            "source_url": source["source_url"],
            "download_url": source["download_url"],
            "license": source["license"],
            "license_url": source["license_url"],
            "credit": source["credit"],
            "retrieved_at": retrieved_at,
        }
        (attr_dir / f"{source['id']}.json").write_text(json.dumps(attribution, indent=2) + "\n", encoding="utf-8")
        templates.append(
            TemplateSpec(
                id=str(source["id"]),
                file=file_path,
                placement=Placement.from_mapping(source["placement"]),
                product=str(source["product"]),
                variant=str(source["title"]),
                attribution=attribution,
            )
        )

    manifest_path = out_dir / "templates.json"
    if not templates:
        raise ValueError(f"no SVG templates downloaded; failures: {failures}")
    write_template_manifest(manifest_path, templates, source="curated-open-svg")
    credits_md = out_dir / "CREDITS.md"
    lines = ["# Open SVG Mockup Template Credits", ""]
    for template in templates:
        attr = template.attribution or {}
        lines.append(f"- **{attr.get('title', template.id)}** — {attr.get('credit', '')}")
        lines.append(f"  Source: {attr.get('source_url', '')}")
        lines.append(f"  License: {attr.get('license', '')} ({attr.get('license_url', '')})")
    if failures:
        lines.append("")
        lines.append("## Download Failures")
        for failure in failures:
            lines.append(f"- {failure['id']}: {failure['error']}")
    credits_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    if failures:
        (out_dir / "download-failures.json").write_text(json.dumps(failures, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def _strip_unit(value: str) -> float | None:
    match = re.match(r"^\s*([0-9.]+)", value)
    return float(match.group(1)) if match else None


def _svg_canvas(svg_text: str) -> tuple[float, float, float, float]:
    viewbox_match = re.search(r'viewBox\s*=\s*["\']([^"\']+)["\']', svg_text, re.IGNORECASE)
    if viewbox_match:
        values = [float(item) for item in re.split(r"[\s,]+", viewbox_match.group(1).strip()) if item]
        if len(values) == 4 and values[2] > 0 and values[3] > 0:
            return values[0], values[1], values[2], values[3]

    svg_tag = re.search(r"<svg\b([^>]*)>", svg_text, re.IGNORECASE | re.DOTALL)
    if svg_tag:
        width_match = re.search(r'\bwidth\s*=\s*["\']([^"\']+)["\']', svg_tag.group(1), re.IGNORECASE)
        height_match = re.search(r'\bheight\s*=\s*["\']([^"\']+)["\']', svg_tag.group(1), re.IGNORECASE)
        width = _strip_unit(width_match.group(1)) if width_match else None
        height = _strip_unit(height_match.group(1)) if height_match else None
        if width and height:
            return 0.0, 0.0, width, height
    return 0.0, 0.0, 1000.0, 1000.0


def _image_data_uri(path: Path, *, trim: bool) -> tuple[str, int, int]:
    Image, _ImageDraw, _ImageFilter = _require_pillow()
    image = Image.open(path).convert("RGBA")
    if trim:
        image = _trim_transparency(image)
    buf = BytesIO()
    image.save(buf, "PNG", optimize=True)
    encoded = b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}", image.width, image.height


def compose_svg_mockup(
    *,
    design_path: Path,
    template: TemplateSpec,
    out_path: Path,
    print_scale: float = 0.88,
    trim: bool = True,
) -> dict[str, Any]:
    if print_scale <= 0:
        raise ValueError("print_scale must be positive")
    svg_text = template.file.read_text(encoding="utf-8", errors="replace")
    min_x, min_y, canvas_w, canvas_h = _svg_canvas(svg_text)
    px, py, box_w, box_h = template.placement.to_pixels((int(round(canvas_w)), int(round(canvas_h))))
    x = min_x + px
    y = min_y + py
    max_w = box_w * print_scale
    max_h = box_h * print_scale
    data_uri, design_w, design_h = _image_data_uri(design_path, trim=trim)
    ratio = min(max_w / design_w, max_h / design_h)
    rendered_w = design_w * ratio
    rendered_h = design_h * ratio
    rendered_x = x + (box_w - rendered_w) / 2
    rendered_y = y + (box_h - rendered_h) / 2
    attr = template.attribution or {}
    credit = attr.get("credit", "No attribution metadata supplied.")
    overlay = f'''
  <g id="forge-print-layer" data-forge-template="{escape(template.id)}">
    <title>Forge print design overlay</title>
    <desc>{escape(str(credit))}</desc>
    <image href="{data_uri}" x="{rendered_x:.3f}" y="{rendered_y:.3f}" width="{rendered_w:.3f}" height="{rendered_h:.3f}" preserveAspectRatio="xMidYMid meet" />
  </g>
  <!-- Forge source credit: {escape(str(credit))} -->
'''
    close_match = re.search(r"</svg\s*>", svg_text, re.IGNORECASE)
    if close_match:
        output = svg_text[: close_match.start()] + overlay + svg_text[close_match.start() :]
    else:
        output = svg_text + overlay
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(output, encoding="utf-8")
    attribution_path = out_path.with_suffix(out_path.suffix + ".attribution.json")
    attribution_path.write_text(json.dumps(attr, indent=2) + "\n", encoding="utf-8")
    return {
        "design": str(design_path),
        "template": template.id,
        "template_file": str(template.file),
        "out": str(out_path),
        "attribution": attr,
        "attribution_file": str(attribution_path),
        "placement_svg": {"x": x, "y": y, "width": box_w, "height": box_h},
        "printed_svg": {"x": rendered_x, "y": rendered_y, "width": rendered_w, "height": rendered_h},
        "variant": template.variant,
        "product": template.product,
    }


def compose_mockup(
    *,
    design_path: Path,
    template: TemplateSpec,
    out_path: Path,
    print_scale: float = 0.88,
    trim: bool = True,
) -> dict[str, Any]:
    Image, _ImageDraw, _ImageFilter = _require_pillow()
    if print_scale <= 0:
        raise ValueError("print_scale must be positive")
    canvas = Image.open(template.file).convert("RGBA")
    design = Image.open(design_path).convert("RGBA")
    if trim:
        design = _trim_transparency(design)
    x, y, width, height = template.placement.to_pixels(canvas.size)
    max_w = max(1, int(width * print_scale))
    max_h = max(1, int(height * print_scale))
    ratio = min(max_w / design.width, max_h / design.height)
    new_size = (max(1, int(design.width * ratio)), max(1, int(design.height * ratio)))
    design = design.resize(new_size, getattr(Image, "Resampling", Image).LANCZOS)
    px = x + (width - new_size[0]) // 2
    py = y + (height - new_size[1]) // 2
    canvas.alpha_composite(design, (px, py))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = out_path.suffix.lower()
    if suffix in {".jpg", ".jpeg", ".webp"}:
        canvas.convert("RGB").save(out_path, quality=94)
    else:
        canvas.save(out_path)
    return {
        "design": str(design_path),
        "template": template.id,
        "template_file": str(template.file),
        "out": str(out_path),
        "placement_px": {"x": x, "y": y, "width": width, "height": height},
        "printed_px": {"x": px, "y": py, "width": new_size[0], "height": new_size[1]},
        "variant": template.variant,
        "product": template.product,
    }


def compose_template_mockup(
    *,
    design_path: Path,
    template: TemplateSpec,
    out_path: Path,
    print_scale: float = 0.88,
    trim: bool = True,
) -> dict[str, Any]:
    if template.file.suffix.lower() == ".svg" or out_path.suffix.lower() == ".svg":
        return compose_svg_mockup(
            design_path=design_path,
            template=template,
            out_path=out_path,
            print_scale=print_scale,
            trim=trim,
        )
    return compose_mockup(
        design_path=design_path,
        template=template,
        out_path=out_path,
        print_scale=print_scale,
        trim=trim,
    )


def list_designs(design_dir: Path, *, pattern: str = "*.transparent.png") -> list[Path]:
    paths = sorted(path for path in design_dir.glob(pattern) if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS)
    if not paths and pattern != "*.png":
        paths = sorted(path for path in design_dir.glob("*.png") if path.is_file())
    return paths


def download_template_files(urls: Iterable[str], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    downloads: list[dict[str, str]] = []
    for url in urls:
        raw_url = github_blob_to_raw(url)
        raw_path = Path(raw_url.split("?", 1)[0])
        filename = slugify(raw_path.stem)
        suffix = raw_path.suffix.lower()
        if suffix not in IMAGE_EXTENSIONS:
            suffix = ".png"
        out_path = out_dir / f"{filename}{suffix}"
        request = urllib.request.Request(raw_url, headers={"User-Agent": "ForgeMockupDownloader/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            out_path.write_bytes(response.read())
        downloads.append({"url": url, "resolved_url": raw_url, "file": str(out_path)})
    manifest_path = out_dir / "downloads.json"
    manifest_path.write_text(json.dumps({"downloads": downloads}, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def write_batch_manifest(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = {
        "version": 1,
        "generated_at": int(time.time()),
        "count": len(rows),
        "mockups": rows,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
