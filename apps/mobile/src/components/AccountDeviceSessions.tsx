import { useEffect, useMemo, useRef, useState } from "react";
import type { ComponentRef } from "react";
import {
  AccessibilityInfo,
  Modal,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { NativeButton, NativeProgress } from "./NativeControls";
import { colors, styles } from "./theme";
import { useResource } from "../application/useResource";
import {
  createDeviceSessionRevocation,
  createDeviceSessionsRepository,
  deviceSessionInstant,
} from "../domain/device-sessions";
import type {
  DeviceSession,
  DeviceSessionRevocation,
} from "../domain/device-sessions";
import type { AuthorizedRequest } from "../domain/repository";

function platformName(session: DeviceSession): string {
  return session.platform === "android" ? "Android" : "iOS";
}
function displayTime(value: string): string {
  return new Date(deviceSessionInstant(value)).toLocaleString();
}

export function AccountDeviceSessions({
  request,
  onCurrentSessionRevoked,
  onBusyChange,
  disabled = false,
}: {
  request: AuthorizedRequest;
  onCurrentSessionRevoked: () => Promise<void>;
  onBusyChange: (busy: boolean) => void;
  disabled?: boolean;
}) {
  const repository = useMemo(
    () => createDeviceSessionsRepository(request),
    [request],
  );
  const { resource, reload } = useResource(
    "account-device-sessions",
    (signal) => repository.list(signal),
  );
  const [selected, setSelected] = useState<DeviceSession | null>(null);
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<DeviceSessionRevocation | null>(null);
  const lock = useRef(false);
  const mounted = useRef(true);
  const confirmationHeading = useRef<ComponentRef<typeof Text>>(null);
  const operation = useRef<(() => Promise<DeviceSessionRevocation>) | null>(
    null,
  );
  const blocked =
    outcome !== null && (outcome.state !== "revoked" || outcome.current);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      onBusyChange(false);
    };
  }, [onBusyChange]);
  const cancel = () => {
    if (lock.current) return;
    operation.current = null;
    setSelected(null);
    onBusyChange(false);
  };
  const confirm = async () => {
    if (disabled || lock.current || !operation.current) return;
    lock.current = true;
    setBusy(true);
    const result = await operation.current();
    if (!mounted.current) return;
    setOutcome(result);
    setSelected(null);
    operation.current = null;
    setBusy(false);
    lock.current = false;
    onBusyChange(false);
    if (result.state === "revoked" && !result.current) reload();
  };
  return (
    <>
      <View
        testID="account-device-sessions"
        style={{ gap: 16 }}
        accessibilityElementsHidden={selected !== null}
        importantForAccessibility={selected ? "no-hide-descendants" : "auto"}
      >
        <Text accessibilityRole="header" style={styles.heading}>
          Device sessions
        </Text>
        {outcome ? (
          <Text
            testID="account-sessions-outcome"
            accessibilityRole="alert"
            style={[
              styles.body,
              {
                color:
                  outcome.state === "revoked" && !outcome.signOutFailed
                    ? colors.success
                    : colors.danger,
              },
            ]}
          >
            {outcome.message}
          </Text>
        ) : null}
        {!blocked && resource.state === "loading" ? (
          <View
            testID="account-sessions-loading"
            accessibilityLiveRegion="polite"
            style={{ gap: 8 }}
          >
            <NativeProgress />
            <Text style={styles.muted}>Loading device sessions</Text>
          </View>
        ) : null}
        {!blocked && resource.state === "error" ? (
          <View testID="account-sessions-error" style={{ gap: 8 }}>
            <Text
              accessibilityRole="alert"
              style={[styles.body, { color: colors.danger }]}
            >
              {resource.error.title}
            </Text>
            <Text style={styles.body}>{resource.error.message}</Text>
          </View>
        ) : null}
        {!blocked && resource.state === "ready" ? (
          resource.data.length === 0 ? (
            <Text testID="account-sessions-empty" style={styles.body}>
              No active native sessions were returned for this account.
            </Text>
          ) : (
            resource.data.map((session, index) => (
              <View
                key={session.id}
                testID={`account-session-${index}`}
                style={{
                  gap: 8,
                  paddingBottom: 16,
                  borderBottomWidth: StyleSheet.hairlineWidth,
                  borderBottomColor: colors.line,
                }}
              >
                <Text
                  testID={`account-session-${index}-platform`}
                  style={styles.body}
                >
                  {platformName(session)} session
                </Text>
                <Text
                  testID={
                    session.current
                      ? "account-session-current"
                      : `account-session-${index}-other`
                  }
                  style={styles.status}
                >
                  {session.current ? "Current session" : "Other session"}
                </Text>
                <Text
                  testID={`account-session-${index}-created`}
                  style={styles.muted}
                >
                  Signed in: {displayTime(session.created_at)}
                </Text>
                <Text
                  testID={`account-session-${index}-last-used`}
                  style={styles.muted}
                >
                  Last used: {displayTime(session.last_used_at)}
                </Text>
                <Text
                  testID={`account-session-${index}-expires`}
                  style={styles.muted}
                >
                  Expires: {displayTime(session.expires_at)}
                </Text>
                {session.revoked_at ? (
                  <Text style={styles.status}>Revoked</Text>
                ) : (
                  <NativeButton
                    testID={`account-session-${index}-revoke`}
                    label={
                      session.current
                        ? "Revoke this session"
                        : `Revoke ${platformName(session)} session`
                    }
                    secondary
                    disabled={disabled || busy || selected !== null}
                    onPress={() => {
                      if (disabled || lock.current || operation.current) return;
                      operation.current = createDeviceSessionRevocation(
                        repository,
                        session,
                        onCurrentSessionRevoked,
                      );
                      setOutcome(null);
                      setSelected(session);
                      onBusyChange(true);
                    }}
                  />
                )}
              </View>
            ))
          )
        ) : null}
        {!(outcome?.current && outcome.state !== "rejected") ? (
          <NativeButton
            testID="account-sessions-reload"
            label="Reload sessions"
            secondary
            disabled={
              disabled ||
              busy ||
              selected !== null ||
              (!blocked && resource.state === "loading")
            }
            onPress={() => {
              operation.current = null;
              setOutcome(null);
              reload();
            }}
          />
        ) : null}
      </View>
      <Modal
        visible={selected !== null}
        transparent
        animationType="none"
        onRequestClose={cancel}
        onShow={() => {
          if (confirmationHeading.current)
            AccessibilityInfo.sendAccessibilityEvent(
              confirmationHeading.current,
              "focus",
            );
        }}
      >
        <View
          style={{
            flex: 1,
            backgroundColor: "rgba(0,0,0,0.45)",
            padding: 20,
            justifyContent: "center",
          }}
        >
          <ScrollView
            style={{
              flexGrow: 0,
              maxHeight: "100%",
              width: "100%",
              maxWidth: 480,
              alignSelf: "center",
              backgroundColor: colors.surface,
              borderRadius: 8,
            }}
            contentContainerStyle={{ padding: 20, gap: 16 }}
            accessibilityViewIsModal
            onAccessibilityEscape={cancel}
            testID="account-session-confirmation"
          >
            <Text
              ref={confirmationHeading}
              accessible
              accessibilityRole="header"
              style={styles.heading}
            >
              {selected?.current
                ? "Revoke this session?"
                : "Revoke device session?"}
            </Text>
            <Text style={styles.body}>
              {selected?.current
                ? "This device will be signed out of this workspace."
                : "The selected session will lose access to this workspace. Only that session will be revoked."}
            </Text>
            {selected ? (
              <Text style={styles.muted}>
                {platformName(selected)} session, signed in{" "}
                {displayTime(selected.created_at)}
              </Text>
            ) : null}
            <NativeButton
              testID="account-session-cancel"
              label="Keep session"
              secondary
              disabled={busy || disabled}
              onPress={cancel}
            />
            <NativeButton
              testID="account-session-confirm"
              label={busy ? "Revoking session" : "Revoke session"}
              disabled={busy || disabled}
              onPress={() => {
                void confirm();
              }}
            />
          </ScrollView>
        </View>
      </Modal>
    </>
  );
}
