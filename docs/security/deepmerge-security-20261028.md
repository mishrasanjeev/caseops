# deepmerge compatibility backport, 2026-10-28

The resolved Expo SDK 58 tooling graph contains one `deepmerge` 4.3.1 copy,
directly required by `@expo/config` 58.0.8 with range `^4.3.1`. The fresh npm
report has seven LOW affected nodes, including dependent Expo packages, and
zero HIGH or CRITICAL findings. The HIGH threshold and exception policy are
unchanged. The original report is retained; this work must not describe it as
zero vulnerabilities.

The [reviewed advisory](https://github.com/advisories/GHSA-gcqx-w48m-w2h4)
lists no patched release. Official npm metadata still identifies 4.3.1 as the
latest release, with gitHead `5b87756a5671635679001cbac72aa42f23472c81`.
Official 4.1.2 falls outside Expo's range and reproduces the same three
prototype-poisoning shapes, so downgrading Expo or deepmerge is not a fix.

## Private compatibility change

`apps/mobile/vendor/deepmerge-4.3.1-caseops.1` retains the exact official
4.3.1 tarball and MIT licence. The original tarball is also retained outside
Git with the initial audit and reproduction evidence. Its SHA-256 is
`4003a0a348276a95543fa969f561f6b5968629acbbb59d66018dd23e7b8f1d5c`;
the full npm SHA-512 integrity and every original member digest are in
`provenance.json`.

The private backport replaces the three destination assignments across the
target and source loops with `Object.defineProperty` calls creating own,
writable, enumerable and configurable data properties. An own `__proto__`
value remains visible data instead of invoking an inherited setter. Existing
inherited-property guards and merge behavior remain in place. The source,
CJS and UMD forms receive the same change, and reversing those exact changes
reproduces the original bytes. This does not authorize using merged input as
authentication or application authority.

The package is named `deepmerge`, versioned `4.3.1-caseops.1`, and marked
private. It is not an official upstream fixed release and must not be
published. Changing a local package version or observing an omitted npm
advisory is not evidence that the upstream vulnerability was resolved.

`scripts/mobile/rebuild-deepmerge-compat.py` rebuilds the package offline from
the pinned official tarball. It executes no package scripts. Member order,
USTAR metadata, modes and gzip timestamps are fixed. The generated tarball's
SHA-256 is `e4edd663b9da1b76adc1899b4ad5285db739a9997d8aefb2dfb927b89266d77b`.
The unchanged upstream files, modified runtime files and new notice are
individually recorded in the provenance manifest.

## Verification boundaries

The source controls exercise the three original poisoning shapes, visible
own-data descriptors, nested merges, default and custom arrays, `.all`,
symbols, custom merges, null/undefined values, dates and regular expressions.
They also execute the exact installed Expo config merge function with its
ordinary update-array and plugin-property behavior. Two independent offline
rebuilds must reproduce the committed package bytes. Altered official input
must fail before creating output.

The generator verifies two complete root-present inventories of generated
files and directories, including their hashes and full metadata. Both share
the original five-second output deadline, 128 charged unique entries and
262,144 read bytes. Every generated node requires the current POSIX UID.
Portable metadata controls qualify only the known Windows named-device-zero
representation; each complete descriptor and named observation remains
independently unchanged. These controls are not real Windows ACL acceptance.

The generic mobile fingerprint excludes paths containing `/dist/`, including
the readable vendor `package/dist` copies. It does include the compatibility
tarball and provenance manifest. The complete Git/source guard and installed
tarball byte witnesses must additionally bind all three runtime forms; the
mobile fingerprint alone must never be described as covering the raw dist
copies.

The lock now selects the private archive through a direct build dependency
and an npm override. An independent clean installation verified the canonical
and hidden locks, every physical nested deepmerge copy and all twelve package
files against the retained archive. The actual Expo config consumer resolves
that runtime. The follow-up SDK 58 patch candidate also passes the current
official online SDK check using an empty owned Expo state directory with
telemetry disabled and default TLS verification.

The fresh npm reports omit the advisory for the private version. This does
not replace the retained seven-LOW original report or establish an upstream
fixed release. Complete coupled mobile/tooling gates and fresh hosted security
checks remain separate requirements. No native acceptance or shipping-artifact
claim follows from source and installed-package controls.

The compatibility archive and notices are mobile build inputs. The tracked
mobile source snapshot includes the vendor directory. The offline generator
is not imported by web units or executed by the API fixture, so it introduces
no web builder import or API runtime dependency.
