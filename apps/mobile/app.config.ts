import type { ExpoConfig } from "expo/config";

const config: ExpoConfig = {
  name: "CaseOps",
  slug: "caseops-mobile",
  version: "0.1.0",
  orientation: "default",
  scheme: "caseops",
  userInterfaceStyle: "light",
  ios: {
    supportsTablet: true,
    bundleIdentifier: "ai.caseops.mobile.dev",
    infoPlist: {
      ITSAppUsesNonExemptEncryption: false,
      NSCameraUsageDescription: "Attach a photograph to the matter you select.",
    },
  },
  android: {
    package: "ai.caseops.mobile.dev",
    allowBackup: false,
    permissions: [],
  },
  plugins: ["expo-secure-store", "expo-web-browser"],
  updates: { enabled: false },
  extra: {
    apiOrigin: process.env.EXPO_PUBLIC_API_ORIGIN || "https://caseops.ai",
    webOrigin:
      process.env.EXPO_PUBLIC_WEB_ORIGIN ||
      process.env.EXPO_PUBLIC_API_ORIGIN ||
      "https://caseops.ai",
    automatedTest: process.env.CASEOPS_MOBILE_AUTOMATED_TEST === "1",
    releaseSha:
      process.env.CASEOPS_MOBILE_RELEASE_SHA || "unreleased-development",
  },
};

export default config;
