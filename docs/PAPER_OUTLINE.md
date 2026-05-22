# Forge v3.0 — Technical Publication Outline

**Status:** Draft, pre-experiment (2026-05-22). Numbers TBD pending the Saturday-evening v3.0 catalog render. Submission-ready by end of following week.

This document is the **publication thread** for Forge v3.0 work. Every claim made here will be backed by a measurement we run. Every limitation will be stated explicitly. This is the artifact reviewers will read; the repo is the proof.

---

## Working title

> **Forge: On-Device, Measurement-Gated Generative Indian Folk and Traditional Art on Apple Silicon — A Reference Implementation with Empirical Provenance and Cross-Tradition Catalog Production**

Alternative shorter framings:
- "On-device measured generation of Indian folk-art catalogs on Apple Silicon"
- "Closed-loop reasoning for culturally-attributed generative folk art: a reference architecture"

---

## Target venues — in order of fit

| Tier | Venue | Why fit | Realistic timeline |
|---|---|---|---|
| **Primary** | **arXiv preprint** (cs.AI + cs.CV + cs.CY cross-list) | No bar to entry. Sets the public record date. Gives reviewers something to cite. | Posted within 7 days of v3.0 ship |
| **Workshop A** | **NeurIPS 2026 Creative AI Workshop** | Creative-generation fits; on-device + measurement-discipline is novel | Submission deadline typically September 2026 |
| **Workshop B** | **EMNLP / ACL Computational Approaches to Cultural Heritage** | Cultural-attribution methodology is a strong fit here | August-October 2026 cycles |
| **Workshop C** | **CHI 2027 Creativity & Cognition** | Tooling-for-creators framing | September 2026 deadline |
| **Workshop D** | **FAccT 2027** | Provenance + cultural-attribution as algorithmic accountability | November 2026 deadline |

Strategy: arXiv first, then workshop submission to NeurIPS Creative AI (highest signal). FAccT as a backup if Creative AI is rejected — the cultural-attribution framing transfers well there.

---

## Abstract (target ~180 words, draft)

We present **Forge**, an open reference implementation for measurement-gated, culturally-attributed generation of Indian folk and traditional art on consumer Apple Silicon. Forge ships a catalog of *N* species across 25 Indian national parks (2 mammals + 2 birds per park) rendered through *T* canonical folk and traditional traditions (Madhubani, Pahari, Kalighat, Tanjore, Ravi-Varma), with every output carrying a versioned provenance receipt linking it to (a) base model + LoRA hashes, (b) cultural reference sources with open-license attribution, and (c) a measurable QC rubric pass/fail. We make four contributions: (i) a **multi-tradition style and protocol registry** that scales across cultural heritage with explicit per-tradition consultation commitments; (ii) **empirical M5 Max throughput benchmarks** for FLUX workloads, demonstrating multi-seed batched generation reduces wall-clock by *X*% over naïve loops; (iii) a **closed-loop quality-gate methodology** with rubric-driven retry, measured against a *N*=16 maintainer-labeled gold corpus at F1 *0.62*; (iv) an **explicit open-source viability audit** of 10 Indian folk-art traditions identifying which can ship with full named-artist provenance and which require deferred cultural consultation. Forge is MIT-licensed; the receipt schema, training pipeline, and demo catalog are reproducible from `forge reproduce <receipt-id>`. We do not claim novel architectures or SOTA on standard benchmarks; the contribution is a measurement and provenance methodology demonstrated at scale.

---

## Section plan (8 pages target, workshop format)

### 1. Introduction (1 page)

**Hook:** AI-generated cultural-heritage imagery raises three open questions:
1. How do we attribute training-data provenance back to a living artistic tradition?
2. How do we measure when a generated artifact respects vs. distorts the tradition's grammar?
3. Can this be done at production scale on consumer hardware, or does it require cloud GPUs?

**Claim:** Forge answers (1) with a versioned receipt schema, (2) with a rubric-driven closed-loop QC gate, and (3) with a measured Apple Silicon throughput pipeline.

**Contributions** (matched to abstract).

**Non-contributions** (explicit, paper-survival-critical):
- We do **not** propose a new generative architecture.
- We do **not** claim SOTA on FID, KID, or any standard image-generation benchmark.
- We do **not** claim our QC rubric is the only or best one; we claim it is *measurable* against human gold labels with reported F1.

---

### 2. Related work (1 page)

Cover four threads:

| Thread | Anchors |
|---|---|
| **Content provenance / C2PA / model cards** | Mitchell et al. 2018 (Model Cards), Gebru et al. 2018 (Datasheets for Datasets), Coalition for Content Provenance and Authenticity (C2PA) spec |
| **Cultural-heritage generative AI** | Recent NeurIPS / CHI / ACM Multimedia workshop papers on cultural-AI ethics; existing AI-art-and-tradition tension literature |
| **On-device generative AI** | mflux + MLX + Apple Silicon work; edge-deployment papers; on-device diffusion benchmarks |
| **Closed-loop / agentic generation** | Best-of-N sampling, RLHF preference learning, iterative refinement methods |

Position: **Forge extends the C2PA / model-cards tradition to the *cultural-attribution* axis**, with a reference implementation for folk-art catalogs as the demonstration.

---

### 3. System architecture (1.5 pages)

**Figure 1**: Forge architecture diagram — shared substrate (mflux + Whisper + Sarvam + Ollama + Kokoro) feeding parallel pipelines (image catalog, audiobook, brand factory, video). Style + protocol registry as the cross-cutting concern.

**Figure 2**: The receipt schema (excerpt) — universal envelope + modality-specific payload + integrity hash chain.

**Figure 3**: The closed-loop reasoning engine — render → score → boost → re-render with retry decision tree.

Subsections:
- 3.1 Style registry (EnumBank in `style_engines.py` + tradition-specific assets in `brand/<tradition>/`)
- 3.2 Cultural protocol registry (`docs/CULTURAL_HERITAGE_ATTRIBUTION_*.md` per tradition)
- 3.3 Reference corpus pipeline (`fetch_wikimedia_category.py` + `rehydrate_references.py` + per-tradition `_audit.py`)
- 3.4 LoRA training queue (one LoRA per tradition; Madhubani v3 trained at *N*=50 references)
- 3.5 Catalog rendering (multi-seed batched, FORGE_METAL_SLOTS=4 parallel)
- 3.6 QC + best-of-N (rubric + composite picker)
- 3.7 Receipt emission + verification (`forge verify`, `forge reproduce`)

---

### 4. Catalog and tradition scope (1 page)

**Table 1**: The 25 Indian national parks with biome/region/elevation/iconic-species/conservation-status metadata. Mapping to the 100-entry catalog (2 mammals + 2 birds per park; 3 documented exceptions for lagoon/marine/bird-sanctuary parks).

**Table 2**: The 5 officially-supported Indian folk and traditional art traditions (Madhubani, Pahari, Kalighat, Tanjore, Ravi-Varma) with named open-source masters per tradition.

**Section 4.3 (the honesty section)**: The tradition pruning. We explicitly excluded Gond, Phad, Pichwai, Pattachitra, Kalamkari, Mysore, and contemporary-Warli from this paper's scope because their named-artist open-source references would require copyright permissions (artists alive within 70-year copyright window) or insufficient pre-modern public-domain archive. **This pruning is the contribution — not a limitation.** A tradition that cannot meet open-source-attribution requirements is honestly excluded; future work with explicit cultural consultation can extend the scope.

---

### 5. Empirical results (2.5 pages — the meat)

**Subsection 5.1: M5 Max throughput**

| Workload | Naïve baseline | Forge | Speedup |
|---|---|---|---|
| 4-seed FLUX.1-schnell, 640², cool profile | 106.7s | 41.9s | **−60.8%** (already measured in commit b618f2c) |
| Same on quality/dev (P1 multi-seed) | TBD | TBD | TBD (~−15-20% expected) |
| 4-pose Madhubani set, `--jobs 2` parallel | 4 waves | 2 waves | **up to −50%** |
| LoRA training time (Madhubani v3, 50 refs, rank 32, 1500 steps) | N/A | TBD | TBD (~12 hrs expected; baseline 9 min 31 s pilot at rank 16, 500 steps) |
| 87-entry × 4 poses catalog render at FORGE_METAL_SLOTS=4 | TBD (linear) | TBD | TBD |

To measure post-render Saturday.

**Subsection 5.2: Closed-loop quality lift**

Compare per-render rubric pass rate:
- Naïve single-seed render
- Best-of-N picker (N=4 seeds, compute-matched to closed-loop)
- Closed-loop with N retries (rubric-driven retry-with-targeted-boost)

Across the 87 catalog × 4 poses = 348 render trials. Report:
- Per-strategy pass rate
- Per-strategy mean QC score
- Statistical comparison (paired t-test or Wilcoxon)

Pre-registered hypothesis: closed-loop > best-of-N > naïve. Magnitude TBD.

**Subsection 5.3: Auto-QC F1 vs human gold corpus**

Already measured (`docs/QC_AGREEMENT_STUDY.md`):
- Heuristic rubric: F1 0.53 LOOCV at N=16
- Class-balanced CLIP probe v2: F1 0.615 LOOCV
- Composite picker ceiling on rhino: 0.82

Add v3.0 numbers post-LoRA-retrain.

**Subsection 5.4: Cross-tradition identity preservation (if we get there)**

The species-identification-across-styles experiment: render the same species in Madhubani vs. Pahari vs. (any other available). Run CLIP zero-shot classification; measure species top-1 accuracy across styles.

Pre-registered hypothesis: ≥75% per-style species identifiability. Numbers TBD.

If we don't get Pahari LoRA trained by Saturday evening, defer 5.4 to v3.1 paper revision and ship 5.1-5.3 as the core empirical contribution.

---

### 6. Cultural attribution methodology (1 page)

**Subsection 6.1**: The receipt schema — what's checkable, what isn't.

**Subsection 6.2**: The tradition-protocol design — community ownership, named-lineage acknowledgment, novel-subject disclosure, refusal categories.

**Subsection 6.3**: The Bhajju-Shyam-London-Jungle-Book precedent for novel-subject extension. Why some traditions (Gond especially) **explicitly cannot** be open-source-ML-corpus-built without permission, and why Forge's protocol-doc-before-corpus pattern is the safer default.

---

### 7. Limitations and honesty section (0.5 page — the critical honest one)

Pre-emptive disclosure of what reviewers will catch:

| Limitation | Honest framing |
|---|---|
| N=16 gold corpus is statistically thin | We report LOOCV F1 with explicit confidence noting small-N. Larger N is future work, not a denial of the gap. |
| Only 1 LoRA fully trained by ship time (Madhubani v3) | Pahari LoRA queued; other 3 traditions ship prompt-only with EnumValue grammar. Explicit. |
| Apple Silicon only | Yes. Stated upfront. NVIDIA port is future work; we don't claim cross-platform generality. |
| No formal cultural-expert validation yet | Protocol-pre-consultation status documented per-tradition. Cold outreach to Mithila Art Institute / Bhajju Shyam estate is logged but not yet completed. |
| LoRA training corpus dominated by community uploads, not named-master work | Master citations in style_engines.py + bibliography in MADHUBANI_BIBLIOGRAPHY.md are documented; corpus is broader than master-only |
| Single-author preprint | Acknowledged. Co-author invitation pending DeepMind contact. |

---

### 8. Conclusion + future work (0.5 page)

**Conclusion**: Forge demonstrates that on-device, measurement-gated, culturally-attributed generative art is feasible on consumer Apple Silicon, with full reproducibility from receipts.

**Future work** (concrete, not vapor):
1. NVIDIA / cross-platform port
2. Pahari + Kalighat + Tanjore + Ravi-Varma LoRAs (queued)
3. iNaturalist + Macaulay Library animal-photo conditioning via IP-Adapter
4. Mithila Art Institute consultation completion
5. N=100 gold-corpus expansion
6. Voice-cloned ASMR audiobook pipeline (separate paper)

---

## Figure list (must-have for visual story)

| # | Figure | Source |
|---|---|---|
| 1 | Architecture diagram (substrate + pipelines + registries) | New SVG |
| 2 | Receipt schema (excerpt) | `docs/SCHEMA.md` |
| 3 | Closed-loop reasoning flowchart | New SVG |
| 4 | Sample catalog renders (2x2 grid: Tiger / Peacock / Snow Leopard / Hornbill in Madhubani v3) | Post-Saturday |
| 5 | Cross-style identity preservation (species rendered in 2 traditions side-by-side) | Post-Saturday, if Pahari LoRA done |
| 6 | M5 Max throughput chart (multi-seed batching speedup curve) | Existing measurement + new |
| 7 | QC F1 over training rounds (Madhubani v2 → v3 progression) | New plot |

---

## Tables (must-have)

| # | Table | Source |
|---|---|---|
| 1 | 25 parks × biome/region/area | `brand/parks/_index.json` |
| 2 | 5 supported traditions × open-source attribution status | `brand/styles/_index.json` (deprecated; rewriting under section 3.1) |
| 3 | M5 Max throughput benchmarks | Existing + new measurements |
| 4 | Per-strategy rubric pass rate (naïve vs best-of-N vs closed-loop) | Post-Saturday measurement |
| 5 | Auto-QC F1 against human gold (N=16) per Madhubani version | Existing + new |

---

## Ship schedule (aggressive — Saturday-evening target)

| When | What | Status |
|---|---|---|
| **Now (Thu)** | Catalog at 87/100, 5 commits landed (parks, schema, refactor, batch A, batch B). Fetcher + orchestrator script + paper outline shipped. | ✅ |
| **Tomorrow (Fri 6pm)** | Run `bin/weekend_kickoff.sh` on M5 Max | ⏳ |
| **Sat 8am** | LoRA training done, validation renders start | ⏳ |
| **Sat 2pm** | Catalog render done, QC summary available | ⏳ |
| **Sat 4pm** | Update PAPER_OUTLINE.md with measured numbers; ship v3.0 release tag | ⏳ |
| **Sat 6pm** | Draft arXiv preprint sections 5.1-5.3 with concrete numbers | ⏳ |
| **Sun (optional)** | Pahari LoRA training overnight Sat→Sun (if energy permits) | ⏳ |
| **Following week** | Polish paper sections 1-8; submit to arXiv | ⏳ |
| **August 2026** | NeurIPS Creative AI workshop submission | ⏳ |

---

## Numbers we'll commit to once measured

Reviewer-grade specificity in the abstract is what separates this from a vibes paper. Replace these `TBD`s with measured numbers post-Saturday:

| Placeholder in abstract | Measurement to do | Where the number comes from |
|---|---|---|
| "Catalog of *N* species" | 87 (or 100 if Batch C lands) | `len(animals)` in animals.json |
| "*T* canonical traditions" | 5 supported + 1 prompt-only Warli + 1 prompt-only Mughal-miniature if added | `_IC_TRADITION` enum |
| "*X*% wall-clock reduction" | M5 throughput on new measurement vs. baseline | `06-render-*.log` total time vs. naïve baseline (1 sequential mflux per render) |
| "Gold corpus at F1 *0.62*" | Already measured; reconfirm post-LoRA-v3 | `madhubani_qc.py` + LOOCV |
| "*N* tradition exclusions in scope audit" | 7 explicitly excluded traditions | Section 4.3 |

---

## What this document is not

- **Not a peer-reviewed paper draft.** It's the outline. The full LaTeX submission is downstream.
- **Not a marketing doc.** It states limitations more aggressively than contributions.
- **Not a roadmap.** The roadmap lives in `docs/ROADMAP.md`. This is the paper-track artifact only.
- **Not final.** Sections, figures, and numbers will change as Saturday's experiments produce real data.

---

**Last revised:** 2026-05-22
**Status:** Draft pre-experiment
**Author:** rohanramekar17@gmail.com (single-author preprint; co-author invitation to be issued post-arXiv-posting)
