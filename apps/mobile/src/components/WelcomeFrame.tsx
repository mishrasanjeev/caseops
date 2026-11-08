import type { ReactNode } from "react";
import { Image, ScrollView, StyleSheet, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { styles } from "./theme";

export function WelcomeFrame({
  testID,
  children,
}: {
  testID: string;
  children: ReactNode;
}) {
  return (
    <SafeAreaView testID={testID} style={styles.fill}>
      <ScrollView contentContainerStyle={[styles.content, frame.content]}>
        <View style={[styles.divider, frame.masthead]}>
          <Image
            source={require("../../assets/app-icon.png")}
            style={frame.mark}
            resizeMethod="resize"
            fadeDuration={0}
            accessible={false}
            accessibilityElementsHidden
            importantForAccessibility="no"
          />
          <Text style={styles.heading}>CaseOps</Text>
        </View>
        {children}
      </ScrollView>
    </SafeAreaView>
  );
}

const frame = StyleSheet.create({
  content: {
    flexGrow: 1,
    justifyContent: "center",
    maxWidth: 560,
    paddingHorizontal: 24,
    paddingVertical: 24,
    gap: 32,
  },
  masthead: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    paddingBottom: 16,
    gap: 12,
  },
  mark: { width: 40, height: 40, borderRadius: 8 },
});
