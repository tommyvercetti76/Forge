# Documentation Protocol

Created: 2026-05-17

This is the rule for Forge going forward:

> A feature is not done until the docs explain what it does, how it works, what
> it outputs, how to verify it, and what limits remain.

## Required Documentation Updates Per Feature

When adding or changing a feature, update these docs in the same change:

1. [FEATURES.md](FEATURES.md)
   - Add or update the feature row.
   - Include command, outputs, mechanism, and limits.
2. [ARCHITECTURE.md](ARCHITECTURE.md)
   - Update diagrams when data flow, state, or model usage changes.
3. [MECHANISMS.md](MECHANISMS.md)
   - Add cross-cutting implementation details if a new mechanism is introduced.
4. [../README.md](../README.md)
   - Add or update quickstart examples when user-facing behavior changes.
5. [../SKILL.md](../SKILL.md)
   - Add mental-model guidance when users must choose between tools.
6. Tests or smoke command notes
   - Include the command used to verify the feature.

## Feature Documentation Checklist

Every feature entry should answer:

- What problem does it solve?
- What command invokes it?
- What input does it accept?
- What files does it create?
- What mechanisms does it use?
- What local models/tools does it depend on?
- What QC or validation happens?
- What can fail?
- What is explicitly not supported yet?

## Diagram Rules

Use Mermaid diagrams for:

- New pipelines.
- New state/model flows.
- New command families.
- New artifact trees when the output structure matters.

Prefer diagrams that show real implementation stages, not aspirational future
states. Future states must be labeled as planned.

## Accuracy Rules

- Do not document planned behavior as already working.
- Do not hide cloud dependencies. If a feature is local-only, say so. If it can
  call a cloud service, mark it optional and identify the boundary.
- Do not say "matching subtitles" when timings are estimated.
- Do not imply diffusion can guarantee exact symmetry; use the procedural engine
  for exact symmetry.
- Keep command examples copy-pasteable.

## Pull-Through Rule

If a code change adds:

- a CLI flag,
- an output file,
- a model dependency,
- a new cache/state file,
- a QC rule,
- a prompt engine,
- a procedural motif,
- a fallback path,

then the docs must mention it.

## Suggested Commit Structure

For feature work:

1. Implement code.
2. Add tests/smoke render.
3. Update docs.
4. Run `python3 -m unittest tests/test_runtime.py`.
5. Include paths to changed docs in the final summary.
