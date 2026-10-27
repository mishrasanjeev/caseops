import type { ExpoConfig } from "expo/config";

const { acceptanceSettings } = require("./plugins/with-local-acceptance.cjs");
const acceptance = acceptanceSettings(process.env);
const { readNativeLinkConfig } = require("../web/lib/native-link-config.cjs");
const {
  DISABLED_NATIVE_LINK_POLICY,
  LOCAL_NATIVE_LINK_POLICY,
} = require("../web/lib/native-link-policy.cjs");
const hasLinkConfig = !!(
  process.env.CASEOPS_NATIVE_LINK_CONFIG_FILE ||
  process.env.CASEOPS_NATIVE_LINK_CONFIG_SHA256
);
if (acceptance && hasLinkConfig)
  throw new Error("ACCEPTANCE_AND_PRODUCTION_LINK_CONFIG_CANNOT_MIX");
const links = hasLinkConfig ? readNativeLinkConfig(process.env) : null;
if (!acceptance && process.env.NODE_ENV === "production" && !links)
  throw new Error("IMMUTABLE_NATIVE_LINK_CONFIG_REQUIRED");
const { readStoreBuildSettings } = require("./plugins/store-build.cjs");
if (
  acceptance &&
  (process.env.CASEOPS_STORE_BUILD_FILE ||
    process.env.CASEOPS_STORE_BUILD_SHA256)
)
  throw new Error("ACCEPTANCE_AND_STORE_BUILD_CONFIG_CANNOT_MIX");
if (
  !links &&
  (process.env.CASEOPS_STORE_BUILD_FILE ||
    process.env.CASEOPS_STORE_BUILD_SHA256)
)
  throw new Error("STORE_BUILD_REQUIRES_NATIVE_LINK_CONFIG");
const storeBuild = links ? readStoreBuildSettings(process.env, links) : null;

const config: ExpoConfig = {
  name: "CaseOps",
  slug: "caseops-mobile",
  version: storeBuild?.version || "0.1.0",
  icon: "./assets/app-icon.png",
  orientation: "default",
  scheme: acceptance ? "caseops" : undefined,
  userInterfaceStyle: "light",
  ios: {
    supportsTablet: true,
    ...(storeBuild ? { buildNumber: storeBuild.iosBuildNumber } : {}),
    bundleIdentifier:
      acceptance?.iosBundleIdentifier ||
      links?.projections.mobile.ios.bundleIdentifier ||
      "ai.caseops.mobile.dev",
    ...(links
      ? {
          associatedDomains: links.projections.mobile.ios.associatedDomains,
          deploymentTarget: "17.4",
        }
      : {}),
    infoPlist: {
      ITSAppUsesNonExemptEncryption: false,
    },
  },
  android: {
    package:
      links?.projections.mobile.android.package || "ai.caseops.mobile.dev",
    ...(storeBuild ? { versionCode: storeBuild.androidVersionCode } : {}),
    ...(links
      ? { intentFilters: links.projections.mobile.android.intentFilters }
      : {}),
    allowBackup: false,
    permissions: ["android.permission.CAMERA"],
    blockedPermissions: [
      "android.permission.SYSTEM_ALERT_WINDOW",
      "android.permission.READ_MEDIA_IMAGES",
      "android.permission.READ_EXTERNAL_STORAGE",
      "android.permission.WRITE_EXTERNAL_STORAGE",
      "android.permission.RECORD_AUDIO",
    ],
    adaptiveIcon: {
      foregroundImage: "./assets/app-icon-foreground.png",
      monochromeImage: "./assets/app-icon-foreground.png",
      backgroundColor: "#0b1220",
    },
  },
  plugins: [
    [
      "expo-secure-store",
      {
        faceIDPermission:
          "Use Face ID to unlock CaseOps when you enable biometric screen lock.",
      },
    ],
    "expo-web-browser",
    [
      "expo-image-picker",
      {
        cameraPermission:
          "Allow CaseOps to take a photo you choose to attach to a matter.",
        photosPermission: false,
        microphonePermission: false,
      },
    ],
    "./plugins/with-local-acceptance.cjs",
  ],
  updates: { enabled: false },
  extra: {
    nativeLinkPolicy: acceptance
      ? LOCAL_NATIVE_LINK_POLICY
      : links?.projections.policy || DISABLED_NATIVE_LINK_POLICY,
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
