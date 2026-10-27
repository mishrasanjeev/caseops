import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { AppState, Text, View } from "react-native";
import { randomUUID } from "expo-crypto";
import {
  createPrivacyRequestController,
  createPrivacyRequestsRepository,
} from "../domain/privacy-requests";
import type { PrivacyRequestController } from "../domain/privacy-requests";
import type { AuthorizedRequest } from "../domain/repository";
import { Fact } from "./Content";
import { NativeButton } from "./NativeControls";
import { styles } from "./theme";

type Props = {
  request: AuthorizedRequest;
  subjectKey: string;
  disabled?: boolean;
  available?: () => boolean;
  onBusyChange?: (busy: boolean) => void;
};
type Entry = {
  request: AuthorizedRequest;
  subjectKey: string;
  controller: PrivacyRequestController;
};
export function AccountPrivacyRequests({
  request,
  subjectKey,
  disabled = false,
  available,
  onBusyChange,
}: Props) {
  const [entry, setEntry] = useState<Entry | null>(null);
  const authority = useRef({
    request,
    subjectKey,
    disabled,
    available,
    onBusyChange,
  });
  authority.current = {
    request,
    subjectKey,
    disabled,
    available,
    onBusyChange,
  };
  const admitted = (owned: Entry) =>
    authority.current.request === owned.request &&
    authority.current.subjectKey === owned.subjectKey &&
    !authority.current.disabled &&
    authority.current.available?.() !== false;
  useEffect(() => {
    const owned: Entry = {
      request,
      subjectKey,
      controller: createPrivacyRequestController(
        createPrivacyRequestsRepository(request),
        randomUUID,
      ),
    };
    const unsubscribe = owned.controller.subscribe(() => {
      const state = owned.controller.getSnapshot();
      authority.current.onBusyChange?.(
        state.phase === "submitting" && state.busy,
      );
    });
    setEntry(owned);
    const update = (state: typeof AppState.currentState) => {
      if (state === "active" && admitted(owned)) {
        if (owned.controller.activate())
          void owned.controller.reload(owned.controller.getSnapshot());
      } else owned.controller.suspend();
    };
    const subscription = AppState.addEventListener("change", update);
    update(AppState.currentState);
    return () => {
      subscription.remove();
      owned.controller.dispose();
      unsubscribe();
      authority.current.onBusyChange?.(false);
    };
  }, [request, subjectKey]);
  useEffect(() => {
    if (!entry) return;
    if (!admitted(entry)) entry.controller.suspend();
    else if (AppState.currentState === "active" && entry.controller.activate())
      void entry.controller.reload(entry.controller.getSnapshot());
  }, [entry, disabled]);
  return (
    <View testID="account-privacy-requests" style={{ gap: 12 }}>
      <Text accessibilityRole="header" style={styles.heading}>
        Account deletion request
      </Text>
      <Text style={styles.body}>
        You can ask CaseOps to review deletion of your own account. Recording a
        request does not delete or deactivate your account, remove organization
        records, or confirm a completion date.
      </Text>
      {entry && admitted(entry) ? (
        <RequestPanel
          key={subjectKey}
          entry={entry}
          current={() => admitted(entry)}
        />
      ) : (
        <Text testID="privacy-request-inactive" style={styles.muted}>
          The account request panel is inactive while account access or another
          account action changes.
        </Text>
      )}
    </View>
  );
}
function RequestPanel({
  entry,
  current,
}: {
  entry: Entry;
  current: () => boolean;
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
    latest.current.current() &&
    controller.current(view);
  return (
    <View testID="privacy-request-panel" style={{ gap: 12 }}>
      <Text testID="privacy-request-state" style={styles.muted}>
        {view.phase === "received"
          ? "Request received"
          : view.phase === "unknown"
            ? "Acknowledgement unconfirmed"
            : view.phase === "none"
              ? "No received request is recorded"
              : view.phase === "confirming"
                ? "Confirm your request"
                : view.phase === "submitting"
                  ? "Submitting one request"
                  : view.phase === "loading"
                    ? "Loading your own request"
                    : "Request receipt unavailable"}
      </Text>
      {view.receipt ? (
        <View testID="privacy-request-receipt" style={{ gap: 8 }}>
          <Fact
            testID="privacy-request-id"
            label="Request ID"
            value={view.receipt.id}
          />
          <Fact
            testID="privacy-request-operation"
            label="Operation ID"
            value={view.receipt.operation_id}
          />
          <Fact
            testID="privacy-request-requested-at"
            label="Received at (UTC)"
            value={view.receipt.requested_at}
          />
          <Fact
            testID="privacy-request-status"
            label="Request status"
            value="Received"
          />
          <Fact
            testID="privacy-request-not-completed"
            label="Account deletion"
            value="Not completed"
          />
        </View>
      ) : null}
      {view.message ? (
        <Text
          testID="privacy-request-message"
          accessibilityLiveRegion="polite"
          style={styles.body}
        >
          {view.message}
        </Text>
      ) : null}
      {view.phase === "none" ? (
        <NativeButton
          testID="privacy-request-start"
          label="Request account deletion"
          disabled={view.busy}
          onPress={() => {
            if (live()) controller.begin(view);
          }}
        />
      ) : null}
      {view.phase === "confirming" ? (
        <View testID="privacy-request-confirmation" style={{ gap: 12 }}>
          <Text style={styles.body}>
            Confirm that you want to record an account deletion request for
            yourself. This submits a request only. Your access and records are
            not deleted by this action.
          </Text>
          <NativeButton
            testID="privacy-request-confirm"
            label="Confirm request"
            disabled={view.busy}
            onPress={() => {
              if (live()) void controller.confirm(view);
            }}
          />
          <NativeButton
            testID="privacy-request-cancel"
            label="Cancel request confirmation"
            secondary
            disabled={view.busy}
            onPress={() => {
              if (live()) controller.cancel(view);
            }}
          />
        </View>
      ) : null}
      {view.phase !== "inactive" && view.phase !== "confirming" ? (
        <NativeButton
          testID="privacy-request-reload"
          label="Reload my request"
          secondary
          disabled={view.busy}
          onPress={() => {
            if (live()) void controller.reload(view);
          }}
        />
      ) : null}
    </View>
  );
}
