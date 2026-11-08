import { useLayoutEffect, useRef, useState } from "react";
import { Keyboard, ScrollView, Text } from "react-native";
import { NativeButton } from "../../components/NativeControls";
import { Empty, RecordRow, ResourceView } from "../../components/Content";
import { colors, styles } from "../../components/theme";
import { StableTextInput } from "../../components/StableTextInput";
import { displayDay } from "../../domain/contracts";
import type { MatterRef } from "../../domain/contracts";
import {
  advanceCursorHistory,
  continuationCursor,
} from "../../domain/cursor-history";
import { readFailure } from "../../domain/repository";
import type { ReadFailure, Repository } from "../../domain/repository";
import { useResource } from "../useResource";

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
  // A refused Next belongs to the visit it was pressed on; any move clears it.
  const [refused, setRefused] = useState<{
    visit: MatterVisit;
    failure: ReadFailure;
  } | null>(null);
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
      if (result.next_cursor !== null)
        continuationCursor(result.next_cursor, "matter continuation");
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
  // A repeated continuation is refused when Next is pressed, so the rows the
  // server authorized for this page stay readable until then.
  const next = (continuation: string) => {
    if (!visit.active || committed.current !== visit) return;
    let advanced: (string | null)[];
    try {
      advanced = advanceCursorHistory(
        history,
        continuation,
        "matter continuation",
      );
    } catch (error) {
      setRefused({ visit, failure: readFailure(error) });
      return;
    }
    move({
      history: advanced,
      firstPage: firstPage + history.length + 1 - advanced.length,
    });
  };
  const search = () =>
    move({ query: input.trim(), history: [null], firstPage: 1 }, true);
  const resource =
    refused?.visit === visit
      ? ({ state: "error", error: refused.failure } as const)
      : page.resource;
  const hasPrevious = history.length > 1;
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
      <ResourceView resource={resource} reload={() => move({})}>
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
                  if (value.next_cursor !== null) next(value.next_cursor);
                }}
              />
            ) : null}
          </>
        )}
      </ResourceView>
      {/* Outside the resource so a failed page can still be left. */}
      {hasPrevious ? (
        <NativeButton
          label="Previous page"
          onPress={() => move({ history: history.slice(0, -1) })}
          secondary
        />
      ) : null}
      {pageNumber > (hasPrevious ? 2 : 1) ? (
        <NativeButton
          label="First page"
          onPress={() => move({ history: [null], firstPage: 1 })}
          secondary
        />
      ) : null}
    </ScrollView>
  );
}
