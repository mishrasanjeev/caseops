import React, {
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import {
  AppState,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import Ionicons from "@expo/vector-icons/Ionicons";
import { getRandomBytes } from "expo-crypto";
import { WebView } from "react-native-webview";
import { colors, styles, target } from "../components/theme";
import { displayAcknowledged, PrivateViewerController } from "./controller.ts";
import type { RendererAcknowledgement } from "./controller.ts";
import { VIEWER_LIMITS, sourceKey, viewerFormat } from "./contracts.ts";
import type { ViewerContent, ViewerPorts, ViewerSource } from "./contracts.ts";
import { encodeBase64 } from "./encoding.ts";
import { createViewerHtml } from "./html.ts";
import {
  PRIVATE_WEBVIEW_POLICY,
  ZOOMS,
  allowViewerNavigation,
  decodeRendererEvent,
} from "./security.ts";

export type ViewerPosition = { sourceKey: string; page: number; zoom: number };
export type PrivateDocumentViewerProps = {
  source: ViewerSource;
  ports: ViewerPorts;
  onClose: () => void;
  initialPosition?: ViewerPosition;
  onPositionChange?: (position: ViewerPosition) => void;
};
type Position = { page: number; pages: number; zoom: number };
type DisplayedPosition = Position & {
  acknowledgement: RendererAcknowledgement | null;
};

function IconButton({
  icon,
  label,
  testID,
  disabled,
  onPress,
}: {
  icon: React.ComponentProps<typeof Ionicons>["name"];
  label: string;
  testID: string;
  disabled?: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: !!disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        local.button,
        { opacity: disabled ? 0.35 : pressed ? 0.65 : 1 },
      ]}
    >
      <Ionicons
        name={icon}
        size={24}
        color={colors.ink}
        accessibilityElementsHidden
        importantForAccessibility="no"
      />
    </Pressable>
  );
}

export function PrivateDocumentViewer(props: PrivateDocumentViewerProps) {
  return <ViewerInstance key={sourceKey(props.source)} {...props} />;
}
function ViewerInstance({
  source,
  ports,
  onClose,
  initialPosition,
  onPositionChange,
}: PrivateDocumentViewerProps) {
  const hiddenCommit = useRef<(() => void) | null>(null);
  const key = sourceKey(source);
  const controller = useMemo(
    () =>
      new PrivateViewerController(
        source,
        ports,
        undefined,
        () =>
          new Promise<void>((resolve) => {
            hiddenCommit.current = resolve;
          }),
      ),
    [key, ports],
  );
  const state = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
  );
  const liveController = useRef(controller);
  liveController.current = controller;
  useLayoutEffect(() => {
    if (state.phase !== "ready") {
      hiddenCommit.current?.();
      hiddenCommit.current = null;
    }
  }, [state.revision, state.phase]);
  const initial =
    initialPosition?.sourceKey === key ? initialPosition : undefined;
  const [position, setPosition] = useState<DisplayedPosition>({
    acknowledgement: null,
    page:
      initial && Number.isSafeInteger(initial.page) && initial.page > 0
        ? initial.page
        : 1,
    pages: 1,
    zoom:
      initial && ZOOMS.includes(initial.zoom as (typeof ZOOMS)[number])
        ? initial.zoom
        : 1,
  });
  const navigate = useRef<(page: number, zoom: number) => void>(() => {});
  const positionRef = useRef(position);
  positionRef.current = position;
  useEffect(() => {
    if (AppState.currentState === "active") void controller.open();
    else controller.purge("background");
    const listener = AppState.addEventListener("change", (next) => {
      if (next !== "active") controller.purge("background");
    });
    return () => {
      listener.remove();
      controller.dispose();
      hiddenCommit.current?.();
      hiddenCommit.current = null;
    };
  }, [controller]);
  const changed = (next: Position, revision: number) => {
    const acknowledgement = { controller, revision };
    if (
      liveController.current !== controller ||
      !displayAcknowledged(controller, acknowledgement)
    )
      return;
    setPosition({ ...next, acknowledgement });
    onPositionChange?.({ sourceKey: key, page: next.page, zoom: next.zoom });
  };
  const close = () => {
    controller.purge("closed");
    onClose();
  };
  const kind = viewerFormat(source)?.kind;
  const displayReady = displayAcknowledged(
    controller,
    position.acknowledgement,
  );
  const zoomIndex = ZOOMS.indexOf(position.zoom as (typeof ZOOMS)[number]);
  return (
    <View style={local.root} testID="private-document-viewer">
      <View style={local.header}>
        <IconButton
          icon="arrow-back"
          label="Return to Files"
          testID="viewer-close"
          onPress={close}
        />
        <Text
          style={[styles.heading, local.filename]}
          testID="viewer-filename"
          numberOfLines={2}
        >
          {source.filename}
        </Text>
      </View>
      <View style={local.toolbar} testID="viewer-toolbar">
        <IconButton
          icon="chevron-back"
          label="Previous page or text segment"
          testID="viewer-previous"
          disabled={!displayReady || position.page <= 1}
          onPress={() => navigate.current(position.page - 1, position.zoom)}
        />
        <Text
          style={styles.label}
          testID="viewer-position"
          accessibilityLiveRegion="polite"
        >
          {displayReady
            ? `${["text", "docx-text"].includes(kind || "") ? "Segment" : "Page"} ${position.page} of ${position.pages}`
            : state.phase === "ready"
              ? "Opening document"
              : "No page displayed"}
        </Text>
        <IconButton
          icon="chevron-forward"
          label="Next page or text segment"
          testID="viewer-next"
          disabled={!displayReady || position.page >= position.pages}
          onPress={() => navigate.current(position.page + 1, position.zoom)}
        />
        <View style={local.zoom}>
          <IconButton
            icon="remove"
            label="Zoom out"
            testID="viewer-zoom-out"
            disabled={!displayReady || zoomIndex <= 0}
            onPress={() =>
              navigate.current(position.page, ZOOMS[zoomIndex - 1])
            }
          />
          <Text testID="viewer-zoom" style={styles.label}>
            {Math.round(position.zoom * 100)}%
          </Text>
          <IconButton
            icon="add"
            label="Zoom in"
            testID="viewer-zoom-in"
            disabled={!displayReady || zoomIndex === ZOOMS.length - 1}
            onPress={() =>
              navigate.current(position.page, ZOOMS[zoomIndex + 1])
            }
          />
        </View>
      </View>
      {state.phase === "ready" ? (
        <Content
          key={state.revision}
          controller={controller}
          position={positionRef.current}
          changed={(next) => changed(next, state.revision)}
          navigate={navigate}
        />
      ) : (
        <View
          style={local.message}
          testID={`viewer-${state.phase}`}
          accessibilityLiveRegion="polite"
        >
          <Text
            style={styles.body}
            accessibilityRole={
              ["blocked", "unsupported"].includes(state.phase)
                ? "alert"
                : undefined
            }
          >
            {state.message || "Checking current document access"}
          </Text>
        </View>
      )}
    </View>
  );
}

function Content({
  controller,
  position,
  changed,
  navigate,
}: {
  controller: PrivateViewerController;
  position: Position;
  changed: (position: Position) => void;
  navigate: React.MutableRefObject<(page: number, zoom: number) => void>;
}) {
  const [content] = useState(() => controller.copyContent());
  useEffect(
    () => () => {
      content?.bytes.fill(0);
      navigate.current = () => {};
    },
    [content, navigate],
  );
  if (!content) return null;
  return ["text", "docx-text"].includes(content.kind) ? (
    <TextReader
      content={content}
      position={position}
      changed={changed}
      navigate={navigate}
    />
  ) : (
    <IsolatedRenderer
      content={content}
      controller={controller}
      position={position}
      changed={changed}
      navigate={navigate}
    />
  );
}
function TextReader({
  content,
  position,
  changed,
  navigate,
}: {
  content: ViewerContent;
  position: Position;
  changed: (position: Position) => void;
  navigate: React.MutableRefObject<(page: number, zoom: number) => void>;
}) {
  const [text] = useState(() => {
    const decoded = new TextDecoder("utf-8", { fatal: true }).decode(
      content.bytes,
    );
    content.bytes.fill(0);
    if (content.kind !== "docx-text") return decoded;
    const docx = JSON.parse(decoded) as {
      paragraphs: string[];
      tableRows: string[][];
    };
    return [
      ...docx.paragraphs,
      ...docx.tableRows.map((row) => row.join(" | ")),
    ].join("\n\n");
  });
  const pages = Math.max(1, Math.ceil(text.length / 10_000));
  const [current, setCurrent] = useState({
    ...position,
    page: Math.min(position.page, pages),
    pages,
  });
  useEffect(() => {
    changed(current);
    navigate.current = (page, zoom) => {
      const next = { page: Math.max(1, Math.min(page, pages)), pages, zoom };
      setCurrent(next);
      changed(next);
    };
    // Only numeric reading position survives a lease renewal.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pages]);
  return (
    <ScrollView
      style={local.reader}
      key={current.page}
      testID="viewer-text-reader"
      contentContainerStyle={local.textContent}
    >
      {content.kind === "docx-text" ? (
        <Text testID="viewer-docx-limitation" style={styles.muted}>
          Extracted text preview. Original layout, images and page order are not
          preserved.
        </Text>
      ) : null}
      <Text
        testID="viewer-text"
        selectable={false}
        style={[
          styles.body,
          { fontSize: 16 * current.zoom, lineHeight: 24 * current.zoom },
        ]}
      >
        {text.slice((current.page - 1) * 10_000, current.page * 10_000) ||
          "No extracted text is available."}
      </Text>
    </ScrollView>
  );
}
function IsolatedRenderer({
  content,
  controller,
  position,
  changed,
  navigate,
}: {
  content: ViewerContent;
  controller: PrivateViewerController;
  position: Position;
  changed: (position: Position) => void;
  navigate: React.MutableRefObject<(page: number, zoom: number) => void>;
}) {
  const [id] = useState(() =>
    Array.from(getRandomBytes(16), (byte) =>
      byte.toString(16).padStart(2, "0"),
    ).join(""),
  );
  const html = useMemo(() => createViewerHtml(id), [id]);
  const webview = useRef<WebView<unknown>>(null);
  const transfer = useRef({
    started: false,
    waiting: -1,
    offset: 0,
    ended: false,
  });
  const latestChanged = useRef(changed);
  latestChanged.current = changed;
  const send = (command: Record<string, unknown>) =>
    webview.current?.postMessage(JSON.stringify({ ...command, id }));
  useEffect(() => {
    const timer = setTimeout(() => {
      if (!rendered.current) controller.rendererFailed();
    }, VIEWER_LIMITS.renderMs);
    navigate.current = (page, zoom) => send({ type: "navigate", page, zoom });
    return () => {
      clearTimeout(timer);
      send({ type: "purge" });
      content.bytes.fill(0);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const rendered = useRef(false);
  return (
    <WebView<unknown>
      ref={webview}
      testID="viewer-isolated-renderer"
      style={local.reader}
      {...PRIVATE_WEBVIEW_POLICY}
      javaScriptEnabled
      source={{ html, baseUrl: "about:blank" }}
      onShouldStartLoadWithRequest={allowViewerNavigation}
      onNavigationStateChange={(event) => {
        if (event.url !== "about:blank") controller.rendererFailed();
      }}
      onOpenWindow={() => controller.rendererFailed()}
      onFileDownload={() => controller.rendererFailed()}
      onError={() => controller.rendererFailed()}
      onContentProcessDidTerminate={() => controller.rendererFailed()}
      onRenderProcessGone={() => controller.rendererFailed()}
      onMessage={(event) => {
        try {
          const message = decodeRendererEvent(event.nativeEvent.data, id);
          const state = transfer.current;
          if (message.type === "error" || message.type === "expired") {
            controller.rendererFailed();
            return;
          }
          if (message.type === "ready") {
            if (state.started) throw new Error("Repeated renderer admission");
            state.started = true;
            const ttl = controller.getSnapshot().expiresAt - Date.now();
            if (ttl <= 0) throw new Error("Expired viewer");
            send({
              type: "begin",
              kind: content.kind,
              mime: content.mime,
              length: content.bytes.length,
              ttl,
              page: position.page,
              zoom: position.zoom,
            });
          } else if (message.type === "ack") {
            if (
              !state.started ||
              state.ended ||
              message.sequence !== state.waiting
            )
              throw new Error("Unexpected transfer acknowledgement");
            if (state.offset === content.bytes.length) {
              state.ended = true;
              content.bytes.fill(0);
              send({ type: "end" });
              return;
            }
            const end = Math.min(
              content.bytes.length,
              state.offset + VIEWER_LIMITS.chunkBytes,
            );
            const chunk = content.bytes.subarray(state.offset, end);
            send({
              type: "chunk",
              sequence: ++state.waiting,
              data: encodeBase64(chunk),
            });
            chunk.fill(0);
            state.offset = end;
          } else if (message.type === "page") {
            if (!state.ended) throw new Error("Unexpected page event");
            rendered.current = true;
            latestChanged.current({
              page: message.page,
              pages: message.pages,
              zoom: message.zoom,
            });
          }
        } catch {
          controller.rendererFailed();
        }
      }}
    />
  );
}

const local = StyleSheet.create({
  root: {
    flex: 1,
    minWidth: 0,
    minHeight: 240,
    backgroundColor: colors.surface,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    minWidth: 0,
    borderBottomWidth: 1,
    borderColor: colors.line,
    padding: 8,
    gap: 8,
  },
  filename: { flex: 1, minWidth: 0, fontSize: 18, lineHeight: 24 },
  toolbar: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    padding: 4,
    minWidth: 0,
    borderBottomWidth: 1,
    borderColor: colors.line,
  },
  zoom: { flexDirection: "row", alignItems: "center", marginLeft: "auto" },
  button: {
    width: target,
    height: target,
    alignItems: "center",
    justifyContent: "center",
  },
  message: { flex: 1, padding: 20, justifyContent: "center" },
  reader: { flex: 1, minWidth: 0, backgroundColor: colors.background },
  textContent: { padding: 16, gap: 16 },
});
