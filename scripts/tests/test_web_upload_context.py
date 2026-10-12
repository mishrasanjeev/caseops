"""Native gcloud upload discovery; no credentials, uploads or provider calls."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = "license-policy/reviewed-packages.json"
REVIEW = "docs/security/js-license-compliance-review-2026-10-12.md"


class NativeUploadTests(unittest.TestCase):
    def setUp(self):
        storage = tempfile.TemporaryDirectory(prefix="caseops-native-upload-")
        self.addCleanup(storage.cleanup)
        self.directory = Path(storage.name)
        self.upload = self.directory / "upload"
        self.upload.mkdir()
        self.gcloud = shutil.which("gcloud")
        self.assertIsNotNone(self.gcloud, "Native SDK required; this gate must not silently skip")
        self.environment = {
            **os.environ,
            "CLOUDSDK_CONFIG": str(self.directory / "sdk-config"),
            "CLOUDSDK_CORE_DISABLE_USAGE_REPORTING": "true",
            "CLOUDSDK_COMPONENT_MANAGER_DISABLE_UPDATE_CHECK": "true",
            "CLOUDSDK_GCLOUDIGNORE_ENABLED": "true",
        }
        self.case = self.id().rsplit(".", 1)[1]
        retained = os.environ.get("CASEOPS_WEB_UPLOAD_EVIDENCE")
        self.evidence = Path(retained) / self.case if retained else None
        if self.evidence:
            self.evidence.mkdir(parents=True, exist_ok=False)
        record = json.loads((ROOT / REGISTRY).read_text(encoding="utf-8"))
        self.required = {REGISTRY, REVIEW, *(
            value["path"] for entry in record["packages"] for value in entry["materials"]
        )}
        self.assertEqual(len(self.required), 62)

    def files(self, paths):
        for relative in paths:
            target = self.upload / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("FAKE upload fixture; not a secret or licensed program.\n")

    def discover(self, directory):
        before = hashlib.sha256((directory / ".gcloudignore").read_bytes()).hexdigest()
        command = [self.gcloud, "meta", "list-files-for-upload", str(directory)]
        result = subprocess.run(
            command, env=self.environment, capture_output=True, text=True,
            encoding="utf-8", timeout=60, check=False,
        )
        if self.evidence:
            (self.evidence / "stdout.txt").write_text(result.stdout, encoding="utf-8")
            (self.evidence / "stderr.txt").write_text(result.stderr, encoding="utf-8")
            (self.evidence / "receipt.json").write_text(json.dumps({
                "argv": command, "exit_code": result.returncode,
                "gcloudignore_sha256": before,
                "required_paths": sorted(self.required),
                "scope": "Local native upload inventory only; isolated unauthenticated SDK config",
            }, indent=2), encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        after = hashlib.sha256((directory / ".gcloudignore").read_bytes()).hexdigest()
        self.assertEqual(before, after)
        self.assertLessEqual(len(result.stdout.encode("utf-8")), 1024 * 1024)
        return {line.replace("\\", "/") for line in result.stdout.splitlines()}

    def test_actual_checkout_contains_every_operator_record(self):
        present = self.discover(ROOT)
        self.assertTrue(
            self.required <= present,
            f"Missing operator upload paths: {sorted(self.required - present)}",
        )
        operator = {name for name in present if name.startswith("license-policy/")}
        required_operator = {name for name in self.required if name.startswith("license-policy/")}
        self.assertEqual(operator, required_operator)
        self.assertEqual(len(operator), 55)
        builder = {
            "package.json", "package-lock.json", "apps/web/Dockerfile", "apps/web/package.json",
            "tests/fixtures/statutes/structured-schedule-api.json",
            *(f"tests/e2e/support/{name}.ts" for name in (
                "prod-failure-diagnostics", "bounded-network-evidence",
                "prod-api-response-evidence", "cost-controls",
            )),
        }
        self.assertTrue(builder <= present, f"Missing builder inputs: {sorted(builder - present)}")

    def test_real_traversal_includes_records_and_excludes_secret_canaries(self):
        forbidden = {
            "license-policy/.env", "license-policy/unreviewed.txt",
            "license-policy/unreviewed/secret.txt", "license-policy/upstream/fake/.env",
            "license-policy/upstream/fake/.git/config", "apps/web/.env.local",
            "apps/web/.env.production", "apps/web/.env.test", "apps/web/.env.staging",
            "apps/web/node_modules/fake/package.json", "apps/web/.next/server.js",
            ".git/config", "docs/private-source.txt", "outputs/private.txt",
            "docs/security/private-source.txt", "docs/security/private/source.txt",
            "docs/marketing/private.txt",
        }
        self.files(self.required | forbidden)
        example = "apps/web/.env.local.example"
        self.files({example})
        (self.upload / ".gcloudignore").write_bytes((ROOT / ".gcloudignore").read_bytes())
        present = self.discover(self.upload)
        self.assertEqual(present, self.required | {example})

    def test_double_star_parent_pruning_is_a_positive_negative_control(self):
        self.files(self.required)
        original = (ROOT / ".gcloudignore").read_text()
        changed = original.replace("license-policy/*\n", "license-policy/**\n")
        self.assertNotEqual(
            original, changed, "Current rule must not retain the broken parent glob",
        )
        (self.upload / ".gcloudignore").write_text(changed)
        present = self.discover(self.upload)
        self.assertIn(REVIEW, present)
        public = {name for name in self.required if name.startswith("apps/web/public/")}
        self.assertTrue(public <= present)
        self.assertNotIn(REGISTRY, present)
        self.assertFalse(any(name.startswith("license-policy/") for name in present))

    def test_docker_context_retains_records_but_excludes_environment_variants(self):
        docker = shutil.which("docker")
        self.assertIsNotNone(docker, "Native Docker required; context gate must not skip")
        forbidden = {
            "apps/web/.env", "apps/web/.env.local", "apps/web/.env.production",
            "apps/web/.env.staging", "apps/web/.env.test", "apps/web/.env.production.local",
            "apps/web/node_modules/fake/package.json", "apps/web/.next/server.js",
            "license-policy/.env", "license-policy/unreviewed.txt",
            "license-policy/upstream/fake/.env", "license-policy/upstream/fake/.git/config",
            ".git/config", "docs/private-source.txt", "outputs/private.txt",
            "docs/security/private-source.txt", "docs/security/private/source.txt",
            "docs/marketing/private.txt",
        }
        example = "apps/web/.env.local.example"
        self.files(self.required | forbidden | {example})
        ignore = self.upload / ".dockerignore"
        ignore.write_bytes((ROOT / ".dockerignore").read_bytes())
        before = hashlib.sha256(ignore.read_bytes()).hexdigest()
        dockerfile = self.directory / "fixture.Dockerfile"
        dockerfile.write_text("FROM scratch\nCOPY . /context/\n", encoding="utf-8")
        archive = self.directory / "context.tar"
        command = [
            docker, "build", "--network", "none", "--file", str(dockerfile),
            "--output", f"type=tar,dest={archive}", str(self.upload),
        ]
        result = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
        )
        if self.evidence:
            (self.evidence / "stdout.txt").write_text(result.stdout, encoding="utf-8")
            (self.evidence / "stderr.txt").write_text(result.stderr, encoding="utf-8")
            (self.evidence / "receipt.json").write_text(json.dumps({
                "argv": command, "exit_code": result.returncode,
                "dockerignore_sha256": before,
                "scope": (
                    "Native scratch context export only; "
                    "no RUN, registry pull, image or container"
                ),
            }, indent=2), encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(before, hashlib.sha256(ignore.read_bytes()).hexdigest())
        self.assertLessEqual(archive.stat().st_size, 16 * 1024 * 1024)
        if self.evidence:
            shutil.copyfile(archive, self.evidence / "context.tar")
        with tarfile.open(archive) as exported:
            members = exported.getmembers()
            self.assertLessEqual(len(members), 256)
            self.assertTrue(all(member.isdir() or member.isfile() for member in members))
            present = {member.name for member in members if member.isfile()}
        self.assertEqual(present, {f"context/{name}" for name in self.required | {example}})


if __name__ == "__main__":
    unittest.main()
