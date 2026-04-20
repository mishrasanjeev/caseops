# `.claude/skills/`

Vendored Claude Code skills that apply to CaseOps.

| Skill | Purpose | Scope |
| --- | --- | --- |
| [`impeccable/`](./impeccable/SKILL.md) | Frontend design quality — typography, OKLCH colour, spatial rhythm, motion, interaction, UX writing, and hardening guardrails against generic "AI aesthetic" output. | All frontend work. |
| [`corpus-ingest/`](./corpus-ingest/SKILL.md) | Per-bucket SC/HC ingest pipeline (ingest → Layer-2 metadata → title-chunk embed → HNSW probe → 0-5 rating) that avoids the "placeholder title poisons embeddings" failure. | Any data-ingest / vector-quality request on the authority corpus. |

## Why these live in the repo

Each skill here is vendored (full source, not a pointer) so the product's
design direction ships with the codebase. The harness loads them
automatically for every contributor — the rule lives in `CLAUDE.md` and
the project design context lives in `.impeccable.md`.

## Adding a new skill

1. Drop the skill's directory under `.claude/skills/<name>/` exactly as the
   upstream author distributes it.
2. Add an `ATTRIBUTION.md` alongside it with: source URL, commit, license,
   upstream notice, and what (if anything) we changed.
3. Update `CLAUDE.md` so future work knows to consult the skill.
4. Update this README.

## Updating

Re-download the upstream tree, compare, commit. Do not edit the skill files
in place — changes specific to CaseOps live in project-root files like
`.impeccable.md`, not inside the vendored skill.
