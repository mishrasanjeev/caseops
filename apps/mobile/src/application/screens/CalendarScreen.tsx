import { useState } from "react";
import { ScrollView, Text, View } from "react-native";
import {
  NativeButton,
  NativeProgress,
  NativeSegments,
} from "../../components/NativeControls";
import { NativeDatePicker } from "../../components/NativeDatePicker";
import { Empty, RecordRow } from "../../components/Content";
import { colors, styles } from "../../components/theme";
import { StableTextInput } from "../../components/StableTextInput";
import { dateOnly, displayDay, localDay } from "../../domain/contracts";
import { adjacentCalendarDay } from "../../domain/calendar-date";
import type { MatterRef } from "../../domain/contracts";
import type { Repository } from "../../domain/repository";
import type { SourceRef } from "../../domain/source-records";
import { useResource } from "../useResource";

export type CalendarScreenProps = {
  repository: Repository;
  active: boolean;
  openMatter: (matter: MatterRef) => void;
  openSource?: (source: SourceRef) => void;
};

export function CalendarScreen({
  repository,
  active,
  openMatter,
  openSource,
}: CalendarScreenProps) {
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
    dateOnly(next);
    setDay(next);
    setInput(next);
    setLimit(50);
    setError(null);
  };
  const previousDay = adjacentCalendarDay(day, -1);
  const nextDay = adjacentCalendarDay(day, 1);
  const previousWeek = adjacentCalendarDay(day, -7);
  const nextWeek = adjacentCalendarDay(day, 7);
  const goToDate = () => {
    try {
      select(dateOnly(input));
    } catch {
      setError("Enter a valid date as YYYY-MM-DD.");
    }
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
      <Text
        testID="calendar-selected-day"
        accessibilityRole="header"
        accessibilityLiveRegion="polite"
        style={styles.heading}
      >
        {displayDay(day)}
      </Text>
      <NativeDatePicker
        value={day}
        onChange={select}
        disabled={!active}
        onInvalidDate={() =>
          setError(
            "The selected date could not be read. Enter a valid date as YYYY-MM-DD.",
          )
        }
      />
      <View style={styles.row}>
        <View style={{ flex: 1, minWidth: 100 }}>
          <NativeButton
            testID="previous-day"
            label="Previous day"
            disabled={!active || !previousDay}
            onPress={() => {
              if (previousDay) select(previousDay);
            }}
            secondary
          />
        </View>
        <View style={{ flex: 1, minWidth: 100 }}>
          <NativeButton
            testID="next-day"
            label="Next day"
            disabled={!active || !nextDay}
            onPress={() => {
              if (nextDay) select(nextDay);
            }}
            secondary
          />
        </View>
      </View>
      <View style={styles.row}>
        <View style={{ flex: 1, minWidth: 100 }}>
          <NativeButton
            testID="previous-week"
            label="Previous week"
            disabled={!active || !previousWeek}
            onPress={() => {
              if (previousWeek) select(previousWeek);
            }}
            secondary
          />
        </View>
        <View style={{ flex: 1, minWidth: 100 }}>
          <NativeButton
            testID="next-week"
            label="Next week"
            disabled={!active || !nextWeek}
            onPress={() => {
              if (nextWeek) select(nextWeek);
            }}
            secondary
          />
        </View>
      </View>
      <Text style={styles.label}>Date (YYYY-MM-DD)</Text>
      <StableTextInput
        testID="calendar-date-input"
        accessibilityLabel="Agenda date, YYYY-MM-DD"
        value={input}
        onChangeText={setInput}
        maxLength={10}
        style={styles.field}
        autoCapitalize="none"
        autoCorrect={false}
        editable={active}
        returnKeyType="go"
        onSubmitEditing={goToDate}
      />
      <NativeButton
        testID="calendar-go-date"
        label="Go to date"
        disabled={!active}
        onPress={goToDate}
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
      {agenda.resource.state === "loading" ? (
        <View accessibilityLiveRegion="polite" style={{ gap: 8 }}>
          <NativeProgress />
          <Text style={styles.muted}>Loading agenda</Text>
        </View>
      ) : agenda.resource.state === "error" ? (
        <View style={{ gap: 8 }}>
          <Text accessibilityRole="alert" style={styles.heading}>
            {agenda.resource.error.title}
          </Text>
          <Text style={styles.body}>{agenda.resource.error.message}</Text>
        </View>
      ) : (
        (() => {
          const events = agenda.resource.data;
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
                matching.slice(0, limit).map((event) => (
                  <RecordRow
                    key={event.id}
                    testID={`event-${event.id}`}
                    title={event.title}
                    subtitle={`${event.matter.matter_code} · ${event.matter.title}`}
                    meta={[
                      displayDay(event.occurs_on),
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
                        ? openSource
                          ? "IP docket"
                          : "IP docket: open in web workspace"
                        : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                    onPress={
                      event.ip_docket_id && openSource
                        ? () =>
                            openSource({
                              kind: "ip_docket",
                              id: event.ip_docket_id!,
                            })
                        : !event.ip_docket_id && event.matter.id
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
            </>
          );
        })()
      )}
      <NativeButton
        testID="reload"
        label="Reload agenda"
        onPress={agenda.reload}
        disabled={!active || agenda.resource.state === "loading"}
        secondary
      />
    </ScrollView>
  );
}
