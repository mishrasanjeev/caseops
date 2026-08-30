# Data view

Generated; do not edit.

| Slice | Data impact |
| --- | --- |
| IPLF-066B | No schema change. A bounded one-tenant rebuild can write IPLF-066A shadow-generation projections from currently active/eligible canonical Clients, Matters, indexed Matter attachments, IP dockets and indexed internal non-privileged IP documents; public authority data is excluded.; Provider batches contain at most 32 bounded source-text values from one tenant and omit tenant/record identifiers, labels, ACL/scopes and projection metadata; external provider use remains an explicit fail-closed service decision.; Bounded event processing mutates only the existing private projection/event/saved-output security records; canonical source, lifecycle, access, document and Assistant owners are unchanged. |
