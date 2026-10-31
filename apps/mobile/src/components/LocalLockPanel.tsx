import { ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { NativeButton, NativeProgress } from "./NativeControls";
import { styles } from "./theme";

export function LocalLockPanel(props: {
  biometric: boolean;
  available: boolean;
  busy: boolean;
  message: string;
  onUnlock: () => void;
  onSignOut: () => void;
}) {
  return (
    <SafeAreaView testID="local-lock" style={styles.fill}>
      <ScrollView
        contentContainerStyle={[
          styles.content,
          { flexGrow: 1, justifyContent: "center", gap: 24 },
        ]}
      >
        <Text style={styles.title}>CaseOps locked</Text>
        <Text style={styles.body}>
          {props.biometric
            ? "Unlock with biometrics, then CaseOps will check your current server session."
            : "Your workspace must be checked again before private information is shown."}
        </Text>
        {props.message ? (
          <Text
            testID="local-lock-message"
            accessibilityRole="alert"
            style={styles.body}
          >
            {props.message}
          </Text>
        ) : null}
        {props.busy ? (
          <View>
            <NativeProgress />
            <Text style={styles.muted}>
              Checking access. Finish or cancel any device prompt before trying
              again.
            </Text>
          </View>
        ) : null}
        <NativeButton
          testID="local-unlock"
          label={
            props.biometric ? "Unlock with biometrics" : "Recheck workspace"
          }
          disabled={props.busy || !props.available}
          onPress={props.onUnlock}
        />
        <NativeButton
          testID="local-lock-sign-out"
          label="Sign out and use secure sign-in"
          secondary
          onPress={props.onSignOut}
        />
        <Text style={styles.muted}>
          Biometrics protect this device's local screen access. They do not
          replace server sign-in or multi-factor authentication.
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}
