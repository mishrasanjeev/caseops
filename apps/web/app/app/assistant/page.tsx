import type { Metadata } from "next";

import { WorkspaceAssistant } from "@/components/assistant/WorkspaceAssistant";

export const metadata: Metadata = {
  title: "Ask this Workspace",
  description: "Permission-scoped workspace assistance with exact record citations.",
};

export default function WorkspaceAssistantPage() {
  return <WorkspaceAssistant />;
}
