import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  BackHandler,
  PanResponder,
  Platform,
  Pressable,
  Text,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import Ionicons from "@expo/vector-icons/Ionicons";
import { colors, styles, target } from "../components/theme";
import type { Matter, MatterRef, WorkItem } from "../domain/contracts";
import { createRepository } from "../domain/repository";
import { createSourceRecordsRepository } from "../domain/source-records";
import type { SourceLocator, SourceRef } from "../domain/source-records";
import { createMatterFilesApi } from "../files/api";
import { attachmentViewerSource } from "../viewer/contracts";
import type { ViewerSource, ViewerPorts } from "../viewer/contracts";
import { PrivateDocumentViewer } from "../viewer/PrivateDocumentViewer";
import { useResource } from "./useResource";

import type {
  LeaveGuard,
  MatterSection,
  MobileApplicationProps,
} from "./types";

import { TodayScreen } from "./screens/TodayScreen";

import { MattersScreen } from "./screens/MattersScreen";

import { CalendarScreen } from "./screens/CalendarScreen";

import { WorkScreen } from "./screens/WorkScreen";

import { MatterScreen } from "./screens/MatterScreen";

import { NoteEditor } from "./screens/NoteEditor";

import { DraftScreen } from "./screens/DraftScreen";

import { AccountScreen } from "./screens/AccountScreen";
import {
  SourceRecordsScreen,
  SourceRecordDetailScreen,
} from "./screens/SourceRecordsScreen";

export type { MobileApplicationProps } from "./types";

type Tab = "today" | "matters" | "calendar" | "work";

type Route =
  | { type: "home" }
  | { type: "matter"; matterId: string; section: MatterSection }
  | { type: "note"; matter: Matter }
  | { type: "draft"; matterId: string; draftId: string }
  | { type: "source-list" }
  | { type: "viewer"; source: ViewerSource }
  | { type: "source"; source: SourceRef; locator?: SourceLocator }
  | { type: "account" };

const tabs: {
  key: Tab;
  label: string;
  icon: React.ComponentProps<typeof Ionicons>["name"];
}[] = [
  { key: "today", label: "Today", icon: "today-outline" },
  { key: "matters", label: "Matters", icon: "briefcase-outline" },
  { key: "calendar", label: "Calendar", icon: "calendar-outline" },
  { key: "work", label: "Work", icon: "checkbox-outline" },
];

export function MobileApplication(props: MobileApplicationProps) {
  return (
    <ApplicationContent
      key={`${props.identity.company.id}:${props.identity.user.id}`}
      {...props}
    />
  );
}

export default MobileApplication;

function ApplicationContent({
  request,
  identity,
  sessionKey,
  initialFilesMatterId,
  selectedFile,
  onChooseFile,
  onClearSelectedFile,
  viewer,
  onSignOut,
}: MobileApplicationProps) {
  const repository = useMemo(() => createRepository(request), [request]);
  const sources = useMemo(
    () =>
      createSourceRecordsRepository(
        request,
        identity.company.id,
        identity.capabilities,
      ),
    [request, identity.company.id, identity.capabilities],
  );
  const viewerPorts = useMemo<ViewerPorts>(
    () => ({
      ...viewer,
      revalidate: async (source, { signal }) => {
        if (
          source.companyId !== identity.company.id ||
          source.userId !== identity.user.id ||
          source.sessionKey !== sessionKey
        )
          throw new Error("The private session changed.");
        const scope = {
          companyId: identity.company.id,
          userId: identity.user.id,
          sessionKey,
          matterId: source.matterId,
        };
        const workspace = await createMatterFilesApi(request, scope).workspace(
          signal,
        );
        const file = workspace.attachments.find(
          (item) => item.id === source.attachmentId,
        );
        if (!file)
          throw new Error("The private source is no longer available.");
        return attachmentViewerSource(scope, file);
      },
    }),
    [viewer, request, identity.company.id, identity.user.id, sessionKey],
  );
  const [tab, setTab] = useState<Tab>("today");
  const [stacks, setStacks] = useState<Record<Tab, Route[]>>({
    today: initialFilesMatterId
      ? [
          { type: "home" },
          { type: "matter", matterId: initialFilesMatterId, section: "Files" },
        ]
      : [{ type: "home" }],
    matters: [{ type: "home" }],
    calendar: [{ type: "home" }],
    work: [{ type: "home" }],
  });
  const stack = stacks[tab],
    route = stack[stack.length - 1];
  useEffect(() => {
    if (
      selectedFile &&
      !(route.type === "matter" && route.matterId === selectedFile.matterId)
    )
      onClearSelectedFile();
  }, [route, selectedFile, onClearSelectedFile]);
  const leaveGuard = useRef<LeaveGuard | null>(null);
  const guarded = (action: () => void) =>
    leaveGuard.current ? leaveGuard.current(action) : action();
  const push = (next: Route) =>
    guarded(() =>
      setStacks((previous) => ({
        ...previous,
        [tab]: [...previous[tab], next],
      })),
    );
  const pop = useCallback(() => {
    if (stack.length > 1)
      guarded(() =>
        setStacks((previous) => ({
          ...previous,
          [tab]: previous[tab].slice(0, -1),
        })),
      );
  }, [tab, stack.length]);
  const [revision, setRevision] = useState(0);
  const today = useResource(`today:${revision}`, (signal) =>
    repository.today(signal),
  );
  useEffect(() => {
    const subscription = BackHandler.addEventListener(
      "hardwareBackPress",
      () => {
        if (stack.length > 1) {
          pop();
          return true;
        }
        if (tab !== "today") {
          guarded(() => setTab("today"));
          return true;
        }
        return false;
      },
    );
    return () => subscription.remove();
  }, [pop, stack.length, tab]);
  const backRef = useRef(pop);
  backRef.current = pop;
  const swipe = useMemo(
    () =>
      PanResponder.create({
        onMoveShouldSetPanResponder: (event, gesture) =>
          Platform.OS === "ios" &&
          event.nativeEvent.pageX - gesture.dx < 24 &&
          gesture.dx > 30 &&
          Math.abs(gesture.dy) < 20,
        onPanResponderRelease: (_event, gesture) => {
          if (gesture.dx > 70) backRef.current();
        },
      }),
    [],
  );
  const openMatter = (matter: MatterRef, section: MatterSection = "Summary") =>
    push({ type: "matter", matterId: matter.id, section });
  const openWork = (item: WorkItem) =>
    item.kind === "draft"
      ? push({ type: "draft", matterId: item.matter.id, draftId: item.id })
      : openMatter(item.matter, item.kind === "task" ? "Work" : "Summary");
  const completeNote = () => {
    leaveGuard.current = null;
    setRevision((value) => value + 1);
    setStacks((previous) => ({
      ...previous,
      [tab]: previous[tab]
        .slice(0, -1)
        .map((item) =>
          item.type === "matter" ? { ...item, section: "Activity" } : item,
        ),
    }));
  };
  return (
    <SafeAreaView
      style={styles.fill}
      edges={["top", "left", "right", "bottom"]}
    >
      <View style={styles.fill} {...swipe.panHandlers}>
        {route.type !== "viewer" ? (
          <View
            style={[
              styles.divider,
              {
                paddingHorizontal: 16,
                paddingVertical: 8,
                flexDirection: "row",
                alignItems: "center",
                gap: 8,
              },
            ]}
          >
            {stack.length > 1 ? (
              <Pressable
                onPress={pop}
                accessibilityRole="button"
                accessibilityLabel="Back"
                testID="back"
                style={{
                  minWidth: target,
                  minHeight: target,
                  justifyContent: "center",
                  alignItems: "center",
                }}
              >
                <Ionicons name="chevron-back" size={26} color={colors.brand} />
              </Pressable>
            ) : null}
            <View style={{ flex: 1, minWidth: 0 }}>
              <Text style={[styles.heading, { fontWeight: "600" }]}>
                CaseOps
              </Text>
              <Text style={styles.label}>{identity.company.name}</Text>
            </View>
            {route.type !== "account" ? (
              <Pressable
                testID="account-open"
                onPress={() => push({ type: "account" })}
                accessibilityRole="button"
                accessibilityLabel="Account"
                style={{
                  minWidth: target,
                  minHeight: target,
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 2,
                }}
              >
                <Ionicons
                  name="person-circle-outline"
                  size={24}
                  color={colors.brand}
                />
                <Text style={[styles.label, { color: colors.brand }]}>
                  Account
                </Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}
        <View style={styles.fill}>
          <View
            style={[
              styles.fill,
              (route.type !== "home" || tab !== "today") && { display: "none" },
            ]}
          >
            <TodayScreen
              resource={today.resource}
              reload={today.reload}
              openWork={openWork}
              search={() => setTab("matters")}
            />
          </View>
          <View
            style={[
              styles.fill,
              (route.type !== "home" || tab !== "matters") && {
                display: "none",
              },
            ]}
          >
            <MattersScreen
              repository={repository}
              active={tab === "matters" && route.type === "home"}
              openMatter={openMatter}
            />
          </View>
          <View
            style={[
              styles.fill,
              (route.type !== "home" || tab !== "calendar") && {
                display: "none",
              },
            ]}
          >
            <CalendarScreen
              repository={repository}
              active={tab === "calendar" && route.type === "home"}
              openMatter={openMatter}
            />
          </View>
          <View
            style={[
              styles.fill,
              (route.type !== "home" || tab !== "work") && { display: "none" },
            ]}
          >
            <WorkScreen
              resource={today.resource}
              reload={today.reload}
              openWork={openWork}
            />
          </View>
          {route.type === "note" ? (
            <NoteEditor
              repository={repository}
              matter={route.matter}
              guard={leaveGuard}
              onDone={completeNote}
              onCancel={pop}
            />
          ) : route.type === "matter" ? (
            <MatterScreen
              key={`${route.matterId}:${revision}`}
              repository={repository}
              matterId={route.matterId}
              initialSection={route.section}
              canWrite={identity.capabilities.includes("matters:write")}
              onSectionChange={(section) =>
                setStacks((previous) => ({
                  ...previous,
                  [tab]: previous[tab].map((item, index) =>
                    index === previous[tab].length - 1 && item.type === "matter"
                      ? { ...item, section }
                      : item,
                  ),
                }))
              }
              files={{
                request,
                companyId: identity.company.id,
                userId: identity.user.id,
                sessionKey,
                matterId: route.matterId,
                capabilities: identity.capabilities,
                selectedFile,
                onChooseFile: (version) =>
                  onChooseFile(route.matterId, version),
                onClearSelectedFile,
                onOpenFile: (source) => push({ type: "viewer", source }),
                guard: leaveGuard,
              }}
              addNote={(matter) => push({ type: "note", matter })}
              openDraft={(draftId) =>
                push({ type: "draft", matterId: route.matterId, draftId })
              }
            />
          ) : route.type === "draft" ? (
            <DraftScreen
              repository={repository}
              matterId={route.matterId}
              draftId={route.draftId}
            />
          ) : route.type === "account" ? (
            <View style={styles.fill}>
              <NativeSourcesButton
                onPress={() => push({ type: "source-list" })}
              />
              <AccountScreen
                identity={identity}
                request={request}
                onSignOut={onSignOut}
              />
            </View>
          ) : route.type === "source-list" ? (
            <SourceRecordsScreen
              repository={sources}
              kind="ip_docket"
              active
              openSource={(source, locator) =>
                push({ type: "source", source, locator })
              }
            />
          ) : route.type === "source" ? (
            <SourceRecordDetailScreen
              repository={sources}
              source={route.source}
              locator={route.locator}
            />
          ) : route.type === "viewer" ? (
            <PrivateDocumentViewer
              source={route.source}
              ports={viewerPorts}
              onClose={pop}
            />
          ) : null}
        </View>
        {route.type !== "note" && route.type !== "viewer" ? (
          <View
            style={{
              flexDirection: "row",
              borderTopWidth: 1,
              borderTopColor: colors.line,
              backgroundColor: colors.background,
              paddingTop: 4,
            }}
          >
            {tabs.map((item) => (
              <Pressable
                testID={`tab-${item.key}`}
                key={item.key}
                accessibilityRole="tab"
                accessibilityState={{ selected: tab === item.key }}
                onPress={() => guarded(() => setTab(item.key))}
                style={{
                  flex: 1,
                  minWidth: 0,
                  minHeight: 72,
                  paddingHorizontal: 2,
                  paddingVertical: 8,
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 4,
                }}
              >
                <View
                  style={{
                    width: 56,
                    height: 28,
                    borderRadius: Platform.OS === "android" ? 16 : 6,
                    alignItems: "center",
                    justifyContent: "center",
                    backgroundColor:
                      tab === item.key ? colors.tonal : "transparent",
                  }}
                >
                  <Ionicons
                    name={item.icon}
                    size={22}
                    color={tab === item.key ? colors.brand : colors.muted}
                  />
                </View>
                <Text
                  style={{
                    color: tab === item.key ? colors.brand : colors.muted,
                    fontSize: 12,
                    lineHeight: 17,
                    textAlign: "center",
                    fontWeight: tab === item.key ? "600" : "400",
                    letterSpacing: 0,
                  }}
                >
                  {item.label}
                </Text>
              </Pressable>
            ))}
          </View>
        ) : null}
      </View>
    </SafeAreaView>
  );
}

function NativeSourcesButton({ onPress }: { onPress: () => void }) {
  return (
    <Pressable
      testID="account-ip-records"
      accessibilityRole="button"
      accessibilityLabel="Trademark portfolio"
      onPress={onPress}
      style={{
        minHeight: target,
        padding: 16,
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
      }}
    >
      <Ionicons
        name="shield-checkmark-outline"
        color={colors.brand}
        size={22}
      />
      <Text style={styles.body}>Trademark portfolio</Text>
      <Ionicons name="chevron-forward" color={colors.brand} size={18} />
    </Pressable>
  );
}
