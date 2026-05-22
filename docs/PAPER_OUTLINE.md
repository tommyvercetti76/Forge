# Forge — Paper Outline + Abstracts

**Status:** Draft 2026-05-22. Two abstract variants below — A leans ML, B leans methodology/FAccT. Both ready for arXiv preprint; either fits a workshop submission with v6 numbers populated.

**Working title:** *Forge: Closed-Loop Cultural-Heritage Image Generation on Apple Silicon — Receipts, Human Grading, and Honest Failure Analysis*

---

## Abstract — Variant A (ML-leaning, 199 words)

> Generative image models reproduce living cultural traditions opaquely: **prior collisions** (a model's "snow leopard" prior defaults to a cheetah body even when the prompt requests Mithila folk-art register) and **missing provenance** (which training image taught what?) compound when rendering folk-art forms. We describe **Forge**, a fully-local Apple Silicon pipeline (M5 Max) that renders 41 Indian-wildlife species in Madhubani folk-art register, grounded in 100% open-license data: 50 Mithila reference paintings and 328 species photographs (Wikimedia Commons, strict CC-BY/SA/CC0/PD). Every rendered artifact ships with a **SHA-256 receipt chain** spanning model weights, LoRA adapter, prompt hash, init image, and license attribution. We measure tradition fidelity via a 10-check structural rubric plus a class-balanced CLIP probe (F1 0.615 on N=16 LOOCV; baseline F1 0.00). Our v1 LoRA achieves +0.0357 mean ΔComposite on held-out species — *below* our pre-registered +0.05 ship threshold — surfacing prior-collision failures (cobra-with-two-tongues, leopard-tan snow-leopard) that prompt engineering alone cannot resolve. We detail v2's photo-init Kontext-img2img methodology addressing these failures, with results pending. All artifacts, intermediate experiments, ITERATE-verdict data, and 76 open-access citations are released. Reproducible from `git clone` + rehydrate.

**Use for:** NeurIPS Creativity & AI Workshop · ICML AI for Science Workshop · ML-leaning audiences.

---

## Abstract — Variant B (methodology-leaning, 170 words)

> Most generative-art systems offer outputs without provenance; ours ships outputs with a receipt. **Forge** is a local pipeline running on Apple Silicon (M5 Max, mflux + MLX) that renders 41 Indian-wildlife species in the Madhubani folk-art register via a closed human-feedback loop: render → 10-check structural rubric → class-balanced CLIP probe (F1 0.615) → best-of-N picker → retry-with-targeted-boost → LoRA training on PASS-graded outputs → paired-delta eval on held-out species. All training data is 100% open-license (50 Mithila references + 328 species photos, strict CC-BY/SA/CC0/PD), all artifacts carry SHA-256 + license + author receipts, and 76 open-access papers ground every claim in the species knowledge base. Our v1 LoRA returned an **ITERATE verdict** (+0.0357 mean ΔComposite, below +0.05 ship threshold), with prior-collision failures the centerpiece of the negative result. We release the pipeline, the intermediate failures, the photo-init v2 methodology, and a documented path to v3.

**Use for:** ACM FAccT · CHI Generative AI Workshop · venues that reward provenance/transparency.

---

## Target venues (priority order)

| Venue | Type | Fit | Submission window | Acceptance rate |
|---|---|---|---|---|
| **arXiv** | preprint | Any time | rolling | N/A |
| **ACM FAccT** (Fairness/Accountability/Transparency) | conference | **Strong** — receipt chain + cultural attribution + open-license maps directly | January submission | ~25% main, ~35% short |
| **NeurIPS Creativity & AI Workshop** | workshop | **Strong** — creativity + open data + honest failures | December submission | ~40% |
| **CHI Generative AI Workshop** | workshop | **Strong** — HCI + cultural framing + human-in-the-loop | January submission | ~50% |
| **ICML AI for Science Workshop** | workshop | Moderate — provenance angle | April submission | ~45% |
| **CHI Late-Breaking Work** | conference LBW | Moderate — needs better user study | January submission | ~60% |

**Recommended path:** arXiv preprint THIS WEEK (no venue gate), then FAccT main-track submission in January with v6 numbers + blind-A/B human eval + inter-annotator agreement populated.

---

## Section structure (8-page workshop format, populated as v6 results land)

### 1. Introduction
- Generative models for cultural heritage: state of the art (cite Yamuna et al., Mehrotra 2022 on Indian folk-art GANs)
- The provenance problem in training data
- The prior-collision problem (with concrete example: snow-leopard render comparison v4 vs v5 vs v6)
- **Contribution claims:**
  1. A fully-local, fully-open-license pipeline for cultural-heritage image generation
  2. Receipt-chained reproducibility (SHA-256 from model to artifact)
  3. Honest failure reporting via pre-registered thresholds
  4. Photo-init Kontext-img2img as the fix for prior collisions

### 2. Related work
- Cultural-heritage generative AI (cite recent papers)
- LoRA + small-corpus fine-tuning (cite Hu et al. 2021, recent style-LoRA work)
- Provenance + watermarking (cite C2PA, OpenAI provenance specs)
- Open-license training data (cite LAION-Aesthetics audit work)

### 3. Methodology
- **3.1 Catalog + reference corpus:** 41 species, 50 Mithila refs, 328 species photos. Open-license discipline. Receipt schema (Figure: schema diagram).
- **3.2 Closed feedback loop:** rubric → CLIP probe → best-of-N → retry-with-boost → LoRA → eval (Figure: pipeline diagram with arrows + ledger).
- **3.3 Knowledge base inheritance:** orders → families → body types → species (Figure: dependency graph).
- **3.4 Prior-collision detection + fix:** signature-features prompts (v5), photo-init img2img (v6).

### 4. Honest measurement
- **4.1 The metric:** composite = 0.6 × rubric + 0.4 × CLIP probability
- **4.2 The probe collapse:** F1 0.89 (N=9) → F1 0.00 (N=16 LOOCV) → F1 0.615 (class-balanced) (Table)
- **4.3 The composite saturation:** rubric pass-rate ceiling at ~1.0 for many species. Identified, will be addressed via per-zone probes (future work).

### 5. Experiments + results
- **5.1 v4 baseline:** 41 species rendered, 29 user-PASS, mean composite 0.7534 (Table)
- **5.2 v5 with signature-features:** 41 species, 41 user-PASS (+41%), but anatomy_broken UP +7, cartoon UP +7 (Table)
- **5.3 v1 LoRA verdict:** ITERATE (+0.0357 mean ΔComposite on held-out, below +0.05 ship) (Table)
- **5.4 v2 LoRA (TBD):** [populate when v2 eval runs]
- **5.5 v6 photo-init (TBD):** [populate when v6 batch + eval run]
- **5.6 Per-species breakdown:** Which species moved, which stayed broken (Figure: heatmap)
- **5.7 Blind A/B human eval (TBD):** [populate when N=50 blind eval runs]
- **5.8 Inter-annotator agreement (TBD):** Cohen's κ on ≥2-annotator subset

### 6. Discussion
- What worked: receipt chain, open-license corpus, honest negative results
- What didn't: composite saturation, single-labeler bias, FLUX cross-architecture
- Limitations:
  - Single-tradition (Madhubani); generalizing requires per-tradition KB work
  - Single labeler (Rohan); inter-annotator gap pending
  - 41-species scope; catalog expansion to 100 is queued

### 7. Cultural attribution + ethics
- Mithila tradition acknowledgment
- Open-license discipline (strict CC-BY/SA/CC0/PD; 0 NC)
- Future product partnership commitment with Mithila artists (revenue share)
- Risk surface: extractive use vs. supportive amplification (discuss)

### 8. Conclusion + future work
- Forge as a reproducibility-first generative-AI pipeline
- v3 (after v6 verdict): per-zone CLIP probes + LoRA stack + multi-tradition
- v4+: blind A/B at N=200, partnership-backed art curation, multi-tradition LoRAs

---

## Numbers we'll commit to once measured

| Metric | Current value | Status |
|---|---|---|
| Open-license refs | 50 Mithila + 328 species | ✅ measured |
| Species in catalog | 41 (target: 100) | ✅ |
| Citations in KB | 76 open-access | ✅ growing |
| v1 LoRA ΔComp | +0.0357 (held-out, scale 0.75) | ✅ measured |
| v2 LoRA ΔComp | TBD | 🚧 in training |
| v6 photo-init ΔComp | TBD | 🚧 pipeline ready |
| Composite ceiling | ~0.82 (rhino) | ✅ documented |
| CLIP probe F1 | 0.615 (LOOCV N=16) | ✅ |
| Blind A/B human eval | N=0 | ❌ pending |
| Inter-annotator κ | N/A (single labeler) | ❌ pending |

---

## Figures we need

1. **Pipeline diagram** — render → rubric → probe → picker → retry → LoRA → eval → ledger
2. **Receipt schema** — JSON envelope showing SHA-256 chain
3. **Knowledge base inheritance** — orders → families → body types → species dependency
4. **Per-species ΔComposite heatmap** — 4 held-out species × 3 scales × {v1 LoRA, v2 LoRA, v6}
5. **Side-by-side renders** — v4 vs v5 vs v6 for the 5 priority failure species
6. **Probe F1 evolution** — 0.89 (N=9) → 0.00 (N=16 LOOCV) → 0.615 (class-balanced) on the same data
7. **Cultural-attribution receipt example** — full schema rendered from a real artifact

---

## What this document is NOT

- Not a marketing pitch. The honest verdict (ITERATE) is the headline, not a hidden footnote.
- Not promising results we don't have. v2 LoRA + v6 photo-init are in flight; numbers will follow.
- Not claiming novelty beyond the pipeline integration. LoRA + img2img + CLIP probe are standard techniques; the contribution is the **receipt chain + honest failure reporting + cultural-attribution discipline** wrapping them.
- Not pursuing top-tier ML venues (NeurIPS main track). Workshop + FAccT main are the realistic targets.

---

*Last updated: 2026-05-22. Will be re-versioned after v6 batch verdict + blind-A/B human eval lands.*
