import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppState, Platform, StyleSheet, Text, View } from "react-native";
import Constants from "expo-constants";
import * as Crypto from "expo-crypto";
import * as WebBrowser from "expo-web-browser";
import { fetch as expoFetch } from "expo/fetch";
import { usePreventScreenCapture } from "expo-screen-capture";
import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { MobileApplication } from "./src/application/MobileApplication";
import { SignInPanel } from "./src/components/SignInPanel";
import {
  authorizationUrl,
  authSessionCallback,
  parseCallback,
} from "./src/auth/handoff";
import { DISABLED_NATIVE_LINK_POLICY, type NativeLinkPolicy } from "../web/lib/native-link-policy.cjs";
import { NativeSession } from "./src/auth/session";
import {
  credentialStore,
  initializeDeviceStore,
} from "./src/auth/secure-store";
import type { SessionIdentity } from "./src/auth/types";
import type { PurgeReason } from "./src/viewer/contracts";
import {
  checkedOrigin,
  createExpoFetchAdapter,
  JsonTransport,
} from "./src/network/http";
import { createFilePickerCoordinator } from "./src/domain/file-picker";
import {
  cleanupPickedFile,
  pickFile,
  purgeMatterFileTemps,
} from "./src/files/native";
import { TempCleanupError } from "./src/files/staging";
import { runPrivateFileCleanup } from "./src/files/private-imports";

WebBrowser.maybeCompleteAuthSession();

export default function App() {
  usePreventScreenCapture();
  const [identity, setIdentity] = useState<SessionIdentity | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isForeground, setIsForeground] = useState(
    AppState.currentState === "active",
  );
  const foreground = useRef(isForeground);
  const loginInFlight = useRef(false);
  const alive = useRef(true);
  const viewerEvents = useMemo(() => {
    const listeners = new Set<(reason: PurgeReason) => void>();
    return {
      subscribe: (listener: (reason: PurgeReason) => void) => {
        listeners.add(listener);
        return () => {
          listeners.delete(listener);
        };
      },
      notify: (reason: PurgeReason) => {
        for (const listener of listeners) listener(reason);
      },
    };
  }, []);
  const [, setPickerRevision] = useState(0);
  const picker = useMemo(
    () =>
      createFilePickerCoordinator(pickFile, cleanupPickedFile, () => {
        if (alive.current) setPickerRevision((value) => value + 1);
      }),
    [],
  );
  const clearSelection = useCallback(() => {
    try {
      picker.clear();
    } catch {
      setError(
        "Private temporary-file cleanup could not be confirmed. Close the app and try again.",
      );
    }
  }, [picker]);
  const runtime = useMemo(() => {
    const extra = Constants.expoConfig?.extra;
    const origin = checkedOrigin(
      String(extra?.apiOrigin || "https://caseops.ai"),
      __DEV__,
    );
    const webOrigin = checkedOrigin(
      String(extra?.webOrigin || origin),
      __DEV__,
    );
    const transport = new JsonTransport(
      origin,
      __DEV__,
      extra?.automatedTest === true,
      createExpoFetchAdapter(expoFetch),
    );
    const session = new NativeSession(
      transport,
      credentialStore,
      Date.now,
      () => {
        if (alive.current) setIdentity(null);
        viewerEvents.notify("logout");
        try {
          runPrivateFileCleanup([() => picker.clear(), purgeMatterFileTemps]);
        } catch {
          if (alive.current)
            setError(
              "Private temporary-file cleanup could not be confirmed. Restart before signing in.",
            );
        }
      },
    );
    return {
      session,
      webOrigin,
      request: session.request.bind(session),
      viewer: {
        requestBytes: session.requestBytes.bind(session),
        subscribeInvalidation: viewerEvents.subscribe,
        sha256: async (bytes: Uint8Array) => {
          const digest = await Crypto.digest(
            Crypto.CryptoDigestAlgorithm.SHA256,
            bytes.slice().buffer,
          );
          return Array.from(new Uint8Array(digest), (byte) =>
            byte.toString(16).padStart(2, "0"),
          ).join("");
        },
      },
    };
  }, [picker, viewerEvents]);
  const fileState = identity
    ? picker.snapshot(identity, runtime.session.sessionKey)
    : null;

  useEffect(() => {
    alive.current = true;
    void (async () => {
      try {
        await initializeDeviceStore();
        purgeMatterFileTemps();
        const restored = await runtime.session.restore();
        if (restored) {
          const current = await runtime.session.revalidate();
          if (alive.current && foreground.current) setIdentity(current);
        }
      } catch (cause) {
        if (alive.current)
          setError(
            cause instanceof Error
              ? cause.message
              : "Sign in again to continue.",
          );
      } finally {
        if (alive.current) setBusy(false);
      }
    })();
    const listener = AppState.addEventListener("change", (state) => {
      foreground.current = state === "active";
      setIsForeground(foreground.current);
      if (state !== "active") {
        // Unmount private screens and discard their memory-only records/drafts.
        setIdentity(null);
        viewerEvents.notify("background");
        if (!picker.picking) clearSelection();
      } else if (!loginInFlight.current && runtime.session.identity) {
        setBusy(true);
        void runtime.session
          .revalidate()
          .then((current) => {
            if (alive.current && foreground.current) setIdentity(current);
          })
          .catch((cause) => {
            if (alive.current)
              setError(
                cause instanceof Error
                  ? cause.message
                  : "Reopen your workspace securely.",
              );
          })
          .finally(() => {
            if (alive.current) setBusy(false);
          });
      }
    });
    return () => {
      alive.current = false;
      listener.remove();
      picker.clear();
    };
  }, [runtime, picker, clearSelection, viewerEvents]);

  async function signIn() {
    if (loginInFlight.current || !["android", "ios"].includes(Platform.OS))
      return;
    loginInFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const nativeLinkPolicy: NativeLinkPolicy = Constants.expoConfig?.extra?.nativeLinkPolicy || DISABLED_NATIVE_LINK_POLICY;
      const callback = authSessionCallback(nativeLinkPolicy, Platform.OS, Platform.Version);
      picker.clear();
      purgeMatterFileTemps();
      const bytes = await Crypto.getRandomBytesAsync(32);
      const verifier = Array.from(bytes, (byte) =>
        byte.toString(16).padStart(2, "0"),
      ).join("");
      const challenge = (
        await Crypto.digestStringAsync(
          Crypto.CryptoDigestAlgorithm.SHA256,
          verifier,
          { encoding: Crypto.CryptoEncoding.BASE64 },
        )
      )
        .replace(/\+/g, "-")
        .replace(/\//g, "_")
        .replace(/=+$/, "");
      const state =
        Crypto.randomUUID().replace(/-/g, "") +
        Crypto.randomUUID().replace(/-/g, "");
      const platform = Platform.OS as "android" | "ios";
      const result = await WebBrowser.openAuthSessionAsync(
        authorizationUrl(runtime.webOrigin, {
          verifier,
          challenge,
          state,
          platform,
        }, nativeLinkPolicy),
        callback.redirectUri,
        callback.options,
      );
      if (result.type !== "success") {
        setError("Sign-in was cancelled. No new device session was retained.");
        return;
      }
      const code = parseCallback(result.url, state, nativeLinkPolicy);
      await runtime.session.exchange({
        code,
        code_verifier: verifier,
        redirect_uri: callback.redirectUri,
        platform,
      });
      const current = await runtime.session.revalidate();
      if (alive.current && foreground.current) setIdentity(current);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message === "IOS_HTTPS_CALLBACK_REQUIRES_17_4"
            ? "Secure sign-in requires iOS 17.4 or later. Update iOS before signing in."
            : cause.message === "NATIVE_SIGN_IN_NOT_CONFIGURED"
              ? "Native sign-in is not configured for this app build."
              : cause.message
          : "The secure sign-in could not be completed.",
      );
    } finally {
      loginInFlight.current = false;
      setBusy(false);
    }
  }

  return (
    <SafeAreaProvider>
      <StatusBar style="dark" />
      {identity && isForeground ? (
        <View style={{ flex: 1 }}>
          {error ? (
            <Text
              testID="app-operation-error"
              accessibilityRole="alert"
              style={{ padding: 16, color: "#a02030" }}
            >
              {error}
            </Text>
          ) : null}
          <MobileApplication
            key={`${identity.company.id}:${identity.user.id}:${identity.membership.id}`}
            identity={identity}
            request={runtime.request}
            viewer={runtime.viewer}
            sessionKey={runtime.session.sessionKey}
            initialFilesMatterId={fileState?.intent.matterId}
            selectedFile={fileState?.selection ?? null}
            onClearSelectedFile={clearSelection}
            onChooseFile={(matterId, expectedLifecycleVersion) => {
              setError(null);
              void picker
                .choose({
                  companyId: identity.company.id,
                  userId: identity.user.id,
                  membershipId: identity.membership.id,
                  sessionKey: runtime.session.sessionKey,
                  matterId,
                  expectedLifecycleVersion,
                })
                .catch((cause) => {
                  if (alive.current)
                    setError(
                      cause instanceof TempCleanupError
                        ? "Private temporary-file cleanup could not be confirmed. Restart CaseOps before choosing another file."
                        : "The file could not be selected. Please choose it again.",
                    );
                });
            }}
            onSignOut={async () => {
              setError(null);
              try {
                await runtime.session.signOut();
              } catch (cause) {
                setError(
                  cause instanceof Error
                    ? cause.message
                    : "Server revocation could not be confirmed.",
                );
              }
            }}
          />
        </View>
      ) : isForeground ? (
        <SignInPanel
          busy={busy}
          error={error}
          onContinue={() => void signIn()}
        />
      ) : (
        <View style={styles.cover} accessibilityLabel="CaseOps locked">
          <Text style={styles.brand}>CaseOps</Text>
        </View>
      )}
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  cover: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#f8f9fc",
  },
  brand: { fontSize: 26, color: "#252936", letterSpacing: 0 },
});
