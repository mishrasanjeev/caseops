import { View } from "react-native";
import { Button, Host, Picker, ProgressView, Text } from "@expo/ui/swift-ui";
import {
  accessibilityLabel,
  buttonStyle,
  controlSize,
  disabled as nativeDisabled,
  frame,
  pickerStyle,
  tag,
  tint,
} from "@expo/ui/swift-ui/modifiers";
import { colors } from "./theme";
import { AdaptiveSegments } from "./AccessibleSegments";
import type { ButtonProps, SegmentsProps } from "./NativeControls.types";
export function NativeButton({
  label,
  onPress,
  disabled,
  secondary,
  testID,
}: ButtonProps) {
  return (
    <Host
      matchContents={{ vertical: true }}
      style={{ width: "100%", minHeight: 44 }}
      colorScheme="light"
      seedColor={colors.brand}
    >
      <Button
        label={label}
        onPress={onPress}
        testID={testID}
        modifiers={[
          buttonStyle(secondary ? "bordered" : "borderedProminent"),
          controlSize("large"),
          tint(colors.brand),
          nativeDisabled(!!disabled),
          frame({ minWidth: 44, minHeight: 44, maxWidth: Infinity }),
        ]}
      />
    </Host>
  );
}
export function NativeProgress() {
  return (
    <View accessibilityLabel="Loading" accessibilityRole="progressbar">
      <Host style={{ width: 44, height: 44 }} colorScheme="light">
        <ProgressView />
      </Host>
    </View>
  );
}
export function NativeSegments(props: SegmentsProps) {
  return (
    <AdaptiveSegments {...props}>
      <Host
        matchContents={{ vertical: true }}
        style={{ width: "100%", minHeight: 44 }}
        colorScheme="light"
        seedColor={colors.brand}
      >
        <Picker
          label={props.label}
          selection={props.value}
          onSelectionChange={props.onChange}
          modifiers={[
            pickerStyle("segmented"),
            accessibilityLabel(props.label),
            frame({ minHeight: 44, maxWidth: Infinity }),
          ]}
        >
          {props.options.map((option) => (
            <Text
              key={option.value}
              testID={option.testID}
              modifiers={[tag(option.value)]}
            >
              {option.label}
            </Text>
          ))}
        </Picker>
      </Host>
    </AdaptiveSegments>
  );
}
