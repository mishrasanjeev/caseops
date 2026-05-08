import { Badge } from "@/components/ui/Badge";

type OrderState = {
  order_kind?: string | null;
  is_interim_order?: boolean | null;
  stay_status?: string | null;
};

const ORDER_KIND_LABELS: Record<string, string> = {
  daily_order: "Daily order",
  interim_order: "Interim order",
  stay_order: "Stay order",
  final_judgment: "Final judgment",
  other: "Other order",
};

const STAY_LABELS: Record<string, string> = {
  granted: "Stay granted",
  continued: "Stay continued",
  modified: "Stay modified",
  vacated: "Stay vacated",
  unknown: "Stay status unknown",
};

export function OrderBadges({ order }: { order: OrderState }) {
  const orderKind = order.order_kind ?? null;
  const interim = Boolean(order.is_interim_order) || orderKind === "interim_order";
  const stayStatus = order.stay_status && order.stay_status !== "none"
    ? order.stay_status
    : null;

  if (!interim && !stayStatus && !orderKind) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {orderKind ? (
        <Badge tone="neutral" className="py-0.5">
          {ORDER_KIND_LABELS[orderKind] ?? orderKind.replaceAll("_", " ")}
        </Badge>
      ) : null}
      {interim && orderKind !== "interim_order" ? (
        <Badge tone="brand" className="py-0.5">
          Interim order
        </Badge>
      ) : null}
      {stayStatus ? (
        <Badge tone={stayStatus === "vacated" ? "neutral" : "warning"} className="py-0.5">
          {STAY_LABELS[stayStatus] ?? `Stay ${stayStatus}`}
        </Badge>
      ) : null}
    </div>
  );
}
