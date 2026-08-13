# Data view

Generated; do not edit.

| Slice | Data impact |
| --- | --- |
| IPLF-028A | Additive migration 20260813_0001 creates six unseeded company-scoped records-governance tables. It creates no retention policy, legal hold, tenant operation, export, purge, offboarding, restore, object, provider, or backup mutation.; Database constraints and triggers keep manifests/items immutable, prohibit execute mode and safe_to_execute=true, require explicit indefinite-retention references, retain hold/version evidence, and refuse a destructive downgrade once governance evidence exists. |
