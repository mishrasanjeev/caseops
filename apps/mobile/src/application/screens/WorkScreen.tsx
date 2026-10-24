import { useState } from "react";
import { ScrollView, Text } from "react-native";
import { NativeButton, NativeSegments } from "../../components/NativeControls";
import { Empty, ResourceView } from "../../components/Content";
import { colors, styles } from "../../components/theme";
import type { Today, WorkItem } from "../../domain/contracts";
import type { Resource } from "../useResource";

import { WorkRow } from "./WorkRow";

export function WorkScreen({
  resource,
  reload,
  openWork,
}: {
  resource: Resource<Today>;
  reload: () => void;
  openWork: (item: WorkItem) => void;
}) {
  const [segment, setSegment] = useState("due");
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Text
        testID="screen-work"
        accessibilityRole="header"
        style={styles.title}
      >
        Work
      </Text>
      <NativeSegments
        label="Work view"
        value={segment}
        onChange={setSegment}
        options={[
          { value: "due", label: "Due work" },
          { value: "reviews", label: "Reviews" },
        ]}
      />
      <Text style={styles.muted}>
        Visible work, not a personal assignment queue
      </Text>
      <ResourceView resource={resource} reload={reload}>
        {(today) => {
          const stream = today.streams.find(
            (item) =>
              item.key ===
              (segment === "due" ? "tasks_due_or_overdue" : "drafts_in_review"),
          )!;
          return (
            <>
              {stream.items.length ? (
                stream.items.map((item) => (
                  <WorkRow
                    key={item.id}
                    item={item}
                    onPress={() => openWork(item)}
                  />
                ))
              ) : (
                <Empty
                  title="No items returned"
                  message="This bounded feed returned no work in the selected stream."
                />
              )}
              {stream.truncated ? (
                <Text style={[styles.body, { color: colors.warning }]}>
                  More items exist than this feed returns. Open their matter in
                  the web workspace.
                </Text>
              ) : null}
              <Text style={styles.label}>
                {segment === "due"
                  ? "Undated tasks and a complete assignment queue have no mobile read contract. Matter-scoped tasks remain available in each matter."
                  : "Drafts open at the exact server-owned current version. Formal review and legal decisions remain in the web workspace."}
              </Text>
              <NativeButton label="Reload work" onPress={reload} secondary />
            </>
          );
        }}
      </ResourceView>
    </ScrollView>
  );
}
