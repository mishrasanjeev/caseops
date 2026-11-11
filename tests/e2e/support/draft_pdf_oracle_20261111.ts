export type DraftPdfProfile = {
  key: string;
  page_format: string;
  margin_left_mm: number; margin_right_mm: number; margin_top_mm: number; margin_bottom_mm: number;
  page_number_format: string;
};
export type DraftPdfSource = { title: string; body: string; citations: string[]; reviewRequired?: boolean };
export type DraftPdfRun = { text: string; left: number; top: number; right: number; bottom: number; contrast: number; darkPixels: number };
export type DraftPdfPageProbe = { width: number; height: number; runs: DraftPdfRun[] };

export const canonicalDraftText = (text: string) => text.normalize("NFC").replace(/\s+/gu, "");

export function assessDraftPdf(probes: DraftPdfPageProbe[], profile: DraftPdfProfile, source: DraftPdfSource) {
  const result = { sourceComplete: false, titleComplete: false, citationsComplete: false,
    pagination: probes.length > 0 && probes.length <= 200, printableBounds: true, contrast: true, paper: true };
  // These release-owned presets currently expose A4 only. Unknown paper is not
  // silently treated as A4, nor is this a claim about a court's filing rules.
  if (profile.page_format !== "A4" || ![profile.margin_left_mm, profile.margin_right_mm,
    profile.margin_top_mm, profile.margin_bottom_mm].every(value => Number.isFinite(value) && value > 0)) {
    result.paper = false;
    return result;
  }
  const texts: string[] = [];
  for (const [index, page] of probes.entries()) {
    if (!(page.width > 0 && page.height > 0) || Math.abs(page.width / page.height - 210 / 297) > 0.003) result.paper = false;
    const printable: string[] = [], footer: string[] = [];
    for (const run of page.runs) {
      if (!run.text.trim()) continue;
      const left = run.left * 210, right = run.right * 210, top = run.top * 297, bottom = run.bottom * 297;
      if (![left, right, top, bottom].every(Number.isFinite) || left < -0.8 || right > 210.8 || top < -0.8 || bottom > 297.8) result.printableBounds = false;
      if (left < profile.margin_left_mm - 0.8 || right > 210 - profile.margin_right_mm + 0.8) result.printableBounds = false;
      if (!Number.isFinite(run.contrast) || run.contrast < 4.5 || run.darkPixels < 1) result.contrast = false;
      if (top >= 297 - profile.margin_bottom_mm) { footer.push(run.text); continue; }
      printable.push(run.text);
      if (left < profile.margin_left_mm - 0.8 || right > 210 - profile.margin_right_mm + 0.8
        || top < profile.margin_top_mm - 0.8 || bottom > 297 - profile.margin_bottom_mm + 0.8) result.printableBounds = false;
    }
    const expectedFooter = profile.page_number_format.replaceAll("{n}", String(index + 1)).replaceAll("{total}", String(probes.length));
    if (canonicalDraftText(footer.join("")) !== canonicalDraftText(expectedFooter)) result.pagination = false;
    texts.push(printable.join(""));
  }
  const actual = canonicalDraftText(texts.join("")), body = canonicalDraftText(source.body);
  const notice = canonicalDraftText(`Layout preset: ${profile.key}. Court rules unverified; lawyer review required.`);
  const boundary = actual.indexOf(notice);
  let renderedBody = boundary >= 0 ? actual.slice(boundary + notice.length) : "";
  if (source.reviewRequired) {
    const review = canonicalDraftText("REVIEW REQUIRED \u2014 this draft has not been approved by a partner.");
    renderedBody = renderedBody.startsWith(review) ? renderedBody.slice(review.length) : "";
  }
  result.sourceComplete = body.length > 0 && boundary >= 0 && renderedBody.startsWith(body);
  result.titleComplete = Boolean(canonicalDraftText(source.title)) && actual.slice(0, Math.max(0, boundary)).includes(canonicalDraftText(source.title));
  let tail = result.sourceComplete ? renderedBody.slice(body.length) : "";
  const authorities = tail.indexOf(canonicalDraftText("Authorities cited"));
  result.citationsComplete = source.citations.length === 0 || authorities >= 0;
  tail = authorities >= 0 ? tail.slice(authorities + canonicalDraftText("Authorities cited").length) : "";
  for (const citation of source.citations) {
    const expected = canonicalDraftText(citation), position = expected ? tail.indexOf(expected) : -1;
    if (position < 0) result.citationsComplete = false;
    else tail = tail.slice(position + expected.length);
  }
  return result;
}

/** Executes in the page; only text/geometry and contrast measurements return. */
export function collectDraftPdfPage(): DraftPdfPageProbe {
  const root = document.querySelector("[data-testid=draft-pdf-preview] .react-pdf__Page");
  const canvas = root?.querySelector("canvas");
  if (!(canvas instanceof HTMLCanvasElement)) throw new Error("PDF canvas is absent.");
  const bounds = canvas.getBoundingClientRect();
  const pixels = canvas.getContext("2d")!.getImageData(0, 0, canvas.width, canvas.height).data;
  const linear = (raw: number, alpha: number) => {
    const value = (raw * alpha + 255 * (1 - alpha)) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  const runs: DraftPdfRun[] = [];
  for (const span of root!.querySelectorAll(".react-pdf__Page__textContent span")) {
    if (span.children.length || !span.textContent?.trim()) continue;
    const rect = span.getBoundingClientRect();
    const x0 = Math.max(0, Math.floor((rect.left - bounds.left) * canvas.width / bounds.width) - 1);
    const y0 = Math.max(0, Math.floor((rect.top - bounds.top) * canvas.height / bounds.height) - 1);
    const x1 = Math.min(canvas.width, Math.ceil((rect.right - bounds.left) * canvas.width / bounds.width) + 1);
    const y1 = Math.min(canvas.height, Math.ceil((rect.bottom - bounds.top) * canvas.height / bounds.height) + 1);
    let min = 1, max = 0, darkPixels = 0;
    for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
      const offset = (y * canvas.width + x) * 4, alpha = pixels[offset + 3] / 255;
      const luminance = 0.2126 * linear(pixels[offset], alpha) + 0.7152 * linear(pixels[offset + 1], alpha) + 0.0722 * linear(pixels[offset + 2], alpha);
      min = Math.min(min, luminance); max = Math.max(max, luminance);
      if (luminance < 0.18) darkPixels++;
    }
    runs.push({ text: span.textContent, left: (rect.left - bounds.left) / bounds.width,
      top: (rect.top - bounds.top) / bounds.height, right: (rect.right - bounds.left) / bounds.width,
      bottom: (rect.bottom - bounds.top) / bounds.height, contrast: (max + 0.05) / (min + 0.05), darkPixels });
  }
  return { width: bounds.width, height: bounds.height, runs };
}
