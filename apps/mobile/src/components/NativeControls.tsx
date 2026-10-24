// Metro resolves the platform files on Android/iOS. This is the web/test fallback.
import { ActivityIndicator, Pressable, Text } from "react-native";
import { colors, styles, target } from "./theme";
import type { ButtonProps } from "./NativeControls.types";
import { AccessibleSegments } from "./AccessibleSegments";
export function NativeButton({
  label,
  onPress,
  disabled,
  secondary,
  testID,
}: ButtonProps) {
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityState={{ disabled: !!disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => ({
        minHeight: target,
        padding: 12,
        alignItems: "center",
        justifyContent: "center",
        backgroundColor: secondary ? colors.tonal : colors.brand,
        borderRadius: 8,
        opacity: disabled ? 0.45 : pressed ? 0.75 : 1,
      })}
    >
      <Text
        style={[
          styles.body,
          {
            color: secondary ? colors.brand : colors.surface,
            fontWeight: "600",
            textAlign: "center",
          },
        ]}
      >
        {label}
      </Text>
    </Pressable>
  );
}
export function NativeProgress() {
  return (
    <ActivityIndicator color={colors.brand} accessibilityLabel="Loading" />
  );
}
export const NativeSegments = AccessibleSegments;
