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

export type { MobileApplicationProps } from "./types";

type Tab = "today" | "matters" | "calendar" | "work";

type Route =
  | { type: "home" }
  | { type: "matter"; matterId: string; section: MatterSection }
  | { type: "note"; matter: Matter }
  | { type: "draft"; matterId: string; draftId: string }
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
  onSignOut,
}: MobileApplicationProps) {
  const repository = useMemo(() => createRepository(request), [request]);
  const [tab, setTab] = useState<Tab>("today");
  const [stacks, setStacks] = useState<Record<Tab, Route[]>>({
    today: [{ type: "home" }],
    matters: [{ type: "home" }],
    calendar: [{ type: "home" }],
    work: [{ type: "home" }],
  });
  const stack = stacks[tab],
    route = stack[stack.length - 1];
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
            <Text style={[styles.heading, { fontWeight: "600" }]}>CaseOps</Text>
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
            <AccountScreen identity={identity} onSignOut={onSignOut} />
          ) : null}
        </View>
        {route.type !== "note" ? (
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
