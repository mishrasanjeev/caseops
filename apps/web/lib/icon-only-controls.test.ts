import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { findIconOnlyControls, findTextIconButtons } from "@/lib/icon-only-controls";

// Nov 27 workbook row 10 (Bookmarks delete icon had no tooltip or name). The
// fix is the shared IconButton / Tooltip contract; this inventory keeps every
// icon-only control in the web app on it, so a new unlabeled icon-only
// button or link fails CI instead of reaching a tester.

const webRoot = path.resolve(__dirname, "..");

function shippedTsx(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    if (entry.name === "node_modules" || entry.name === ".next") return [];
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return shippedTsx(full);
    return entry.name.endsWith(".tsx") && !/\.(test|spec)\.tsx$/.test(entry.name) ? [full] : [];
  });
}

const sources = ["app", "components"]
  .flatMap((dir) => shippedTsx(path.join(webRoot, dir)))
  .map((file) => ({
    file: path.relative(webRoot, file).split(path.sep).join("/"),
    text: readFileSync(file, "utf8"),
  }));

const audit = (text: string) => findIconOnlyControls("probe.tsx", text);

describe("icon-only control audit", () => {
  it("flags icon-only buttons, links and Radix closers with or without aria-label", () => {
    const probe = `
      import { Archive, X } from "lucide-react";
      export function Probe() {
        return <>
          <Button onClick={go}><Archive className="h-4 w-4" /></Button>
          <button aria-label="Close" title="Close"><X /></button>
          <a href="/x"><Archive /></a>
          <Link href="/x">{open ? <Archive /> : <X />}</Link>
          <DialogPrimitive.Close><X /><span className="sr-only">Close</span></DialogPrimitive.Close>
        </>;
      }`;
    expect(audit(probe).map((hit) => [hit.tag, hit.inTooltip])).toEqual([
      ["Button", false],
      ["button", false],
      ["a", false],
      ["Link", false],
      ["DialogPrimitive.Close", false],
    ]);
  });

  it("accepts visible text, IconButton and Tooltip-wrapped controls", () => {
    const probe = `
      import { Archive, RefreshCw } from "lucide-react";
      export function Probe({ label }) {
        return <>
          <Button><RefreshCw /> Refresh</Button>
          <Button>{label}</Button>
          <button><CaseSummary title="x" /></button>
          <Button>{busy ? <Spinner /> : "Save"}</Button>
          <IconButton label="Delete bookmark"><Archive /></IconButton>
          <Tooltip label="Previous"><button type="button"><Archive /></button></Tooltip>
          <DropdownMenu.Trigger asChild><IconButton label="More"><Archive /></IconButton></DropdownMenu.Trigger>
        </>;
      }`;
    expect(audit(probe).filter((hit) => !hit.inTooltip)).toEqual([]);
  });

  it("flags an IconButton that also renders visible text", () => {
    expect(
      findTextIconButtons("probe.tsx", `const x = <IconButton label="Refresh"><RefreshCw /> Refresh</IconButton>;`),
    ).toEqual([1]);
  });

  it("covers the shipped web source", () => {
    expect(sources.length).toBeGreaterThan(250);
    expect(sources.some((source) => source.file === "app/app/case-tracking/page.tsx")).toBe(true);
  });

  it("leaves no icon-only button or link without IconButton or Tooltip", () => {
    const unlabeled = sources.flatMap((source) =>
      findIconOnlyControls(source.file, source.text)
        .filter((hit) => !hit.inTooltip)
        .map((hit) => `${hit.file}:${hit.line} <${hit.tag}>`),
    );
    expect(unlabeled).toEqual([]);
  });

  it("uses IconButton only for controls without visible text", () => {
    const misused = sources.flatMap((source) =>
      findTextIconButtons(source.file, source.text).map((line) => `${source.file}:${line}`),
    );
    expect(misused).toEqual([]);
  });

  it("keeps the Bookmarks delete action on the shared primitive", () => {
    const page = sources.find((source) => source.file === "app/app/case-tracking/page.tsx");
    expect(page?.text).toMatch(/<IconButton\s+label="Delete bookmark"/);
  });
});
