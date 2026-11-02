import { ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { NativeButton, NativeProgress } from "./NativeControls";
import { colors, styles } from "./theme";
export type SignInPanelProps = {
  busy: boolean;
  error: string | null;
  onContinue: () => void;
};
export function SignInPanel({ busy, error, onContinue }: SignInPanelProps) {
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
        <NativeButton
          label={busy ? "Opening secure sign-in" : "Continue to sign in"}
          onPress={onContinue}
          disabled={busy}
          testID="sign-in"
        />
      </ScrollView>
    </SafeAreaView>
  );
}
export default SignInPanel;
