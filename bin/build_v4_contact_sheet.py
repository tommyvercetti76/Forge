#!/usr/bin/env python3
"""Build an HTML contact sheet + grading form for the v4 batch.

Reads `generated/madhubani_animals/v4/_batch_summary.json` (written by
`forge_madhubani_batch_v4.py`) and produces a single self-contained HTML
file at `generated/madhubani_animals/v4/_contact_sheet.html` that:

  - Shows every species' winning render at a uniform thumb size
  - Surfaces the composite score + active-check pass count under each
  - Adds a PASS / FAIL / SKIP radio per species
  - Exports the user's votes as a JSON download (drop into
    brand/madhubani/labels_v2.json for the next agreement-study round)

Pure stdlib + a `<base64>` data: URL per image so the file is portable
without disk-relative paths (works when opened from anywhere).

Usage:
  python3 bin/build_v4_contact_sheet.py
  open generated/madhubani_animals/v4/_contact_sheet.html
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V4_ROOT = ROOT / "generated/madhubani_animals/v4"
SUMMARY_PATH = V4_ROOT / "_batch_summary.json"
OUT_PATH = V4_ROOT / "_contact_sheet.html"


def thumb_data_url(png_path: Path, max_dim: int = 360) -> str | None:
    """Read a PNG, resize to max_dim, encode as data: URL.
    Returns None if the file is missing."""
    if not png_path or not png_path.exists():
        return None
    try:
        from PIL import Image
        img = Image.open(png_path).convert("RGB")
        img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        import io
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception:
        return None


def build_html(summary: dict) -> str:
    rows: list[str] = []
    for s in summary.get("statuses", []):
        slug = s.get("slug", "?")
        body = s.get("body_type", "?")
        park = s.get("park", "")
        comp = s.get("winner_composite")
        accepted = s.get("accepted")
        attempts = s.get("stopped_on_attempt")
        winner_path = s.get("winner_path")
        rc = s.get("rc", -1)
        # Resolve path. winner_path is absolute when present.
        thumb = thumb_data_url(Path(winner_path)) if winner_path else None
        thumb_src = thumb if thumb else ""
        thumb_html = (
            f'<img src="{thumb_src}" alt="{slug}" loading="lazy">' if thumb_src
            else '<div class="missing">no render</div>'
        )
        if comp is None:
            score_html = f'<span class="bad">render failed (rc={rc})</span>'
        else:
            badge = "accepted" if accepted else "stopped"
            color = "ok" if accepted else "warn"
            score_html = (
                f'composite <b>{comp:.4f}</b> '
                f'<span class="badge {color}">{badge}@{attempts}</span>'
            )
        rows.append(f"""
        <div class="card" data-slug="{slug}">
          <div class="thumb">{thumb_html}</div>
          <div class="meta">
            <div class="name">{slug}</div>
            <div class="sub">{body} · {park}</div>
            <div class="score">{score_html}</div>
            <div class="vote">
              <label><input type="radio" name="vote-{slug}" value="pass"> PASS</label>
              <label><input type="radio" name="vote-{slug}" value="fail"> FAIL</label>
              <label><input type="radio" name="vote-{slug}" value="skip" checked> ?</label>
            </div>
          </div>
        </div>""")

    n = len(summary.get("statuses", []))
    accepted_n = sum(1 for s in summary.get("statuses", []) if s.get("accepted"))
    composites = [s["winner_composite"] for s in summary.get("statuses", [])
                  if s.get("winner_composite") is not None]
    summary_line = (
        f"<b>{n}</b> species · <b>{accepted_n}</b> auto-accepted · "
        + (f"composite range <b>{min(composites):.3f}</b>–<b>{max(composites):.3f}</b>"
           if composites else "")
    )

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>Forge v4 batch — contact sheet + grading</title>
<style>
  :root {{
    --bg: #F5EFE3; --fg: #1a2952; --muted: #6b6258;
    --ok: #3d7d3d; --warn: #e87722; --bad: #c8261f;
    --card: #fff; --line: #d8cfb8;
  }}
  body {{ background: var(--bg); color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif;
    margin: 0; padding: 24px; }}
  h1 {{ margin: 0 0 8px; font-size: 22px; }}
  .summary {{ color: var(--muted); margin-bottom: 24px; font-size: 14px; }}
  .toolbar {{ position: sticky; top: 0; background: var(--bg);
    padding: 12px 0 16px; border-bottom: 1px solid var(--line);
    margin-bottom: 16px; z-index: 10; }}
  button {{ padding: 8px 16px; border: 1px solid var(--fg);
    background: var(--fg); color: var(--bg); border-radius: 4px;
    font-size: 14px; cursor: pointer; margin-right: 8px; }}
  button.secondary {{ background: transparent; color: var(--fg); }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 16px; }}
  .card {{ background: var(--card); border: 1px solid var(--line);
    border-radius: 6px; overflow: hidden; }}
  .thumb {{ width: 100%; aspect-ratio: 1 / 1;
    background: #ece2cf; display: flex; align-items: center; justify-content: center; }}
  .thumb img {{ width: 100%; height: 100%; object-fit: contain; }}
  .missing {{ color: var(--bad); font-size: 12px; }}
  .meta {{ padding: 12px; }}
  .name {{ font-weight: 600; }}
  .sub {{ color: var(--muted); font-size: 12px; margin: 2px 0 8px; }}
  .score {{ font-size: 13px; margin-bottom: 10px; }}
  .badge {{ display: inline-block; padding: 1px 6px; border-radius: 3px;
    font-size: 11px; font-weight: 600; color: #fff; margin-left: 4px; }}
  .badge.ok {{ background: var(--ok); }}
  .badge.warn {{ background: var(--warn); }}
  .vote label {{ display: inline-flex; align-items: center;
    margin-right: 10px; font-size: 13px; cursor: pointer; }}
  .vote input {{ margin-right: 4px; }}
  .bad {{ color: var(--bad); }}
  .ok {{ color: var(--ok); }}
</style>
</head>
<body>
  <h1>Forge v4 batch — contact sheet + grading</h1>
  <div class="summary">{summary_line}</div>
  <div class="toolbar">
    <button onclick="exportVotes()">Export votes as JSON</button>
    <button class="secondary" onclick="markAllSkip()">Reset (mark all ?)</button>
    <span style="color: var(--muted); font-size: 13px; margin-left: 16px;">
      Use the radio buttons to grade each render. Click Export when done — that JSON
      is what gets dropped into `brand/madhubani/labels_v2.json` for the next agreement study.
    </span>
  </div>
  <div class="grid">{''.join(rows)}</div>
  <script>
    function markAllSkip() {{
      document.querySelectorAll('input[value="skip"]').forEach(el => el.checked = true);
    }}
    function exportVotes() {{
      const votes = [];
      document.querySelectorAll('.card').forEach(card => {{
        const slug = card.dataset.slug;
        const checked = card.querySelector('input[type="radio"]:checked');
        votes.push({{ slug, vote: checked ? checked.value : 'skip' }});
      }});
      const data = {{
        schema: 'forge.user_grading.v1',
        ts: new Date().toISOString(),
        votes
      }};
      const blob = new Blob([JSON.stringify(data, null, 2)], {{type: 'application/json'}});
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'v4_user_votes_' + new Date().toISOString().slice(0,10) + '.json';
      a.click();
      URL.revokeObjectURL(url);
    }}
  </script>
</body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--summary", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()
    if not args.summary.exists():
        raise SystemExit(f"summary not found: {args.summary}")
    summary = json.loads(args.summary.read_text())
    html = build_html(summary)
    args.out.write_text(html, encoding="utf-8")
    print(f"Wrote {args.out}")
    print(f"  {len(summary.get('statuses', []))} species in the sheet")
    print(f"  open {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
