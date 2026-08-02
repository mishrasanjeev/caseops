# IP implementation control plane

`PROGRAM_MANIFEST.yaml` is the only manually maintained program-status and
traceability source. It uses JSON syntax, which is a valid YAML subset, so the
validator has no dependency outside the Python standard library.

Schema version 2 records PRD-explicit and derived suffix slices, reciprocal
requirement/path allocation, stable planned or executable test references,
ownership and release boundaries, evidence metadata, milestone gates, and
child-derived status. Parent epic, milestone, requirement, journey, path, and
program status must not be edited optimistically; validation recomputes it.

The Markdown files under `generated/` are projections. Do not edit them.

From the repository root:

```powershell
python scripts/ip_program_manifest.py validate
python scripts/ip_program_manifest.py generate
```

`bootstrap` is a one-time mechanical extraction command and refuses to replace
an existing manifest unless `--force` is supplied. Do not use `--force` on an
actively maintained program manifest.

`scripts/reconcile_ip_program_manifest_phase0.py` records the reviewed 2 August
2026 Phase 0 allocation. It is retained as a reproducible audit/migration tool,
not as a completion generator: it preserves `not_started` future scope and does
not infer implementation, verification, release, or human acceptance.

Evidence belongs under `evidence/<milestone>/<slice>/`. Evidence must name the
command, environment, revision, fixture/data scope, assertions, and result.
Generated prose or an empty file is not acceptance evidence.
