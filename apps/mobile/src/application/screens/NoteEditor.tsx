import React, { useEffect, useRef, useState } from "react";
import {
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { NativeButton } from "../../components/NativeControls";
import { colors, styles } from "../../components/theme";
import type { Matter } from "../../domain/contracts";
import { createNoteSubmission, verifySavedNote } from "../../domain/repository";
import type { NoteSaveResult, Repository } from "../../domain/repository";

import type { LeaveGuard } from "../types";

export function NoteEditor({
  repository,
  matter,
  guard,
  onDone,
  onCancel,
}: {
  repository: Repository;
  matter: Matter;
  guard: React.RefObject<LeaveGuard | null>;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [body, setBody] = useState(""),
    [busy, setBusy] = useState(false),
    [result, setResult] = useState<NoteSaveResult | null>(null);
  const lock = useRef(false);
  const blocked = busy || result !== null;
  const restricted =
    !!result &&
    (result.state === "rejected" || result.state === "acknowledged") &&
    result.restricted;
  useEffect(() => {
    guard.current = (leave) => {
      if (busy) {
        Alert.alert(
          "Save in progress",
          "Wait for the save outcome before leaving.",
        );
        return;
      }
      if (
        body.trim() &&
        result?.state !== "confirmed" &&
        result?.state !== "acknowledged"
      ) {
        Alert.alert(
          result?.state === "unknown"
            ? "Save outcome unknown"
            : "Discard unsaved note?",
          result?.state === "unknown"
            ? "The note may already be saved. Leaving does not cancel it or send it again."
            : "This note is only held in memory and has not been saved.",
          [
            { text: "Stay", style: "cancel" },
            { text: "Leave editor", style: "destructive", onPress: leave },
          ],
        );
        return;
      }
      leave();
    };
    return () => {
      guard.current = null;
    };
  }, [body, busy, result, guard]);
  const save = async () => {
    if (lock.current || blocked) return;
    lock.current = true;
    setBusy(true);
    const operation = createNoteSubmission(repository, matter, body);
    try {
      const outcome = await operation.save();
      setResult(outcome);
      if (
        (outcome.state === "rejected" || outcome.state === "acknowledged") &&
        outcome.restricted
      )
        setBody("");
    } finally {
      setBusy(false);
    }
  };
  const verify = async () => {
    if (busy || result?.state !== "acknowledged") return;
    setBusy(true);
    try {
      const checked = await verifySavedNote(repository, matter.id, result.note);
      setResult(checked);
      if (checked.state === "acknowledged" && checked.restricted) setBody("");
    } finally {
      setBusy(false);
    }
  };
  return (
    <KeyboardAvoidingView
      style={styles.fill}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <ScrollView
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={styles.content}
      >
        <Text accessibilityRole="header" style={styles.title}>
          Add note
        </Text>
        {restricted ? (
          <Text style={styles.heading}>Matter access changed</Text>
        ) : (
          <>
            <Text style={styles.label}>{matter.matter_code}</Text>
            <Text style={styles.heading}>{matter.title}</Text>
          </>
        )}
        <Text style={styles.label}>Internal note</Text>
        <TextInput
          testID="note-input"
          accessibilityLabel="Internal note"
          value={body}
          onChangeText={setBody}
          editable={!blocked}
          multiline
          maxLength={4000}
          textAlignVertical="top"
          style={[styles.field, { minHeight: 200 }]}
        />
        <Text style={styles.label}>{body.length}/4000</Text>
        {result ? (
          <View accessibilityLiveRegion="polite" style={{ gap: 8 }}>
            <Text
              testID={
                result.state === "confirmed" ? "note-confirmed" : "note-outcome"
              }
              accessibilityRole="alert"
              style={[
                styles.heading,
                {
                  color:
                    result.state === "confirmed" ||
                    result.state === "acknowledged"
                      ? colors.success
                      : colors.warning,
                },
              ]}
            >
              {result.state === "confirmed"
                ? "Note saved and reloaded"
                : result.state === "acknowledged"
                  ? "Note acknowledged"
                  : result.state === "unknown"
                    ? "Save outcome unknown"
                    : "Note not accepted"}
            </Text>
            <Text style={styles.body}>
              {result.state === "confirmed"
                ? "The same saved note was verified in the matter workspace."
                : result.message}
            </Text>
            {!restricted &&
            (result.state === "confirmed" ||
              result.state === "acknowledged") ? (
              <Text style={styles.label}>Saved note ID: {result.note.id}</Text>
            ) : null}
            {result.state === "acknowledged" ? (
              <NativeButton
                label={busy ? "Verifying saved note" : "Verify saved note"}
                disabled={busy}
                onPress={() => {
                  void verify();
                }}
                secondary
              />
            ) : null}
            {result.state === "rejected" && !result.restricted ? (
              <NativeButton
                label="Edit note"
                onPress={() => {
                  lock.current = false;
                  setResult(null);
                }}
                secondary
              />
            ) : null}
            <NativeButton
              label="Return to matter activity"
              testID="note-return"
              onPress={() => {
                if (guard.current) guard.current(onDone);
                else onDone();
              }}
              secondary
            />
          </View>
        ) : (
          <NativeButton
            testID="note-save"
            label={busy ? "Saving note" : "Save note"}
            onPress={() => {
              void save();
            }}
            disabled={busy || body.trim().length < 2}
          />
        )}
        <NativeButton
          label="Cancel"
          onPress={onCancel}
          disabled={busy}
          secondary
        />
        <Text style={styles.label}>
          Unsaved text is held only while this app is open. It is not an offline
          draft.
        </Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}
