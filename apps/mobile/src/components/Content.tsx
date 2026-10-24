import React from "react";
import { Pressable, Text, View } from "react-native";
import Ionicons from "@expo/vector-icons/Ionicons";
import { NativeButton, NativeProgress } from "./NativeControls";
import { colors, styles, target } from "./theme";
import type { Resource } from "../application/useResource";
export function ResourceView<T>({
  resource,
  reload,
  children,
}: {
  resource: Resource<T>;
  reload: () => void;
  children: (value: T) => React.ReactNode;
}) {
  if (resource.state === "loading")
    return (
      <View
        accessibilityLiveRegion="polite"
        style={{ paddingVertical: 24, gap: 12 }}
      >
        <NativeProgress />
        <Text style={styles.muted}>Loading current records</Text>
        <View
          style={{
            height: 16,
            width: "80%",
            backgroundColor: colors.background,
          }}
        />
        <View
          style={{
            height: 16,
            width: "55%",
            backgroundColor: colors.background,
          }}
        />
      </View>
    );
  if (resource.state === "error")
    return (
      <View style={{ gap: 12 }}>
        <Text accessibilityRole="alert" style={styles.heading}>
          {resource.error.title}
        </Text>
        <Text style={styles.body}>{resource.error.message}</Text>
        <NativeButton label="Reload" onPress={reload} secondary />
      </View>
    );
  return <>{children(resource.data)}</>;
}
export function RecordRow({
  title,
  subtitle,
  meta,
  onPress,
  testID,
  icon = "chevron-forward",
}: {
  title: string;
  subtitle?: string | null;
  meta?: string | null;
  onPress?: () => void;
  testID?: string;
  icon?: React.ComponentProps<typeof Ionicons>["name"];
}) {
  const content = (
    <>
      <View style={{ flex: 1, minWidth: 0, gap: 4 }}>
        <Text style={[styles.body, { fontWeight: "600" }]}>{title}</Text>
        {subtitle ? <Text style={styles.muted}>{subtitle}</Text> : null}
        {meta ? <Text style={styles.label}>{meta}</Text> : null}
      </View>
      {onPress ? (
        <Ionicons
          name={icon}
          size={20}
          color={colors.muted}
          accessibilityElementsHidden
          importantForAccessibility="no"
        />
      ) : null}
    </>
  );
  const rowStyle = {
    minHeight: target,
    paddingVertical: 16,
    flexDirection: "row" as const,
    alignItems: "center" as const,
    gap: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.line,
  };
  return onPress ? (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      onPress={onPress}
      style={({ pressed }) => [rowStyle, { opacity: pressed ? 0.65 : 1 }]}
    >
      {content}
    </Pressable>
  ) : (
    <View style={rowStyle}>{content}</View>
  );
}
export function Empty({ title, message }: { title: string; message: string }) {
  return (
    <View style={{ paddingVertical: 24, gap: 8 }}>
      <Text style={styles.heading}>{title}</Text>
      <Text style={styles.muted}>{message}</Text>
    </View>
  );
}
export function Fact({
  label,
  value,
  testID,
}: {
  label: string;
  value: string | null | undefined;
  testID?: string;
}) {
  return (
    <View style={[styles.divider, { gap: 4, paddingVertical: 10 }]}>
      <Text style={styles.label}>{label}</Text>
      <Text testID={testID} selectable style={styles.body}>
        {value || "Not recorded"}
      </Text>
    </View>
  );
}
