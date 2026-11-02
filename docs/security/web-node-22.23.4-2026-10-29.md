# QG-SEC-004: Node 22.23.4 checkpoint, 2026-10-29

Status: Partially implemented. This security replacement remains NO-GO for release until its remaining CI, image and complete verification gates pass. It addresses the existing C23/QG-SEC-004 trust-store control; it adds no customer journey or module.

The repository inspection found shipping and active CI defaults pinned to Node 22.14.0. The prepared candidate selects 22.23.4, requires its exact 116-root set, and retains the full upstream bundled licence. Historical 22.14 receipts, the accepted Host 24.15 executable and the 19 npm licence exceptions remain separately bound evidence.

The official archive was acquired once with BASE144 verification and the fixed no-paid marker on the actual HTTPS constructor. Redirects and retries were disabled. Its SHA-256 is c9e1dbc748b33ed2d14f42445191ecaf14c56259c7a9a26d0042c49ec2b66428. Every archive member was audited. Only four physical members were installed: the root directory, bin directory, bin/node and LICENSE. This is a selected executable test target; npm, headers and SDKs were not installed. The acquisition used 11,025 entries and 1,011,349,205 bytes within its 20,000-entry/1-GiB budget.

One actual metadata invocation passed on the selected binary. It reported Node 22.23.4, Darwin arm64, an empty compiled system-CA path and no additive trust environment. Both bundled and effective default stores contained 116 distinct roots, with zero matches for the compromised root. The root-set SHA-256 was f5c557f94fddcecbd61b66da4634ca2537f1b153cccf581170b4b25e29b084cb; the canonical bundle SHA-256 was c2929361a5be0afcf231461fa8b4b00e4454d49cfea9592c12089d8efdc8c64f. The 113,002,944-byte executable has SHA-256 2cc28a1880d0774616959f2210ee739bffa6ac695c887e8988a496a21271f6c0. Complete selected-member and source observations matched before and after, and the owned child groups closed. This probe made no HTTP request and executed no updated trust helper or npm command.

Evidence is retained under the native-end-to-end-20261028-01 cache, in web-node-security-20261029-01/source-draft-01:

- node-acquisition-01/source-handoff-concrete-unarmed-02.json: SHA-256 307cec8293e1721ccc551dbea98e6339e7e0b5c2ab9f10229018a0a8788948ae. Root retains the separate actual acquisition exit receipt.
- node22-metadata-probe-01/actual-acceptance-02.json: SHA-256 41a133a81d77e9736b40fe19b51a45fb2c64d52d28bb88ae77c9fa43423df67e.
- The original pre-admission refusal, SHA-256 711c72a7b8f023170df7bf584d6a0a7e1500027f22ce49175a56bfca737f0f89, is preserved. JavaScript JSON conversion had rounded nanosecond identity integers. A new binding was produced directly from descriptor-verified original JSON using Python exact integers. No identity comparison was rounded or relaxed.

Required before closure:

1. Join the active CI version pins, 116-root H policy and measured observer A changes. Generate canonical B/provenance and reconcile every tooling/CI source commitment. Preserve the Windows 8,191-byte option limit and prove actual Linux/Windows behavior.
2. Collect and execute all 33 expanded scoped cases: 17 trust cases, including six descriptor scenarios, and 16 notice cases, including nine full notices. Compare exact file/suite/title tuples; require zero failures, skips, cancellations and todos. Preserve the configured hostTrustedForks pool.
3. Run real default fetch/HTTPS trusted, untrusted and wrong-host controls. Send the fixed no-paid marker on both constructors. Verify one marker per trusted request and zero HTTP on TLS denial. Keep the original certificate, hostname and deadline assertions.
4. Run unchanged apps/api/tests/test_timeout_boundary_inventory.py. Include tests/fixtures/node-default-tls-probe.cjs explicitly in the isolated frontend source snapshot and preserve its canonical LF bytes.
5. Run canonical Next typegen, then full web TypeScript compilation including component tests. Bind the generated route-type inputs. Run the complete final web unit/coverage inventory; the current source inventory contains 253 unit files and must be reenumerated after writers close.
6. Reconcile public, retained-source, image and native-upload licence inventories without changing the 19 historical npm exceptions. Replay the affected deployment and CI contracts.
7. Build fresh shipping images. Verify actual Linux-musl installed dependencies and default fetch/HTTPS certificate, hostname and override behavior inside the web image. Check the latest source-bound CI failures before an expensive replacement gate.

The metadata pass does not close C23/QG-SEC-004. Android/iOS acceptance, store archives, deployment and the complete joined release remain separate requirements.
