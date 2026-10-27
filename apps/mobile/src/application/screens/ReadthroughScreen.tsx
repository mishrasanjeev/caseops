import { useEffect, useMemo, useState } from "react";
import type { RefObject } from "react";
import { ScrollView, Text, View } from "react-native";
import { Empty, Fact, RecordRow, ResourceView } from "../../components/Content";
import { NativeButton } from "../../components/NativeControls";
import { styles } from "../../components/theme";
import {
  advanceReadPage,
  createReadthroughPageLease,
  createReadthroughRepository,
} from "../../domain/readthrough";
import type {
  HearingPack,
  HearingPackItem,
  ReadPage,
  ReadScope,
  ReadState,
  RecommendationDecision,
  RecommendationDetail,
  RecommendationOption,
  RecommendationSummary,
  StoredJson,
} from "../../domain/readthrough";
import type { AuthorizedRequest } from "../../domain/repository";
import type { LeaveGuard } from "../types";
import { useResource } from "../useResource";

export type ReadthroughTarget =
  | { kind: "recommendations" }
  | { kind: "pack"; hearingId: string };
type ViewState =
  | { kind: "recommendations" }
  | { kind: "recommendation" | "options" | "decisions"; id: string }
  | { kind: "pack"; hearingId: string }
  | { kind: "pack-items"; id: string; hearingId: string };
type Loaded =
  | { kind: "recommendations"; page: ReadPage<RecommendationSummary> }
  | { kind: "recommendation"; record: RecommendationDetail }
  | { kind: "options"; page: ReadPage<RecommendationOption> }
  | { kind: "decisions"; page: ReadPage<RecommendationDecision> }
  | { kind: "pack"; record: HearingPack | null }
  | { kind: "pack-items"; page: ReadPage<HearingPackItem> };

export function ReadthroughScreen({
  request,
  companyId,
  matterId,
  target,
  guard,
}: {
  request: AuthorizedRequest;
  companyId: string;
  matterId: string;
  target: ReadthroughTarget;
  guard: RefObject<LeaveGuard | null>;
}) {
  const initial: ViewState = target;
  const repository = useMemo(
    () => createReadthroughRepository(request, companyId),
    [request, companyId],
  );
  const lease = useMemo(
    () => createReadthroughPageLease(),
    [request, companyId, matterId],
  );
  const [view, setView] = useState<ViewState>(initial);
  const [history, setHistory] = useState<(string | null)[]>([null]);
  const cursor = history[history.length - 1];
  const key = JSON.stringify([companyId, matterId, view, cursor]);
  const data = useResource<Loaded>(key, async (signal) => {
    switch (view.kind) {
      case "recommendations":
        return {
          kind: view.kind,
          page: await repository.recommendations(matterId, cursor, signal),
        };
      case "recommendation":
        return {
          kind: view.kind,
          record: await repository.recommendation(matterId, view.id, signal),
        };
      case "options":
        return {
          kind: view.kind,
          page: await repository.options(matterId, view.id, cursor, signal),
        };
      case "decisions":
        return {
          kind: view.kind,
          page: await repository.decisions(matterId, view.id, cursor, signal),
        };
      case "pack":
        return {
          kind: view.kind,
          record: await repository.latestPack(matterId, view.hearingId, signal),
        };
      case "pack-items":
        return {
          kind: view.kind,
          page: await repository.packItems(matterId, view.id, cursor, signal),
        };
    }
  });
  const frame = lease.bind(
    key,
    data.resource.state === "ready" ? data.resource.data : null,
  );
  const change = (next: ViewState) =>
    lease.navigate(frame, () => {
      setHistory([null]);
      setView(next);
    });
  const restart = () =>
    lease.navigate(
      frame,
      () => {
        setHistory([null]);
        setView(initial);
        data.reload();
      },
      false,
    );
  useEffect(() => {
    const leave: LeaveGuard = (action) => {
      lease.dispose();
      action();
    };
    guard.current = leave;
    return () => {
      lease.dispose();
      if (guard.current === leave) guard.current = null;
    };
  }, [guard, lease]);
  return (
    <ScrollView
      testID="screen-readthrough"
      contentContainerStyle={styles.content}
    >
      <Text accessibilityRole="header" style={styles.title}>
        {target.kind === "recommendations"
          ? "Saved recommendations"
          : "Existing hearing pack"}
      </Text>
      <Text testID="readthrough-read-only" style={styles.muted}>
        Recorded material for professional review. Citations and source
        references do not establish legal accuracy.
      </Text>
      <NativeButton
        label="Reload from the beginning"
        testID="readthrough-first-page"
        onPress={restart}
        secondary
      />
      {view.kind !== initial.kind ? (
        <NativeButton
          label="Return to saved records"
          onPress={() => change(initial)}
          secondary
        />
      ) : null}
      {view.kind === "options" || view.kind === "decisions" ? (
        <NativeButton
          label="Return to this recommendation"
          testID="readthrough-recommendation-back"
          secondary
          onPress={() => change({ kind: "recommendation", id: view.id })}
        />
      ) : null}
      <ResourceView
        resource={lease.isActive() ? data.resource : { state: "loading" }}
        reload={() => lease.navigate(frame, data.reload, false)}
      >
        {(value) => {
          const scope =
            "page" in value ? value.page.scope : value.record?.scope;
          const page = "page" in value ? value.page : null;
          return (
            <>
              {scope ? <Scope scope={scope} /> : null}
              {value.kind === "recommendations" ? (
                value.page.items.length ? (
                  value.page.items.map((item) => (
                    <RecordRow
                      key={item.id}
                      testID={`recommendation-${item.id}`}
                      title={item.record?.title || "Retained recommendation"}
                      subtitle={`Updated ${item.updated_at}`}
                      meta={`${item.read_state} · ${item.id}`}
                      onPress={() =>
                        change({ kind: "recommendation", id: item.id })
                      }
                    />
                  ))
                ) : (
                  <Empty
                    title="No saved recommendations"
                    message="No recommendations were returned for this Matter."
                  />
                )
              ) : value.kind === "recommendation" ? (
                <>
                  <Recommendation record={value.record} />
                  <NativeButton
                    label="Read saved options"
                    testID="recommendation-options"
                    onPress={() =>
                      change({ kind: "options", id: value.record.id })
                    }
                    secondary
                  />
                  <NativeButton
                    label="Read recorded decisions"
                    testID="recommendation-decisions"
                    onPress={() =>
                      change({ kind: "decisions", id: value.record.id })
                    }
                    secondary
                  />
                </>
              ) : value.kind === "options" ? (
                value.page.items.length ? (
                  value.page.items.map((item) => (
                    <Option key={item.id} record={item} />
                  ))
                ) : (
                  <Empty
                    title="No saved options"
                    message="No options were returned for this recommendation."
                  />
                )
              ) : value.kind === "decisions" ? (
                value.page.items.length ? (
                  value.page.items.map((item) => (
                    <Decision key={item.id} record={item} />
                  ))
                ) : (
                  <Empty
                    title="No recorded decisions"
                    message="No decisions were returned for this recommendation."
                  />
                )
              ) : value.kind === "pack" ? (
                value.record ? (
                  <>
                    <Pack record={value.record} />
                    <NativeButton
                      label="Read pack items"
                      testID="hearing-pack-items"
                      onPress={() =>
                        change({
                          kind: "pack-items",
                          id: value.record!.id,
                          hearingId:
                            target.kind === "pack" ? target.hearingId : "",
                        })
                      }
                      secondary
                    />
                  </>
                ) : (
                  <Empty
                    title="No saved hearing pack"
                    message="No existing pack was returned for this exact hearing."
                  />
                )
              ) : value.page.items.length ? (
                value.page.items.map((item) => (
                  <PackItem key={item.id} record={item} />
                ))
              ) : (
                <Empty
                  title="No saved pack items"
                  message="No items were returned for this pack."
                />
              )}
              {page ? (
                <View style={{ gap: 8 }}>
                  <Text style={styles.label}>
                    Page {history.length} · {page.items.length} returned records
                    · {page.order}
                  </Text>
                  <NativeButton
                    label="Previous page"
                    testID="readthrough-previous"
                    secondary
                    disabled={history.length === 1}
                    onPress={() =>
                      lease.navigate(frame, () =>
                        setHistory((old) => old.slice(0, -1)),
                      )
                    }
                  />
                  <NativeButton
                    label="Next page"
                    testID="readthrough-next"
                    secondary
                    disabled={
                      page.next_cursor === null || history.length >= 100
                    }
                    onPress={() =>
                      lease.navigate(frame, () => {
                        if (page.next_cursor !== null)
                          setHistory(
                            advanceReadPage(history, page.next_cursor),
                          );
                      })
                    }
                  />
                  {history.length >= 100 && page.next_cursor !== null ? (
                    <Text style={styles.muted}>
                      Reload from the beginning to continue browsing safely.
                    </Text>
                  ) : null}
                </View>
              ) : null}
            </>
          );
        }}
      </ResourceView>
    </ScrollView>
  );
}
function Scope({ scope }: { scope: ReadScope }) {
  return (
    <Text style={styles.label}>
      Status {scope.matter_status} · Active flag{" "}
      {scope.matter_is_active ? "Yes" : "No"} · Lifecycle version{" "}
      {scope.matter_lifecycle_version}
    </Text>
  );
}
function Unavailable({ state, id }: { state: ReadState; id: string }) {
  return (
    <Empty
      title="Retained content unavailable in this view"
      message={`${state === "unsupported_size" ? "This saved content exceeds the supported display size." : "This saved content has an unsupported legacy format."} Record ${id}.`}
    />
  );
}
function TextList({ label, values }: { label: string; values: string[] }) {
  return (
    <View style={{ gap: 8 }}>
      <Text accessibilityRole="header" style={styles.heading}>
        {label}
      </Text>
      {values.length ? (
        values.map((value, index) => (
          <Text key={index} selectable style={styles.body}>
            {value}
          </Text>
        ))
      ) : (
        <Text style={styles.muted}>None recorded</Text>
      )}
    </View>
  );
}
function Structured({ value }: { value: StoredJson }) {
  if (value === null) return <Text style={styles.muted}>Not recorded</Text>;
  if (typeof value !== "object")
    return (
      <Text selectable style={styles.body}>
        {String(value)}
      </Text>
    );
  if (Array.isArray(value))
    return (
      <View style={{ gap: 12 }}>
        {value.length ? (
          value.map((item, index) => <Structured key={index} value={item} />)
        ) : (
          <Text style={styles.muted}>None recorded</Text>
        )}
      </View>
    );
  return (
    <View style={{ gap: 12 }}>
      {Object.entries(value).map(([key, child]) => (
        <View key={key} style={{ gap: 4 }}>
          <Text style={[styles.body, { fontWeight: "600" }]}>
            {key.replaceAll("_", " ")}
          </Text>
          <Structured value={child} />
        </View>
      ))}
    </View>
  );
}
function Recommendation({ record }: { record: RecommendationDetail }) {
  if (record.record === null)
    return <Unavailable state={record.read_state} id={record.id} />;
  const value = record.record;
  return (
    <View style={{ gap: 12 }}>
      <Text
        testID={`recommendation-body-${record.id}`}
        accessibilityRole="header"
        style={styles.heading}
      >
        {value.title || "Title not recorded"}
      </Text>
      <Fact label="Record" value={record.id} />
      <Fact label="Updated" value={record.updated_at} />
      <Fact label="Recorded status" value={value.status} />
      <Fact label="Recorded type" value={value.type} />
      <Fact label="Recorded confidence" value={value.confidence} />
      <Fact
        label="Review required flag"
        value={value.review_required ? "Yes" : "No"}
      />
      <Fact label="Rationale" value={value.rationale} />
      <Fact
        label="Recorded primary option index"
        value={String(value.primary_option_index)}
      />
      <Fact label="Next action" value={value.next_action} />
      <TextList label="Assumptions" values={value.assumptions} />
      <TextList label="Missing facts" values={value.missing_facts} />
      <TextList
        label="Recorded retrieved authorities"
        values={value.retrieved_authorities}
      />
      {value.analysis ? (
        <View style={{ gap: 8 }}>
          <Text style={styles.heading}>Stored analysis</Text>
          <Structured value={value.analysis} />
        </View>
      ) : null}
      {value.strategy_payload ? (
        <View style={{ gap: 8 }}>
          <Text style={styles.heading}>Stored strategy</Text>
          <Structured value={value.strategy_payload} />
        </View>
      ) : null}
    </View>
  );
}
function Option({ record }: { record: RecommendationOption }) {
  if (record.record === null)
    return <Unavailable state={record.read_state} id={record.id} />;
  return (
    <View
      testID={`recommendation-option-${record.id}`}
      style={[styles.divider, { paddingVertical: 12, gap: 8 }]}
    >
      <Text style={styles.heading}>
        {record.record.label || "Label not recorded"}
      </Text>
      <Fact label="Record / rank" value={`${record.id} / ${record.rank}`} />
      <Fact label="Rationale" value={record.record.rationale} />
      <Fact label="Recorded confidence" value={record.record.confidence} />
      <Fact label="Risk notes" value={record.record.risk_notes} />
      <TextList
        label="Recorded citations"
        values={record.record.supporting_citations}
      />
    </View>
  );
}
function Decision({ record }: { record: RecommendationDecision }) {
  if (record.record === null)
    return <Unavailable state={record.read_state} id={record.id} />;
  return (
    <View
      testID={`recommendation-decision-${record.id}`}
      style={[styles.divider, { paddingVertical: 12, gap: 8 }]}
    >
      <Fact label="Record" value={record.id} />
      <Fact label="Recorded decision" value={record.record.decision} />
      <Fact
        label="Recorded actor membership"
        value={record.record.actor_membership_id}
      />
      <Fact label="Recorded at" value={record.created_at} />
      <Fact label="Notes" value={record.record.notes} />
      <Fact
        label="Recorded selected option index"
        value={
          record.record.selected_option_index === null
            ? null
            : String(record.record.selected_option_index)
        }
      />
    </View>
  );
}
function Pack({ record }: { record: HearingPack }) {
  if (record.record === null)
    return <Unavailable state={record.read_state} id={record.id} />;
  return (
    <View testID={`hearing-pack-${record.id}`} style={{ gap: 12 }}>
      <Fact
        label="Pack / hearing"
        value={`${record.id} / ${record.hearing_id || "Not recorded"}`}
      />
      <Fact label="Generated at" value={record.generated_at} />
      <Fact label="Reviewed at" value={record.reviewed_at} />
      <Fact label="Recorded status" value={record.record.status} />
      <Fact
        label="Review required flag"
        value={record.record.review_required ? "Yes" : "No"}
      />
      <Fact label="Summary" value={record.record.summary} />
      <Fact
        label="Generated by membership"
        value={record.record.generated_by_membership_id}
      />
      <Fact
        label="Reviewed by membership"
        value={record.record.reviewed_by_membership_id}
      />
    </View>
  );
}
function PackItem({ record }: { record: HearingPackItem }) {
  if (record.record === null)
    return <Unavailable state={record.read_state} id={record.id} />;
  return (
    <View
      testID={`hearing-pack-item-${record.id}`}
      style={[styles.divider, { paddingVertical: 12, gap: 8 }]}
    >
      <Text style={styles.heading}>
        {record.record.title || "Title not recorded"}
      </Text>
      <Fact label="Record / rank" value={`${record.id} / ${record.rank}`} />
      <Fact label="Recorded type" value={record.record.item_type} />
      <Fact label="Created at" value={record.created_at} />
      <Fact label="Content" value={record.record.body} />
      <Fact label="Stored source reference" value={record.record.source_ref} />
    </View>
  );
}
