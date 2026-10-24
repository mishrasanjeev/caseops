import { useEffect, useMemo, useRef, useState } from "react";
import { AppState, Platform, StyleSheet, Text, View } from "react-native";
import Constants from "expo-constants";
import * as Crypto from "expo-crypto";
import * as WebBrowser from "expo-web-browser";
import { usePreventScreenCapture } from "expo-screen-capture";
import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { MobileApplication } from "./src/application/MobileApplication";
import { SignInPanel } from "./src/components/SignInPanel";
import {
  authorizationUrl,
  NATIVE_CALLBACK,
  parseCallback,
} from "./src/auth/handoff";
import { NativeSession } from "./src/auth/session";
import {
  credentialStore,
  initializeDeviceStore,
} from "./src/auth/secure-store";
import type { SessionIdentity } from "./src/auth/types";
import { checkedOrigin, JsonTransport } from "./src/network/http";

WebBrowser.maybeCompleteAuthSession();

export default function App() {
  usePreventScreenCapture();
  const [identity, setIdentity] = useState<SessionIdentity | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const foreground = useRef(AppState.currentState === "active");
  const loginInFlight = useRef(false);
  const alive = useRef(true);
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
    );
    const session = new NativeSession(
      transport,
      credentialStore,
      Date.now,
      () => {
        if (alive.current) setIdentity(null);
      },
    );
    return { session, webOrigin };
  }, []);

  useEffect(() => {
    alive.current = true;
    void (async () => {
      try {
        await initializeDeviceStore();
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
      if (state !== "active") {
        // Unmount private screens and discard their memory-only records/drafts.
        setIdentity(null);
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
    };
  }, [runtime]);

  async function signIn() {
    if (loginInFlight.current || !["android", "ios"].includes(Platform.OS))
      return;
    loginInFlight.current = true;
    setBusy(true);
    setError(null);
    try {
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
        }),
        NATIVE_CALLBACK,
        { preferEphemeralSession: true },
      );
      if (result.type !== "success") {
        setError("Sign-in was cancelled. No new device session was retained.");
        return;
      }
      const code = parseCallback(result.url, state);
      await runtime.session.exchange({
        code,
        code_verifier: verifier,
        redirect_uri: NATIVE_CALLBACK,
        platform,
      });
      const current = await runtime.session.revalidate();
      if (alive.current && foreground.current) setIdentity(current);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
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
      {identity && foreground.current ? (
        <MobileApplication
          key={`${identity.company.id}:${identity.user.id}:${identity.membership.id}`}
          identity={identity}
          request={runtime.session.request.bind(runtime.session)}
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
      ) : foreground.current ? (
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
