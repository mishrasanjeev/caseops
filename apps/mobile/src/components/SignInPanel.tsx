import { Platform, StyleSheet, Text, View } from "react-native";
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
      <View style={welcome.hero}>
        <Text style={welcome.kicker}>Legal workspace</Text>
        <Text accessibilityRole="header" style={welcome.headline}>
          Your day in view.
        </Text>
        <Text style={welcome.intro}>
          Find your matters, upcoming hearings and assigned work in one place.
        </Text>
      </View>
      <View style={welcome.entry}>
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
  hero: { gap: 12 },
  kicker: {
    color: colors.brand,
    fontSize: 13,
    lineHeight: 19,
    fontWeight: "700",
    letterSpacing: 1.4,
    textTransform: "uppercase",
  },
  headline: {
    color: colors.ink,
    fontFamily: Platform.select({ ios: "Georgia", default: "serif" }),
    fontSize: 44,
    lineHeight: 52,
  },
  intro: { color: colors.muted, fontSize: 17, lineHeight: 25 },
  entry: { gap: 12 },
  error: { color: colors.danger },
});

export default SignInPanel;
