import { ScrollView, Text } from "react-native";
import { NativeButton } from "../../components/NativeControls";
import { Fact, ResourceView } from "../../components/Content";
import { styles } from "../../components/theme";
import type { Repository } from "../../domain/repository";
import { useResource } from "../useResource";

export function DraftScreen({
  repository,
  matterId,
  draftId,
}: {
  repository: Repository;
  matterId: string;
  draftId: string;
}) {
  const draft = useResource(`draft:${matterId}:${draftId}`, (signal) =>
    repository.draft(matterId, draftId, signal),
  );
  return (
    <ScrollView contentContainerStyle={styles.content}>
      <ResourceView resource={draft.resource} reload={draft.reload}>
        {(value) => (
          <>
            <Text accessibilityRole="header" style={styles.title}>
              {value.title}
            </Text>
            <Text style={styles.status}>{value.status} · Read-only</Text>
            <Fact
              label="Current version"
              value={
                value.current
                  ? `Revision ${value.current.revision} · ${value.current.id}`
                  : "No current version"
              }
            />
            {value.current ? (
              <>
                <Text selectable style={styles.body}>
                  {value.current.body}
                </Text>
                <Text style={styles.heading}>Citations</Text>
                {value.current.citations.length ? (
                  value.current.citations.map((citation, index) => (
                    <Text selectable key={index} style={styles.body}>
                      {citation}
                    </Text>
                  ))
                ) : (
                  <Text style={styles.muted}>
                    No citations supplied for this version.
                  </Text>
                )}
                <Text style={styles.label}>
                  {value.current.verified_citation_count} server-marked verified
                  citations. This is not certification of legal accuracy.
                </Text>
              </>
            ) : null}
            <NativeButton
              label="Reload current version"
              onPress={draft.reload}
              secondary
            />
          </>
        )}
      </ResourceView>
    </ScrollView>
  );
}
