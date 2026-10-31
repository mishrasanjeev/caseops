import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AppState,
  Linking,
  Platform,
  StyleSheet,
  Text,
  View,
} from "react-native";
import Constants from "expo-constants";
import * as Crypto from "expo-crypto";
import * as WebBrowser from "expo-web-browser";
import { fetch as expoFetch } from "expo/fetch";
import { usePreventScreenCapture } from "expo-screen-capture";
import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { MobileApplication } from "./src/application/MobileApplication";
import { SignInPanel } from "./src/components/SignInPanel";
import { LocalLockPanel } from "./src/components/LocalLockPanel";
import { ClientCompatibilityPanel } from "./src/components/ClientCompatibilityPanel";
import { createClientCompatibility } from "./src/network/client-compatibility";
import { createLocalUnlock, sameServerBinding } from "./src/auth/local-unlock";
import type { LocalUnlockController } from "./src/auth/local-unlock";
import { createBiometricStore } from "./src/auth/biometric-store";
import {
  authorizationUrl,
  authSessionCallback,
  parseCallback,
} from "./src/auth/handoff";
import {
  DISABLED_NATIVE_LINK_POLICY,
  type NativeLinkPolicy,
} from "../web/lib/native-link-policy.cjs";
import { NativeSession } from "./src/auth/session";
import {
  credentialStore,
  initializeDeviceStore,
} from "./src/auth/secure-store";
import type { LocalSessionBinding, SessionIdentity } from "./src/auth/types";
import type { PurgeReason } from "./src/viewer/contracts";
import {
  checkedOrigin,
  createExpoFetchAdapter,
  JsonTransport,
  MobileApiError,
} from "./src/network/http";
import {
  createFilePickerCoordinator,
  pickerIdentityMatches,
} from "./src/domain/file-picker";
import {
  cleanupPickedFile,
  capturePhoto,
  pickFile,
  purgeMatterFileTemps,
} from "./src/files/native";
import { TempCleanupError } from "./src/files/staging";
import { CameraCaptureError } from "./src/files/camera";
import {
  createRecordLinkInbox,
  parseRecordLink,
} from "./src/domain/record-links";
import { runPrivateFileCleanup } from "./src/files/private-imports";

WebBrowser.maybeCompleteAuthSession();
type LocalUiCommand = {
  lock: LocalUnlockController | null;
  epoch: number | null;
  binding: LocalSessionBinding | null;
};

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
  const signOutInFlight = useRef(false);
  const localLock = useRef<LocalUnlockController | null>(null);
  const [, setLockRevision] = useState(0);
  const [, setCompatibilityRevision] = useState(0);
  const [, setRecordRevision] = useState(0);
  const [localStoreFailed, setLocalStoreFailed] = useState(false);
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
        runPrivateFileCleanup(
          [...listeners].map((listener) => () => listener(reason)),
        );
      },
    };
  }, []);
  const [, setPickerRevision] = useState(0);
  const picker = useMemo(
    () =>
      createFilePickerCoordinator(
        pickFile,
        cleanupPickedFile,
        () => {
          if (alive.current) setPickerRevision((value) => value + 1);
        },
        capturePhoto,
      ),
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
  const readFileSelection = useCallback(() => picker.selectionState, [picker]);
  const runtime = useMemo(() => {
    let compatibility: ReturnType<typeof createClientCompatibility> | null =
      null;
    let recordLinks: ReturnType<typeof createRecordLinkInbox> | null = null;
    let recordEpoch = 0;
    const recordRetirementListeners = new Set<() => void>();
    const retireRecordLinks = () => {
      ++recordEpoch;
      recordLinks?.invalidate();
      for (const notify of [...recordRetirementListeners]) notify();
    };
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
      { platform: Platform.OS, version: Constants.expoConfig?.version },
      createExpoFetchAdapter(expoFetch),
      20_000,
      {
        admit: (path, method) => {
          if (!compatibility)
            throw new MobileApiError(
              "App compatibility is unavailable.",
              503,
              "native_compatibility_unavailable",
            );
          compatibility.admit(path, method);
        },
        incompatible: (body) => compatibility?.incompatible(body),
      },
    );
    const session: NativeSession = new NativeSession(
      transport,
      credentialStore,
      Date.now,
      () => {
        if (alive.current) setIdentity(null);
        try {
          runPrivateFileCleanup([
            retireRecordLinks,
            () => compatibility?.invalidate(),
            () => localLock.current?.invalidate(),
            () => viewerEvents.notify("logout"),
            () => picker.clear(),
            purgeMatterFileTemps,
          ]);
        } catch {
          if (alive.current)
            setError(
              "Private temporary-file cleanup could not be confirmed. Restart before signing in.",
            );
        }
      },
      (path, method, purpose) => {
        compatibility?.admit(path, method);
        if (
          purpose === "business" &&
          !localLock.current?.allows(session.localBinding)
        )
          throw new MobileApiError(
            "Unlock CaseOps before continuing.",
            423,
            "local_device_locked",
          );
      },
    );
    compatibility = createClientCompatibility(
      { platform: Platform.OS, version: Constants.expoConfig?.version },
      (path) => transport.request(path),
      () => JSON.stringify(session.localBinding),
      (status) => {
        if (alive.current) {
          setIdentity(null);
          setError(null);
        }
        localLock.current?.invalidate();
        try {
          runPrivateFileCleanup([
            () => viewerEvents.notify("background"),
            () => {
              // A routine public recheck does not steal the SDK's opaque active
              // picker lease. A real denial/unknown policy cancels it normally.
              if (status !== "checking" || !picker.picking) {
                picker.clear();
                purgeMatterFileTemps();
              }
            },
          ]);
        } catch {
          if (alive.current)
            setError(
              "Private temporary-file cleanup could not be confirmed. Restart CaseOps.",
            );
        }
      },
      () => {
        if (alive.current) setCompatibilityRevision((value) => value + 1);
      },
    );
    const recordPolicy: NativeLinkPolicy = Object.freeze({
      ...(extra?.nativeLinkPolicy || DISABLED_NATIVE_LINK_POLICY),
    });
    recordLinks = createRecordLinkInbox(
      recordPolicy,
      () => ({
        binding: session.localBinding,
        allowed:
          alive.current &&
          foreground.current &&
          compatibility?.supported === true &&
          localLock.current?.allows(session.localBinding) === true,
      }),
      () => {
        if (alive.current) setRecordRevision((value) => value + 1);
      },
    );
    return {
      session,
      compatibility,
      recordLinks,
      recordPolicy,
      get recordEpoch() {
        return recordEpoch;
      },
      retireRecordLinks,
      subscribeRecordRetirement(notify: () => void) {
        recordRetirementListeners.add(notify);
        return () => {
          recordRetirementListeners.delete(notify);
        };
      },
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
  const coverPrivate = useCallback(async () => {
    if (alive.current) setIdentity(null);
    runPrivateFileCleanup([
      () => viewerEvents.notify("background"),
      () => {
        if (!picker.picking) {
          picker.clear();
          purgeMatterFileTemps();
        }
      },
    ]);
  }, [picker, viewerEvents]);

  const openServerSession = useCallback(async () => {
    runtime.compatibility.admit("/api/auth/me", "GET");
    if (!runtime.session.identity && !(await runtime.session.restore()))
      return null;
    return runtime.session.revalidate();
  }, [runtime]);
  const publishUnlocked = useCallback(
    (
      current: SessionIdentity | null,
      owner: LocalUnlockController,
      expectedEpoch: number,
    ) => {
      const binding = runtime.session.localBinding;
      if (
        current &&
        binding &&
        current.user.id === binding.userId &&
        current.company.id === binding.companyId &&
        current.membership.id === binding.membershipId &&
        alive.current &&
        foreground.current &&
        localLock.current === owner &&
        owner.commandEpoch === expectedEpoch &&
        owner.allows(binding) &&
        runtime.compatibility.supported
      )
        setIdentity(current);
    },
    [runtime],
  );
  const currentUiCommand = useCallback(
    (command: LocalUiCommand) => {
      const lock = localLock.current,
        binding = runtime.session.localBinding;
      if (!alive.current || !foreground.current || lock !== command.lock)
        return false;
      if (lock)
        return (
          command.epoch !== null &&
          lock.commandCurrent(command.epoch, command.binding)
        );
      return command.binding === null
        ? binding === null
        : !!binding &&
            binding.sessionKey === command.binding.sessionKey &&
            sameServerBinding(command.binding, binding);
    },
    [runtime],
  );
  const resumeServer = useCallback(
    async (biometric = false, command?: LocalUiCommand) => {
      if (command && !currentUiCommand(command)) return;
      const lock = localLock.current;
      if (
        !lock ||
        lock.busy ||
        signOutInFlight.current ||
        !runtime.compatibility.supported
      )
        return;
      const expectedEpoch = lock.commandEpoch;
      setBusy(true);
      try {
        publishUnlocked(
          await (biometric
            ? lock.unlock(openServerSession)
            : lock.resume(openServerSession)),
          lock,
          expectedEpoch,
        );
      } finally {
        if (alive.current) setBusy(false);
      }
    },
    [openServerSession, publishUnlocked, currentUiCommand],
  );
  const checkCompatibilityAndResume = useCallback(async () => {
    const lock = localLock.current,
      sessionKey = runtime.session.sessionKey;
    const supported = await runtime.compatibility.refresh();
    if (
      !supported ||
      !alive.current ||
      !foreground.current ||
      !lock ||
      localLock.current !== lock ||
      runtime.session.sessionKey !== sessionKey ||
      lock.required ||
      lock.busy ||
      loginInFlight.current ||
      signOutInFlight.current
    )
      return;
    const expectedEpoch = lock.commandEpoch;
    publishUnlocked(await lock.resume(openServerSession), lock, expectedEpoch);
  }, [runtime, openServerSession, publishUnlocked]);
  const uiCommand: LocalUiCommand = {
    lock: localLock.current,
    epoch: localLock.current?.commandEpoch ?? null,
    binding: runtime.session.localBinding,
  };
  const selectionSessionKey = runtime.session.sessionKey;
  const fileState = identity
    ? picker.snapshot(identity, selectionSessionKey)
    : null;

  const chooseFile = (
    matterId: string,
    expectedLifecycleVersion: number,
    source: "file" | "camera",
  ) => {
    if (!identity) return;
    const intent = {
      companyId: identity.company.id,
      userId: identity.user.id,
      membershipId: identity.membership.id,
      sessionKey: selectionSessionKey,
      matterId,
      expectedLifecycleVersion,
    };
    const current = runtime.session.identity;
    if (
      !alive.current ||
      !foreground.current ||
      !current ||
      !runtime.compatibility.supported ||
      !localLock.current?.allows(runtime.session.localBinding) ||
      !pickerIdentityMatches(intent, current, runtime.session.sessionKey) ||
      !current.capabilities.includes("documents:upload")
    )
      return;
    setError(null);
    void picker.choose(intent, source).catch((cause) => {
      if (alive.current)
        setError(
          cause instanceof TempCleanupError
            ? "Private temporary-file cleanup could not be confirmed. Restart CaseOps before choosing another file."
            : cause instanceof CameraCaptureError
              ? cause.message
              : "The file could not be selected. Please choose it again.",
        );
    });
  };

  useEffect(() => {
    alive.current = true;
    let disposed = false;
    let ownedLock: LocalUnlockController | null = null;
    void (async () => {
      try {
        const installationId = await initializeDeviceStore();
        if (disposed) return;
        purgeMatterFileTemps();
        ownedLock = createLocalUnlock(
          installationId,
          createBiometricStore(installationId),
          {
            current: () => runtime.session.localBinding,
            revalidate: () => runtime.session.revalidate(),
          },
          coverPrivate,
          () => {
            if (!disposed) setLockRevision((value) => value + 1);
          },
        );
        localLock.current = ownedLock;
        ownedLock.visibility(
          AppState.currentState === "active"
            ? "active"
            : AppState.currentState === "inactive"
              ? "inactive"
              : "background",
        );
        await ownedLock.initialize();
        const compatible = await runtime.compatibility.refresh();
        if (
          !compatible ||
          disposed ||
          localLock.current !== ownedLock ||
          !foreground.current ||
          ownedLock.required
        )
          return;
        const expectedEpoch = ownedLock.commandEpoch;
        publishUnlocked(
          await ownedLock.resume(openServerSession),
          ownedLock,
          expectedEpoch,
        );
      } catch {
        if (!disposed) {
          setLocalStoreFailed(true);
          setError(
            "Local device storage could not be verified. Private access remains locked. Sign out and restart CaseOps.",
          );
        }
      } finally {
        if (!disposed) setBusy(false);
      }
    })();
    const listener = AppState.addEventListener("change", (state) => {
      foreground.current = state === "active";
      setIsForeground(foreground.current);
      runtime.compatibility.visibility(
        state === "active",
        state === "background",
      );
      localLock.current?.visibility(
        state === "active"
          ? "active"
          : state === "inactive"
            ? "inactive"
            : "background",
      );
      if (state !== "active") {
        // SDK camera/picker ownership survives only its existing opaque intent.
        // Normal background selections and viewer buffers are cleared.
        void coverPrivate().catch(() =>
          setError(
            "Private temporary-file cleanup could not be confirmed. Restart CaseOps.",
          ),
        );
      } else if (!loginInFlight.current) {
        // Face ID's owned transient inactive state must not cancel its own
        // prompt. Actual background already invalidated the policy and epoch.
        if (
          !localLock.current?.busy ||
          runtime.compatibility.getSnapshot().status !== "supported"
        )
          void checkCompatibilityAndResume();
      }
    });
    return () => {
      alive.current = false;
      disposed = true;
      listener.remove();
      ownedLock?.invalidate();
      if (localLock.current === ownedLock) localLock.current = null;
      picker.clear();
    };
  }, [
    runtime,
    picker,
    coverPrivate,
    openServerSession,
    publishUnlocked,
    resumeServer,
    checkCompatibilityAndResume,
  ]);

  useEffect(() => {
    let disposed = false,
      warmSerial = 0;
    let listener: ReturnType<typeof Linking.addEventListener> | null = null;
    const initialEpoch = runtime.recordEpoch;
    const receive = (url: unknown, expectedEpoch: number) => {
      if (
        disposed ||
        !alive.current ||
        runtime.recordEpoch !== expectedEpoch ||
        !parseRecordLink(url, runtime.recordPolicy)
      )
        return false;
      // Only validated record locators reach this inbox. OAuth callbacks and
      // their state/code/query are left entirely to the existing PKCE handler.
      return runtime.recordLinks.receive(url);
    };
    const listeningFailed = () => {
      if (!disposed && alive.current)
        setError(
          "Record-link listening could not be confirmed. Reopen CaseOps before opening the link again.",
        );
    };
    const detach = () => {
      const previous = listener;
      listener = null;
      try {
        previous?.remove();
      } catch {
        listeningFailed();
      }
    };
    const bindWarm = () => {
      detach();
      if (disposed) return;
      const ownerEpoch = runtime.recordEpoch;
      try {
        listener = Linking.addEventListener("url", (event) => {
          if (
            disposed ||
            !alive.current ||
            runtime.recordEpoch !== ownerEpoch ||
            !parseRecordLink(event.url, runtime.recordPolicy)
          )
            return;
          ++warmSerial;
          receive(event.url, ownerEpoch);
        });
      } catch {
        listeningFailed();
      }
    };
    // Retirement advances the epoch synchronously before replacing the native
    // subscription. Even a retained/late old callback cannot become a cold link.
    const unsubscribe = runtime.subscribeRecordRetirement(bindWarm);
    bindWarm();
    try {
      void Linking.getInitialURL()
        .then((url) => {
          if (
            !disposed &&
            runtime.recordEpoch === initialEpoch &&
            warmSerial === 0
          )
            receive(url, initialEpoch);
        })
        .catch(() => {
          if (
            !disposed &&
            alive.current &&
            runtime.recordEpoch === initialEpoch &&
            warmSerial === 0
          )
            setError(
              "The initial record link could not be read. Open it again when ready.",
            );
        });
    } catch {
      if (
        !disposed &&
        alive.current &&
        runtime.recordEpoch === initialEpoch &&
        warmSerial === 0
      )
        setError(
          "The initial record link could not be read. Open it again when ready.",
        );
    }
    return () => {
      disposed = true;
      unsubscribe();
      detach();
      runtime.retireRecordLinks();
    };
  }, [runtime]);

  async function signOut(command = uiCommand) {
    if (signOutInFlight.current || !currentUiCommand(command)) return;
    signOutInFlight.current = true;
    localLock.current?.invalidate();
    setIdentity(null);
    setError(null);
    setBusy(true);
    try {
      try {
        await runtime.session.signOut();
      } catch (cause) {
        if (alive.current)
          setError(
            cause instanceof Error
              ? cause.message
              : "Server revocation could not be confirmed.",
          );
      }
      try {
        await localLock.current?.reset();
        await runtime.compatibility.refresh();
      } catch {
        if (alive.current)
          setError(
            "Signed out locally, but local lock removal could not be confirmed. Restart CaseOps before signing in.",
          );
      }
    } finally {
      signOutInFlight.current = false;
      if (alive.current) setBusy(false);
    }
  }

  async function enableLocalLock(command = uiCommand) {
    const lock = localLock.current;
    if (
      !lock ||
      lock.busy ||
      signOutInFlight.current ||
      !identity ||
      !currentUiCommand(command) ||
      !lock.allows(runtime.session.localBinding) ||
      !runtime.compatibility.supported
    )
      return;
    const expectedEpoch = lock.commandEpoch;
    publishUnlocked(await lock.enable(), lock, expectedEpoch);
  }

  async function signIn() {
    if (
      loginInFlight.current ||
      signOutInFlight.current ||
      localStoreFailed ||
      !runtime.compatibility.supported ||
      !currentUiCommand(uiCommand) ||
      !localLock.current ||
      localLock.current.required ||
      localLock.current.busy ||
      !["android", "ios"].includes(Platform.OS)
    )
      return;
    loginInFlight.current = true;
    const owner = localLock.current;
    const loginSessionKey = runtime.session.sessionKey;
    setBusy(true);
    setError(null);
    try {
      const nativeLinkPolicy: NativeLinkPolicy =
        Constants.expoConfig?.extra?.nativeLinkPolicy ||
        DISABLED_NATIVE_LINK_POLICY;
      const callback = authSessionCallback(
        nativeLinkPolicy,
        Platform.OS,
        Platform.Version,
      );
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
        authorizationUrl(
          runtime.webOrigin,
          {
            verifier,
            challenge,
            state,
            platform,
          },
          nativeLinkPolicy,
        ),
        callback.redirectUri,
        callback.options,
      );
      if (result.type !== "success") {
        setError("Sign-in was cancelled. No new device session was retained.");
        return;
      }
      if (
        !alive.current ||
        localLock.current !== owner ||
        runtime.session.sessionKey !== loginSessionKey ||
        signOutInFlight.current
      )
        return;
      if (
        !(await runtime.compatibility.refresh()) ||
        localLock.current !== owner ||
        runtime.session.sessionKey !== loginSessionKey ||
        signOutInFlight.current ||
        !alive.current
      )
        return;
      const code = parseCallback(result.url, state, nativeLinkPolicy);
      const expectedEpoch = owner.commandEpoch;
      publishUnlocked(
        await owner.resume(async () => {
          await runtime.session.exchange({
            code,
            code_verifier: verifier,
            redirect_uri: callback.redirectUri,
            platform,
          });
          return runtime.session.revalidate();
        }),
        owner,
        expectedEpoch,
      );
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
      {isForeground && !runtime.compatibility.supported ? (
        <ClientCompatibilityPanel
          state={{
            ...runtime.compatibility.getSnapshot(),
            message: error || runtime.compatibility.getSnapshot().message,
          }}
          onRetry={() => {
            void checkCompatibilityAndResume();
          }}
          onSignOut={() => {
            void signOut();
          }}
        />
      ) : identity &&
        isForeground &&
        localLock.current?.allows(runtime.session.localBinding) ? (
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
            recordLinks={
              uiCommand.binding
                ? { inbox: runtime.recordLinks, binding: uiCommand.binding }
                : undefined
            }
            sessionKey={runtime.session.sessionKey}
            initialFilesMatterId={fileState?.intent.matterId}
            selectedFile={fileState?.selection ?? null}
            onClearSelectedFile={clearSelection}
            selectingFile={picker.picking}
            selectionRevision={
              fileState?.revision ?? picker.selectionState.revision
            }
            readFileSelection={readFileSelection}
            localUnlock={{
              enabled: localLock.current.getSnapshot().enabled,
              busy: localLock.current.busy,
              message: localLock.current.getSnapshot().message,
              enable: enableLocalLock,
            }}
            onChooseFile={(matterId, version) =>
              chooseFile(matterId, version, "file")
            }
            onCapturePhoto={(matterId, version) =>
              chooseFile(matterId, version, "camera")
            }
            onSignOut={signOut}
          />
        </View>
      ) : isForeground &&
        (localStoreFailed ||
          localLock.current?.required ||
          runtime.session.identity) ? (
        <LocalLockPanel
          biometric={!!localLock.current?.required}
          available={
            !localStoreFailed &&
            (!localLock.current?.required ||
              localLock.current.getSnapshot().enabled)
          }
          busy={busy || !!localLock.current?.busy}
          message={error || localLock.current?.getSnapshot().message || ""}
          onUnlock={() => {
            void resumeServer(!!localLock.current?.required, uiCommand);
          }}
          onSignOut={() => {
            void signOut();
          }}
        />
      ) : isForeground ? (
        <SignInPanel
          busy={busy}
          error={error || localLock.current?.getSnapshot().message || null}
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
