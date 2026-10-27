import { useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { NativeButton, NativeSegments } from "../../components/NativeControls";
import { Empty, Fact, RecordRow, ResourceView } from "../../components/Content";
import { styles } from "../../components/theme";
import { canAddNote, displayDay } from "../../domain/contracts";
import type { Matter } from "../../domain/contracts";
import { quickEditable } from "../../domain/quick-work";
import type { QuickTarget } from "../../domain/quick-work";
import type { Repository } from "../../domain/repository";
import { useResource } from "../useResource";

import type { MatterSection } from "../types";
import { FilesScreen } from "./FilesScreen";
import type { FilesScreenProps } from "./FilesScreen";

export function MatterScreen({
  repository,
  matterId,
  initialSection,
  canWrite,
  addNote,
  openDraft,
  openQuickWork,
  openCounsel,
  openRecommendations,
  openHearingPack,
  files,
  onSectionChange,
}: {
  repository: Repository;
  matterId: string;
  initialSection: MatterSection;
  canWrite: boolean;
  addNote: (matter: Matter) => void;
  openDraft: (id: string) => void;
  openQuickWork: (matter: Matter, target: QuickTarget) => void;
  openCounsel: () => void;
  openRecommendations: () => void;
  openHearingPack: (hearingId: string) => void;
  files: FilesScreenProps;
  onSectionChange: (section: MatterSection) => void;
}) {
  const [section, setSection] = useState<string>(initialSection),
    [limit, setLimit] = useState(50);
  const data = useResource(`workspace:${matterId}`, (signal) =>
    repository.workspace(matterId, signal),
  );
  return (
    <ScrollView
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={styles.content}
      testID="matter-detail"
    >
      <ResourceView resource={data.resource} reload={data.reload}>
        {(workspace) => (
          <>
            <Text testID="matter-code" style={styles.label}>
              {workspace.matter.matter_code}
            </Text>
            <Text accessibilityRole="header" style={styles.title}>
              {workspace.matter.title}
            </Text>
            <Text style={styles.status}>{workspace.matter.status}</Text>
            <NativeSegments
              label="Matter view"
              value={section}
              options={["Summary", "Activity", "Files", "Work"].map(
                (value) => ({
                  value,
                  label: value,
                  testID: `matter-${value.toLowerCase()}`,
                }),
              )}
              onChange={(value) => {
                const change = () => {
                  setSection(value);
                  setLimit(50);
                  onSectionChange(value as MatterSection);
                  if (value !== "Files") files.onClearSelectedFile();
                };
                if (section === "Files" && files.guard.current)
                  files.guard.current(change);
                else change();
              }}
            />
            {section === "Summary" ? (
              <>
                <Fact label="Client" value={workspace.matter.client_name} />
                <Fact
                  label="Next hearing"
                  value={
                    workspace.matter.next_hearing_on
                      ? displayDay(workspace.matter.next_hearing_on)
                      : null
                  }
                />
                <Fact
                  label="Hearing source"
                  value={
                    workspace.matter.next_hearing_source === "manual"
                      ? "Manual date"
                      : workspace.matter.next_hearing_source || "Unknown"
                  }
                />
                <Text style={styles.label}>Source freshness unknown</Text>
                <Fact label="Court" value={workspace.matter.court_name} />
                <Fact
                  label="Case number"
                  value={workspace.matter.case_number}
                />
                <Fact
                  label="Temporary e-case number"
                  value={workspace.matter.temporary_e_case_number}
                />
                <Fact
                  label="Filing number"
                  value={workspace.matter.filing_number}
                />
                <Fact label="CNR" value={workspace.matter.cnr_number} />
                <Fact
                  label="Description"
                  value={workspace.matter.description}
                />
                <NativeButton
                  testID="matter-counsel"
                  label="Counsel & spend"
                  onPress={openCounsel}
                  secondary
                />
                <NativeButton
                  testID="matter-recommendations"
                  label="Saved recommendations"
                  onPress={openRecommendations}
                  secondary
                />
              </>
            ) : section === "Activity" ? (
              <>
                <Text accessibilityRole="header" style={styles.heading}>
                  Notes
                </Text>
                {workspace.notes.length ? (
                  workspace.notes.slice(0, limit).map((note) => (
                    <View
                      key={note.id}
                      testID={`note-${note.id}`}
                      style={[styles.divider, { paddingVertical: 16, gap: 8 }]}
                    >
                      <Text
                        testID={`note-body-${note.id}`}
                        selectable
                        style={styles.body}
                      >
                        {note.body}
                      </Text>
                      <Text style={styles.label}>
                        {note.author_name || "Author not supplied"} ·{" "}
                        {note.created_at}
                      </Text>
                    </View>
                  ))
                ) : (
                  <Empty
                    title="No notes recorded"
                    message="Notes saved against this matter appear here."
                  />
                )}
                {workspace.notes.length > limit ? (
                  <NativeButton
                    label="Show more notes"
                    onPress={() => setLimit((value) => value + 50)}
                    secondary
                  />
                ) : null}
                <Text accessibilityRole="header" style={styles.heading}>
                  Activity
                </Text>
                {workspace.activity.length ? (
                  workspace.activity
                    .slice(0, limit)
                    .map((item) => (
                      <RecordRow
                        key={item.id}
                        title={item.title}
                        subtitle={item.detail}
                        meta={`${item.actor_name || "Actor not supplied"} · ${item.created_at}`}
                      />
                    ))
                ) : (
                  <Text style={styles.muted}>No activity returned.</Text>
                )}
                {workspace.activity.length > limit ? (
                  <NativeButton
                    label="Show more activity"
                    onPress={() => setLimit((value) => value + 50)}
                    secondary
                  />
                ) : null}
              </>
            ) : section === "Files" ? (
              <FilesScreen {...files} />
            ) : (
              <>
                <MatterQuickWork
                  repository={repository}
                  matterId={matterId}
                  canWrite={canWrite}
                  openQuickWork={openQuickWork}
                  openHearingPack={openHearingPack}
                />
                <MatterDrafts
                  repository={repository}
                  matterId={matterId}
                  openDraft={openDraft}
                />
              </>
            )}
            {["Summary", "Activity"].includes(section) ? (
              canWrite && canAddNote(workspace.matter) ? (
                <NativeButton
                  label="Add note"
                  testID="note-add"
                  onPress={() => addNote(workspace.matter)}
                />
              ) : (
                <Text style={styles.muted}>
                  {canAddNote(workspace.matter)
                    ? "This account has read-only access."
                    : "This matter is read-only. Lifecycle actions are not available on mobile."}
                </Text>
              )
            ) : null}
            <NativeButton
              label="Reload matter"
              testID="matter-reload"
              onPress={data.reload}
              secondary
            />
          </>
        )}
      </ResourceView>
    </ScrollView>
  );
}

function MatterQuickWork({
  repository,
  matterId,
  canWrite,
  openQuickWork,
  openHearingPack,
}: {
  repository: Repository;
  matterId: string;
  canWrite: boolean;
  openQuickWork: (matter: Matter, target: QuickTarget) => void;
  openHearingPack: (hearingId: string) => void;
}) {
  const [limit, setLimit] = useState(50);
  const current = useResource(`quick-work:${matterId}`, () =>
    repository.quickWork.load(matterId),
  );
  return (
    <ResourceView resource={current.resource} reload={current.reload}>
      {(snapshot) => {
        const mayWrite = canWrite && canAddNote(snapshot.matter);
        return (
          <View style={{ gap: 12 }}>
            <Text accessibilityRole="header" style={styles.heading}>
              Matter tasks
            </Text>
            {snapshot.tasks.length ? (
              snapshot.tasks.slice(0, limit).map((record) => (
                <RecordRow
                  key={record.id}
                  testID={`task-${record.id}`}
                  title={record.fields.title || "Untitled task"}
                  subtitle={record.owner_name || "Unassigned"}
                  meta={`${record.fields.status} · ${record.fields.due_on ? displayDay(record.fields.due_on) : "No due date"}${mayWrite && quickEditable(record) ? "" : " · Read-only"}`}
                  onPress={
                    mayWrite && quickEditable(record)
                      ? () =>
                          openQuickWork(snapshot.matter, {
                            kind: "task",
                            id: record.id,
                          })
                      : undefined
                  }
                />
              ))
            ) : (
              <Empty
                title="No tasks returned"
                message="No tasks were returned for this Matter."
              />
            )}
            {mayWrite ? (
              <NativeButton
                testID="quick-task-add"
                label="Add task"
                onPress={() => openQuickWork(snapshot.matter, { kind: "task" })}
              />
            ) : null}
            <Text accessibilityRole="header" style={styles.heading}>
              Hearings
            </Text>
            {snapshot.hearings.length ? (
              snapshot.hearings.slice(0, limit).map((record) => (
                <View key={record.id} style={{ gap: 8 }}>
                  <RecordRow
                    key={record.id}
                    testID={`hearing-${record.id}`}
                    title={
                      record.fields.purpose || "Hearing purpose not recorded"
                    }
                    subtitle={record.fields.forum_name || "Forum not recorded"}
                    meta={`${displayDay(record.fields.hearing_on)} · ${record.fields.status}${mayWrite && quickEditable(record) ? "" : " · Read-only"}`}
                    onPress={
                      mayWrite && quickEditable(record)
                        ? () =>
                            openQuickWork(snapshot.matter, {
                              kind: "hearing",
                              id: record.id,
                            })
                        : undefined
                    }
                  />
                  <NativeButton
                    testID={`hearing-pack-open-${record.id}`}
                    label={`Existing pack: ${displayDay(record.fields.hearing_on)}`}
                    secondary
                    onPress={() => openHearingPack(record.id)}
                  />
                </View>
              ))
            ) : (
              <Empty
                title="No hearings returned"
                message="No hearings were returned for this Matter."
              />
            )}
            {mayWrite ? (
              <NativeButton
                testID="quick-hearing-add"
                label="Add hearing"
                onPress={() =>
                  openQuickWork(snapshot.matter, { kind: "hearing" })
                }
              />
            ) : (
              <Text style={styles.muted}>
                Work is read-only for this account or Matter lifecycle.
              </Text>
            )}
            {snapshot.tasks.length > limit ||
            snapshot.hearings.length > limit ? (
              <NativeButton
                label="Show more work records"
                testID="quick-work-more"
                onPress={() => setLimit((value) => value + 50)}
                secondary
              />
            ) : null}
            <Text style={styles.muted}>
              Retained lifecycle history and records without current version or
              reminder-plan support are read-only. Reload before editing changed
              work.
            </Text>
          </View>
        );
      }}
    </ResourceView>
  );
}

function MatterDrafts({
  repository,
  matterId,
  openDraft,
}: {
  repository: Repository;
  matterId: string;
  openDraft: (id: string) => void;
}) {
  const drafts = useResource(`matter-drafts:${matterId}`, (signal) =>
    repository.drafts(matterId, signal),
  );
  return (
    <View style={{ gap: 12 }}>
      <Text style={styles.heading}>Drafts</Text>
      <ResourceView resource={drafts.resource} reload={drafts.reload}>
        {(value) =>
          value.length ? (
            value.map((draft) => (
              <RecordRow
                key={draft.id}
                title={draft.title}
                meta={`${draft.status} · Read-only`}
                onPress={() => openDraft(draft.id)}
              />
            ))
          ) : (
            <Text style={styles.muted}>No drafts returned.</Text>
          )
        }
      </ResourceView>
    </View>
  );
}
