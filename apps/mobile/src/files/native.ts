import * as DocumentPicker from "expo-document-picker";
import * as ImagePicker from "expo-image-picker";
import Constants from "expo-constants";
import { Platform } from "react-native";
import { Directory, File, FileMode, Paths } from "expo-file-system";
import { randomUUID } from "expo-crypto";
import type { MatterFileAsset } from "./contracts";
import { MAX_NATIVE_UPLOAD_BYTES } from "./contracts";
import { nativeMultipart, stagedMultipartUri } from "./api";
import type { MultipartFactory } from "./api";
import { copyBounded, createStagingArea, pickerMimeTypes } from "./staging";
import {
  createPrivateImportArea,
  iosImportRoot,
  iosPickerCacheRoot,
  pickPrivateIosCopy,
  runPrivateFileCleanup,
} from "./private-imports";
import {
  createNativePreparationDiagnostics,
  nativePickedDomain,
} from "./native-preparation-diagnostics";
import {
  cameraCacheRoot,
  createCameraCache,
  createPhotoCapture,
} from "./camera";

const root = () => new Directory(Paths.cache, "caseops-matter-files-v1");
const importRoot = () =>
  new Directory(
    iosImportRoot(
      Paths.document.uri,
      Constants.expoConfig?.ios?.bundleIdentifier || "",
    ),
  );
const preparationDiagnostics = createNativePreparationDiagnostics(
  Constants.expoConfig?.extra?.automatedTest === true,
  (value) => console.warn(JSON.stringify(value)),
);
function privateCopyIO(directoryRoot: () => Directory) {
  return {
    get rootUri() {
      return directoryRoot().uri;
    },
    file(uri: string) {
      const file = new File(uri);
      return {
        get exists() {
          return file.exists;
        },
        delete: () => {
          file.delete();
          preparationDiagnostics.deleted(uri);
        },
      };
    },
    listFiles() {
      const directory = directoryRoot();
      if (!directory.exists) return [];
      // Preserve each SDK-managed directory and remove only its direct files.
      return directory.list().map((entry) => {
        if (!(entry instanceof File))
          throw new Error("Unexpected private import entry.");
        const uri = entry.uri;
        return {
          uri,
          get exists() {
            return entry.exists;
          },
          delete: () => {
            entry.delete();
            preparationDiagnostics.deleted(uri);
          },
        };
      });
    },
  };
}
const privateImports = createPrivateImportArea(privateCopyIO(importRoot));
const pickerCacheRoot = () =>
  new Directory(iosPickerCacheRoot(Paths.cache.uri));
const privatePickerCopies = createPrivateImportArea(
  privateCopyIO(pickerCacheRoot),
);
const cameraRoot = () => new Directory(cameraCacheRoot(Paths.cache.uri));
const privateCameraCopies = createCameraCache(privateCopyIO(cameraRoot));

// Only this explicit command asks for camera access. Images only: no microphone
// or library permission, editing, base64, album save, pending-result recovery or
// automatic upload. exif:false suppresses JS fields, not encoded JPEG metadata.
export const capturePhoto = createPhotoCapture({
  get cacheRootUri() {
    return cameraRoot().uri;
  },
  requestPermission: () => ImagePicker.requestCameraPermissionsAsync(),
  launch: () =>
    ImagePicker.launchCameraAsync({
      mediaTypes: ["images"],
      allowsEditing: false,
      allowsMultipleSelection: false,
      cameraType: ImagePicker.CameraType.back,
      quality: 1,
      exif: false,
      base64: false,
    }),
  inspect(uri) {
    const file = new File(uri);
    return { exists: file.exists, size: file.size };
  },
  purge: () => purgeMatterFileTemps(),
  retainOnly: (uri) => privateCameraCopies.retainOnly(uri),
});
export const nativeFileMultipart: MultipartFactory = (part, version, size) => {
  const file = new File(stagedMultipartUri(part.uri, root().uri));
  return nativeMultipart(part, version, () => file.bytes(), size);
};
const nativeStagingArea = createStagingArea({
  get rootUri() {
    return root().uri;
  },
  ensureRoot() {
    preparationDiagnostics.sync("staging-directory", () =>
      root().create({ intermediates: true, idempotent: true }),
    );
  },
  uniqueUri(extension) {
    return preparationDiagnostics.sync(
      "staging-path",
      () => new File(root(), `${randomUUID()}.${extension}`).uri,
    );
  },
  file(uri) {
    const file = new File(uri);
    // Classification for fixed diagnostic enums only. createStagingArea owns
    // the independent strict URI admission; this performs no extra native IO.
    const staged = uri.includes("/caseops-matter-files-v1/");
    return {
      get exists() {
        const exists = preparationDiagnostics.sync(
          staged ? "staged-exists" : "selected-exists",
          () => file.exists,
        );
        if (!staged && !exists) preparationDiagnostics.unavailable(uri);
        return exists;
      },
      get size() {
        return preparationDiagnostics.sync(
          staged ? "staged-size" : "selected-size",
          () => file.size,
        );
      },
      async copyTo(destination, limit, check) {
        const target = new File(destination);
        preparationDiagnostics.sync("target-create", () => target.create());
        const input = preparationDiagnostics.sync("source-open", () =>
          file.open(FileMode.ReadOnly),
        );
        try {
          const output = preparationDiagnostics.sync("target-open", () =>
            target.open(FileMode.WriteOnly),
          );
          try {
            await preparationDiagnostics.async("copy-bounded", () =>
              copyBounded(
                (length) =>
                  preparationDiagnostics.async("source-read", () =>
                    input.readBytes(length),
                  ),
                (bytes) =>
                  preparationDiagnostics.async("target-write", () =>
                    output.writeBytes(bytes),
                  ),
                limit,
                check,
              ),
            );
          } finally {
            preparationDiagnostics.sync("target-close", () => output.close());
          }
        } finally {
          preparationDiagnostics.sync("source-close", () => input.close());
        }
      },
      digest: () =>
        preparationDiagnostics.async("digest", () => file.digest("SHA-256")),
      delete: () => {
        file.delete();
        preparationDiagnostics.deleted(uri);
      },
    };
  },
  purgeRoot() {
    const directory = root();
    if (directory.exists) {
      directory.delete();
      preparationDiagnostics.deletedUnder(directory.uri);
    }
  },
});
export const nativeFileStager = {
  ...nativeStagingArea,
  prepare(...args: Parameters<typeof nativeStagingArea.prepare>) {
    preparationDiagnostics.begin();
    const pending = nativeStagingArea.prepare(...args);
    void pending.catch((error: unknown) => {
      preparationDiagnostics.report(error);
    });
    return pending;
  },
};

// Owned by App's picker coordinator, never by the private screen's effect.
export async function pickFile(): Promise<MatterFileAsset | null> {
  const pick = async (): Promise<MatterFileAsset | null> => {
    const result = await DocumentPicker.getDocumentAsync({
      type: pickerMimeTypes,
      multiple: false,
      // iOS raw provider URLs may not remain readable after the callback.
      // Own and purge the SDK cache copy; Android retains its content URI.
      copyToCacheDirectory: Platform.OS === "ios",
      base64: false,
    });
    if (result.canceled) return null;
    if (!result.assets || result.assets.length !== 1)
      throw new Error("Choose one file from the system picker.");
    const asset = result.assets[0];
    if (Constants.expoConfig?.extra?.automatedTest === true) {
      preparationDiagnostics.selected(
        asset.uri,
        nativePickedDomain(asset.uri, {
          imports: Platform.OS === "ios" ? importRoot().uri : undefined,
          cache: Paths.cache.uri,
          documents: Paths.document.uri,
        }),
      );
    }
    return {
      uri: asset.uri,
      name: asset.name,
      mimeType: asset.mimeType,
      size: asset.size,
    };
  };
  if (Platform.OS === "ios")
    return pickPrivateIosCopy(
      pick,
      pickerCacheRoot().uri,
      MAX_NATIVE_UPLOAD_BYTES,
      (uri) => {
        const file = new File(uri);
        return { exists: file.exists, size: file.size };
      },
      purgeMatterFileTemps,
      () => privateImports.purge(),
    );
  purgeMatterFileTemps();
  return pick();
}

// Never delete provider-owned content:// or external file:// originals.
export function cleanupPickedFile(asset: MatterFileAsset): void {
  runPrivateFileCleanup([
    () => nativeFileStager.cleanupPickedFile(asset),
    () => {
      if (Platform.OS === "ios") privateImports.cleanupPickedFile(asset);
    },
    () => {
      if (Platform.OS === "ios") privatePickerCopies.cleanupPickedFile(asset);
    },
    () => privateCameraCopies.cleanupPickedFile(asset),
  ]);
}
// Call at startup and sign-out; no private metadata is written to disk.
export function purgeMatterFileTemps(): void {
  runPrivateFileCleanup([
    () => nativeFileStager.purge(),
    () => {
      if (Platform.OS === "ios") privateImports.purge();
    },
    () => {
      if (Platform.OS === "ios") privatePickerCopies.purge();
    },
    () => privateCameraCopies.purge(),
  ]);
}
