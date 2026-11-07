import { useLayoutEffect, useRef, useState } from "react";
import { Keyboard, ScrollView, Text } from "react-native";
import { NativeButton } from "../../components/NativeControls";
import { Empty, RecordRow, ResourceView } from "../../components/Content";
import { colors, styles } from "../../components/theme";
import { StableTextInput } from "../../components/StableTextInput";
import { ContractError, displayDay } from "../../domain/contracts";
import type { MatterRef } from "../../domain/contracts";
import type { Repository } from "../../domain/repository";
import { useResource } from "../useResource";

const CURSOR_HISTORY_LIMIT = 100;
type MatterVisit = {
  query: string;
  history: readonly (string | null)[];
  firstPage: number;
  version: number;
  active: boolean;
};

export function MattersScreen({
  repository,
  active,
  openMatter,
}: {
  repository: Repository;
  active: boolean;
  openMatter: (matter: MatterRef) => void;
}) {
  const [input, setInput] = useState("");
  const [visit, setVisit] = useState<MatterVisit>({
    query: "",
    history: [null],
    firstPage: 1,
    version: 0,
    active,
  });
  // React restarts this render when tab visibility changes. A fresh visit
  // prevents the previous authorized result flashing on the way back in.
  if (visit.active !== active)
    setVisit({ ...visit, active, version: visit.version + 1 });
  const committed = useRef<MatterVisit | null>(null);
  useLayoutEffect(() => {
    committed.current = visit;
    return () => {
      committed.current = null;
    };
  }, [visit]);
  const { query, history, firstPage } = visit;
  const cursor = history[history.length - 1];
  const pageNumber = firstPage + history.length - 1;
  const page = useResource(
    `matters:${visit.version}`,
    async (signal) => {
      const result = await repository.matters(query, cursor, signal);
      const next = result.next_cursor;
      if (
        next !== null &&
        (!next.trim() ||
          next.length > 8000 ||
          /[\x00-\x1f\x7f]/.test(next) ||
          history.includes(next))
      )
        throw new ContractError("matter continuation");
      return result;
    },
    active && visit.active,
  );
  const move = (
    change: Partial<Pick<MatterVisit, "query" | "history" | "firstPage">>,
    dismissKeyboard = false,
  ) => {
    if (!visit.active || committed.current !== visit) return;
    // Consume the displayed visit before any second press can use it.
    committed.current = null;
    setVisit((current) =>
      current === visit
        ? { ...current, ...change, version: current.version + 1 }
        : current,
    );
    if (dismissKeyboard) Keyboard.dismiss();
  };
  const search = () =>
    move({ query: input.trim(), history: [null], firstPage: 1 }, true);
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
        // Identifiers are codes: shift and correction would rewrite them.
        autoCapitalize="none"
        autoCorrect={false}
        spellCheck={false}
        onSubmitEditing={search}
        style={styles.field}
      />
      <NativeButton
        label="Search"
        testID="matter-search-submit"
        onPress={search}
        secondary
      />
      <ResourceView resource={page.resource} reload={() => move({})}>
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
              Page {pageNumber}. Up to 25 records per page.
            </Text>
            {value.next_cursor !== null ? (
              <NativeButton
                label="Next page"
                onPress={() => {
                  const next = value.next_cursor;
                  if (next === null) return;
                  const drop = history.length === CURSOR_HISTORY_LIMIT ? 1 : 0;
                  move({
                    history: [...history.slice(drop), next],
                    firstPage: firstPage + drop,
                  });
                }}
              />
            ) : null}
            {history.length > 1 ? (
              <NativeButton
                label="Previous page"
                onPress={() => move({ history: history.slice(0, -1) })}
                secondary
              />
            ) : firstPage > 1 ? (
              <NativeButton
                label="First page"
                onPress={() => move({ history: [null], firstPage: 1 })}
                secondary
              />
            ) : null}
          </>
        )}
      </ResourceView>
    </ScrollView>
  );
}
