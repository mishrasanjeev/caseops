import { View } from "react-native";
import {
  Button,
  OutlinedButton,
  Host,
  LoadingIndicator,
  SegmentedButton,
  SingleChoiceSegmentedButtonRow,
  Text,
} from "@expo/ui/jetpack-compose";
import {
  defaultMinSize,
  fillMaxWidth,
  testID as nativeTestID,
} from "@expo/ui/jetpack-compose/modifiers";
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
  const Control = secondary ? OutlinedButton : Button;
  return (
    <Host
      matchContents={{ vertical: true }}
      style={{ width: "100%", minHeight: 48 }}
      colorScheme="light"
      seedColor={colors.brand}
    >
      <Control
        onClick={onPress}
        enabled={!disabled}
        modifiers={[
          fillMaxWidth(),
          defaultMinSize({ minHeight: 48, minWidth: 48 }),
          ...(testID ? [nativeTestID(testID)] : []),
        ]}
      >
        <Text>{label}</Text>
      </Control>
    </Host>
  );
}
export function NativeProgress() {
  return (
    <View accessibilityLabel="Loading" accessibilityRole="progressbar">
      <Host
        style={{ width: 48, height: 48 }}
        colorScheme="light"
        seedColor={colors.brand}
      >
        <LoadingIndicator color={colors.brand} />
      </Host>
    </View>
  );
}
export function NativeSegments(props: SegmentsProps) {
  return (
    <AdaptiveSegments {...props}>
      <Host
        matchContents={{ vertical: true }}
        style={{ width: "100%", minHeight: 48 }}
        colorScheme="light"
        seedColor={colors.brand}
      >
        <SingleChoiceSegmentedButtonRow
          modifiers={[fillMaxWidth(), defaultMinSize({ minHeight: 48 })]}
        >
          {props.options.map((option) => (
            <SegmentedButton
              key={option.value}
              selected={props.value === option.value}
              onClick={() => props.onChange(option.value)}
              modifiers={[
                defaultMinSize({ minHeight: 48, minWidth: 48 }),
                ...(option.testID ? [nativeTestID(option.testID)] : []),
              ]}
            >
              <SegmentedButton.Label>
                <Text>{option.label}</Text>
              </SegmentedButton.Label>
            </SegmentedButton>
          ))}
        </SingleChoiceSegmentedButtonRow>
      </Host>
    </AdaptiveSegments>
  );
}
