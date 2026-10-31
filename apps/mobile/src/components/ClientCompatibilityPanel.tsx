import { ScrollView, Text } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import type { CompatibilitySnapshot } from "../network/client-compatibility";
import { NativeButton, NativeProgress } from "./NativeControls";
import { styles } from "./theme";

export function ClientCompatibilityPanel(props: {
  state: CompatibilitySnapshot;
  onRetry: () => void;
  onSignOut: () => void;
}) {
  const busy = props.state.busy;
  return (
    <SafeAreaView testID="client-compatibility" style={styles.fill}>
      <ScrollView
        contentContainerStyle={[
          styles.content,
          { flexGrow: 1, justifyContent: "center", gap: 24 },
        ]}
      >
        <Text accessibilityRole="header" style={styles.title}>
          {props.state.status === "update_required"
            ? "Update CaseOps"
            : "Check app compatibility"}
        </Text>
        {busy ? <NativeProgress /> : null}
        <Text accessibilityRole="alert" style={styles.body}>
          {busy
            ? "Checking whether this app can use the service."
            : props.state.message}
        </Text>
        {props.state.minimum ? (
          <Text style={styles.muted}>
            Required app version: {props.state.minimum} or later.
          </Text>
        ) : null}
        <Text style={styles.muted}>
          Private screens and work actions stay closed until compatibility is
          confirmed. Use your organization's approved installation method to
          obtain an update. You can sign out here, or revoke this device from
          another signed-in device.
        </Text>
        <NativeButton
          testID="compatibility-retry"
          label="Check again"
          disabled={busy}
          onPress={props.onRetry}
        />
        <NativeButton
          testID="compatibility-sign-out"
          label="Sign out"
          secondary
          onPress={props.onSignOut}
        />
      </ScrollView>
    </SafeAreaView>
  );
}
