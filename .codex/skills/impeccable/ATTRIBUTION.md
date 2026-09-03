# Attribution — `.codex/skills/impeccable/`

The contents of this directory are a vendored copy of:

- **Project:** `impeccable`
- **Author:** Paul Bakaus
- **Source:** https://github.com/pbakaus/impeccable
- **Commit:** `main` (fetched 2026-04-17)
- **License:** Apache License 2.0 (full text in `vendor/LICENSE`)
- **Upstream attribution notice:** see `vendor/NOTICE.md`

`impeccable` itself builds on Anthropic's original `frontend-design` skill.
See `vendor/NOTICE.md` for the upstream attribution chain.

## What we changed

CaseOps-specific design direction lives in the project root at
`.impeccable.md`, which the skill is designed to consume. Divergence from an
upstream *heuristic* belongs there, not in edits to the vendored files.

One deletion from `SKILL.md`, approved by the repository owner on 2026-08-22:

- Removed the `<post-update-cleanup>` block (upstream v2.1.1). It instructed
  every invocation to run
  `.codex/skills/impeccable/scripts/cleanup-deprecated.mjs` and then delete
  itself from `SKILL.md`. Neither half applies to a vendored copy: that script
  was never vendored (there is no `scripts/` directory here), and the
  deprecated skills it names - `arrange`, `normalize` - do not exist in this
  repository either. So it could only ever fail, while prompting a detour on
  every frontend task.

  This is a packaging artefact of vendoring rather than a heuristic, which is
  why it is fixed here instead of in `.impeccable.md`: no note in a project
  doc can stop a block inside `SKILL.md` from being read and acted on.

  Re-review on the next upstream pull. If upstream ships a real `scripts/`
  directory, vendor it and restore the block.

## How it is wired

- `CODEX.md` instructs the harness to read `.impeccable.md` and this
  skill's `SKILL.md` before any frontend task.
- The skill lives at `.codex/skills/impeccable/SKILL.md` which is the
  standard Claude Code skill path.
- `.codex/skills/` is explicitly allow-listed in `.gitignore` even though
  `.claude/` itself is ignored.

## Updates

To pull a newer release, re-run the download block used to populate this
directory (see the commit that introduced it) and re-review the diff. Prefer
`.impeccable.md` for anything that is a design opinion; edit a skill file only
for a packaging artefact that cannot be addressed from outside it, and record
the edit under *What we changed* above so the next puller sees the divergence
before overwriting it.
