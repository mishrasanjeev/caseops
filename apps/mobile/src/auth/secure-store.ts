import * as SecureStore from "expo-secure-store";
import { File, Paths } from "expo-file-system";
import type { CredentialStore, StoredCredential } from "./types";

const KEY = "caseops.native.refresh.v1";
const options: SecureStore.SecureStoreOptions = {
  keychainService: "ai.caseops.native-session",
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

export async function initializeDeviceStore(): Promise<void> {
  const installation = new File(Paths.cache, "caseops-native-install-v1");
  // Keychain may survive reinstall. A missing app-owned marker invalidates it.
  if (!installation.exists) {
    await SecureStore.deleteItemAsync(KEY, options);
    installation.create({ overwrite: false });
    installation.write("1");
  }
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
