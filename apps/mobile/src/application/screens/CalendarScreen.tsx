import { useState } from "react";
import { ScrollView, Text, TextInput, View } from "react-native";
import { NativeButton, NativeSegments } from "../../components/NativeControls";
import { Empty, RecordRow, ResourceView } from "../../components/Content";
import { colors, styles } from "../../components/theme";
import {
  dateOnly,
  displayDay,
  localDay,
  shiftDay,
} from "../../domain/contracts";
import type { MatterRef } from "../../domain/contracts";
import type { Repository } from "../../domain/repository";
import { useResource } from "../useResource";

export function CalendarScreen({
  repository,
  active,
  openMatter,
}: {
  repository: Repository;
  active: boolean;
  openMatter: (matter: MatterRef) => void;
}) {
  const [day, setDay] = useState(localDay()),
    [input, setInput] = useState(day),
    [error, setError] = useState<string | null>(null),
    [kind, setKind] = useState("all"),
    [limit, setLimit] = useState(50);
  const agenda = useResource(
    `agenda:${day}`,
    (signal) => repository.agenda(day, signal),
    active,
  );
  const select = (next: string) => {
    setDay(next);
    setInput(next);
    setLimit(50);
    setError(null);
  };
  return (
    <ScrollView
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={styles.content}
    >
      <Text
        testID="screen-calendar"
        accessibilityRole="header"
        style={styles.title}
      >
        Calendar
      </Text>
      <Text style={styles.heading}>{displayDay(day)}</Text>
      <View style={styles.row}>
        <View style={{ flex: 1, minWidth: 100 }}>
          <NativeButton
            label="Previous day"
            onPress={() => select(shiftDay(day, -1))}
            secondary
          />
        </View>
        <View style={{ flex: 1, minWidth: 100 }}>
          <NativeButton
            label="Next day"
            onPress={() => select(shiftDay(day, 1))}
            secondary
          />
        </View>
      </View>
      <View style={styles.row}>
        <View style={{ flex: 1, minWidth: 100 }}>
          <NativeButton
            label="Previous week"
            onPress={() => select(shiftDay(day, -7))}
            secondary
          />
        </View>
        <View style={{ flex: 1, minWidth: 100 }}>
          <NativeButton
            label="Next week"
            onPress={() => select(shiftDay(day, 7))}
            secondary
          />
        </View>
      </View>
      <Text style={styles.label}>Date (YYYY-MM-DD)</Text>
      <TextInput
        accessibilityLabel="Agenda date, YYYY-MM-DD"
        value={input}
        onChangeText={setInput}
        maxLength={10}
        style={styles.field}
        autoCapitalize="none"
      />
      <NativeButton
        label="Go to date"
        onPress={() => {
          try {
            select(dateOnly(input));
          } catch {
            setError("Enter a valid date as YYYY-MM-DD.");
          }
        }}
        secondary
      />
      {error ? (
        <Text
          accessibilityRole="alert"
          style={[styles.body, { color: colors.danger }]}
        >
          {error}
        </Text>
      ) : null}
      <NativeSegments
        label="Event type"
        value={kind}
        options={[
          { value: "all", label: "All" },
          { value: "hearing", label: "Hearings" },
          { value: "task_date", label: "Tasks" },
          { value: "due", label: "Deadlines" },
        ]}
        onChange={(value) => {
          setKind(value);
          setLimit(50);
        }}
      />
      <ResourceView resource={agenda.resource} reload={agenda.reload}>
        {(events) => {
          const matching = events.filter(
            (event) =>
              kind === "all" ||
              event.kind === kind ||
              (kind === "due" &&
                !["hearing", "task_date", "task"].includes(event.kind)) ||
              (kind === "task_date" && event.kind === "task"),
          );
          return (
            <>
              {matching.length ? (
                matching
                  .slice(0, limit)
                  .map((event) => (
                    <RecordRow
                      key={event.id}
                      title={event.title}
                      subtitle={`${event.matter.matter_code} · ${event.matter.title}`}
                      meta={[
                        event.kind.replaceAll("_", " "),
                        event.time_status === "exact"
                          ? [
                              event.hearing_time,
                              event.timezone || "Timezone not supplied",
                            ]
                              .filter(Boolean)
                              .join(" ")
                          : event.session_label || "Time not published",
                        event.detail,
                        event.ip_docket_id
                          ? "IP docket: open in web workspace"
                          : null,
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                      onPress={
                        !event.ip_docket_id && event.matter.id
                          ? () => openMatter(event.matter)
                          : undefined
                      }
                    />
                  ))
              ) : (
                <Empty
                  title="No events returned"
                  message="There are no permitted events for this date and filter in the calendar feed."
                />
              )}
              {matching.length > limit ? (
                <NativeButton
                  label={`Show next ${Math.min(50, matching.length - limit)} events`}
                  onPress={() => setLimit((value) => value + 50)}
                  secondary
                />
              ) : null}
              <Text style={styles.label}>
                Date-only legal dates remain on their recorded day. Contract
                obligations are not included in this feed.
              </Text>
              <NativeButton
                label="Reload agenda"
                onPress={agenda.reload}
                secondary
              />
            </>
          );
        }}
      </ResourceView>
    </ScrollView>
  );
}
