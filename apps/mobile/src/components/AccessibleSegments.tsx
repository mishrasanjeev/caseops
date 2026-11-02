import { useState } from "react";
import type { ReactNode } from "react";
import { Pressable, Text, View, useWindowDimensions } from "react-native";
import { colors, styles, target } from "./theme";
import type { SegmentsProps } from "./NativeControls.types";
export function AccessibleSegments({
  label,
  options,
  value,
  onChange,
}: SegmentsProps) {
  return (
    <View accessibilityLabel={label} style={[styles.row, { gap: 4 }]}>
      {options.map((option) => (
        <Pressable
          key={option.value}
          testID={option.testID}
          accessibilityRole="tab"
          accessibilityState={{ selected: value === option.value }}
          onPress={() => onChange(option.value)}
          style={{
            flexGrow: 1,
            minHeight: target,
            minWidth: 72,
            padding: 12,
            borderBottomWidth: 2,
            borderBottomColor:
              value === option.value ? colors.brand : colors.line,
          }}
        >
          <Text
            style={[
              styles.body,
              {
                textAlign: "center",
                color: value === option.value ? colors.brand : colors.muted,
              },
            ]}
          >
            {option.label}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}
export function AdaptiveSegments({
  children,
  ...props
}: SegmentsProps & { children: ReactNode }) {
  const { fontScale } = useWindowDimensions();
  const [available, setAvailable] = useState(0);
  const minimum = props.options.reduce(
    (sum, option) =>
      sum + Math.max(target, option.label.length * 8 * fontScale + 32),
    0,
  );
  return (
    <View
      style={{ width: "100%" }}
      onLayout={(event) => setAvailable(event.nativeEvent.layout.width)}
    >
      {fontScale > 1.25 || available < minimum ? (
        <AccessibleSegments {...props} />
      ) : (
        children
      )}
    </View>
  );
}
