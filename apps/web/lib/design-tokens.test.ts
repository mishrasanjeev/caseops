// @vitest-environment node
import { readdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

// Ram 2026-10-30 (ENH-017 evidence): the calendar's hearing and task markers
// and its today highlight used var(--color-accent), var(--color-info-500)
// and var(--color-accent-bg), none of which globals.css defined. In Tailwind
// v4 an undefined var() voids the declaration, so production painted them
// transparent while every jsdom test (which never loads CSS) passed. This
// guard fails on any colour token the source references but the theme does
// not define.

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SOURCE_DIRS = ["app", "components", "lib"];
const SOURCE_FILE = /\.(?:ts|tsx|css)$/;

function definedColorTokens(css: string): Set<string> {
  return new Set([...css.matchAll(/(--color-[a-z0-9-]+)\s*:/g)].map((match) => match[1]));
}

const themeCss = readFileSync(path.join(webRoot, "app", "globals.css"), "utf8");
// `@import "tailwindcss"` brings the default palette (red-600, amber-500...).
const tailwindTheme = readFileSync(
  createRequire(path.join(webRoot, "package.json")).resolve("tailwindcss/theme.css"),
  "utf8",
);
const defined = new Set([...definedColorTokens(themeCss), ...definedColorTokens(tailwindTheme)]);

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    if (entry.name === "node_modules" || entry.name === ".next") return [];
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    // Shipped source only: tests never load CSS, and this file holds probes.
    const shipped = !/\.(?:test|spec)\.tsx?$/.test(entry.name) && !entry.name.endsWith(".d.ts");
    return SOURCE_FILE.test(entry.name) && shipped ? [full] : [];
  });
}

const sources = SOURCE_DIRS.flatMap((dir) => sourceFiles(path.join(webRoot, dir))).map((file) => ({
  file: path.relative(webRoot, file).split(path.sep).join("/"),
  text: readFileSync(file, "utf8"),
}));

// A fallback only rescues a declaration if it is itself a colour.
const REAL_COLOUR = /^(?:#[0-9a-f]{3,8}|(?:oklch|oklab|rgb|rgba|hsl|hsla|color-mix)\(.+\)|transparent|currentcolor|white|black)$/i;

type Offender = { file: string; line: number; token: string; fallback: string | null };

function colourReferences(text: string): Array<{ index: number; token: string; fallback: string | null }> {
  return [...text.matchAll(/var\(\s*(--color-[a-z0-9-]+)\s*(?:,\s*([^)]*\)?)\s*)?\)/gi)].map((match) => ({
    index: match.index ?? 0,
    token: match[1],
    fallback: match[2]?.trim() || null,
  }));
}

function lineOf(text: string, index: number): number {
  return text.slice(0, index).split("\n").length;
}

describe("design tokens", () => {
  it("parses a theme that defines the palette the guard relies on", () => {
    // If parsing silently found nothing, every reference would look undefined
    // (or, worse, a broken parse could be hidden by an empty allow-list).
    for (const token of ["--color-ink", "--color-line", "--color-brand-700", "--color-red-600"]) {
      expect(defined.has(token), token).toBe(true);
    }
    expect(sources.length).toBeGreaterThan(100);
  });

  it("defines every var(--color-*) the web source references", () => {
    const offenders: Offender[] = [];
    let references = 0;
    for (const { file, text } of sources) {
      for (const reference of colourReferences(text)) {
        references += 1;
        if (defined.has(reference.token)) continue;
        if (reference.fallback && REAL_COLOUR.test(reference.fallback)) continue;
        offenders.push({ file, line: lineOf(text, reference.index), ...reference });
      }
    }
    expect(references).toBeGreaterThan(1000);
    expect(
      offenders.map(({ file, line, token, fallback }) => `${file}:${line} ${token}${fallback ? ` (fallback ${fallback})` : ""}`),
    ).toEqual([]);
  });

  it("defines every theme colour a Tailwind utility class names", () => {
    // `text-danger-700` silently generates no CSS when --color-danger-700 is
    // missing, which fails the same way as an undefined var().
    const utility = /(?<![\w-])(?:bg|text|border|ring|fill|stroke|outline|divide|decoration|placeholder|caret)-((?:ink|mute|line|surface|brand|accent|success|warning|warn|danger|info|primary)(?:-[a-z0-9]+)*)(?![\w-])/g;
    const offenders: string[] = [];
    for (const { file, text } of sources) {
      for (const match of text.matchAll(utility)) {
        if (!defined.has(`--color-${match[1]}`)) {
          offenders.push(`${file}:${lineOf(text, match.index ?? 0)} ${match[0]}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("names a colour that the guard would reject", () => {
    // Self-check: the matcher must see an undefined token and reject a bogus fallback.
    const probe = "bg-[var(--color-not-a-token)] text-[var(--color-also-missing,var(--x))]";
    const found = colourReferences(probe);
    expect(found.map((reference) => reference.token)).toEqual(["--color-not-a-token", "--color-also-missing"]);
    expect(found.every((reference) => !defined.has(reference.token))).toBe(true);
    expect(REAL_COLOUR.test(found[1].fallback ?? "")).toBe(false);
    expect(REAL_COLOUR.test("#a55400")).toBe(true);
  });

  it("keeps the calendar's hearing and task markers on distinct hues", () => {
    const value = (token: string) => themeCss.match(new RegExp(`${token}:\\s*([^;]+);`))?.[1].trim();
    expect(value("--color-accent")).toBe("var(--color-accent-600)");
    const hue = (oklch: string | undefined) => Number(oklch?.match(/oklch\([\d.]+\s+[\d.]+\s+([\d.]+)\)/)?.[1]);
    const hearing = hue(value("--color-accent-600"));
    const task = hue(value("--color-info-500"));
    const brand = hue(value("--color-brand-700"));
    expect(Math.abs(hearing - task)).toBeGreaterThan(90);
    // Info is a blue, but not the indigo brand.
    expect(task).toBeGreaterThanOrEqual(220);
    expect(task).toBeLessThanOrEqual(250);
    expect(Math.abs(task - brand)).toBeGreaterThanOrEqual(20);
  });
});
