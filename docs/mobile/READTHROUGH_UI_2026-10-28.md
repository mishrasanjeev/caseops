# Saved recommendations and hearing packs on mobile

The Matter summary opens saved recommendations. The Work view opens the
existing pack for a named hearing. These screens use the seven additive
GET-only `/api/matter-readthrough/{matter_id}` routes; they do not generate,
approve, reject, review, finalize or execute legal work.

Recommendation metadata leads to the exact stored detail, options and recorded
decisions. Existing hearing-pack content leads to that exact pack's items.
Each collection shows one server-ordered page of at most 25 records, with explicit
previous/next controls and a bounded cursor history. A stale or unavailable read
does not become an empty success. Reload from the beginning restarts the
read; actions retained from an older page or a departed screen cannot navigate
the current frame. No HTTP operation or mutation is automatically replayed.

Decoders require the current company and exact Matter/child identity, actual
scope/lifecycle fields, the declared order/parent/page limit and unique IDs.
They preserve explicit timestamp offsets and microseconds. Signed stored ranks
and indices are retained rather than applying new-submission constraints to
legacy records. Missing optional actor, review time, next action and source
reference values remain null. An unsupported-size/legacy wrapper retains its
identity and valid siblings; an available payload must meet its wire contract.

The UI displays real updated/generated/reviewed timestamps and recorded flags.
It invents no recommendation or pack revision. Stored structured strategy and
analysis remain read-only, including any unverified flags. Recorded confidence,
citations and references are not a legal-accuracy guarantee. A stored source
reference is plain text; it is never treated as permission to open an arbitrary
URL. Canonical source resolution/audited external opening remains a separate
integration requirement. Private Matter files retain their existing authorized
viewer path.

No SDK, permission, persistent cache or external service is added. API responses
and cursor history live in process memory; the existing app foreground,
compatibility, local-unlock and session boundaries cover the screens. The
private application subtree additionally remounts when its session, membership,
role or capability set changes. Unsaved memory from a retired authority is not
represented as a durable save.

Development checks pass 30 focused source tests and complete mobile TypeScript
after exclusive installs from both unchanged lock files with the accepted
Node 24/mobile and Node 22/root runtimes. The earlier missing-root-Playwright
environment refusal and two generic test-adapter type errors are retained.
The original client refusal of valid retained lifecycle version zero is also
retained; the corrected decoder preserves zero and rejects negative versions.
These development results are not the final frozen-source gate, populated API
or native acceptance. Backend candidate `a4a7e79b` and its complete replacement
gates are tracked separately. Actual iOS/Android binaries, populated readback,
source/CA/backend identities, accessibility, device lifecycle and physical
requirements remain independent release work.
