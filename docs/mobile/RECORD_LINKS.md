# Native record links

The finite `/native/open/workspaces/{companyId}/…` route vocabulary opens
Matter summary/activity/files/work, a Matter's exact draft or counsel context,
and exact contract/IP docket records. IDs are canonical lowercase UUIDs. Links
contain no title, email, access token, document URL, mutation or workspace-switch
command. Query strings, fragments, encoded path components, alternate hosts,
credentials, ports, dot segments and unsupported paths are refused.

Production links use the exact HTTPS origin from the existing validated,
hash-bound public native callback policy. The generated AASA and Android intent
projections additionally cover `/native/open/`. They do not establish domain
ownership, deployed association bytes or signed-binary verification. The local
acceptance policy alone admits the explicit `caseops://open/…` route; production
does not fall back to that scheme.

The pending typed locator lives only in process memory. A cold link can wait
for normal sign-in and workspace validation. A warm link is bound to its
current user, workspace, membership, server session and local session epoch.
Claiming it requires the live foreground, compatibility and local-unlock gates.
Every retained leave callback checks live authority and the exact pending intent
again. A new principal or different workspace cannot inherit a warm intent.
Logout clears pending state. Normal unsaved-work prompts still apply; a refused
leave retains an explicit Open record link action. No mutation is replayed.

The App reads `Linking.getInitialURL()` once for its owned runtime and listens for
warm URL events. Only a validated record locator reaches the inbox; OAuth callback
state, code and query values remain with the existing PKCE handler and are never
logged or retained by the record receiver. A newer valid warm event supersedes a
delayed initial read. Logout and runtime retirement fence delayed initial results
and retained listener callbacks. A pending locator may survive a local lock, but
its live claim remains closed until compatibility, foreground and the exact
authenticated principal/session binding are confirmed.
Each warm subscription captures its own record epoch. Retirement advances that
epoch synchronously and replaces the subscription; an old captured callback is
refused even after a later sign-in, while the new listener can accept a genuinely
new event. Cleanup unsubscribes from retirement before clearing the inbox.
A delayed initial failure also cannot overwrite the current UI after a newer
valid warm event has been accepted.

The normal authenticated repositories retrieve the exact record and enforce
current tenant/parent/role/capability/ACL and lifecycle rules. A link is not an
authorization grant. Missing, moved, blocked or inaccessible records retain
normal unavailable states; labels or permissions are not fabricated from URL
input. No link automatically selects a different workspace.

The anonymous browser fallback is fixed, non-cacheable, non-referring and
non-indexed. A single hash-authorized script replaces the address with the fixed
`/native/open` path without reading its locator, query or fragment. It does not
redirect to a guessed store listing, open a custom scheme or issue a session.
Ingress/access-log handling and actual URL/history behavior remain operational
and native acceptance requirements.

Source tests do not prove iOS Universal Links or Android verified App Links.
Final production identifiers, signing identities, served association bytes,
cold/warm/locked receipt and exact authorized readback must be verified
independently on each shipping platform. The App listener and composed offline
tests establish source integration; they are not native URL dispatch or complete
device workflow evidence.
