import { useEffect, useState } from "react";
import { Platform } from "react-native";
import { NativeButton } from "./NativeControls";
import { colors } from "./theme";
import {
  dateOnlyToPickerDate,
  pickerDateToDateOnly,
} from "../domain/calendar-date";

export type NativeDatePickerProps = {
  value: string;
  onChange: (day: string) => void;
  onInvalidDate: () => void;
  disabled?: boolean;
};

export function NativeDatePicker({
  value,
  onChange,
  onInvalidDate,
  disabled = false,
}: NativeDatePickerProps) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);
  const selected = (date: Date) => {
    if (disabled) return;
    setOpen(false);
    let day: string;
    try {
      day = pickerDateToDateOnly(date);
    } catch {
      onInvalidDate();
      return;
    }
    onChange(day);
  };

  // Load only the current platform's native views, not the other native registry.
  if (Platform.OS === "android") {
    const { Host, DatePickerDialog } =
      require("@expo/ui/jetpack-compose") as typeof import("@expo/ui/jetpack-compose");
    return (
      <>
        <NativeButton
          testID="date-picker"
          label="Choose date"
          secondary
          disabled={disabled || open}
          onPress={() => setOpen(true)}
        />
        {open && !disabled ? (
          <Host
            style={{ width: 1, height: 1 }}
            colorScheme="light"
            seedColor={colors.brand}
          >
            <DatePickerDialog
              initialDate={dateOnlyToPickerDate(value).toISOString()}
              variant="picker"
              showVariantToggle
              confirmButtonLabel="Go to date"
              dismissButtonLabel="Cancel"
              color={colors.brand}
              onDateSelected={selected}
              onDismissRequest={() => setOpen(false)}
            />
          </Host>
        ) : null}
      </>
    );
  }
  if (Platform.OS === "ios") {
    const { Host, DatePicker } =
      require("@expo/ui/swift-ui") as typeof import("@expo/ui/swift-ui");
    const {
      accessibilityLabel,
      datePickerStyle,
      disabled: nativeDisabled,
      environment,
      frame,
    } = require("@expo/ui/swift-ui/modifiers") as typeof import("@expo/ui/swift-ui/modifiers");
    return (
      <Host
        matchContents={{ vertical: true }}
        style={{ width: "100%", minHeight: 44 }}
        colorScheme="light"
        seedColor={colors.brand}
      >
        <DatePicker
          testID="date-picker"
          title="Date"
          selection={dateOnlyToPickerDate(value)}
          displayedComponents={["date"]}
          onDateChange={selected}
          modifiers={[
            datePickerStyle("compact"),
            environment({ key: "timeZone", value: "UTC" }),
            accessibilityLabel("Agenda date"),
            nativeDisabled(disabled),
            frame({ minHeight: 44, maxWidth: Infinity, alignment: "leading" }),
          ]}
        />
      </Host>
    );
  }
  return null;
}
