import type { ExpoConfig } from "expo/config";

const { acceptanceSettings } = require("./plugins/with-local-acceptance.cjs");
const acceptance = acceptanceSettings(process.env);

const config: ExpoConfig = {
  name: "CaseOps",
  slug: "caseops-mobile",
  version: "0.1.0",
  icon: "./assets/app-icon.png",
  orientation: "default",
  scheme: "caseops",
  userInterfaceStyle: "light",
  ios: {
    supportsTablet: true,
    bundleIdentifier: acceptance?.iosBundleIdentifier || "ai.caseops.mobile.dev",
    infoPlist: {
      ITSAppUsesNonExemptEncryption: false,
      NSCameraUsageDescription: "Attach a photograph to the matter you select.",
    },
  },
  android: {
    package: "ai.caseops.mobile.dev",
    allowBackup: false,
    permissions: [],
    adaptiveIcon: {
      foregroundImage: "./assets/app-icon-foreground.png",
      monochromeImage: "./assets/app-icon-foreground.png",
      backgroundColor: "#0b1220",
    },
  },
  plugins: [
    "expo-secure-store",
    "expo-web-browser",
    "./plugins/with-local-acceptance.cjs",
  ],
  updates: { enabled: false },
  extra: {
    apiOrigin: process.env.EXPO_PUBLIC_API_ORIGIN || "https://caseops.ai",
    webOrigin:
      process.env.EXPO_PUBLIC_WEB_ORIGIN ||
      process.env.EXPO_PUBLIC_API_ORIGIN ||
      "https://caseops.ai",
    automatedTest: acceptance
      ? true
      : process.env.CASEOPS_MOBILE_AUTOMATED_TEST === "1",
    releaseSha:
      process.env.CASEOPS_MOBILE_RELEASE_SHA || "unreleased-development",
  },
};

export default config;
