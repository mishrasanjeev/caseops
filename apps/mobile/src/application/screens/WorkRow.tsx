import { RecordRow } from "../../components/Content";
import { displayDay } from "../../domain/contracts";
import type { WorkItem } from "../../domain/contracts";

export function WorkRow({
  item,
  onPress,
}: {
  item: WorkItem;
  onPress: () => void;
}) {
  return (
    <RecordRow
      title={item.title}
      subtitle={`${item.matter.matter_code} · ${item.matter.title}`}
      meta={[
        item.kind,
        item.due_on
          ? displayDay(item.due_on)
          : item.kind === "draft"
            ? "Read-only review"
            : "No due date",
        item.status,
        item.detail,
      ]
        .filter(Boolean)
        .join(" · ")}
      onPress={onPress}
      testID={`today-item-${item.kind}-${item.id}`}
    />
  );
}
