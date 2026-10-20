"use strict";

const { createHash, X509Certificate } = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { rootCertificates } = require("node:tls");

const DENIED_ROOT = "86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b";
const INPUT_ROOTS_SHA256 = "8679e032ebe303c8fc30036873fabda30ded10de2dc72aea982a4cb2808f1456";
const BUNDLE_SHA256 = "553a980a0de1e9e7fd65bcea308db009f4e2269f08475227d6f6b04beeab2554";
const bundlePath = path.join(__dirname, "ca-bundle.pem");
const emptyDirectory = path.join(__dirname, "empty");
const sha256 = (value) => createHash("sha256").update(value).digest("hex");

function refuse() {
  throw new Error("CaseOps Node trust policy refused startup.");
}

function checkNodeBuild() {
  // v22.14 configure records a nonempty override; node.gyp otherwise uses "".
  if (process.version !== "v22.14.0" || process.config.variables.openssl_system_ca_path) refuse();
}

function createBundle(roots) {
  checkNodeBuild();
  const fingerprints = roots.map((pem) => sha256(new X509Certificate(pem).raw));
  if (roots.length !== 149 || new Set(fingerprints).size !== 149
      || fingerprints.filter((value) => value === DENIED_ROOT).length !== 1
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
  const bundle = fs.lstatSync(bundlePath);
  const directory = fs.lstatSync(emptyDirectory);
  if (!bundle.isFile() || !directory.isDirectory() || fs.readdirSync(emptyDirectory).length
      || sha256(fs.readFileSync(bundlePath)) !== BUNDLE_SHA256) refuse();
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
