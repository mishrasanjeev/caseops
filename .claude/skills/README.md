# `.claude/skills/`

Vendored and CaseOps-authored Claude Code skills that apply to CaseOps.

| Skill | Purpose | Scope |
| --- | --- | --- |
| [`impeccable/`](./impeccable/SKILL.md) | Frontend design quality — typography, OKLCH colour, spatial rhythm, motion, interaction, UX writing, and hardening guardrails against generic "AI aesthetic" output. | All frontend work. |
| [`bug-fixing/`](./bug-fixing/SKILL.md) | Fail-closed bug triage and regression-hardening protocol that forces explicit verdicts, adjacent-path audits, and strongest-practical verification. | Any bug fix, bug verification, reopen analysis, or review of another agent's bug-fix claim. |
| [`corpus-ingest/`](./corpus-ingest/SKILL.md) | Per-bucket SC/HC ingest pipeline (ingest → Layer-2 metadata → title-chunk embed → HNSW probe → 0-5 rating) that avoids the "placeholder title poisons embeddings" failure. | Any data-ingest / vector-quality request on the authority corpus. |

## Why these live in the repo

Each skill here is either vendored (full source, not a pointer) or authored in
this repo when CaseOps needs a permanent workflow policy. The harness loads
them automatically for every contributor — the rule lives in `CLAUDE.md` and
the project design context lives in `.impeccable.md`.

## Adding a new skill

1. Drop the skill's directory under `.claude/skills/<name>/`.
2. If the skill is vendored, add an `ATTRIBUTION.md` alongside it with: source
   URL, commit, license, upstream notice, and what (if anything) we changed.
3. If the skill is CaseOps-authored, keep the policy narrow, explicit, and
   tied to a recurring repository workflow.
4. Update `CLAUDE.md` so future work knows to consult the skill.
5. Update this README.

## Updating

Re-download vendored trees, compare, commit. Do not edit vendored skill files
in place — changes specific to CaseOps live in project-root files like
`.impeccable.md`, while repo-authored policy skills should be maintained here.
