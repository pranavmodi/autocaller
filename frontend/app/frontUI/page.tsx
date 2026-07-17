"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type React from "react";
import Link from "next/link";
import {
  CalendarDays, ChevronRight, Download, ExternalLink, Inbox, Loader2,
  Mail, Paperclip, RefreshCw, Search, UserRound,
} from "lucide-react";
import { apiUrl } from "@/lib/api";
import { cn } from "@/lib/utils";

type Tag = { id: string; name: string; highlight: string };
type Recipient = { name: string; handle: string; role: string };
type FrontInbox = { id: string; name: string; address: string; type: string; is_private: boolean };
type Conversation = { id: string; subject: string; status: string; assignee_name: string; recipient_name: string; recipient_handle: string; updated_at: string | null; front_url: string; tags: Tag[] };
type Attachment = { id: string; filename: string; content_type: string; size: number | null };
type Message = { id: string; is_inbound: boolean; created_at: string | null; author_name: string; author_handle: string; recipients: Recipient[]; text: string; body: string; blurb: string; attachments: Attachment[] };
type ConversationDetail = { conversation: Conversation; messages: Message[]; message_count: number };
type ExportStatus = { export_id?: string; status: "queued" | "running" | "completed" | "failed"; message: string; total_conversations: number; processed_conversations: number; download_url: string | null; file_size: number | null };

const conversationLimit = 15;
const isoDate = (date: Date) => date.toISOString().slice(0, 10);
const formatDate = (value: string | null) => value ? new Date(value).toLocaleString() : "";
const text = (message: Message) => (message.text || message.blurb || message.body || "").replace(/<style[\s\S]*?<\/style>|<script[\s\S]*?<\/script>|<[^>]+>/gi, " ").replace(/&nbsp;/g, " ").replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/\s+/g, " ").trim() || "(No message text)";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), { credentials: "include", ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "Unable to load Front data.");
  }
  return response.json() as Promise<T>;
}

export default function FrontUiPage() {
  const [inboxes, setInboxes] = useState<FrontInbox[]>([]);
  const [selectedInboxId, setSelectedInboxId] = useState("");
  const [inboxQuery, setInboxQuery] = useState("");
  const [conversationQuery, setConversationQuery] = useState("");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [selectedConversationId, setSelectedConversationId] = useState("");
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [loadingInboxes, setLoadingInboxes] = useState(true);
  const [loadingConversations, setLoadingConversations] = useState(false);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [from, setFrom] = useState(() => isoDate(new Date()));
  const [to, setTo] = useState(() => isoDate(new Date()));
  const [startingExport, setStartingExport] = useState(false);
  const [exportStatus, setExportStatus] = useState<ExportStatus | null>(null);
  const [error, setError] = useState("");

  const loadInboxes = useCallback(async (refresh = false) => {
    setLoadingInboxes(true);
    try {
      const data = await request<{ items: FrontInbox[] }>(`/api/front-ui/inboxes${refresh ? "?refresh=true" : ""}`);
      setInboxes(data.items);
      setSelectedInboxId((current) => current || data.items[0]?.id || "");
      setError("");
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to load Front inboxes."); }
    finally { setLoadingInboxes(false); }
  }, []);

  const loadConversations = useCallback(async (inboxId: string, options?: { append?: boolean; cursor?: string | null; refresh?: boolean }) => {
    if (!inboxId) return;
    const append = Boolean(options?.append);
    append ? setLoadingMore(true) : setLoadingConversations(true);
    try {
      const params = new URLSearchParams({ limit: String(conversationLimit) });
      if (options?.cursor) params.set("cursor", options.cursor);
      if (options?.refresh) params.set("refresh", "true");
      const data = await request<{ items: Conversation[]; next_cursor: string | null }>(`/api/front-ui/inboxes/${encodeURIComponent(inboxId)}/conversations?${params}`);
      setConversations((current) => append ? [...current, ...data.items] : data.items);
      setNextCursor(data.next_cursor);
      if (!append) { setSelectedConversationId(data.items[0]?.id || ""); setDetail(null); }
      setError("");
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to load conversations."); }
    finally { append ? setLoadingMore(false) : setLoadingConversations(false); }
  }, []);

  const loadDetail = useCallback(async (conversationId: string) => {
    if (!conversationId) return;
    setLoadingDetail(true);
    try { setDetail(await request<ConversationDetail>(`/api/front-ui/conversations/${encodeURIComponent(conversationId)}`)); setError(""); }
    catch (err) { setError(err instanceof Error ? err.message : "Unable to load conversation."); }
    finally { setLoadingDetail(false); }
  }, []);

  useEffect(() => { loadInboxes(); }, [loadInboxes]);
  useEffect(() => { setConversations([]); setNextCursor(null); setSelectedConversationId(""); setDetail(null); loadConversations(selectedInboxId); }, [loadConversations, selectedInboxId]);
  useEffect(() => { loadDetail(selectedConversationId); }, [loadDetail, selectedConversationId]);

  const selectedInbox = inboxes.find((item) => item.id === selectedInboxId);
  const visibleInboxes = useMemo(() => { const q = inboxQuery.trim().toLowerCase(); return q ? inboxes.filter((item) => `${item.name} ${item.address} ${item.id}`.toLowerCase().includes(q)) : inboxes; }, [inboxes, inboxQuery]);
  const visibleConversations = useMemo(() => { const q = conversationQuery.trim().toLowerCase(); return q ? conversations.filter((item) => `${item.subject} ${item.recipient_name} ${item.recipient_handle} ${item.id}`.toLowerCase().includes(q)) : conversations; }, [conversations, conversationQuery]);
  const exportRunning = exportStatus?.status === "queued" || exportStatus?.status === "running";

  const startExport = async () => {
    if (!selectedInboxId) return;
    setStartingExport(true);
    try {
      const started = await request<{ export_id: string; status: ExportStatus["status"]; message: string }>("/api/front-ui/exports", { method: "POST", body: JSON.stringify({ inbox_id: selectedInboxId, inbox_name: selectedInbox?.name, date_from: from, date_to: to }) });
      setExportStatus({ ...started, export_id: started.export_id, total_conversations: 0, processed_conversations: 0, download_url: null, file_size: null });
      setError("");
    } catch (err) { setError(err instanceof Error ? err.message : "Unable to start export."); }
    finally { setStartingExport(false); }
  };

  useEffect(() => {
    if (!exportStatus?.export_id || !exportRunning) return;
    const timer = window.setInterval(async () => {
      try { setExportStatus({ ...(await request<ExportStatus>(`/api/front-ui/exports/${exportStatus.export_id}`)), export_id: exportStatus.export_id }); }
      catch (err) { setError(err instanceof Error ? err.message : "Unable to check export status."); }
    }, 5000);
    return () => window.clearInterval(timer);
  }, [exportRunning, exportStatus?.export_id]);

  return <div className="mx-auto flex min-h-[calc(100dvh-5rem)] max-w-[1600px] flex-col gap-4">
    <header className="flex flex-wrap items-center gap-3">
      <div><h1 className="flex items-center gap-2 text-lg font-semibold"><Inbox className="h-5 w-5" /> frontUI</h1><p className="text-sm text-neutral-500">{selectedInbox ? `${selectedInbox.name} · ${selectedInbox.address || selectedInbox.id}` : "Read-only Front inbox workspace"}</p></div>
      <Link href="/leads" className="ml-auto inline-flex h-9 items-center gap-2 rounded-md border border-neutral-200 bg-white px-3 text-sm font-medium text-neutral-700 hover:bg-neutral-50"><UserRound className="h-4 w-4" /> Firm workspace</Link>
      <button type="button" onClick={() => { loadInboxes(true); if (selectedInboxId) loadConversations(selectedInboxId, { refresh: true }); }} disabled={loadingInboxes || loadingConversations} className="inline-flex h-9 items-center gap-2 rounded-md bg-neutral-900 px-3 text-sm font-medium text-white hover:bg-neutral-800 disabled:opacity-60"><RefreshCw className={cn("h-4 w-4", loadingInboxes || loadingConversations ? "animate-spin" : "")} /> Refresh</button>
    </header>
    {error && <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</div>}
    <section className="rounded-lg border border-neutral-200 bg-white p-4"><div className="flex flex-wrap items-end justify-between gap-4"><div><h2 className="flex items-center gap-2 text-sm font-semibold"><Download className="h-4 w-4" /> Bulk export</h2><p className="mt-1 text-xs text-neutral-500">Full conversations and attachments. Exports are serialized and paced at one Front request every two seconds; range capped at 7 days.</p></div><div className="flex flex-wrap items-end gap-3"><DateField label="From" value={from} onChange={setFrom} /><DateField label="To" value={to} onChange={setTo} /><button type="button" onClick={startExport} disabled={!selectedInboxId || startingExport || exportRunning} className="inline-flex h-9 items-center gap-2 rounded-md bg-neutral-900 px-3 text-sm font-medium text-white disabled:opacity-60">{startingExport || exportRunning ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}{exportRunning ? "Exporting" : "Export ZIP"}</button></div></div>{exportStatus && <div className="mt-3 flex flex-wrap items-center gap-3 rounded-md border border-neutral-200 bg-neutral-50 px-3 py-2 text-sm"><StatusPill status={exportStatus.status} /><span className="text-neutral-600">{exportStatus.message}{exportStatus.total_conversations > 0 ? ` (${exportStatus.processed_conversations}/${exportStatus.total_conversations})` : ""}</span>{exportStatus.status === "completed" && exportStatus.export_id && <a href={apiUrl(`/api/front-ui/exports/${exportStatus.export_id}/download`)} className="ml-auto inline-flex items-center gap-1 text-sm font-medium text-neutral-900 hover:underline">Download ZIP <Download className="h-4 w-4" /></a>}</div>}</section>
    <div className="grid min-h-0 flex-1 overflow-hidden rounded-lg border border-neutral-200 bg-white lg:grid-cols-[270px_390px_minmax(0,1fr)]">
      <aside className="border-b border-neutral-200 lg:border-b-0 lg:border-r"><PaneHeader icon={<Inbox className="h-4 w-4" />} title="Inboxes" count={visibleInboxes.length} /><SearchBox value={inboxQuery} onChange={setInboxQuery} placeholder="Search inboxes" /><div className="max-h-56 overflow-y-auto p-2 lg:max-h-none lg:h-[calc(100dvh-23rem)]">{loadingInboxes ? <Loading label="Loading inboxes" /> : visibleInboxes.map((inbox) => <button key={inbox.id} type="button" onClick={() => setSelectedInboxId(inbox.id)} disabled={loadingConversations} className={cn("mb-1 flex w-full items-center gap-3 rounded-md px-3 py-2 text-left", inbox.id === selectedInboxId ? "bg-neutral-900 text-white" : "hover:bg-neutral-50")}><Mail className="h-4 w-4 shrink-0" /><span className="min-w-0"><span className="block truncate text-sm font-medium">{inbox.name}</span><span className={cn("block truncate text-xs", inbox.id === selectedInboxId ? "text-neutral-300" : "text-neutral-500")}>{inbox.address || inbox.type || inbox.id}</span></span></button>)}</div></aside>
      <section className="border-b border-neutral-200 lg:border-b-0 lg:border-r"><PaneHeader icon={<Mail className="h-4 w-4" />} title="Conversations" count={visibleConversations.length} /><SearchBox value={conversationQuery} onChange={setConversationQuery} placeholder="Search conversations" /><div className="max-h-[38dvh] overflow-y-auto p-2 lg:max-h-none lg:h-[calc(100dvh-23rem)]">{loadingConversations ? <Loading label="Loading conversations" /> : visibleConversations.length ? visibleConversations.map((item) => <ConversationButton key={item.id} conversation={item} selected={item.id === selectedConversationId} onClick={() => setSelectedConversationId(item.id)} />) : <Empty label="No conversations found." />}{nextCursor && !conversationQuery && <button type="button" onClick={() => selectedInboxId && loadConversations(selectedInboxId, { append: true, cursor: nextCursor })} disabled={loadingMore} className="mt-2 flex h-9 w-full items-center justify-center gap-2 rounded-md border border-neutral-200 text-sm font-medium hover:bg-neutral-50">{loadingMore ? <Loader2 className="h-4 w-4 animate-spin" /> : <ChevronRight className="h-4 w-4" />}Load more</button>}</div></section>
      <section className="min-w-0 overflow-y-auto bg-neutral-50 lg:h-[calc(100dvh-23rem)]">{loadingDetail ? <Loading label="Loading conversation" /> : detail ? <ConversationView detail={detail} /> : <Empty label="Select a conversation." />}</section>
    </div>
  </div>;
}

function DateField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) { return <label className="block text-xs font-medium text-neutral-500">{label}<span className="mt-1 flex h-9 items-center gap-1 rounded-md border border-neutral-200 px-2"><CalendarDays className="h-3.5 w-3.5" /><input type="date" value={value} onChange={(event) => onChange(event.target.value)} className="bg-transparent text-sm text-neutral-900 outline-none" /></span></label>; }
function StatusPill({ status }: { status: ExportStatus["status"] }) { return <span className={cn("rounded px-2 py-0.5 text-xs font-medium", status === "completed" ? "bg-emerald-100 text-emerald-800" : status === "failed" ? "bg-rose-100 text-rose-800" : "bg-amber-100 text-amber-800")}>{status}</span>; }
function PaneHeader({ icon, title, count }: { icon: React.ReactNode; title: string; count: number }) { return <div className="flex items-center justify-between border-b border-neutral-200 px-4 py-3"><h2 className="flex items-center gap-2 text-sm font-semibold">{icon}{title}</h2><span className="rounded bg-neutral-100 px-2 py-0.5 text-xs text-neutral-600">{count}</span></div>; }
function SearchBox({ value, onChange, placeholder }: { value: string; onChange: (value: string) => void; placeholder: string }) { return <label className="flex h-11 items-center gap-2 border-b border-neutral-200 px-3 text-neutral-400"><Search className="h-4 w-4" /><input value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className="min-w-0 flex-1 bg-transparent text-sm text-neutral-900 outline-none placeholder:text-neutral-400" /></label>; }
function Loading({ label }: { label: string }) { return <div className="flex min-h-40 items-center justify-center gap-2 text-sm text-neutral-500"><Loader2 className="h-4 w-4 animate-spin" />{label}</div>; }
function Empty({ label }: { label: string }) { return <div className="flex min-h-40 items-center justify-center text-sm text-neutral-500">{label}</div>; }
function ConversationButton({ conversation, selected, onClick }: { conversation: Conversation; selected: boolean; onClick: () => void }) { return <button type="button" onClick={onClick} className={cn("mb-1 w-full rounded-md px-3 py-3 text-left", selected ? "bg-neutral-900 text-white" : "hover:bg-neutral-50")}><div className="flex items-start gap-2"><span className="min-w-0 flex-1 line-clamp-2 text-sm font-medium">{conversation.subject}</span><span className={cn("rounded px-1.5 py-0.5 text-[11px]", selected ? "bg-white/15 text-neutral-100" : "bg-neutral-100 text-neutral-500")}>{conversation.status || "open"}</span></div><div className={cn("mt-1 truncate text-xs", selected ? "text-neutral-300" : "text-neutral-500")}>{conversation.recipient_name || conversation.recipient_handle || conversation.assignee_name || conversation.id}</div><div className={cn("mt-2 flex flex-wrap gap-1 text-xs", selected ? "text-neutral-300" : "text-neutral-400")}><span>{formatDate(conversation.updated_at)}</span>{conversation.tags.slice(0, 2).map((tag) => <span key={tag.id || tag.name} className={cn("rounded px-1.5 py-0.5", selected ? "bg-white/10" : "bg-neutral-100 text-neutral-500")}>{tag.name}</span>)}</div></button>; }
function ConversationView({ detail }: { detail: ConversationDetail }) { const { conversation } = detail; return <div className="flex min-h-full flex-col"><header className="border-b border-neutral-200 bg-white px-5 py-4"><div className="flex items-start gap-3"><div className="min-w-0 flex-1"><h2 className="line-clamp-2 text-base font-semibold">{conversation.subject}</h2><div className="mt-1 flex flex-wrap gap-x-2 text-xs text-neutral-500"><span>{conversation.id}</span><span>{formatDate(conversation.updated_at)}</span><span>{conversation.recipient_handle}</span></div></div><a href={conversation.front_url} target="_blank" rel="noreferrer" className="inline-flex h-8 shrink-0 items-center gap-1 rounded-md border border-neutral-200 px-2 text-xs font-medium hover:bg-neutral-50">Open in Front <ExternalLink className="h-3.5 w-3.5" /></a></div><div className="mt-3 flex flex-wrap gap-1"><span className="rounded bg-neutral-100 px-2 py-0.5 text-xs text-neutral-600">{conversation.status || "open"}</span><span className="rounded bg-neutral-100 px-2 py-0.5 text-xs text-neutral-600">{detail.message_count} messages</span>{conversation.tags.map((tag) => <span key={tag.id || tag.name} className="rounded bg-sky-50 px-2 py-0.5 text-xs text-sky-700">{tag.name}</span>)}</div></header><div className="space-y-4 p-5">{detail.messages.map((message) => <MessageView key={message.id} message={message} />)}</div></div>; }
function MessageView({ message }: { message: Message }) { const to = message.recipients.filter((item) => item.role === "to"); const cc = message.recipients.filter((item) => item.role === "cc"); return <article className={cn("rounded-md border p-4", message.is_inbound ? "border-neutral-200 bg-white" : "ml-auto border-sky-100 bg-sky-50")}><div className="flex flex-wrap items-start justify-between gap-2"><div className="min-w-0"><div className="flex items-center gap-2 text-sm font-medium"><Mail className="h-4 w-4 text-neutral-400" /><span className="truncate">{message.author_name || message.author_handle || "Unknown sender"}</span></div>{message.author_handle && <div className="mt-0.5 truncate text-xs text-neutral-500">{message.author_handle}</div>}</div><span className="text-xs text-neutral-400">{formatDate(message.created_at)}</span></div>{(to.length > 0 || cc.length > 0) && <div className="mt-3 space-y-1 text-xs text-neutral-500">{to.length > 0 && <Recipients label="To" values={to} />}{cc.length > 0 && <Recipients label="Cc" values={cc} />}</div>}<p className="mt-4 whitespace-pre-wrap break-words text-sm leading-6 text-neutral-800">{text(message)}</p>{message.attachments.length > 0 && <div className="mt-4 flex flex-wrap gap-2">{message.attachments.map((attachment) => <a key={attachment.id || attachment.filename} href={apiUrl(`/api/front-ui/messages/${message.id}/attachments/${attachment.id}/download`)} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-neutral-200 bg-white px-2.5 py-1 text-xs text-neutral-700 hover:border-neutral-400"><Paperclip className="h-3.5 w-3.5 shrink-0" /><span className="truncate">{attachment.filename || attachment.content_type || "Attachment"}</span></a>)}</div>}</article>; }
function Recipients({ label, values }: { label: string; values: Recipient[] }) { return <div className="flex gap-2"><span className="w-5 shrink-0 font-medium uppercase text-neutral-400">{label}</span><span>{values.map((value) => value.name || value.handle).join(", ")}</span></div>; }
