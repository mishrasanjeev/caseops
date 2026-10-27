import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { AppState, ScrollView, Text, View } from "react-native";
import {
  NativeButton,
  NativeProgress,
  NativeSegments,
} from "../../components/NativeControls";
import { Empty, Fact, RecordRow, ResourceView } from "../../components/Content";
import { colors, styles } from "../../components/theme";
import { displayDay } from "../../domain/contracts";
import type { MatterRef, Today, WorkItem } from "../../domain/contracts";
import {
  createMatterWorkQueueController,
  createMatterWorkQueueRepository,
} from "../../domain/matter-work-queue";
import type {
  MatterWorkQueueController,
  QueueOwnership,
} from "../../domain/matter-work-queue";
import type { AuthorizedRequest } from "../../domain/repository";
import type { Resource } from "../useResource";
import { WorkRow } from "./WorkRow";

type QueueEntry = {
  request: AuthorizedRequest;
  subjectKey: string;
  controller: MatterWorkQueueController;
};
export function WorkScreen({
  resource,
  reload,
  openWork,
  openMatter,
  request,
  memberId,
  subjectKey,
  active,
  available,
  deactivate,
}: {
  resource: Resource<Today>;
  reload: () => void;
  openWork: (item: WorkItem) => void;
  openMatter: (matter: MatterRef) => void;
  request: AuthorizedRequest;
  memberId: string;
  subjectKey: string;
  active: boolean;
  available: () => boolean;
  deactivate: { current: (() => void) | null };
}) {
  const [segment, setSegment] = useState("due");
  const live = useRef({ active, available });
  live.current = { active, available };
  const current = () => live.current.active && live.current.available();
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
        onChange={(value) => {
          if (!current() || value === segment) return;
          deactivate.current?.();
          setSegment(value);
        }}
        options={[
          { value: "due", label: "Task queue" },
          { value: "reviews", label: "Reviews" },
        ]}
      />
      {segment === "due" && active ? (
        <MatterTaskQueue
          key={`${subjectKey}:${memberId}`}
          request={request}
          memberId={memberId}
          subjectKey={subjectKey}
          available={current}
          deactivate={deactivate}
          openMatter={openMatter}
        />
      ) : segment === "reviews" ? (
        <ResourceView resource={resource} reload={reload}>
          {(today) => {
            const stream = today.streams.find(
              (item) => item.key === "drafts_in_review",
            )!;
            return (
              <>
                <Text style={styles.muted}>Visible draft reviews</Text>
                {stream.items.length ? (
                  stream.items.map((item) => (
                    <WorkRow
                      key={item.id}
                      item={item}
                      onPress={() => {
                        if (current()) openWork(item);
                      }}
                    />
                  ))
                ) : (
                  <Empty
                    title="No items returned"
                    message="This bounded feed returned no drafts in review."
                  />
                )}
                {stream.truncated ? (
                  <Text style={[styles.body, { color: colors.warning }]}>
                    More items exist than this feed returns. Open their matter
                    in the web workspace.
                  </Text>
                ) : null}
                <Text style={styles.label}>
                  Drafts open at the exact server-owned current version. Formal
                  review and legal decisions remain in the web workspace.
                </Text>
                <NativeButton
                  label="Reload work"
                  onPress={() => {
                    if (current()) reload();
                  }}
                  secondary
                />
              </>
            );
          }}
        </ResourceView>
      ) : null}
    </ScrollView>
  );
}
function MatterTaskQueue({
  request,
  memberId,
  subjectKey,
  available,
  deactivate,
  openMatter,
}: {
  request: AuthorizedRequest;
  memberId: string;
  subjectKey: string;
  available: () => boolean;
  deactivate: { current: (() => void) | null };
  openMatter: (matter: MatterRef) => void;
}) {
  const [entry, setEntry] = useState<QueueEntry | null>(null);
  const authority = useRef({ request, subjectKey, available });
  authority.current = { request, subjectKey, available };
  const admitted = (owned: QueueEntry) =>
    authority.current.request === owned.request &&
    authority.current.subjectKey === owned.subjectKey &&
    authority.current.available() &&
    AppState.currentState === "active";
  useEffect(() => {
    const owned: QueueEntry = {
      request,
      subjectKey,
      controller: createMatterWorkQueueController(
        createMatterWorkQueueRepository(request, memberId),
        () => admitted(owned),
      ),
    };
    setEntry(owned);
    const suspend = () => owned.controller.suspend();
    deactivate.current = suspend;
    const update = (state: typeof AppState.currentState) => {
      if (state === "active" && admitted(owned)) {
        if (owned.controller.activate())
          void owned.controller.firstPage(owned.controller.getSnapshot());
      } else suspend();
    };
    const subscription = AppState.addEventListener("change", update);
    update(AppState.currentState);
    return () => {
      subscription.remove();
      if (deactivate.current === suspend) deactivate.current = null;
      owned.controller.dispose();
    };
  }, [request, subjectKey, memberId, deactivate]);
  return entry && admitted(entry) ? (
    <QueuePanel
      entry={entry}
      current={() => admitted(entry)}
      openMatter={openMatter}
    />
  ) : null;
}
const ownershipLabel: Record<QueueOwnership, string> = {
  mine: "Assigned to you",
  team: "Assigned to another member of your active teams",
  unassigned: "Unassigned",
};
function QueuePanel({
  entry,
  current,
  openMatter,
}: {
  entry: QueueEntry;
  current: () => boolean;
  openMatter: (matter: MatterRef) => void;
}) {
  const controller = entry.controller;
  const view = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  const latest = useRef({ controller, view, current });
  latest.current = { controller, view, current };
  const live = () =>
    latest.current.controller === controller &&
    latest.current.view === view &&
    controller.current(view) &&
    latest.current.current();
  const select = (
    ownership: QueueOwnership,
    dates: typeof view.filter.dates,
  ) => {
    if (live()) void controller.select(view, { ownership, dates });
  };
  return (
    <View testID="matter-task-queue" style={{ gap: 12 }}>
      <Text style={styles.muted}>
        Open Matter tasks. IP work and hearing schedules have separate views.
      </Text>
      <NativeSegments
        label="Task ownership"
        value={view.filter.ownership}
        onChange={(value) => {
          if (
            ["mine", "team", "unassigned"].includes(value) &&
            value !== view.filter.ownership
          )
            select(value as QueueOwnership, view.filter.dates);
        }}
        options={[
          { value: "mine", label: "Mine" },
          { value: "team", label: "Team" },
          { value: "unassigned", label: "Unassigned" },
        ]}
      />
      <Text testID="queue-ownership-meaning" style={styles.label}>
        {view.filter.ownership === "team"
          ? "Tasks assigned to other members of your active teams. Your own and unassigned tasks are excluded. Matter access is still required."
          : ownershipLabel[view.filter.ownership]}
      </Text>
      <NativeSegments
        label="Task dates"
        value={view.filter.dates}
        onChange={(value) => {
          if (
            ["all", "dated", "undated"].includes(value) &&
            value !== view.filter.dates
          )
            select(view.filter.ownership, value as typeof view.filter.dates);
        }}
        options={[
          { value: "all", label: "All dates" },
          { value: "dated", label: "Dated" },
          { value: "undated", label: "Undated" },
        ]}
      />
      {view.phase === "loading" ? (
        <>
          <NativeProgress />
          <Text style={styles.muted}>Loading current work</Text>
        </>
      ) : null}
      {view.phase === "ready" && view.page ? (
        <>
          {view.page.items.length ? (
            view.page.items.map((item) => (
              <RecordRow
                key={item.id}
                title={item.title}
                subtitle={`${item.matter.matter_code} · ${item.matter.title}`}
                meta={`${item.due_on ? displayDay(item.due_on) : "No due date"} · ${item.status.replaceAll("_", " ")} · ${item.priority} priority · ${ownershipLabel[view.filter.ownership]}`}
                testID={`queue-task-${item.id}`}
                onPress={() => {
                  if (live()) void controller.showTask(view, item);
                }}
              />
            ))
          ) : (
            <Empty
              title="No matching tasks"
              message="The current server page contains no open Matter tasks for this ownership and date view."
            />
          )}
          <Text style={styles.label}>
            This page reflects current work when loaded. Reload the first page
            to include work added or moved earlier.
          </Text>
          {view.page.next_cursor ? (
            <NativeButton
              label="Next page"
              testID="queue-next"
              disabled={view.busy}
              onPress={() => {
                if (live()) void controller.nextPage(view);
              }}
            />
          ) : (
            <Text style={styles.label}>No next page was returned.</Text>
          )}
        </>
      ) : null}
      {view.phase === "detail" && view.selected ? (
        <View testID="queue-task-detail" style={{ gap: 12 }}>
          <Text
            testID="queue-task-title"
            accessibilityRole="header"
            style={styles.heading}
          >
            {view.selected.title}
          </Text>
          <Fact
            testID="queue-task-matter"
            label="Matter"
            value={`${view.selected.matter.matter_code} · ${view.selected.matter.title}`}
          />
          <Fact
            testID="queue-task-id"
            label="Task ID"
            value={view.selected.id}
          />
          <Fact
            testID="queue-task-status"
            label="Status"
            value={view.selected.status.replaceAll("_", " ")}
          />
          <Fact
            testID="queue-task-priority"
            label="Priority"
            value={view.selected.priority}
          />
          <Fact
            testID="queue-task-due"
            label="Due date"
            value={
              view.selected.due_on
                ? displayDay(view.selected.due_on)
                : "No due date recorded"
            }
          />
          <Fact
            testID="queue-task-assignment"
            label="Assignment"
            value={ownershipLabel[view.filter.ownership]}
          />
          <Fact
            testID="queue-task-created"
            label="Created (UTC)"
            value={view.selected.created_at}
          />
          <Fact
            testID="queue-task-updated"
            label="As loaded: updated (UTC)"
            value={view.selected.updated_at}
          />
          <Fact
            testID="queue-task-lifecycle"
            label="Matter lifecycle version as loaded"
            value={String(view.selected.matter.lifecycle_version)}
          />
          <Text style={styles.label}>
            These are the task facts returned by a fresh read of this queue
            page. Open Matter loads its current workspace separately; that
            bounded workspace may not include this task.
          </Text>
          <NativeButton
            label="Open Matter"
            testID="queue-open-matter"
            onPress={() => {
              if (live())
                controller.openMatter(view, (item) => openMatter(item.matter));
            }}
          />
          <NativeButton
            label="Back to page"
            testID="queue-back"
            onPress={() => {
              if (live()) controller.backToPage(view);
            }}
            secondary
          />
        </View>
      ) : null}
      {view.phase === "stale" ? (
        <Text
          testID="queue-stale"
          accessibilityRole="alert"
          style={styles.body}
        >
          Work or access changed. The old page and task have been cleared. Load
          the first page to continue.
        </Text>
      ) : null}
      {view.failure ? (
        <View accessibilityRole="alert">
          <Text style={styles.heading}>{view.failure.title}</Text>
          <Text style={styles.body}>{view.failure.message}</Text>
        </View>
      ) : null}
      {view.phase !== "inactive" ? (
        <NativeButton
          label="First page"
          testID="queue-first"
          disabled={view.busy}
          onPress={() => {
            if (live()) void controller.firstPage(view);
          }}
          secondary
        />
      ) : (
        <Text style={styles.muted}>
          Work is cleared while this view is inactive.
        </Text>
      )}
    </View>
  );
}
