import { createHash } from "node:crypto";
import { readFile, writeFile, mkdir, readdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gunzipSync } from "node:zlib";

export const VERSION = "6.4.299";
export const INTEGRITY =
  "sha512-AVl138zALtfaAPvADulE0PZThbYzCBS79nL4pOSL/6Sm/4AH5A21BD9VHt97OlCuzJuCpmeZtAtkinisF4Vb1g==";
const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const output = join(root, "apps/mobile/src/viewer/generated");
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const selected = (path) =>
  /^(LICENSE|legacy\/build\/pdf(?:\.worker)?\.mjs|cmaps\/(?:[^/]+\.bcmap|LICENSE)|standard_fonts\/(?:[^/]+\.(?:pfb|ttf)|LICENSE[^/]*)|wasm\/LICENSE[^/]*)$/.test(
    path,
  );

// Only public renderer inputs are ever written. No document bytes enter this tool.
export function unpack(archive) {
  const integrity = `sha512-${createHash("sha512").update(archive).digest("base64")}`;
  if (integrity !== INTEGRITY)
    throw new Error("PDF.js archive integrity mismatch");
  const tar = gunzipSync(archive, { maxOutputLength: 64 * 1024 * 1024 });
  const files = new Map();
  for (let offset = 0; offset + 512 <= tar.length; ) {
    const header = tar.subarray(offset, offset + 512);
    const name = header.subarray(0, 100).toString().replace(/\0.*$/, "");
    if (!name) break;
    const size = Number.parseInt(header.subarray(124, 136).toString(), 8) || 0;
    if (
      !Number.isSafeInteger(size) ||
      size < 0 ||
      offset + 512 + size > tar.length
    )
      throw new Error("Invalid public package archive");
    const path = name.replace(/^package\//, "");
    if (selected(path) || path === "package.json") {
      if (files.has(path) || ![0, 48].includes(header[156]))
        throw new Error("Invalid package entry");
      files.set(path, tar.subarray(offset + 512, offset + 512 + size));
    }
    offset += 512 + Math.ceil(size / 512) * 512;
  }
  return files;
}

async function installedFiles() {
  const require = createRequire(join(root, "apps/mobile/package.json"));
  const folder = dirname(require.resolve("pdfjs-dist/package.json"));
  const files = new Map([
    ["package.json", await readFile(join(folder, "package.json"))],
  ]);
  for (const directory of [
    "",
    "legacy/build",
    "cmaps",
    "standard_fonts",
    "wasm",
  ]) {
    for (const entry of await readdir(join(folder, directory), {
      withFileTypes: true,
    })) {
      const path = directory ? `${directory}/${entry.name}` : entry.name;
      if (entry.isFile() && selected(path))
        files.set(path, await readFile(join(folder, path)));
    }
  }
  return files;
}

export function buildAssets(files) {
  const pkg = JSON.parse(files.get("package.json")?.toString() || "{}");
  if (
    pkg.name !== "pdfjs-dist" ||
    pkg.version !== VERSION ||
    pkg.license !== "Apache-2.0"
  )
    throw new Error("Install the exact reviewed pdfjs-dist version");
  for (const [path, hash] of Object.entries({
    "legacy/build/pdf.mjs":
      "bc51f4874a66e3853189cb5d50aba4b3096afa83ed433b885d293a3d94583cdc",
    "legacy/build/pdf.worker.mjs":
      "bb422f60804477de4a0b09091d8347a916a387755ed1cbad24ccaec1d09c78bf",
    LICENSE: "0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594",
  })) {
    if (!files.has(path) || sha256(files.get(path)) !== hash)
      throw new Error(`Unreviewed public asset: ${path}`);
  }
  const manifest = [...files]
    .filter(([path]) => selected(path))
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([path, data]) => ({
      path,
      bytes: data.length,
      sha256: sha256(data),
    }));
  if (manifest.filter(({ path }) => path.endsWith(".bcmap")).length !== 168)
    throw new Error("Incomplete CMap asset closure");
  if (
    sha256(JSON.stringify(manifest)) !==
    "790549fc095c0c19713e1458b67d72aa7a9501d81f75c3103eac656183c92c15"
  )
    throw new Error("Unreviewed public asset closure");
  const assets = Object.fromEntries(
    manifest.map(({ path }) => [path, files.get(path).toString("base64")]),
  );
  return {
    "pdfjs-assets.ts": `// Generated public assets. Run scripts/mobile/prepare-viewer-assets.mjs; do not edit.\nexport const pdfjsVersion = ${JSON.stringify(VERSION)};\nexport const pdfjsAssets: Readonly<Record<string, string>> = ${JSON.stringify(assets)};\n`,
    "manifest.json": `${JSON.stringify({ package: pkg.name, version: VERSION, integrity: INTEGRITY, files: manifest }, null, 2)}\n`,
    "LICENSES.txt": manifest
      .filter(({ path }) => /LICENSE/.test(path))
      .map(
        ({ path }) =>
          `===== pdfjs-dist/${path} =====\n${files.get(path).toString()}`,
      )
      .join("\n\n"),
  };
}

export async function main(args = process.argv.slice(2)) {
  if (args.some((arg) => !["--check", "--from-registry"].includes(arg)))
    throw new Error("Unknown asset option");
  let files;
  if (args.includes("--from-registry")) {
    const response = await fetch(
      `https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-${VERSION}.tgz`,
      { redirect: "error", signal: AbortSignal.timeout(30_000) },
    );
    if (!response.ok) throw new Error("Public renderer archive unavailable");
    const archive = Buffer.from(await response.arrayBuffer());
    if (archive.length > 16 * 1024 * 1024)
      throw new Error("Public archive too large");
    files = unpack(archive);
  } else files = await installedFiles();
  const built = buildAssets(files);
  if (!args.includes("--check")) await mkdir(output, { recursive: true });
  for (const [name, content] of Object.entries(built)) {
    const path = join(output, name);
    if (args.includes("--check")) {
      if ((await readFile(path, "utf8")) !== content)
        throw new Error(`Stale public asset: ${name}`);
    } else await writeFile(path, content);
  }
  console.log(
    `PDF.js ${VERSION}: ${args.includes("--check") ? "verified" : "prepared"} ${Object.keys(built).length} deterministic public outputs`,
  );
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
)
  main().catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
