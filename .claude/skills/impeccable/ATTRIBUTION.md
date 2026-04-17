# Attribution — `.claude/skills/impeccable/`

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

Nothing in the skill files themselves. CaseOps-specific design direction
lives in the project root at `.impeccable.md`, which the skill is designed
to consume. If we need to diverge from an upstream heuristic in the future,
the divergence lives in `.impeccable.md` (or a successor doc), not in edits
to the vendored files.

## How it is wired

- `CLAUDE.md` instructs the harness to read `.impeccable.md` and this
  skill's `SKILL.md` before any frontend task.
- The skill lives at `.claude/skills/impeccable/SKILL.md` which is the
  standard Claude Code skill path.
- `.claude/skills/` is explicitly allow-listed in `.gitignore` even though
  `.claude/` itself is ignored.

## Updates

To pull a newer release, re-run the download block used to populate this
directory (see the commit that introduced it) and re-review the diff. Do
not edit the skill files in place — make changes in `.impeccable.md`.
