import * as SecureStore from "expo-secure-store";
import { randomUUID } from "expo-crypto";
import type { LocalUnlockStore } from "./local-unlock";

const POLICY = "caseops.local-biometric.policy.v1";
const MARKER = "caseops.local-biometric.marker.v1";
const policyOptions: SecureStore.SecureStoreOptions = {
  keychainService: "ai.caseops.local-biometric-policy.v1",
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};
const uuid = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
function markerOptions(installationId: string): SecureStore.SecureStoreOptions {
  if (installationId.length !== 36 || !uuid.test(installationId))
    throw new Error("Local device binding is unavailable.");
  // Never reuse the existing unauthenticated session key/service. All writes
  // in this fresh installation namespace require biometric authentication.
  return {
    keychainService: `ai.caseops.local-biometric.v1.${installationId}`,
    keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
    requireAuthentication: true,
    requireConfirmation: true,
    authenticationPrompt: "Unlock CaseOps",
  };
}
async function readPolicy(): Promise<unknown> {
  const text = await SecureStore.getItemAsync(POLICY, policyOptions);
  if (text === null) return null;
  if (text.length > 2048) throw new Error("Local lock policy is unavailable.");
  try {
    return JSON.parse(text);
  } catch {
    throw new Error("Local lock policy is unavailable.");
  }
}
export function createBiometricStore(installationId: string): LocalUnlockStore {
  const options = markerOptions(installationId);
  const clearMarker = () => SecureStore.deleteItemAsync(MARKER, options);
  return {
    readPolicy,
    writePolicy: (value) =>
      SecureStore.setItemAsync(POLICY, JSON.stringify(value), policyOptions),
    writeMarker: (value) => SecureStore.setItemAsync(MARKER, value, options),
    readMarker: () => SecureStore.getItemAsync(MARKER, options),
    clearMarker,
    async clear() {
      let failed = false;
      try {
        await clearMarker();
      } catch {
        failed = true;
      }
      try {
        await SecureStore.deleteItemAsync(POLICY, policyOptions);
      } catch {
        failed = true;
      }
      if (failed) throw new Error("Local lock removal could not be confirmed.");
    },
    supported: () => SecureStore.canUseBiometricAuthentication(),
    nonce: () => randomUUID(),
  };
}

// Only a missing installation marker invokes this reinstall purge. Legacy "1"
// migration preserves the healthy existing refresh/session credential.
export async function clearRetainedBiometricInstallation(): Promise<void> {
  const policy = await readPolicy();
  if (
    policy &&
    typeof policy === "object" &&
    "installationId" in policy &&
    typeof policy.installationId === "string" &&
    policy.installationId.length === 36 &&
    uuid.test(policy.installationId)
  ) {
    await createBiometricStore(policy.installationId).clear();
  } else {
    await SecureStore.deleteItemAsync(POLICY, policyOptions);
  }
}
