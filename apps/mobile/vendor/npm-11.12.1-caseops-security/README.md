# Native verification npm installer

This is a distinct local dependency rebundle of official npm 11.12.1. The npm CLI version and its own code remain unchanged. It replaces 13 dependency roots and 10 dependency-range fields, and retains the previously accepted LF node-gyp launcher. PROVENANCE.json identifies the exact inputs and changes; MEMBERS.json records all 2,149 regular archive members. The archive retains all 149 upstream and bundled notice files.

Use the pinned Node 24.15.0 runtime and `node scripts/mobile/npm-tooling.mjs` from the repository root, followed by normal npm arguments. `--npx` selects the same package’s npx CLI. `--cli-health` checks its full dependency graph; `--audit-cli` checks all installed identities, seven embedded bundle dependencies and the explicit upstream glob mapping against the current registry advisory service. Nested npm/npx calls use scoped launchers and the same Node runtime. No global npm installation is modified.

The helper opens and verifies the archive through one descriptor, transfers the kept bytes into a fresh private directory, rejects links and unsafe or duplicate paths, and verifies the complete installed inventory twice with final reconciliation. Linux and Windows CI must independently execute these checks; a Mac result does not certify those platforms.
