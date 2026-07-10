import { describe, expect, it } from "vitest";

import { safePostLoginPath } from "./safe-next-path";

describe("safePostLoginPath", () => {
  it.each([
    [null, "/app"],
    [undefined, "/app"],
    ["/app", "/app"],
    ["/app/", "/app/"],
    [
      "/app/matters?status=open#recent",
      "/app/matters?status=open#recent",
    ],
  ])("maps %s to %s", (candidate, expected) => {
    expect(safePostLoginPath(candidate)).toBe(expected);
  });

  it.each([
    "",
    " /app",
    "/app ",
    "app/matters",
    "https://attacker.example/phish",
    "http://attacker.example/phish",
    "//attacker.example/phish",
    "///attacker.example/phish",
    "/\\attacker.example/phish",
    "\\attacker.example\phish",
    "javascript:alert(document.domain)",
    "data:text/html,phish",
    "/admin/users",
    "/application",
    "/app/../admin",
    "/app/%2e%2e/admin",
    "/app/%2f%2fattacker.example",
    "/app/%5c%5cattacker.example",
    "/app\n/admin",
  ])("rejects unsafe redirect %s", (candidate) => {
    expect(safePostLoginPath(candidate)).toBe("/app");
  });
});
