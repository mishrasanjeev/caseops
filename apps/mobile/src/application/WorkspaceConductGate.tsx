import { useEffect, useRef, useState, type ReactNode } from "react";
import { Linking, ScrollView, Text, View } from "react-native";
import { NativeButton, NativeProgress } from "../components/NativeControls";
import { styles } from "../components/theme";
import {
  workspaceUsePolicyUrl,
  type WorkspaceConductRepository,
} from "../domain/workspace-conduct";
import { useResource } from "./useResource";

export function WorkspaceUseRulesLink({
  disabled = false,
}: {
  disabled?: boolean;
}) {
  const [unavailable, setUnavailable] = useState(false);
  const opening = useRef(false);
  return (
    <>
      <NativeButton
        testID="workspace-use-rules"
        label="Read workspace use rules"
        secondary
        disabled={disabled}
        onPress={() => {
          if (opening.current || disabled) return;
          opening.current = true;
          setUnavailable(false);
          void Linking.openURL(workspaceUsePolicyUrl)
            .catch(() => setUnavailable(true))
            .finally(() => {
              opening.current = false;
            });
        }}
      />
      {unavailable ? (
        <Text accessibilityRole="alert" style={styles.muted} selectable>
          Open {workspaceUsePolicyUrl} in your browser to read the rules.
        </Text>
      ) : null}
    </>
  );
}

export function WorkspaceConductGate({
  repository,
  action,
  children,
}: {
  repository: WorkspaceConductRepository;
  action: "notes" | "files";
  children: ReactNode;
}) {
  const { resource, reload } = useResource("workspace-use-policy", (signal) =>
    repository.current(signal),
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const flight = useRef<AbortController | null>(null);
  const live = useRef(resource);
  const mounted = useRef(false);
  live.current = resource;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      flight.current?.abort();
    };
  }, []);

  async function accept(displayedVersion: string) {
    const current = live.current;
    if (
      !mounted.current ||
      flight.current ||
      current.state !== "ready" ||
      current.data.version !== displayedVersion ||
      current.data.accepted_at !== null
    )
      return;
    const controller = new AbortController();
    flight.current = controller;
    setBusy(true);
    setError(false);
    try {
      await repository.accept(displayedVersion, controller.signal);
      if (!controller.signal.aborted) {
        live.current = { state: "loading" };
        reload();
      }
    } catch {
      if (!controller.signal.aborted) {
        live.current = { state: "loading" };
        setError(true);
        reload();
      }
    } finally {
      if (flight.current === controller) flight.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  if (resource.state === "ready" && resource.data.accepted_at !== null)
    return <>{children}</>;
  const body = (
    <View testID="workspace-use-gate" style={{ gap: 12 }}>
      <Text accessibilityRole="header" style={styles.heading}>
        Workspace use rules
      </Text>
      {resource.state === "loading" ? (
        <>
          <NativeProgress />
          <Text accessibilityLiveRegion="polite" style={styles.muted}>
            Checking the current rules…
          </Text>
        </>
      ) : resource.state === "error" ? (
        <>
          <Text accessibilityRole="alert" style={styles.body}>
            The current rules couldn’t be checked. Sharing is unavailable.
          </Text>
          <NativeButton label="Check again" onPress={reload} secondary />
        </>
      ) : (
        <>
          <Text style={styles.body}>
            Read and accept the current rules before sharing {action} in this
            workspace.
          </Text>
          <Text style={styles.muted}>Version {resource.data.version}</Text>
          {error ? (
            <Text accessibilityRole="alert" style={styles.body}>
              We couldn’t confirm your acceptance. Review the current rules
              before trying again.
            </Text>
          ) : null}
          <WorkspaceUseRulesLink disabled={busy} />
          <NativeButton
            testID="workspace-use-accept"
            label={
              busy ? "Saving acceptance…" : "I agree to the workspace rules"
            }
            disabled={busy}
            onPress={() => void accept(resource.data.version)}
          />
        </>
      )}
    </View>
  );
  return action === "notes" ? (
    <ScrollView contentContainerStyle={styles.content}>{body}</ScrollView>
  ) : (
    body
  );
}
