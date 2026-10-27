import type { ReactNode } from "react";
import { useState } from "react";
import { ScrollView, Text, View } from "react-native";
import { Fact, RecordRow } from "../../components/Content";
import {
  NativeButton,
  NativeProgress,
  NativeSegments,
} from "../../components/NativeControls";
import { styles } from "../../components/theme";
import { ContractObligations } from "../../components/ContractObligations";
import { displayDay } from "../../domain/contracts";
import { readFailure } from "../../domain/repository";
import {
  advanceSourcePage,
  formatSourceValue,
  SOURCE_GAPS,
  sourceDateStateLabel,
} from "../../domain/source-records";
import type {
  ContractSource,
  IpPortfolioSource,
  IpDocketSource,
  SourceLocator,
  SourceDateState,
  SourceKind,
  SourceRecordsRepository,
  SourceRef,
  SourceUnavailable,
} from "../../domain/source-records";
import { useResource } from "../useResource";
import type { Resource } from "../useResource";

export type SourceRecordsScreenProps = {
  repository: SourceRecordsRepository;
  kind: SourceKind;
  onKindChange: (kind: SourceKind) => void;
  active: boolean;
  openSource: (source: SourceRef, locator?: SourceLocator) => void;
};

// Type selection does not grant authority: both lists use their normal
// authenticated readers, and IP additionally checks current workspace readiness.
export function SourceRecordsScreen(props: SourceRecordsScreenProps) {
  const { kind } = props;
  if (!props.active) return null;
  return (
    <View style={styles.fill}>
      <NativeSegments
        label="Source type"
        value={kind}
        options={[
          { value: "ip_docket", label: "Trademarks" },
          { value: "contract", label: "Contracts" },
        ]}
        onChange={(value) => {
          if (value === "contract" || value === "ip_docket")
            props.onKindChange(value);
        }}
      />
      {kind === "contract" ? (
        <ContractRecords
          key={`contracts:${props.repository.companyId}`}
          {...props}
        />
      ) : (
        <IpRecords key={`ip:${props.repository.companyId}`} {...props} />
      )}
    </View>
  );
}

function ContractRecords({
  repository,
  active,
  openSource,
}: SourceRecordsScreenProps) {
  const [history, setHistory] = useState<(string | null)[]>([null]);
  const [pageError, setPageError] = useState<ReturnType<
    typeof readFailure
  > | null>(null);
  const cursor = history[history.length - 1];
  const data = useResource(
    JSON.stringify(["contract-source-page", repository.companyId, cursor]),
    (signal) => repository.contracts(cursor, signal),
    active,
  );
  const reload = () => {
    setPageError(null);
    data.reload();
  };
  return (
    <ScrollView
      testID="screen-source-records"
      contentContainerStyle={styles.content}
    >
      <Heading>Contracts</Heading>
      <Text testID="source-scope" style={styles.muted}>
        Contract metadata visible to this workspace account
      </Text>
      <SourceRead
        resource={
          pageError ? { state: "error", error: pageError } : data.resource
        }
        reload={reload}
      >
        {(page) => (
          <>
            {page.contracts.length ? (
              page.contracts.map((record) => (
                <RecordRow
                  key={record.id}
                  testID={`source-row-contract-${record.id}`}
                  title={record.title}
                  subtitle={record.contract_code}
                  meta={`${record.status} · ${record.counterparty_name || "Counterparty not recorded"}`}
                  onPress={() =>
                    openSource({ kind: "contract", id: record.id })
                  }
                />
              ))
            ) : (
              <View testID="source-empty" style={{ gap: 8 }}>
                <Text style={styles.heading}>No contracts returned</Text>
                <Text style={styles.muted}>
                  The server returned no visible contracts for this page.
                </Text>
              </View>
            )}
            <Text testID="source-page" style={styles.label}>
              Page {history.length}
            </Text>
            {page.next_cursor !== null ? (
              <NativeButton
                label="Next page"
                testID="source-next-page"
                onPress={() => {
                  try {
                    setHistory(advanceSourcePage(history, page.next_cursor!));
                  } catch (error) {
                    setPageError(readFailure(error));
                  }
                }}
              />
            ) : null}
          </>
        )}
      </SourceRead>
      {history.length > 1 ? (
        <NativeButton
          label="First page"
          testID="source-first-page"
          onPress={() => {
            setPageError(null);
            setHistory([null]);
            data.reload();
          }}
          secondary
        />
      ) : null}
      <NativeButton
        label="Reload sources"
        testID="source-reload"
        onPress={reload}
        secondary
      />
    </ScrollView>
  );
}

function IpRecords({
  repository,
  active,
  openSource,
}: SourceRecordsScreenProps) {
  const [history, setHistory] = useState<(string | null)[]>([null]);
  const [pageError, setPageError] = useState<ReturnType<
    typeof readFailure
  > | null>(null);
  const cursor = history[history.length - 1];
  const data = useResource(
    JSON.stringify(["ip-source-page", repository.companyId, cursor]),
    (signal) => repository.ipPage(cursor, signal),
    active,
  );
  const reload = () => {
    setPageError(null);
    data.reload();
  };
  return (
    <ScrollView
      testID="screen-source-records"
      contentContainerStyle={styles.content}
    >
      <Heading>Trademark Applications</Heading>
      <Text testID="source-scope" style={styles.muted}>
        Visible active trademark applications
      </Text>
      <SourceRead
        resource={
          pageError ? { state: "error", error: pageError } : data.resource
        }
        reload={reload}
      >
        {(result) =>
          result.state === "unavailable" ? (
            <Unavailable value={result} />
          ) : (
            <>
              {result.page.rows.length ? (
                result.page.rows.map((record) => (
                  <RecordRow
                    key={record.application_id}
                    testID={`source-row-ip_docket-${record.id}-${record.application_id}`}
                    title={record.docket_title}
                    subtitle={
                      record.primary_identifier ||
                      (record.pending_identifier_allocation
                        ? "Application number pending allocation"
                        : "Application number not recorded")
                    }
                    meta={`${record.docket_status} · ${record.office || "Office not recorded"} · Renewal: ${record.source_renewal_due_on ? displayDay(record.source_renewal_due_on) : "Not recorded"} · ${sourceDateStateLabel(record.source_renewal_state)}`}
                    onPress={() =>
                      openSource(
                        { kind: "ip_docket", id: record.id },
                        {
                          kind: "ip_docket",
                          docketId: record.id,
                          applicationId: record.application_id,
                          cursor,
                        },
                      )
                    }
                  />
                ))
              ) : (
                <View testID="source-empty" style={{ gap: 8 }}>
                  <Text style={styles.heading}>
                    No visible active trademark applications
                  </Text>
                  <Text style={styles.muted}>
                    The server returned no trademark applications for this page.
                  </Text>
                </View>
              )}
              <Text testID="source-page" style={styles.label}>
                Page {history.length}
              </Text>
              {result.page.next_cursor !== null ? (
                <NativeButton
                  label="Next page"
                  testID="source-next-page"
                  onPress={() => {
                    try {
                      setHistory(
                        advanceSourcePage(history, result.page.next_cursor!),
                      );
                    } catch (error) {
                      setPageError(readFailure(error));
                    }
                  }}
                />
              ) : null}
            </>
          )
        }
      </SourceRead>
      {history.length > 1 ? (
        <NativeButton
          label="First page"
          testID="source-first-page"
          onPress={() => {
            setPageError(null);
            setHistory([null]);
            data.reload();
          }}
          secondary
        />
      ) : null}
      <NativeButton
        label="Reload sources"
        testID="source-reload"
        onPress={reload}
        secondary
      />
    </ScrollView>
  );
}

export type SourceRecordDetailScreenProps = {
  repository: SourceRecordsRepository;
  source: SourceRef;
  locator?: SourceLocator;
  active?: boolean;
};

// Reusable by Today/Calendar/record navigation without a manufactured Matter ID.
export function SourceRecordDetailScreen({
  active = true,
  ...props
}: SourceRecordDetailScreenProps) {
  if (!active) return null;
  return (
    <SourceDetailContent
      key={JSON.stringify([
        props.repository.companyId,
        props.source,
        props.locator,
      ])}
      {...props}
    />
  );
}

function SourceDetailContent({
  repository,
  source,
  locator,
}: Omit<SourceRecordDetailScreenProps, "active">) {
  const data = useResource(
    JSON.stringify(["source-detail", repository.companyId, source, locator]),
    (signal) => repository.detail(source, locator, signal),
  );
  return (
    <ScrollView testID="source-detail" contentContainerStyle={styles.content}>
      <SourceRead resource={data.resource} reload={data.reload}>
        {(result) =>
          result.state === "unavailable" ? (
            <Unavailable value={result} />
          ) : (
            <>
              {result.record.kind === "contract" ? (
                <ContractDetail
                  record={result.record}
                  repository={repository}
                />
              ) : "record_type" in result.record ? (
                <IpDocketDetail record={result.record} />
              ) : (
                <IpDetail record={result.record} />
              )}
              <Text testID="source-read-only" style={styles.muted}>
                Read-only source record
              </Text>
              <Text testID="source-counsel-unavailable" style={styles.muted}>
                {SOURCE_GAPS.counsel}
              </Text>
            </>
          )
        }
      </SourceRead>
      <NativeButton
        label="Reload source"
        testID="source-detail-reload"
        onPress={data.reload}
        secondary
      />
    </ScrollView>
  );
}

function ContractDetail({
  record,
  repository,
}: {
  record: ContractSource;
  repository: SourceRecordsRepository;
}) {
  return (
    <>
      <Text testID="source-kind" style={styles.label}>
        Contract
      </Text>
      <Heading>{record.title}</Heading>
      <Text testID="source-status" style={styles.status}>
        {record.status}
      </Text>
      <Fact
        label="Contract code"
        value={record.contract_code}
        testID="source-contract-code"
      />
      <Fact label="Source contract ID" value={record.id} testID="source-id" />
      <Fact label="Counterparty" value={record.counterparty_name} />
      <Fact label="Contract type" value={record.contract_type} />
      <DateFact
        label="Effective date"
        value={record.effective_on}
        testID="source-effective-date"
      />
      <DateFact
        label="Expiry date"
        value={record.expires_on}
        testID="source-expiry-date"
      />
      <DateFact
        label="Renewal date"
        value={record.renewal_on}
        testID="source-renewal-date"
      />
      <Fact
        label="Auto-renewal recorded"
        value={record.auto_renewal ? "Yes" : "No"}
      />
      <Fact
        label="Date verification"
        value="Not supplied by the contract API"
        testID="source-verification"
      />
      <Fact
        label="Recorded value"
        value={formatSourceValue(record.total_value_minor, record.currency)}
        testID="source-value"
      />
      <Fact label="Currency" value={record.currency} testID="source-currency" />
      <Fact
        label="Responsible membership ID"
        value={record.owner_membership_id}
        testID="source-owner-id"
      />
      <Text style={styles.muted}>
        Responsible-person name not supplied by this read.
      </Text>
      <Fact label="Linked Matter ID" value={record.linked_matter_id} />
      <Fact label="Jurisdiction" value={record.jurisdiction} />
      <Fact label="Summary" value={record.summary} />
      <Fact
        label="Source record updated"
        value={record.updated_at}
        testID="source-updated"
      />
      <Text testID="source-provenance" style={styles.muted}>
        Recorded contract metadata; source verification and check time not
        supplied.
      </Text>
      <ContractObligations repository={repository} contractId={record.id} />
    </>
  );
}

function IpDocketDetail({ record }: { record: IpDocketSource }) {
  return (
    <>
      <Text testID="source-kind" style={styles.label}>
        IP docket · {record.record_type}
      </Text>
      <Heading>{record.title}</Heading>
      <Text testID="source-status" style={styles.status}>
        {record.status}
      </Text>
      <Fact label="Source docket ID" value={record.id} testID="source-id" />
      <Fact label="Recorded identifier" value={record.primary_identifier} />
      <Fact label="Linked Matter ID" value={record.matter_id} />
      <Fact
        label="Lifecycle version"
        value={String(record.lifecycle_version)}
      />
      <Fact label="Record version" value={String(record.current_version)} />
      <Fact
        label="Source record updated"
        value={record.updated_at}
        testID="source-updated"
      />
      <Text testID="source-provenance" style={styles.muted}>
        Current docket metadata. This summary does not supply application,
        renewal or verification dates; no dates are inferred from the Calendar
        event.
      </Text>
    </>
  );
}

function IpDetail({ record }: { record: IpPortfolioSource }) {
  return (
    <>
      <Text testID="source-kind" style={styles.label}>
        Trademark application
      </Text>
      <Heading>{record.docket_title}</Heading>
      <Text testID="source-status" style={styles.status}>
        {record.docket_status}
      </Text>
      <Fact label="Source docket ID" value={record.id} testID="source-id" />
      <Fact
        label="Application ID"
        value={record.application_id}
        testID="source-application-id"
      />
      <Fact
        label="Application number"
        value={
          record.primary_identifier ||
          (record.pending_identifier_allocation ? "Pending allocation" : null)
        }
        testID="source-application-number"
      />
      <Fact
        label="Application numbers"
        value={record.application_numbers.join("\n")}
      />
      <Fact
        label="Opposition numbers"
        value={record.opposition_numbers.join("\n")}
      />
      <Fact label="Office" value={record.office} />
      <Fact label="Jurisdiction" value={record.jurisdiction} />
      <Fact label="Filing phase" value={record.filing_phase} />
      <DateFact
        label="Source application date"
        value={record.source_application_on}
        testID="source-application-date"
        state={record.source_application_state}
      />
      <DateFact
        label="Source renewal date"
        value={record.source_renewal_due_on}
        testID="source-renewal-date"
        state={record.source_renewal_state}
      />
      <Fact
        label="Source version"
        value={String(record.current_version)}
        testID="source-version"
      />
      <Fact
        label="Application lifecycle version"
        value={String(record.lifecycle_version)}
      />
      <Fact
        label="Record completeness"
        value={
          record.record_complete
            ? "Complete source fields; not a legal verification"
            : "Incomplete"
        }
      />
      {record.incomplete_reasons.length ? (
        <Fact
          label="Missing source fields"
          value={record.incomplete_reasons.join("\n")}
        />
      ) : null}
      <Fact label="Client" value={record.client_name} />
      <Fact
        label="Responsible lawyer"
        value={record.responsible_lawyer}
        testID="source-owner-name"
      />
      <Fact
        label="Responsible membership ID"
        value={record.responsible_membership_id}
        testID="source-owner-id"
      />
      <Fact label="Team" value={record.team_name} />
      <Fact
        label="Registry sync state"
        value={record.registry_sync_state}
        testID="source-registry-state"
      />
      <Fact
        label="Registry last success"
        value={record.registry_last_success_at}
      />
      <Fact
        label="Source provenance"
        value={record.provenance.join("\n") || "Not supplied"}
        testID="source-provenance"
      />
      <Fact
        label="Source record updated"
        value={record.updated_at}
        testID="source-updated"
      />
      <Fact
        label="Renewal alert state"
        value={record.source_renewal_alert_status}
      />
      <Fact label="Renewal alert time" value={record.source_renewal_alert_at} />
    </>
  );
}

function Heading({ children }: { children: ReactNode }) {
  return (
    <Text accessibilityRole="header" style={styles.title}>
      {children}
    </Text>
  );
}
function DateFact({
  label,
  value,
  testID,
  state,
}: {
  label: string;
  value: string | null;
  testID: string;
  state?: SourceDateState;
}) {
  return (
    <View style={{ gap: 4 }}>
      <Fact
        label={label}
        value={value ? displayDay(value) : null}
        testID={testID}
      />
      {state ? (
        <Text testID={`${testID}-state`} style={styles.muted}>
          {sourceDateStateLabel(state)}
        </Text>
      ) : null}
    </View>
  );
}
function Unavailable({ value }: { value: SourceUnavailable }) {
  return (
    <View
      testID="source-unavailable"
      accessibilityLiveRegion="polite"
      style={{ gap: 8 }}
    >
      <Text accessibilityRole="header" style={styles.heading}>
        Source unavailable
      </Text>
      <Text style={styles.body}>{value.message}</Text>
    </View>
  );
}
function SourceRead<T>({
  resource,
  reload,
  children,
}: {
  resource: Resource<T>;
  reload: () => void;
  children: (value: T) => ReactNode;
}) {
  if (resource.state === "loading")
    return (
      <View
        testID="source-loading"
        accessibilityLiveRegion="polite"
        style={{ gap: 12 }}
      >
        <NativeProgress />
        <Text style={styles.muted}>Loading current source</Text>
      </View>
    );
  if (resource.state === "error")
    return (
      <View testID="source-error" style={{ gap: 12 }}>
        <Text accessibilityRole="alert" style={styles.heading}>
          {resource.error.title}
        </Text>
        <Text style={styles.body}>{resource.error.message}</Text>
        <NativeButton
          label="Reload"
          testID="source-error-reload"
          onPress={reload}
          secondary
        />
      </View>
    );
  return <>{children(resource.data)}</>;
}
