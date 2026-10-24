import { useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { NativeButton, NativeSegments } from "../../components/NativeControls";
import { Empty, Fact, RecordRow, ResourceView } from "../../components/Content";
import { styles } from "../../components/theme";
import { canAddNote, displayDay } from "../../domain/contracts";
import type { Matter } from "../../domain/contracts";
import type { Repository } from "../../domain/repository";
import { useResource } from "../useResource";

import type { MatterSection } from "../types";

export function MatterScreen({
  repository,
  matterId,
  initialSection,
  canWrite,
  addNote,
  openDraft,
}: {
  repository: Repository;
  matterId: string;
  initialSection: MatterSection;
  canWrite: boolean;
  addNote: (matter: Matter) => void;
  openDraft: (id: string) => void;
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
                setSection(value);
                setLimit(50);
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
              </>
            ) : section === "Activity" ? (
              <>
                <Text accessibilityRole="header" style={styles.heading}>
                  Notes
                </Text>
                {workspace.notes.length ? (
                  workspace.notes.slice(0, limit).map((note, index) => (
                    <View
                      key={note.id}
                      testID={`note-${note.id}`}
                      style={[styles.divider, { paddingVertical: 16, gap: 8 }]}
                    >
                      <Text
                        testID={
                          index === 0
                            ? "note-latest-body"
                            : `note-body-${note.id}`
                        }
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
              <>
                <Text style={styles.muted}>
                  Private native viewing, camera capture and upload are not
                  available in this build. Use the secure web workspace.
                </Text>
                {workspace.attachments.length ? (
                  workspace.attachments
                    .slice(0, limit)
                    .map((file) => (
                      <RecordRow
                        key={file.id}
                        title={file.filename || "Filename not supplied"}
                        meta={`${file.processing_status || "Processing state unknown"} · ${file.created_at}`}
                      />
                    ))
                ) : (
                  <Empty
                    title="No files returned"
                    message="No attachments were returned for this matter."
                  />
                )}
                {workspace.attachments.length > limit ? (
                  <NativeButton
                    label="Show more files"
                    onPress={() => setLimit((value) => value + 50)}
                    secondary
                  />
                ) : null}
              </>
            ) : (
              <>
                <Text accessibilityRole="header" style={styles.heading}>
                  Matter tasks
                </Text>
                {workspace.tasks.length ? (
                  workspace.tasks
                    .slice(0, limit)
                    .map((task) => (
                      <RecordRow
                        key={task.id}
                        title={task.title}
                        subtitle={task.owner_name || "Unassigned"}
                        meta={`${task.status} · ${task.due_on ? displayDay(task.due_on) : "No due date"}`}
                      />
                    ))
                ) : (
                  <Empty
                    title="No tasks returned"
                    message="No tasks were returned for this matter."
                  />
                )}
                {workspace.tasks.length > limit ? (
                  <NativeButton
                    label="Show more tasks"
                    onPress={() => setLimit((value) => value + 50)}
                    secondary
                  />
                ) : null}
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
