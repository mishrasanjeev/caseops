import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { Text, View } from "react-native";
import { useResource } from "../application/useResource";
import { displayDay } from "../domain/contracts";
import {
  createObligationDisclosure,
  createObligationNavigator,
} from "../domain/contract-obligations";
import type { SourceRecordsRepository } from "../domain/source-records";
import { Fact, RecordRow, ResourceView } from "./Content";
import { NativeButton } from "./NativeControls";
import { styles } from "./theme";

export function ContractObligations({
  repository,
  contractId,
}: {
  repository: SourceRecordsRepository;
  contractId: string;
}) {
  const disclosure = useMemo(createObligationDisclosure, [
    repository,
    contractId,
  ]);
  const latest = useRef(disclosure);
  latest.current = disclosure;
  const frame = useSyncExternalStore(
    disclosure.subscribe,
    disclosure.getSnapshot,
    disclosure.getSnapshot,
  );
  useEffect(() => () => disclosure.dispose(), [disclosure]);
  const current = () =>
    latest.current === disclosure && disclosure.current(frame);
  return frame.open ? (
    <ObligationList
      key={JSON.stringify([repository.companyId, contractId, frame.revision])}
      repository={repository}
      contractId={contractId}
      close={() => {
        if (current()) disclosure.close(frame);
      }}
    />
  ) : (
    <NativeButton
      label="Read recorded obligations"
      testID="source-open-obligations"
      onPress={() => {
        if (current()) disclosure.open(frame);
      }}
      secondary
    />
  );
}

function ObligationList({
  repository,
  contractId,
  close,
}: {
  repository: SourceRecordsRepository;
  contractId: string;
  close: () => void;
}) {
  const navigation = useMemo(createObligationNavigator, [
    repository,
    contractId,
  ]);
  const frame = useSyncExternalStore(
    navigation.subscribe,
    navigation.getSnapshot,
    navigation.getSnapshot,
  );
  const [selection, setSelection] = useState<string | null>(null);
  useEffect(() => () => navigation.dispose(), [navigation]);
  const data = useResource(
    JSON.stringify([
      "contract-obligations",
      repository.companyId,
      contractId,
      frame,
    ]),
    (signal) => repository.obligations(contractId, frame.after, signal),
  );
  return (
    <View testID="source-obligations" style={{ gap: 12 }}>
      <Text accessibilityRole="header" style={styles.heading}>
        Recorded obligations
      </Text>
      <Text style={styles.muted}>
        Source records in ID order. Dates and responsibility are recorded facts.
      </Text>
      <ResourceView
        resource={data.resource}
        reload={() => {
          if (navigation.reload(frame)) setSelection(null);
        }}
      >
        {(page) => {
          const selected = page.obligations.find(
            (item) => item.id === selection,
          );
          return (
            <>
              {page.obligations.length ? (
                page.obligations.map((item) => (
                  <RecordRow
                    key={item.id}
                    testID={`obligation-row-${item.id}`}
                    title={item.title || "Title not recorded"}
                    subtitle={
                      item.due_on
                        ? displayDay(item.due_on)
                        : "Due date not recorded"
                    }
                    meta={`${item.status || "Status not recorded"} · ${item.owner_name || "Responsible person not supplied"}`}
                    onPress={() => {
                      if (navigation.current(frame)) setSelection(item.id);
                    }}
                  />
                ))
              ) : (
                <Text testID="obligations-empty" style={styles.muted}>
                  No obligations returned on this page.
                </Text>
              )}
              {selected ? (
                <View
                  testID={`obligation-detail-${selected.id}`}
                  style={{ gap: 8 }}
                >
                  <Fact
                    testID="obligation-id"
                    label="Recorded obligation ID"
                    value={selected.id}
                  />
                  <Fact
                    testID="obligation-due"
                    label="Due date"
                    value={selected.due_on ? displayDay(selected.due_on) : null}
                  />
                  <Fact
                    testID="obligation-owner-name"
                    label="Responsible person"
                    value={selected.owner_name}
                  />
                  <Fact
                    testID="obligation-owner-id"
                    label="Responsible membership ID"
                    value={selected.owner_membership_id}
                  />
                  <Fact
                    testID="obligation-status"
                    label="Recorded status"
                    value={selected.status}
                  />
                  <Fact
                    testID="obligation-priority"
                    label="Priority"
                    value={selected.priority}
                  />
                  <Fact
                    testID="obligation-description"
                    label={
                      selected.description_truncated
                        ? "Description preview · first 4,000 characters"
                        : "Recorded description"
                    }
                    value={selected.description}
                  />
                  <Fact
                    testID="obligation-created"
                    label="Created"
                    value={selected.created_at}
                  />
                  <Fact
                    testID="obligation-completed"
                    label="Completed at"
                    value={selected.completed_at}
                  />
                </View>
              ) : null}
              <Text testID="obligation-page" style={styles.label}>
                Page {frame.page}
              </Text>
              {page.next_after ? (
                <NativeButton
                  label="Next obligations"
                  testID="obligations-next"
                  onPress={() => {
                    if (navigation.next(frame, page.next_after!))
                      setSelection(null);
                  }}
                  secondary
                />
              ) : null}
            </>
          );
        }}
      </ResourceView>
      {frame.after ? (
        <NativeButton
          label="First obligation page"
          testID="obligations-first"
          onPress={() => {
            if (navigation.first(frame)) setSelection(null);
          }}
          secondary
        />
      ) : null}
      <NativeButton
        label="Reload obligations"
        testID="obligations-reload"
        onPress={() => {
          if (navigation.reload(frame)) setSelection(null);
        }}
        secondary
      />
      <NativeButton
        label="Close obligations"
        testID="obligations-close"
        onPress={() => {
          if (navigation.current(frame)) {
            navigation.dispose();
            close();
          }
        }}
        secondary
      />
    </View>
  );
}
