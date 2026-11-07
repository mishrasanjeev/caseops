import { ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { NativeButton, NativeProgress } from "./NativeControls";
import { PrivacyPolicyLink } from "./PrivacyPolicyLink";
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
    <SafeAreaView
      testID={busy ? "session-loading" : "signed-out"}
      style={styles.fill}
    >
      <ScrollView
        contentContainerStyle={[
          styles.content,
          { flexGrow: 1, justifyContent: "center", gap: 24 },
        ]}
      >
        <View style={{ gap: 8 }}>
          <Text style={[styles.title, { fontSize: 32, lineHeight: 40 }]}>
            CaseOps
          </Text>
          <Text style={styles.heading}>Your legal workspace</Text>
          <Text style={styles.muted}>Sign in securely to continue.</Text>
        </View>
        {error ? (
          <Text
            accessibilityRole="alert"
            style={[styles.body, { color: colors.danger }]}
          >
            {error}
          </Text>
        ) : null}
        {busy ? <NativeProgress /> : null}
        <View style={{ gap: 8 }}>
          <NativeButton
            label={busy ? "Opening secure sign-in" : "Continue to sign in"}
            onPress={() => {
              if (!busy && canOpenBrowser()) onContinue();
            }}
            disabled={busy || privacyOpening}
            testID="sign-in"
          />
          <PrivacyPolicyLink
            disabled={busy}
            canOpen={canOpenBrowser}
            openUrl={openPrivacyPolicy}
            hideUnconfigured
          />
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}
export default SignInPanel;
