import { useState } from "react";
import { ScrollView, Text } from "react-native";
import { NativeButton } from "../../components/NativeControls";
import { Fact } from "../../components/Content";
import { colors, styles } from "../../components/theme";

import type { MobileApplicationProps } from "../types";

export function AccountScreen({
  identity,
  onSignOut,
}: Pick<MobileApplicationProps, "identity" | "onSignOut">) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null);
  const signOut = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await onSignOut();
    } catch {
      setError(
        "Sign-out could not be confirmed. Check your connection and try again.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <ScrollView contentContainerStyle={styles.content}>
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
      <Text style={styles.muted}>
        Changing workspace requires sign-out and a new secure sign-in. Device
        sessions and account-deletion requests remain in the web account
        settings.
      </Text>
      {error ? (
        <Text
          accessibilityRole="alert"
          style={[styles.body, { color: colors.danger }]}
        >
          {error}
        </Text>
      ) : null}
      <NativeButton
        testID="sign-out"
        label={busy ? "Signing out" : "Sign out"}
        disabled={busy}
        onPress={() => {
          void signOut();
        }}
      />
    </ScrollView>
  );
}
