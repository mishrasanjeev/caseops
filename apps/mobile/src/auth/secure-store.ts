import * as SecureStore from "expo-secure-store";
import { File, FileMode, Paths } from "expo-file-system";
import { randomUUID } from "expo-crypto";
import { clearRetainedBiometricInstallation } from "./biometric-store";
import type { CredentialStore, StoredCredential } from "./types";

const KEY = "caseops.native.refresh.v1";
const options: SecureStore.SecureStoreOptions = {
  keychainService: "ai.caseops.native-session",
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

let initialization: Promise<string> | null = null;
export function initializeDeviceStore(): Promise<string> {
  initialization ??= initializeInstallation();
  return initialization;
}
async function initializeInstallation(): Promise<string> {
  try {
    return await initializeInstallationInternal();
  } catch {
    throw new Error("Local device binding is unavailable.");
  }
}
async function initializeInstallationInternal(): Promise<string> {
  const installation = new File(Paths.cache, "caseops-native-install-v1");
  // Keychain may survive reinstall. A missing app-owned marker invalidates it.
  if (!installation.exists) {
    await SecureStore.deleteItemAsync(KEY, options);
    await clearRetainedBiometricInstallation();
    installation.create({ overwrite: false });
    const id = randomUUID();
    installation.write(`2:${id}`);
    return id;
  }
  const handle = installation.open(FileMode.ReadOnly);
  let bytes: Uint8Array;
  try {
    bytes = await handle.readBytes(65);
  } finally {
    handle.close();
  }
  if (bytes.length > 64)
    throw new Error("Local device binding is unavailable.");
  let marker: string;
  try {
    marker = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    throw new Error("Local device binding is unavailable.");
  }
  if (marker === "1") {
    const id = randomUUID();
    installation.write(`2:${id}`);
    return id;
  }
  if (
    marker.length !== 38 ||
    !/^2:[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(marker)
  )
    throw new Error("Local device binding is unavailable.");
  return marker.slice(2);
}

export const credentialStore: CredentialStore = {
  async read() {
    const value = await SecureStore.getItemAsync(KEY, options);
    if (!value) return null;
    try {
      const parsed: unknown = JSON.parse(value);
      if (!parsed || typeof parsed !== "object")
        throw new Error("Invalid credential.");
      const record = parsed as StoredCredential;
      if (
        typeof record.refreshToken !== "string" ||
        !record.refreshToken ||
        typeof record.sessionId !== "string" ||
        !record.sessionId
      )
        throw new Error("Invalid credential.");
      return record;
    } catch {
      await SecureStore.deleteItemAsync(KEY, options);
      return null;
    }
  },
  async write(credential) {
    await SecureStore.setItemAsync(KEY, JSON.stringify(credential), options);
  },
  async clear() {
    await SecureStore.deleteItemAsync(KEY, options);
  },
};
