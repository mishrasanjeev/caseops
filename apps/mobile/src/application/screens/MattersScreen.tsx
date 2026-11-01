import { useState } from "react";
import { ScrollView, Text } from "react-native";
import { NativeButton } from "../../components/NativeControls";
import { Empty, RecordRow, ResourceView } from "../../components/Content";
import { colors, styles } from "../../components/theme";
import { StableTextInput } from "../../components/StableTextInput";
import { displayDay } from "../../domain/contracts";
import type { MatterRef } from "../../domain/contracts";
import type { Repository } from "../../domain/repository";
import { useResource } from "../useResource";

export function MattersScreen({
  repository,
  active,
  openMatter,
}: {
  repository: Repository;
  active: boolean;
  openMatter: (matter: MatterRef) => void;
}) {
  const [input, setInput] = useState(""),
    [query, setQuery] = useState(""),
    [cursors, setCursors] = useState<(string | null)[]>([null]);
  const cursor = cursors[cursors.length - 1];
  const page = useResource(
    `matters:${query}:${cursor ?? ""}`,
    (signal) => repository.matters(query, cursor, signal),
    active,
  );
  return (
    <ScrollView
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={styles.content}
    >
      <Text
        testID="screen-matters"
        accessibilityRole="header"
        style={styles.title}
      >
        Matters
      </Text>
      <Text style={styles.label}>
        Search permitted matter identifiers or title
      </Text>
      <StableTextInput
        testID="matter-search"
        accessibilityLabel="Search matters"
        value={input}
        onChangeText={setInput}
        maxLength={200}
        placeholder="Matter, case, filing or CNR"
        placeholderTextColor={colors.muted}
        returnKeyType="search"
        onSubmitEditing={() => {
          setCursors([null]);
          setQuery(input.trim());
          page.reload();
        }}
        style={styles.field}
      />
      <NativeButton
        label="Search"
        testID="matter-search-submit"
        onPress={() => {
          setCursors([null]);
          setQuery(input.trim());
          page.reload();
        }}
        secondary
      />
      <ResourceView resource={page.resource} reload={page.reload}>
        {(value) => (
          <>
            {query ? (
              <Text style={styles.muted}>Results for: {query}</Text>
            ) : null}
            {value.matters.length ? (
              value.matters.map((matter) => (
                <RecordRow
                  key={matter.id}
                  testID={`matter-row-${matter.id}`}
                  title={matter.title}
                  subtitle={matter.matter_code}
                  meta={`${matter.status} · ${matter.next_hearing_on ? `Next hearing ${displayDay(matter.next_hearing_on)}` : "Next hearing not recorded"}`}
                  onPress={() => openMatter(matter)}
                />
              ))
            ) : (
              <Empty
                title="No matching matters"
                message="No permitted records matched this search."
              />
            )}
            <Text style={styles.label}>
              Page {cursors.length}. Up to 25 records per page.
            </Text>
            {value.next_cursor ? (
              <NativeButton
                label="Next page"
                onPress={() =>
                  setCursors((previous) => [...previous, value.next_cursor])
                }
              />
            ) : null}
            {cursors.length > 1 ? (
              <NativeButton
                label="Previous page"
                onPress={() => setCursors((previous) => previous.slice(0, -1))}
                secondary
              />
            ) : null}
          </>
        )}
      </ResourceView>
    </ScrollView>
  );
}
