import { useRef, useState } from "react";
import { Linking, Text, View } from "react-native";
import {
  PUBLISHER_CONTACT,
  publisherEmailDraft,
} from "../domain/publisher-contact";
import type { PublisherEnquiry } from "../domain/publisher-contact";
import { NativeButton } from "./NativeControls";
import { styles } from "./theme";

export function AccountHelp({
  disabled = false,
  requestPanelPresent = false,
}: {
  disabled?: boolean;
  requestPanelPresent?: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [opening, setOpening] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const openingLease = useRef(false);

  const openEmail = async (purpose: PublisherEnquiry) => {
    if (disabled || openingLease.current) return;
    const url = publisherEmailDraft(purpose);
    openingLease.current = true;
    setOpening(true);
    setNotice(null);
    try {
      await Linking.openURL(url);
      setNotice(
        "Your email app was opened. Review and send the draft to submit your enquiry. Nothing is sent automatically.",
      );
    } catch {
      setNotice(
        `An email app could not be confirmed. You can email ${PUBLISHER_CONTACT.email} from your preferred mail service.`,
      );
    } finally {
      openingLease.current = false;
      setOpening(false);
    }
  };

  return (
    <View testID="account-help" style={{ gap: 12 }}>
      <NativeButton
        testID="account-help-toggle"
        label={expanded ? "Hide privacy and help" : "Privacy and help"}
        secondary
        disabled={disabled}
        onPress={() => setExpanded((value) => !value)}
      />
      {expanded ? (
        <View style={{ gap: 12 }}>
          <Text accessibilityRole="header" style={styles.heading}>
            Your information in this app
          </Text>
          <Text style={styles.body}>
            This app connects to the configured CaseOps service for your
            workspace. Your organization controls access to its matters,
            documents and work records.
          </Text>
          <Text style={styles.body}>
            Session credentials use your device's secure storage. Working views
            and unsaved edits are temporary. Selected files and document
            previews use private temporary copies, which are cleared when the
            operation or session ends. This app does not provide a private
            offline document library.
          </Text>
          <Text style={styles.body}>
            The app hides private content when it goes into the background and
            checks access again when you return. This is not a guarantee that
            screenshots or other device captures can always be prevented.
          </Text>
          <Text style={styles.body}>
            Signing out ends this app's session. It does not delete your account
            or your organization's records.
          </Text>
          <Text accessibilityRole="header" style={styles.heading}>
            Publisher enquiries
          </Text>
          <Text style={styles.body}>{PUBLISHER_CONTACT.name}</Text>
          <Text selectable testID="publisher-email" style={styles.body}>
            {PUBLISHER_CONTACT.email}
          </Text>
          <Text style={styles.muted}>
            For workspace access and its records, contact your organization
            administrator. For an app enquiry or an account and personal data
            deletion enquiry, you can email the publisher. Do not send
            passwords, verification codes or confidential documents.
          </Text>
          <NativeButton
            testID="publisher-app-enquiry"
            label="Email about the app"
            secondary
            disabled={disabled || opening}
            onPress={() => void openEmail("app")}
          />
          <NativeButton
            testID="publisher-deletion-request"
            label="Ask about account deletion"
            secondary
            disabled={disabled || opening}
            onPress={() => void openEmail("deletion")}
          />
          <Text style={styles.muted}>
            These buttons open an email draft. No account or document details
            are included automatically. Asking for instructions does not submit
            a deletion request in CaseOps or confirm deletion. Your organization
            needs to review its records and any retention requirements. This app{" "}
            {requestPanelPresent
              ? "can separately record a request in the account request panel when the configured service supports it. A received receipt does not confirm account deletion."
              : "does not currently record a deletion request or show its progress."}
          </Text>
          {notice ? (
            <Text
              testID="publisher-enquiry-notice"
              accessibilityLiveRegion="polite"
              style={styles.body}
            >
              {notice}
            </Text>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}
