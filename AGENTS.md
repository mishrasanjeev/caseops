# CaseOps agent instructions

## User-approved spreadsheet fallback

For standalone spreadsheet creation or editing in this repository, prefer the
configured `@oai/artifact-tool` runtime whenever it is available. If that
runtime or `load_workspace_dependencies` is unavailable, the user explicitly
approved `openpyxl` as the fallback on 17 July 2026. Continue to apply the
spreadsheet skill's formatting, formula, inspection, and visual-verification
requirements when using the fallback.
