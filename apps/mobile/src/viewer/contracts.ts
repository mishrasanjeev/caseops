import type { FilesScope, MatterFile } from "../files/contracts.ts";

export const VIEWER_LIMITS = Object.freeze({
  maxBytes: 20 * 1024 * 1024,
  textBytes: 1024 * 1024,
  maxPages: 1000,
  maxCanvasPixels: 8_000_000,
  maxImagePixels: 16_000_000,
  maxTextCharacters: 500_000,
  maxPageTextCharacters: 100_000,
  leaseMs: 15_000,
  requestMs: 15_000,
  renderMs: 15_000,
  chunkBytes: 48 * 1024,
});
export type ViewerSource = Readonly<
  FilesScope & {
    attachmentId: string;
    filename: string;
    contentType: string | null;
    sizeBytes: number;
    sha256: string;
  }
>;
export type ViewerKind = "pdf" | "image" | "text" | "docx-text";
export type RequestBytes = (
  path: string,
  options: {
    signal?: AbortSignal;
    maxBytes: number;
    rangeProbe?: boolean;
  },
) => Promise<{
  bytes: Uint8Array;
  contentType: string;
  status: number;
  contentRange: string | null;
  cacheControl: string | null;
}>;
export type PurgeReason =
  | "background"
  | "logout"
  | "revoked"
  | "source-changed"
  | "closed";
export type ViewerPorts = {
  requestBytes: RequestBytes;
  // Parent must perform a fresh authorized workspace read, not echo this source.
  revalidate: (
    source: ViewerSource,
    options: { signal: AbortSignal },
  ) => Promise<ViewerSource>;
  sha256: (bytes: Uint8Array) => Promise<string>;
  requestDocxPreview?: (
    path: string,
    options: { signal: AbortSignal; maxBytes: number },
  ) => Promise<{ value: unknown; cacheControl: string | null }>;
  subscribeInvalidation: (
    listener: (reason: PurgeReason) => void,
  ) => () => void;
};
export type DocxText = { paragraphs: string[]; tableRows: string[][] };
export type ViewerContent = {
  kind: ViewerKind;
  mime: string;
  bytes: Uint8Array;
};

function identity(value: unknown): string {
  if (typeof value !== "string" || !/^[a-zA-Z0-9_-]{1,200}$/.test(value))
    throw new Error("Invalid viewer identity");
  return value;
}
export function validateSource(source: ViewerSource): ViewerSource {
  for (const key of [
    "companyId",
    "userId",
    "sessionKey",
    "matterId",
    "attachmentId",
  ] as const)
    identity(source[key]);
  if (
    !/^[a-f0-9]{64}$/.test(source.sha256) ||
    !Number.isSafeInteger(source.sizeBytes) ||
    source.sizeBytes < 1 ||
    typeof source.filename !== "string" ||
    !source.filename.trim() ||
    source.filename.length > 255 ||
    !(
      source.contentType === null ||
      (typeof source.contentType === "string" &&
        source.contentType.length <= 255)
    )
  )
    throw new Error("Invalid viewer source");
  return Object.freeze({ ...source });
}
export function attachmentViewerSource(
  scope: FilesScope,
  file: MatterFile,
): ViewerSource {
  if (file.matter_id !== scope.matterId)
    throw new Error("Wrong attachment parent");
  return validateSource({
    ...scope,
    attachmentId: file.id,
    filename: file.original_filename,
    contentType: file.content_type,
    sizeBytes: file.size_bytes,
    sha256: file.sha256_hex,
  });
}
export function sourceKey(source: ViewerSource): string {
  return JSON.stringify([
    source.companyId,
    source.userId,
    source.sessionKey,
    source.matterId,
    source.attachmentId,
    source.sha256,
    source.sizeBytes,
    source.filename,
    source.contentType,
  ]);
}
export function viewerFormat(
  source: ViewerSource,
): { kind: ViewerKind; mime: string } | null {
  const extension = source.filename.split(".").pop()?.toLowerCase();
  const formats: Record<string, { kind: ViewerKind; mime: string }> = {
    pdf: { kind: "pdf", mime: "application/pdf" },
    png: { kind: "image", mime: "image/png" },
    jpg: { kind: "image", mime: "image/jpeg" },
    jpeg: { kind: "image", mime: "image/jpeg" },
    txt: { kind: "text", mime: "text/plain" },
    docx: { kind: "docx-text", mime: "application/json" },
  };
  const format = extension ? formats[extension] : undefined;
  const expected =
    format?.kind === "docx-text"
      ? "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
      : format?.mime;
  if (
    !format ||
    (source.contentType && normalizeMime(source.contentType) !== expected)
  )
    return null;
  return format;
}
export function normalizeMime(value: string): string {
  return value.split(";", 1)[0].trim().toLowerCase();
}
export function sourcePath(source: ViewerSource): string {
  validateSource(source);
  const base = `/api/matters/${source.matterId}/attachments/${source.attachmentId}`;
  const kind = viewerFormat(source)?.kind;
  return kind === "docx-text"
    ? `${base}/preview`
    : `${base}/download${kind === "text" ? "" : "?inline=true"}`;
}
export function originalPath(source: ViewerSource): string {
  validateSource(source);
  return `/api/matters/${source.matterId}/attachments/${source.attachmentId}/download${["pdf", "image"].includes(viewerFormat(source)?.kind || "") ? "?inline=true" : ""}`;
}
export function validateBytes(
  bytes: Uint8Array,
  kind: ViewerKind,
  mime: string,
): void {
  const starts = (...values: number[]) =>
    values.every((value, i) => bytes[i] === value);
  if (
    !bytes.length ||
    bytes.length > VIEWER_LIMITS.maxBytes ||
    (kind === "pdf" && !starts(37, 80, 68, 70, 45)) ||
    (kind === "image" &&
      mime === "image/png" &&
      !starts(137, 80, 78, 71, 13, 10, 26, 10)) ||
    (kind === "image" && mime === "image/jpeg" && !starts(255, 216, 255))
  )
    throw new Error("Document bytes do not match their source type");
  if (
    ["text", "docx-text"].includes(kind) &&
    bytes.length > VIEWER_LIMITS.textBytes
  )
    throw new Error("Text preview exceeds its safe limit");
  if (kind === "image") imageDimensions(bytes, mime);
}
export function imageDimensions(
  bytes: Uint8Array,
  mime: string,
): { width: number; height: number } {
  let width = 0,
    height = 0;
  if (
    mime === "image/png" &&
    bytes.length >= 24 &&
    String.fromCharCode(...bytes.subarray(12, 16)) === "IHDR"
  ) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    width = view.getUint32(16);
    height = view.getUint32(20);
  } else if (mime === "image/jpeg") {
    for (
      let cursor = 2, segments = 0;
      cursor + 4 < bytes.length && segments < 4096;
      segments++
    ) {
      if (bytes[cursor++] !== 255) break;
      while (bytes[cursor] === 255) cursor++;
      const marker = bytes[cursor++];
      if (marker === 217 || marker === 218) break;
      const size = (bytes[cursor] << 8) | bytes[cursor + 1];
      if (size < 2 || cursor + size > bytes.length) break;
      if (
        [
          192, 193, 194, 195, 197, 198, 199, 201, 202, 203, 205, 206, 207,
        ].includes(marker) &&
        size >= 8
      ) {
        height = (bytes[cursor + 3] << 8) | bytes[cursor + 4];
        width = (bytes[cursor + 5] << 8) | bytes[cursor + 6];
        break;
      }
      cursor += size;
    }
  }
  if (
    !width ||
    !height ||
    width > 16384 ||
    height > 16384 ||
    width * height > VIEWER_LIMITS.maxImagePixels
  )
    throw new Error("Image dimensions exceed the private viewer limit");
  return { width, height };
}
export function decodeDocxText(value: unknown, source: ViewerSource): DocxText {
  if (!value || typeof value !== "object")
    throw new Error("Invalid DOCX preview");
  const row = value as Record<string, unknown>;
  if (
    row.attachment_id !== source.attachmentId ||
    row.filename !== source.filename ||
    row.content_type !==
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document" ||
    !Array.isArray(row.paragraphs) ||
    row.paragraphs.length > 5000 ||
    !Array.isArray(row.table_rows) ||
    row.table_rows.length > 5000
  )
    throw new Error("Invalid DOCX preview identity");
  let count = 0;
  const text = (input: unknown) => {
    if (
      typeof input !== "string" ||
      input.length > 500_000 ||
      (count += input.length) > VIEWER_LIMITS.maxTextCharacters
    )
      throw new Error("Preview exceeds its text limit");
    return input;
  };
  return {
    paragraphs: row.paragraphs.map(text),
    tableRows: row.table_rows.map((cells: unknown) => {
      if (!Array.isArray(cells) || cells.length > 100)
        throw new Error("Invalid preview table");
      return cells.map((cell) => {
        if (typeof cell !== "string" || cell.length > 10_000)
          throw new Error("Invalid preview cell");
        return text(cell);
      });
    }),
  };
}
