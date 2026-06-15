"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Loader2, Pencil, Plus, Save, X } from "lucide-react";
import {
  createTodo,
  listTodos,
  updateTodo,
  type Todo,
  type TodoPayload,
} from "@/lib/api";

const IDEAS_AREA = "ideas";

function isIdea(todo: Todo) {
  return todo.area === IDEAS_AREA || todo.area.startsWith("idea:");
}

function titleFromText(text: string) {
  const firstLine = text.trim().split("\n").find(Boolean) ?? "Idea";
  return `${firstLine.slice(0, 80)} ${new Date().toISOString()}`;
}

export default function IdeasPage() {
  const qc = useQueryClient();
  const [newIdea, setNewIdea] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editText, setEditText] = useState("");

  const ideas = useQuery({
    queryKey: ["todos", "ideas"],
    queryFn: () => listTodos(),
    refetchInterval: 30_000,
  });

  const create = useMutation({
    mutationFn: (payload: TodoPayload & { title: string }) => createTodo(payload),
    onSuccess: () => {
      setNewIdea("");
      qc.invalidateQueries({ queryKey: ["todos"] });
    },
  });

  const update = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: TodoPayload }) => updateTodo(id, payload),
    onSuccess: () => {
      setEditingId(null);
      setEditText("");
      qc.invalidateQueries({ queryKey: ["todos"] });
    },
  });

  const savedIdeas = (ideas.data?.todos ?? []).filter(isIdea).reverse();
  const canSave = newIdea.trim().length > 0 && !create.isPending;

  function saveIdea() {
    const body = newIdea.trim();
    if (!body) return;
    create.mutate({
      title: titleFromText(body),
      area: IDEAS_AREA,
      section: "Ideas",
      status: "raw",
      body,
      actor: "operator",
    });
  }

  function startEdit(idea: Todo) {
    setEditingId(idea.id);
    setEditText(idea.body || idea.title);
  }

  function saveEdit(idea: Todo) {
    const body = editText.trim();
    if (!body) return;
    update.mutate({
      id: idea.id,
      payload: {
        title: idea.title || titleFromText(body),
        area: idea.area || IDEAS_AREA,
        section: idea.section || "Ideas",
        status: idea.status || "raw",
        body,
        actor: "operator",
      },
    });
  }

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-neutral-900">Ideas</h1>
        <p className="mt-1 text-sm text-neutral-500">Product, marketing, and GTM ideas for later.</p>
      </div>

      <section className="rounded-xl border border-neutral-200 bg-white p-4">
        <textarea
          value={newIdea}
          onChange={(event) => setNewIdea(event.target.value)}
          rows={7}
          placeholder="Write an idea..."
          className="w-full resize-y rounded-md border border-neutral-200 px-3 py-2 text-sm leading-6 outline-none focus:border-neutral-900"
        />
        <div className="mt-3 flex justify-end">
          <button
            type="button"
            onClick={saveIdea}
            disabled={!canSave}
            className="inline-flex items-center gap-2 rounded-md bg-neutral-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
          >
            {create.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
            Save
          </button>
        </div>
        {create.isError && (
          <div className="mt-3 flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            <AlertCircle className="h-4 w-4" />
            Could not save idea.
          </div>
        )}
      </section>

      <section className="rounded-xl border border-neutral-200 bg-white">
        <div className="border-b border-neutral-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-neutral-950">Saved Ideas</h2>
        </div>

        {ideas.isError ? (
          <div className="m-4 flex items-center gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            <AlertCircle className="h-4 w-4" />
            Could not load ideas.
          </div>
        ) : ideas.isLoading ? (
          <div className="flex items-center gap-2 px-4 py-10 text-sm text-neutral-500">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading ideas
          </div>
        ) : savedIdeas.length === 0 ? (
          <div className="px-4 py-10 text-sm text-neutral-500">No ideas saved yet.</div>
        ) : (
          <div className="divide-y divide-neutral-100">
            {savedIdeas.map((idea) => {
              const isEditing = editingId === idea.id;
              return (
                <article key={idea.id} className="px-4 py-4">
                  {isEditing ? (
                    <div className="space-y-3">
                      <textarea
                        value={editText}
                        onChange={(event) => setEditText(event.target.value)}
                        rows={6}
                        className="w-full resize-y rounded-md border border-neutral-200 px-3 py-2 text-sm leading-6 outline-none focus:border-neutral-900"
                      />
                      <div className="flex justify-end gap-2">
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
                          onClick={() => saveEdit(idea)}
                          disabled={update.isPending || !editText.trim()}
                          className="inline-flex items-center gap-2 rounded-md bg-neutral-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-neutral-800 disabled:opacity-60"
                        >
                          {update.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                          Save
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="grid gap-3 md:grid-cols-[1fr_auto]">
                      <p className="min-w-0 whitespace-pre-wrap text-sm leading-6 text-neutral-700">
                        {idea.body || idea.title}
                      </p>
                      <button
                        type="button"
                        onClick={() => startEdit(idea)}
                        className="inline-flex h-8 items-center justify-center gap-2 rounded-md border border-neutral-200 px-3 text-xs font-medium text-neutral-700 hover:bg-neutral-50 md:justify-start"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                        Edit
                      </button>
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
