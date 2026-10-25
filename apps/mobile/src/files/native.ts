import * as DocumentPicker from "expo-document-picker";
import { Directory, File, FileMode, Paths } from "expo-file-system";
import { randomUUID } from "expo-crypto";
import type { MatterFileAsset } from "./contracts";
import { nativeMultipart, stagedMultipartUri } from "./api";
import type { MultipartFactory } from "./api";
import { copyBounded, createStagingArea, pickerMimeTypes } from "./staging";

const root = () => new Directory(Paths.cache, "caseops-matter-files-v1");
export const nativeFileMultipart: MultipartFactory = (part, version, size) => {
  const file = new File(stagedMultipartUri(part.uri, root().uri));
  return nativeMultipart(part, version, () => file.bytes(), size);
};
export const nativeFileStager = createStagingArea({
  get rootUri() {
    return root().uri;
  },
  ensureRoot() {
    root().create({ intermediates: true, idempotent: true });
  },
  uniqueUri(extension) {
    return new File(root(), `${randomUUID()}.${extension}`).uri;
  },
  file(uri) {
    const file = new File(uri);
    return {
      get exists() {
        return file.exists;
      },
      get size() {
        return file.size;
      },
      async copyTo(destination, limit, check) {
        const target = new File(destination);
        target.create();
        const input = file.open(FileMode.ReadOnly);
        try {
          const output = target.open(FileMode.WriteOnly);
          try {
            await copyBounded(
              (length) => input.readBytes(length),
              (bytes) => output.writeBytes(bytes),
              limit,
              check,
            );
          } finally {
            output.close();
          }
        } finally {
          input.close();
        }
      },
      digest: () => file.digest("SHA-256"),
      delete: () => file.delete(),
    };
  },
  purgeRoot() {
    const directory = root();
    if (directory.exists) directory.delete();
  },
});

// Owned by App's picker coordinator, never by the private screen's effect.
export async function pickFile(): Promise<MatterFileAsset | null> {
  const result = await DocumentPicker.getDocumentAsync({
    type: pickerMimeTypes,
    multiple: false,
    copyToCacheDirectory: false,
    base64: false,
  });
  if (result.canceled) return null;
  if (result.assets.length !== 1) throw new Error("Select exactly one file.");
  const asset = result.assets[0];
  return {
    uri: asset.uri,
    name: asset.name,
    mimeType: asset.mimeType,
    size: asset.size,
  };
}

// Never delete provider-owned content:// or external file:// originals.
export function cleanupPickedFile(asset: MatterFileAsset): void {
  nativeFileStager.cleanupPickedFile(asset);
}
// Call at startup and sign-out; no private metadata is written to disk.
export function purgeMatterFileTemps(): void {
  nativeFileStager.purge();
}
