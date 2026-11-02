import { useEffect, useMemo, useState } from "react";
import type { RefObject } from "react";
import { ScrollView, Text, View } from "react-native";
import { Empty, Fact, RecordRow, ResourceView } from "../../components/Content";
import { NativeButton, NativeSegments } from "../../components/NativeControls";
import { styles } from "../../components/theme";
import { displayDay } from "../../domain/contracts";
import {
  advanceCounselPage,
  COUNSEL_PAGE_HISTORY,
  createCounselContextRepository,
  createCounselPageLease,
  formatCounselMoney,
} from "../../domain/counsel-context";
import type {
  CounselAssignment,
  CounselSpend,
  CounselCurrencyPage,
} from "../../domain/counsel-context";
import type { AuthorizedRequest } from "../../domain/repository";
import type { LeaveGuard } from "../types";
import { useResource } from "../useResource";

export function CounselScreen({
  request,
  companyId,
  matterId,
  guard,
}: {
  request: AuthorizedRequest;
  companyId: string;
  matterId: string;
  guard: RefObject<LeaveGuard | null>;
}) {
  const repository = useMemo(
    () => createCounselContextRepository(request, companyId),
    [request, companyId],
  );
  const lease = useMemo(
    () => createCounselPageLease(),
    [request, companyId, matterId],
  );
  const [assignments, setAssignments] = useState<(string | null)[]>([null]);
  const [spend, setSpend] = useState<(string | null)[]>([null]);
  const [view, setView] = useState("Assignments");
  const [detail, setDetail] = useState<{
    kind: "assignment" | "spend" | "currency";
    id: string;
  } | null>(null);
  const after = {
    assignment: assignments[assignments.length - 1],
    spend: spend[spend.length - 1],
  };
  const key = JSON.stringify([
    companyId,
    matterId,
    after.assignment,
    after.spend,
  ]);
  const data = useResource(key, (signal) =>
    repository.load(matterId, after, signal),
  );
  const frame = lease.bind(
    key,
    data.resource.state === "ready" ? data.resource.data : null,
  );
  const reload = () => lease.navigate(frame, data.reload, false);
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
    <ScrollView testID="screen-counsel" contentContainerStyle={styles.content}>
      <Text accessibilityRole="header" style={styles.title}>
        Counsel &amp; spend
      </Text>
      <Text testID="counsel-read-only" style={styles.muted}>
        Read-only Matter context. Totals cover the two selected pages.
      </Text>
      <Text style={styles.muted}>
        INR amounts retain rupees and paise. Other currencies show their
        recorded minor units.
      </Text>
      <ResourceView
        resource={lease.isActive() ? data.resource : { state: "loading" }}
        reload={reload}
      >
        {(page) => (
          <>
            <Text testID="counsel-matter-code" style={styles.label}>
              {page.matter_code}
            </Text>
            <Text testID="counsel-matter-title" style={styles.heading}>
              {page.matter_title}
            </Text>
            <Text style={styles.label}>
              {page.matter_status} · Lifecycle version {page.lifecycle_version}
            </Text>
            {detail ? (
              <>
                <NativeButton
                  testID="counsel-detail-back"
                  label={`Return to ${view.toLowerCase()}`}
                  secondary
                  onPress={() => lease.navigate(frame, () => setDetail(null))}
                />
                {detail.kind === "assignment"
                  ? (() => {
                      const selected = page.assignments.find(
                        (record) => record.id === detail.id,
                      );
                      return selected ? (
                        <Assignment record={selected} />
                      ) : (
                        <Empty
                          title="Assignment unavailable on this page"
                          message="Reload or return to the current assignment list."
                        />
                      );
                    })()
                  : detail.kind === "spend"
                    ? (() => {
                        const selected = page.spend_records.find(
                          (record) => record.id === detail.id,
                        );
                        return selected ? (
                          <Spend record={selected} />
                        ) : (
                          <Empty
                            title="Spend record unavailable on this page"
                            message="Reload or return to the current spend list."
                          />
                        );
                      })()
                    : (() => {
                        const selected = page.currencies.find(
                          (record) => record.currency === detail.id,
                        );
                        return selected ? (
                          <CurrencyTotal record={selected} />
                        ) : (
                          <Empty
                            title="Currency totals unavailable on these pages"
                            message="Reload or return to page totals."
                          />
                        );
                      })()}
              </>
            ) : (
              <>
                <NativeSegments
                  label="Counsel view"
                  value={view}
                  options={["Assignments", "Spend", "Page totals"].map(
                    (value) => ({ value, label: value }),
                  )}
                  onChange={(value) =>
                    lease.navigate(frame, () => setView(value))
                  }
                />
                {view === "Assignments" ? (
                  <>
                    <Text testID="counsel-assignment-page" style={styles.label}>
                      Assignments page {assignments.length}
                    </Text>
                    <NativeButton
                      testID="counsel-assignment-next"
                      label="Next assignments page"
                      secondary
                      disabled={
                        page.assignment_next_after === null ||
                        assignments.length >= COUNSEL_PAGE_HISTORY
                      }
                      onPress={() =>
                        lease.navigate(frame, () =>
                          setAssignments((history) =>
                            advanceCounselPage(
                              history,
                              page.assignment_next_after,
                            ),
                          ),
                        )
                      }
                    />
                    {assignments.length > 1 ? (
                      <NativeButton
                        testID="counsel-assignment-first"
                        label="First assignments page"
                        secondary
                        onPress={() =>
                          lease.navigate(frame, () => setAssignments([null]))
                        }
                      />
                    ) : null}
                    {assignments.length >= COUNSEL_PAGE_HISTORY &&
                    page.assignment_next_after !== null ? (
                      <Text style={styles.muted}>
                        Return to the first assignments page to continue
                        browsing.
                      </Text>
                    ) : null}
                    {page.assignments.length ? (
                      page.assignments.map((record) => (
                        <RecordRow
                          key={record.id}
                          testID={`counsel-assignment-row-${record.id}`}
                          title={
                            record.counsel_name || "Counsel name not supplied"
                          }
                          subtitle={record.role_summary || "Role not recorded"}
                          meta={`${record.status} · ${formatCounselMoney(record.currency, record.budget_amount_minor)}`}
                          onPress={() =>
                            lease.navigate(frame, () =>
                              setDetail({ kind: "assignment", id: record.id }),
                            )
                          }
                        />
                      ))
                    ) : (
                      <Empty
                        title="No assignments on this page"
                        message="Only the current assignment page is shown."
                      />
                    )}
                  </>
                ) : view === "Spend" ? (
                  <>
                    <Text testID="counsel-spend-page" style={styles.label}>
                      Spend page {spend.length}
                    </Text>
                    <NativeButton
                      testID="counsel-spend-next"
                      label="Next spend page"
                      secondary
                      disabled={
                        page.spend_next_after === null ||
                        spend.length >= COUNSEL_PAGE_HISTORY
                      }
                      onPress={() =>
                        lease.navigate(frame, () =>
                          setSpend((history) =>
                            advanceCounselPage(history, page.spend_next_after),
                          ),
                        )
                      }
                    />
                    {spend.length > 1 ? (
                      <NativeButton
                        testID="counsel-spend-first"
                        label="First spend page"
                        secondary
                        onPress={() =>
                          lease.navigate(frame, () => setSpend([null]))
                        }
                      />
                    ) : null}
                    {spend.length >= COUNSEL_PAGE_HISTORY &&
                    page.spend_next_after !== null ? (
                      <Text style={styles.muted}>
                        Return to the first spend page to continue browsing.
                      </Text>
                    ) : null}
                    {page.spend_records.length ? (
                      page.spend_records.map((record) => (
                        <RecordRow
                          key={record.id}
                          testID={`counsel-spend-row-${record.id}`}
                          title={
                            record.counsel_name || "Counsel name not supplied"
                          }
                          subtitle={record.description}
                          meta={`${record.status} · ${formatCounselMoney(record.currency, record.amount_minor)}`}
                          onPress={() =>
                            lease.navigate(frame, () =>
                              setDetail({ kind: "spend", id: record.id }),
                            )
                          }
                        />
                      ))
                    ) : (
                      <Empty
                        title="No spend records on this page"
                        message="Only the current spend page is shown."
                      />
                    )}
                  </>
                ) : (
                  <>
                    <Text testID="counsel-totals-scope" style={styles.heading}>
                      Totals for assignments page {assignments.length} and spend
                      page {spend.length}
                    </Text>
                    {page.currencies.length ? (
                      page.currencies.map((record, index) => (
                        <RecordRow
                          key={record.currency}
                          testID={`counsel-currency-${index}`}
                          title={record.currency}
                          subtitle="Totals for these pages"
                          meta={formatCounselMoney(
                            record.currency,
                            record.amount_minor,
                          )}
                          onPress={() =>
                            lease.navigate(frame, () =>
                              setDetail({
                                kind: "currency",
                                id: record.currency,
                              }),
                            )
                          }
                        />
                      ))
                    ) : (
                      <Text style={styles.muted}>
                        No monetary records on these pages.
                      </Text>
                    )}
                  </>
                )}
              </>
            )}
            <NativeButton
              testID="counsel-reload"
              label="Reload counsel context"
              onPress={reload}
              secondary
            />
          </>
        )}
      </ResourceView>
    </ScrollView>
  );
}

function Assignment({ record }: { record: CounselAssignment }) {
  return (
    <View testID={`counsel-assignment-${record.id}`} style={{ gap: 4 }}>
      <Text accessibilityRole="header" style={styles.heading}>
        {record.counsel_name || "Counsel name not supplied"}
      </Text>
      <Fact
        testID="counsel-assignment-id"
        label="Assignment ID"
        value={record.id}
      />
      <Fact
        testID="counsel-assignment-counsel-id"
        label="Counsel ID"
        value={record.counsel_id}
      />
      <Fact
        testID="counsel-assignment-status"
        label="Status"
        value={record.status}
      />
      <Fact
        testID="counsel-assignment-role"
        label="Role"
        value={record.role_summary}
      />
      <Fact
        testID="counsel-assignment-budget"
        label="Recorded budget"
        value={formatCounselMoney(record.currency, record.budget_amount_minor)}
      />
      <Fact
        testID="counsel-assignment-fee"
        label="Reported fee"
        value={formatCounselMoney(record.currency, record.fee_agreed_minor)}
      />
      <Fact
        testID="counsel-assignment-owner-name"
        label="Assigned by"
        value={record.assigned_by_name || "Name not supplied"}
      />
      <Fact
        testID="counsel-assignment-owner-id"
        label="Assigning membership ID"
        value={record.assigned_by_membership_id}
      />
      <Fact
        testID="counsel-assignment-notes"
        label="Notes"
        value={record.internal_notes}
      />
      <Fact
        testID="counsel-assignment-created"
        label="Created"
        value={record.created_at}
      />
      <Fact
        testID="counsel-assignment-updated"
        label="Updated"
        value={record.updated_at}
      />
    </View>
  );
}
function CurrencyTotal({ record }: { record: CounselCurrencyPage }) {
  return (
    <View testID="counsel-currency-detail">
      <Text style={styles.heading}>
        {record.currency} totals for these pages
      </Text>
      <Fact
        testID="counsel-currency-budget"
        label="Recorded assignment budgets on this page"
        value={formatCounselMoney(
          record.currency,
          record.recorded_budget_minor,
        )}
      />
      <Fact
        testID="counsel-currency-unpriced"
        label="Assignments without a recorded budget on this page"
        value={String(record.unpriced_assignment_count)}
      />
      <Fact
        testID="counsel-currency-amount"
        label="Recorded spend on this page"
        value={formatCounselMoney(record.currency, record.amount_minor)}
      />
      <Fact
        testID="counsel-currency-approved"
        label="Approved spend on this page"
        value={formatCounselMoney(
          record.currency,
          record.approved_amount_minor,
        )}
      />
      <Fact
        testID="counsel-currency-paid"
        label="Paid spend on this page"
        value={formatCounselMoney(record.currency, record.paid_amount_minor)}
      />
      <Fact
        testID="counsel-currency-pending"
        label="Pending spend on this page"
        value={formatCounselMoney(record.currency, record.pending_amount_minor)}
      />
    </View>
  );
}
function Spend({ record }: { record: CounselSpend }) {
  return (
    <View testID={`counsel-spend-${record.id}`} style={{ gap: 4 }}>
      <Text accessibilityRole="header" style={styles.heading}>
        {record.counsel_name || "Counsel name not supplied"}
      </Text>
      <Fact
        testID="counsel-spend-id"
        label="Spend record ID"
        value={record.id}
      />
      <Fact
        testID="counsel-spend-counsel-id"
        label="Counsel ID"
        value={record.counsel_id}
      />
      <Fact
        testID="counsel-spend-assignment-id"
        label="Assignment ID"
        value={record.assignment_id}
      />
      <Fact
        testID="counsel-spend-description"
        label="Description"
        value={record.description}
      />
      <Fact
        testID="counsel-spend-invoice"
        label="Invoice reference"
        value={record.invoice_reference}
      />
      <Fact
        testID="counsel-spend-stage"
        label="Stage"
        value={record.stage_label}
      />
      <Fact
        testID="counsel-spend-amount"
        label="Recorded amount"
        value={formatCounselMoney(record.currency, record.amount_minor)}
      />
      <Fact
        testID="counsel-spend-approved"
        label="Approved amount"
        value={formatCounselMoney(
          record.currency,
          record.approved_amount_minor,
        )}
      />
      <Fact
        testID="counsel-spend-paid"
        label="Paid amount"
        value={formatCounselMoney(record.currency, record.paid_amount_minor)}
      />
      <Fact
        testID="counsel-spend-pending"
        label="Pending amount"
        value={formatCounselMoney(record.currency, record.pending_amount_minor)}
      />
      <Fact
        testID="counsel-spend-status"
        label="Record status"
        value={record.status}
      />
      <Fact
        testID="counsel-spend-payment-status"
        label="Reported payment status"
        value={record.payment_status}
      />
      <Fact
        testID="counsel-spend-payment-tracking"
        label="Payment tracking"
        value={record.payment_tracking_status}
      />
      <Fact
        testID="counsel-spend-billed"
        label="Billed date"
        value={record.billed_on ? displayDay(record.billed_on) : null}
      />
      <Fact
        testID="counsel-spend-due"
        label="Due date"
        value={record.due_on ? displayDay(record.due_on) : null}
      />
      <Fact
        testID="counsel-spend-paid-on"
        label="Paid date"
        value={record.paid_on ? displayDay(record.paid_on) : null}
      />
      <Fact
        testID="counsel-spend-owner-name"
        label="Recorded by"
        value={record.recorded_by_name || "Name not supplied"}
      />
      <Fact
        testID="counsel-spend-owner-id"
        label="Recording membership ID"
        value={record.recorded_by_membership_id}
      />
      <Fact testID="counsel-spend-notes" label="Notes" value={record.notes} />
      <Fact
        testID="counsel-spend-created"
        label="Created"
        value={record.created_at}
      />
      <Fact
        testID="counsel-spend-updated"
        label="Updated"
        value={record.updated_at}
      />
    </View>
  );
}
