import { ScrollView, Text, View } from "react-native";
import { NativeButton } from "../../components/NativeControls";
import { ResourceView } from "../../components/Content";
import { colors, styles } from "../../components/theme";
import { displayDay } from "../../domain/contracts";
import type { Today, WorkItem } from "../../domain/contracts";
import type { Resource } from "../useResource";

import { WorkRow } from "./WorkRow";

const streamLabels = {
  hearings_next_7d: "Upcoming hearings",
  tasks_due_or_overdue: "Due and overdue tasks",
  drafts_in_review: "Drafts in review",
  deadlines_next_7d: "Upcoming deadlines",
};

export function TodayScreen({
  resource,
  reload,
  openWork,
  search,
}: {
  resource: Resource<Today>;
  reload: () => void;
  openWork: (item: WorkItem) => void;
  search: () => void;
}) {
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Text
        testID="screen-today"
        accessibilityRole="header"
        style={styles.title}
      >
        Today
      </Text>
      <Text style={styles.muted}>Visible work</Text>
      <NativeButton label="Search matters" onPress={search} secondary />
      <ResourceView resource={resource} reload={reload}>
        {(value) => (
          <>
            <Text style={styles.body}>{displayDay(value.today)}</Text>
            {value.streams.map((stream) => (
              <View key={stream.key} style={{ gap: 8 }}>
                <Text accessibilityRole="header" style={styles.heading}>
                  {streamLabels[stream.key]}
                </Text>
                {stream.items.length ? (
                  stream.items.map((item) => (
                    <WorkRow
                      key={item.id}
                      item={item}
                      onPress={() => openWork(item)}
                    />
                  ))
                ) : (
                  <Text style={styles.muted}>
                    No items returned in this stream.
                  </Text>
                )}
                {stream.truncated ||
                (stream.total !== null &&
                  stream.total > stream.items.length) ? (
                  <Text style={[styles.body, { color: colors.warning }]}>
                    Showing {stream.items.length} of {stream.total ?? "more"}{" "}
                    items. This feed has no continuation; use the matter
                    workspace for full context.
                  </Text>
                ) : stream.truncated === null ? (
                  <Text style={styles.label}>
                    Stream completeness was not supplied by the server.
                  </Text>
                ) : null}
              </View>
            ))}
            {value.ipActions > 0 ? (
              <Text style={styles.muted}>
                IP coverage actions require the web workspace.
              </Text>
            ) : null}
            <Text style={styles.label}>
              Hearing source freshness is not supplied by this feed. Contract
              obligations and the full assignment queue are not included.
            </Text>
            <NativeButton label="Reload Today" onPress={reload} secondary />
          </>
        )}
      </ResourceView>
    </ScrollView>
  );
}
