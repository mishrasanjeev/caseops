import { useCallback, useRef, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { AccountDeviceSessions } from "../../components/AccountDeviceSessions";
import { AccountHelp } from "../../components/AccountHelp";
import { AccountPrivacyRequests } from "../../components/AccountPrivacyRequests";
import { NativeButton } from "../../components/NativeControls";
import { Fact } from "../../components/Content";
import { colors, styles } from "../../components/theme";
import { cameraLicences } from "../../files/camera-notices";

import type { MobileApplicationProps } from "../types";

export type AccountScreenProps = Pick<
  MobileApplicationProps,
  "identity" | "onSignOut"
> & {
  request?: MobileApplicationProps["request"];
  localUnlock?: MobileApplicationProps["localUnlock"];
};

export function AccountScreen({
  identity,
  onSignOut,
  request,
  localUnlock,
}: AccountScreenProps) {
  const [busy, setBusy] = useState(false),
    [sessionBusy, setSessionBusy] = useState(false),
    [privacyBusy, setPrivacyBusy] = useState(false),
    [softwareNotices, setSoftwareNotices] = useState(false),
    [error, setError] = useState<string | null>(null);
  const signOutLock = useRef(false);
  const activity = useRef({ sessions: false, privacy: false, local: false });
  const markSessionBusy = useCallback((value: boolean) => {
    activity.current.sessions = value;
    setSessionBusy(value);
  }, []);
  const markPrivacyBusy = useCallback((value: boolean) => {
    activity.current.privacy = value;
    setPrivacyBusy(value);
  }, []);
  const privacyAvailable = useCallback(
    () =>
      !signOutLock.current &&
      !activity.current.sessions &&
      !activity.current.local,
    [],
  );
  const enableLocalLock = async () => {
    if (
      !localUnlock ||
      signOutLock.current ||
      activity.current.sessions ||
      activity.current.privacy ||
      activity.current.local
    )
      return;
    activity.current.local = true;
    try {
      await localUnlock.enable();
    } finally {
      activity.current.local = false;
    }
  };
  const signOut = async () => {
    if (
      signOutLock.current ||
      activity.current.sessions ||
      activity.current.privacy
    )
      return;
    signOutLock.current = true;
    setBusy(true);
    setError(null);
    try {
      await onSignOut();
    } catch {
      setError(
        "Sign-out could not be confirmed. Check your connection and try again.",
      );
    } finally {
      signOutLock.current = false;
      setBusy(false);
    }
  };
  return (
    <ScrollView testID="account-screen" contentContainerStyle={styles.content}>
      <Text accessibilityRole="header" style={styles.title}>
        Account
      </Text>
      <Fact
        label="Signed in as"
        testID="account-principal"
        value={identity.user.full_name || identity.user.email}
      />
      <Fact label="Email" value={identity.user.email} />
      <Fact
        testID="account-workspace"
        label="Workspace"
        value={identity.company.name}
      />
      <Fact label="Workspace address" value={identity.company.slug} />
      {localUnlock ? (
        <View testID="account-local-lock" style={{ gap: 12 }}>
          <Text accessibilityRole="header" style={styles.heading}>
            Biometric screen lock
          </Text>
          <Text style={styles.muted}>
            {localUnlock.enabled
              ? "Enabled for this sign-in on this installation. Sign out to turn it off."
              : "Optional: require biometrics before reopening private screens. Server sign-in and MFA still apply. Changing biometric enrollment can make the local marker unavailable; sign out and use secure sign-in if that happens."}
          </Text>
          {localUnlock.message ? (
            <Text accessibilityRole="alert" style={styles.body}>
              {localUnlock.message}
            </Text>
          ) : null}
          {!localUnlock.enabled ? (
            <NativeButton
              testID="local-lock-enable"
              label="Enable biometric screen lock"
              disabled={busy || sessionBusy || privacyBusy || localUnlock.busy}
              onPress={() => {
                void enableLocalLock();
              }}
            />
          ) : null}
        </View>
      ) : null}
      <View pointerEvents={busy ? "none" : "auto"}>
        {request ? (
          <AccountDeviceSessions
            key={`${identity.company.id}:${identity.user.id}`}
            request={request}
            disabled={busy || privacyBusy}
            onCurrentSessionRevoked={onSignOut}
            onBusyChange={markSessionBusy}
          />
        ) : (
          <Text testID="account-sessions-unavailable" style={styles.muted}>
            Device-session management is unavailable in this app build.
          </Text>
        )}
      </View>
      <Text style={styles.muted}>
        Changing workspace requires sign-out and a new secure sign-in. For
        workspace and organization records, contact your organization
        administrator.{" "}
        {request
          ? "The panel below records a self account deletion request when the configured service supports it."
          : "Account request intake is unavailable in this app build."}
      </Text>
      {error ? (
        <Text
          testID="account-sign-out-error"
          accessibilityRole="alert"
          style={[styles.body, { color: colors.danger }]}
        >
          {error}
        </Text>
      ) : null}
      <NativeButton
        testID="sign-out"
        label={busy ? "Signing out" : "Sign out"}
        disabled={busy || sessionBusy || privacyBusy}
        onPress={() => {
          void signOut();
        }}
      />
      {request ? (
        <AccountPrivacyRequests
          request={request}
          subjectKey={JSON.stringify([
            identity.company.id,
            identity.membership.id,
            identity.user.id,
          ])}
          disabled={busy || sessionBusy}
          available={privacyAvailable}
          onBusyChange={markPrivacyBusy}
        />
      ) : null}
      <AccountHelp
        disabled={busy || sessionBusy || privacyBusy}
        requestPanelPresent={!!request}
      />
      <View testID="account-software" style={{ gap: 12 }}>
        <Text accessibilityRole="header" style={styles.heading}>
          About this software
        </Text>
        <NativeButton
          testID="account-camera-notices"
          label={
            softwareNotices
              ? "Hide camera software licences"
              : "Camera software licences"
          }
          secondary
          onPress={() => setSoftwareNotices((value) => !value)}
        />
        {softwareNotices ? (
          <Text testID="account-camera-licences" style={styles.muted}>
            {cameraLicences}
          </Text>
        ) : null}
      </View>
    </ScrollView>
  );
}
