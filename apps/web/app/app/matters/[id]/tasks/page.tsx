"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ClipboardList, Plus, RotateCcw, TimerReset } from "lucide-react";
import { type FormEvent, type ReactNode, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { StatusBadge } from "@/components/ui/StatusBadge";
import {
  createMatterDeadline,
  createMatterTask,
  listMatterDeadlines,
  listMatterTasks,
  updateMatterDeadline,
  updateMatterTask,
  type MatterDeadlineRecord,
  type MatterTaskRecord,
} from "@/lib/api/endpoints";
import { apiErrorMessage } from "@/lib/api/config";
import { useMatterWorkspace } from "@/lib/use-matter-workspace";

type TaskForm = {
  title: string;
  due_on: string;
  priority: MatterTaskRecord["priority"];
  owner_membership_id: string;
};

type DeadlineForm = {
  title: string;
  due_on: string;
  kind: string;
  assignee_membership_id: string;
};

const EMPTY_TASK: TaskForm = {
  title: "",
  due_on: "",
  priority: "medium",
  owner_membership_id: "",
};

const EMPTY_DEADLINE: DeadlineForm = {
  title: "",
  due_on: "",
  kind: "manual",
  assignee_membership_id: "",
};

function formatDate(value: string | null | undefined): string {
  if (!value) return "No date";
  try {
    return new Date(`${value}T00:00:00`).toLocaleDateString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return value;
  }
}

function sourceLabel(item: MatterTaskRecord | MatterDeadlineRecord): string {
  if ("source_type" in item) {
    return item.source_type === "proceeding_intelligence"
      ? "Source-backed"
      : "User-created";
  }
  if (item.source_ref_type || item.source !== "custom") return "Source-backed";
  return "User-created";
}

function cleanPayload<T extends Record<string, string>>(value: T): T {
  return Object.fromEntries(
    Object.entries(value).map(([key, raw]) => [key, raw.trim()]),
  ) as T;
}

export default function MatterTasksPage() {
  const params = useParams<{ id: string }>();
  const matterId = params.id;
  const queryClient = useQueryClient();
  const { data: workspace } = useMatterWorkspace(matterId);
  const [taskForm, setTaskForm] = useState<TaskForm>(EMPTY_TASK);
  const [deadlineForm, setDeadlineForm] = useState<DeadlineForm>(EMPTY_DEADLINE);

  const assignees = workspace?.available_assignees ?? [];
  const isDisposed = workspace?.matter.status === "disposed";
  const assigneeOptions = useMemo(
    () => assignees.filter((member) => member.is_active),
    [assignees],
  );

  const tasksQuery = useQuery({
    queryKey: ["matters", matterId, "tasks"],
    queryFn: () => listMatterTasks(matterId),
    enabled: Boolean(matterId),
  });
  const deadlinesQuery = useQuery({
    queryKey: ["matters", matterId, "deadlines"],
    queryFn: () => listMatterDeadlines(matterId),
    enabled: Boolean(matterId),
  });

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["matters", matterId, "tasks"] }),
      queryClient.invalidateQueries({ queryKey: ["matters", matterId, "deadlines"] }),
      queryClient.invalidateQueries({ queryKey: ["matters", matterId, "workspace"] }),
    ]);
  }

  const createTaskMutation = useMutation({
    mutationFn: (form: TaskForm) => {
      const payload = cleanPayload(form);
      return createMatterTask(matterId, {
        title: payload.title,
        due_on: payload.due_on || null,
        priority: payload.priority,
        owner_membership_id: payload.owner_membership_id || null,
      });
    },
    onSuccess: async () => {
      setTaskForm(EMPTY_TASK);
      await refresh();
      toast.success("Task created");
    },
    onError: (err) => toast.error(apiErrorMessage(err, "Could not create task.")),
  });

  const updateTaskMutation = useMutation({
    mutationFn: (input: { id: string; status: "todo" | "completed" }) =>
      updateMatterTask(matterId, input.id, { status: input.status }),
    onSuccess: refresh,
    onError: (err) => toast.error(apiErrorMessage(err, "Could not update task.")),
  });

  const createDeadlineMutation = useMutation({
    mutationFn: (form: DeadlineForm) => {
      const payload = cleanPayload(form);
      return createMatterDeadline(matterId, {
        source: "custom",
        kind: payload.kind || "manual",
        title: payload.title,
        due_on: payload.due_on,
        assignee_membership_id: payload.assignee_membership_id || null,
      });
    },
    onSuccess: async () => {
      setDeadlineForm(EMPTY_DEADLINE);
      await refresh();
      toast.success("Deadline created");
    },
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not create deadline.")),
  });

  const updateDeadlineMutation = useMutation({
    mutationFn: (input: { id: string; status: MatterDeadlineRecord["status"] }) =>
      updateMatterDeadline(matterId, input.id, { status: input.status }),
    onSuccess: refresh,
    onError: (err) =>
      toast.error(apiErrorMessage(err, "Could not update deadline.")),
  });

  function submitTask(event: FormEvent) {
    event.preventDefault();
    createTaskMutation.mutate(taskForm);
  }

  function submitDeadline(event: FormEvent) {
    event.preventDefault();
    createDeadlineMutation.mutate(deadlineForm);
  }

  const tasks = tasksQuery.data?.tasks ?? [];
  const deadlines = deadlinesQuery.data?.deadlines ?? [];

  return (
    <div className="grid gap-5 xl:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Tasks</CardTitle>
          <CardDescription>Open work and source-backed action items.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          {isDisposed ? (
            <p
              className="rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] px-3 py-2 text-sm text-[var(--color-mute)]"
              data-testid="disposed-task-write-guard"
            >
              This matter is disposed. Its tasks are retained as history and cannot be
              created, changed, or reopened.
            </p>
          ) : (
          <form className="grid gap-3 md:grid-cols-[1fr_10rem_9rem_auto]" onSubmit={submitTask}>
            <Field label="Task">
              <Input
                value={taskForm.title}
                onChange={(event) =>
                  setTaskForm((current) => ({ ...current, title: event.target.value }))
                }
                placeholder="Prepare reply affidavit"
                required
              />
            </Field>
            <Field label="Due">
              <Input
                type="date"
                value={taskForm.due_on}
                onChange={(event) =>
                  setTaskForm((current) => ({ ...current, due_on: event.target.value }))
                }
              />
            </Field>
            <Field label="Priority">
              <select
                className="h-10 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                value={taskForm.priority}
                onChange={(event) =>
                  setTaskForm((current) => ({
                    ...current,
                    priority: event.target.value as MatterTaskRecord["priority"],
                  }))
                }
              >
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
                <option value="urgent">Urgent</option>
              </select>
            </Field>
            <Button
              className="self-end"
              type="submit"
              disabled={createTaskMutation.isPending}
            >
              <Plus className="h-4 w-4" aria-hidden /> Add
            </Button>
            <Field label="Owner" className="md:col-span-3">
              <select
                className="h-10 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                value={taskForm.owner_membership_id}
                onChange={(event) =>
                  setTaskForm((current) => ({
                    ...current,
                    owner_membership_id: event.target.value,
                  }))
                }
              >
                <option value="">Unassigned</option>
                {assigneeOptions.map((member) => (
                  <option key={member.membership_id} value={member.membership_id}>
                    {member.full_name}
                  </option>
                ))}
              </select>
            </Field>
          </form>
          )}

          {tasksQuery.isPending ? (
            <p className="text-sm text-[var(--color-mute)]">Loading tasks...</p>
          ) : tasks.length === 0 ? (
            <EmptyState
              icon={ClipboardList}
              title="No tasks"
              description="Add the first matter task above."
            />
          ) : (
            <ul className="flex flex-col gap-3">
              {tasks.map((task) => (
                <TaskRow
                  key={task.id}
                  task={task}
                  onToggle={() =>
                    updateTaskMutation.mutate({
                      id: task.id,
                      status: task.status === "completed" ? "todo" : "completed",
                    })
                  }
                  busy={updateTaskMutation.isPending}
                />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Deadlines</CardTitle>
          <CardDescription>Manual and source-backed matter deadlines.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          {isDisposed ? (
            <p
              className="rounded-md border border-[var(--color-line)] bg-[var(--color-bg-2)] px-3 py-2 text-sm text-[var(--color-mute)]"
              data-testid="disposed-deadline-write-guard"
            >
              This matter is disposed. Its deadlines are retained as history and cannot
              be created or changed.
            </p>
          ) : (
          <form
            className="grid gap-3 md:grid-cols-[1fr_10rem_9rem_auto]"
            onSubmit={submitDeadline}
          >
            <Field label="Deadline">
              <Input
                value={deadlineForm.title}
                onChange={(event) =>
                  setDeadlineForm((current) => ({
                    ...current,
                    title: event.target.value,
                  }))
                }
                placeholder="File rejoinder"
                required
              />
            </Field>
            <Field label="Due">
              <Input
                type="date"
                value={deadlineForm.due_on}
                onChange={(event) =>
                  setDeadlineForm((current) => ({
                    ...current,
                    due_on: event.target.value,
                  }))
                }
                required
              />
            </Field>
            <Field label="Kind">
              <Input
                value={deadlineForm.kind}
                onChange={(event) =>
                  setDeadlineForm((current) => ({
                    ...current,
                    kind: event.target.value,
                  }))
                }
              />
            </Field>
            <Button
              className="self-end"
              type="submit"
              disabled={createDeadlineMutation.isPending}
            >
              <Plus className="h-4 w-4" aria-hidden /> Add
            </Button>
            <Field label="Assignee" className="md:col-span-3">
              <select
                className="h-10 rounded-md border border-[var(--color-line)] bg-white px-3 text-sm"
                value={deadlineForm.assignee_membership_id}
                onChange={(event) =>
                  setDeadlineForm((current) => ({
                    ...current,
                    assignee_membership_id: event.target.value,
                  }))
                }
              >
                <option value="">Unassigned</option>
                {assigneeOptions.map((member) => (
                  <option key={member.membership_id} value={member.membership_id}>
                    {member.full_name}
                  </option>
                ))}
              </select>
            </Field>
          </form>
          )}

          {deadlinesQuery.isPending ? (
            <p className="text-sm text-[var(--color-mute)]">Loading deadlines...</p>
          ) : deadlines.length === 0 ? (
            <EmptyState
              icon={TimerReset}
              title="No deadlines"
              description="Add the first matter deadline above."
            />
          ) : (
            <ul className="flex flex-col gap-3">
              {deadlines.map((deadline) => (
                <DeadlineRow
                  key={deadline.id}
                  deadline={deadline}
                  onToggle={() =>
                    updateDeadlineMutation.mutate({
                      id: deadline.id,
                      status: deadline.status === "done" ? "open" : "done",
                    })
                  }
                  busy={updateDeadlineMutation.isPending}
                />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function Field({
  label,
  children,
  className,
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Label className={`flex flex-col gap-1 text-xs font-medium ${className ?? ""}`}>
      <span>{label}</span>
      {children}
    </Label>
  );
}

function TaskRow({
  task,
  onToggle,
  busy,
}: {
  task: MatterTaskRecord;
  onToggle: () => void;
  busy: boolean;
}) {
  const completed = task.status === "completed";
  const cancelled = task.status === "cancelled";
  return (
    <li className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-[var(--color-ink)]">{task.title}</h3>
            <StatusBadge status={task.status} />
          </div>
          <p className="mt-1 text-xs text-[var(--color-mute)]">
            {formatDate(task.due_on)} - {task.owner_name ?? "Unassigned"} -{" "}
            {task.priority}
          </p>
          <p className="mt-1 text-xs text-[var(--color-mute-2)]">
            {sourceLabel(task)}
            {task.source_label ? ` - ${task.source_label.replaceAll("_", " ")}` : ""}
          </p>
        </div>
        {!cancelled ? (
        <Button size="sm" variant="outline" onClick={onToggle} disabled={busy}>
          {completed ? (
            <RotateCcw className="h-4 w-4" aria-hidden />
          ) : (
            <CheckCircle2 className="h-4 w-4" aria-hidden />
          )}
          {completed ? "Reopen" : "Complete"}
        </Button>
        ) : null}
      </div>
    </li>
  );
}

function DeadlineRow({
  deadline,
  onToggle,
  busy,
}: {
  deadline: MatterDeadlineRecord;
  onToggle: () => void;
  busy: boolean;
}) {
  const done = deadline.status === "done";
  const cancelled = deadline.status === "cancelled";
  return (
    <li className="rounded-lg border border-[var(--color-line)] bg-[var(--color-bg)] p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-[var(--color-ink)]">
              {deadline.title}
            </h3>
            <StatusBadge status={deadline.status} />
          </div>
          <p className="mt-1 text-xs text-[var(--color-mute)]">
            {formatDate(deadline.due_on)} - {deadline.kind}
          </p>
          <p className="mt-1 text-xs text-[var(--color-mute-2)]">
            {sourceLabel(deadline)}
            {deadline.source_ref_type ? ` - ${deadline.source_ref_type}` : ""}
          </p>
        </div>
        {!cancelled ? (
        <Button size="sm" variant="outline" onClick={onToggle} disabled={busy}>
          {done ? (
            <RotateCcw className="h-4 w-4" aria-hidden />
          ) : (
            <CheckCircle2 className="h-4 w-4" aria-hidden />
          )}
          {done ? "Reopen" : "Complete"}
        </Button>
        ) : null}
      </div>
    </li>
  );
}
