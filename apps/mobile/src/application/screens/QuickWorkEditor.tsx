import { useEffect, useMemo, useSyncExternalStore } from "react";
import type { RefObject } from "react";
import {
  Alert,
  Platform,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { NativeButton, NativeSegments } from "../../components/NativeControls";
import { styles } from "../../components/theme";
import type { Matter } from "../../domain/contracts";
import {
  createQuickWorkController,
  hearingStatuses,
  taskStatuses,
} from "../../domain/quick-work";
import type { QuickTarget } from "../../domain/quick-work";
import type { Repository } from "../../domain/repository";
import type { LeaveGuard } from "../types";

export function QuickWorkEditor({
  repository,
  matter,
  target,
  capabilities,
  guard,
  onClose,
}: {
  repository: Repository;
  matter: Matter;
  target: QuickTarget;
  capabilities: readonly string[];
  guard: RefObject<LeaveGuard | null>;
  onClose: () => void;
}) {
  const controller = useMemo(
    () =>
      createQuickWorkController(
        repository.quickWork,
        matter,
        target,
        capabilities,
      ),
    [repository, matter, target, capabilities],
  );
  const state = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  useEffect(() => {
    void controller.load();
    return () => controller.dispose();
  }, [controller]);
  useEffect(() => {
    const blocked = () =>
      Alert.alert(
        "Save in progress",
        "Wait for the current operation before leaving.",
      );
    const leaveGuard: LeaveGuard = (leave) => {
      const decision = controller.leaveDecision();
      if (decision === "blocked") {
        blocked();
        return;
      }
      if (decision === "closed") return;
      if (decision === "confirm") {
        const current = controller.getSnapshot();
        Alert.alert(
          current.outcome?.state === "unknown"
            ? "Save outcome unknown"
            : "Leave editor?",
          current.outcome?.state === "unknown"
            ? "This request may already be saved. Leaving does not cancel or replay it. Review current Matter work before starting anything new."
            : "Unsaved fields are held only in memory. Leaving discards them.",
          [
            { text: "Stay", style: "cancel" },
            {
              text: "Leave editor",
              style: "destructive",
              onPress: () => {
                if (
                  !controller.leave(true, leave) &&
                  controller.leaveDecision() === "blocked"
                )
                  blocked();
              },
            },
          ],
        );
      } else controller.leave(false, leave);
    };
    guard.current = leaveGuard;
    return () => {
      if (guard.current === leaveGuard) guard.current = null;
    };
  }, [controller, guard]);
  const task = target.kind === "task";
  const busy = state.phase === "loading" || state.phase === "saving";
  const editing = state.phase === "editing";
  const field = (
    key: string,
    label: string,
    maximum = 255,
    multiline = false,
    editable = true,
  ) => (
    <View key={key} style={{ gap: 4 }}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        testID={`quick-${key}`}
        accessibilityLabel={label}
        value={state.fields[key] || ""}
        onChangeText={(value) => controller.change(key, value)}
        editable={editing && editable}
        maxLength={maximum}
        multiline={multiline}
        autoCapitalize="none"
        autoCorrect={false}
        style={[styles.field, multiline && { minHeight: 100 }]}
      />
    </View>
  );
  const select = (key: string, label: string, values: readonly string[]) =>
    editing ? (
      <NativeSegments
        label={label}
        value={state.fields[key]}
        options={values.map((value) => ({
          value,
          label: value.replaceAll("_", " "),
        }))}
        onChange={(value) => controller.change(key, value)}
      />
    ) : (
      <Text style={styles.label}>
        {label}: {state.fields[key]?.replaceAll("_", " ")}
      </Text>
    );
  return (
    <ScrollView
      testID="quick-work-editor"
      automaticallyAdjustKeyboardInsets={Platform.OS === "ios"}
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={styles.content}
    >
      <Text accessibilityRole="header" style={styles.title}>
        {target.id ? "Edit" : "Add"} {task ? "task" : "hearing"}
      </Text>
      {state.contentAvailable && state.matter ? (
        <>
          <Text style={styles.label}>{state.matter.matter_code}</Text>
          <Text style={styles.heading}>{state.matter.title}</Text>
        </>
      ) : null}
      {busy ? (
        <Text accessibilityLiveRegion="polite" style={styles.muted}>
          {state.phase === "saving"
            ? "Checking current state and saving once"
            : "Loading current work"}
        </Text>
      ) : null}
      {!state.contentAvailable ? (
        <Text testID="quick-content-unavailable" style={styles.muted}>
          Current work is hidden until access and record state can be verified.
        </Text>
      ) : task ? (
        <>
          {field("title", "Task title")}
          {field("description", "Description", 4000, true)}
          {field("due_on", "Due date (YYYY-MM-DD, optional)", 10)}
          {select("status", "Task status", taskStatuses)}
          {select("priority", "Priority", ["low", "medium", "high", "urgent"])}
          <Text style={styles.muted}>
            {target.id
              ? `Responsible person: ${state.record?.owner_name || "Unassigned"}. Assignment is unchanged by this editor.`
              : "New task is unassigned. Assignment can be reviewed in the workspace."}
          </Text>
        </>
      ) : (
        <>
          {field("forum_name", "Forum", 255, false, !target.id)}
          {field("purpose", "Hearing purpose", 255, false, !target.id)}
          {field("judge_name", "Judge (optional)", 255, false, !target.id)}
          {field("hearing_on", "Hearing date (YYYY-MM-DD)", 10)}
          {select("status", "Hearing status", hearingStatuses)}
          {field("outcome_note", "Outcome note (optional)", 4000, true)}
          {select("time_status", "Published time", [
            "time_not_published",
            "session",
            "exact",
          ])}
          {state.fields.time_status === "exact"
            ? field("hearing_time", "Local hearing time (HH:MM)", 32)
            : null}
          {state.fields.time_status === "session"
            ? field("session_label", "Session label", 80)
            : null}
          {field("timezone", "IANA timezone (for example Asia/Kolkata)", 64)}
          {target.id && state.fields.status === "completed"
            ? select(
                "create_follow_up",
                "Create follow-up task on completion",
                ["yes", "no"],
              )
            : null}
          <Text style={styles.muted}>
            {target.id
              ? `Forum, purpose and judge are read-only here. Existing reminder channels: ${state.record?.reminderChannels?.join(", ") || "none recorded"}. Rescheduling preserves this plan; no channels are added. Completion may create the follow-up task you selected; verify Matter work.`
              : "No reminders or notifications are requested by this editor. Email, SMS, WhatsApp and in-app channels are disabled in this new hearing plan."}{" "}
            Legal dates remain on their recorded day.
          </Text>
        </>
      )}
      {state.outcome ? (
        <View accessibilityLiveRegion="polite" style={{ gap: 12 }}>
          <Text
            accessibilityRole="alert"
            testID={`quick-${state.outcome.state}`}
            style={styles.heading}
          >
            {state.outcome.state === "confirmed"
              ? "Saved and reloaded"
              : state.outcome.state === "unknown"
                ? "Save outcome unknown"
                : state.outcome.state === "acknowledged"
                  ? "Server acknowledged save"
                  : "Save not completed"}
          </Text>
          <Text style={styles.body}>{state.outcome.message}</Text>
          {state.reviewError ? (
            <Text accessibilityRole="alert" style={styles.muted}>
              {state.reviewError}
            </Text>
          ) : null}
          {state.outcome.record ? (
            <Text style={styles.label}>
              Acknowledged ID: {state.outcome.record.id}
            </Text>
          ) : null}
          <NativeButton
            label="Reload current work"
            testID="quick-reload"
            onPress={() => {
              void controller.load();
            }}
            disabled={busy}
            secondary
          />
          {state.reviewed &&
          state.history.length < 10 &&
          state.outcome.state !== "confirmed" &&
          state.outcome.state !== "acknowledged" &&
          (target.id || state.outcome.state !== "unknown") ? (
            <NativeButton
              label="Start a new request from reloaded state"
              testID="quick-new-request"
              onPress={controller.beginNewRequest}
              secondary
            />
          ) : null}
          {state.reviewed && !target.id && state.outcome.state === "unknown" ? (
            <Text style={styles.muted}>
              A missing acknowledgement cannot identify a possibly created
              record. Return to Matter work and inspect the current records.
              This editor will not create it again.
            </Text>
          ) : null}
        </View>
      ) : (
        <NativeButton
          label={busy ? "Checking current work" : "Save once"}
          testID="quick-save"
          disabled={!editing || !state.dirty}
          onPress={() => {
            void controller.save();
          }}
        />
      )}
      {state.history.length ? (
        <Text testID="quick-attempt-history" style={styles.muted}>
          Earlier attempt outcomes retained in this editor:{" "}
          {state.history.map((entry) => entry.outcome.state).join(", ")}.
          Starting a new request does not replay or erase them.
        </Text>
      ) : null}
      <NativeButton
        label="Return to Matter work"
        testID="quick-close"
        onPress={() => {
          if (guard.current) guard.current(onClose);
        }}
        disabled={busy}
        secondary
      />
    </ScrollView>
  );
}
