import {
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { Alert, AppState, Text, View } from "react-native";
import type { RefObject } from "react";
import type { LeaveGuard } from "../types";
import Ionicons from "@expo/vector-icons/Ionicons";
import { NativeButton, NativeProgress } from "../../components/NativeControls";
import { Fact } from "../../components/Content";
import { colors, styles } from "../../components/theme";
import type { AuthorizedRequest } from "../../domain/repository";
import { createMatterFilesApi } from "../../files/api";
import { matchesSelection, uploadRestriction } from "../../files/contracts";
import type { MatterFile, MatterFileSelection } from "../../files/contracts";
import { createFilesController } from "../../files/controller";
import { createFilesInteractionActions } from "../../files/interaction-actions";
import {
  cleanupPickedFile,
  nativeFileStager,
  nativeFileMultipart,
} from "../../files/native";
import { uploadByteLimit, validateAsset } from "../../files/staging";
import { viewerFormat, attachmentViewerSource } from "../../viewer/contracts";
import type { ViewerSource } from "../../viewer/contracts";

export type FilesScreenProps = {
  request: AuthorizedRequest;
  companyId: string;
  userId: string;
  sessionKey: string;
  matterId: string;
  capabilities: readonly string[];
  selectedFile: MatterFileSelection | null;
  onChooseFile: (expectedLifecycleVersion: number) => void;
  onClearSelectedFile: () => void;
  onOpenFile: (source: ViewerSource) => void;
  guard: RefObject<LeaveGuard | null>;
};

export function FilesScreen(props: FilesScreenProps) {
  // An account, sign-in generation or parent change cannot reuse private state.
  return (
    <ScopedFilesScreen
      key={JSON.stringify([
        props.companyId,
        props.userId,
        props.sessionKey,
        props.matterId,
      ])}
      {...props}
    />
  );
}

function ScopedFilesScreen(props: FilesScreenProps) {
  const {
    request,
    companyId,
    userId,
    sessionKey,
    matterId,
    capabilities,
    selectedFile,
    onChooseFile,
    onClearSelectedFile,
  } = props;
  const requestRef = useRef(request);
  requestRef.current = request;
  const capabilitiesRef = useRef(capabilities);
  capabilitiesRef.current = capabilities;
  const scope = useMemo(
    () => ({ companyId, userId, sessionKey, matterId }),
    [companyId, userId, sessionKey, matterId],
  );
  const controller = useMemo(
    () =>
      createFilesController(
        createMatterFilesApi(
          (path, init) => requestRef.current(path, init),
          scope,
          nativeFileMultipart,
        ),
        nativeFileStager,
        scope,
        () => capabilitiesRef.current,
      ),
    [scope],
  );
  const snapshot = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
    controller.getSnapshot,
  );
  const interactions = useMemo(() => createFilesInteractionActions(controller), [controller]);
  const [visible, setVisible] = useState(25);
  const [privacyClosed, setPrivacyClosed] = useState(false);
  useEffect(() => {
    if (AppState.currentState !== "active") {
      controller.dispose();
      setPrivacyClosed(true);
      return;
    }
    void controller.activate();
    const subscription = AppState.addEventListener("change", (state) => {
      if (state !== "active") {
        controller.dispose();
        setPrivacyClosed(true);
      }
    });
    return () => {
      subscription.remove();
      controller.dispose();
    };
  }, [controller]);

  const busy =
    snapshot.upload.state === "preparing" ||
    snapshot.upload.state === "uploading";
  const unknown = snapshot.upload.state === "unknown";
  useEffect(() => {
    props.guard.current = (leave) => {
      const state = controller.getSnapshot().upload.state;
      const pending = state === "preparing" || state === "uploading";
      const outcomeUnknown = state === "unknown";
      if (pending) {
        Alert.alert(
          "Upload in progress",
          "Wait for the upload outcome, or use Stop waiting before leaving.",
        );
      } else if (outcomeUnknown || selectedFile) {
        Alert.alert(
          outcomeUnknown ? "Upload outcome unknown" : "Discard file selection?",
          outcomeUnknown
            ? "The file may already be saved. Leaving does not cancel it or upload it again. Reload Files before deciding whether another upload is needed."
            : "The selected file has not been uploaded.",
          [
            { text: "Stay", style: "cancel" },
            { text: "Leave Files", style: "destructive", onPress: leave },
          ],
        );
      } else leave();
    };
    return () => {
      props.guard.current = null;
    };
  }, [controller, selectedFile, props.guard]);
  const workspace =
    snapshot.view.state === "ready" ? snapshot.view.workspace : null;
  const scopedSelection =
    selectedFile && matchesSelection(selectedFile, scope) ? selectedFile : null;
  const restriction = workspace
    ? uploadRestriction(workspace, capabilities)
    : null;
  let selectionError: string | null =
    selectedFile && !scopedSelection
      ? "This file selection does not belong to the current account and matter. Clear it and choose the file again."
      : null;
  if (workspace && scopedSelection) {
    if (
      scopedSelection.expectedLifecycleVersion !==
      workspace.matter.lifecycle_version
    ) {
      selectionError =
        "The matter lifecycle changed since this file was chosen. Clear it and choose the file again.";
    } else
      try {
        validateAsset(scopedSelection.asset, workspace.storage);
      } catch {
        selectionError =
          "This file is unsupported, unavailable or exceeds the current size limit. Choose a PDF, Word, text, PNG or JPEG file within the limit.";
      }
  }
  const clearSelectionOwned = () => {
    try {
      if (selectedFile) cleanupPickedFile(selectedFile.asset);
    } catch {
      controller.recordCleanupFailure();
    } finally {
      onClearSelectedFile();
    }
  };
  const clearSelection = () => interactions.clear(clearSelectionOwned);
  const upload = async () => {
    if (!scopedSelection) return;
    await interactions.upload(scopedSelection, clearSelectionOwned);
  };

  if (privacyClosed || snapshot.view.state === "inactive")
    return <View testID="files-inactive" />;
  return (
    <View testID="matter-files" style={{ gap: 16, minWidth: 0 }}>
      <Text accessibilityRole="header" style={styles.heading}>
        Files
      </Text>
      {snapshot.view.state === "loading" ? (
        <View
          testID="files-loading"
          accessibilityLiveRegion="polite"
          style={{ gap: 12 }}
        >
          <NativeProgress />
          <Text style={styles.muted}>Loading current files and access</Text>
        </View>
      ) : snapshot.view.state === "error" ? (
        <View
          testID={
            snapshot.view.error.kind === "restricted"
              ? "files-restricted"
              : "files-error"
          }
          style={{ gap: 8 }}
        >
          <Text accessibilityRole="alert" style={styles.heading}>
            {snapshot.view.error.title}
          </Text>
          <Text style={styles.body}>{snapshot.view.error.message}</Text>
        </View>
      ) : workspace ? (
        <>
          <Text testID="files-matter-code" style={styles.label}>
            {workspace.matter.matter_code}
          </Text>
          <Text testID="files-matter-title" style={styles.body}>
            {workspace.matter.title}
          </Text>
          <Text testID="files-matter-status" style={styles.status}>
            {workspace.matter.status}
          </Text>
          <Text testID="files-scan-evidence" style={styles.muted}>
            The server does not expose a separate malware-scan receipt. Text
            processing status is not a clean-scan result.
          </Text>
          {workspace.attachments.length === 0 ? (
            <View testID="files-empty" style={{ paddingVertical: 16, gap: 8 }}>
              <Text style={styles.heading}>No files attached</Text>
              <Text style={styles.muted}>
                No attachments were returned for this matter.
              </Text>
            </View>
          ) : (
            <View testID="files-list">
              <Text testID="files-count" style={styles.label}>
                {workspace.attachments.length}{" "}
                {workspace.attachments.length === 1 ? "file" : "files"}
              </Text>
              {workspace.attachments.slice(0, visible).map((file) => (
                <FileRow
                  key={file.id}
                  file={file}
                  open={() =>
                    props.onOpenFile(attachmentViewerSource(scope, file))
                  }
                  supported={["pdf", "image", "text"].includes(
                    viewerFormat(attachmentViewerSource(scope, file))?.kind ||
                      "",
                  )}
                />
              ))}
              {workspace.attachments.length > visible ? (
                <NativeButton
                  testID="files-more"
                  label="Show more files"
                  secondary
                  onPress={() => setVisible((count) => count + 25)}
                />
              ) : null}
            </View>
          )}
          {restriction ? (
            <Text testID="files-upload-restricted" style={styles.muted}>
              {restriction}
            </Text>
          ) : (
            <View style={{ gap: 12 }}>
              <Text style={styles.label}>
                Current upload limit:{" "}
                {formatBytes(uploadByteLimit(workspace.storage))}
              </Text>
              {scopedSelection ? (
                <View testID="files-selection" style={{ gap: 8 }}>
                  <Text style={styles.body}>{scopedSelection.asset.name}</Text>
                  <Text style={styles.label}>
                    {scopedSelection.asset.size === undefined
                      ? "Size will be checked before upload"
                      : formatBytes(scopedSelection.asset.size)}
                  </Text>
                  <Text style={styles.muted}>
                    Upload to {workspace.matter.matter_code}
                  </Text>
                  <NativeButton
                    testID="files-upload"
                    label="Upload file"
                    disabled={
                      busy ||
                      unknown ||
                      !!selectionError ||
                      snapshot.cleanupFailed
                    }
                    onPress={() => {
                      void upload();
                    }}
                  />
                </View>
              ) : null}
              {selectedFile ? (
                <NativeButton
                  testID="files-selection-clear"
                  label="Clear selection"
                  secondary
                  disabled={busy}
                  onPress={clearSelection}
                />
              ) : null}
              {selectionError ? (
                <Text
                  testID="files-selection-error"
                  accessibilityRole="alert"
                  style={styles.body}
                >
                  {selectionError}
                </Text>
              ) : null}
              <NativeButton
                testID="files-choose"
                label={selectedFile ? "Choose another file" : "Choose file"}
                secondary={!!selectedFile}
                disabled={busy || unknown || snapshot.cleanupFailed}
                onPress={() => interactions.choose(() => {
                  controller.clearOutcome();
                  onChooseFile(workspace.matter.lifecycle_version);
                })}
              />
            </View>
          )}
        </>
      ) : null}
      {snapshot.upload.state !== "idle" ? (
        <View
          testID={`files-upload-${snapshot.upload.state}`}
          accessibilityLiveRegion="polite"
          style={{ gap: 8 }}
        >
          {busy ? <NativeProgress /> : null}
          <Text
            accessibilityRole={
              snapshot.upload.state === "rejected" || unknown ? "alert" : "text"
            }
            style={styles.body}
          >
            {snapshot.upload.message}
          </Text>
          {snapshot.upload.preparationStep ? (
            <View collapsable={false} testID={`files-preparation-failure-${snapshot.upload.preparationStep}`} style={{ width: 1, height: 1 }} />
          ) : null}
          {busy ? (
            <NativeButton
              testID="files-upload-cancel"
              label={
                snapshot.upload.state === "uploading"
                  ? "Stop waiting for upload"
                  : "Cancel upload"
              }
              secondary
              onPress={controller.cancel}
            />
          ) : null}
        </View>
      ) : null}
      {snapshot.cleanupFailed ? (
        <Text
          testID="files-cleanup-error"
          accessibilityRole="alert"
          style={styles.body}
        >
          Temporary-file removal could not be confirmed. Further uploads are
          blocked. Sign out and restart CaseOps to run cleanup.
        </Text>
      ) : null}
      <NativeButton
        testID="files-reload"
        label="Reload files"
        secondary
        disabled={busy}
        onPress={() => {
          setVisible(25);
          void controller.reload();
        }}
      />
    </View>
  );
}

const processingLabels: Record<MatterFile["processing_status"], string> = {
  pending: "Queued for text processing",
  indexed: "Text indexed",
  needs_ocr: "OCR needed",
  failed: "Text processing failed",
};
function FileRow({
  file,
  open,
  supported,
}: {
  file: MatterFile;
  open: () => void;
  supported: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <View
      testID={`files-row-${file.id}`}
      style={[styles.divider, { paddingVertical: 16, gap: 8, minWidth: 0 }]}
    >
      <View
        style={[styles.row, { alignItems: "flex-start", flexWrap: "nowrap" }]}
      >
        <Ionicons
          name="document-text-outline"
          size={24}
          color={colors.muted}
          accessibilityElementsHidden
          importantForAccessibility="no"
        />
        <View style={{ flex: 1, minWidth: 0, gap: 4 }}>
          <Text
            testID={`files-name-${file.id}`}
            style={[styles.body, { fontWeight: "600" }]}
          >
            {file.original_filename}
          </Text>
          <Text style={styles.label}>
            {formatBytes(file.size_bytes)}
            {file.content_type
              ? ` | ${file.content_type}`
              : " | File type not supplied"}
          </Text>
          <Text testID={`files-processing-${file.id}`} style={styles.muted}>
            {processingLabels[file.processing_status]}
          </Text>
          <Text style={styles.label}>Uploaded {file.created_at}</Text>
        </View>
      </View>
      <NativeButton
        testID={`files-open-${file.id}`}
        label="Open file"
        secondary
        disabled={!supported}
        onPress={open}
      />
      <NativeButton
        testID={`files-source-${file.id}`}
        label={expanded ? "Hide source details" : "Source details"}
        secondary
        onPress={() => setExpanded((value) => !value)}
      />
      {expanded ? (
        <View
          testID={`files-source-details-${file.id}`}
          style={{ gap: 4, minWidth: 0 }}
        >
          <Fact label="Source" value="Original Matter attachment" />
          <Fact label="Attachment ID" value={file.id} />
          <Fact
            label="Source SHA-256"
            value={file.sha256_hex}
            testID={`files-hash-${file.id}`}
          />
          <Fact label="Uploaded by" value={file.uploaded_by_name} />
          <Fact label="Document type" value={file.document_type} />
          <Fact label="Lifecycle stage" value={file.lifecycle_stage} />
          <Fact label="Document date" value={file.document_date} />
          <Fact
            label="Linked court order ID"
            value={file.linked_court_order_id}
          />
          <Fact label="Linked hearing ID" value={file.hearing_id} />
          {!supported ? (
            <Text
              testID={`files-viewer-unavailable-${file.id}`}
              style={styles.muted}
            >
              This file type is not supported by the private reader. No file is
              opened or shared with another app.
            </Text>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}
function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
}
