import type { MatterFileAsset } from "./contracts.ts";
import { MAX_NATIVE_UPLOAD_BYTES } from "./contracts.ts";
import {
  isPrivateImportUri,
  runPrivateFileCleanup,
} from "./private-imports.ts";
import type { PrivateImportIO } from "./private-imports.ts";
import { TempCleanupError } from "./staging.ts";

export class CameraCaptureError extends Error {
  constructor(readonly reason: "permission" | "unavailable" | "busy") {
    super(
      reason === "permission"
        ? "Camera access was not granted. You can still use Choose file, or enable camera access in device settings."
        : reason === "busy"
          ? "Finish the current photo capture first."
          : "The photo could not be captured. You can still use Choose file.",
    );
    this.name = "CameraCaptureError";
  }
}

// Both pinned native implementations generate UUID names in cache/ImagePicker.
// No external camera/library/provider URI is an owned deletion target.
export function cameraCacheRoot(cacheUri: string): string {
  try {
    if (/[\x00-\x20\x7f\\]/.test(cacheUri)) throw new Error();
    const base = new URL(`${cacheUri.replace(/\/$/, "")}/`);
    if (
      base.protocol !== "file:" ||
      base.hostname ||
      base.username ||
      base.password ||
      base.search ||
      base.hash ||
      /[\x00-\x1f\x7f\\]/.test(decodeURIComponent(base.pathname)) ||
      !/\/(?:cache|Library\/Caches)\/$/.test(base.pathname)
    )
      throw new Error();
    return new URL("ImagePicker/", base).href;
  } catch {
    throw new TempCleanupError();
  }
}

export function isCameraCopy(uri: string, rootUri: string): boolean {
  if (typeof uri !== "string" || /[\x00-\x20\x7f\\]/.test(uri)) return false;
  if (!isPrivateImportUri(uri, rootUri)) return false;
  const name = decodeURIComponent(new URL(uri).pathname).split("/").at(-1)!;
  return /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\.(?:jpg|jpeg|png)$/i.test(
    name,
  );
}

export function createCameraCache(io: PrivateImportIO) {
  const purge = (keep?: string) => {
    try {
      const files = io.listFiles();
      if (
        files.length > 128 ||
        new Set(files.map((file) => file.uri)).size !== files.length ||
        files.some((file) => !isCameraCopy(file.uri, io.rootUri)) ||
        (keep !== undefined && !isCameraCopy(keep, io.rootUri))
      )
        throw new TempCleanupError();
      runPrivateFileCleanup(
        files
          .filter((file) => file.uri !== keep)
          .map((file) => () => {
            if (file.exists) file.delete();
            if (file.exists) throw new TempCleanupError();
          }),
      );
      const remaining = io.listFiles();
      if (
        keep === undefined
          ? remaining.length !== 0
          : remaining.length !== 1 ||
            remaining[0].uri !== keep ||
            !remaining[0].exists
      )
        throw new TempCleanupError();
    } catch {
      throw new TempCleanupError();
    }
  };
  return {
    purge: () => purge(),
    retainOnly: (uri: string) => purge(uri),
    cleanupPickedFile(asset: Pick<MatterFileAsset, "uri">) {
      if (!isPrivateImportUri(asset.uri, io.rootUri)) return;
      if (!isCameraCopy(asset.uri, io.rootUri)) throw new TempCleanupError();
      try {
        const file = io.file(asset.uri);
        if (file.exists) file.delete();
        if (file.exists) throw new TempCleanupError();
      } catch {
        throw new TempCleanupError();
      }
    },
  };
}

export type CameraCaptureIO = {
  cacheRootUri: string;
  requestPermission: () => Promise<{ granted: boolean }>;
  launch: () => Promise<{
    canceled: boolean;
    assets?:
      | readonly {
          uri: string;
          type?: string | null;
          mimeType?: string;
          fileSize?: number;
        }[]
      | null;
  }>;
  inspect: (uri: string) => { exists: boolean; size: number };
  purge: () => void;
  retainOnly: (uri: string) => void;
};

export function createPhotoCapture(io: CameraCaptureIO) {
  let capturing = false;
  return async (
    current: () => boolean = () => true,
  ): Promise<MatterFileAsset | null> => {
    // Reject before cleanup/permission work: a rapid second command must not
    // purge the first command's native camera output.
    if (capturing) throw new CameraCaptureError("busy");
    capturing = true;
    try {
      io.purge();
      if (!current()) return null;
      if ((await io.requestPermission()).granted !== true)
        throw new CameraCaptureError("permission");
      if (!current()) return null;
      const result = await io.launch();
      if (!current() || result.canceled === true) {
        io.purge();
        return null;
      }
      if (
        result.canceled !== false ||
        !Array.isArray(result.assets) ||
        result.assets.length !== 1
      )
        throw new CameraCaptureError("unavailable");
      const asset = result.assets[0];
      if (
        !asset ||
        asset.type !== "image" ||
        !isCameraCopy(asset.uri, io.cacheRootUri)
      )
        throw new CameraCaptureError("unavailable");
      const extension = new URL(asset.uri).pathname
        .split(".")
        .at(-1)!
        .toLowerCase();
      const mime = extension === "png" ? "image/png" : "image/jpeg";
      const file = io.inspect(asset.uri);
      if (
        !file.exists ||
        !Number.isSafeInteger(file.size) ||
        file.size < 1 ||
        file.size > MAX_NATIVE_UPLOAD_BYTES ||
        (asset.mimeType != null && asset.mimeType !== mime) ||
        (asset.fileSize != null && asset.fileSize !== file.size)
      )
        throw new CameraCaptureError("unavailable");
      io.retainOnly(asset.uri);
      return {
        uri: asset.uri,
        name: `capture.${extension}`,
        mimeType: mime,
        size: file.size,
      };
    } catch (cause) {
      io.purge();
      if (
        cause instanceof TempCleanupError ||
        cause instanceof CameraCaptureError
      )
        throw cause;
      throw new CameraCaptureError("unavailable");
    } finally {
      capturing = false;
    }
  };
}
