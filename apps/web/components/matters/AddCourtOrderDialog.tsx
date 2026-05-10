"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FilePlus, Loader2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { Textarea } from "@/components/ui/Textarea";
import { apiErrorMessage } from "@/lib/api/config";
import {
  createMatterCourtOrder,
  uploadMatterAttachment,
} from "@/lib/api/endpoints";

/**
 * AddCourtOrderDialog — BUG-032 (Hari 2026-05-09).
 *
 * The matter Hearings page Orders-on-file card had no Add-order
 * affordance; court-sync was the only path that produced
 * MatterCourtOrder rows, so the documents-page Linked-order
 * selector was effectively unavailable for any matter that hadn't
 * been court-synced. This dialog ships an explicit manual create
 * path: required metadata fields + optional file upload.
 *
 * The dialog uploads any selected file via the existing
 * `POST /api/matters/{id}/attachments` route first (so file
 * validation, ClamAV scan, storage backend, and audit stay in one
 * place), then calls `POST /api/matters/{id}/court-orders` with
 * the resulting attachment ID. On success it invalidates the
 * workspace query so the new order appears immediately on the
 * Orders-on-file card AND in the documents-page Linked-order
 * selector (both feed off `data.court_orders`).
 */
export function AddCourtOrderDialog({
  matterId,
  triggerLabel = "Add order",
  triggerSize = "sm",
  triggerVariant = "secondary",
}: {
  matterId: string;
  triggerLabel?: string;
  triggerSize?: "sm" | "md" | "lg";
  triggerVariant?: "primary" | "secondary" | "ghost" | "outline";
}): React.JSX.Element {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [orderDate, setOrderDate] = useState("");
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [orderKind, setOrderKind] = useState<
    "" | "daily_order" | "interim_order" | "stay_order" | "final_judgment" | "other"
  >("");
  const [isInterim, setIsInterim] = useState(false);
  const [stayStatus, setStayStatus] = useState<
    "" | "none" | "granted" | "continued" | "modified" | "vacated" | "unknown"
  >("");
  const [stayUntil, setStayUntil] = useState("");
  const [benchName, setBenchName] = useState("");
  const [judgeNamesRaw, setJudgeNamesRaw] = useState("");
  const [file, setFile] = useState<File | null>(null);

  function reset() {
    setOrderDate("");
    setTitle("");
    setSummary("");
    setOrderKind("");
    setIsInterim(false);
    setStayStatus("");
    setStayUntil("");
    setBenchName("");
    setJudgeNamesRaw("");
    setFile(null);
  }

  const mutation = useMutation({
    mutationFn: async () => {
      // Two-step: optional upload first, then create. Re-uses
      // existing attachment validation + ClamAV + audit pipeline.
      let orderAttachmentId: string | null = null;
      if (file) {
        const attachment = await uploadMatterAttachment({
          matterId,
          file,
          documentType: "order_judgment",
        });
        orderAttachmentId = attachment.id;
      }
      const judgeNames = judgeNamesRaw
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      return createMatterCourtOrder({
        matterId,
        order_date: orderDate,
        title: title.trim(),
        summary: summary.trim(),
        source: file ? "manual_upload" : "manual_remarks",
        order_kind: orderKind || null,
        is_interim_order: isInterim,
        stay_status: stayStatus || null,
        stay_effective_until: stayUntil || null,
        bench_name: benchName.trim() || null,
        judge_names: judgeNames.length > 0 ? judgeNames : null,
        order_attachment_id: orderAttachmentId,
      });
    },
    onSuccess: async () => {
      setOpen(false);
      reset();
      await queryClient.invalidateQueries({
        queryKey: ["matters", matterId, "workspace"],
      });
      toast.success("Court order added.");
    },
    onError: (err) => {
      toast.error(apiErrorMessage(err, "Could not add court order."));
    },
  });

  const canSubmit =
    Boolean(orderDate) &&
    title.trim().length >= 2 &&
    summary.trim().length >= 2 &&
    !mutation.isPending;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          type="button"
          size={triggerSize}
          variant={triggerVariant}
          data-testid="add-court-order-open"
        >
          <FilePlus className="h-4 w-4" aria-hidden /> {triggerLabel}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Add a court order</DialogTitle>
          <DialogDescription>
            Record an order from a hearing manually. A linked PDF is
            optional — orders without a file will still appear in the
            documents page Linked-order selector, you can attach the
            file later from the Documents tab.
          </DialogDescription>
        </DialogHeader>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (canSubmit) mutation.mutate();
          }}
          data-testid="add-court-order-form"
        >
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="order_date">Order date</Label>
              <Input
                id="order_date"
                type="date"
                required
                value={orderDate}
                onChange={(e) => setOrderDate(e.target.value)}
                data-testid="add-court-order-date"
              />
            </div>
            <div>
              <Label htmlFor="order_kind">Order kind</Label>
              <select
                id="order_kind"
                value={orderKind}
                onChange={(e) =>
                  setOrderKind(e.target.value as typeof orderKind)
                }
                className="block h-9 w-full rounded-md border border-[var(--color-line-2)] bg-white px-2 text-sm"
                data-testid="add-court-order-kind"
              >
                <option value="">Unspecified</option>
                <option value="daily_order">Daily order</option>
                <option value="interim_order">Interim order</option>
                <option value="stay_order">Stay order</option>
                <option value="final_judgment">Final judgment</option>
                <option value="other">Other</option>
              </select>
            </div>
          </div>
          <div>
            <Label htmlFor="title">Title</Label>
            <Input
              id="title"
              required
              minLength={2}
              maxLength={255}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. Stay continued — bail application"
              data-testid="add-court-order-title"
            />
          </div>
          <div>
            <Label htmlFor="summary">Summary</Label>
            <Textarea
              id="summary"
              required
              minLength={2}
              maxLength={4000}
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              rows={3}
              placeholder="Brief operative excerpt or remarks the court recorded."
              data-testid="add-court-order-summary"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="bench_name">Bench (optional)</Label>
              <Input
                id="bench_name"
                value={benchName}
                onChange={(e) => setBenchName(e.target.value)}
                placeholder="Division Bench"
                data-testid="add-court-order-bench"
              />
            </div>
            <div>
              <Label htmlFor="judge_names">Judges (optional)</Label>
              <Input
                id="judge_names"
                value={judgeNamesRaw}
                onChange={(e) => setJudgeNamesRaw(e.target.value)}
                placeholder="Comma-separated"
                data-testid="add-court-order-judges"
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input
              id="is_interim"
              type="checkbox"
              checked={isInterim}
              onChange={(e) => setIsInterim(e.target.checked)}
              data-testid="add-court-order-interim"
            />
            <Label htmlFor="is_interim">Interim order</Label>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="stay_status">Stay status</Label>
              <select
                id="stay_status"
                value={stayStatus}
                onChange={(e) =>
                  setStayStatus(e.target.value as typeof stayStatus)
                }
                className="block h-9 w-full rounded-md border border-[var(--color-line-2)] bg-white px-2 text-sm"
                data-testid="add-court-order-stay"
              >
                <option value="">Unspecified</option>
                <option value="none">None</option>
                <option value="granted">Granted</option>
                <option value="continued">Continued</option>
                <option value="modified">Modified</option>
                <option value="vacated">Vacated</option>
                <option value="unknown">Unknown</option>
              </select>
            </div>
            <div>
              <Label htmlFor="stay_until">Stay effective until</Label>
              <Input
                id="stay_until"
                type="date"
                value={stayUntil}
                onChange={(e) => setStayUntil(e.target.value)}
                data-testid="add-court-order-stay-until"
              />
            </div>
          </div>
          <div>
            <Label htmlFor="order_file">Attach order PDF (optional)</Label>
            <input
              id="order_file"
              type="file"
              accept="application/pdf"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              className="block w-full text-sm"
              data-testid="add-court-order-file"
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setOpen(false)}
              disabled={mutation.isPending}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              disabled={!canSubmit}
              data-testid="add-court-order-submit"
            >
              {mutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />{" "}
                  Adding…
                </>
              ) : (
                "Add order"
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
