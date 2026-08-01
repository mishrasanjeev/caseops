# IP implementation control plane

`PROGRAM_MANIFEST.yaml` is the only manually maintained program-status and
traceability source. It uses JSON syntax, which is a valid YAML subset, so the
validator has no dependency outside the Python standard library.

The Markdown files under `generated/` are projections. Do not edit them.

From the repository root:

```powershell
python scripts/ip_program_manifest.py validate
python scripts/ip_program_manifest.py generate
```

`bootstrap` is a one-time mechanical extraction command and refuses to replace
an existing manifest unless `--force` is supplied. Do not use `--force` on an
actively maintained program manifest.

Evidence belongs under `evidence/<milestone>/<slice>/`. Evidence must name the
command, environment, revision, fixture/data scope, assertions, and result.
Generated prose or an empty file is not acceptance evidence.
