import { pdfjsAssets, pdfjsVersion } from "./generated/pdfjs-assets.ts";
import { decodeBase64 } from "./encoding.ts";
import { VIEWER_LIMITS } from "./contracts.ts";
import { rendererRuntimeSource } from "./generated/renderer-runtime-source.ts";

export function createViewerHtml(id: string): string {
  if (!/^[a-f0-9]{32}$/.test(id) || pdfjsVersion !== "6.4.299")
    throw new Error("Invalid viewer admission");
  const script = (code: string) => {
    if (/<\/script/i.test(code)) throw new Error("Unsafe renderer asset");
    return `<script type="module" nonce="${id}">${code}</script>`;
  };
  const asset = (path: string) =>
    new TextDecoder("utf-8", { fatal: true }).decode(
      decodeBase64(pdfjsAssets[path]),
    );
  const publicData = Object.fromEntries(
    Object.entries(pdfjsAssets).filter(
      ([path]) =>
        path.endsWith(".bcmap") ||
        /standard_fonts\/.*\.(?:pfb|ttf)$/.test(path),
    ),
  );
  const config = JSON.stringify({
    id,
    limits: VIEWER_LIMITS,
    assets: publicData,
  });
  return `<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-${id}'; style-src 'nonce-${id}'; connect-src 'none'; img-src blob: data:; font-src 'none'; worker-src 'none'; frame-src 'none'; object-src 'none'; media-src 'none'; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Private document</title><style nonce="${id}">
html,body{margin:0;padding:0;background:#f7f8fa;color:#272934;font:16px/1.5 system-ui;letter-spacing:0}body{padding:12px}#content{width:max-content;min-width:100%;}canvas{display:block;background:white}#page-text{white-space:pre-wrap;max-width:72ch;overflow-wrap:anywhere;margin-top:20px}#status{margin:12px}*[hidden]{display:none!important}
</style></head><body><p id="status" role="status">Opening private document</p><main id="content" hidden aria-label="Document page"><canvas id="page" role="img"></canvas><section id="page-text" aria-label="Embedded page text"></section></main>
${script(asset("legacy/build/pdf.worker.mjs"))}
${script(asset("legacy/build/pdf.mjs"))}
${script(`(${rendererRuntimeSource})(${config});`)}
</body></html>`;
}
