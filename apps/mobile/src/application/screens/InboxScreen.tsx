import { useEffect, useMemo, useRef, useState } from "react";
import type { RefObject } from "react";
import { ScrollView, Text, View } from "react-native";
import { NativeButton, NativeSegments } from "../../components/NativeControls";
import { Empty, ResourceView } from "../../components/Content";
import { styles } from "../../components/theme";
import {
  advanceInboxPage,
  createInboxAction,
  createInboxRepository,
  createInboxViewLease,
} from "../../domain/recipient-inbox";
import type {
  InboxPage,
  InboxState,
  InboxTarget,
  InboxView,
  InboxRepository,
  InboxViewLease,
  InboxFrame,
} from "../../domain/recipient-inbox";
import type { AuthorizedRequest } from "../../domain/repository";
import { useResource } from "../useResource";
import type { LeaveGuard } from "../types";

export function InboxScreen({
  request,
  openTarget,
  guard,
}: {
  request: AuthorizedRequest;
  openTarget: (target: InboxTarget) => void;
  guard: RefObject<LeaveGuard | null>;
}) {
  const repository = useMemo(() => createInboxRepository(request), [request]);
  const [view, setView] = useState<InboxView>("active");
  const [history, setHistory] = useState<(string | null)[]>([null]);
  const [message, setMessage] = useState<string | null>(null);
  const lease = useMemo(() => createInboxViewLease(), []);
  const after = history[history.length - 1];
  const { resource, reload } = useResource(
    `${view}:${after ?? "first"}`,
    (signal) => repository.page(view, after, signal),
  );
  const frame = lease.bind(
    `${view}:${after ?? "first"}`,
    resource.state === "ready" ? resource.data : null,
  );
  useEffect(() => {
    const owned: LeaveGuard = (leave) => {
      if (lease.leave()) leave();
      else if (lease.busy())
        setMessage(
          "Wait for the notification change to finish before leaving.",
        );
    };
    guard.current = owned;
    return () => {
      lease.dispose();
      if (guard.current === owned) guard.current = null;
    };
  }, [guard, lease]);
  const navigate = (action: () => void) => {
    lease.navigate(frame, () => {
      setMessage(null);
      action();
    });
  };
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <Text
        testID="screen-inbox"
        accessibilityRole="header"
        style={styles.title}
      >
        Notifications
      </Text>
      <Text style={styles.muted}>
        Delivered hearing and IP renewal alerts that you can currently open.
        This view does not include every email or background job.
      </Text>
      <NativeSegments
        label="Notification view"
        value={view}
        onChange={(value) =>
          navigate(() => {
            setView(value as InboxView);
            setHistory([null]);
          })
        }
        options={[
          { value: "active", label: "Active" },
          { value: "dismissed", label: "Dismissed" },
        ]}
      />
      {message ? (
        <Text accessibilityRole="alert" style={styles.body}>
          {message}
        </Text>
      ) : null}
      <ResourceView resource={resource} reload={() => navigate(reload)}>
        {(page) => (
          <InboxPageContent
            key={`${view}:${after ?? "first"}`}
            page={page}
            repository={repository}
            lease={lease}
            frame={frame}
            openTarget={(target) => navigate(() => openTarget(target))}
            reload={reload}
            report={setMessage}
          />
        )}
      </ResourceView>
      {resource.state === "ready" ? (
        <>
          {history.length > 1 ? (
            <NativeButton
              label="Newer notification page"
              secondary
              onPress={() =>
                navigate(() => setHistory((current) => current.slice(0, -1)))
              }
            />
          ) : null}
          {resource.data.nextCursor ? (
            <NativeButton
              label="Older notification page"
              secondary
              onPress={() =>
                navigate(() => {
                  try {
                    setHistory(
                      advanceInboxPage(history, resource.data.nextCursor!),
                    );
                  } catch {
                    setMessage("Return to the first page to continue.");
                  }
                })
              }
            />
          ) : null}
          <NativeButton
            label="Reload notifications"
            secondary
            onPress={() =>
              navigate(() => {
                setHistory([null]);
                reload();
              })
            }
          />
        </>
      ) : null}
      <Text style={styles.label}>
        Notifications are reminders. Open the current source record to confirm
        its dates and status. Push notifications are not enabled in this build.
      </Text>
    </ScrollView>
  );
}

function InboxPageContent({
  page,
  repository,
  lease,
  frame,
  openTarget,
  reload,
  report,
}: {
  page: InboxPage;
  repository: InboxRepository;
  lease: InboxViewLease;
  frame: InboxFrame;
  openTarget: (target: InboxTarget) => void;
  reload: () => void;
  report: (message: string) => void;
}) {
  const action = useMemo(
    () => createInboxAction(repository, { lease, frame }),
    [repository, page, lease, frame],
  );
  const [busy, setBusy] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      action.dispose();
    };
  }, [action]);
  const change = async (
    record: InboxPage["items"][number],
    next: InboxState,
  ) => {
    if (!active.current || lease.busy() || action.blocked()) return;
    setBusy(true);
    try {
      const result = await action.change(record, next);
      if (!active.current) return;
      if (result.state === "confirmed") {
        report("Notification status saved. Loading its current state.");
        reload();
      } else if (result.state === "unverified") {
        setBlocked(true);
        report(
          "The status change could not be confirmed. Reload notifications before making another change.",
        );
      }
    } finally {
      if (active.current) setBusy(false);
    }
  };
  return (
    <>
      {!page.items.length ? (
        <Empty
          title={
            page.historyExhausted
              ? "No current alerts on this page"
              : "No current alerts among these records"
          }
          message={
            page.historyExhausted
              ? "You have reached the end of this notification history."
              : "Older records are available on the next page."
          }
        />
      ) : null}
      {page.items.map((record) => (
        <View
          key={record.id}
          testID={`notification-${record.id}`}
          style={[styles.divider, { gap: 12, paddingBottom: 16 }]}
        >
          <Text accessibilityRole="header" style={styles.heading}>
            {record.title}
          </Text>
          <Text style={styles.body}>
            {record.targetLabel || "Source title not recorded"}
          </Text>
          {record.body ? <Text style={styles.body}>{record.body}</Text> : null}
          <Text style={styles.label}>
            {record.status} · {new Date(record.createdAt).toLocaleString()}
          </Text>
          <NativeButton
            label="Open source record"
            secondary
            disabled={busy}
            onPress={() => openTarget(record.target)}
          />
          {record.status !== "read" ? (
            <NativeButton
              label="Mark as read"
              secondary
              disabled={busy || blocked}
              onPress={() => void change(record, "read")}
            />
          ) : null}
          {record.status !== "dismissed" ? (
            <NativeButton
              label="Dismiss notification"
              secondary
              disabled={busy || blocked}
              onPress={() => void change(record, "dismissed")}
            />
          ) : (
            <NativeButton
              label="Restore notification"
              secondary
              disabled={busy || blocked}
              onPress={() => void change(record, "unread")}
            />
          )}
        </View>
      ))}
    </>
  );
}
