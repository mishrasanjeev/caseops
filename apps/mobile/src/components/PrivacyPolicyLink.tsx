import { useEffect, useRef, useState } from "react";
import { Linking, Pressable, Text, View } from "react-native";
import Constants from "expo-constants";
import { createPrivacyPolicyOpener } from "../domain/privacy-policy";
import { colors, styles } from "./theme";

export function PrivacyPolicyLink({
  disabled = false,
}: {
  disabled?: boolean;
}) {
  const liveDisabled = useRef(disabled);
  liveDisabled.current = disabled;
  const [, changed] = useState(0);
  const controller = useRef<ReturnType<
    typeof createPrivacyPolicyOpener
  > | null>(null);
  const createController = () => {
    const extra = Constants.expoConfig?.extra;
    return createPrivacyPolicyOpener(extra?.privacyPolicy, extra?.webOrigin, {
      openUrl: (url) => Linking.openURL(url),
      allowed: () => !liveDisabled.current,
      changed: () => changed((value) => value + 1),
    });
  };
  if (!controller.current) controller.current = createController();
  const action = controller.current;
  useEffect(() => {
    if (!controller.current) controller.current = createController();
    return () => {
      controller.current?.dispose();
      controller.current = null;
    };
  }, []);
  const state = action.snapshot();
  const available = !["unconfigured", "unavailable", "unknown"].includes(
    state.status,
  );
  return (
    <View testID="privacy-policy" style={{ gap: 8 }}>
      {available ? (
        <Pressable
          accessibilityRole="link"
          accessibilityLabel="Read privacy policy"
          accessibilityHint="Opens your web browser"
          accessibilityState={{
            disabled: disabled || state.status === "opening",
          }}
          testID="privacy-policy-open"
          disabled={disabled || state.status === "opening"}
          onPress={() => {
            controller.current?.open();
          }}
          style={{ minHeight: 48, minWidth: 48, paddingVertical: 12 }}
        >
          <Text
            style={{
              ...styles.body,
              color: colors.brand,
              textDecorationLine: "underline",
            }}
          >
            Read privacy policy
          </Text>
        </Pressable>
      ) : null}
      <Text
        testID="privacy-policy-status"
        accessibilityLiveRegion="polite"
        style={styles.muted}
      >
        {state.message}
      </Text>
    </View>
  );
}
