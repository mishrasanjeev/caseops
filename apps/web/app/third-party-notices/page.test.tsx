import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import sitemap from "@/app/sitemap";

import notices from "./notices.json";
import ThirdPartyNoticesPage, { metadata } from "./page";

const webRoot = process.cwd();
const repoRoot = path.resolve(webRoot, "../..");
const publicRoot = path.join(webRoot, "public/third-party-notices");
const sha256 = (bytes: Buffer) => createHash("sha256").update(bytes).digest("hex");
const allNotices = notices.components.flatMap((component) =>
  component.notices.map((notice) => ({ component, notice })),
);

describe("third-party license notices", () => {
  it("has noindex metadata and stays outside the public sitemap", () => {
    expect(metadata.title).toBe("Third-party notices");
    expect(metadata.alternates).toEqual({ canonical: "/third-party-notices" });
    expect(metadata.robots).toEqual({ index: false, follow: true, googleBot: { index: false, follow: true } });
    expect(metadata.openGraph).toMatchObject({ title: metadata.title, url: "/third-party-notices", description: metadata.description });
    expect(sitemap().some((entry) => new URL(entry.url).pathname.startsWith("/third-party-notices"))).toBe(false);
  });

  it("renders one heading, seven named components and all nine original full notices", () => {
    render(<ThirdPartyNoticesPage />);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Third-party notices");
    const article = screen.getByRole("article");
    expect(within(article).getAllByRole("heading", { level: 2 })).toHaveLength(7);
    expect(article.querySelectorAll("details")).toHaveLength(9);
    for (const { component, notice } of allNotices) {
      const section = document.getElementById(component.id)!;
      expect(section).toHaveTextContent(component.packageName);
      expect(section).toHaveTextContent(`Version ${component.version}`);
      const link = within(section).getByRole("link", { name: `Download ${component.name} ${notice.license} notice` });
      expect(link).toHaveAttribute("href", `/third-party-notices/${notice.filename}`);
      expect(link).toHaveAttribute("download", notice.filename);
      expect(link).toHaveClass("focus-visible:outline");
      const detail = Array.from(section.querySelectorAll("details")).find((element) =>
        element.querySelector("summary")!.textContent === `Read full ${notice.license} notice`,
      )!;
      expect(detail.querySelector("pre")!.textContent).toBe(notice.text);
      expect(detail.querySelector("pre")).toHaveClass("whitespace-pre-wrap");
    }
  });

  it("offers one accessible footer link without adding forms or telemetry", () => {
    render(<ThirdPartyNoticesPage />);
    const footer = screen.getByRole("contentinfo");
    const link = within(footer).getByRole("link", { name: "Third-party notices" });
    expect(link).toHaveAttribute("href", "/third-party-notices");
    expect(link).toHaveClass("focus-visible:outline");
    expect(document.querySelectorAll("form, input, textarea")).toHaveLength(0);
    expect(document.querySelectorAll('script[src*="google-analytics"], script[src*="googletagmanager"]')).toHaveLength(0);
    expect(screen.getByRole("main")).not.toHaveTextContent(/all licenses (?:approved|compliant)|production image|server image/i);
  });

  it("binds each notice to the exact package or pinned shipping runtime version", () => {
    expect(notices.components.map(({ packageName, version }) => [packageName, version])).toEqual([
      ["@fontsource/atkinson-hyperlegible", "5.2.8"],
      ["@fontsource/jetbrains-mono", "5.2.8"],
      ["@fontsource/libre-caslon-text", "5.2.7"],
      ["nodemailer", "10.2.1"],
      ["pako", "1.0.11"],
      ["qrcode.react", "4.2.0"],
      ["node", "22.23.4"],
    ]);
    for (const component of notices.components) {
      if (component.packageName === "node") {
        expect(readFileSync(path.join(webRoot, "Dockerfile"), "utf8")).toContain("FROM node:22.23.4-alpine AS trusted-base");
        continue;
      }
      const installed = JSON.parse(readFileSync(path.join(repoRoot, "node_modules", component.packageName, "package.json"), "utf8"));
      expect(installed.name).toBe(component.packageName);
      expect(installed.version).toBe(component.version);
    }
  });

  it("keeps an exact notice-file inventory and binds the parent-owned byte-preservation rule", () => {
    expect(readdirSync(publicRoot).filter((name) => name !== ".gitattributes").sort()).toEqual(allNotices.map(({ notice }) => notice.filename).sort());
    expect(readFileSync(path.join(repoRoot, ".gitattributes"), "utf8")).toContain("apps/web/public/third-party-notices/** -text");
  });

  it("independently pins the bundled QR generator to its retained exact upstream license", () => {
    const component = notices.components.find(({ packageName }) => packageName === "qrcode.react")!;
    expect(component.notices).toHaveLength(2);
    expect(component.notices.find(({ license }) => license === "ISC")).toMatchObject({
      sourceFile: "LICENSE",
      sourceUrl: "https://raw.githubusercontent.com/zpao/qrcode.react/v4.2.0/LICENSE",
      sha256: "908a4454d01d77cd6a0ae1eea0bafaa74a2e3befdbc4b7b714de2499a22351ce",
    });
    const notice = component.notices.find(({ license }) => license === "MIT")!;
    expect(notice).toMatchObject({
      sourceFile: "src/third-party/qrcodegen/LICENSE",
      sourceUrl: "https://raw.githubusercontent.com/zpao/qrcode.react/v4.2.0/src/third-party/qrcodegen/LICENSE",
      retainedSource: "license-policy/upstream/qrcode.react_4.2.0/qrcodegen-LICENSE.txt",
      filename: "qrcode.react-4.2.0-Nayuki-MIT-LICENSE.txt",
      sha256: "ba5a977288ff7463c51ea0cc5bf5a34372707985655c1ccc054f2a0caa3d9bff",
    });
    const original = readFileSync(path.join(repoRoot, "license-policy/upstream/qrcode.react_4.2.0/qrcodegen-LICENSE.txt"));
    expect(sha256(original)).toBe("ba5a977288ff7463c51ea0cc5bf5a34372707985655c1ccc054f2a0caa3d9bff");
    expect(notice.text).toBe(original.toString("utf8"));
    const bundled = readFileSync(path.join(repoRoot, "node_modules/qrcode.react/lib/esm/index.js"), "utf8");
    expect(bundled).toContain("Copyright (c) Project Nayuki.");
    expect(bundled).toContain("SPDX-License-Identifier: MIT");
    expect(readFileSync(path.join(repoRoot, ".gitattributes"), "utf8")).toContain("license-policy/upstream/** -text");
  });

  it("pins the shipping Node license to the immutable upstream source", () => {
    const component = notices.components.find(({ packageName }) => packageName === "node")!;
    expect(component.version).toBe("22.23.4");
    expect(component.notices).toHaveLength(1);
    expect(component.notices[0]).toMatchObject({
      sourceFile: "LICENSE",
      sourceUrl: "https://raw.githubusercontent.com/nodejs/node/27f213124280b4db4cd1e3dd42f6f8afd01ceff7/LICENSE",
      retainedSource: "license-policy/upstream/node_22.23.4/LICENSE",
      filename: "node-22.23.4-LICENSE.txt",
      sha256: "c738ae413cf561f174e34f6961f8ca458aae2369a73640dda6234c629b98bcc4",
    });
    const original = readFileSync(path.join(repoRoot, "license-policy/upstream/node_22.23.4/LICENSE"));
    expect(original).toHaveLength(145485);
    expect(sha256(original)).toBe("c738ae413cf561f174e34f6961f8ca458aae2369a73640dda6234c629b98bcc4");
    expect(component.notices[0].text).toBe(original.toString("utf8"));
  });

  for (const { component, notice } of allNotices) {
    it(`${component.packageName} ${notice.license} preserves original bytes, authors and full text`, () => {
      const installed = component.packageName === "node"
        ? readFileSync(path.join(repoRoot, "license-policy/upstream/node_22.23.4/LICENSE"))
        : component.packageName === "qrcode.react" && notice.license === "MIT"
        ? readFileSync(path.join(repoRoot, "license-policy/upstream/qrcode.react_4.2.0/qrcodegen-LICENSE.txt"))
        : readFileSync(path.join(repoRoot, "node_modules", component.packageName, notice.sourceFile));
      let original = installed;
      if (notice.license === "Zlib") {
        const start = installed.indexOf(Buffer.from("// (C)"));
        expect(start).toBeGreaterThan(0);
        let end = start;
        while (installed.subarray(end, end + 2).equals(Buffer.from("//"))) {
          const newline = installed.indexOf(10, end);
          expect(newline).toBeGreaterThan(end);
          end = newline + 1;
        }
        original = installed.subarray(start, end);
        expect(original.toString()).toContain("3. This notice may not be removed or altered from any source distribution.");
      }
      const download = readFileSync(path.join(publicRoot, notice.filename));
      expect(download.equals(original)).toBe(true);
      expect(notice.text).toBe(original.toString("utf8"));
      expect(notice.sha256).toBe(sha256(original));
      expect(sha256(download)).toBe(notice.sha256);
    });
  }
});
