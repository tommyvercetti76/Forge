from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from mockup_compositor import (
    CURATED_OPEN_SVG_SOURCES,
    Placement,
    TemplateSpec,
    compose_mockup,
    compose_svg_mockup,
    generate_tshirt_template_set,
    github_blob_to_raw,
    list_designs,
    load_template_manifest,
)


class MockupCompositorTests(unittest.TestCase):
    def test_github_blob_url_is_downloadable_raw_url(self) -> None:
        self.assertEqual(
            github_blob_to_raw("https://github.com/owner/repo/blob/main/mockups/front.png"),
            "https://raw.githubusercontent.com/owner/repo/main/mockups/front.png",
        )

    def test_init_generates_templates_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = generate_tshirt_template_set(root / "templates", count=3, width=400, height=500)
            templates = load_template_manifest(manifest)

            self.assertEqual(len(templates), 3)
            self.assertTrue((root / "templates" / "tshirt-front-white.png").exists())
            self.assertEqual(templates[0].placement.to_pixels((400, 500)), (132, 175, 136, 170))

    def test_compose_mockup_places_trimmed_design(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template_path = root / "template.png"
            design_path = root / "design.transparent.png"
            out_path = root / "mockup.jpg"

            Image.new("RGB", (400, 500), "#EEEEEE").save(template_path)
            design = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
            draw = ImageDraw.Draw(design)
            draw.rectangle((70, 70, 130, 130), fill=(220, 20, 30, 255))
            design.save(design_path)

            template = TemplateSpec(
                id="test-template",
                file=template_path,
                placement=Placement(x=100, y=150, width=200, height=200),
            )
            receipt = compose_mockup(design_path=design_path, template=template, out_path=out_path)

            self.assertTrue(out_path.exists())
            self.assertLess(receipt["printed_px"]["width"], 200)
            image = Image.open(out_path).convert("RGB")
            center = image.getpixel((200, 250))
            self.assertGreater(center[0], 150)
            self.assertLess(center[1], 90)

    def test_compose_svg_mockup_embeds_design_and_credit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template_path = root / "template.svg"
            design_path = root / "design.transparent.png"
            out_path = root / "mockup.svg"

            template_path.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 500 500">'
                '<rect x="25" y="25" width="450" height="450" fill="#f7f7f7"/>'
                '</svg>',
                encoding="utf-8",
            )
            design = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
            draw = ImageDraw.Draw(design)
            draw.rectangle((50, 50, 150, 150), fill=(30, 80, 220, 255))
            design.save(design_path)
            template = TemplateSpec(
                id="svg-template",
                file=template_path,
                placement=Placement(x=0.25, y=0.25, width=0.50, height=0.50),
                attribution={"credit": "Example SVG, CC0."},
            )

            receipt = compose_svg_mockup(design_path=design_path, template=template, out_path=out_path)
            text = out_path.read_text(encoding="utf-8")

            self.assertIn("forge-print-layer", text)
            self.assertIn("data:image/png;base64", text)
            self.assertIn("Example SVG, CC0.", text)
            self.assertTrue(Path(receipt["attribution_file"]).exists())

    def test_list_designs_prefers_transparent_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(root / "a.transparent.png")
            Image.new("RGBA", (10, 10), (0, 0, 0, 0)).save(root / "b.png")

            paths = list_designs(root)
            self.assertEqual([path.name for path in paths], ["a.transparent.png"])

    def test_curated_open_svg_sources_have_license_metadata(self) -> None:
        self.assertGreaterEqual(len(CURATED_OPEN_SVG_SOURCES), 10)
        for source in CURATED_OPEN_SVG_SOURCES:
            self.assertIn("download_url", source)
            self.assertIn("source_url", source)
            self.assertIn("license", source)
            self.assertIn("credit", source)
            self.assertIn("placement", source)


if __name__ == "__main__":
    unittest.main()
