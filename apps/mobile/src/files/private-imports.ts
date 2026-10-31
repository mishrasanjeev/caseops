import { TempCleanupError } from "./staging.ts";
import type { MatterFileAsset } from "./contracts.ts";

export function runPrivateFileCleanup(cleanups: readonly (() => void)[]): void {
  let failed = false;
  for (const cleanup of cleanups) {
    try { cleanup(); } catch { failed = true; }
  }
  if (failed) throw new TempCleanupError();
}

function localUrl(uri: string): URL {
  const url = new URL(uri);
  if (
    url.protocol !== "file:" || url.hostname || url.username || url.password ||
    url.search || url.hash || /[\x00-\x1f\x7f\\]/.test(decodeURIComponent(url.pathname))
  ) throw new Error("An app-private local directory is required.");
  return url;
}

// UIDocumentPicker(asCopy: true) imports into this app's temporary Inbox even
// when Expo's additional copyToCacheDirectory option is false.
export function iosImportRoot(documentUri: string, bundleId: string): string {
  if (!/^[A-Za-z0-9]+(?:\.[A-Za-z0-9-]+){2,}$/.test(bundleId))
    throw new TempCleanupError();
  try {
    const documents = localUrl(`${documentUri.replace(/\/$/, "")}/`);
    if (!documents.pathname.endsWith("/Documents/")) throw new Error();
    return new URL(`../tmp/${bundleId}-Inbox/`, documents).href;
  } catch {
    throw new TempCleanupError();
  }
}

export function iosPickerCacheRoot(cacheUri: string): string {
  try {
    const cache = localUrl(`${cacheUri.replace(/\/$/, "")}/`);
    if (!cache.pathname.endsWith("/Library/Caches/")) throw new Error();
    return new URL("DocumentPicker/", cache).href;
  } catch { throw new TempCleanupError(); }
}

// Expo's iOS picker copies while the native callback still owns the provider
// URL. That SDK/OS disk copy precedes JS size checks; bounded staging remains
// independently enforced before any upload request.
export async function pickPrivateIosCopy(
  pick: () => Promise<MatterFileAsset | null>,
  cacheRootUri: string,
  maxBytes: number,
  inspectCache: (uri: string) => { exists: boolean; size: number },
  purgeCopies: () => void,
  purgeInbox: () => void,
): Promise<MatterFileAsset | null> {
  purgeCopies();
  let asset: MatterFileAsset | null;
  try {
    asset = await pick();
    if (asset) {
      if (!isPrivateImportUri(asset.uri, cacheRootUri))
        throw new Error("The selected file could not be retained privately. Choose it again.");
      const cached = inspectCache(asset.uri);
      if (!cached.exists || !Number.isSafeInteger(cached.size) || cached.size < 1 || cached.size > maxBytes ||
        !Number.isSafeInteger(asset.size) || asset.size !== cached.size)
        throw new Error("The selected file is unavailable, incomplete or exceeds the native upload limit.");
      purgeInbox();
    }
  } catch (cause) {
    purgeCopies();
    throw cause;
  }
  if (!asset) purgeCopies();
  return asset;
}

export function isPrivateImportUri(uri: string, rootUri: string): boolean {
  try {
    const root = decodeURIComponent(localUrl(rootUri).pathname).replace(/\/$/, "");
    const path = decodeURIComponent(localUrl(uri).pathname);
    if (!path.startsWith(`${root}/`)) return false;
    const name = path.slice(root.length + 1);
    return name.length > 0 && name.length <= 255 && ![".", ".."].includes(name) && !name.includes("/");
  } catch { return false; }
}

export type PrivateImportIO = {
  rootUri: string;
  file: (uri: string) => { exists: boolean; delete: () => void };
  listFiles: () => { uri: string; exists: boolean; delete: () => void }[];
};

export function createPrivateImportArea(io: PrivateImportIO) {
  return {
    cleanupPickedFile(asset: { uri: string }) {
      if (!isPrivateImportUri(asset.uri, io.rootUri)) return;
      try {
        const file = io.file(asset.uri);
        if (file.exists) file.delete();
      } catch { throw new TempCleanupError(); }
    },
    purge() {
      try {
        const files = io.listFiles();
        if (new Set(files.map((file) => file.uri)).size !== files.length ||
          files.some((file) => !isPrivateImportUri(file.uri, io.rootUri))) throw new TempCleanupError();
        let failed = false;
        for (const file of files) {
          try { if (file.exists) file.delete(); } catch { failed = true; }
        }
        if (io.listFiles().length !== 0) failed = true;
        if (failed) throw new TempCleanupError();
      }
      catch { throw new TempCleanupError(); }
    },
  };
}
