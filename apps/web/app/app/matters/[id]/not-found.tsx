import { FolderSearch } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";

export default function MatterNotFound() {
  return (
    <EmptyState
      icon={FolderSearch}
      title="Matter not found"
      description="This matter may have been archived, renamed, or isn't one you have access to on this workspace."
      action={<Button href="/app/matters">Back to matter portfolio</Button>}
    />
  );
}
