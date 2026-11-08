import { StyleSheet, Text, View } from "react-native";
import { NativeButton, NativeProgress } from "./NativeControls";
import { PrivacyPolicyLink } from "./PrivacyPolicyLink";
import { WelcomeFrame } from "./WelcomeFrame";
import { colors, styles } from "./theme";
export type SignInPanelProps = {
  busy: boolean;
  error: string | null;
  onContinue: () => void;
  privacyOpening: boolean;
  canOpenBrowser: () => boolean;
  openPrivacyPolicy: (url: string) => Promise<unknown>;
};
export function SignInPanel({
  busy,
  error,
  onContinue,
  privacyOpening,
  canOpenBrowser,
  openPrivacyPolicy,
}: SignInPanelProps) {
  return (
    <WelcomeFrame testID={busy ? "session-loading" : "signed-out"}>
      <View style={welcome.group}>
        <Text accessibilityRole="header" style={styles.title}>
          Your legal workspace
        </Text>
        <Text style={styles.body}>
          Find your matters, upcoming hearings and assigned work in one place.
        </Text>
      </View>
      <View style={welcome.group}>
        <Text style={styles.muted}>Sign in securely to continue.</Text>
        {error ? (
          <Text accessibilityRole="alert" style={[styles.body, welcome.error]}>
            {error}
          </Text>
        ) : null}
        <NativeButton
          label={busy ? "Opening secure sign-in" : "Continue to sign in"}
          onPress={() => {
            if (!busy && canOpenBrowser()) onContinue();
          }}
          disabled={busy || privacyOpening}
          testID="sign-in"
        />
        {busy ? <NativeProgress /> : null}
        <PrivacyPolicyLink
          disabled={busy}
          canOpen={canOpenBrowser}
          openUrl={openPrivacyPolicy}
          hideUnconfigured
        />
      </View>
    </WelcomeFrame>
  );
}

const welcome = StyleSheet.create({
  group: { gap: 12 },
  error: { color: colors.danger },
});

export default SignInPanel;
