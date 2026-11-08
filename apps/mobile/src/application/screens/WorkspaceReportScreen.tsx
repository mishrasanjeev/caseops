import { useEffect, useRef, useState, type RefObject } from "react";
import { Pressable, ScrollView, Text } from "react-native";
import * as Crypto from "expo-crypto";
import { NativeButton } from "../../components/NativeControls";
import { colors, styles, target } from "../../components/theme";
import { errorStatus } from "../../domain/repository";
import {
  workspaceReportReasons,
  type WorkspaceConductRepository,
  type WorkspaceReportReason,
  type WorkspaceReportTarget,
} from "../../domain/workspace-conduct";
import type { LeaveGuard } from "../types";

type Operation = Readonly<{ id: string; reason: WorkspaceReportReason }>;
type Phase = "ready" | "sending" | "uncertain" | "rejected" | "received";

export function WorkspaceReportScreen({
  subject,
  repository,
  guard,
  onClose,
}: {
  subject: WorkspaceReportTarget;
  repository: WorkspaceConductRepository;
  guard: RefObject<LeaveGuard | null>;
  onClose: () => void;
}) {
  const [phase, setPhase] = useState<Phase>("ready");
  const [reason, setReason] = useState<WorkspaceReportReason | null>(null);
  const current = useRef<{
    phase: Phase;
    reason: WorkspaceReportReason | null;
  }>({
    phase: "ready",
    reason: null,
  });
  const attempted = useRef<Operation | null>(null);
  const flight = useRef<AbortController | null>(null);
  const retired = useRef(false);
  useEffect(() => {
    retired.current = false;
    const leave: LeaveGuard = (next) => {
      if (!flight.current) next();
    };
    guard.current = leave;
    return () => {
      retired.current = true;
      flight.current?.abort();
      if (guard.current === leave) guard.current = null;
    };
  }, [guard]);

  const publish = (next: Phase) => {
    current.current.phase = next;
    setPhase(next);
  };
  const submit = async () => {
    const live = current.current;
    if (retired.current || flight.current || !live.reason) return;
    const previous = attempted.current;
    if (previous && live.phase !== "uncertain") return;
    const operation = previous ?? {
      id: Crypto.randomUUID(),
      reason: live.reason,
    };
    const abort = new AbortController();
    attempted.current = operation;
    flight.current = abort;
    publish("sending");
    try {
      await repository.report(
        operation.id,
        operation.reason,
        subject,
        abort.signal,
      );
      if (!abort.signal.aborted) publish("received");
    } catch (error) {
      if (abort.signal.aborted) return;
      const status = errorStatus(error);
      publish(
        status === 401 || status === 403 || status === 404 || status === 409
          ? "rejected"
          : "uncertain",
      );
    } finally {
      if (flight.current === abort) flight.current = null;
    }
  };

  const subjectLabel =
    subject.kind === "user" ? "workspace member" : subject.kind;
  return (
    <ScrollView
      contentContainerStyle={styles.content}
      testID="workspace-report"
    >
      <Text accessibilityRole="header" style={styles.title}>
        Report{" "}
        {subjectLabel === "workspace member"
          ? "a workspace member"
          : `this ${subjectLabel}`}
      </Text>
      <Text style={styles.body}>
        An authorized reviewer can check the report. This won’t delete matter
        records or change anyone’s access.
      </Text>
      {phase === "ready" ? (
        <>
          <Text accessibilityRole="header" style={styles.heading}>
            Choose a reason
          </Text>
          {workspaceReportReasons.map((item) => (
            <Pressable
              key={item.value}
              testID={`workspace-report-reason-${item.value}`}
              accessibilityRole="radio"
              accessibilityState={{ checked: reason === item.value }}
              onPress={() => {
                if (!attempted.current) {
                  current.current.reason = item.value;
                  setReason(item.value);
                }
              }}
              style={{
                minHeight: target,
                justifyContent: "center",
                padding: 12,
                borderRadius: 8,
                borderWidth: 1,
                borderColor: reason === item.value ? colors.brand : colors.line,
                backgroundColor:
                  reason === item.value ? colors.tonal : colors.surface,
              }}
            >
              <Text style={styles.body}>{item.label}</Text>
            </Pressable>
          ))}
        </>
      ) : (
        <Text
          accessibilityLiveRegion="polite"
          style={styles.body}
          testID="workspace-report-status"
        >
          {phase === "received"
            ? "Report received. It’s ready for review."
            : phase === "sending"
              ? "Sending your report…"
              : phase === "rejected"
                ? "The report couldn’t be accepted. Return to the workspace to check access."
                : "We couldn’t confirm your report. You can retry this same report without creating a duplicate."}
        </Text>
      )}
      {phase === "ready" || phase === "uncertain" ? (
        <NativeButton
          testID="workspace-report-submit"
          label={phase === "uncertain" ? "Retry this report" : "Send report"}
          disabled={!reason}
          onPress={() => void submit()}
        />
      ) : null}
      <NativeButton
        testID="workspace-report-close"
        label={phase === "ready" ? "Cancel" : "Back to workspace"}
        secondary
        disabled={phase === "sending"}
        onPress={() => {
          if (!retired.current && !flight.current) onClose();
        }}
      />
    </ScrollView>
  );
}
