import { useRef, useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { AccountDeviceSessions } from "../../components/AccountDeviceSessions";
import { NativeButton } from "../../components/NativeControls";
import { Fact } from "../../components/Content";
import { colors, styles } from "../../components/theme";

import type { MobileApplicationProps } from "../types";

export type AccountScreenProps = Pick<
  MobileApplicationProps,
  "identity" | "onSignOut"
> & {
  request?: MobileApplicationProps["request"];
};

export function AccountScreen({
  identity,
  onSignOut,
  request,
}: AccountScreenProps) {
  const [busy, setBusy] = useState(false),
    [sessionBusy, setSessionBusy] = useState(false),
    [error, setError] = useState<string | null>(null);
  const signOutLock = useRef(false);
  const signOut = async () => {
    if (signOutLock.current || sessionBusy) return;
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
      <View pointerEvents={busy ? "none" : "auto"}>
        {request ? (
          <AccountDeviceSessions
            key={`${identity.company.id}:${identity.user.id}`}
            request={request}
            disabled={busy}
            onCurrentSessionRevoked={onSignOut}
            onBusyChange={setSessionBusy}
          />
        ) : (
          <Text testID="account-sessions-unavailable" style={styles.muted}>
            Device-session management is unavailable in this app build.
          </Text>
        )}
      </View>
      <Text style={styles.muted}>
        Changing workspace requires sign-out and a new secure sign-in.
        Account-deletion requests remain in the web account settings.
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
        disabled={busy || sessionBusy}
        onPress={() => {
          void signOut();
        }}
      />
    </ScrollView>
  );
}
