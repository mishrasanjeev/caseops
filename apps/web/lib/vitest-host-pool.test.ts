// @vitest-environment node
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

import { resolve as resolveVitestPath } from "pathe";

import { describe, expect, test } from "vitest";
import { ForksPoolWorker, type PoolOptions } from "vitest/node";

import { hostTrustedForks, sameHostForkFileIdentity, selectHostForkArguments } from "./vitest-host-pool";

const root = path.dirname(createRequire(import.meta.url).resolve("vitest/package.json"));
const warning = path.join(root, "suppress-warnings.cjs");
// The pinned Vitest resolver uses pathe, including on Windows.
const warningArgument = resolveVitestPath(root, "./suppress-warnings.cjs");
const defaults = ["--experimental-import-meta-resolve", "--require", warningArgument,
  "--conditions", "node", "--conditions", "development"];

describe("host trusted Vitest fork constructor", () => {
  const identity = fs.statSync(warning, { bigint: true });
  test.each([
    ["Windows zero named device", "win32", 7n, 0n, identity.ino, true],
    ["Windows matching nonzero device", "win32", 7n, 7n, identity.ino, true],
    ["Windows differing nonzero device", "win32", 7n, 8n, identity.ino, false],
    ["POSIX zero named device mismatch", "linux", 7n, 0n, identity.ino, false],
    ["Windows zero device changed inode", "win32", 7n, 0n, identity.ino + 1n, false],
  ] as const)("keeps descriptor identity strict for %s", (_name, platform, openedDevice, namedDevice, inode, accepted) => {
    expect(sameHostForkFileIdentity({ ...identity, dev: openedDevice },
      { ...identity, dev: namedDevice, ino: inode }, platform)).toBe(accepted);
  });
  test("removes only the reviewed development warning preload without mutating input", () => {
    const original = [...defaults];
    expect(selectHostForkArguments(original, warning)).toEqual([
      "--experimental-import-meta-resolve", "--conditions", "node", "--conditions", "development",
    ]);
    expect(original).toEqual(defaults);
  });

  test("retains the production condition", () => {
    const original = [...defaults.slice(0, -1), "production"];
    expect(selectHostForkArguments(original, warning)).toEqual([
      "--experimental-import-meta-resolve", "--conditions", "node", "--conditions", "production",
    ]);
  });

  test("accepts the real installed Vitest path producer and rejects native Windows substitution", () => {
    const produced = resolveVitestPath(root, "./suppress-warnings.cjs");
    expect(defaults[2]).toBe(produced);
    expect(path.resolve(produced)).toBe(warning);
    expect(selectHostForkArguments(defaults, warning)).toEqual([
      defaults[0], "--conditions", "node", "--conditions", "development",
    ]);
    if (process.platform === "win32") {
      expect(produced).not.toBe(warning);
      expect(() => selectHostForkArguments([
        ...defaults.slice(0, 2), warning, ...defaults.slice(3),
      ], warning)).toThrow("VITEST_HOST_FORK_CONSTRUCTOR_REFUSED");
    }
  });

  const refused: [string, string[]][] = [
    ["missing arguments", []],
    ["missing warning preload", [defaults[0], ...defaults.slice(3)]],
    ["alternate preload path", [defaults[0], "--require", warningArgument + ".other", ...defaults.slice(3)]],
    ["equals require syntax", [defaults[0], "--require=" + warningArgument, ...defaults.slice(3)]],
    ["short require syntax", [defaults[0], "-r", warningArgument, ...defaults.slice(3)]],
    ["additional require", [...defaults, "--require", warningArgument]],
    ["additional import", [...defaults, "--import=data:text/javascript,throw 1"]],
    ["additional loader", [...defaults, "--experimental-loader=data:text/javascript,export{}"]],
    ["TLS verification override", [...defaults, "--tls-min-v1.0"]],
    ["CA store override", [...defaults, "--use-bundled-ca"]],
    ["profiling argument", ["--cpu-prof", ...defaults]],
    ["eval argument", [...defaults, "--eval", "throw 1"]],
    ["alternate runtime condition", [...defaults.slice(0, 4), "browser", ...defaults.slice(5)]],
    ["alternate mode condition", [...defaults.slice(0, -1), "unreviewed"]],
    ["reordered arguments", ["--conditions", "node", ...defaults.slice(0, 3), ...defaults.slice(5)]],
    ["duplicate warning preload", [...defaults.slice(0, 3), ...defaults]],
    ["backslash warning argument", [defaults[0], "--require",
      warningArgument.replaceAll("/", "\\"), ...defaults.slice(3)]],
    ["dot-segment warning argument", [defaults[0], "--require",
      warningArgument.replace("/suppress-warnings.cjs", "/./suppress-warnings.cjs"),
      ...defaults.slice(3)]],
    ["parent-segment warning argument", [defaults[0], "--require",
      warningArgument.replace("/suppress-warnings.cjs", "/../vitest/suppress-warnings.cjs"),
      ...defaults.slice(3)]],
    ["duplicate-separator warning argument", [defaults[0], "--require",
      warningArgument.replace("/suppress-warnings.cjs", "//suppress-warnings.cjs"),
      ...defaults.slice(3)]],
  ];
  test.each(refused)("refuses %s before a constructor can run", (_name, args) => {
    let constructors = 0;
    expect(() => {
      const selected = selectHostForkArguments(args, warning);
      constructors += 1;
      return selected;
    }).toThrow("VITEST_HOST_FORK_CONSTRUCTOR_REFUSED");
    expect(constructors).toBe(0);
  });

  test("refuses a relative warning identity", () => {
    expect(() => selectHostForkArguments(defaults, "suppress-warnings.cjs"))
      .toThrow("VITEST_HOST_FORK_CONSTRUCTOR_REFUSED");
  });

  test("delegates the same public fork class without starting an actor or mutating options", () => {
    const env = { CASEOPS_TEST_LITERAL: "kept" };
    const project = { vitest: { logger: {
      outputStream: process.stdout, errorStream: process.stderr,
    } } } as unknown as PoolOptions["project"];
    const execArgv = [...defaults];
    const options: PoolOptions = { distPath: path.join(root, "dist"), project,
      method: "run", environment: { name: "node", options: null }, execArgv, env };
    const worker = hostTrustedForks.createPoolWorker(options);
    expect(worker).toBeInstanceOf(ForksPoolWorker);
    expect(worker.name).toBe("forks");
    expect(hostTrustedForks.name).toBe("caseops-host-trusted-forks");
    expect(Reflect.get(worker, "env")).toBe(env);
    expect(Reflect.get(worker, "execArgv")).toEqual([defaults[0], ...defaults.slice(3)]);
    expect(Reflect.get(worker, "_fork")).toBeUndefined();
    expect(options.execArgv).toBe(execArgv);
    expect(execArgv).toEqual(defaults);
  });

  test("refuses a different worker distribution before reading constructor options", () => {
    const options = { distPath: root, get project() { throw new Error("CONSTRUCTOR_TOUCHED"); } };
    expect(() => hostTrustedForks.createPoolWorker(options as unknown as PoolOptions))
      .toThrow("VITEST_HOST_FORK_CONSTRUCTOR_REFUSED");
  });

  test("refuses an extra preload before accessing constructor project", () => {
    const options = { distPath: path.join(root, "dist"), execArgv: [...defaults, "--require", warningArgument],
      get project() { throw new Error("CONSTRUCTOR_TOUCHED"); } };
    expect(() => hostTrustedForks.createPoolWorker(options as unknown as PoolOptions))
      .toThrow("VITEST_HOST_FORK_CONSTRUCTOR_REFUSED");
  });
});
