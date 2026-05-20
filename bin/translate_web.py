#!/usr/bin/env python3
"""Translate Studio — one-click multi-format translation UI.

Stdlib-only HTTP server, mirroring `forge_web.py`'s pattern. Default bind is
local-only. The UI shipped here is intentionally minimal: paste text or
upload a file, pick a target language, optionally enable subtitle output,
press Translate. Backend pipeline:

  input_adapter.read_as_text   →   translate_texts_ollama (with glossary + leakage)
                              ↘
                                engine_qc.write_translation_blockers   →   publishable + blockers.json
                              ↘
                                (optional) subtitle estimate as SRT

Subtitles here are sentence-timed estimates, not Whisper-aligned. Aligning
requires audio (TTS first), which lives in `bin/audiobook.py`. The flow
explicitly distinguishes "estimate" from "aligned" so reviewers know what
they're looking at.

Usage:
    python3 bin/translate_web.py --host 127.0.0.1 --port 5003
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import engine_qc
import input_adapter
from forge_runtime import translate_texts_ollama


SUPPORTED_LANGS = [
    ("en", "English"),
    ("hi", "Hindi (हिन्दी)"),
    ("mr", "Marathi (मराठी)"),
]
STATE_DIR = Path.home() / ".forge" / "translate-web"
STATE_DIR.mkdir(parents=True, exist_ok=True)


# ─────────────── pipeline core ───────────────


def _estimate_srt(translated_text: str, *, lang: str, words_per_second: float = 2.4) -> str:
    """Produce a sentence-timed SRT estimate. Not Whisper-aligned.

    Sentence detection: split on `.!?…।` followed by whitespace, plus newlines.
    Allocates ~words/2.4 seconds per cue (typical narration pace), with a 1.5s
    floor per cue so short fragments don't flash by.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[\.\!\?…।])\s+|\n+", translated_text) if s.strip()]
    cues: list[str] = []
    cursor = 0.0
    for idx, sentence in enumerate(sentences, start=1):
        words = max(1, len(sentence.split()))
        dur = max(1.5, words / words_per_second)
        start = cursor
        end = cursor + dur
        cursor = end
        cues.append(
            f"{idx}\n{_srt_ts(start)} --> {_srt_ts(end)}\n{sentence}\n"
        )
    header = f"NOTE forge.translate_web.v1 estimate (lang={lang}, wps={words_per_second})\n\n"
    return header + "\n".join(cues)


def _srt_ts(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def run_translation(
    *,
    source_text: str,
    target_lang: str,
    glossary: dict[str, dict[str, str]] | None = None,
    want_subtitles: bool = False,
    job_dir: Path,
) -> dict[str, Any]:
    """Run the end-to-end translate pipeline; return a manifest-shaped dict.

    Writes (always): job_dir/source.txt, job_dir/translation.txt,
                     job_dir/translation.qc.json,
                     job_dir/manifest.json
    Writes (failing-only): job_dir/translation.txt.blockers.json
    Writes (if requested): job_dir/translation.srt (sentence-estimate)
    """
    job_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()

    # Sentence-paragraph split so the translator gets a manageable batch.
    paragraphs = [p.strip() for p in source_text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [source_text.strip()] if source_text.strip() else []

    report: dict[str, Any] = {}
    translated_paragraphs = translate_texts_ollama(
        paragraphs,
        target_lang=target_lang,
        glossary=glossary,
        out_report=report,
    )
    translated_text = "\n\n".join(translated_paragraphs)

    source_path = job_dir / "source.txt"
    translation_path = job_dir / "translation.txt"
    source_path.write_text(source_text, encoding="utf-8")
    translation_path.write_text(translated_text + "\n", encoding="utf-8")

    blockers_path, blockers, qc_pass = engine_qc.write_translation_blockers(translation_path, report)
    publishable = engine_qc.is_publishable(blockers)

    srt_path = None
    if want_subtitles:
        srt_path = job_dir / "translation.srt"
        srt_path.write_text(_estimate_srt(translated_text, lang=target_lang), encoding="utf-8")

    elapsed = time.time() - started
    manifest = {
        "schema": "forge.translate_web.v1",
        "started_at": started,
        "elapsed_seconds": round(elapsed, 2),
        "target_lang": target_lang,
        "source_kind": "text",
        "source_path": str(source_path),
        "translation_path": str(translation_path),
        "srt_path": str(srt_path) if srt_path else None,
        "qc_path": str(translation_path.with_suffix(engine_qc.QC_SUFFIX)),
        "blockers_path": str(blockers_path) if blockers_path else None,
        "blockers": [b["check"] for b in blockers],
        "publishable": publishable,
        "qc_pass": qc_pass,
        "glossary_used": bool(glossary and glossary.get(target_lang)),
        "report": report,
    }
    (job_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


# ─────────────── HTML ───────────────


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<title>Forge — Translate Studio</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; max-width: 880px; margin: 32px auto; padding: 0 24px; color: #2a2a2a; }
  h1 { font-weight: 600; margin-bottom: 6px; }
  .hint { color: #888; font-size: 13px; margin-bottom: 24px; }
  label { display: block; font-weight: 500; margin-top: 18px; margin-bottom: 6px; }
  textarea, select, input[type=text] { width: 100%; padding: 10px; font-size: 14px; border: 1px solid #ccc; border-radius: 6px; box-sizing: border-box; font-family: inherit; }
  textarea { min-height: 180px; resize: vertical; }
  .row { display: flex; gap: 16px; }
  .row > * { flex: 1; }
  .opts { margin-top: 18px; padding: 14px 16px; background: #f7f7f7; border-radius: 6px; }
  .opts label { display: inline-flex; align-items: center; gap: 8px; margin: 6px 16px 0 0; font-weight: 400; }
  button { margin-top: 22px; padding: 12px 24px; font-size: 15px; font-weight: 500; background: #1f6feb; color: white; border: 0; border-radius: 6px; cursor: pointer; }
  button:disabled { background: #999; cursor: wait; }
  .result { margin-top: 32px; padding: 18px; border: 1px solid #ddd; border-radius: 8px; background: #fafafa; }
  .result.ok { border-color: #2ea043; background: #f0f9f3; }
  .result.warn { border-color: #d97706; background: #fef6ec; }
  .blockers { margin-top: 12px; padding: 10px 14px; background: #fff3cd; border-left: 3px solid #d97706; border-radius: 4px; font-size: 13px; }
  pre { background: white; padding: 12px; border-radius: 4px; white-space: pre-wrap; word-break: break-word; max-height: 320px; overflow: auto; font-size: 13px; }
  .links { margin-top: 12px; font-size: 13px; color: #666; }
  .links code { background: #eee; padding: 2px 6px; border-radius: 3px; font-size: 12px; }
  details { margin-top: 12px; }
  details summary { cursor: pointer; color: #1f6feb; font-size: 13px; }
</style>
</head>
<body>
  <h1>Translate Studio</h1>
  <div class="hint">Paste text, pick a language, press Translate. Trust layer (glossary, leakage, repeated-line detection) runs automatically — blockers surface in the result.</div>

  <form id="form">
    <label for="source">Source text</label>
    <textarea id="source" name="source" placeholder="Paste the text you want translated…" required></textarea>

    <div class="row">
      <div>
        <label for="target">Target language</label>
        <select id="target" name="target_lang">
          <option value="hi">Hindi (हिन्दी)</option>
          <option value="mr">Marathi (मराठी)</option>
          <option value="en">English</option>
        </select>
      </div>
      <div>
        <label for="source_lang">Source language</label>
        <select id="source_lang" name="source_lang">
          <option value="en">English</option>
          <option value="hi">Hindi</option>
          <option value="mr">Marathi</option>
        </select>
      </div>
    </div>

    <div class="opts">
      <label><input type="checkbox" id="subtitles" name="subtitles" /> Generate sentence-timed SRT estimate</label>
    </div>

    <details>
      <summary>Glossary (advanced — pin terms exactly)</summary>
      <label for="glossary">JSON: <code>{"<target_lang>": {"source": "target", ...}}</code></label>
      <textarea id="glossary" name="glossary" placeholder='{"hi": {"Forge": "फ़ोर्ज", "tiger": "बाघ"}}' style="min-height: 80px;"></textarea>
    </details>

    <button type="submit" id="submit">Translate</button>
  </form>

  <div id="result"></div>

<script>
const form = document.getElementById('form');
const submit = document.getElementById('submit');
const resultBox = document.getElementById('result');

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  submit.disabled = true;
  submit.textContent = 'Translating…';
  resultBox.innerHTML = '';
  let glossary = null;
  const gstr = document.getElementById('glossary').value.trim();
  if (gstr) {
    try { glossary = JSON.parse(gstr); }
    catch (err) {
      resultBox.innerHTML = '<div class="result warn">Glossary JSON is invalid: ' + err.message + '</div>';
      submit.disabled = false; submit.textContent = 'Translate';
      return;
    }
  }
  const payload = {
    source: document.getElementById('source').value,
    target_lang: document.getElementById('target').value,
    source_lang: document.getElementById('source_lang').value,
    subtitles: document.getElementById('subtitles').checked,
    glossary: glossary,
  };
  try {
    const res = await fetch('/api/translate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      resultBox.innerHTML = '<div class="result warn">Error: ' + (data.error || 'unknown') + '</div>';
    } else {
      renderResult(data);
    }
  } catch (err) {
    resultBox.innerHTML = '<div class="result warn">Network error: ' + err.message + '</div>';
  } finally {
    submit.disabled = false;
    submit.textContent = 'Translate';
  }
});

function renderResult(data) {
  const cls = data.publishable ? 'ok' : 'warn';
  const status = data.publishable ? '✓ publishable' : '! blocked — review';
  let html = '<div class="result ' + cls + '">';
  html += '<strong>' + status + '</strong> · ' + data.elapsed_seconds + 's · target=' + data.target_lang;
  if (data.glossary_used) html += ' · glossary applied';
  if (data.blockers.length) {
    html += '<div class="blockers"><strong>Blockers:</strong> ' + data.blockers.join(', ') + '</div>';
  }
  html += '<label style="margin-top:16px">Translation</label>';
  html += '<pre>' + escapeHtml(data.translation_text || '') + '</pre>';
  html += '<div class="links">';
  html += 'Files: <code>' + data.translation_path + '</code>';
  if (data.srt_path) html += ' · <code>' + data.srt_path + '</code>';
  html += ' · QC <code>' + data.qc_path + '</code>';
  if (data.blockers_path) html += ' · Blockers <code>' + data.blockers_path + '</code>';
  html += '</div>';
  html += '</div>';
  resultBox.innerHTML = html;
}
function escapeHtml(s) { return (s || '').replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c])); }
</script>
</body>
</html>
"""


# ─────────────── HTTP handler ───────────────


class TranslateHandler(BaseHTTPRequestHandler):
    server_version = "ForgeTranslate/0.1"

    def log_message(self, _fmt: str, *_args: Any) -> None:
        return

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, body: str, content_type: str = "text/html; charset=utf-8", status: int = 200) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self._text(INDEX_HTML)
        elif parsed.path == "/health":
            self._json({"status": "ok", "supported_langs": [code for code, _ in SUPPORTED_LANGS]})
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/api/translate":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length > 0 else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError as e:
            self._json({"error": f"invalid JSON: {e}"}, HTTPStatus.BAD_REQUEST)
            return
        source = (payload.get("source") or "").strip()
        target_lang = (payload.get("target_lang") or "hi").strip()
        glossary = payload.get("glossary")
        want_subtitles = bool(payload.get("subtitles"))
        if not source:
            self._json({"error": "source text is empty"}, HTTPStatus.BAD_REQUEST)
            return
        if target_lang not in {code for code, _ in SUPPORTED_LANGS}:
            self._json({"error": f"unsupported target_lang: {target_lang}"}, HTTPStatus.BAD_REQUEST)
            return
        job_id = f"job-{int(time.time())}-{abs(hash(source)) % 100000:05d}"
        job_dir = STATE_DIR / job_id
        try:
            manifest = run_translation(
                source_text=source,
                target_lang=target_lang,
                glossary=glossary if isinstance(glossary, dict) else None,
                want_subtitles=want_subtitles,
                job_dir=job_dir,
            )
        except Exception as e:
            self._json({"error": str(e), "job_dir": str(job_dir)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        # Inline the translation text for the UI to render without a second fetch
        try:
            manifest["translation_text"] = Path(manifest["translation_path"]).read_text(encoding="utf-8")
        except OSError:
            pass
        self._json(manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description="Forge Translate Studio (local UI)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5003)
    parser.add_argument("--no-open", action="store_true", help="don't open a browser tab")
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), TranslateHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Forge Translate Studio running at {url}")
    print(f"State dir: {STATE_DIR}")
    if not args.no_open:
        threading.Timer(0.6, lambda: webbrowser.open_new_tab(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
