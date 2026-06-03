"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  Check,
  ExternalLink,
  Loader2,
  Pencil,
  Plus,
  RefreshCw,
  Save,
  Trash2,
  X,
} from "lucide-react";
import {
  createTodo,
  deleteTodo,
  listTodos,
  updateTodo,
  type Todo,
  type TodoPayload,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const STATUSES = [
  { value: "not_started", label: "Not Started", section: "Not Started" },
  { value: "in_progress", label: "In Progress", section: "In Progress" },
  { value: "done", label: "Done", section: "Done" },
  { value: "done_in_code", label: "Done In Code", section: "Done" },
  { value: "done_partial", label: "Done Partial", section: "Done" },
  { value: "deferred", label: "Deferred", section: "Deferred" },
] as const;

type TodoForm = {
  title: string;
  area: string;
  section: string;
  status: string;
  body: string;
  source_url: string;
};

const blankForm: TodoForm = {
  title: "",
  area: "general",
  section: "Not Started",
  status: "not_started",
  body: "",
  source_url: "",
};

function statusLabel(value: string) {
  return STATUSES.find((item) => item.value === value)?.label ?? value.replace(/_/g, " ");
}

function sectionForStatus(value: string) {
  return STATUSES.find((item) => item.value === value)?.section ?? "Not Started";
}

function todoForm(todo: Todo): TodoForm {
  return {
    title: todo.title,
    area: todo.area,
    section: todo.section,
    status: todo.status,
    body: todo.body,
    source_url: todo.source_url ?? "",
  };
}

function payloadFromForm(form: TodoForm): TodoPayload & { title: string } {
  return {
    title: form.title.trim(),
    area: form.area.trim() || "general",
    section: form.section.trim() || sectionForStatus(form.status),
    status: form.status,
    body: form.body,
    source_url: form.source_url.trim() || null,
    actor: "operator",
  };
}

function shortDate(value: string | null | undefined) {
  if (!value) return "";
  return new Date(value).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function statusTone(value: string) {
  if (value === "done") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (value.startsWith("done_")) return "border-sky-200 bg-sky-50 text-sky-700";
  if (value === "in_progress") return "border-amber-200 bg-amber-50 text-amber-700";
  if (value === "deferred") return "border-neutral-200 bg-neutral-50 text-neutral-500";
  return "border-neutral-200 bg-white text-neutral-700";
}

function TodoFields({
  form,
  onChange,
  compact = false,
}: {
  form: TodoForm;
  onChange: (next: TodoForm) => void;
  compact?: boolean;
}) {
  const update = (patch: Partial<TodoForm>) => onChange({ ...form, ...patch });

  return (
    <div className={cn("grid gap-3", compact ? "md:grid-cols-12" : "md:grid-cols-6")}>
      <label className={cn("space-y-1", compact ? "md:col-span-5" : "md:col-span-3")}>
        <span className="text-xs font-medium text-neutral-500">Title</span>
        <input
          value={form.title}
          onChange={(event) => update({ title: event.target.value })}
          className="h-9 w-full rounded-md border border-neutral-200 px-3 text-sm outline-none focus:border-neutral-900"
        />
      </label>
      <label className={cn("space-y-1", compact ? "md:col-span-2" : "md:col-span-1")}>
        <span className="text-xs font-medium text-neutral-500">Area</span>
        <input
          value={form.area}
          onChange={(event) => update({ area: event.target.value })}
          className="h-9 w-full rounded-md border border-neutral-200 px-3 text-sm outline-none focus:border-neutral-900"
        />
      </label>
      <label className={cn("space-y-1", compact ? "md:col-span-2" : "md:col-span-1")}>
        <span className="text-xs font-medium text-neutral-500">Status</span>
        <select
          value={form.status}
          onChange={(event) => {
            const status = event.target.value;
            update({ status, section: sectionForStatus(status) });
          }}
          className="h-9 w-full rounded-md border border-neutral-200 bg-white px-3 text-sm outline-none focus:border-neutral-900"
        >
          {STATUSES.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </label>
      <label className={cn("space-y-1", compact ? "md:col-span-3" : "md:col-span-1")}>
        <span className="text-xs font-medium text-neutral-500">Source URL</span>
        <input
          value={form.source_url}
          onChange={(event) => update({ source_url: event.target.value })}
          className="h-9 w-full rounded-md border border-neutral-200 px-3 text-sm outline-none focus:border-neutral-900"
        />
      </label>
      <label className="space-y-1 md:col-span-full">
        <span className="text-xs font-medium text-neutral-500">Body</span>
        <textarea
          value={form.body}
          onChange={(event) => update({ body: event.target.value })}
          rows={compact ? 5 : 4}
          className="w-full rounded-md border border-neutral-200 px-3 py-2 text-sm leading-6 outline-none focus:border-neutral-900"
        />
      </label>
    </div>
  );
}

export default function TodosPage() {
  const qc = useQueryClient();
  const [areaFilter, setAreaFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [createForm, setCreateForm] = useState<TodoForm>(blankForm);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<TodoForm>(blankForm);

  const todos = useQuery({
    queryKey: ["todos"],
    queryFn: () => listTodos(),
    refetchInterval: 30_000,
  });

  const create = useMutation({
    mutationFn: (payload: TodoPayload & { title: string }) => createTodo(payload),
    onSuccess: () => {
      setCreateForm(blankForm);
      qc.invalidateQueries({ queryKey: ["todos"] });
    },
  });

  const update = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: TodoPayload }) => updateTodo(id, payload),
    onSuccess: () => {
      setEditingId(null);
      qc.invalidateQueries({ queryKey: ["todos"] });
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) => deleteTodo(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["todos"] }),
  });

  const allTodos = todos.data?.todos ?? [];
  const areas = useMemo(
    () => Array.from(new Set(allTodos.map((todo) => todo.area))).sort(),
    [allTodos],
  );
  const visibleTodos = useMemo(
    () =>
      allTodos.filter((todo) => {
        if (areaFilter !== "all" && todo.area !== areaFilter) return false;
        if (statusFilter !== "all" && todo.status !== statusFilter) return false;
        return true;
      }),
    [allTodos, areaFilter, statusFilter],
  );
  const counts = useMemo(() => {
    return allTodos.reduce<Record<string, number>>((acc, todo) => {
      acc[todo.status] = (acc[todo.status] ?? 0) + 1;
      return acc;
    }, {});
  }, [allTodos]);

  const startEdit = (todo: Todo) => {
    setEditingId(todo.id);
    setEditForm(todoForm(todo));
  };

  const createDisabled = create.isPending || !createForm.title.trim();

  return (
    <div className="mx-auto min-w-0 max-w-[1500px] space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-semibold text-neutral-900">Todos</h1>
        <span className="text-xs text-neutral-400">DB-backed operator backlog</span>
        <button
          type="button"
          onClick={() => todos.refetch()}
          disabled={todos.isFetching}
          className="inline-flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50 disabled:opacity-60 sm:ml-auto"
        >
          {todos.isFetching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
          Refresh
        </button>
      </div>

      <section className="rounded-xl border border-neutral-200 bg-white p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="text-sm font-semibold text-neutral-950">New todo</h2>
          <button
            type="button"
            onClick={() => create.mutate(payloadFromForm(createForm))}
            disabled={createDisabled}
            className="ml-auto inline-flex items-center gap-2 rounded-md bg-neutral-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
          >
            {create.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
            Add
          </button>
        </div>
        <TodoFields form={createForm} onChange={setCreateForm} />
        {create.isError && (
          <div className="mt-3 flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            <AlertCircle className="h-4 w-4" />
            Could not add todo.
          </div>
        )}
      </section>

      <section className="rounded-xl border border-neutral-200 bg-white">
        <div className="flex flex-wrap items-center gap-2 border-b border-neutral-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-neutral-950">Backlog</h2>
          <div className="flex flex-wrap gap-1">
            {STATUSES.map((item) => (
              <button
                key={item.value}
                type="button"
                onClick={() => setStatusFilter(statusFilter === item.value ? "all" : item.value)}
                className={cn(
                  "rounded-md border px-2 py-1 text-xs font-medium",
                  statusFilter === item.value
                    ? "border-neutral-900 bg-neutral-900 text-white"
                    : "border-neutral-200 text-neutral-600 hover:bg-neutral-50",
                )}
              >
                {item.label} {counts[item.value] ?? 0}
              </button>
            ))}
          </div>
          <select
            value={areaFilter}
            onChange={(event) => setAreaFilter(event.target.value)}
            className="ml-auto h-8 rounded-md border border-neutral-200 bg-white px-2 text-xs font-medium text-neutral-700 outline-none focus:border-neutral-900"
          >
            <option value="all">All areas</option>
            {areas.map((area) => (
              <option key={area} value={area}>
                {area}
              </option>
            ))}
          </select>
        </div>

        {todos.isError ? (
          <div className="m-4 flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            <AlertCircle className="h-4 w-4" />
            Could not load todos.
          </div>
        ) : todos.isLoading ? (
          <div className="flex items-center gap-2 px-4 py-10 text-sm text-neutral-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading todos
          </div>
        ) : visibleTodos.length === 0 ? (
          <div className="px-4 py-10 text-sm text-neutral-500">No todos match the current filters.</div>
        ) : (
          <div className="divide-y divide-neutral-100">
            {visibleTodos.map((todo) => {
              const isEditing = editingId === todo.id;
              return (
                <article key={todo.id} className="px-4 py-4">
                  {isEditing ? (
                    <div className="space-y-3">
                      <TodoFields form={editForm} onChange={setEditForm} compact />
                      <div className="flex flex-wrap justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => setEditingId(null)}
                          className="inline-flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50"
                        >
                          <X className="h-3.5 w-3.5" />
                          Cancel
                        </button>
                        <button
                          type="button"
                          onClick={() => update.mutate({ id: todo.id, payload: payloadFromForm(editForm) })}
                          disabled={update.isPending || !editForm.title.trim()}
                          className="inline-flex items-center gap-2 rounded-md bg-neutral-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
                        >
                          {update.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                          Save
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="grid gap-3 lg:grid-cols-[1fr_auto]">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className={cn("rounded-md border px-2 py-0.5 text-xs font-medium", statusTone(todo.status))}>
                            {statusLabel(todo.status)}
                          </span>
                          <span className="rounded-md border border-neutral-200 px-2 py-0.5 text-xs font-medium text-neutral-500">
                            {todo.area}
                          </span>
                          {todo.source_url && (
                            <a
                              href={todo.source_url}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 text-xs font-medium text-neutral-500 hover:text-neutral-900"
                            >
                              <ExternalLink className="h-3 w-3" />
                              Source
                            </a>
                          )}
                          <span className="text-xs text-neutral-400">
                            {todo.updated_at ? `Updated ${shortDate(todo.updated_at)}` : ""}
                          </span>
                        </div>
                        <h3 className="mt-2 text-sm font-semibold text-neutral-950">{todo.title}</h3>
                        {todo.body && (
                          <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-neutral-600">{todo.body}</p>
                        )}
                      </div>
                      <div className="flex items-start gap-2 lg:justify-end">
                        {todo.status !== "done" && (
                          <button
                            type="button"
                            onClick={() =>
                              update.mutate({
                                id: todo.id,
                                payload: { status: "done", section: "Done", actor: "operator" },
                              })
                            }
                            disabled={update.isPending}
                            className="inline-flex items-center gap-2 rounded-md border border-emerald-200 px-3 py-1.5 text-xs font-medium text-emerald-700 hover:bg-emerald-50 disabled:opacity-60"
                          >
                            <Check className="h-3.5 w-3.5" />
                            Done
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => startEdit(todo)}
                          className="inline-flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-1.5 text-xs font-medium text-neutral-700 hover:bg-neutral-50"
                        >
                          <Pencil className="h-3.5 w-3.5" />
                          Edit
                        </button>
                        <button
                          type="button"
                          onClick={() => remove.mutate(todo.id)}
                          disabled={remove.isPending}
                          className="inline-flex items-center gap-2 rounded-md border border-red-200 px-3 py-1.5 text-xs font-medium text-red-700 hover:bg-red-50 disabled:opacity-60"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                          Delete
                        </button>
                      </div>
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}
