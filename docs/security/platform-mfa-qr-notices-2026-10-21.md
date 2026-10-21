# Platform MFA QR Notices

The platform authenticator renderer adds stock `qrcode.react` 4.2.0 at runtime.
Its ISC declaration and bundled Project Nayuki MIT generator use the existing
base allowlist. Test-only `jsqr` 1.4.0 declares Apache-2.0 and includes its full
license in the installed package. No special admission, registry entry, base
allowlist change or modification of the hash-pinned 2026-10-12 review is needed.

## Exact Original Sources

The following official v4.2.0 sources were acquired on 2026-10-21:

- ISC: https://raw.githubusercontent.com/zpao/qrcode.react/v4.2.0/LICENSE
  SHA256 `908a4454d01d77cd6a0ae1eea0bafaa74a2e3befdbc4b7b714de2499a22351ce`.
- Bundled MIT: https://raw.githubusercontent.com/zpao/qrcode.react/v4.2.0/src/third-party/qrcodegen/LICENSE
  SHA256 `ba5a977288ff7463c51ea0cc5bf5a34372707985655c1ccc054f2a0caa3d9bff`.

The ISC download matches the installed package LICENSE exactly. The npm package
does not publish the generator's source LICENSE; retain that original under
`license-policy/upstream/qrcode.react_4.2.0/qrcodegen-LICENSE.txt`. Its public copy
is byte-identical. The installed generator identifies Project Nayuki and MIT.
Do not substitute its short SPDX header for the complete permission text.

Both full original texts and exact downloadable files are added to the existing
`/third-party-notices` component inventory. The six prior notice files remain
unchanged. Unit checks independently pin the upstream URL, retained bytes and
hash; desktop/mobile public-content journeys check visible full text and exact
download hashes without requesting the external source.

This is bounded engineering notice retention, not a legal guarantee, a fresh
production-image audit, or real-owner MFA acceptance. Existing complete release
and built-image checks still apply; earlier suite results do not cover these
changed tests.
