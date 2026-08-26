"use client";

import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import {
  BookOpen,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Loader2,
  Plus,
  Search,
  Trash2,
} from "lucide-react";

import {
  createKnowledgeEntry,
  deleteKnowledgeEntry,
  listKnowledgeEntries,
  type KnowledgeEntry,
  type KnowledgeSourceType,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const SOURCE_OPTIONS: Array<{ value: KnowledgeSourceType; label: string }> = [
  { value: "linkedin", label: "LinkedIn" },
  { value: "web", label: "Web page" },
  { value: "article", label: "Article" },
  { value: "transcript", label: "Transcript" },
  { value: "note", label: "Note" },
  { value: "other", label: "Other" },
];

const fieldClass =
  "w-full rounded-md border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-900 outline-none transition focus:border-neutral-400 focus:ring-2 focus:ring-neutral-100";

export default function KnowledgePage() {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState<KnowledgeSourceType | "all">("all");
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const entries = useQuery({
    queryKey: ["knowledge", query, sourceFilter],
    queryFn: () => listKnowledgeEntries({ query, source_type: sourceFilter }),
  });
  const remove = useMutation({
    mutationFn: deleteKnowledgeEntry,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["knowledge"] }),
  });

  return (
    <div className="mx-auto max-w-[1500px] space-y-5">
      <header className="flex items-center gap-3 border-b border-neutral-200 pb-4">
        <BookOpen className="h-5 w-5 text-neutral-700" />
        <div>
          <h1 className="text-lg font-semibold text-neutral-950">Knowledge</h1>
          <p className="text-xs text-neutral-500">Captured source material for Possible OS</p>
        </div>
        <span className="ml-auto text-xs tabular-nums text-neutral-400">
          {entries.data?.count ?? 0} entries
        </span>
      </header>

      <div className="grid min-w-0 gap-6 lg:grid-cols-[380px_minmax(0,1fr)]">
        <CapturePanel onSaved={() => queryClient.invalidateQueries({ queryKey: ["knowledge"] })} />

        <section className="min-w-0">
          <div className="mb-3 flex flex-col gap-2 sm:flex-row">
            <label className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-neutral-400" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search titles, text, authors, or URLs"
                className={cn(fieldClass, "pl-9")}
              />
            </label>
            <select
              value={sourceFilter}
              onChange={(event) => setSourceFilter(event.target.value as KnowledgeSourceType | "all")}
              className={cn(fieldClass, "w-full sm:w-40")}
              aria-label="Filter by source"
            >
              <option value="all">All sources</option>
              {SOURCE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </div>

          <div className="divide-y divide-neutral-200 border-y border-neutral-200 bg-white">
            {entries.isLoading && (
              <div className="flex items-center justify-center gap-2 py-16 text-sm text-neutral-500">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading entries
              </div>
            )}
            {entries.isError && (
              <div className="py-12 text-center text-sm text-red-600">Could not load knowledge entries.</div>
            )}
            {entries.data?.entries.map((entry) => (
              <EntryRow
                key={entry.id}
                entry={entry}
                expanded={expandedId === entry.id}
                deleting={remove.isPending && remove.variables === entry.id}
                onToggle={() => setExpandedId(expandedId === entry.id ? null : entry.id)}
                onDelete={() => {
                  if (window.confirm(`Delete “${entry.title}”?`)) remove.mutate(entry.id);
                }}
              />
            ))}
            {!entries.isLoading && entries.data?.entries.length === 0 && (
              <div className="py-16 text-center text-sm text-neutral-500">
                {query || sourceFilter !== "all" ? "No matching entries." : "No knowledge captured yet."}
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function CapturePanel({ onSaved }: { onSaved: () => void }) {
  const [content, setContent] = useState("");
  const [title, setTitle] = useState("");
  const [sourceType, setSourceType] = useState<KnowledgeSourceType>("linkedin");
  const [sourceUrl, setSourceUrl] = useState("");
  const [author, setAuthor] = useState("");
  const [tags, setTags] = useState("");
  const save = useMutation({
    mutationFn: createKnowledgeEntry,
    onSuccess: () => {
      setContent("");
      setTitle("");
      setSourceUrl("");
      setAuthor("");
      setTags("");
      onSaved();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate({
      content,
      title: title.trim() || undefined,
      source_type: sourceType,
      source_url: sourceUrl.trim() || undefined,
      author: author.trim() || undefined,
      tags: tags.split(",").map((tag) => tag.trim()).filter(Boolean),
    });
  }

  return (
    <form onSubmit={submit} className="self-start border border-neutral-200 bg-white p-4 lg:sticky lg:top-4">
      <div className="mb-4 flex items-center gap-2">
        <Plus className="h-4 w-4" />
        <h2 className="text-sm font-semibold">Capture text</h2>
      </div>
      <div className="space-y-3">
        <label className="block text-xs font-medium text-neutral-600">
          Source
          <select
            value={sourceType}
            onChange={(event) => setSourceType(event.target.value as KnowledgeSourceType)}
            className={cn(fieldClass, "mt-1")}
          >
            {SOURCE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        <label className="block text-xs font-medium text-neutral-600">
          Text
          <textarea
            required
            value={content}
            onChange={(event) => setContent(event.target.value)}
            placeholder="Paste a LinkedIn post, article excerpt, transcript, or note…"
            className={cn(fieldClass, "mt-1 min-h-56 resize-y")}
          />
        </label>
        <label className="block text-xs font-medium text-neutral-600">
          Title <span className="font-normal text-neutral-400">optional</span>
          <input value={title} onChange={(event) => setTitle(event.target.value)} className={cn(fieldClass, "mt-1")} />
        </label>
        <div className="grid grid-cols-2 gap-2">
          <label className="block text-xs font-medium text-neutral-600">
            Author
            <input value={author} onChange={(event) => setAuthor(event.target.value)} className={cn(fieldClass, "mt-1")} />
          </label>
          <label className="block text-xs font-medium text-neutral-600">
            Tags
            <input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="intake, AI" className={cn(fieldClass, "mt-1")} />
          </label>
        </div>
        <label className="block text-xs font-medium text-neutral-600">
          Source URL <span className="font-normal text-neutral-400">optional</span>
          <input type="url" value={sourceUrl} onChange={(event) => setSourceUrl(event.target.value)} placeholder="https://…" className={cn(fieldClass, "mt-1")} />
        </label>
        {save.isError && <p className="text-xs text-red-600">Could not save this entry. Check the URL and try again.</p>}
        <button
          type="submit"
          disabled={!content.trim() || save.isPending}
          className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-md bg-neutral-900 px-4 text-sm font-medium text-white hover:bg-neutral-800 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
          Save entry
        </button>
      </div>
    </form>
  );
}

function EntryRow({
  entry,
  expanded,
  deleting,
  onToggle,
  onDelete,
}: {
  entry: KnowledgeEntry;
  expanded: boolean;
  deleting: boolean;
  onToggle: () => void;
  onDelete: () => void;
}) {
  const sourceLabel = SOURCE_OPTIONS.find((option) => option.value === entry.source_type)?.label ?? entry.source_type;
  return (
    <article className="min-w-0 px-4 py-3">
      <div className="flex min-w-0 items-start gap-3">
        <button type="button" onClick={onToggle} className="mt-0.5 text-neutral-400 hover:text-neutral-800" aria-label={expanded ? "Collapse entry" : "Expand entry"}>
          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </button>
        <button type="button" onClick={onToggle} className="min-w-0 flex-1 text-left">
          <h3 className="truncate text-sm font-semibold text-neutral-900">{entry.title}</h3>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-neutral-500">
            <span>{sourceLabel}</span>
            {entry.author && <span>{entry.author}</span>}
            {entry.created_at && <span>{formatDistanceToNow(new Date(entry.created_at), { addSuffix: true })}</span>}
            {!expanded && <span className="max-w-full truncate text-neutral-400">{entry.content.replace(/\s+/g, " ")}</span>}
          </div>
        </button>
        {entry.source_url && (
          <a href={entry.source_url} target="_blank" rel="noreferrer" className="p-1 text-neutral-400 hover:text-neutral-800" title="Open source">
            <ExternalLink className="h-4 w-4" />
          </a>
        )}
        <button type="button" onClick={onDelete} disabled={deleting} className="p-1 text-neutral-400 hover:text-red-600 disabled:opacity-40" title="Delete entry">
          {deleting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
        </button>
      </div>
      {expanded && (
        <div className="ml-7 mt-3 min-w-0 border-l border-neutral-200 pl-4">
          <div className="whitespace-pre-wrap break-words text-sm leading-6 text-neutral-700">{entry.content}</div>
          {entry.tags.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-1.5">
              {entry.tags.map((tag) => <span key={tag} className="rounded bg-neutral-100 px-2 py-1 text-[11px] text-neutral-600">{tag}</span>)}
            </div>
          )}
        </div>
      )}
    </article>
  );
}
