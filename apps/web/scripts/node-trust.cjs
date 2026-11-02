"use strict";

const { createHash, X509Certificate } = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { rootCertificates } = require("node:tls");

const DENIED_ROOT = "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b";
const INPUT_ROOTS_SHA256 = "f5c557f94fddcecbd61b66da4634ca2537f1b153cccf581170b4b25e29b084cb";
const BUNDLE_SHA256 = "c2929361a5be0afcf231461fa8b4b00e4454d49cfea9592c12089d8efdc8c64f";
const bundlePath = path.join(__dirname, "ca-bundle.pem");
const emptyDirectory = path.join(__dirname, "empty");
const sha256 = (value) => createHash("sha256").update(value).digest("hex");

function refuse() {
  throw new Error("CaseOps Node trust policy refused startup.");
}

function checkNodeBuild() {
  // Reject a build-time system CA override; the pinned store must be selected.
  if (process.version !== "v22.23.4" || process.config.variables.openssl_system_ca_path) refuse();
}

// v22.23.4 already removed G3. Preserve every other root in this exact upstream set.
function createBundle(roots) {
  checkNodeBuild();
  const fingerprints = roots.map((pem) => sha256(new X509Certificate(pem).raw));
  if (roots.length !== 116 || new Set(fingerprints).size !== 116
      || fingerprints.includes(DENIED_ROOT)
      || sha256([...fingerprints].sort().join("\n") + "\n") !== INPUT_ROOTS_SHA256) refuse();
  const bundle = roots.filter((_pem, index) => fingerprints[index] !== DENIED_ROOT)
    .map((pem) => pem.trim()).join("\n") + "\n";
  if (sha256(bundle) !== BUNDLE_SHA256) refuse();
  return bundle;
}

function verifyRuntime() {
  checkNodeBuild();
  for (const key of ["NODE_EXTRA_CA_CERTS", "NODE_USE_SYSTEM_CA", "NODE_TLS_REJECT_UNAUTHORIZED", "OPENSSL_CONF"]) {
    if (process.env[key]) refuse();
  }
  if (process.env.NODE_OPTIONS !== "--use-openssl-ca"
      || process.env.SSL_CERT_FILE !== bundlePath
      || process.env.SSL_CERT_DIR !== emptyDirectory
      || process.execArgv.some((arg) => arg !== "--use-openssl-ca"
        && /^--(?:no-)?(?:use-(?:bundled|openssl|system)-ca|openssl-(?:config|shared-config))(?:=|$)/.test(arg))) refuse();
  const descriptor = fs.openSync(bundlePath, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0));
  try {
    const bundle = fs.fstatSync(descriptor, { bigint: true });
    const current = fs.lstatSync(bundlePath, { bigint: true });
    const directory = fs.lstatSync(emptyDirectory);
    // Windows lstat reports dev=0, unlike fstat; its inode is still comparable.
    if (!bundle.isFile() || !current.isFile() || bundle.ino !== current.ino
        || (process.platform !== "win32" && bundle.dev !== current.dev)
        || !directory.isDirectory() || fs.readdirSync(emptyDirectory).length
        || sha256(fs.readFileSync(descriptor)) !== BUNDLE_SHA256) refuse();
  } finally {
    fs.closeSync(descriptor);
  }
}

module.exports = { createBundle, verifyRuntime };

if (require.main === module) {
  try {
    if (process.argv.length !== 3 || process.argv[2] !== "--generate") refuse();
    const bundle = createBundle(rootCertificates);
    fs.writeFileSync(bundlePath, bundle, { flag: "wx", mode: 0o444 });
    fs.mkdirSync(emptyDirectory, { mode: 0o555 });
  } catch {
    console.error("CaseOps Node trust policy generation failed.");
    process.exitCode = 1;
  }
}
