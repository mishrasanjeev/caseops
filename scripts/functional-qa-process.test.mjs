import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import {
  createNodeCliCommand,
  createPlaywrightCommand,
  validateTcpPort,
} from "./functional-qa-process.mjs";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const webRoot = path.join(repoRoot, "apps", "web");
const require = createRequire(import.meta.url);

test("validates and canonicalizes TCP port overrides", () => {
  assert.equal(validateTcpPort("8000", "PORT"), "8000");
  assert.equal(validateTcpPort("00080", "PORT"), "80");
  assert.equal(validateTcpPort("65535", "PORT"), "65535");

  for (const value of [
    "0",
    "65536",
    "-1",
    "1e3",
    " 3100",
    "3100 ",
    "3100 & whoami",
    "3100|whoami",
    "3100\r",
    "3100\n",
    "3100\r\n",
    "3100\n\r",
    "3100\rwhoami",
    "3100\nwhoami",
    "3100\r\nwhoami",
    "3100\n\rwhoami",
  ]) {
    assert.throws(() => validateTcpPort(value, "PORT"), /1 to 65535/);
  }
});

test("preserves config and forwarded argument boundaries without a shell", () => {
  const playwrightCliPath = require.resolve("@playwright/test/cli", {
    paths: [repoRoot],
  });
  const config = "../../config with spaces.ts & whoami\r\necho injected";
  const forwardedArgs = [
    "tests/e2e/a spec.ts",
    "--grep",
    "name with spaces & whoami | echo $HOME; $(hostname)\r\nnext line",
    "-cplaywright.app.self-hosted.config.ts",
    "--reporter=../../custom reporter.mjs",
    "--project=functional-qa-chromium",
  ];
  const command = createPlaywrightCommand(
    playwrightCliPath,
    config,
    forwardedArgs,
  );

  assert.equal(command.command, process.execPath);
  assert.equal(command.shell, false);
  assert.deepEqual(command.args, [
    playwrightCliPath,
    "test",
    "--config",
    config,
    "--reporter=line",
    ...forwardedArgs,
  ]);
});

test("runs resolved package CLIs through Node without a shell", () => {
  const nextCliPath = require.resolve("next/dist/bin/next", {
    paths: [webRoot],
  });
  const playwrightCliPath = require.resolve("@playwright/test/cli", {
    paths: [repoRoot],
  });

  for (const entrypoint of [nextCliPath, playwrightCliPath]) {
    assert.equal(path.isAbsolute(entrypoint), true);
    assert.equal(fs.existsSync(entrypoint), true);
  }

  const payload = "value with spaces & whoami | echo injected";
  const command = createNodeCliCommand(playwrightCliPath, ["test", payload]);
  assert.equal(command.command, process.execPath);
  assert.equal(command.shell, false);
  assert.deepEqual(command.args, [playwrightCliPath, "test", payload]);
});

test("passes adversarial values to a child as literal arguments", () => {
  const echoArgvPath = path.join(
    repoRoot,
    "scripts",
    "test-fixtures",
    "echo-argv.mjs",
  );
  const payloads = [
    "value with spaces & whoami | echo injected; $(hostname)",
    "line one\r\nline two\n\rline three",
    'quotes "double" and \'single\' plus %COMSPEC% and $HOME',
  ];
  const command = createNodeCliCommand(echoArgvPath, payloads);
  const result = spawnSync(command.command, command.args, {
    encoding: "utf8",
    shell: command.shell,
  });

  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), payloads);
});
