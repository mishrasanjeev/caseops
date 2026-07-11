import path from "node:path";

export const DEFAULT_PLAYWRIGHT_CONFIG =
  "playwright.functional-qa.config.ts";

export function validateTcpPort(value, variableName) {
  const isAsciiPort =
    typeof value === "string" &&
    value.length >= 1 &&
    value.length <= 5 &&
    [...value].every((character) => character >= "0" && character <= "9");
  if (!isAsciiPort) {
    throw new Error(`${variableName} must be an integer from 1 to 65535`);
  }

  const port = Number(value);
  if (!Number.isSafeInteger(port) || port < 1 || port > 65_535) {
    throw new Error(`${variableName} must be an integer from 1 to 65535`);
  }

  return String(port);
}

export function createNodeCliCommand(entrypoint, args) {
  if (typeof entrypoint !== "string" || !path.isAbsolute(entrypoint)) {
    throw new TypeError("The Node CLI entrypoint must be an absolute path");
  }
  if (
    !Array.isArray(args) ||
    args.some((argument) => typeof argument !== "string")
  ) {
    throw new TypeError("Node CLI arguments must be an array of strings");
  }

  // Invoke package JS entrypoints directly so Windows never reparses argv via
  // npm.cmd, npx.cmd, or cmd.exe.
  return {
    command: process.execPath,
    args: [entrypoint, ...args],
    shell: false,
  };
}

export function createPlaywrightCommand(entrypoint, config, forwardedArgs) {
  if (typeof config !== "string") {
    throw new TypeError("The Playwright config must be a string");
  }

  return createNodeCliCommand(entrypoint, [
    "test",
    "--config",
    config,
    "--reporter=line",
    ...forwardedArgs,
  ]);
}
