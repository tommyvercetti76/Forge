# Forge Receipt Schema v0.1

**Status:** Draft (2026-05-22). Locks at v1.0 by end of week-6 of the catalog buildout.

Every Forge-produced artifact (image, audio, future modalities) ships with a `receipt.json` sidecar. The receipt is the **complete record of how the artifact was produced** — model versions, prompts, seeds, LoRA stack, cultural references, QC outcomes, compute substrate, and operator identity. It is what `forge verify` checks against and what `forge reproduce` re-runs from.

## Design principles

| Principle | Why it matters |
|---|---|
| **Self-contained** | A receipt + its referenced models/LoRAs is enough to reproduce the artifact. No hidden state. |
| **Versioned** | `schema_version` is mandatory. Old receipts remain readable forever; new fields are additive. |
| **Cross-modal** | Same envelope shape for image, audio, future video. Modality-specific fields live under `payload`. |
| **Honest about what's verified** | Some claims are mechanically checkable (file hash, schema validity). Others (cultural appropriateness) explicitly are not — flagged as `requires_human_review: true`. |
| **Cryptographic at boundaries** | Hash chain over (model_hash + prompt_hash + lora_hash + seed) lets `verify` detect any post-hoc tampering. |
| **Reference-preserving** | All cultural source references retained as a list of `{title, url, license, accessed_at, sha256}` — never as freeform text. |

## Envelope (universal across modalities)

```json
{
  "schema_version": "forge.receipt.v0.1",
  "receipt_id": "rcpt-2026-05-22-c4f1a8d7",
  "generated_at": "2026-05-22T14:30:00Z",
  "modality": "image",                       // image | audio | video (future)
  "operator": {
    "identity_hash": "sha256:8a3f...",       // hash of operator declaration (privacy-preserving)
    "consent_attestation": "I affirm this artifact was produced for my own use and the source materials are licensed appropriately."
  },
  "compute": {
    "device": "Apple M5 Max",
    "device_memory_gb": 64,
    "platform": "darwin-26.0",
    "metal_slots_used": 4,
    "quantization": "q8",
    "wall_clock_seconds": 41.9
  },
  "payload": { /* modality-specific — see below */ },
  "qc": {
    "rubric_version": "madhubani.v9",
    "checks": [
      { "name": "flat-silhouette", "result": "pass", "score": 0.94 },
      { "name": "stripe-rhythm", "result": "pass", "score": 0.87 },
      { "name": "anatomy-count-legs", "result": "pass", "expected": 4, "observed": 4 }
    ],
    "publishable": true,
    "blockers_path": null,                   // path to blockers.json if any rubric check failed
    "human_review_required_for": ["cultural_appropriateness"]
  },
  "cultural_attribution": {
    "tradition": "madhubani",
    "protocol_version": "madhubani.protocol.v1",
    "references": [
      {
        "title": "Madhubani painting of peacock, ca. 1970",
        "url": "https://commons.wikimedia.org/wiki/File:Madhubani_peacock_1970.jpg",
        "license": "CC-BY-SA-4.0",
        "accessed_at": "2026-05-22T10:00:00Z",
        "sha256": "f7b3..."
      }
    ],
    "tradition_owners_acknowledgment": "This artifact draws on the Madhubani / Mithila folk-art tradition of Bihar, India. Originated and sustained by women artists of the Mithila region. Commercial use should support cultural-preservation organizations.",
    "novelty_disclosure": null              // set to a string if the subject is novel to this tradition (e.g., "Snow leopards are not traditionally depicted in Madhubani; this is a contemporary interpolation.")
  },
  "integrity": {
    "input_hash_chain": "sha256:9b3a...",   // hash of (model_hash + prompt + seed + lora_stack + image_dimensions)
    "output_artifact_sha256": "sha256:7f2e...",
    "output_artifact_path": "renders/madhubani/peacock-jim-corbett-v1.png",
    "tamper_check": "intact"
  },
  "reproducibility": {
    "deterministic_seed": 8301,
    "reproducible": true,
    "reproduce_command": "forge reproduce rcpt-2026-05-22-c4f1a8d7"
  }
}
```

## Image payload (modality: `image`)

```json
"payload": {
  "subject": {
    "species_slug": "peacock",
    "binomial": "Pavo cristatus",
    "park_slug": "ranthambore",
    "pose_slug": "signature-action",
    "body_type": "bird",
    "bird_subtype": "pheasant-grouse"        // optional refinement
  },
  "style": {
    "tradition_slug": "madhubani",
    "tradition_style_yaml_hash": "sha256:a1b2...",
    "prompt": "single centered indian peacock SIGNATURE ACTION in complete full-body side profile facing right ...",
    "negative_prompt": "photorealistic, 3D render, ...",
    "engine": "minimalist-tshirt",
    "engine_version": "1.3.0"
  },
  "model": {
    "base_model": "flux.1-dev",
    "base_model_hash": "sha256:c3d4...",
    "lora_stack": [
      { "name": "madhubani-style-v1", "scale": 1.0, "hash": "sha256:..." },
      { "name": "peacock-anatomy-v1", "scale": 0.8, "hash": "sha256:..." }
    ],
    "controlnets": [],
    "scheduler": "euler",
    "steps": 18,
    "guidance": 3.5
  },
  "output": {
    "native_resolution": [1024, 1024],
    "size_matrix_emitted": {
      "icon_64": "renders/.../peacock-jim-corbett-v1.64.png",
      "sticker_512": "renders/.../peacock-jim-corbett-v1.512.png",
      "social_1080": "renders/.../peacock-jim-corbett-v1.1080.png",
      "print_a4": "renders/.../peacock-jim-corbett-v1.a4.png",
      "print_a3": "renders/.../peacock-jim-corbett-v1.a3.png",
      "gallery_a1": "renders/.../peacock-jim-corbett-v1.a1.png",
      "vector_svg": null
    },
    "color_space": "sRGB"
  }
}
```

## Audio payload (modality: `audio`)

```json
"payload": {
  "source_text": {
    "title": "Chapter 1 of Mrityunjaya by Shivaji Sawant",
    "language": "mr",
    "text_sha256": "sha256:e5f6...",
    "word_count": 5234
  },
  "translation": {
    "applied": false,                       // true if source language differs from output
    "source_lang": "mr",
    "target_lang": "mr",
    "translator": null,
    "translator_version": null,
    "bleu_score_pair": null                 // populated if applied
  },
  "tts": {
    "base_engine": "sarvam-bulbul",
    "base_engine_version": "bulbul:v3",
    "base_speaker": "shreya",
    "voice_clone": {
      "applied": true,
      "method": "rvc",
      "model_name": "operator-voice-mr-v1",
      "model_hash": "sha256:b8a7...",
      "training_data_hash": "sha256:9f8e...",
      "training_duration_seconds": 5400,    // 90 min × 60
      "similarity_score_holdout": 0.83,
      "asmr_preset": "calm-explainer"
    }
  },
  "mastering": {
    "preset": "asmr.calm-explainer",
    "loudness_lufs": -19.0,
    "true_peak_db": -1.5,
    "lra": 11.0,
    "filter_chain_hash": "sha256:..."
  },
  "output": {
    "duration_seconds": 1845,
    "sample_rate_hz": 44100,
    "bit_depth": 16,
    "channels": 1,
    "format": "wav",
    "wav_sha256": "sha256:...",
    "subtitle_srt_path": "renders/.../chapter-1.mr.srt"
  }
}
```

## Threat model — what `forge verify` checks

| Check | Mechanism | Catches |
|---|---|---|
| **Schema validity** | JSON Schema validation against the version declared in `schema_version` | Malformed receipts |
| **Hash chain integrity** | Recompute `input_hash_chain` from declared inputs; compare to stored value | Post-hoc tampering of prompt, seed, model, or LoRA stack |
| **Output artifact integrity** | Recompute SHA-256 of the file at `output_artifact_path`; compare to `output_artifact_sha256` | Tampering of the rendered file |
| **Reference URL liveness** (optional) | HTTP HEAD on every `cultural_attribution.references[].url` | Dead provenance links |
| **Reference content integrity** (optional) | Fetch the reference; compute SHA-256; compare to declared | Citation drift / silent reference swap |
| **Determinism** | `forge reproduce <receipt-id>` re-runs the pipeline; compare output hash | Non-deterministic toolchain regression |
| **Cultural appropriateness** | ❌ **Explicitly NOT verified by code.** Marked `requires_human_review` in QC. | Honest scope — this is expert judgment, not a mechanical check |

## What `forge reproduce` does

```sh
forge reproduce rcpt-2026-05-22-c4f1a8d7
```

1. Loads the receipt
2. Verifies all model/LoRA hashes match the local copies (refuses if missing)
3. Re-runs the generation pipeline with the exact seed, prompt, LoRA stack, scheduler, steps, guidance
4. Computes SHA-256 of the new output
5. Compares to `output_artifact_sha256` in the receipt
6. Reports: **identical** (byte-for-byte), **equivalent** (perceptual hash matches), or **divergent** (something has drifted — toolchain change, hardware non-determinism, etc.)

## Versioning policy

- Schema breaking changes bump the **major** version (`v0.1 → v1.0`)
- Additive fields bump the **minor** version (`v1.0 → v1.1`)
- Old receipts remain readable by all future parsers (no field removal in minor versions)
- `forge verify` declares which schema versions it understands; refuses to verify newer versions with a clear "upgrade Forge" message rather than silently passing

## File locations

| Artifact | Receipt sidecar path |
|---|---|
| `renders/madhubani/peacock-jim-corbett-v1.png` | `renders/madhubani/peacock-jim-corbett-v1.receipt.json` |
| `audio/mrityunjaya/chapter-1.mr.master.wav` | `audio/mrityunjaya/chapter-1.mr.master.receipt.json` |

Or as a sibling file: `<artifact_basename>.receipt.json`.

## Open questions (locked before v1.0)

1. **Operator identity hashing scheme** — currently SHA-256 of a declaration string. Consider adding optional public-key signing so the receipt becomes attestable by a third party.
2. **Reference content integrity** — do we fetch and hash all Wikimedia references at receipt-emit time, or do we trust the URL + accessed_at? Current draft: hash at emit time; refuse to emit if reference is unreachable. Tradeoff: network dependency at render time.
3. **Cross-receipt provenance** — when one receipt references another (e.g., an audiobook receipt that uses a voice-clone trained from a separate training receipt), how do we chain them? Current draft: `payload.tts.voice_clone.training_receipt_id` field, pointing to the training receipt.
4. **Privacy of operator identity** — `identity_hash` is privacy-preserving by default. Public receipts could include a clear `operator_name` field if the operator wants attribution. Current draft: hash by default, plaintext opt-in.

## What this enables

| Claim | Mechanism it relies on |
|---|---|
| "Forge artifacts are reproducible from receipts" | `forge reproduce` + integrity hash chain |
| "Forge artifacts carry verifiable cultural attribution" | `cultural_attribution.references` with hashed sources + `forge verify` reference-content check |
| "Forge auditability generalizes across image and audio" | Shared envelope + modality-scoped `payload` |
| "Forge does not claim to verify cultural appropriateness mechanically" | Explicit `requires_human_review` field; never silently asserts cultural validity |
| "Forge receipts are tamper-evident" | Hash chain + output artifact hash; `verify` catches any swap |

This schema is the substrate everything else builds on. Style registry, species catalog, theme-pack CLI, `forge verify`, `forge reproduce` — all reference this contract.
